"""Experiment: use Trafilatura to normalize and compare the text of source pages and their MAML renders."""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import trafilatura


RUNS_DIR = Path(__file__).with_name("runs")
SUMMARIES_DIR = Path(__file__).with_name("benchmark_summaries")
# Order-sensitive comparison is quadratic, so it is skipped for very long pages.
MAX_SEQUENCE_WORDS = 5000
_WORD = re.compile(r"\w+", re.UNICODE)


def _words(text: str | None) -> list[str]:
    """Normalize Unicode forms and case, then split into words without punctuation."""
    return _WORD.findall(unicodedata.normalize("NFKC", text or "").lower())


def _overlap(reference: list[str], candidate: list[str]) -> dict[str, float | None]:
    """Word-count recall, precision and F1. Ignores order, because MAML renders elements in z order."""
    shared = sum((Counter(reference) & Counter(candidate)).values())
    recall = shared / len(reference) if reference else None
    precision = shared / len(candidate) if candidate else None
    f1 = 2 * recall * precision / (recall + precision) if recall and precision else None
    return {"recall": recall, "precision": precision, "f1": f1}


def _maml_text(run_dir: Path) -> str:
    """All text in the final MAML, whatever Trafilatura would keep."""
    lines = (run_dir / "final.maml").read_text(encoding="utf-8").splitlines()[1:]
    return "\n".join(json.loads(line).get("text", "") for line in lines if line.strip())


def compare_run(run_dir: Path) -> dict[str, Any]:
    source_html = (run_dir / "rendered_source.html").read_text(encoding="utf-8")
    maml_html = (run_dir / "rendered.html").read_text(encoding="utf-8")
    source_main = _words(trafilatura.extract(source_html))
    maml_main = _words(trafilatura.extract(maml_html))
    maml_all = _words(_maml_text(run_dir))
    sequence = (
        SequenceMatcher(None, source_main, maml_main, autojunk=False).ratio()
        if source_main and maml_main and max(len(source_main), len(maml_main)) <= MAX_SEQUENCE_WORDS
        else None
    )
    return {
        "source_main_content_words": len(source_main),
        "maml_main_content_words": len(maml_main),
        "maml_all_text_words": len(maml_all),
        # Trafilatura on both pages: compares what it judges to be main content on each.
        "main_vs_main": _overlap(source_main, maml_main),
        # Trafilatura only on the source, to define the important content; all MAML text as the candidate.
        "source_main_content_kept_in_maml": _overlap(source_main, maml_all)["recall"],
        "order_sensitive_similarity": sequence,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare source and MAML text with Trafilatura.")
    parser.add_argument("run_dirs", nargs="*", type=Path, help="Run folders (default: every run in evaluation/runs)")
    args = parser.parse_args()
    run_dirs = args.run_dirs or sorted(path for path in RUNS_DIR.iterdir() if path.is_dir())

    results = []
    for run_dir in run_dirs:
        if not all((run_dir / name).exists() for name in ("rendered_source.html", "rendered.html", "final.maml")):
            continue
        report = compare_run(run_dir)
        (run_dir / "trafilatura_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        results.append({"run": run_dir.name, **report})
        main_f1 = report["main_vs_main"]["f1"]
        kept = report["source_main_content_kept_in_maml"]
        print(
            f"{run_dir.name}: source main words={report['source_main_content_words']}, "
            f"MAML main words={report['maml_main_content_words']}, "
            f"main-vs-main F1={main_f1 if main_f1 is None else round(main_f1, 3)}, "
            f"source main content kept={kept if kept is None else round(kept, 3)}",
            flush=True,
        )

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    SUMMARIES_DIR.mkdir(parents=True, exist_ok=True)
    summary_path = SUMMARIES_DIR / f"trafilatura_{timestamp}.json"
    summary_path.write_text(json.dumps({"results": results}, indent=2), encoding="utf-8")
    print(f"Summary: {summary_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
