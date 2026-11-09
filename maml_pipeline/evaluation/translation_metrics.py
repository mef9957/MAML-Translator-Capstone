# Purpose: Score a rendered MAML page against its source page using the Design2Code
# element metrics (Block-Match, Text, Position, Color, CLIP), SSIM, and MAML validity.
#
# Reference: Si et al., "Design2Code: Benchmarking Multimodal Code Generation for Automated
# Front-End Engineering" (arXiv:2403.03163) and the authors' metrics/visual_score.py.
# Deliberate differences from that implementation:
# 1. Text blocks come from the browser DOM of both pages (the same extraction script for the
#    source and the rendered MAML) instead of recoloring text and diffing screenshots.
# 2. Block merging is skipped. Every MAML text element resolves to exactly one source text
#    node, so source and rendered blocks are already split the same way.
# 3. The context bonus is replaced by a small position tie-break, so repeated texts such as
#    several "Learn more" links are paired with their nearest counterpart.
# 4. Both pages are normalized by the source page size. MAML keeps absolute coordinates, so a
#    rendered page that is shorter because content is missing must not shift every position.

from __future__ import annotations

import re
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image
from scipy.optimize import linear_sum_assignment
from skimage.color import deltaE_ciede2000, rgb2lab

from maml_pipeline.models import SourceInventory
from maml_pipeline.validation.preservation_validator import required_source_ids, validate_preservation
from maml_pipeline.validation.schema_validator import validate_schema


# Design2Code drops matched pairs whose text similarity is below this value.
MATCH_THRESHOLD = 0.5
# Weight of the center distance in the matching cost. It only decides between pairs whose
# text similarity is equal, because similarities differ by far more than this.
POSITION_TIE_BREAK = 1e-3

_RGB = re.compile(r"rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)")


def _text_blocks(elements: list[dict[str, Any]], page_width: float, page_height: float) -> list[dict[str, Any]]:
    """Return visible text blocks with boxes normalized to [0, 1] by the source page size."""
    blocks = []
    for element in elements:
        text = (element.get("text") or "").strip()
        if (
            element.get("kind") in {"text", "control"}
            and text
            and element.get("visible_in_capture")
            and element.get("width", 0) > 0
            and element.get("height", 0) > 0
        ):
            blocks.append(
                {
                    "text": text,
                    "x": element["x"] / page_width,
                    "y": element["y"] / page_height,
                    "w": element["width"] / page_width,
                    "h": element["height"] / page_height,
                    "color": (element.get("styles") or {}).get("color"),
                }
            )
    return blocks


def _image_sources(elements: list[dict[str, Any]]) -> set[str]:
    return {
        element["src"]
        for element in elements
        if element.get("kind") == "image" and element.get("src") and element.get("visible_in_capture")
    }


def _center_offset(first: dict[str, Any], second: dict[str, Any]) -> float:
    """Design2Code position distance: the larger of the horizontal and vertical center offsets."""
    dx = (first["x"] + first["w"] / 2) - (second["x"] + second["w"] / 2)
    dy = (first["y"] + first["h"] / 2) - (second["y"] + second["h"] / 2)
    return max(abs(dx), abs(dy))


def _center_offset_px(first: dict[str, Any], second: dict[str, Any], page_width: float, page_height: float) -> float:
    """The same distance in CSS pixels, so it can be read directly."""
    dx = ((first["x"] + first["w"] / 2) - (second["x"] + second["w"] / 2)) * page_width
    dy = ((first["y"] + first["h"] / 2) - (second["y"] + second["h"] / 2)) * page_height
    return max(abs(dx), abs(dy))


def _match_blocks(
    source: list[dict[str, Any]], rendered: list[dict[str, Any]]
) -> list[tuple[int, int, float]]:
    """Optimal one-to-one matching on text similarity (Jonker-Volgenant), keeping pairs >= 0.5."""
    if not source or not rendered:
        return []
    similarity = np.zeros((len(source), len(rendered)))
    offsets = np.zeros_like(similarity)
    matcher = SequenceMatcher(None)
    for j, rendered_block in enumerate(rendered):
        # SequenceMatcher indexes its second string, so set it once per column.
        matcher.set_seq2(rendered_block["text"])
        for i, source_block in enumerate(source):
            offsets[i, j] = _center_offset(source_block, rendered_block)
            if source_block["text"] == rendered_block["text"]:
                similarity[i, j] = 1.0
                continue
            matcher.set_seq1(source_block["text"])
            # Pairs below the threshold are never kept, so skip the exact ratio when a cheap
            # upper bound already rules them out.
            if matcher.real_quick_ratio() >= MATCH_THRESHOLD and matcher.quick_ratio() >= MATCH_THRESHOLD:
                similarity[i, j] = matcher.ratio()
    rows, cols = linear_sum_assignment(-similarity + POSITION_TIE_BREAK * offsets)
    return [(i, j, float(similarity[i, j])) for i, j in zip(rows, cols) if similarity[i, j] >= MATCH_THRESHOLD]


