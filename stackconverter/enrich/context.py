"""Context builder for node semantic enrichment."""

from __future__ import annotations

from typing import Any

from stackconverter.schemas import CodeGraph, EdgeType, Node


def build_enrichment_context(graph: CodeGraph, node: Node) -> dict[str, Any]:
    """Assemble structural and neighbor context for the Documenter Agent."""
    outgoing_targets = [
        e.target for e in graph.edges if e.source == node.id and e.edge_type == EdgeType.IMPORTS
    ]
    incoming_sources = [
        e.source for e in graph.edges if e.target == node.id and e.edge_type == EdgeType.IMPORTS
    ]
    defined_symbols = [
        e.target for e in graph.edges if e.source == node.id and e.edge_type == EdgeType.DEFINES
    ]

    return {
        "node": node.model_dump(mode="json"),
        "imported_nodes": sorted(outgoing_targets),
        "imported_by_nodes": sorted(incoming_sources),
        "defined_symbols": sorted(defined_symbols),
    }
