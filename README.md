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
   python -m pip install --upgrade pip
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

## 4. Important files and functions

**Page fetcher:** `maml_pipeline/extraction/browser_capture.py`, `capture_page()`
- Loads the page in Chrome, scrolls until the page height stops growing (up to 20 steps), then screenshots the full page (capped at 16,000 px).
- Runs JavaScript in the page that walks every element and text node and records visible text, images, controls and boxes with a background, border or shadow.
- **Input:** URL, run folder, viewport size, headless flag. **Output:** `PageCapture`.

**Source inventory builder:** `maml_pipeline/extraction/source_inventory.py`, `build_source_inventory()`
- Keeps content elements first and fills any remaining budget with containers, then restores page order.
- Adds a warning when the 350-element cap cuts elements.
- **Input:** `PageCapture`, element cap. **Output:** `SourceInventory`.

**Prompt builder:** `maml_pipeline/generation/prompt_builder.py`, `load_system_prompt()` and `build_translation_prompt()`
- Loads the prompt file and returns its text and version name (the file name).
- Converts the inventory to compact JSON with empty fields removed.
- **Input:** prompt path, `SourceInventory`. **Output:** system prompt text and page prompt text.

**Translation agent:** `maml_agent/agent.py`, `build_translation_agent()`, and `maml_agent/runner.py`, `run_translation_agent()`
- Builds a tool-free ADK `LlmAgent` using LiteLLM with the configured model, key and gateway.
- Runs it once in a new in-memory session and returns the final text. Raises an error if the reply is empty.
- **Input:** page prompt, settings, system prompt. **Output:** raw response text.

**Translation coordinator:** `maml_pipeline/generation/translator.py`, `translate_inventory()`
- Calls the agent, parses the response and serializes the plan.
- **Input:** `SourceInventory`, settings, prompts. **Output:** plan, MAML objects, raw response.

**Serializer:** `maml_pipeline/generation/serializer.py`, `serialize_plan()` and `to_jsonl()`
- Resolves `text_source_id`, `link_source_id`, `aria_label_source_id`, `placeholder_source_id`, `options_source_id` and `src_source_id` to exact inventory values.
- Collects every referenced ID into the element's `source_ids` so the validator can check it.
- **Input:** plan, `SourceInventory`. **Output:** list of MAML objects (JSON-lines text from `to_jsonl()`).

**Validator:** `maml_pipeline/validation/validator.py`, `validate_maml()`
- Combines the schema checks (`validate_schema()`) and the source-preservation checks (`validate_preservation()`).
- The run is valid only when there are no errors. Warnings do not stop it.
- **Input:** MAML objects, `SourceInventory`. **Output:** `ValidationReport`.

**Repair:** `maml_pipeline/validation/deterministic_repair.py`, `repair_maml()`
- Normalizes `display`, converts geometry strings like `"12px"` to numbers, and renames duplicate IDs.
- **Input:** MAML objects. **Output:** repaired objects and a list of changes.

**Renderer:** `maml_pipeline/rendering/renderer.py`, `render_maml()`
- Writes one absolutely positioned HTML element per MAML element, sorted by `z`, and wraps linked elements in `<a>`.
- Converts `script` elements to JavaScript with `convert_mamlscript()` in `mamlscript.py`.
- **Input:** MAML objects, output path. **Output:** `RenderResult` and `rendered.html`.

**Visual comparison:** `maml_pipeline/evaluation/visual_metrics.py`, `capture_rendered_page()` and `compare_screenshots()`
- Screenshots the rendered HTML in Chrome.
- Calculates grayscale SSIM between the two screenshots and saves a difference image.
- **Input:** HTML path, screenshot paths. **Output:** capture dimensions, SSIM report.

**Orchestrator:** `maml_pipeline/pipeline.py`, `run_pipeline()`
- Runs every stage, saves every artifact and times each stage.
- Always writes `run_metadata.json`, including the failure stage and error when a run fails.
- **Input:** URL, output folder, settings, headless flag, prompt path. **Output:** `PipelineResult`.

**Benchmark:** `evaluation/run_benchmark.py`, `main()`
- Runs the pipeline once per benchmark URL, each in its own subprocess.
- Reads each run's metadata and writes one summary file.
- **Input:** `evaluation/benchmark_urls.json`. **Output:** run folders and a benchmark summary.

## 5. Current known issues

**Evaluation**
- **SSIM scores in the saved runs are not valid.** In all six completed runs (Nov 2–3), `rendered.png` is a Chrome "Access to the file was denied" page instead of the rendered MAML. The `rendered.html` files themselves are fine. The likely cause is that Chrome cannot read files under `~/Desktop`, but this is not confirmed. The pipeline does not check that it loaded the right page before taking the screenshot.
- **SSIM alone hides missing content.** Screenshots are padded with white, so content missing at the bottom of a white page barely lowers the score.
- **Completed runs always report 0 missing elements.** Missing elements are a validation error, so any run with one stops. Coverage also counts IDs listed in `source_ids`, even if their content is never rendered (4 text sources on the Stripe run).
- **No comparison with MAML2023 yet.** This repository uses its own renderer and MAML schema, not MAML2023's.

**Extraction**
- **The page background is never captured.** `<body>` and `<html>` are skipped, so dark pages render as white text on a white page (seen on PM Interview and Medium).
- **Screenshots are clipped at the bottom.** Chrome's window size includes the browser frame, so about 143 px is cut from each original screenshot.
- **Long pages are cut.** The 350-element cap drops elements from the bottom of long pages with only a warning (the Stripe render is about 6,000 px tall against a 16,000 px original). Scrolling covers about 12,000 px, so lazy content further down never loads.
- **Some content is not extracted:** CSS background images, inline SVG icons, video, canvas and iframes.
- **Nested controls can be recorded twice.** The nested-control check in `addControl` never triggers.
- **Bot-protection pages are translated as normal pages.** The Medium run translated a Cloudflare "Just a moment..." page and was marked completed. The final URL after redirects is not saved.

**LLM generation**
- **Generation is slow.** It takes 40–315 seconds per page in the saved runs, most of the total run time. Time grows with output size because the model writes back positions and styles it was given.
- **Token usage is not logged**, and no output-token limit, JSON mode, temperature or retry is set.
- **One invalid source ID stops the whole run** before validation or repair can run.

**Validation, repair and rendering**
- **Repair is limited and runs once.** `MAML_MAX_REPAIR_ATTEMPTS` is loaded but not used, and there is no LLM repair.
- **Accessible names are dropped.** `ariaLabel` is only allowed on buttons and text fields, so the renderer ignores it on text, images and shapes.
- **Pages are not responsive.** Every element is positioned for one fixed viewport width.
- **Rendered text can wrap and overlap.** Web fonts from the original page are not loaded.
- **Interactions are not generated.** The prompt never asks for `script` elements, so MAMLScript conversion is never used, and carousels render as empty boxes.

**Reliability**
- **No full benchmark has completed.** Both saved benchmark summaries show 0/10, the second because Chrome exited at startup.
- **Two runs on the same site in the same second collide.** Run folder names use one-second timestamps, and the second run fails before any metadata is written.
- **The project has no tests and no lock file**, and `.gitignore` does not exclude `evaluation/runs/`.
