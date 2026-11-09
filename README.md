# Fall 2026 HTML-to-MAML Translation Pipeline

## 1. What does the project do?

**Overall Goal:** To develop and evaluate an LLM-based agentic workflow that translates existing webpages into MAML while preserving their content, structure, and visual layout. The project will investigate the effectiveness of this approach and compare its performance with the existing MAML2023 rule-based translator, which will serve as the baseline and demonstrate the limitations motivating the new approach.

**What the current implementation does:** It takes one webpage URL and:

1. Opens the page in headless Chrome and records every visible text, image, control and styled box, with its position and computed styles.
2. Sends that list to a single Google ADK translation agent (one LLM call), which returns a MAML element plan that refers to page content by ID only.
3. Replaces those IDs with the exact text, links and image URLs from the page, then validates and repairs the result deterministically.
4. Renders the MAML into a standalone HTML page and scores it against the original page: the Design2Code element metrics (Block-Match, Text, Position, Color, CLIP), SSIM, and MAML validity.

Only the translation step uses an LLM. Every other step is deterministic Python. The MAML2023 baseline is not part of this repository.

## 2. How to install and run it

**Requirements:** Python 3.12.8 (set in `.python-version`), Google Chrome, and an API key for the LLM gateway. The first evaluation downloads the CLIP ViT-B/32 weights (about 350 MB) and caches them.

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

8. Re-score saved runs with the current evaluation, without calling the model:
   ```bash
   python evaluation/evaluate_runs.py
   ```
   This scores every run in `evaluation/runs/` (or only the run folders you pass). It replaces each run's `rendered.png`, `visual_diff.png`, `ssim_report.json`, `rendered_elements.json` and `evaluation_report.json`, updates the scores in `run_metadata.json`, and writes a summary to `evaluation/benchmark_summaries/rescore_<timestamp>.json`. Runs saved before `source_elements.json` existed are scored against their capped inventory.

9. Experiments (no pipeline changes; results are for the report):
   - **LLM latency:** sends one saved page to the model with the current input, a reduced input (no hidden elements, no default CSS values, whole-pixel positions), a decisions-only output format (`evaluation/prompts/prompt_decisions_v001.txt`), and both together. Each call records input, output and reasoning tokens from the API, time to the first output token, and total time. Results go to `evaluation/latency_runs/`. `--dry-run` only compares input sizes, including the full DOM and the DOM reduced to its relevant HTML.
     ```bash
     python evaluation/measure_generation.py evaluation/runs/www_weather_gov_20261103T044617Z --repeats 2
     ```
   - **Trafilatura:** extracts and normalizes the main-content text of `rendered_source.html` and `rendered.html`, and compares them by word counts (order is ignored because MAML renders in z order). It reports both pages' main content against each other and how much of the source's main content appears anywhere in the MAML. Writes `trafilatura_report.json` per run.
     ```bash
     python evaluation/compare_trafilatura.py
     ```

10. (Optional) Inspect only the translation agent in the Google ADK interface:
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
| `source_elements.json` | Every extracted page element before the 350-element cap (used for evaluation) |
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
| `rendered_elements.json` | Elements extracted from the rendered HTML with the same script as the source page |
| `visual_diff.png` | Difference image between the two screenshots |
| `ssim_report.json` | SSIM score and image dimensions |
| `evaluation_report.json` | Element preservation, text preservation, layout accuracy, visual similarity and MAML validity scores |
| `run_metadata.json` | Pipeline version, status, failure stage, error, element counts, per-stage timings, SSIM and the headline evaluation scores. Written for both successful and failed runs |

## 3. Architecture and data flow

**User ⇒ CLI Entry Point ⇒ Pipeline Orchestrator ⇒ Page Fetcher ⇒ Source Inventory Builder ⇒ Prompt Builder ⇒ MAML Translation Agent (single LLM call) ⇒ Response Parser ⇒ Deterministic Serializer ⇒ Deterministic Validator ⇒ Deterministic Repair (once) ⇒ Re-Validator ⇒ MAML Renderer ⇒ Rendered Page Screenshot ⇒ Evaluation (Design2Code metrics, SSIM, MAML validity) ⇒ Final .maml output**

