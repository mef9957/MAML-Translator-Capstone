# Purpose: Coordinate the single translation call, parse its response, and resolve exact source evidence.

from __future__ import annotations

from maml_pipeline.config import Settings
from maml_pipeline.generation.model_client import call_translation_agent
from maml_pipeline.generation.prompt_builder import build_translation_prompt
from maml_pipeline.generation.response_parser import parse_translation_response
from maml_pipeline.generation.serializer import serialize_plan
from maml_pipeline.models import SourceInventory


def translate_inventory(
    inventory: SourceInventory,
    settings: Settings,
    *,
    system_prompt: str,
    page_prompt: str | None = None,
) -> tuple[dict, list[dict], str]:
    prompt = page_prompt or build_translation_prompt(inventory)
    response = call_translation_agent(prompt, settings, system_prompt)
    plan = parse_translation_response(response)
    return plan, serialize_plan(plan, inventory), response
