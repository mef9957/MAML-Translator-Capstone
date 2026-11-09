# Purpose: Render canonical MAML objects into deterministic standalone HTML for comparison.

from __future__ import annotations

import html
from pathlib import Path
from typing import Any

from maml_pipeline.models import RenderResult
from maml_pipeline.rendering.mamlscript import convert_mamlscript


_CSS_FIELDS = {
    "backgroundColor": "background-color",
    "borderRadius": "border-radius",
    "border": "border",
    "boxShadow": "box-shadow",
    "color": "color",
    "fontFamily": "font-family",
    "fontSize": "font-size",
    "fontStyle": "font-style",
    "fontWeight": "font-weight",
    "lineHeight": "line-height",
    "letterSpacing": "letter-spacing",
    "textAlign": "text-align",
    "padding": "padding",
}


def _styles(element: dict[str, Any]) -> str:
    styles = {
        "position": "absolute",
        "left": f"{element['x']}px",
        "top": f"{element['y']}px",
        "width": f"{element['w']}px",
        "height": f"{element['h']}px",
        "z-index": str(element["z"]),
        "display": element["display"],
        "box-sizing": "border-box",
    }
    for maml_name, css_name in _CSS_FIELDS.items():
        if element.get(maml_name) not in (None, ""):
            styles[css_name] = str(element[maml_name])
    if element.get("type") == "image" and element.get("fit"):
        styles["object-fit"] = str(element["fit"])
    return ";".join(f"{key}:{value}" for key, value in styles.items())


def _tag_for(element_type: str) -> str:
    return {
        "text": "div",
        "shape": "div",
        "text-field": "input",
        "button": "button",
        "dropdown": "select",
        "image": "img",
        "carousel": "div",
    }[element_type]


def _render_element(element: dict[str, Any]) -> str:
    element_type = element["type"]
    tag = _tag_for(element_type)
    attributes = [f'id="{html.escape(element["id"], quote=True)}"', f'style="{html.escape(_styles(element), quote=True)}"']
    content = ""

    if element_type in {"text", "button"}:
        content = html.escape(str(element.get("text", "")))
        if element_type == "button" and element.get("ariaLabel"):
            attributes.append(
                f'aria-label="{html.escape(str(element["ariaLabel"]), quote=True)}"'
            )
    elif element_type == "text-field":
        if element.get("placeholder"):
            attributes.append(f'placeholder="{html.escape(str(element["placeholder"]), quote=True)}"')
        if element.get("ariaLabel"):
            attributes.append(f'aria-label="{html.escape(str(element["ariaLabel"]), quote=True)}"')
    elif element_type == "dropdown":
        content = "".join(f"<option>{html.escape(str(option))}</option>" for option in element.get("options", []))
    elif element_type == "image":
        source = element["src"][0]["thumbnail"]
        attributes.append(f'src="{html.escape(source, quote=True)}"')
        attributes.append(f'alt="{html.escape(str(element.get("alt", "")), quote=True)}"')

    void = tag in {"img", "input"}
    rendered = f"<{tag} {' '.join(attributes)}{' />' if void else f'>{content}</{tag}>'}"
    if element.get("link"):
        rendered = f'<a href="{html.escape(str(element["link"]), quote=True)}" target="_blank" rel="noopener">{rendered}</a>'
    return rendered


def render_maml(objects: list[dict[str, Any]], output_path: Path) -> RenderResult:
    warnings: list[str] = []
    scripts: list[str] = []
    elements = [obj for obj in objects[1:] if obj.get("type") != "script"]
    elements = sorted(enumerate(elements), key=lambda pair: (pair[1].get("z", 0), pair[0]))
    rendered_elements = [_render_element(element) for _, element in elements]

    for obj in objects[1:]:
        if obj.get("type") == "script":
            javascript, script_warnings = convert_mamlscript(str(obj.get("code", "")))
            scripts.append(javascript)
            warnings.extend(script_warnings)

    viewport = objects[0]["viewport_width"]
    document = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Rendered MAML</title>
  <style>
    html, body {{ margin: 0; padding: 0; }}
    body {{ position: relative; width: {viewport}px; min-height: 100vh; overflow-x: hidden; }}
    a, a:visited {{ color: inherit; text-decoration: inherit; }}
  </style>
</head>
<body>
{''.join(rendered_elements)}
<script>{''.join(scripts)}</script>
</body>
</html>
"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(document, encoding="utf-8")
    return RenderResult(True, str(output_path), warnings=warnings)