1. **User:** enters the URL of the website to translate with `python -m maml_pipeline <url>`.
2. **CLI entry point:** checks the URL and loads settings from `.env`. Done in `cli.py` and `config.py`.
3. **Pipeline orchestrator:** runs every stage in order, times each one and saves all the artifacts to the run folder. If a stage fails, it records the failing stage and error in `run_metadata.json`. Done in `pipeline.py`.
4. **Page fetcher:** opens the page in headless Chrome, scrolls to trigger lazy-loaded content, takes the `original.png` screenshot and records every visible text, image, control and styled box with its position and styles. Done in `browser_capture.py`. Output: a `PageCapture` (page HTML, screenshot path, page size and the list of raw elements).
5. **Source inventory builder:** removes empty elements and keeps at most 350 elements, keeping content ahead of decorative boxes. Every element keeps an ID such as `src_00001`. Done in `source_inventory.py`. Output: `source_inventory.json`.
6. **Prompt builder:** loads the versioned system prompt and compresses the inventory into compact JSON, dropping empty fields. Done in `prompt_builder.py`. Output: `system_prompt.txt` and `page_prompt.txt`.
7. **MAML translation agent:** one Google ADK agent with no tools, so exactly one LLM call. It decides which elements to keep, each element's MAML type, position, layer and style, and refers to content only by source ID. Done in `maml_agent/agent.py`. Output: `raw_model_response.txt`, saved before parsing so an invalid reply can still be inspected.
8. **Response parser:** strips Markdown code fences and parses the reply as JSON with an `elements` list. Done in `translator.py`. Output: `translation_plan.json`.
9. **Deterministic serializer:** replaces source IDs with the exact text, links, accessible names, placeholders, options and image URLs from the inventory, and writes canonical MAML. Done in `serializer.py`. Output: `generated.maml`.
10. **Deterministic validator:** checks the MAML structure (types, unique IDs, numeric geometry, required fields), checks that text, links and accessible names exactly match the source, and checks that every visible source element is included. Missing elements are a warning, not an error, so the run is still rendered and scored. Done in `schema_validator.py` and `preservation_validator.py`. Output: a validation report.
11. **Deterministic repair:** if validation fails, fixes invalid `display` values, numbers stored as strings and duplicate IDs. Runs once. Done in `deterministic_repair.py`. Output: `repaired.maml`.
12. **Re-validator:** validates again. If errors remain, the run stops. Output: `validation_report.json`.
13. **MAML renderer:** converts each MAML element into an absolutely positioned HTML element, layered by `z`. Done in `renderer.py`. Output: `final.maml`, `rendered.html` and `render_report.json`.
14. **Rendered page screenshot:** serves `rendered.html` from a local web server, opens it in headless Chrome, checks that the page title is the rendered page's title, waits up to 5 seconds for images and fonts, takes a full-page screenshot, and extracts the rendered elements with the same script as the page fetcher. Done in `visual_metrics.py`. Output: `rendered.png` and `rendered_elements.json`.
15. **Evaluation:** calculates SSIM and a difference image (`visual_metrics.py`), then scores the translation (`translation_metrics.py`):
    - **Element preservation:** Design2Code Block-Match (area of matched text blocks ÷ area of all text blocks on both pages), text-block recall and precision, and image recall by image URL.
    - **Text preservation:** Design2Code Text (character similarity of matched blocks), exact-text recall and character recall.
    - **Layout accuracy:** Design2Code Position (1 − the larger of the horizontal and vertical center offsets, normalized by the source page size) and the mean offset in pixels.
    - **Visual similarity:** SSIM, Design2Code CLIP (cosine similarity of CLIP ViT-B/32 embeddings after inpainting the matched text) and Design2Code Color (1 − CIEDE2000 ÷ 100 between text colors).
    - **MAML validity:** schema errors before and after repair, repairs applied, content-integrity errors, unknown-property warnings and source-ID coverage.
    - **Design2Code overall:** the mean of Block-Match, Text, Position, Color and CLIP, as in the paper.

    Text blocks are matched one-to-one on text similarity with the Jonker-Volgenant algorithm, and pairs below 0.5 similarity are dropped, as in Design2Code. Output: `ssim_report.json`, `visual_diff.png` and `evaluation_report.json`.
16. **Final .maml output:** `final.maml`, with the summary printed to the terminal and saved in `run_metadata.json`.

**Canonical MAML format:** the first line is `{"viewport_width": 1200}`. Each following line is one flat element with `type`, `id`, `source_ids`, `x`, `y`, `z`, `w`, `h`, `display` and its type-specific fields. Supported types are `text`, `shape`, `text-field`, `button`, `dropdown`, `image`, `carousel` and `script`. This schema is defined by this repository's validator and renderer and is not the MAML2023 format.


