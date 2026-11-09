# Fall 2026 HTML-to-MAML Translation Pipeline

## 1. What does the project do?

**Overall Goal:** To develop and evaluate an LLM-based agentic workflow that translates existing webpages into MAML while preserving their content, structure, and visual layout. The project will investigate the effectiveness of this approach and compare its performance with the existing MAML2023 rule-based translator, which will serve as the baseline and demonstrate the limitations motivating the new approach.

**What the current implementation does:** It takes one webpage URL and:

1. Opens the page in headless Chrome and records every visible text, image, control and styled box, with its position and computed styles.
2. Sends that list to a single Google ADK translation agent (one LLM call), which returns a MAML element plan that refers to page content by ID only.
3. Replaces those IDs with the exact text, links and image URLs from the page, then validates and repairs the result deterministically.
4. Renders the MAML into a standalone HTML page and compares a screenshot of it with the original page using SSIM.

Only the translation step uses an LLM. Every other step is deterministic Python. The MAML2023 baseline is not part of this repository.

## 2. How to install and run it

**Requirements:** Python 3.12.8 (set in `.python-version`), Google Chrome, and an API key for the LLM gateway.

1. Select Python 3.12.8 (if you use pyenv):
   ```bash
   pyenv local 3.12.8
   ```
2. Create the virtual environment:
   ```bash
   python -m venv .venv
   ```
3. Activate it:
   ```bash
   source .venv/bin/activate
   ```
4. Install the dependencies:
   ```bash
   python -m pip install -r requirements.txt
   ```
5. Create a `.env` file in the project root. Shell environment variables override `.env` values.

   | Variable | Default | Purpose |
   |---|---|---|
   | `PORTKEY_API_KEY` | none | API key (`OPENAI_API_KEY` or `GOOGLE_API_KEY` are also accepted) |
   | `MAML_API_BASE` | `https://ai-gateway.apps.cloud.rt.nyu.edu/v1` | LLM gateway URL |
   | `MAML_MODEL` | `openai/@vertexai/gemini-2.5-pro` | Model name passed to LiteLLM |
   | `MAML_VIEWPORT_WIDTH` | `1200` | Browser width in pixels |
   | `MAML_VIEWPORT_HEIGHT` | `900` | Browser height in pixels |
   | `MAML_MAX_INVENTORY_ELEMENTS` | `350` | Maximum number of page elements sent to the LLM |

6. Translate one page:
   ```bash
   python -m maml_pipeline https://example.com
   ```
   The URL must start with `http://` or `https://`.

   The current default prompt is `evaluation/prompts/prompt_v001.txt`. You can run an alternate prompt by adding a new file to `evaluation/prompts/` and passing it with `--prompt-file`:
   ```bash
   python -m maml_pipeline https://example.com --prompt-file evaluation/prompts/prompt_v002.txt
   ```
   The run stops if that file does not exist.

   Other options:
   - `--show-browser` shows Chrome during capture instead of running headless.
   - `--output-dir <path>` changes where run folders are saved (default: `outputs/runs`).

7. Run the benchmark (the 10 URLs in `evaluation/benchmark_urls.json`):
   ```bash
   python evaluation/run_benchmark.py
   ```
   Pages run one after another. A failed page does not stop the rest. Each page gets its own folder in `evaluation/runs/`, and a summary is saved to `evaluation/benchmark_summaries/benchmark_<timestamp>.json`. The script exits with code 1 if any page failed.

8. (Optional) Inspect only the translation agent in the Google ADK interface:
   ```bash
   .venv/bin/adk web
   ```
   Then choose `maml_agent`.

**Output files:** each run creates a folder named `<host>_<UTC timestamp>` (for example `www_loc_gov_20261103T051114Z`) containing:

| File | Contents |
|---|---|
| `system_prompt.txt` | System prompt used for the run |
| `original.png` | Screenshot of the original page |
| `rendered_source.html` | Page HTML after JavaScript ran |
| `source_inventory.json` | Extracted page elements with IDs, positions and styles |
| `page_prompt.txt` | Inventory prompt sent to the LLM |
| `raw_model_response.txt` | Unedited LLM response |
| `translation_plan.json` | Parsed LLM element plan |
| `generated.maml` | MAML before validation |
| `repaired.maml` | MAML after deterministic repair (only if the first validation failed) |
| `validation_report.json` | Errors, warnings and repairs applied |
| `final.maml` | Final MAML output |
| `rendered.html` | MAML rendered as HTML |
| `render_report.json` | Renderer result and warnings |
| `rendered.png` | Screenshot of the rendered HTML |
| `visual_diff.png` | Difference image between the two screenshots |
| `ssim_report.json` | SSIM score and image dimensions |
| `run_metadata.json` | Status, failure stage, error, element counts, per-stage timings and SSIM. Written for both successful and failed runs |

