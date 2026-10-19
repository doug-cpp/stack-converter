"""Google Gemini API provider adapter using langchain-google-genai."""

from __future__ import annotations

import json
import os
from typing import Any, TypeVar

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class GeminiAPIProvider:
    """Adapter for Google Gemini API via langchain-google-genai."""

    name = "gemini_api"

    def __init__(self, model_name: str = "gemini-2.5-pro") -> None:
        self.model_name = model_name
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise RuntimeError(
                "GOOGLE_API_KEY is not set. Add it to .env or switch default_provider to 'fake' or 'claude_subscription'."
            )
        self._client = ChatGoogleGenerativeAI(
            model=model_name,
            google_api_key=api_key,
            temperature=0.0,
        )

    async def generate_structured(
        self,
        role: str,
        system_prompt: str,
        payload: dict[str, Any],
        response_model: type[T],
        validation_error_feedback: str | None = None,
    ) -> dict[str, Any]:
        """Request structured JSON output from Gemini matching response_model."""
        structured_llm = self._client.with_structured_output(response_model)
        user_text = json.dumps(payload, indent=2, default=str)
        if validation_error_feedback:
            user_text += (
                f"\n\nPREVIOUS OUTPUT FAILED PYDANTIC VALIDATION:\n{validation_error_feedback}\n"
                "Please fix the fields to match the exact schema."
            )
        result = await structured_llm.ainvoke(
            [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_text),
            ]
        )
        if isinstance(result, BaseModel):
            return result.model_dump(mode="json")
        if isinstance(result, dict):
            return result
        raise ValueError(f"Unexpected response type from Gemini: {type(result)}")
