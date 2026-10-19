"""Documenter Agent runner that enriches module nodes and validates cited dependencies against the graph."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from stackconverter.enrich.context import build_enrichment_context
from stackconverter.llm.base import AgentCaller
from stackconverter.schemas import CodeGraph, Node, NodeDoc


def _render_node_doc_markdown(doc: NodeDoc) -> str:
    lines = [
        f"# Node Documentation: `{doc.node_id}`",
        "",
        f"**Purpose:** {doc.purpose}",
        "",
        "## Inputs",
        *[f"- {item}" for item in (doc.inputs or ["None"])],
        "",
        "## Outputs",
        *[f"- {item}" for item in (doc.outputs or ["None"])],
        "",
        "## Invariants",
        *[f"- {item}" for item in (doc.invariants or ["None"])],
        "",
        "## Side Effects",
        *[f"- {item}" for item in (doc.side_effects or ["None"])],
        "",
        "## Edge Cases",
        *[f"- {item}" for item in (doc.edge_cases or ["None"])],
        "",
        "## External Dependencies",
        *[f"- `{dep}`" for dep in (doc.external_dependencies or ["None"])],
        "",
        f"**Error Model:** {doc.error_model}",
        f"**Concurrency Model:** {doc.concurrency_model}",
        "",
    ]
    return "\n".join(lines)


def _sanitize_cited_dependencies(doc: NodeDoc, node: Node, graph: CodeGraph) -> NodeDoc:
    """Deterministically enforce that external_dependencies only cite imports present in the AST."""
    allowed = set(node.imports) | {n.id for n in graph.nodes} | {n.name for n in graph.nodes}
    verified_deps = [d for d in doc.external_dependencies if d in allowed or d.split(".")[0] in allowed]
    return doc.model_copy(update={"node_id": node.id, "external_dependencies": verified_deps})


async def enrich_graph_nodes(
    graph: CodeGraph,
    caller: AgentCaller,
    docs_dir: str | Path | None = None,
) -> dict[str, NodeDoc]:
    """Generate and persist NodeDoc artifacts for all module nodes in the graph."""
    modules = graph.module_nodes()
    out_dir = Path(docs_dir) if docs_dir else None
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)

    async def _doc_one(mod: Node) -> tuple[str, NodeDoc]:
        payload = build_enrichment_context(graph, mod)
        raw_doc = await caller.call_agent("documenter", payload, NodeDoc)
        clean_doc = _sanitize_cited_dependencies(raw_doc, mod, graph)
        if out_dir:
            safe_name = mod.id.replace(".", "_").replace(":", "_")
            (out_dir / f"{safe_name}.json").write_text(
                json.dumps(clean_doc.model_dump(mode="json"), indent=2),
                encoding="utf-8",
            )
            (out_dir / f"{safe_name}.md").write_text(
                _render_node_doc_markdown(clean_doc),
                encoding="utf-8",
            )
        return mod.id, clean_doc

    results = await asyncio.gather(*[_doc_one(m) for m in modules])
    return dict(results)
