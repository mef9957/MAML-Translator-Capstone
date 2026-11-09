# Purpose: Check canonical MAML objects for syntax-independent schema and renderer compatibility errors.

from __future__ import annotations

from typing import Any

from maml_pipeline.models import ValidationIssue


VALID_TYPES = {"text", "shape", "text-field", "button", "dropdown", "image", "carousel", "script"}
GEOMETRY_FIELDS = {"x", "y", "z", "w", "h"}
COMMON_FIELDS = {"type", "id", "source_ids", "x", "y", "z", "w", "h", "display", "link"}
STYLE_FIELDS = {
    "backgroundColor", "borderRadius", "border", "boxShadow", "color",
    "fontFamily", "fontSize", "fontStyle", "fontWeight", "textAlign",
    "padding", "lineHeight", "letterSpacing",
}
TYPE_FIELDS = {
    "text": {"text", "fontFamily", "textAlign", "fontSize", "color", "fontStyle", "fontWeight"},
    "shape": {"backgroundColor", "borderRadius", "border", "boxShadow"},
    "text-field": {"placeholder", "ariaLabel", "backgroundColor", "color", "fontFamily", "fontSize", "borderRadius", "border", "padding"},
    "button": {"text", "ariaLabel"},
    "dropdown": {"options", "backgroundColor", "color", "fontFamily", "fontSize", "borderRadius", "border", "padding"},
    "image": {"src", "alt", "fit"},
    "carousel": {"srcs"},
    "script": {"code"},
}
REQUIRED_BY_TYPE = {
    "text": {"text"},
    "shape": set(),
    "text-field": set(),
    "button": set(),
    "dropdown": {"options"},
    "image": {"src"},
    "carousel": {"srcs"},
    "script": {"code"},
}


def validate_schema(objects: list[dict[str, Any]]) -> tuple[list[ValidationIssue], list[ValidationIssue]]:
    errors: list[ValidationIssue] = []
    warnings: list[ValidationIssue] = []
    if not objects or set(objects[0]) != {"viewport_width"} or not isinstance(objects[0].get("viewport_width"), (int, float)):
        errors.append(
            ValidationIssue(
                code="invalid_viewport",
                message="The first object must contain only a numeric viewport_width.",
                line_number=1,
            )
        )

    seen_ids: set[str] = set()
    for line_number, element in enumerate(objects[1:], start=2):
        element_id = element.get("id")
        element_type = element.get("type")
        if element_type not in VALID_TYPES:
            errors.append(ValidationIssue("invalid_type", f"Unsupported type: {element_type!r}", line_number, element_id))
            continue

        if element_type != "script":
            if not isinstance(element_id, str) or not element_id:
                errors.append(ValidationIssue("missing_id", "Every element needs a non-empty id.", line_number))
            elif element_id in seen_ids:
                errors.append(
                    ValidationIssue(
                        "duplicate_id",
                        f"Duplicate element id: {element_id}",
                        line_number,
                        element_id,
                        deterministic_fix_available=True,
                    )
                )
            else:
                seen_ids.add(element_id)

            for field in GEOMETRY_FIELDS:
                if not isinstance(element.get(field), (int, float)):
                    errors.append(
                        ValidationIssue(
                            "invalid_geometry",
                            f"{field} must be numeric.",
                            line_number,
                            element_id,
                            deterministic_fix_available=isinstance(element.get(field), str),
                        )
                    )
            if element.get("display") not in {"block", "none"}:
                errors.append(
                    ValidationIssue(
                        "invalid_display",
                        "display must be block or none.",
                        line_number,
                        element_id,
                        deterministic_fix_available=True,
                    )
                )

        for required in REQUIRED_BY_TYPE[element_type]:
            if element.get(required) in (None, "", []):
                errors.append(ValidationIssue("missing_property", f"{element_type} requires {required}.", line_number, element_id))

        if element_type == "text-field" and not (element.get("placeholder") or element.get("ariaLabel")):
            errors.append(
                ValidationIssue(
                    "missing_property",
                    "text-field requires a placeholder or ariaLabel.",
                    line_number,
                    element_id,
                )
            )

        if element_type == "button" and not (element.get("text") or element.get("ariaLabel")):
            errors.append(
                ValidationIssue(
                    "missing_property",
                    "button requires text or ariaLabel.",
                    line_number,
                    element_id,
                )
            )

        allowed = TYPE_FIELDS[element_type] | ({"type"} if element_type == "script" else COMMON_FIELDS | STYLE_FIELDS)
        unknown = set(element) - allowed
        if unknown:
            warnings.append(
                ValidationIssue(
                    "unknown_properties",
                    f"Renderer will ignore unknown properties: {sorted(unknown)}",
                    line_number,
                    element_id,
                )
            )

        if element_type == "image":
            src = element.get("src")
            if not (
                isinstance(src, list)
                and src
                and isinstance(src[0], dict)
                and isinstance(src[0].get("thumbnail"), str)
            ):
                errors.append(ValidationIssue("invalid_image_src", "image src must contain a thumbnail URL.", line_number, element_id))

    return errors, warnings