def _color_similarity(first: str | None, second: str | None) -> float | None:
    """Design2Code color score: max(0, 1 - CIEDE2000 / 100) between the two text colors."""
    first_match, second_match = _RGB.match(first or ""), _RGB.match(second or "")
    if not first_match or not second_match:
        return None
    first_lab = rgb2lab(np.array([[[float(v) / 255 for v in first_match.groups()]]]))
    second_lab = rgb2lab(np.array([[[float(v) / 255 for v in second_match.groups()]]]))
    return max(0.0, 1.0 - float(deltaE_ciede2000(first_lab, second_lab)[0, 0]) / 100)


@lru_cache(maxsize=1)
def _clip_model() -> tuple[Any, Any]:
    """Load CLIP ViT-B/32 with OpenAI weights once per process (downloaded on first use)."""
    import open_clip

    model, _, preprocess = open_clip.create_model_and_transforms("ViT-B-32", pretrained="openai")
    model.eval()
    return model, preprocess


def _inpaint_text(screenshot: Path, blocks: list[dict[str, Any]], page_width: float, page_height: float) -> Image.Image:
    """Remove text by Telea inpainting inside the matched text boxes, as Design2Code does before CLIP."""
    import cv2

    image = cv2.imread(str(screenshot))
    scale = image.shape[1] / page_width
    mask = np.zeros(image.shape[:2], dtype=np.uint8)
    for block in blocks:
        x0 = max(int(block["x"] * page_width * scale), 0)
        y0 = max(int(block["y"] * page_height * scale), 0)
        x1 = min(int((block["x"] + block["w"]) * page_width * scale), image.shape[1])
        y1 = min(int((block["y"] + block["h"]) * page_height * scale), image.shape[0])
        if x1 > x0 and y1 > y0:
            mask[y0:y1, x0:x1] = 255
    inpainted = cv2.inpaint(image, mask, 3, cv2.INPAINT_TELEA)
    return Image.fromarray(cv2.cvtColor(inpainted, cv2.COLOR_BGR2RGB))


def _clip_similarity(original: Image.Image, rendered: Image.Image) -> float:
    """Cosine similarity of CLIP embeddings after stretching each image to a square on its shorter side."""
    import torch

    model, preprocess = _clip_model()
    features = []
    for image in (original, rendered):
        side = min(image.size)
        square = image.resize((side, side), Image.LANCZOS)
        with torch.no_grad():
            embedding = model.encode_image(preprocess(square).unsqueeze(0))
        features.append(embedding / embedding.norm(dim=-1, keepdim=True))
    return float((features[0] @ features[1].T).item())


def _mean(values: list[float]) -> float | None:
    return float(np.mean(values)) if values else None


def _ratio(part: int, whole: int) -> float | None:
    return part / whole if whole else None


def maml_validity(
    generated_objects: list[dict[str, Any]],
    final_objects: list[dict[str, Any]],
    inventory: SourceInventory,
    repair_count: int,
) -> dict[str, Any]:
    """Separate syntax validity (schema) from content integrity and source coverage."""
    schema_errors_before, _ = validate_schema(generated_objects)
    schema_errors_after, schema_warnings = validate_schema(final_objects)
    content_errors, _ = validate_preservation(final_objects, inventory)
    required = required_source_ids(inventory)
    represented = {
        source_id for element in final_objects[1:] for source_id in element.get("source_ids") or []
    }
    return {
        "schema_errors_before_repair": len(schema_errors_before),
        "schema_errors_after_repair": len(schema_errors_after),
        "deterministic_repairs": repair_count,
        "content_integrity_errors": len(content_errors),
        "unknown_property_warnings": len(schema_warnings),
        "required_source_elements": len(required),
        "source_id_coverage": _ratio(len(required & represented), len(required)),
        "maml_element_count": len(final_objects) - 1,
    }


