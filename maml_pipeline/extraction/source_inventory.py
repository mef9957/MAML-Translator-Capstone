# Purpose: Normalize browser evidence into a compact source inventory for translation and validation.

from __future__ import annotations

from maml_pipeline.models import PageCapture, SourceElement, SourceInventory


def _has_meaningful_content(item: dict) -> bool:
    return bool(
        (item.get("text") or "").strip()
        or (item.get("accessible_name") or "").strip()
        or item.get("href")
        or item.get("src")
        or item.get("placeholder")
        or item.get("options")
        or item.get("kind") == "container"
    )


def build_source_inventory(capture: PageCapture, max_elements: int = 350) -> SourceInventory:
    """Filter invisible/noise elements and retain exact page evidence in document order."""
    elements: list[SourceElement] = []
    warnings = list(capture.errors)

    meaningful = [
        item
        for item in capture.raw_elements
        if item.get("visible") and _has_meaningful_content(item)
    ]
    content = [item for item in meaningful if item.get("kind") != "container"]
    containers = [item for item in meaningful if item.get("kind") == "container"]

    # Content is evidence that must not be displaced by decorative containers
    # when the inventory reaches its API-cost cap. Restore document order after
    # selecting as many useful containers as the remaining budget allows.
    selected = content[:max_elements]
    if len(selected) < max_elements:
        selected.extend(containers[: max_elements - len(selected)])
    selected.sort(key=lambda item: int(str(item["source_id"]).split("_")[-1]))

    if len(meaningful) > len(selected):
        warnings.append(
            f"Inventory was capped at {max_elements} elements to control model input size."
        )

    for item in selected:

        elements.append(
            SourceElement(
                source_id=str(item["source_id"]),
                kind=str(item.get("kind") or "text"),
                tag=str(item.get("tag") or "div"),
                role=item.get("role"),
                text=str(item.get("text") or ""),
                accessible_name=item.get("accessible_name"),
                href=item.get("href"),
                src=item.get("src"),
                alt=item.get("alt"),
                placeholder=item.get("placeholder"),
                input_type=item.get("input_type"),
                options=list(item.get("options") or []),
                x=float(item.get("x") or 0),
                y=float(item.get("y") or 0),
                width=float(item.get("width") or 0),
                height=float(item.get("height") or 0),
                visible=bool(item.get("visible")),
                visible_in_capture=bool(item.get("visible_in_capture", item.get("visible"))),
                interactive=bool(item.get("interactive")),
                styles=dict(item.get("styles") or {}),
            )
        )

    return SourceInventory(
        url=capture.url,
        title=capture.title,
        viewport_width=capture.viewport_width,
        page_width=capture.page_width,
        page_height=capture.page_height,
        screenshot_path=capture.screenshot_path,
        elements=elements,
        warnings=warnings,
    )
