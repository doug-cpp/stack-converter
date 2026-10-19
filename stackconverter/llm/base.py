"""Provider protocol and schema-validated agent caller with retry and caching."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from stackconverter.config import AppConfig, load_config
from stackconverter.llm.cache import DiskCache

T = TypeVar("T", bound=BaseModel)


class LLMProvider(Protocol):
    """Protocol implemented by all LLM provider adapters."""

    name: str
    model_name: str

    async def generate_structured(
        self,
        role: str,
        system_prompt: str,
        payload: dict[str, Any],
        response_model: type[T],
        validation_error_feedback: str | None = None,
    ) -> dict[str, Any]:
        """Generate a raw JSON-serializable dict matching response_model."""
        ...


def load_prompt_file(prompts_dir: Path, role: str) -> tuple[str, str]:
    """Load prompt Markdown and extract version header."""
    prompt_path = prompts_dir / f"{role}.md"
    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt file not found for role '{role}': {prompt_path}")
    text = prompt_path.read_text(encoding="utf-8")
    version_match = re.search(r'^version:\s*["\']?([^"\'\n]+)["\']?', text, re.MULTILINE)
    version = version_match.group(1).strip() if version_match else "1.0"
    return version, text


class AgentCaller:
    """Manages provider instances, concurrency semaphores, disk caching, and retries."""

    def __init__(self, config: AppConfig | None = None, cache: DiskCache | None = None) -> None:
        self.config = config or load_config()
        fallback_dirs: list[Path] = []
        demo_dir = self.config.resolve_path(self.config.paths.demo_cache_dir)
        if demo_dir.exists():
            fallback_dirs.append(demo_dir)
        self.cache = cache or DiskCache(
            self.config.resolve_path(self.config.paths.cache_dir),
            fallback_dirs=fallback_dirs,
        )
        self._semaphores: dict[str, asyncio.Semaphore] = {
            "gemini_api": asyncio.Semaphore(self.config.concurrency.gemini_api),
            "claude_subscription": asyncio.Semaphore(self.config.concurrency.claude_subscription),
            "fake": asyncio.Semaphore(self.config.concurrency.fake),
        }
        self._providers: dict[str, LLMProvider] = {}
        self.llm_calls = 0

    def get_provider(self, provider_name: str) -> LLMProvider:
        """Instantiate or return cached provider adapter."""
        if provider_name in self._providers:
            return self._providers[provider_name]

        if provider_name == "fake":
            from stackconverter.llm.fake import FakeProvider

            provider: LLMProvider = FakeProvider(model_name=self.config.models.fake)
        elif provider_name == "gemini_api":
            from stackconverter.llm.gemini_api import GeminiAPIProvider

            provider = GeminiAPIProvider(model_name=self.config.models.gemini_api)
        elif provider_name == "claude_subscription":
            from stackconverter.llm.claude_subscription import ClaudeSubscriptionProvider

            provider = ClaudeSubscriptionProvider(model_name=self.config.models.claude_subscription)
        else:
            raise ValueError(f"Unsupported provider: {provider_name}")

        self._providers[provider_name] = provider
        return provider

    async def call_agent(
        self,
        role: str,
        payload: dict[str, Any],
        response_model: type[T],
    ) -> T:
        """Invoke an agent role with disk caching, semaphore throttling, and 1 retry on ValidationError."""
        provider_name = self.config.get_provider_for_role(role)
        provider = self.get_provider(provider_name)
        prompts_dir = Path(__file__).resolve().parent.parent / "prompts"
        prompt_version, system_prompt = load_prompt_file(prompts_dir, role)

        cache_key = self.cache.compute_key(
            role=role,
            prompt_version=prompt_version,
            model_name=provider.model_name,
            payload=payload,
            schema_name=response_model.__name__,
        )

        cached = self.cache.get(cache_key)
        if cached is not None:
            return response_model.model_validate(cached)

        semaphore = self._semaphores.get(provider_name, asyncio.Semaphore(4))
        last_error: str | None = None

        async with semaphore:
            for attempt in range(2):
                self.llm_calls += 1
                raw_dict = await provider.generate_structured(
                    role=role,
                    system_prompt=system_prompt,
                    payload=payload,
                    response_model=response_model,
                    validation_error_feedback=last_error,
                )
                try:
                    validated = response_model.model_validate(raw_dict)
                    self.cache.set(
                        cache_key,
                        metadata={
                            "role": role,
                            "provider": provider_name,
                            "model": provider.model_name,
                            "prompt_version": prompt_version,
                            "schema": response_model.__name__,
                            "attempt": attempt + 1,
                        },
                        response=validated.model_dump(mode="json"),
                    )
                    return validated
                except ValidationError as exc:
                    last_error = str(exc)
                    if attempt == 1:
                        raise


async def call_agent[T: BaseModel](
    role: str,
    payload: dict[str, Any],
    response_model: type[T],
    caller: AgentCaller | None = None,
) -> T:
    """Convenience wrapper around AgentCaller.call_agent."""
    active_caller = caller or AgentCaller()
    return await active_caller.call_agent(role=role, payload=payload, response_model=response_model)
