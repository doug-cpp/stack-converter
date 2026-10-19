"""Deterministic decision table for the Viability Gate across all 7 evaluation axes."""

from __future__ import annotations

import json
from pathlib import Path

from stackconverter.schemas import (
    AxisAssessment,
    Evidence,
    EvidenceJudgment,
    EvidenceScope,
    JudgmentResult,
    RiskAxis,
    RiskLevel,
    Verdict,
    VerdictType,
)

RISK_PRIORITY = {
    RiskLevel.LOW: 0,
    RiskLevel.MEDIUM: 1,
    RiskLevel.HIGH: 2,
}


def compute_verdict(
    evidences: list[Evidence],
    judgment_result: JudgmentResult,
    output_path: str | Path | None = None,
) -> Verdict:
    """Compute the final migration Verdict deterministically from AST evidences and Judge classifications."""
    judgment_by_id: dict[str, EvidenceJudgment] = {
        j.evidence_id: j for j in judgment_result.judgments
    }

    axis_Assessments: list[AxisAssessment] = []
    blocking_evidences: list[Evidence] = []
    caveats: list[str] = []

    for axis in RiskAxis:
        axis_evs = [e for e in evidences if e.axis == axis]
        if not axis_evs:
            axis_Assessments.append(
                AxisAssessment(
                    axis=axis,
                    risk_level=RiskLevel.LOW,
                    has_central_high_risk=False,
                    evidences=[],
                    summary=f"No risk patterns detected on the {axis.value} axis.",
                )
            )
            continue

        max_risk = RiskLevel.LOW
        has_central_high = False

        for ev in axis_evs:
            j = judgment_by_id.get(ev.id)
            effective_risk = j.adjusted_risk_level if j is not None else ev.risk_level
            scope = j.classification if j is not None else EvidenceScope.CENTRAL

            if RISK_PRIORITY[effective_risk] > RISK_PRIORITY[max_risk]:
                max_risk = effective_risk

            if effective_risk == RiskLevel.HIGH and scope == EvidenceScope.CENTRAL:
                has_central_high = True
                blocking_evidences.append(ev)
            elif effective_risk in (RiskLevel.MEDIUM, RiskLevel.HIGH):
                caveats.append(
                    f"[{axis.value}] {ev.file_path}:{ev.line} ({scope.value}, {effective_risk.value}): {ev.description}"
                )

        summary = (
            f"Detected {len(axis_evs)} finding(s) on {axis.value}; highest risk is {max_risk.value}"
            + (" (CENTRAL blocking pattern)." if has_central_high else ".")
        )
        axis_Assessments.append(
            AxisAssessment(
                axis=axis,
                risk_level=max_risk,
                has_central_high_risk=has_central_high,
                evidences=[e.id for e in axis_evs],
                summary=summary,
            )
        )

    if any(a.has_central_high_risk for a in axis_Assessments):
        verdict_type = VerdictType.NOT_RECOMMENDED
        citations = ", ".join(f"{e.file_path}:{e.line}" for e in blocking_evidences)
        rationale = (
            f"Migration to TypeScript/Node.js is NOT RECOMMENDED due to central high-risk architectural "
            f"incompatibilities at: {citations}."
        )
        alternatives = judgment_result.suggested_alternatives or [
            "Go (native multi-core concurrency and compiled performance)",
            "Rust (SIMD/ndarray ecosystem and zero-cost memory layout)",
        ]
    elif any(a.risk_level in (RiskLevel.MEDIUM, RiskLevel.HIGH) for a in axis_Assessments):
        verdict_type = VerdictType.VIABLE_WITH_CAVEATS
        rationale = (
            "Migration is VIABLE WITH CAVEATS: medium or peripheral high-risk patterns were found and "
            "logged as technical debt items."
        )
        alternatives = []
    else:
        verdict_type = VerdictType.RECOMMENDED
        rationale = "Migration is RECOMMENDED: all 7 viability axes indicate low risk."
        alternatives = []

    verdict = Verdict(
        verdict=verdict_type,
        axes=axis_Assessments,
        blocking_evidences=blocking_evidences,
        caveats=caveats,
        rationale=rationale,
        suggested_alternatives=alternatives,
    )

    if output_path is not None:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(verdict.model_dump(mode="json"), indent=2), encoding="utf-8")

    return verdict
