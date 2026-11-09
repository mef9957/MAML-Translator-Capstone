# Purpose: Build the compact, evidence-grounded prompt used for the single translation model call.

from __future__ import annotations

import json
from pathlib import Path

from maml_pipeline.models import SourceInventory


DEFAULT_PROMPT_VERSION = "prompt_v001"
DEFAULT_PROMPT_PATH = Path(__file__).resolve().parents[2] / "evaluation" / "prompts" / f"{DEFAULT_PROMPT_VERSION}.txt"


_FALLBACK_SYSTEM_PROMPT = """You translate a deterministic webpage inventory into a flat MAML element plan.
Return JSON only. Do not use Markdown. Do not paraphrase or invent page content.

The response must have this shape:
{
  "elements": [
    {
      "type": "text|shape|text-field|button|dropdown|image|carousel",
      "id": "unique_id",
      "source_ids": ["src_00001"],
      "x": 0,
      "y": 0,
      "z": 1,
      "w": 100,
      "h": 40,
      "display": "block",
      "properties": {
        "text_source_id": "src_00001",
        "link_source_id": "src_00001",
        "src_source_id": "src_00001",
        "aria_label_source_id": "src_00001",
        "placeholder_source_id": "src_00001",
        "options_source_id": "src_00001",
        "backgroundColor": "rgb(255, 255, 255)",
        "color": "rgb(0, 0, 0)",
        "fontFamily": "Arial",
        "fontSize": "16px",
        "fontWeight": "400",
        "fontStyle": "normal",
        "textAlign": "left",
        "border": "none",
        "borderRadius": "0px",
        "padding": "0px",
        "boxShadow": "none",
        "lineHeight": "normal",
        "letterSpacing": "normal",
        "alt": "description",
        "fit": "cover"
      }
    }
  ],
  "unsupported_features": []
}

Rules:
1. Use the supplied document-space geometry whenever possible.
2. Represent every meaningful text, link, image and control with visible_in_capture=true exactly once unless its exact content is duplicated by another source item. Ignore items with visible_in_capture=false.
3. Reference exact content with *_source_id fields. Never copy or rewrite source text or URLs.
4. Flatten nested HTML into independent absolute-positioned MAML elements.
5. Avoid duplicate text caused by parent and child elements.
6. Never omit non-link text that appears before, after or between inline links.
7. Treat kind as the primary evidence. The HTML tag is only a supporting hint and may be legacy, custom or unfamiliar.
8. Map meaningful kind=container items to shape elements so backgrounds, borders and grouped regions are preserved.
9. For an icon-only control, use aria_label_source_id rather than inventing visible text.
10. For a text-field, use placeholder_source_id when a placeholder exists; otherwise use aria_label_source_id when an accessible name exists. Never invent placeholder text.
11. All IDs must be unique and descriptive.
12. Use only the fields shown above. Omit irrelevant properties.
13. Report interactions that MAML cannot represent in unsupported_features.
"""


def load_system_prompt(prompt_path: Path | None = None) -> tuple[str, str, Path | None]:
    """Load a versioned system prompt and return its text, version, and source path."""
    selected = prompt_path or DEFAULT_PROMPT_PATH
    if selected.exists():
        return selected.read_text(encoding="utf-8").strip(), selected.stem, selected
    if prompt_path is not None:
        raise FileNotFoundError(f"Prompt file does not exist: {prompt_path}")
    return _FALLBACK_SYSTEM_PROMPT.strip(), DEFAULT_PROMPT_VERSION, None


# ADK Web uses the default versioned prompt. Command-line runs can override it.
SYSTEM_PROMPT, _, _ = load_system_prompt()


def _compact_element(element: dict) -> dict:
    """Remove empty fields so the prompt does not spend tokens on unused evidence."""
    keep = {
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
    return {key: value for key, value in element.items() if key in keep and value not in (None, "", [], {})}


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
