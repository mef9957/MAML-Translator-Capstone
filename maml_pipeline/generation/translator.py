# Purpose: Make the single translation model call and parse its JSON response.

from __future__ import annotations

import json
from typing import Any

from maml_agent.agent import run_translation_agent
from maml_pipeline.config import Settings


class ModelConfigurationError(RuntimeError):
    """Raised when the model cannot be called because no API key is configured."""


class TranslationResponseError(ValueError):
    """Raised when the model response is not the requested JSON structure."""


def request_translation(page_prompt: str, settings: Settings, system_prompt: str) -> str:
    """Call the translation agent once and return its raw text response."""
    if not settings.api_key:
        raise ModelConfigurationError(
            "No model API key was found. Set PORTKEY_API_KEY, OPENAI_API_KEY, or GOOGLE_API_KEY in .env."
        )
    return run_translation_agent(page_prompt, settings, system_prompt)


def parse_translation_response(content: str) -> dict[str, Any]:
    """Strip an optional Markdown code fence and require an object with an elements array."""
    cleaned = content.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        cleaned = "\n".join(lines[1:-1]).strip()

    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise TranslationResponseError(f"Model output was not valid JSON: {exc}") from exc

    if not isinstance(payload, dict) or not isinstance(payload.get("elements"), list):
        raise TranslationResponseError("Model output must be an object containing an elements array.")
    return payload
