"""Unit tests for the deterministic Viability Gate verdict decision table."""

from __future__ import annotations

from stackconverter.schemas import (
    Evidence,
    EvidenceJudgment,
    EvidenceScope,
    JudgmentResult,
    RiskAxis,
    RiskLevel,
    VerdictType,
)
from stackconverter.viability.verdict_rules import compute_verdict


def test_verdict_recommended_when_no_evidences() -> None:
    verdict = compute_verdict([], JudgmentResult(judgments=[]))
    assert verdict.verdict == VerdictType.RECOMMENDED
    assert len(verdict.axes) == 7
    assert verdict.blocking_evidences == []


def test_verdict_viable_with_caveats_on_peripheral_high_or_medium() -> None:
    ev = Evidence(
        id="ev_1",
        axis=RiskAxis.METAPROGRAMMING,
        risk_level=RiskLevel.HIGH,
        detector="metaprogramming",
        file_path="cli_helper.py",
        line=12,
        snippet="setattr(obj, k, v)",
        description="Dynamic setattr in CLI helper",
    )
    judgment = JudgmentResult(
        judgments=[
            EvidenceJudgment(
                evidence_id="ev_1",
                mitigation_argument="Isolated in CLI script",
                incompatibility_argument="Dynamic reflection",
                classification=EvidenceScope.PERIPHERAL,
                adjusted_risk_level=RiskLevel.HIGH,
                rationale="Peripheral CLI utility",
            )
        ]
    )
    verdict = compute_verdict([ev], judgment)
    assert verdict.verdict == VerdictType.VIABLE_WITH_CAVEATS
    assert len(verdict.caveats) == 1
    assert verdict.blocking_evidences == []


def test_verdict_not_recommended_on_central_high_risk() -> None:
    ev = Evidence(
        id="ev_1",
        axis=RiskAxis.CONCURRENCY,
        risk_level=RiskLevel.HIGH,
        detector="concurrency",
        file_path="parallel_worker.py",
        line=4,
        snippet="ProcessPoolExecutor(max_workers=4)",
        description="Multi-core CPU pool",
    )
    judgment = JudgmentResult(
        judgments=[
            EvidenceJudgment(
                evidence_id="ev_1",
                mitigation_argument="Use worker_threads",
                incompatibility_argument="CPU-bound shared memory pool",
                classification=EvidenceScope.CENTRAL,
                adjusted_risk_level=RiskLevel.HIGH,
                rationale="Core architecture relies on multi-process parallelism",
            )
        ],
        suggested_alternatives=["Go", "Rust"],
    )
    verdict = compute_verdict([ev], judgment)
    assert verdict.verdict == VerdictType.NOT_RECOMMENDED
    assert len(verdict.blocking_evidences) == 1
    assert "parallel_worker.py:4" in verdict.rationale
    assert "Go" in verdict.suggested_alternatives
