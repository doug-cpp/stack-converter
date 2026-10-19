"""Unit tests for topological level sorting and cycle detection."""

from __future__ import annotations

from pathlib import Path

from stackconverter.extract.graphify_runner import run_graphify
from stackconverter.extract.normalizer import normalize_graph
from stackconverter.plan.topology import compute_topological_levels
from stackconverter.schemas import CodeGraph, Edge, EdgeType, Node, NodeType


def test_topological_levels_on_success_fixture() -> None:
    fixture_dir = Path(__file__).resolve().parent.parent / "fixtures" / "success_case"
    raw = run_graphify(fixture_dir)
    graph = normalize_graph(raw, fixture_dir)

    levels, cycles = compute_topological_levels(graph)
    assert cycles == []
    assert levels == [
        ["discounts", "tax_rules"],
        ["invoice", "pricing"],
        ["analytics"],
    ]


def test_topological_levels_collapses_cyclic_modules() -> None:
    graph = CodeGraph(
        source_root="/tmp/cyclic",
        nodes=[
            Node(id="leaf", name="leaf", node_type=NodeType.MODULE),
            Node(id="mod_a", name="mod_a", node_type=NodeType.MODULE),
            Node(id="mod_b", name="mod_b", node_type=NodeType.MODULE),
            Node(id="entry", name="entry", node_type=NodeType.MODULE),
        ],
        edges=[
            Edge(source="mod_a", target="leaf", edge_type=EdgeType.IMPORTS),
            Edge(source="mod_a", target="mod_b", edge_type=EdgeType.IMPORTS),
            Edge(source="mod_b", target="mod_a", edge_type=EdgeType.IMPORTS),
            Edge(source="entry", target="mod_a", edge_type=EdgeType.IMPORTS),
        ],
    )
    levels, cycles = compute_topological_levels(graph)
    assert len(cycles) == 1
    assert cycles[0].modules == ["mod_a", "mod_b"]
    assert levels == [
        ["leaf"],
        ["mod_a", "mod_b"],
        ["entry"],
    ]
