"""Deterministic AST detector for unmapped or unsupported third-party Python libraries."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import yaml

from stackconverter.schemas import CodeGraph, Evidence, RiskAxis, RiskLevel


def _load_libmap_catalog(libmap_path: str | Path | None) -> tuple[set[str], set[str], dict[str, str]]:
    if libmap_path is None:
        libmap_path = Path(__file__).resolve().parent.parent.parent.parent / "libmap" / "python_to_ts.yaml"
    else:
        libmap_path = Path(libmap_path)

    supported: set[str] = set(sys.stdlib_module_names) - {"multiprocessing", "ctypes"}
    unsupported: set[str] = {"numpy", "pandas", "scipy", "torch", "tensorflow", "multiprocessing"}
    notes_map: dict[str, str] = {}

    if libmap_path.exists():
        data = yaml.safe_load(libmap_path.read_text(encoding="utf-8")) or {}
        for pkg, info in (data.get("stdlib") or {}).items():
            supported.add(pkg)
            if isinstance(info, dict) and info.get("notes"):
                notes_map[pkg] = str(info["notes"])
        for pkg, info in (data.get("third_party") or {}).items():
            supported.add(pkg)
            if isinstance(info, dict) and info.get("notes"):
                notes_map[pkg] = str(info["notes"])
        for pkg, info in (data.get("unsupported") or {}).items():
            unsupported.add(pkg)
            supported.discard(pkg)
            if isinstance(info, dict) and info.get("notes"):
                notes_map[pkg] = str(info["notes"])

    return supported, unsupported, notes_map


def detect_ecosystem(
    graph: CodeGraph,
    libmap_path: str | Path | None = None,
) -> list[Evidence]:
    """Cross-reference all imports against internal modules and libmap/python_to_ts.yaml."""
    supported, unsupported, notes_map = _load_libmap_catalog(libmap_path)
    internal_names = {m.id.split(".")[0] for m in graph.module_nodes()} | {
        m.name for m in graph.module_nodes()
    }

    evidences: list[Evidence] = []
    counter = 0

    for mod in graph.module_nodes():
        if not mod.source_code or not mod.file_path:
            continue
        lines = mod.source_code.splitlines()
        tree = ast.parse(mod.source_code, filename=mod.file_path)

        for node in ast.walk(tree):
            imported_roots: list[tuple[str, int]] = []
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported_roots.append((alias.name.split(".")[0], getattr(node, "lineno", 1)))
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                if node.module != "__future__":
                    imported_roots.append((node.module.split(".")[0], getattr(node, "lineno", 1)))

            for pkg, lineno in imported_roots:
                if pkg in internal_names or pkg == "multiprocessing":
                    # multiprocessing is already covered by concurrency detector
                    continue
                snippet = lines[lineno - 1].strip() if 1 <= lineno <= len(lines) else f"import {pkg}"
                if pkg in unsupported:
                    counter += 1
                    reason = notes_map.get(
                        pkg,
                        f"Library '{pkg}' relies on native C/Fortran extensions without a mature TypeScript equivalent.",
                    )
                    evidences.append(
                        Evidence(
                            id=f"ev_ecosystem_{counter}",
                            axis=RiskAxis.ECOSYSTEM,
                            risk_level=RiskLevel.HIGH,
                            detector="ecosystem",
                            file_path=mod.file_path,
                            line=lineno,
                            snippet=snippet,
                            symbol=pkg,
                            description=f"Unsupported dependency '{pkg}': {reason}",
                        )
                    )
                elif pkg not in supported:
                    counter += 1
                    evidences.append(
                        Evidence(
                            id=f"ev_ecosystem_{counter}",
                            axis=RiskAxis.ECOSYSTEM,
                            risk_level=RiskLevel.MEDIUM,
                            detector="ecosystem",
                            file_path=mod.file_path,
                            line=lineno,
                            snippet=snippet,
                            symbol=pkg,
                            description=f"External dependency '{pkg}' is not mapped in libmap/python_to_ts.yaml.",
                        )
                    )

    return evidences
