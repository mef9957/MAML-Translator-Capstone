# Purpose: Capture generated HTML and compare it pixel-for-pixel with the source screenshot.

from __future__ import annotations

import functools
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from selenium.common.exceptions import TimeoutException

from maml_pipeline.extraction.browser_capture import ELEMENT_SCRIPT, build_chrome_driver
from maml_pipeline.rendering.renderer import RENDERED_PAGE_TITLE


class _QuietRequestHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        """Keep per-request server logs out of the pipeline's terminal output."""


def capture_rendered_page(
    html_path: Path,
    screenshot_path: Path,
    *,
    viewport_width: int,
    viewport_height: int,
    max_capture_height: int = 16000,
) -> tuple[dict[str, int], list[dict[str, Any]]]:
    """Serve generated HTML on localhost, save a full-page screenshot, and extract its visible elements."""
    # Chrome loads the page over HTTP rather than file:// because file:// reads of the run
    # folder were refused (ERR_ACCESS_DENIED). Python reads the file and Chrome only makes
    # a local network request, so the result does not depend on file-access permissions.
    handler = functools.partial(_QuietRequestHandler, directory=str(html_path.resolve().parent))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    driver = None
    try:
        driver = build_chrome_driver(viewport_width, viewport_height, headless=True)
        driver.set_page_load_timeout(30)
        try:
            driver.get(f"http://127.0.0.1:{server.server_port}/{html_path.name}")
        except TimeoutException:
            # Remote image URLs may outlive the local document load. Capture the
            # content that Chrome has available rather than discarding the run.
            pass

        if driver.title != RENDERED_PAGE_TITLE:
            raise RuntimeError(
                f"Chrome did not load the rendered MAML page (page title: {driver.title!r})."
            )

        driver.execute_async_script(
            """
            const done = arguments[arguments.length - 1];
            const images = Array.from(document.images);
            const imageReady = Promise.all(images.map(image => {
              if (image.complete) return Promise.resolve();
              return new Promise(resolve => {
                image.addEventListener('load', resolve, {once: true});
                image.addEventListener('error', resolve, {once: true});
              });
            }));
            const fontReady = document.fonts?.ready || Promise.resolve();
            Promise.race([
              Promise.all([imageReady, fontReady]),
              new Promise(resolve => setTimeout(resolve, 5000))
            ]).then(done);
            """
        )

        page_width = int(driver.execute_script("return document.documentElement.scrollWidth"))
        page_height = int(driver.execute_script("return document.documentElement.scrollHeight"))
        capture_height = min(max(page_height, viewport_height), max_capture_height)
        driver.set_window_size(viewport_width, capture_height)
        driver.execute_script("window.scrollTo(0, 0)")
        time.sleep(0.25)
        screenshot_path.parent.mkdir(parents=True, exist_ok=True)
        driver.save_screenshot(str(screenshot_path))
        # Extracted after the full-height resize, matching how the source page is extracted.
        rendered_elements: list[dict[str, Any]] = driver.execute_script(ELEMENT_SCRIPT)
        capture_details = {
            "page_width": page_width,
            "page_height": page_height,
            "captured_height": capture_height,
        }
        return capture_details, rendered_elements
    finally:
        if driver is not None:
            driver.quit()
        server.shutdown()
        server.server_close()


def compare_screenshots(
    original_path: Path,
    rendered_path: Path,
    difference_path: Path,
) -> dict[str, Any]:
    """Pad screenshots to one canvas, calculate SSIM, and save a visual difference."""
    try:
        import numpy as np
        from PIL import Image, ImageChops, ImageEnhance
        from skimage.metrics import structural_similarity
    except ImportError as exc:
        raise RuntimeError(
            "Visual comparison requires Pillow and scikit-image. "
            "Install the project requirements again."
        ) from exc

    original = Image.open(original_path).convert("RGB")
    rendered = Image.open(rendered_path).convert("RGB")
    comparison_size = (
        max(original.width, rendered.width),
        max(original.height, rendered.height),
    )

    def padded(image: Any) -> Any:
        canvas = Image.new("RGB", comparison_size, "white")
        canvas.paste(image, (0, 0))
        return canvas

    original_canvas = padded(original)
    rendered_canvas = padded(rendered)
    original_gray = np.asarray(original_canvas.convert("L"), dtype=np.uint8)
    rendered_gray = np.asarray(rendered_canvas.convert("L"), dtype=np.uint8)
    score = float(
        structural_similarity(
            original_gray,
            rendered_gray,
            data_range=255,
        )
    )

    difference = ImageChops.difference(original_canvas, rendered_canvas)
    difference = ImageEnhance.Contrast(difference).enhance(2.0)
    difference.save(difference_path)

    return {
        "ssim": score,
        "original_dimensions": [original.width, original.height],
        "rendered_dimensions": [rendered.width, rendered.height],
        "comparison_dimensions": list(comparison_size),
        "padding_color": "white",
    }
