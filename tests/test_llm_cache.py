"""Unit tests for SHA-256 DiskCache and AgentCaller retry/cache behavior."""

from __future__ import annotations

from pathlib import Path

import pytest

from stackconverter.config import AppConfig
from stackconverter.llm.base import AgentCaller
from stackconverter.llm.cache import DiskCache
from stackconverter.schemas import NodeDoc


def test_disk_cache_deterministic_key_and_persistence(tmp_path: Path) -> None:
    cache = DiskCache(tmp_path / "cache")
    k1 = cache.compute_key("documenter", "1.0", "fake-v1", {"b": 2, "a": 1}, "NodeDoc")
    k2 = cache.compute_key("documenter", "1.0", "fake-v1", {"a": 1, "b": 2}, "NodeDoc")
    assert k1 == k2

    assert cache.get(k1) is None
    assert cache.misses == 1

    cache.set(k1, {"role": "documenter"}, {"node_id": "m1", "purpose": "test"})
    hit = cache.get(k1)
    assert hit is not None
    assert hit["node_id"] == "m1"
    assert cache.hits == 1


@pytest.mark.asyncio
async def test_agent_caller_uses_cache_on_second_call(tmp_path: Path) -> None:
    cfg = AppConfig(default_provider="fake")
    cache = DiskCache(tmp_path / "cache")
    caller = AgentCaller(config=cfg, cache=cache)

    payload = {
        "node": {
            "id": "tax_rules",
            "name": "tax_rules",
            "docstring": "Tax calculation utilities.",
            "imports": [],
            "parameters": [],
        }
    }
    doc1 = await caller.call_agent("documenter", payload, NodeDoc)
    assert caller.llm_calls == 1
    assert cache.hits == 0

    doc2 = await caller.call_agent("documenter", payload, NodeDoc)
    assert caller.llm_calls == 1
    assert cache.hits == 1
    assert doc1 == doc2
