"""SHA-256 disk cache manager for LLM structured responses."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


class DiskCache:
    """Deterministic SHA-256 JSON disk cache for LLM calls."""

    def __init__(self, cache_dir: str | Path, fallback_dirs: list[str | Path] | None = None) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.fallback_dirs = [Path(d) for d in (fallback_dirs or [])]
        self.hits = 0
        self.misses = 0

    @staticmethod
    def compute_key(
        role: str,
        prompt_version: str,
        model_name: str,
        payload: dict[str, Any],
        schema_name: str,
    ) -> str:
        """Compute a canonical SHA-256 hash key for an agent invocation."""
        canonical = json.dumps(
            {
                "role": role,
                "prompt_version": prompt_version,
                "model_name": model_name,
                "schema_name": schema_name,
                "payload": payload,
            },
            sort_keys=True,
            ensure_ascii=True,
            default=str,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def get(self, key: str) -> dict[str, Any] | None:
        """Retrieve a cached response dictionary by SHA-256 key, checking fallback dirs."""
        search_dirs = [self.cache_dir, *self.fallback_dirs]
        for directory in search_dirs:
            path = directory / f"{key}.json"
            if path.exists():
                with path.open("r", encoding="utf-8") as f:
                    record = json.load(f)
                self.hits += 1
                return record.get("response")
        self.misses += 1
        return None

    def set(self, key: str, metadata: dict[str, Any], response: dict[str, Any]) -> Path:
        """Persist a validated response dictionary under its SHA-256 key."""
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path = self.cache_dir / f"{key}.json"
        record = {
            "key": key,
            "metadata": metadata,
            "response": response,
        }
        with path.open("w", encoding="utf-8") as f:
            json.dump(record, f, indent=2, sort_keys=True)
        return path
