# Purpose: Open a webpage in Chrome, trigger lazy loading, capture a screenshot,
# and collect deterministic browser evidence for the HTML-to-MAML pipeline.

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.chrome.options import Options

from maml_pipeline.models import PageCapture


_ELEMENT_SCRIPT = r"""
const results = [];
const CONTROL_SELECTOR = [
  'button',
  'input',
  'textarea',
  'select',
  '[role="button"]',
  '[role="textbox"]',
  '[role="combobox"]',
  '[contenteditable="true"]'
].join(',');
const SKIP_SELECTOR = 'script,style,noscript,template';

function normalizeText(value) {
  return (value || '').replace(/\s+/g, ' ').trim();
}

function stylesFor(element) {
  const style = window.getComputedStyle(element);
  return {
    fontFamily: style.fontFamily,
    fontSize: style.fontSize,
    fontWeight: style.fontWeight,
    fontStyle: style.fontStyle,
    lineHeight: style.lineHeight,
    letterSpacing: style.letterSpacing,
    color: style.color,
    backgroundColor: style.backgroundColor,
    textAlign: style.textAlign,
    border: style.border,
    borderRadius: style.borderRadius,
    padding: style.padding,
    boxShadow: style.boxShadow,
    objectFit: style.objectFit
  };
}

function visible(element, rect) {
  if (!element || !rect || rect.width <= 0 || rect.height <= 0) return false;
  for (let current = element; current; current = current.parentElement) {
    const style = window.getComputedStyle(current);
    if (style.display === 'none' || style.visibility === 'hidden' || Number(style.opacity || 1) <= 0) {
      return false;
    }
  }
  return true;
}

function visibleInCapture(element, rect) {
  if (!visible(element, rect)) return false;

  // The source screenshot is captured at the document's top-left with the
  // document height expanded to fit the page. Clip against that capture area,
  // then account for ancestors that clip or scroll their contents.
  const bounds = {
    left: 0,
    top: 0,
    right: document.documentElement.clientWidth,
    bottom: document.documentElement.clientHeight
  };
  let left = Math.max(rect.left, bounds.left);
  let top = Math.max(rect.top, bounds.top);
  let right = Math.min(rect.right, bounds.right);
  let bottom = Math.min(rect.bottom, bounds.bottom);
  if (right <= left || bottom <= top) return false;

  for (let parent = element.parentElement; parent; parent = parent.parentElement) {
    const style = window.getComputedStyle(parent);
    const parentRect = parent.getBoundingClientRect();
    const clipX = /^(hidden|clip|scroll|auto)$/.test(style.overflowX);
    const clipY = /^(hidden|clip|scroll|auto)$/.test(style.overflowY);

    if (clipX) {
      left = Math.max(left, parentRect.left + parent.clientLeft);
      right = Math.min(right, parentRect.left + parent.clientLeft + parent.clientWidth);
    }
    if (clipY) {
      top = Math.max(top, parentRect.top + parent.clientTop);
      bottom = Math.min(bottom, parentRect.top + parent.clientTop + parent.clientHeight);
    }
    if (right <= left || bottom <= top) return false;
  }
  return true;
}

function geometry(rect) {
  return {
    x: Math.round((rect.left + window.scrollX) * 100) / 100,
    y: Math.round((rect.top + window.scrollY) * 100) / 100,
    width: Math.round(rect.width * 100) / 100,
    height: Math.round(rect.height * 100) / 100
  };
}

function accessibleName(element) {
  return element.getAttribute('aria-label') ||
    element.getAttribute('title') ||
    element.getAttribute('alt') ||
    null;
}

function addResult(result) {
  results.push({
    source_id: '',
    role: null,
    text: '',
    accessible_name: null,
    href: null,
    src: null,
    alt: null,
    placeholder: null,
    input_type: null,
    options: [],
    interactive: false,
    ...result
  });
}

function addTextNode(node) {
  const parent = node.parentElement;
  const text = normalizeText(node.textContent);
  if (!parent || !text || parent.closest(SKIP_SELECTOR) || parent.closest(CONTROL_SELECTOR)) return;

  const range = document.createRange();
  range.selectNodeContents(node);
  const rect = range.getBoundingClientRect();
  if (!visible(parent, rect)) return;

  const link = parent.closest('a[href]');
  const semanticOwner = link || parent.closest('[role],h1,h2,h3,h4,h5,h6,label') || parent;
  addResult({
    kind: 'text',
    tag: semanticOwner.tagName.toLowerCase(),
    role: semanticOwner.getAttribute('role'),
    text,
    accessible_name: accessibleName(semanticOwner),
    href: link ? link.href : null,
    interactive: Boolean(link),
    styles: stylesFor(parent),
    visible: true,
    visible_in_capture: visibleInCapture(parent, rect),
    ...geometry(rect)
  });
}

function addControl(element) {
  if (element.closest(CONTROL_SELECTOR) !== element) return;
  const rect = element.getBoundingClientRect();
  if (!visible(element, rect)) return;

  const tag = element.tagName.toLowerCase();
  const type = (element.getAttribute('type') || '').toLowerCase();
  const valueText = ['button', 'submit', 'reset'].includes(type)
    ? normalizeText(element.value)
    : '';
  const text = normalizeText(element.innerText) || valueText;
  const link = element.closest('a[href]');
  addResult({
    kind: 'control',
    tag,
    role: element.getAttribute('role'),
    text,
    accessible_name: accessibleName(element),
    href: link ? link.href : null,
    placeholder: element.getAttribute('placeholder'),
    input_type: element.getAttribute('type'),
    options: tag === 'select'
      ? Array.from(element.options).map(option => normalizeText(option.text)).filter(Boolean)
      : [],
    interactive: true,
    styles: stylesFor(element),
    visible: true,
    visible_in_capture: visibleInCapture(element, rect),
    ...geometry(rect)
  });
}

function addImage(element) {
  const rect = element.getBoundingClientRect();
  if (!visible(element, rect)) return;
  const link = element.closest('a[href]');
  addResult({
    kind: 'image',
    tag: element.tagName.toLowerCase(),
    role: element.getAttribute('role'),
    accessible_name: accessibleName(element),
    href: link ? link.href : null,
    src: element.currentSrc || element.src || null,
    alt: element.getAttribute('alt'),
    interactive: Boolean(link),
    styles: stylesFor(element),
    visible: true,
    visible_in_capture: visibleInCapture(element, rect),
    ...geometry(rect)
  });
}

function addVisualContainer(element) {
  if (element === document.body || element.matches(CONTROL_SELECTOR + ',img')) return;
  const rect = element.getBoundingClientRect();
  if (!visible(element, rect) || rect.width * rect.height < 100) return;

  const style = window.getComputedStyle(element);
  const hasBackground = !['rgba(0, 0, 0, 0)', 'transparent'].includes(style.backgroundColor);
  const hasBorder = ['Top', 'Right', 'Bottom', 'Left'].some(
    side => parseFloat(style[`border${side}Width`]) > 0
  );
  const hasShadow = style.boxShadow && style.boxShadow !== 'none';
  if (!hasBackground && !hasBorder && !hasShadow) return;

  addResult({
    kind: 'container',
    tag: element.tagName.toLowerCase(),
    role: element.getAttribute('role'),
    accessible_name: accessibleName(element),
    href: element.closest('a[href]')?.href || null,
    interactive: Boolean(element.closest('a[href]')),
    styles: stylesFor(element),
    visible: true,
    visible_in_capture: visibleInCapture(element, rect),
    ...geometry(rect)
  });
}

// Walk elements and raw text nodes in DOM order. This captures visible text
// inside arbitrary, legacy, and custom tags rather than relying on a tag list.
const walker = document.createTreeWalker(
  document.body,
  NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT
);
let node;
while ((node = walker.nextNode())) {
  if (node.nodeType === Node.TEXT_NODE) {
    addTextNode(node);
    continue;
  }
  const element = node;
  if (element.matches(SKIP_SELECTOR)) continue;
  if (element.matches('img')) addImage(element);
  if (element.matches(CONTROL_SELECTOR)) addControl(element);
  addVisualContainer(element);
}

results.forEach((result, index) => {
  result.source_id = `src_${String(index + 1).padStart(5, '0')}`;
});
return results;
"""


