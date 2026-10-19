"""Unified Dialectical Judge Agent evaluating AST evidences for architectural centrality."""

from __future__ import annotations

import json
from pathlib import Path

from stackconverter.llm.base import AgentCaller
from stackconverter.schemas import CodeGraph, Evidence, JudgmentResult, NodeDoc


async def run_dialectical_judge(
    graph: CodeGraph,
    evidences: list[Evidence],
    node_docs: dict[str, NodeDoc],
    caller: AgentCaller,
    output_path: str | Path | None = None,
) -> JudgmentResult:
    """Invoke the Dialectical Judge Agent to classify each AST evidence as central or peripheral."""
    if not evidences:
        result = JudgmentResult(
            judgments=[],
            overall_architectural_notes="No AST risk evidences detected; all modules are clean for TypeScript migration.",
            suggested_alternatives=[],
        )
    else:
        payload = {
            "modules": [m.id for m in graph.module_nodes()],
            "evidences": [e.model_dump(mode="json") for e in evidences],
            "docs_summary": {k: v.purpose for k, v in node_docs.items()},
        }
        result = await caller.call_agent("judge", payload, JudgmentResult)

    if output_path is not None:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result.model_dump(mode="json"), indent=2), encoding="utf-8")

    return result
