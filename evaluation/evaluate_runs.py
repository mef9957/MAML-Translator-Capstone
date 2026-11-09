"""Re-screenshot and re-score saved runs with the current evaluation, without calling the model."""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
# Running `python evaluation/evaluate_runs.py` puts evaluation/ on the path, not the project root.
sys.path.insert(0, str(PROJECT_ROOT))

from maml_pipeline.evaluation.translation_metrics import (  # noqa: E402
    evaluate_translation,
    headline_scores,
    maml_validity,
)
from maml_pipeline.evaluation.visual_metrics import capture_rendered_page, compare_screenshots  # noqa: E402
from maml_pipeline.models import SourceElement, SourceInventory  # noqa: E402


RUNS_DIR = Path(__file__).with_name("runs")
SUMMARIES_DIR = Path(__file__).with_name("benchmark_summaries")
REQUIRED_FILES = ("final.maml", "generated.maml", "rendered.html", "original.png", "source_inventory.json")
_SOURCE_FIELDS = {field.name for field in dataclasses.fields(SourceElement)}


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_maml(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _with_capture_flag(element: dict[str, Any]) -> dict[str, Any]:
    # Inventories saved before visible_in_capture existed only recorded visible elements.
    return {"visible_in_capture": element.get("visible", True), **element}


def _load_inventory(data: dict[str, Any]) -> SourceInventory:
    elements = [
        SourceElement(**{key: value for key, value in _with_capture_flag(element).items() if key in _SOURCE_FIELDS})
        for element in data["elements"]
    ]
    return SourceInventory(
        url=data["url"],
        title=data["title"],
        viewport_width=data["viewport_width"],
        page_width=data["page_width"],
        page_height=data["page_height"],
        screenshot_path=data["screenshot_path"],
        elements=elements,
        warnings=data.get("warnings", []),
    )


def rescore_run(run_dir: Path, viewport_width: int, viewport_height: int) -> dict[str, Any]:
    """Replace a run's rendered screenshot and evaluation files, and update its metadata."""
    inventory_data = _read_json(run_dir / "source_inventory.json")
    inventory = _load_inventory(inventory_data)
    # Runs saved before source_elements.json existed are scored against the capped inventory.
    source_elements_path = run_dir / "source_elements.json"
    source_elements = (
        _read_json(source_elements_path)
        if source_elements_path.exists()
        else [_with_capture_flag(element) for element in inventory_data["elements"]]
    )
    validation_path = run_dir / "validation_report.json"
    repair_count = len(_read_json(validation_path).get("deterministic_repairs", [])) if validation_path.exists() else 0

    capture_details, rendered_elements = capture_rendered_page(
        run_dir / "rendered.html",
        run_dir / "rendered.png",
        viewport_width=viewport_width,
        viewport_height=viewport_height,
    )
    _write_json(run_dir / "rendered_elements.json", rendered_elements)
    comparison = compare_screenshots(run_dir / "original.png", run_dir / "rendered.png", run_dir / "visual_diff.png")
    _write_json(run_dir / "ssim_report.json", comparison)
    evaluation = evaluate_translation(
        source_elements=source_elements,
        rendered_elements=rendered_elements,
        source_page_width=inventory.page_width,
        source_page_height=inventory.page_height,
        original_screenshot=run_dir / "original.png",
        rendered_screenshot=run_dir / "rendered.png",
        ssim=comparison["ssim"],
        validity=maml_validity(
            _read_maml(run_dir / "generated.maml"),
            _read_maml(run_dir / "final.maml"),
            inventory,
            repair_count,
        ),
    )
    _write_json(run_dir / "evaluation_report.json", evaluation)

    headline = headline_scores(evaluation)
    metadata_path = run_dir / "run_metadata.json"
    if metadata_path.exists():
        metadata = _read_json(metadata_path)
        metadata.update(
            {
                "ssim": comparison["ssim"],
                "evaluation": headline,
                "rendered_capture": capture_details,
                "evaluation_rescored_at_utc": datetime.now(timezone.utc).isoformat(),
            }
        )
        _write_json(metadata_path, metadata)
    return {"ssim": comparison["ssim"], **headline}


def main() -> int:
    parser = argparse.ArgumentParser(description="Re-score saved runs without calling the model.")
    parser.add_argument("run_dirs", nargs="*", type=Path, help="Run folders to score (default: every run in evaluation/runs)")
    args = parser.parse_args()
    run_dirs = args.run_dirs or sorted(path for path in RUNS_DIR.iterdir() if path.is_dir())

    results: list[dict[str, Any]] = []
    for run_dir in run_dirs:
        missing = [name for name in REQUIRED_FILES if not (run_dir / name).exists()]
        if missing:
            print(f"skipped {run_dir.name}: missing {', '.join(missing)}", flush=True)
            continue
        metadata_path = run_dir / "run_metadata.json"
        viewport = _read_json(metadata_path).get("viewport", {}) if metadata_path.exists() else {}
        try:
            scores = rescore_run(run_dir, viewport.get("width", 1200), viewport.get("height", 900))
        except Exception as exc:
            print(f"failed  {run_dir.name}: {type(exc).__name__}: {exc}", flush=True)
            results.append({"run": run_dir.name, "error": f"{type(exc).__name__}: {exc}"})
            continue
        results.append({"run": run_dir.name, **scores})
        print(
            f"scored  {run_dir.name}: overall={scores['design2code_overall']:.3f} "
            f"ssim={scores['ssim']:.3f} clip={scores['clip']:.3f}",
            flush=True,
        )

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    SUMMARIES_DIR.mkdir(parents=True, exist_ok=True)
    summary_path = SUMMARIES_DIR / f"rescore_{timestamp}.json"
    _write_json(summary_path, {"finished_at_utc": datetime.now(timezone.utc).isoformat(), "results": results})
    print(f"Summary: {summary_path}", flush=True)
    return 1 if any("error" in result for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
