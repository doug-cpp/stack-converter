"""Unit tests for graphify_runner and AST normalizer."""

from __future__ import annotations

from pathlib import Path

from stackconverter.extract.graphify_runner import run_graphify
from stackconverter.extract.normalizer import normalize_graph
from stackconverter.schemas import NodeType


def test_extract_and_normalize_success_fixture(tmp_path: Path) -> None:
    fixture_dir = Path(__file__).resolve().parent.parent / "fixtures" / "success_case"
    raw_out = tmp_path / "raw_graph.json"
    norm_out = tmp_path / "graph.json"

    raw = run_graphify(fixture_dir, output_path=raw_out)
    assert raw_out.exists()

    graph = normalize_graph(raw, fixture_dir, output_path=norm_out)
    assert norm_out.exists()

    mod_ids = [m.id for m in graph.module_nodes()]
    assert mod_ids == ["analytics", "discounts", "invoice", "pricing", "tax_rules"]

    fn_node = graph.get_node("tax_rules:calculate_tax")
    assert fn_node is not None
    assert fn_node.node_type == NodeType.FUNCTION
    assert fn_node.return_annotation == "float"
    assert len(fn_node.parameters) == 2
