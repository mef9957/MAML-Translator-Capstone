# Purpose: Provide the command-line entry point for translating one URL into MAML and HTML.

from __future__ import annotations

import argparse
import json
from pathlib import Path

from maml_pipeline.config import load_settings
from maml_pipeline.pipeline import run_pipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Translate a webpage URL into canonical MAML.")
    parser.add_argument("url", help="Complete http:// or https:// webpage URL")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("outputs/runs"),
        help="Directory where reproducible run folders are saved",
    )
    parser.add_argument(
        "--show-browser",
        action="store_true",
        help="Show Chrome during capture instead of using headless mode",
    )
    parser.add_argument(
        "--prompt-file",
        type=Path,
        default=None,
        help="Versioned system-prompt file; defaults to evaluation/prompts/prompt_v001.txt",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if not args.url.startswith(("http://", "https://")):
        raise SystemExit("URL must start with http:// or https://")

    project_root = Path(__file__).resolve().parents[1]
    settings = load_settings(project_root)
    result = run_pipeline(
        args.url,
        args.output_dir,
        settings,
        headless=not args.show_browser,
        prompt_path=args.prompt_file,
    )
    print(json.dumps(result.to_dict(), indent=2))


if __name__ == "__main__":
    main()
