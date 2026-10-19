"""Deterministic AST detector for concurrency, multiprocessing, and shared memory patterns."""

from __future__ import annotations

import ast

from stackconverter.schemas import CodeGraph, Evidence, RiskAxis, RiskLevel

HIGH_RISK_IMPORTS = {"multiprocessing", "concurrent.futures"}
HIGH_RISK_SYMBOLS = {
    "ProcessPoolExecutor",
    "Pool",
    "Process",
    "SharedMemory",
    "RawArray",
    "RawValue",
    "Queue",
}
MEDIUM_RISK_IMPORTS = {"threading", "asyncio"}


def detect_concurrency(graph: CodeGraph) -> list[Evidence]:
    """Scan module ASTs for CPU-bound multiprocessing, shared memory, and threading primitives."""
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
                    if alias.name == "multiprocessing" or alias.name.startswith("multiprocessing."):
                        counter += 1
                        lineno = getattr(node, "lineno", 1)
                        snippet = lines[lineno - 1].strip() if 1 <= lineno <= len(lines) else alias.name
                        evidences.append(
                            Evidence(
                                id=f"ev_concurrency_{counter}",
                                axis=RiskAxis.CONCURRENCY,
                                risk_level=RiskLevel.HIGH,
                                detector="concurrency",
                                file_path=mod.file_path,
                                line=lineno,
                                snippet=snippet,
                                symbol=alias.name,
                                description=f"Imports '{alias.name}' for multi-process parallelism incompatible with Node.js single-threaded event loop.",
                            )
                        )
                    elif alias.name == "threading":
                        counter += 1
                        lineno = getattr(node, "lineno", 1)
                        snippet = lines[lineno - 1].strip() if 1 <= lineno <= len(lines) else alias.name
                        evidences.append(
                            Evidence(
                                id=f"ev_concurrency_{counter}",
                                axis=RiskAxis.CONCURRENCY,
                                risk_level=RiskLevel.MEDIUM,
                                detector="concurrency",
                                file_path=mod.file_path,
                                line=lineno,
                                snippet=snippet,
                                symbol="threading",
                                description="Uses OS-level threading module; requires refactoring to async/await or worker_threads.",
                            )
                        )

            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module.startswith("multiprocessing") or node.module == "concurrent.futures":
                    imported_names = [a.name for a in node.names]
                    if any(name in HIGH_RISK_SYMBOLS for name in imported_names) or node.module.startswith(
                        "multiprocessing"
                    ):
                        counter += 1
                        lineno = getattr(node, "lineno", 1)
                        snippet = lines[lineno - 1].strip() if 1 <= lineno <= len(lines) else node.module
                        evidences.append(
                            Evidence(
                                id=f"ev_concurrency_{counter}",
                                axis=RiskAxis.CONCURRENCY,
                                risk_level=RiskLevel.HIGH,
                                detector="concurrency",
                                file_path=mod.file_path,
                                line=lineno,
                                snippet=snippet,
                                symbol=",".join(imported_names),
                                description=f"Uses multi-process/shared-memory primitives ({', '.join(imported_names)}) from '{node.module}'.",
                            )
                        )

            elif isinstance(node, ast.Call):
                func_name = ""
                if isinstance(node.func, ast.Name):
                    func_name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    func_name = node.func.attr
                if func_name in ("ProcessPoolExecutor", "Pool", "SharedMemory"):
                    counter += 1
                    lineno = getattr(node, "lineno", 1)
                    snippet = lines[lineno - 1].strip() if 1 <= lineno <= len(lines) else func_name
                    evidences.append(
                        Evidence(
                            id=f"ev_concurrency_{counter}",
                            axis=RiskAxis.PERFORMANCE,
                            risk_level=RiskLevel.HIGH,
                            detector="concurrency",
                            file_path=mod.file_path,
                            line=lineno,
                            snippet=snippet,
                            symbol=func_name,
                            description=f"Instantiates CPU-bound process pool or shared memory '{func_name}()'.",
                        )
                    )

    return evidences
