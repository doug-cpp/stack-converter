"""Configuration and environment loader for StackConverter."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

ProviderName = Literal["fake", "gemini_api", "claude_subscription"]


class ModelsConfig(BaseModel):
    """Model identifiers per provider."""

    gemini_api: str = "gemini-2.5-pro"
    claude_subscription: str = "claude-sonnet-4-5"
    fake: str = "fake-deterministic-v1"


class ConcurrencyConfig(BaseModel):
    """Max concurrent LLM requests per provider."""

    gemini_api: int = 5
    claude_subscription: int = 2
    fake: int = 16


class RoleProvidersConfig(BaseModel):
    """Optional per-role provider overrides."""

    documenter: ProviderName | None = None
    judge: ProviderName | None = None
    characterizer: ProviderName | None = None
    translator: ProviderName | None = None
    fixer: ProviderName | None = None


class PathsConfig(BaseModel):
    """Configurable filesystem paths relative to repository root."""

    cache_dir: str = "cache"
    demo_cache_dir: str = "demo_cache"
    runs_dir: str = "runs"
    libmap_path: str = "libmap/python_to_ts.yaml"
    rules_path: str = "rules/typescript.md"


class ValidationConfig(BaseModel):
    """Validation loop settings."""

    max_fix_attempts: int = 3
    run_tsc: bool = True
    run_eslint: bool = True
    run_characterization: bool = True


class AppConfig(BaseModel):
    """Top-level application configuration."""

    default_provider: ProviderName = "fake"
    default_source_stack: str = "python"
    default_target_stack: str = "typescript-node"
    models: ModelsConfig = Field(default_factory=ModelsConfig)
    concurrency: ConcurrencyConfig = Field(default_factory=ConcurrencyConfig)
    role_providers: RoleProvidersConfig = Field(default_factory=RoleProvidersConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)
    validation: ValidationConfig = Field(default_factory=ValidationConfig)
    project_root: Path = Field(default_factory=lambda: Path(__file__).resolve().parent.parent)

    def get_provider_for_role(self, role: str) -> ProviderName:
        """Return the configured provider name for a specific agent role."""
        override = getattr(self.role_providers, role, None)
        return override or self.default_provider

    def resolve_path(self, relative_or_abs: str | Path) -> Path:
        """Resolve a path relative to the code repository root."""
        p = Path(relative_or_abs)
        if p.is_absolute():
            return p
        return (self.project_root / p).resolve()


def load_config(
    config_path: str | Path | None = None,
    provider_override: ProviderName | None = None,
    cache_dir_override: str | Path | None = None,
    runs_dir_override: str | Path | None = None,
    target_stack_override: str | None = None,
) -> AppConfig:
    """Load .env and config.yaml (falling back to config.example.yaml or defaults)."""
    from stackconverter.schemas import resolve_target_stack

    project_root = Path(__file__).resolve().parent.parent
    load_dotenv(project_root / ".env", override=False)

    env_config = os.getenv("STACKCONVERTER_CONFIG")
    candidate_paths: list[Path] = []
    if config_path:
        candidate_paths.append(Path(config_path))
    if env_config:
        candidate_paths.append(project_root / env_config)
    candidate_paths.append(project_root / "config.yaml")
    candidate_paths.append(project_root / "config.example.yaml")

    raw_data: dict = {}
    for candidate in candidate_paths:
        if candidate.exists():
            with candidate.open("r", encoding="utf-8") as f:
                loaded = yaml.safe_load(f)
                if isinstance(loaded, dict):
                    raw_data = loaded
            break

    cfg = AppConfig(**raw_data, project_root=project_root)

    effective_target = target_stack_override or os.getenv("STACKCONVERTER_TARGET_STACK") or cfg.default_target_stack
    spec = resolve_target_stack(effective_target)
    cfg.default_target_stack = spec.id
    cfg.default_source_stack = spec.source_stack
    cfg.paths.libmap_path = spec.libmap_path
    cfg.paths.rules_path = spec.rules_path

    if provider_override:
        cfg.default_provider = provider_override
    if cache_dir_override:
        cfg.paths.cache_dir = str(cache_dir_override)
    elif os.getenv("STACKCONVERTER_CACHE_DIR"):
        cfg.paths.cache_dir = os.environ["STACKCONVERTER_CACHE_DIR"]

    if runs_dir_override:
        cfg.paths.runs_dir = str(runs_dir_override)
    elif os.getenv("STACKCONVERTER_RUNS_DIR"):
        cfg.paths.runs_dir = os.environ["STACKCONVERTER_RUNS_DIR"]

    return cfg

