"""Runs ESLint and strict TypeScript idiom checks on generated TypeScript modules."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from stackconverter.schemas import ValidationDiagnostic
from stackconverter.validate.tsc import _build_env, _find_binary

FORBIDDEN_PATTERNS: list[tuple[re.Pattern[str], str, str]] = [
    (re.compile(r":\s*any\b"), "no-explicit-any", "Explicit 'any' type is forbidden by strict TypeScript rules."),
    (re.compile(r"\bas\s+any\b"), "no-explicit-any", "Type assertion 'as any' is forbidden."),
    (re.compile(r"@ts-ignore|@ts-expect-error"), "ban-ts-comment", "Suppressing TypeScript compiler errors is forbidden."),
    (re.compile(r"^\s*var\s+\w+"), "no-var", "Use 'const' or 'let' instead of 'var'."),
]


def run_eslint_check(
    output_ts_dir: str | Path,
    target_path: str,
) -> tuple[bool, list[ValidationDiagnostic], str]:
    """Run deterministic TypeScript lint rules and optional ESLint CLI on target_path."""
    out_dir = Path(output_ts_dir).resolve()
    ts_file = out_dir / target_path
    diagnostics: list[ValidationDiagnostic] = []
    logs: list[str] = []

    if not ts_file.exists():
        diagnostics.append(
            ValidationDiagnostic(
                source="eslint",
                file_path=target_path,
                line=1,
                column=1,
                code="file-missing",
                message=f"Generated TypeScript file not found: {target_path}",
            )
        )
        return False, diagnostics, "File missing"

    lines = ts_file.read_text(encoding="utf-8").splitlines()
    for idx, line in enumerate(lines, start=1):
        stripped = line.strip()
        if stripped.startswith("//") and "@ts-" not in stripped:
            continue
        for pattern, rule_id, message in FORBIDDEN_PATTERNS:
            if pattern.search(line):
                diagnostics.append(
                    ValidationDiagnostic(
                        source="eslint",
                        file_path=target_path,
                        line=idx,
                        column=1,
                        code=rule_id,
                        message=message,
                    )
                )
                logs.append(f"{target_path}:{idx}: [{rule_id}] {message}")

    eslint_bin = _find_binary("eslint")
    eslint_config = out_dir / "eslint.config.mjs"
    if eslint_bin and eslint_config.exists():
        proc = subprocess.run(
            [eslint_bin, "--format", "json", str(ts_file)],
            cwd=str(out_dir),
            env=_build_env(),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if proc.stdout.strip().startswith("["):
            try:
                parsed = json.loads(proc.stdout)
                for file_entry in parsed:
                    for msg in file_entry.get("messages", []):
                        if msg.get("severity", 0) >= 2:
                            diagnostics.append(
                                ValidationDiagnostic(
                                    source="eslint",
                                    file_path=target_path,
                                    line=msg.get("line", 1),
                                    column=msg.get("column", 1),
                                    code=msg.get("ruleId") or "eslint-error",
                                    message=msg.get("message", "ESLint error"),
                                )
                            )
            except json.JSONDecodeError:
                pass

    passed = len(diagnostics) == 0
    return passed, diagnostics, "\n".join(logs) if logs else "ESLint checks passed."
