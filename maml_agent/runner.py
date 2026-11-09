# Purpose: Execute the ADK translation agent programmatically inside the deterministic pipeline.

from __future__ import annotations

import asyncio
import uuid

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from maml_agent.agent import build_translation_agent
from maml_pipeline.config import Settings


_APP_NAME = "maml_translation"
_USER_ID = "pipeline"


async def _run_agent(prompt: str, settings: Settings, system_prompt: str) -> str:
    agent = build_translation_agent(settings, instruction=system_prompt)
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
    """Run the async ADK session from the synchronous pipeline CLI."""
    return asyncio.run(_run_agent(prompt, settings, system_prompt))
