"""Deterministic AST detectors for the 7 Viability Gate axes."""

from __future__ import annotations

from pathlib import Path

from stackconverter.schemas import CodeGraph, Evidence
from stackconverter.viability.detectors.concurrency import detect_concurrency
from stackconverter.viability.detectors.duck_typing import detect_duck_typing
from stackconverter.viability.detectors.ecosystem import detect_ecosystem
from stackconverter.viability.detectors.metaprogramming import detect_metaprogramming
from stackconverter.viability.detectors.runtime import detect_runtime


def run_all_detectors(
    graph: CodeGraph,
    libmap_path: str | Path | None = None,
) -> list[Evidence]:
    """Execute all deterministic AST detectors across the codebase graph."""
    evidences: list[Evidence] = []
    evidences.extend(detect_concurrency(graph))
    evidences.extend(detect_metaprogramming(graph))
    evidences.extend(detect_duck_typing(graph))
    evidences.extend(detect_ecosystem(graph, libmap_path=libmap_path))
    evidences.extend(detect_runtime(graph))
    return sorted(evidences, key=lambda e: (e.file_path, e.line, e.id))


__all__ = [
    "detect_concurrency",
    "detect_duck_typing",
    "detect_ecosystem",
    "detect_metaprogramming",
    "detect_runtime",
    "run_all_detectors",
]