class BrowserCaptureError(RuntimeError):
    """Raised when a webpage cannot be captured."""


def _build_driver(viewport_width: int, viewport_height: int, headless: bool) -> webdriver.Chrome:
    options = Options()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-notifications")
    options.add_argument(f"--window-size={viewport_width},{viewport_height}")
    return webdriver.Chrome(options=options)


def _scroll_until_stable(
    driver: webdriver.Chrome,
    *,
    max_steps: int,
    pause_seconds: float,
    stable_checks_required: int = 2,
) -> None:
    """Scroll incrementally until page height stops growing or the limit is reached."""
    stable_checks = 0
    previous_height = int(driver.execute_script("return document.body.scrollHeight"))

    for _ in range(max_steps):
        driver.execute_script("window.scrollBy(0, Math.max(window.innerHeight * 0.8, 500));")
        time.sleep(pause_seconds)
        current_height = int(driver.execute_script("return document.body.scrollHeight"))
        at_bottom = bool(
            driver.execute_script(
                "return window.scrollY + window.innerHeight >= document.body.scrollHeight - 2"
            )
        )
        stable_checks = stable_checks + 1 if current_height == previous_height else 0
        previous_height = current_height
        if at_bottom and stable_checks >= stable_checks_required:
            break

    driver.execute_script("window.scrollTo(0, 0)")


