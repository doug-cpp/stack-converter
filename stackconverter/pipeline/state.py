"""TypedDict state definitions for the LangGraph migration pipeline."""

from __future__ import annotations

from typing import Any, TypedDict


class PipelineState(TypedDict, total=False):
    """Serializable state dictionary passed across LangGraph nodes and SQLite checkpoints."""

    run_id: str
    source_root: str
    run_dir: str
    config_dict: dict[str, Any]
    raw_graph: dict[str, Any]
    graph: dict[str, Any]
    node_docs: dict[str, dict[str, Any]]
    evidences: list[dict[str, Any]]
    judgment: dict[str, Any]
    verdict: dict[str, Any]
    plan: dict[str, Any]
    characterization: dict[str, dict[str, Any]]
    current_level: int
    converted_modules: dict[str, dict[str, Any]]
    validation_results: dict[str, dict[str, Any]]
    module_entries: list[dict[str, Any]]
    metrics: dict[str, Any]
    report_markdown: str
