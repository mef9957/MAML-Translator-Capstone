# Purpose: Call the Google ADK translation agent once for the initial MAML element plan.

from __future__ import annotations

from maml_agent.runner import run_translation_agent
from maml_pipeline.config import Settings


class ModelConfigurationError(RuntimeError):
    """Raised when the model cannot be called because required configuration is missing."""


def call_translation_agent(prompt: str, settings: Settings, system_prompt: str) -> str:
    if not settings.api_key:
        raise ModelConfigurationError(
            "No model API key was found. Set PORTKEY_API_KEY, OPENAI_API_KEY, or GOOGLE_API_KEY in .env."
        )
    return run_translation_agent(prompt, settings, system_prompt)