def capture_page(
    url: str,
    output_dir: Path,
    *,
    viewport_width: int = 1200,
    viewport_height: int = 900,
    headless: bool = True,
    page_load_timeout: int = 30,
    max_scroll_steps: int = 20,
    scroll_pause_seconds: float = 0.35,
) -> PageCapture:
    """Capture rendered page evidence and return it as a typed PageCapture."""
    output_dir.mkdir(parents=True, exist_ok=True)
    driver: webdriver.Chrome | None = None
    errors: list[str] = []

    try:
        driver = _build_driver(viewport_width, viewport_height, headless)
        driver.set_page_load_timeout(page_load_timeout)
        try:
            driver.get(url)
        except TimeoutException:
            errors.append(f"Page load exceeded {page_load_timeout} seconds; using available content.")

        _scroll_until_stable(
            driver,
            max_steps=max_scroll_steps,
            pause_seconds=scroll_pause_seconds,
        )

        page_width = int(driver.execute_script("return document.documentElement.scrollWidth"))
        page_height = int(driver.execute_script("return document.documentElement.scrollHeight"))
        screenshot_path = output_dir / "original.png"

        # Resize Chrome to the document height for an initial full-page research capture.
        # A height cap protects Chrome from very large or infinite pages.
        capture_height = min(page_height, 16000)
        driver.set_window_size(viewport_width, max(viewport_height, capture_height))
        driver.save_screenshot(str(screenshot_path))

        raw_elements: list[dict[str, Any]] = driver.execute_script(_ELEMENT_SCRIPT)
        return PageCapture(
            url=url,
            title=driver.title or "",
            viewport_width=viewport_width,
            viewport_height=viewport_height,
            page_width=page_width,
            page_height=page_height,
            screenshot_path=str(screenshot_path),
            rendered_html=driver.page_source,
            raw_elements=raw_elements,
            errors=errors,
        )
    except WebDriverException as exc:
        raise BrowserCaptureError(f"Chrome could not capture {url}: {exc}") from exc
    finally:
        if driver is not None:
            driver.quit()
