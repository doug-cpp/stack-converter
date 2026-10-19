"""Deterministic AST detector for CPython runtime internals, ctypes/FFI, and memory layout."""

from __future__ import annotations

import ast

from stackconverter.schemas import CodeGraph, Evidence, RiskAxis, RiskLevel

LOW_LEVEL_MODULES = {"ctypes", "cffi", "mmap", "gc", "resource", "fcntl"}


def detect_runtime(graph: CodeGraph) -> list[Evidence]:
    """Scan module ASTs for CPython internals, native C FFI (ctypes/cffi), and raw memory buffers."""
    evidences: list[Evidence] = []
    counter = 0

    for mod in graph.module_nodes():
        if not mod.source_code or not mod.file_path:
            continue
        lines = mod.source_code.splitlines()
        tree = ast.parse(mod.source_code, filename=mod.file_path)

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root_pkg = alias.name.split(".")[0]
                    if root_pkg in LOW_LEVEL_MODULES:
                        counter += 1
                        lineno = getattr(node, "lineno", 1)
                        snippet = lines[lineno - 1].strip() if 1 <= lineno <= len(lines) else alias.name
                        axis = RiskAxis.MEMORY if root_pkg in ("mmap", "gc") else RiskAxis.RUNTIME
                        evidences.append(
                            Evidence(
                                id=f"ev_runtime_{counter}",
                                axis=axis,
                                risk_level=RiskLevel.HIGH,
                                detector="runtime",
                                file_path=mod.file_path,
                                line=lineno,
                                snippet=snippet,
                                symbol=root_pkg,
                                description=f"Low-level runtime/memory dependency '{root_pkg}' cannot be directly translated to TypeScript.",
                            )
                        )
            elif isinstance(node, ast.ImportFrom) and node.module:
                root_pkg = node.module.split(".")[0]
                if root_pkg in LOW_LEVEL_MODULES:
                    counter += 1
                    lineno = getattr(node, "lineno", 1)
                    snippet = lines[lineno - 1].strip() if 1 <= lineno <= len(lines) else node.module
                    axis = RiskAxis.MEMORY if root_pkg in ("mmap", "gc") else RiskAxis.RUNTIME
                    evidences.append(
                        Evidence(
                            id=f"ev_runtime_{counter}",
                            axis=axis,
                            risk_level=RiskLevel.HIGH,
                            detector="runtime",
                            file_path=mod.file_path,
                            line=lineno,
                            snippet=snippet,
                            symbol=root_pkg,
                            description=f"Imports low-level runtime/memory module '{node.module}'.",
                        )
                    )
            elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                if node.value.id == "sys" and node.attr in ("_getframe", "settrace", "setprofile", "getrefcount"):
                    counter += 1
                    lineno = getattr(node, "lineno", 1)
                    snippet = lines[lineno - 1].strip() if 1 <= lineno <= len(lines) else f"sys.{node.attr}"
                    evidences.append(
                        Evidence(
                            id=f"ev_runtime_{counter}",
                            axis=RiskAxis.RUNTIME,
                            risk_level=RiskLevel.HIGH,
                            detector="runtime",
                            file_path=mod.file_path,
                            line=lineno,
                            snippet=snippet,
                            symbol=f"sys.{node.attr}",
                            description=f"Depends on CPython-specific runtime hook 'sys.{node.attr}'.",
                        )
                    )

    return evidences
