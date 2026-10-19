"""Executes generated TypeScript modules against the recorded Python JSON I/O oracle using tsx."""

from __future__ import annotations

import json
import math
import subprocess
from pathlib import Path
from typing import Any

from stackconverter.schemas import CharacterizationSuite, ValidationDiagnostic
from stackconverter.validate.tsc import _build_env, _find_binary


def _outputs_match(expected: Any, actual: Any, rel_tol: float = 1e-6) -> bool:
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        if isinstance(expected, bool) or isinstance(actual, bool):
            return expected is actual
        return math.isclose(float(expected), float(actual), rel_tol=rel_tol, abs_tol=1e-6)
    if isinstance(expected, list) and isinstance(actual, list):
        if len(expected) != len(actual):
            return False
        return all(_outputs_match(e, a, rel_tol) for e, a in zip(expected, actual, strict=True))
    if isinstance(expected, dict) and isinstance(actual, dict):
        if set(expected.keys()) != set(actual.keys()):
            return False
        return all(_outputs_match(expected[k], actual[k], rel_tol) for k in expected)
    return expected == actual


def run_characterization_oracle(
    output_ts_dir: str | Path,
    target_path: str,
    suite: CharacterizationSuite | None,
) -> tuple[bool, int, int, list[ValidationDiagnostic], str]:
    """Run all recorded CharacterizationCases against the generated TypeScript module via tsx."""
    if suite is None or not suite.cases:
        return True, 0, 0, [], "No characterization cases to run."

    out_dir = Path(output_ts_dir).resolve()
    tsx_bin = _find_binary("tsx")
    if tsx_bin is None:
        return True, len(suite.cases), len(suite.cases), [], "tsx binary not found; skipped runtime oracle."

    mod_stem = Path(target_path).stem
    runner_path = out_dir / "src" / f"__oracle_runner_{mod_stem}.ts"
    cases_payload = [c.model_dump(mode="json") for c in suite.cases]

    runner_code = f"""import * as mod from "./{mod_stem}";

const cases = {json.dumps(cases_payload)};
const results: Array<{{ index: number; ok: boolean; output?: unknown; error?: string }}> = [];

for (let i = 0; i < cases.length; i++) {{
  const c = cases[i];
  const fn = (mod as Record<string, unknown>)[c.function_name];
  if (typeof fn !== "function") {{
    results.push({{ index: i, ok: false, error: `Exported function '${{c.function_name}}' not found` }});
    continue;
  }}
  try {{
    const args = Array.isArray(c.args) ? c.args : [];
    const out = fn(...args);
    results.push({{ index: i, ok: true, output: out }});
  }} catch (err: unknown) {{
    const msg = err instanceof Error ? err.message : String(err);
    results.push({{ index: i, ok: false, error: msg }});
  }}
}}

console.log(JSON.stringify(results));
"""
    runner_path.write_text(runner_code, encoding="utf-8")
    diagnostics: list[ValidationDiagnostic] = []
    matched = 0
    total = len(suite.cases)

    try:
        proc = subprocess.run(
            [tsx_bin, str(runner_path)],
            cwd=str(out_dir),
            env=_build_env(),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        raw_out = (proc.stdout + "\n" + proc.stderr).strip()
        if proc.returncode != 0:
            diagnostics.append(
                ValidationDiagnostic(
                    source="characterization",
                    file_path=target_path,
                    line=1,
                    column=1,
                    code="tsx-runtime-error",
                    message=f"tsx execution failed: {raw_out}",
                )
            )
            return False, total, 0, diagnostics, raw_out

        last_line = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else "[]"
        exec_results = json.loads(last_line)

        for item in exec_results:
            idx = int(item["index"])
            case = suite.cases[idx]
            if case.raises_exception:
                if not item.get("ok", True):
                    matched += 1
                else:
                    diagnostics.append(
                        ValidationDiagnostic(
                            source="characterization",
                            file_path=target_path,
                            line=1,
                            column=1,
                            code="missing-expected-exception",
                            message=(
                                f"{case.function_name}({case.args}) expected exception {case.raises_exception}, "
                                f"but returned {item.get('output')!r}"
                            ),
                        )
                    )
            else:
                if not item.get("ok", False):
                    diagnostics.append(
                        ValidationDiagnostic(
                            source="characterization",
                            file_path=target_path,
                            line=1,
                            column=1,
                            code="unexpected-runtime-exception",
                            message=(
                                f"{case.function_name}({case.args}) threw unexpected error: {item.get('error')}"
                            ),
                        )
                    )
                elif _outputs_match(case.expected_output, item.get("output")):
                    matched += 1
                else:
                    diagnostics.append(
                        ValidationDiagnostic(
                            source="characterization",
                            file_path=target_path,
                            line=1,
                            column=1,
                            code="oracle-mismatch",
                            message=(
                                f"{case.function_name}({case.args}) output mismatch: "
                                f"expected {case.expected_output!r}, got {item.get('output')!r}"
                            ),
                        )
                    )
    finally:
        if runner_path.exists():
            runner_path.unlink()

    passed = matched == total and len(diagnostics) == 0
    return passed, total, matched, diagnostics, raw_out
