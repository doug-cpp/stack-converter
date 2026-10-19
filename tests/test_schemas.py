"""Unit tests for Pydantic v2 data contracts in stackconverter.schemas."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from stackconverter.schemas import (
    TARGET_STACK_REGISTRY,
    CodeGraph,
    Evidence,
    Node,
    NodeDoc,
    NodeType,
    RiskAxis,
    RiskLevel,
    ValidationResult,
    VerdictType,
    resolve_target_stack,
)


def test_code_graph_loads_mock_fixture() -> None:
    mock_path = Path(__file__).resolve().parent.parent / "fixtures" / "mocks" / "sample_graph.json"
    data = json.loads(mock_path.read_text(encoding="utf-8"))
    graph = CodeGraph.model_validate(data)
    assert len(graph.module_nodes()) == 2
    assert graph.get_node("math_utils") is not None
    assert graph.get_node("nonexistent") is None


def test_strict_model_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        Node(
            id="mod",
            name="mod",
            node_type=NodeType.MODULE,
            extra_field="not_allowed",  # type: ignore[call-arg]
        )


def test_evidence_and_node_doc_validation() -> None:
    ev = Evidence(
        id="ev_1",
        axis=RiskAxis.CONCURRENCY,
        risk_level=RiskLevel.HIGH,
        detector="concurrency",
        file_path="worker.py",
        line=10,
        snippet="ProcessPoolExecutor()",
        description="Process pool",
    )
    assert ev.axis == RiskAxis.CONCURRENCY

    doc = NodeDoc(node_id="worker", purpose="Runs background jobs")
    assert doc.error_model == "Standard exceptions"


def test_validation_result_passed_property() -> None:
    vr_pass = ValidationResult(
        module_id="tax_rules",
        attempt=1,
        tsc_passed=True,
        eslint_passed=True,
        characterization_passed=True,
    )
    assert vr_pass.passed is True

    vr_fail = ValidationResult(
        module_id="tax_rules",
        attempt=1,
        tsc_passed=True,
        eslint_passed=False,
        characterization_passed=True,
    )
    assert vr_fail.passed is False
    assert VerdictType.NOT_RECOMMENDED.value == "not_recommended"


def test_resolve_target_stack_and_catalog() -> None:
    assert "typescript-node" in TARGET_STACK_REGISTRY
    spec_default = resolve_target_stack(None)
    assert spec_default.id == "typescript-node"

    spec_alias = resolve_target_stack("typescript")
    assert spec_alias.id == "typescript-node"
    assert spec_alias.rules_path == "rules/typescript.md"

    with pytest.raises(ValueError, match="registered as 'roadmap'"):
        resolve_target_stack("rust")

    with pytest.raises(ValueError, match="Unknown target output stack"):
        resolve_target_stack("cobol")

