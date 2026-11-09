# Purpose: Capture generated HTML and compare it pixel-for-pixel with the source screenshot.

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.options import Options


def capture_rendered_page(
    html_path: Path,
    screenshot_path: Path,
    *,
    viewport_width: int,
    viewport_height: int,
    max_capture_height: int = 16000,
) -> dict[str, int]:
    """Open generated HTML in Chrome and save a full-page screenshot."""
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-notifications")
    options.add_argument(f"--window-size={viewport_width},{viewport_height}")

    driver = webdriver.Chrome(options=options)
    try:
        driver.set_page_load_timeout(30)
        try:
            driver.get(html_path.resolve().as_uri())
        except TimeoutException:
            # Remote image URLs may outlive the local document load. Capture the
            # content that Chrome has available rather than discarding the run.
            pass

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
        return {
            "page_width": page_width,
            "page_height": page_height,
            "captured_height": capture_height,
        }
    finally:
        driver.quit()


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
