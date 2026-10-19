"""Unit tests for deterministic AST detectors across all risk axes."""

from __future__ import annotations

from pathlib import Path

from stackconverter.extract.graphify_runner import run_graphify
from stackconverter.extract.normalizer import normalize_graph
from stackconverter.schemas import RiskAxis, RiskLevel
from stackconverter.viability.detectors import run_all_detectors


def test_detectors_on_success_case_find_zero_risks() -> None:
    fixture_dir = Path(__file__).resolve().parent.parent / "fixtures" / "success_case"
    raw = run_graphify(fixture_dir)
    graph = normalize_graph(raw, fixture_dir)
    evidences = run_all_detectors(graph)
    assert evidences == []


def test_detectors_on_refusal_case_detect_high_risks() -> None:
    fixture_dir = Path(__file__).resolve().parent.parent / "fixtures" / "refusal_case"
    raw = run_graphify(fixture_dir)
    graph = normalize_graph(raw, fixture_dir)
    evidences = run_all_detectors(graph)

    assert len(evidences) >= 5
    axes_found = {e.axis for e in evidences}
    assert RiskAxis.CONCURRENCY in axes_found
    assert RiskAxis.ECOSYSTEM in axes_found
    assert RiskAxis.RUNTIME in axes_found
    assert RiskAxis.METAPROGRAMMING in axes_found
    assert all(e.line >= 1 and e.file_path for e in evidences)
    assert any(e.risk_level == RiskLevel.HIGH and e.symbol == "numpy" for e in evidences)
