"""Experiment: measure where LLM generation time goes for one saved page.

The same page is sent to the model with different inputs and output formats, so the effect of
input size and output size can be separated. Each call records input, output and reasoning
tokens from the API, the time to the first output token, and the total time.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import re
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
# Running `python evaluation/measure_generation.py` puts evaluation/ on the path, not the project root.
sys.path.insert(0, str(PROJECT_ROOT))

import litellm  # noqa: E402
from lxml import html as lxml_html  # noqa: E402

from maml_pipeline.config import load_settings  # noqa: E402
from maml_pipeline.generation.prompt_builder import build_translation_prompt, load_system_prompt  # noqa: E402
from maml_pipeline.models import SourceElement, SourceInventory  # noqa: E402


PROMPTS_DIR = Path(__file__).with_name("prompts")
RESULTS_DIR = Path(__file__).with_name("latency_runs")
_SOURCE_FIELDS = {field.name for field in dataclasses.fields(SourceElement)}

# Computed-style values that are CSS defaults. Dropping them removes no information.
_DEFAULT_STYLES = {
    "fontStyle": {"normal"},
    "fontWeight": {"400"},
    "letterSpacing": {"normal"},
    "lineHeight": {"normal"},
    "textAlign": {"start"},
    "boxShadow": {"none"},
    "objectFit": {"fill"},
    "borderRadius": {"0px"},
    "padding": {"0px"},
    "backgroundColor": {"rgba(0, 0, 0, 0)", "transparent"},
}
# Attributes kept when the DOM is reduced to the HTML relevant for translation.
_KEPT_ATTRIBUTES = {"href", "src", "alt", "title", "aria-label", "role", "placeholder", "type", "value"}
_REMOVED_TAGS = "//script|//style|//noscript|//template|//svg|//link|//meta|//iframe|//comment()"

# Each variant pairs a system prompt with an input builder. Only one factor changes between the
# first variant and each of the next two, so their time differences can be attributed.
VARIANTS = {
    "current": ("prompt_v001.txt", "current"),
    "reduced_input": ("prompt_v001.txt", "reduced"),
    "decisions_output": ("prompt_decisions_v001.txt", "current"),
    "reduced_input_decisions_output": ("prompt_decisions_v001.txt", "reduced"),
}


def _load_inventory(run_dir: Path) -> SourceInventory:
    data = json.loads((run_dir / "source_inventory.json").read_text(encoding="utf-8"))
    elements = [
        # Inventories saved before visible_in_capture existed only recorded visible elements.
        SourceElement(**{k: v for k, v in {"visible_in_capture": e.get("visible", True), **e}.items() if k in _SOURCE_FIELDS})
        for e in data["elements"]
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


def _is_default(name: str, value: str) -> bool:
    return value in _DEFAULT_STYLES.get(name, set()) or (name == "border" and value.startswith("0px"))


def reduce_inventory(inventory: SourceInventory) -> SourceInventory:
    """Keep the same evidence with less text: drop items the prompt says to ignore, default styles, and decimals."""
    elements = [
        dataclasses.replace(
            element,
            x=round(element.x),
            y=round(element.y),
            width=round(element.width),
            height=round(element.height),
            styles={name: value for name, value in element.styles.items() if not _is_default(name, value)},
        )
        for element in inventory.elements
        if element.visible_in_capture
    ]
    return dataclasses.replace(inventory, elements=elements)


def relevant_html(page_html: str) -> str:
    """The page DOM without scripts, styles, SVG, metadata or presentational attributes."""
    document = lxml_html.fromstring(page_html)
    for node in document.xpath(_REMOVED_TAGS):
        node.drop_tree()
    for element in document.iter():
        if isinstance(element.tag, str):
            for attribute in list(element.attrib):
                if attribute not in _KEPT_ATTRIBUTES:
                    del element.attrib[attribute]
    return re.sub(r"\s+", " ", lxml_html.tostring(document, encoding="unicode"))


def _estimate_tokens(text: str) -> int:
    """About 4 characters per token. Only used for prompts that are not sent; calls record real counts."""
    return len(text) // 4


def call_model(system_prompt: str, user_prompt: str, settings: Any) -> dict[str, Any]:
    """Stream one completion and time it. Uses the same model, key and gateway as the pipeline."""
    started = time.perf_counter()
    first_token_at = None
    parts: list[str] = []
    usage = None
    stream = litellm.completion(
        model=settings.model,
        api_key=settings.api_key,
        api_base=settings.api_base,
        messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
        stream=True,
        stream_options={"include_usage": True},
    )
    for chunk in stream:
        if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
            if first_token_at is None:
                first_token_at = time.perf_counter()
            parts.append(chunk.choices[0].delta.content)
        if getattr(chunk, "usage", None):
            usage = chunk.usage
    finished = time.perf_counter()

    text = "".join(parts)
    details = getattr(usage, "completion_tokens_details", None) if usage else None
    first = (first_token_at or finished) - started
    try:
        elements = len(json.loads(text.strip().removeprefix("```json").removeprefix("```").removesuffix("```"))["elements"])
    except (json.JSONDecodeError, KeyError, TypeError):
        elements = None
    return {
        "input_tokens": getattr(usage, "prompt_tokens", None),
        "output_tokens": getattr(usage, "completion_tokens", None),
        "reasoning_tokens": getattr(details, "reasoning_tokens", None),
        "seconds_to_first_token": round(first, 3),
        "seconds_writing": round(finished - (first_token_at or finished), 3),
        "seconds_total": round(finished - started, 3),
        "output_characters": len(text),
        "output_whitespace_share": round(sum(c.isspace() for c in text) / len(text), 3) if text else None,
        "json_valid": elements is not None,
        "elements_returned": elements,
        "response": text,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Measure LLM generation time for one saved run.")
    parser.add_argument("run_dir", type=Path, help="A saved run folder containing source_inventory.json")
    parser.add_argument("--variants", nargs="+", choices=list(VARIANTS), default=list(VARIANTS))
    parser.add_argument("--repeats", type=int, default=2, help="Calls per variant (default 2)")
    parser.add_argument("--dry-run", action="store_true", help="Only report prompt sizes; make no model calls")
    args = parser.parse_args()

    inventory = _load_inventory(args.run_dir)
    inputs = {
        "current": build_translation_prompt(inventory),
        "reduced": build_translation_prompt(reduce_inventory(inventory)),
    }
    sizes = {name: _estimate_tokens(text) for name, text in inputs.items()}
    page_html_path = args.run_dir / "rendered_source.html"
    if page_html_path.exists():
        page_html = page_html_path.read_text(encoding="utf-8")
        # Not sent to the model: the prompt rules refer to source IDs, which raw HTML does not have.
        sizes["full_dom"] = _estimate_tokens(page_html)
        sizes["relevant_html_only"] = _estimate_tokens(relevant_html(page_html))
    print("Estimated input tokens (characters / 4):", json.dumps(sizes), flush=True)
    if args.dry_run:
        return 0

    settings = load_settings(PROJECT_ROOT)
    out_dir = RESULTS_DIR / f"{args.run_dir.name}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    out_dir.mkdir(parents=True)
    calls: list[dict[str, Any]] = []
    # Interleave variants so that gateway load changes over time affect all of them alike.
    for repeat in range(1, args.repeats + 1):
        for variant in args.variants:
            prompt_file, input_name = VARIANTS[variant]
            system_prompt, _, _ = load_system_prompt(PROMPTS_DIR / prompt_file)
            print(f"[{variant} #{repeat}] calling {settings.model} ...", flush=True)
            try:
                result = call_model(system_prompt, inputs[input_name], settings)
            except Exception as exc:
                result = {"error": f"{type(exc).__name__}: {exc}"}
            (out_dir / f"{variant}_{repeat}.txt").write_text(result.pop("response", ""), encoding="utf-8")
            calls.append({"variant": variant, "repeat": repeat, **result})
            print(f"  {json.dumps({k: v for k, v in result.items()})}", flush=True)

    summary = {}
    for variant in args.variants:
        done = [call for call in calls if call["variant"] == variant and "error" not in call]
        summary[variant] = {
            key: round(statistics.mean(call[key] for call in done), 3)
            for key in ("input_tokens", "output_tokens", "reasoning_tokens", "seconds_to_first_token", "seconds_writing", "seconds_total")
            if done and all(isinstance(call.get(key), (int, float)) for call in done)
        }
        summary[variant]["successful_calls"] = len(done)
    (out_dir / "results.json").write_text(
        json.dumps({"run": args.run_dir.name, "model": settings.model, "estimated_input_tokens": sizes, "summary": summary, "calls": calls}, indent=2),
        encoding="utf-8",
    )
    print("\nMean per variant:", flush=True)
    for variant, values in summary.items():
        print(f"  {variant}: {json.dumps(values)}", flush=True)
    print(f"Results: {out_dir / 'results.json'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
