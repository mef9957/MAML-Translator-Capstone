# Purpose: Verify that generated MAML content and evidence references come from the captured webpage.

from __future__ import annotations

from typing import Any

from maml_pipeline.models import SourceInventory, ValidationIssue


def validate_preservation(
    objects: list[dict[str, Any]], inventory: SourceInventory
) -> tuple[list[ValidationIssue], list[ValidationIssue]]:
    errors: list[ValidationIssue] = []
    warnings: list[ValidationIssue] = []
    by_id = inventory.by_id()
    represented: set[str] = set()

    for line_number, element in enumerate(objects[1:], start=2):
        source_ids = element.get("source_ids") or []
        if not isinstance(source_ids, list):
            errors.append(ValidationIssue("invalid_source_ids", "source_ids must be an array.", line_number, element.get("id")))
            continue
        for source_id in source_ids:
            if source_id not in by_id:
                errors.append(
                    ValidationIssue(
                        "unknown_source_id",
                        f"Element references unknown inventory item {source_id}.",
                        line_number,
                        element.get("id"),
                        [source_id],
                    )
                )
            else:
                represented.add(source_id)

        if "text" in element:
            valid_texts = {by_id[source_id].text for source_id in source_ids if source_id in by_id}
            if element["text"] not in valid_texts:
                errors.append(
                    ValidationIssue(
                        "changed_or_invented_text",
                        "Text does not exactly match a referenced source element.",
                        line_number,
                        element.get("id"),
                        source_ids,
                    )
                )
        if element.get("link"):
            valid_links = {by_id[source_id].href for source_id in source_ids if source_id in by_id}
            if element["link"] not in valid_links:
                errors.append(
                    ValidationIssue(
                        "changed_or_invented_link",
                        "Link does not exactly match a referenced source element.",
                        line_number,
                        element.get("id"),
                        source_ids,
                    )
                )
        if element.get("ariaLabel"):
            valid_names = {
                by_id[source_id].accessible_name
                for source_id in source_ids
                if source_id in by_id
            }
            if element["ariaLabel"] not in valid_names:
                errors.append(
                    ValidationIssue(
                        "changed_or_invented_accessible_name",
                        "Accessible name does not exactly match a referenced source element.",
                        line_number,
                        element.get("id"),
                        source_ids,
                    )
                )

    required_ids = {
        element.source_id
        for element in inventory.elements
        if element.visible_in_capture
        and element.kind != "container"
        and (
            element.text
            or element.accessible_name
            or element.href
            or element.src
            or element.placeholder
            or element.options
        )
    }
    missing = required_ids - represented
    if missing:
        errors.append(
            ValidationIssue(
                "unrepresented_source_elements",
                f"{len(missing)} meaningful source elements are not represented in MAML.",
                source_ids=sorted(missing),
            )
        )
    return errors, warnings
