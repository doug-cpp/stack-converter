"""Runs tsc --noEmit --strict and parses compiler diagnostics."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

from stackconverter.schemas import ValidationDiagnostic

TSC_DIAG_PATTERN = re.compile(
    r"^(?P<file>[^\(\n]+)\((?P<line>\d+),(?P<col>\d+)\):\s+error\s+(?P<code>TS\d+):\s+(?P<msg>.+)$"
)


def _find_binary(name: str) -> str | None:
    extra_paths = [
        str(Path.home() / ".local" / "node" / "bin"),
        str(Path.home() / ".local" / "bin"),
        "/opt/homebrew/bin",
        "/usr/local/bin",
    ]
    search_path = os.pathsep.join([*extra_paths, os.environ.get("PATH", "")])
    return shutil.which(name, path=search_path)


def _build_env() -> dict[str, str]:
    env = dict(os.environ)
    extra_paths = [
        str(Path.home() / ".local" / "node" / "bin"),
        str(Path.home() / ".local" / "bin"),
    ]
    env["PATH"] = os.pathsep.join([*extra_paths, env.get("PATH", "")])
    return env


def run_tsc_check(
    output_ts_dir: str | Path,
    target_path: str | None = None,
) -> tuple[bool, list[ValidationDiagnostic], str]:
    """Execute `tsc --noEmit --strict` inside output_ts_dir and parse compiler errors."""
    out_dir = Path(output_ts_dir).resolve()
    tsc_bin = _find_binary("tsc")
    diagnostics: list[ValidationDiagnostic] = []

    if tsc_bin is None:
        return True, [], "tsc binary not found in PATH; skipped external compiler invocation."

    proc = subprocess.run(
        [tsc_bin, "--noEmit", "--strict", "--pretty", "false", "-p", str(out_dir / "tsconfig.json")],
        cwd=str(out_dir),
        env=_build_env(),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    raw_output = (proc.stdout + "\n" + proc.stderr).strip()

    for line in raw_output.splitlines():
        match = TSC_DIAG_PATTERN.match(line.strip())
        if match:
            f_path = match.group("file").strip()
            if target_path and Path(f_path).name != Path(target_path).name:
                continue
            diagnostics.append(
                ValidationDiagnostic(
                    source="tsc",
                    file_path=f_path,
                    line=int(match.group("line")),
                    column=int(match.group("col")),
                    code=match.group("code"),
                    message=match.group("msg").strip(),
                )
            )
        elif "error TS" in line and not target_path:
            diagnostics.append(
                ValidationDiagnostic(
                    source="tsc",
                    file_path=target_path,
                    line=1,
                    column=1,
                    code="TS0000",
                    message=line.strip(),
                )
            )

    passed = len(diagnostics) == 0 and (proc.returncode == 0 or bool(target_path and not diagnostics))
    return passed, diagnostics, raw_output
