# Purpose: Define the Google ADK translation agent and run it once per page.

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from maml_pipeline.config import Settings, load_settings
from maml_pipeline.generation.prompt_builder import load_system_prompt


_APP_NAME = "maml_translation"
_USER_ID = "pipeline"


def build_translation_agent(settings: Settings, instruction: str) -> LlmAgent:
    """Build one tool-free ADK agent so a translation makes exactly one model inference."""
    model_options: dict = {
        "model": settings.model,
        "api_key": settings.api_key,
    }
    if settings.api_base:
        model_options["api_base"] = settings.api_base

    return LlmAgent(
        name="maml_translation_agent",
        model=LiteLlm(**model_options),
        description=(
            "Converts a deterministic source-page inventory into a structured MAML element plan."
        ),
        instruction=instruction,
    )


async def _run_agent(prompt: str, settings: Settings, system_prompt: str) -> str:
    agent = build_translation_agent(settings, system_prompt)
    session_service = InMemorySessionService()
    session_id = str(uuid.uuid4())
    await session_service.create_session(
        app_name=_APP_NAME,
        user_id=_USER_ID,
        session_id=session_id,
    )
    runner = Runner(
        agent=agent,
        app_name=_APP_NAME,
        session_service=session_service,
    )
    message = types.Content(role="user", parts=[types.Part(text=prompt)])
    final_text = ""

    async for event in runner.run_async(
        user_id=_USER_ID,
        session_id=session_id,
        new_message=message,
    ):
        if event.is_final_response() and event.content and event.content.parts:
            final_text = "".join(part.text or "" for part in event.content.parts)

    if not final_text:
        raise RuntimeError("The Google ADK translation agent returned no final text response.")
    return final_text


def run_translation_agent(prompt: str, settings: Settings, system_prompt: str) -> str:
    """Run the async ADK session from the synchronous pipeline."""
    return asyncio.run(_run_agent(prompt, settings, system_prompt))


# `adk web` discovers this variable. It uses the default versioned prompt;
# pipeline runs build their own agent with the prompt selected for that run.
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
root_agent = build_translation_agent(load_settings(_PROJECT_ROOT), load_system_prompt()[0])
