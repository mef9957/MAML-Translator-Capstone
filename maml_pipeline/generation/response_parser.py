# Purpose: Parse and minimally check the model's JSON response before deterministic serialization.

from __future__ import annotations

import json
from typing import Any


class TranslationResponseError(ValueError):
    """Raised when the model response is not the requested JSON structure."""


def parse_translation_response(content: str) -> dict[str, Any]:
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
