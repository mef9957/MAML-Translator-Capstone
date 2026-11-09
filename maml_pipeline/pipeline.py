# Purpose: Run the fixed HTML-to-MAML workflow in order and save every artifact for inspection.

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any
from urllib.parse import urlparse

from maml_pipeline import __version__
from maml_pipeline.config import Settings
from maml_pipeline.evaluation.translation_metrics import evaluate_translation, headline_scores, maml_validity
from maml_pipeline.evaluation.visual_metrics import capture_rendered_page, compare_screenshots
from maml_pipeline.extraction.browser_capture import capture_page
from maml_pipeline.extraction.source_inventory import build_source_inventory
from maml_pipeline.generation.prompt_builder import build_translation_prompt, load_system_prompt
from maml_pipeline.generation.serializer import serialize_plan, to_jsonl
from maml_pipeline.generation.translator import parse_translation_response, request_translation
from maml_pipeline.models import PipelineResult
from maml_pipeline.rendering.renderer import render_maml
from maml_pipeline.validation.deterministic_repair import repair_maml
from maml_pipeline.validation.validator import validate_maml


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_text(path: Path, value: str) -> None:
    path.write_text(value, encoding="utf-8")


def _run_name(url: str) -> str:
    host = urlparse(url).netloc or "page"
    safe_host = re.sub(r"[^a-zA-Z0-9_-]+", "_", host).strip("_")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{safe_host}_{timestamp}"


