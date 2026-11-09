# Purpose: Define the real Google ADK LlmAgent that plans and maps a source inventory to MAML elements.

from __future__ import annotations

from pathlib import Path

from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm

from maml_pipeline.config import Settings, load_settings
from maml_pipeline.generation.prompt_builder import SYSTEM_PROMPT


def build_translation_agent(settings: Settings, instruction: str = SYSTEM_PROMPT) -> LlmAgent:
    """Build one tool-free ADK agent so a normal translation uses one model inference."""
    model_options: dict = {
        "model": settings.model,
        "api_key": settings.api_key,
    }
    if settings.api_base:
        model_options["api_base"] = settings.api_base
    if "portkey" in (settings.api_base or "") and settings.api_key:
        model_options["extra_headers"] = {"x-portkey-api-key": settings.api_key}

    return LlmAgent(
        name="maml_translation_agent",
        model=LiteLlm(**model_options),
        description=(
            "Converts a deterministic source-page inventory into a structured MAML element plan."
        ),
        instruction=instruction,
    )


# ADK discovers this variable when `adk web` is launched from the project root.
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
root_agent = build_translation_agent(load_settings(_PROJECT_ROOT))
