"""Run the fixed website benchmark sequentially and retain each pipeline artifact."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
URLS_FILE = Path(__file__).with_name("benchmark_urls.json")
RUNS_DIR = Path(__file__).with_name("runs")
SUMMARIES_DIR = Path(__file__).with_name("benchmark_summaries")


def main() -> int:
    cases = json.loads(URLS_FILE.read_text(encoding="utf-8"))
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    results: list[dict] = []

    print(f"Running {len(cases)} benchmark pages into {RUNS_DIR}", flush=True)
    for index, case in enumerate(cases, start=1):
        before = {path for path in RUNS_DIR.iterdir() if path.is_dir()}
        command = [
            sys.executable,
            "-m",
            "maml_pipeline",
            case["url"],
            "--output-dir",
            str(RUNS_DIR),
        ]
        print(f"[{index}/{len(cases)}] {case['name']}: {case['url']}", flush=True)
        completed = subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        created = sorted(
            (path for path in RUNS_DIR.iterdir() if path.is_dir() and path not in before),
            key=lambda path: path.stat().st_mtime,
        )
        run_dir = created[-1] if created else None
        metadata_path = run_dir / "run_metadata.json" if run_dir else None
        metadata = {}
        if metadata_path and metadata_path.exists():
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))

        result = {
            "name": case["name"],
            "category": case["category"],
            "url": case["url"],
            "status": metadata.get("status", "failed" if completed.returncode else "completed"),
            "return_code": completed.returncode,
            "run_directory": str(run_dir) if run_dir else None,
            "failure_stage": metadata.get("failure_stage"),
            "error": metadata.get("error"),
            "ssim": metadata.get("ssim"),
            "evaluation": metadata.get("evaluation"),
            "inventory_element_count": metadata.get("inventory_element_count"),
            "maml_element_count": metadata.get("maml_element_count"),
            "missing_source_element_count": metadata.get("missing_source_element_count"),
        }
        results.append(result)

        if result["status"] == "completed":
            print(
                f"  completed | SSIM={result['ssim']} | "
                f"Design2Code={result['evaluation']['design2code_overall']} | "
                f"inventory={result['inventory_element_count']} | "
                f"missing={result['missing_source_element_count']}",
                flush=True,
            )
        else:
            print(f"  failed at {result['failure_stage'] or 'startup'}: {result['error'] or ''}", flush=True)
            details = (completed.stderr or completed.stdout).strip()
            if details:
                print("  " + details[-1200:].replace("\n", "\n  "), flush=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    SUMMARIES_DIR.mkdir(parents=True, exist_ok=True)
    summary_path = SUMMARIES_DIR / f"benchmark_{timestamp}.json"
    summary = {
        "started_by": "evaluation/run_benchmark.py",
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "total": len(results),
        "completed": sum(item["status"] == "completed" for item in results),
        "failed": sum(item["status"] != "completed" for item in results),
        "results": results,
    }
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(f"Summary: {summary_path}", flush=True)
    return 1 if summary["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