def run_pipeline(
    url: str,
    output_root: Path,
    settings: Settings,
    *,
    headless: bool = True,
    prompt_path: Path | None = None,
) -> PipelineResult:
    """Execute capture, inventory, one model call, validation, repair, rendering, and evaluation."""
    run_dir = output_root / _run_name(url)
    run_dir.mkdir(parents=True, exist_ok=False)
    total_started = perf_counter()
    stage = "initialization"
    stage_started = total_started
    metadata: dict[str, Any] = {
        "status": "running",
        "url": url,
        "pipeline_version": __version__,
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "model": settings.model,
        "model_calls": 0,
        "prompt_version": None,
        "prompt_file": None,
        "viewport": {
            "width": settings.viewport_width,
            "height": settings.viewport_height,
        },
        "max_inventory_elements": settings.max_inventory_elements,
        "inventory_element_count": None,
        "maml_element_count": None,
        "missing_source_element_count": None,
        "missing_source_ids": [],
        "unsupported_feature_count": None,
        "failure_stage": None,
        "error": None,
        "timings_seconds": {},
        "ssim": None,
        "evaluation": None,
    }

    def begin(name: str) -> None:
        nonlocal stage, stage_started
        stage = name
        stage_started = perf_counter()

    def finish() -> None:
        metadata["timings_seconds"][stage] = round(perf_counter() - stage_started, 6)

    try:
        system_prompt, prompt_version, selected_prompt_path = load_system_prompt(prompt_path)
        metadata["prompt_version"] = prompt_version
        metadata["prompt_file"] = str(selected_prompt_path)
        _write_text(run_dir / "system_prompt.txt", system_prompt + "\n")

        begin("extraction")
        capture = capture_page(
            url,
            run_dir,
            viewport_width=settings.viewport_width,
            viewport_height=settings.viewport_height,
            headless=headless,
        )
        _write_text(run_dir / "rendered_source.html", capture.rendered_html)
        # Every extracted element before the inventory cap. Evaluation compares against this
        # list, so elements the cap removes are counted as missing.
        _write_json(run_dir / "source_elements.json", capture.raw_elements)
        inventory = build_source_inventory(capture, settings.max_inventory_elements)
        _write_json(run_dir / "source_inventory.json", inventory.to_dict())
        page_prompt = build_translation_prompt(inventory)
        _write_text(run_dir / "page_prompt.txt", page_prompt + "\n")
        metadata["inventory_element_count"] = len(inventory.elements)
        metadata["inventory_warnings"] = inventory.warnings
        finish()

        begin("llm_generation")
        # Counts attempted calls, so a failed or rejected call is still recorded.
        metadata["model_calls"] = 1
        raw_response = request_translation(page_prompt, settings, system_prompt)
        # Saved before parsing so an invalid response can still be inspected.
        _write_text(run_dir / "raw_model_response.txt", raw_response)
        plan = parse_translation_response(raw_response)
        _write_json(run_dir / "translation_plan.json", plan)
        maml_objects = serialize_plan(plan, inventory)
        generated_objects = maml_objects
        _write_text(run_dir / "generated.maml", to_jsonl(maml_objects))
        metadata["maml_element_count"] = max(len(maml_objects) - 1, 0)
        metadata["unsupported_feature_count"] = len(plan.get("unsupported_features") or [])
        finish()

        begin("validation_and_repair")
        report = validate_maml(maml_objects, inventory)
        repair_log: list[str] = []
        if not report.valid:
            maml_objects, repair_log = repair_maml(maml_objects)
            _write_text(run_dir / "repaired.maml", to_jsonl(maml_objects))
            report = validate_maml(maml_objects, inventory)

        missing_ids = sorted(
            {
                source_id
                for issue in [*report.errors, *report.warnings]
                if issue.code == "unrepresented_source_elements"
                for source_id in issue.source_ids
            }
        )
        metadata["missing_source_ids"] = missing_ids
        metadata["missing_source_element_count"] = len(missing_ids)
        metadata["validation_error_count"] = len(report.errors)
        metadata["validation_warning_count"] = len(report.warnings)
        _write_json(
            run_dir / "validation_report.json",
            {**report.to_dict(), "deterministic_repairs": repair_log},
        )
        finish()
        if not report.valid:
            error_summary = "; ".join(issue.message for issue in report.errors[:5])
            raise RuntimeError(
                "Generated MAML still has validation errors after deterministic repair: "
                + error_summary
            )

        begin("rendering")
        final_maml_path = run_dir / "final.maml"
        _write_text(final_maml_path, to_jsonl(maml_objects))
        render_result = render_maml(maml_objects, run_dir / "rendered.html")
        _write_json(run_dir / "render_report.json", render_result.to_dict())
        finish()

        begin("rendered_screenshot")
        rendered_screenshot_path = run_dir / "rendered.png"
        metadata["rendered_capture"], rendered_elements = capture_rendered_page(
            Path(render_result.html_path),
            rendered_screenshot_path,
            viewport_width=settings.viewport_width,
            viewport_height=settings.viewport_height,
        )
        _write_json(run_dir / "rendered_elements.json", rendered_elements)
        finish()

        begin("evaluation")
        comparison = compare_screenshots(
            Path(capture.screenshot_path),
            rendered_screenshot_path,
            run_dir / "visual_diff.png",
        )
        _write_json(run_dir / "ssim_report.json", comparison)
        evaluation = evaluate_translation(
            source_elements=capture.raw_elements,
            rendered_elements=rendered_elements,
            source_page_width=capture.page_width,
            source_page_height=capture.page_height,
            original_screenshot=Path(capture.screenshot_path),
            rendered_screenshot=rendered_screenshot_path,
            ssim=comparison["ssim"],
            validity=maml_validity(generated_objects, maml_objects, inventory, len(repair_log)),
        )
        evaluation_report_path = run_dir / "evaluation_report.json"
        _write_json(evaluation_report_path, evaluation)
        metadata["ssim"] = comparison["ssim"]
        metadata["evaluation"] = headline_scores(evaluation)
        finish()

        metadata["status"] = "completed"
        return PipelineResult(
            run_directory=str(run_dir),
            maml_path=str(final_maml_path),
            html_path=render_result.html_path,
            rendered_screenshot_path=str(rendered_screenshot_path),
            validation_report_path=str(run_dir / "validation_report.json"),
            evaluation_report_path=str(evaluation_report_path),
            metadata_path=str(run_dir / "run_metadata.json"),
            model_calls=int(metadata["model_calls"]),
            ssim=float(comparison["ssim"]),
        )
    except Exception as exc:
        if stage not in metadata["timings_seconds"]:
            metadata["timings_seconds"][stage] = round(perf_counter() - stage_started, 6)
        metadata["status"] = "failed"
        metadata["failure_stage"] = stage
        metadata["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        metadata["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        metadata["timings_seconds"]["total"] = round(perf_counter() - total_started, 6)
        _write_json(run_dir / "run_metadata.json", metadata)
