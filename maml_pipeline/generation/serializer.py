# Purpose: Convert the model's element plan into canonical JSON-lines MAML using exact inventory values.

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from maml_pipeline.models import SourceElement, SourceInventory


_REFERENCE_FIELDS = {
    "text_source_id": "text",
    "link_source_id": "link",
    "aria_label_source_id": "ariaLabel",
    "placeholder_source_id": "placeholder",
    "options_source_id": "options",
}


def _collect_source_ids(raw: dict[str, Any], properties: dict[str, Any]) -> list[str]:
    """Collect every source item used to construct the final MAML element."""
    candidates = list(raw.get("source_ids") or [])
    candidates.extend(properties.get(field) for field in _REFERENCE_FIELDS)
    candidates.append(properties.get("src_source_id"))

    source_ids: list[str] = []
    for source_id in candidates:
        if isinstance(source_id, str) and source_id and source_id not in source_ids:
            source_ids.append(source_id)
    return source_ids


def _resolve_reference(
    source_id: str,
    output_field: str,
    inventory_by_id: dict[str, SourceElement],
) -> Any:
    source = inventory_by_id.get(source_id)
    if source is None:
        raise ValueError(f"Unknown source inventory ID: {source_id}")
    if output_field == "link":
        return source.href
    if output_field == "ariaLabel":
        return source.accessible_name
    return getattr(source, output_field)


def serialize_plan(plan: dict[str, Any], inventory: SourceInventory) -> list[dict[str, Any]]:
    """Resolve evidence references and produce in-memory canonical MAML objects."""
    inventory_by_id = inventory.by_id()
    result: list[dict[str, Any]] = [{"viewport_width": inventory.viewport_width}]

    for raw in plan["elements"]:
        properties = deepcopy(raw.get("properties") or {})
        element: dict[str, Any] = {
            "type": raw.get("type"),
            "id": raw.get("id"),
            # Include both the agent's summary list and every field-level
            # evidence reference. Text and links often come from different
            # nested HTML elements, and both must be declared for validation.
            "source_ids": _collect_source_ids(raw, properties),
            "x": raw.get("x"),
            "y": raw.get("y"),
            "z": raw.get("z", 1),
            "w": raw.get("w"),
            "h": raw.get("h"),
            "display": raw.get("display", "block"),
        }

        for reference_field, output_field in _REFERENCE_FIELDS.items():
            source_id = properties.pop(reference_field, None)
            if source_id:
                value = _resolve_reference(source_id, output_field, inventory_by_id)
                if value not in (None, "", []):
                    element[output_field] = value

        src_source_id = properties.pop("src_source_id", None)
        if src_source_id:
            source = inventory_by_id.get(src_source_id)
            if source is None:
                raise ValueError(f"Unknown source inventory ID: {src_source_id}")
            if source.src:
                element["src"] = [{"source": source.src, "thumbnail": source.src}]
            if source.alt and not properties.get("alt"):
                properties["alt"] = source.alt

        element.update({key: value for key, value in properties.items() if value is not None})
        result.append(element)

    return result


def to_jsonl(objects: list[dict[str, Any]]) -> str:
    return "\n".join(json.dumps(obj, ensure_ascii=False) for obj in objects) + "\n"
