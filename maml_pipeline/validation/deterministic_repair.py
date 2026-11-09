# Purpose: Apply safe mechanical fixes to common MAML problems without spending another API call.

from __future__ import annotations

from copy import deepcopy
from typing import Any


def repair_maml(objects: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    repaired = deepcopy(objects)
    changes: list[str] = []
    seen_ids: dict[str, int] = {}

    for index, element in enumerate(repaired[1:], start=2):
        if element.get("type") == "script":
            continue

        if element.get("display") not in {"block", "none"}:
            element["display"] = "block"
            changes.append(f"Line {index}: normalized display to block.")

        for field in ("x", "y", "z", "w", "h"):
            value = element.get(field)
            if isinstance(value, str):
                try:
                    element[field] = float(value.rstrip("px"))
                    changes.append(f"Line {index}: converted {field} to a number.")
                except ValueError:
                    pass

        element_id = element.get("id")
        if isinstance(element_id, str) and element_id:
            occurrence = seen_ids.get(element_id, 0) + 1
            seen_ids[element_id] = occurrence
            if occurrence > 1:
                element["id"] = f"{element_id}_{occurrence}"
                changes.append(f"Line {index}: renamed duplicate id to {element['id']}.")

    return repaired, changes
