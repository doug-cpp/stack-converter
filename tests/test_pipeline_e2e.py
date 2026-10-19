"""End-to-end tests for the full LangGraph pipeline on success_case and refusal_case fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

from stackconverter.config import load_config
from stackconverter.pipeline.main_graph import run_full_pipeline
from stackconverter.schemas import VerdictType


@pytest.mark.asyncio
async def test_pipeline_e2e_success_case(tmp_path: Path) -> None:
    fixture_dir = Path(__file__).resolve().parent.parent / "fixtures" / "success_case"
    cfg = load_config(
        provider_override="fake",
        cache_dir_override=tmp_path / "cache",
        runs_dir_override=tmp_path / "runs",
    )
    verdict, metrics = await run_full_pipeline(
        source_root=fixture_dir,
        run_id="e2e_success",
        config=cfg,
    )

    assert verdict.verdict == VerdictType.RECOMMENDED
    assert metrics.total_modules == 5
    assert metrics.converted_modules == 5
    assert metrics.pending_modules == 0
    assert metrics.total_characterization_cases > 0
    assert metrics.passed_characterization_cases == metrics.total_characterization_cases

    run_dir = tmp_path / "runs" / "e2e_success"
    assert (run_dir / "graph.json").exists()
    assert (run_dir / "verdict.json").exists()
    assert (run_dir / "plan.json").exists()
    assert (run_dir / "report.md").exists()
    assert (run_dir / "output_ts" / "src" / "analytics.ts").exists()


@pytest.mark.asyncio
async def test_pipeline_e2e_refusal_case(tmp_path: Path) -> None:
    fixture_dir = Path(__file__).resolve().parent.parent / "fixtures" / "refusal_case"
    cfg = load_config(
        provider_override="fake",
        cache_dir_override=tmp_path / "cache",
        runs_dir_override=tmp_path / "runs",
    )
    verdict, metrics = await run_full_pipeline(
        source_root=fixture_dir,
        run_id="e2e_refusal",
        config=cfg,
    )

    assert verdict.verdict == VerdictType.NOT_RECOMMENDED
    assert len(verdict.blocking_evidences) >= 3
    assert metrics.converted_modules == 0

    run_dir = tmp_path / "runs" / "e2e_refusal"
    assert (run_dir / "verdict.json").exists()
    assert (run_dir / "report.md").exists()
    assert not (run_dir / "output_ts").exists()
