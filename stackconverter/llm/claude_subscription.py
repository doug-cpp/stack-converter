"""Claude Code Subscription provider adapter."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from typing import Any, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class ClaudeSubscriptionProvider:
    """Adapter for Claude Code Subscription via claude-agent-sdk or claude CLI."""

    name = "claude_subscription"

    def __init__(self, model_name: str = "claude-sonnet-4-5") -> None:
        self.model_name = model_name
        if os.getenv("ANTHROPIC_API_KEY"):
            raise RuntimeError(
                "ANTHROPIC_API_KEY is set in the environment! When using 'claude_subscription', "
                "you must unset ANTHROPIC_API_KEY so Claude Code uses your active subscription "
                "instead of billing API credits."
            )

    async def generate_structured(
        self,
        role: str,
        system_prompt: str,
        payload: dict[str, Any],
        response_model: type[T],
        validation_error_feedback: str | None = None,
    ) -> dict[str, Any]:
        """Invoke Claude Code SDK or CLI in non-interactive JSON mode."""
        schema_json = json.dumps(response_model.model_json_schema(), indent=2)
        prompt = (
            f"{system_prompt}\n\n"
            f"Target JSON Schema:\n{schema_json}\n\n"
            f"Input Payload:\n{json.dumps(payload, indent=2, default=str)}\n\n"
            "Respond ONLY with a raw JSON object conforming to the Target JSON Schema."
        )
        if validation_error_feedback:
            prompt += f"\n\nFix previous Pydantic validation error:\n{validation_error_feedback}"

        # Try claude-agent-sdk if installed, otherwise fallback to claude CLI
        try:
            import claude_agent_sdk  # type: ignore[import-not-found]

            response_text = await claude_agent_sdk.query(prompt=prompt, model=self.model_name)
        except ImportError:
            claude_bin = shutil.which("claude")
            if not claude_bin:
                raise RuntimeError(
                    "Neither 'claude-agent-sdk' nor 'claude' CLI binary was found in PATH."
                ) from None
            proc = await asyncio.create_subprocess_exec(
                claude_bin,
                "-p",
                prompt,
                "--output-format",
                "text",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode != 0:
                raise RuntimeError(
                    f"claude CLI failed: {stderr.decode('utf-8', errors='replace')}"
                ) from None
            response_text = stdout.decode("utf-8", errors="replace").strip()

        cleaned = response_text.strip()
        if cleaned.startswith("```"):
            lines = cleaned.splitlines()
            cleaned = "\n".join(lines[1:-1] if lines[-1].strip().startswith("```") else lines[1:])
        return json.loads(cleaned)
