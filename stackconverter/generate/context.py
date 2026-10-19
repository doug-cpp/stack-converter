"""Assembles translation context including NodeDoc, TypeScript rules, libmap, and neighbor TS signatures."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from stackconverter.schemas import CodeGraph, EdgeType, MigrationPlan, ModuleCode, Node, NodeDoc


def build_translation_context(
    graph: CodeGraph,
    module_node: Node,
    node_doc: NodeDoc | None,
    plan: MigrationPlan,
    converted_modules: dict[str, ModuleCode],
    rules_path: str | Path | None = None,
) -> dict[str, Any]:
    """Build the full context payload for the Translator Agent for a single module."""
    if rules_path is None:
        rules_path = Path(__file__).resolve().parent.parent.parent / "rules" / "typescript.md"
    else:
        rules_path = Path(rules_path)

    rules_text = rules_path.read_text(encoding="utf-8") if rules_path.exists() else ""

    # Gather already-converted neighbor signatures (dependencies imported by this module)
    neighbor_signatures: dict[str, list[str]] = {}
    for edge in graph.edges:
        if edge.source == module_node.id and edge.edge_type == EdgeType.IMPORTS:
            dep_mod = converted_modules.get(edge.target)
            if dep_mod is not None:
                neighbor_signatures[edge.target] = dep_mod.exported_signatures

    short_name = module_node.id.split(".")[-1]
    target_path = f"src/{short_name}.ts"

    return {
        "module_id": module_node.id,
        "file_path": module_node.file_path,
        "target_path": target_path,
        "source_code": module_node.source_code or "",
        "node_doc": node_doc.model_dump(mode="json") if node_doc else {},
        "neighbor_ts_signatures": neighbor_signatures,
        "library_mappings": [m.model_dump(mode="json") for m in plan.library_mappings],
        "typescript_rules": rules_text,
    }
