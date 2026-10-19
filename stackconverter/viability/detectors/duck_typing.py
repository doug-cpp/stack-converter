"""Deterministic AST detector for missing type annotations and complex runtime duck typing."""

from __future__ import annotations

import ast

from stackconverter.schemas import CodeGraph, Evidence, RiskAxis, RiskLevel


def detect_duck_typing(graph: CodeGraph) -> list[Evidence]:
    """Scan module ASTs for untyped public functions and polymorphic runtime dispatch."""
    evidences: list[Evidence] = []
    counter = 0

    for mod in graph.module_nodes():
        if not mod.source_code or not mod.file_path:
            continue
        lines = mod.source_code.splitlines()
        tree = ast.parse(mod.source_code, filename=mod.file_path)

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_"):
                non_self_args = [a for a in node.args.args if a.arg != "self"]
                untyped_args = [a.arg for a in non_self_args if a.annotation is None]
                missing_return = node.returns is None

                if (non_self_args and len(untyped_args) == len(non_self_args)) and missing_return:
                    counter += 1
                    lineno = getattr(node, "lineno", 1)
                    snippet = lines[lineno - 1].strip() if 1 <= lineno <= len(lines) else node.name
                    evidences.append(
                        Evidence(
                            id=f"ev_typing_{counter}",
                            axis=RiskAxis.TYPING,
                            risk_level=RiskLevel.MEDIUM,
                            detector="duck_typing",
                            file_path=mod.file_path,
                            line=lineno,
                            snippet=snippet,
                            symbol=node.name,
                            description=f"Public function '{node.name}' has no parameter or return type annotations.",
                        )
                    )

            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "hasattr":
                counter += 1
                lineno = getattr(node, "lineno", 1)
                snippet = lines[lineno - 1].strip() if 1 <= lineno <= len(lines) else "hasattr"
                evidences.append(
                    Evidence(
                        id=f"ev_typing_{counter}",
                        axis=RiskAxis.TYPING,
                        risk_level=RiskLevel.LOW,
                        detector="duck_typing",
                        file_path=mod.file_path,
                        line=lineno,
                        snippet=snippet,
                        symbol="hasattr",
                        description="Runtime structural check via 'hasattr()' should be replaced with TypeScript type guards.",
                    )
                )

    return evidences
