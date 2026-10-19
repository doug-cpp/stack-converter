"""Fixer Agent runner that repairs TypeScript code using compiler and characterization diagnostics."""

from __future__ import annotations

from pathlib import Path

from stackconverter.generate.translator import write_module_code
from stackconverter.llm.base import AgentCaller
from stackconverter.schemas import (
    CodeGraph,
    EdgeType,
    ModuleCode,
    Node,
    NodeDoc,
    ValidationDiagnostic,
)


async def fix_module_code(
    graph: CodeGraph,
    module_node: Node,
    node_doc: NodeDoc | None,
    current_code: ModuleCode,
    diagnostics: list[ValidationDiagnostic],
    converted_modules: dict[str, ModuleCode],
    attempt: int,
    caller: AgentCaller,
    output_ts_dir: str | Path,
) -> ModuleCode:
    """Invoke the Fixer Agent with compiler/oracle diagnostics and write updated code to disk."""
    neighbor_signatures: dict[str, list[str]] = {}
    for edge in graph.edges:
        if edge.source == module_node.id and edge.edge_type == EdgeType.IMPORTS:
            dep_mod = converted_modules.get(edge.target)
            if dep_mod is not None:
                neighbor_signatures[edge.target] = dep_mod.exported_signatures

    payload = {
        "module_id": module_node.id,
        "target_path": current_code.target_path,
        "attempt": attempt,
        "source_code": module_node.source_code or "",
        "node_doc": node_doc.model_dump(mode="json") if node_doc else {},
        "current_typescript_code": current_code.typescript_code,
        "diagnostics": [d.model_dump(mode="json") for d in diagnostics],
        "neighbor_ts_signatures": neighbor_signatures,
    }
    fixed_code = await caller.call_agent("fixer", payload, ModuleCode)
    write_module_code(output_ts_dir, fixed_code)
    return fixed_code
