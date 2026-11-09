# Purpose: Load the versioned system prompt and build the compact inventory prompt for the translation call.

from __future__ import annotations

import json
from pathlib import Path

from maml_pipeline.models import SourceInventory


DEFAULT_PROMPT_PATH = Path(__file__).resolve().parents[2] / "evaluation" / "prompts" / "prompt_v001.txt"

_PROMPT_FIELDS = {
    "source_id",
    "kind",
    "tag",
    "role",
    "text",
    "accessible_name",
    "href",
    "src",
    "alt",
    "placeholder",
    "input_type",
    "options",
    "x",
    "y",
    "width",
    "height",
    "interactive",
    "visible_in_capture",
    "styles",
}


def load_system_prompt(prompt_path: Path | None = None) -> tuple[str, str, Path]:
    """Load a versioned system prompt and return its text, version (the file name), and path."""
    selected = prompt_path or DEFAULT_PROMPT_PATH
    if not selected.exists():
        raise FileNotFoundError(f"Prompt file does not exist: {selected}")
    return selected.read_text(encoding="utf-8").strip(), selected.stem, selected


def _compact_element(element: dict) -> dict:
    """Keep prompt fields and drop empty values so the prompt does not spend tokens on unused evidence."""
    return {
        key: value
        for key, value in element.items()
        if key in _PROMPT_FIELDS and value not in (None, "", [], {})
    }


def build_translation_prompt(inventory: SourceInventory) -> str:
    compact_inventory = {
        "url": inventory.url,
        "title": inventory.title,
        "viewport_width": inventory.viewport_width,
        "page_width": inventory.page_width,
        "page_height": inventory.page_height,
        "elements": [_compact_element(element.to_dict()) for element in inventory.elements],
    }
    return "Translate this source inventory into a MAML element plan:\n" + json.dumps(
        compact_inventory,
        ensure_ascii=False,
        separators=(",", ":"),
    )