def evaluate_translation(
    *,
    source_elements: list[dict[str, Any]],
    rendered_elements: list[dict[str, Any]],
    source_page_width: float,
    source_page_height: float,
    original_screenshot: Path,
    rendered_screenshot: Path,
    ssim: float,
    validity: dict[str, Any],
) -> dict[str, Any]:
    """Return the full evaluation report, grouped by what each metric measures."""
    source_blocks = _text_blocks(source_elements, source_page_width, source_page_height)
    rendered_blocks = _text_blocks(rendered_elements, source_page_width, source_page_height)
    matches = _match_blocks(source_blocks, rendered_blocks)

    matched_area = sum(
        source_blocks[i]["w"] * source_blocks[i]["h"] + rendered_blocks[j]["w"] * rendered_blocks[j]["h"]
        for i, j, _ in matches
    )
    total_area = sum(block["w"] * block["h"] for block in source_blocks + rendered_blocks)
    offsets = [_center_offset(source_blocks[i], rendered_blocks[j]) for i, j, _ in matches]
    colors = [
        score
        for i, j, _ in matches
        if (score := _color_similarity(source_blocks[i]["color"], rendered_blocks[j]["color"])) is not None
    ]
    matched_characters = sum(
        similarity * (len(source_blocks[i]["text"]) + len(rendered_blocks[j]["text"])) / 2
        for i, j, similarity in matches
    )
    source_characters = sum(len(block["text"]) for block in source_blocks)
    source_images, rendered_images = _image_sources(source_elements), _image_sources(rendered_elements)

    clip = _clip_similarity(
        _inpaint_text(original_screenshot, [source_blocks[i] for i, _, _ in matches], source_page_width, source_page_height),
        _inpaint_text(rendered_screenshot, [rendered_blocks[j] for _, j, _ in matches], source_page_width, source_page_height),
    )
    block_match = matched_area / total_area if total_area else None
    text = _mean([similarity for _, _, similarity in matches])
    position = _mean([max(0.0, 1.0 - offset) for offset in offsets])
    color = _mean(colors)
    element_scores = [block_match, text, position, color]
    # Design2Code averages the five scores equally; with no matched blocks only CLIP counts.
    design2code_overall = (
        0.2 * (sum(element_scores) + clip) if all(score is not None for score in element_scores) else 0.2 * clip
    )

    return {
        "design2code_overall": design2code_overall,
        "element_preservation": {
            "block_match": block_match,
            "text_block_recall": _ratio(len(matches), len(source_blocks)),
            "text_block_precision": _ratio(len(matches), len(rendered_blocks)),
            "image_recall": _ratio(len(source_images & rendered_images), len(source_images)),
            "source_text_blocks": len(source_blocks),
            "rendered_text_blocks": len(rendered_blocks),
            "matched_text_blocks": len(matches),
            "source_images": len(source_images),
            "matched_images": len(source_images & rendered_images),
        },
        "text_preservation": {
            "text_similarity": text,
            "exact_text_recall": _ratio(sum(similarity == 1.0 for _, _, similarity in matches), len(source_blocks)),
            "character_recall": matched_characters / source_characters if source_characters else None,
        },
        "layout_accuracy": {
            "position": position,
            "mean_center_offset_px": _mean(
                [
                    _center_offset_px(source_blocks[i], rendered_blocks[j], source_page_width, source_page_height)
                    for i, j, _ in matches
                ]
            ),
        },
        "visual_similarity": {
            "ssim": ssim,
            "clip": clip,
            "text_color": color,
        },
        "maml_validity": validity,
    }


def headline_scores(report: dict[str, Any]) -> dict[str, Any]:
    """Scores copied into run_metadata.json and benchmark summaries. SSIM stays in its own field."""
    return {
        "design2code_overall": report["design2code_overall"],
        "block_match": report["element_preservation"]["block_match"],
        "text": report["text_preservation"]["text_similarity"],
        "position": report["layout_accuracy"]["position"],
        "color": report["visual_similarity"]["text_color"],
        "clip": report["visual_similarity"]["clip"],
        "text_block_recall": report["element_preservation"]["text_block_recall"],
        "source_id_coverage": report["maml_validity"]["source_id_coverage"],
    }
