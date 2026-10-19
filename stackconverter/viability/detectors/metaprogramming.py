"""Deterministic AST detector for dynamic code execution and metaprogramming."""

from __future__ import annotations

import ast

from stackconverter.schemas import CodeGraph, Evidence, RiskAxis, RiskLevel


def detect_metaprogramming(graph: CodeGraph) -> list[Evidence]:
    """Scan module ASTs for eval, exec, compile, metaclasses, and dynamic attribute interception."""
    evidences: list[Evidence] = []
    counter = 0

    for mod in graph.module_nodes():
        if not mod.source_code or not mod.file_path:
            continue
        lines = mod.source_code.splitlines()
        tree = ast.parse(mod.source_code, filename=mod.file_path)

        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                fn = node.func.id
                if fn in ("eval", "exec", "compile"):
                    counter += 1
                    lineno = getattr(node, "lineno", 1)
                    snippet = lines[lineno - 1].strip() if 1 <= lineno <= len(lines) else fn
                    evidences.append(
                        Evidence(
                            id=f"ev_metaprogramming_{counter}",
                            axis=RiskAxis.METAPROGRAMMING,
                            risk_level=RiskLevel.HIGH,
                            detector="metaprogramming",
                            file_path=mod.file_path,
                            line=lineno,
                            snippet=snippet,
                            symbol=fn,
                            description=f"Dynamic code execution via '{fn}()' cannot be statically typed in TypeScript.",
                        )
                    )
                elif fn in ("setattr", "delattr") or (fn == "type" and len(node.args) == 3):
                    counter += 1
                    lineno = getattr(node, "lineno", 1)
                    snippet = lines[lineno - 1].strip() if 1 <= lineno <= len(lines) else fn
                    evidences.append(
                        Evidence(
                            id=f"ev_metaprogramming_{counter}",
                            axis=RiskAxis.METAPROGRAMMING,
                            risk_level=RiskLevel.MEDIUM,
                            detector="metaprogramming",
                            file_path=mod.file_path,
                            line=lineno,
                            snippet=snippet,
                            symbol=fn,
                            description=f"Dynamic runtime reflection or class synthesis via '{fn}()'.",
                        )
                    )

            elif isinstance(node, ast.FunctionDef) and node.name in (
                "__getattr__",
                "__getattribute__",
                "__setattr__",
                "__new__",
            ):
                counter += 1
                lineno = getattr(node, "lineno", 1)
                snippet = lines[lineno - 1].strip() if 1 <= lineno <= len(lines) else node.name
                evidences.append(
                    Evidence(
                        id=f"ev_metaprogramming_{counter}",
                        axis=RiskAxis.METAPROGRAMMING,
                        risk_level=RiskLevel.HIGH if node.name in ("__getattr__", "__getattribute__") else RiskLevel.MEDIUM,
                        detector="metaprogramming",
                        file_path=mod.file_path,
                        line=lineno,
                        snippet=snippet,
                        symbol=node.name,
                        description=f"Defines dynamic dunder hook '{node.name}', requiring ES6 Proxy or redesign in TypeScript.",
                    )
                )

            elif isinstance(node, ast.ClassDef):
                for kw in node.keywords:
                    if kw.arg == "metaclass":
                        counter += 1
                        lineno = getattr(node, "lineno", 1)
                        snippet = lines[lineno - 1].strip() if 1 <= lineno <= len(lines) else node.name
                        evidences.append(
                            Evidence(
                                id=f"ev_metaprogramming_{counter}",
                                axis=RiskAxis.METAPROGRAMMING,
                                risk_level=RiskLevel.HIGH,
                                detector="metaprogramming",
                                file_path=mod.file_path,
                                line=lineno,
                                snippet=snippet,
                                symbol=node.name,
                                description=f"Class '{node.name}' uses a custom Python metaclass.",
                            )
                        )

    return evidences