## 3. Architecture and data flow

**User ⇒ CLI Entry Point ⇒ Pipeline Orchestrator ⇒ Page Fetcher ⇒ Source Inventory Builder ⇒ Prompt Builder ⇒ MAML Translation Agent (single LLM call) ⇒ Response Parser ⇒ Deterministic Serializer ⇒ Deterministic Validator ⇒ Deterministic Repair (once) ⇒ Re-Validator ⇒ MAML Renderer ⇒ Rendered Page Screenshot ⇒ SSIM Comparison ⇒ Final .maml output**

1. **User:** enters the URL of the website to translate with `python -m maml_pipeline <url>`.
2. **CLI entry point:** checks the URL and loads settings from `.env`. Done in `cli.py` and `config.py`.
3. **Pipeline orchestrator:** runs every stage in order, times each one and saves all the artifacts to the run folder. If a stage fails, it records the failing stage and error in `run_metadata.json`. Done in `pipeline.py`.
4. **Page fetcher:** opens the page in headless Chrome, scrolls to trigger lazy-loaded content, takes the `original.png` screenshot and records every visible text, image, control and styled box with its position and styles. Done in `browser_capture.py`. Output: a `PageCapture` (page HTML, screenshot path, page size and the list of raw elements).
5. **Source inventory builder:** removes empty elements and keeps at most 350 elements, keeping content ahead of decorative boxes. Every element keeps an ID such as `src_00001`. Done in `source_inventory.py`. Output: `source_inventory.json`.
6. **Prompt builder:** loads the versioned system prompt and compresses the inventory into compact JSON, dropping empty fields. Done in `prompt_builder.py`. Output: `system_prompt.txt` and `page_prompt.txt`.
7. **MAML translation agent:** one Google ADK agent with no tools, so exactly one LLM call. It decides which elements to keep, each element's MAML type, position, layer and style, and refers to content only by source ID. Done in `maml_agent/agent.py` and `maml_agent/runner.py`. Output: `raw_model_response.txt`.
8. **Response parser:** strips Markdown code fences and parses the reply as JSON with an `elements` list. Done in `response_parser.py`. Output: `translation_plan.json`.
9. **Deterministic serializer:** replaces source IDs with the exact text, links, accessible names, placeholders, options and image URLs from the inventory, and writes canonical MAML. Done in `serializer.py`. Output: `generated.maml`.
10. **Deterministic validator:** checks the MAML structure (types, unique IDs, numeric geometry, required fields), checks that text, links and accessible names exactly match the source, and checks that every visible source element is included. Done in `schema_validator.py` and `preservation_validator.py`. Output: a validation report.
11. **Deterministic repair:** if validation fails, fixes invalid `display` values, numbers stored as strings and duplicate IDs. Runs once. Done in `deterministic_repair.py`. Output: `repaired.maml`.
12. **Re-validator:** validates again. If errors remain, the run stops. Output: `validation_report.json`.
13. **MAML renderer:** converts each MAML element into an absolutely positioned HTML element, layered by `z`. Done in `renderer.py`. Output: `final.maml`, `rendered.html` and `render_report.json`.
14. **Rendered page screenshot:** opens `rendered.html` in headless Chrome, waits up to 5 seconds for images and fonts, and takes a full-page screenshot. Done in `visual_metrics.py`. Output: `rendered.png`.
15. **SSIM comparison:** places both screenshots on a white canvas of the same size, calculates grayscale SSIM and saves a difference image. Done in `visual_metrics.py`. Output: `ssim_report.json` and `visual_diff.png`.
16. **Final .maml output:** `final.maml`, with the summary printed to the terminal and saved in `run_metadata.json`.

**Canonical MAML format:** the first line is `{"viewport_width": 1200}`. Each following line is one flat element with `type`, `id`, `source_ids`, `x`, `y`, `z`, `w`, `h`, `display` and its type-specific fields. Supported types are `text`, `shape`, `text-field`, `button`, `dropdown`, `image`, `carousel` and `script`. This schema is defined by this repository's validator and renderer and is not the MAML2023 format.


- **The project has no tests and no lock file**, and `.gitignore` does not exclude `evaluation/runs/`.
