# Purpose: Define the shared typed data structures passed between pipeline stages.

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class PageCapture:
    url: str
    title: str
    viewport_width: int
    viewport_height: int
    page_width: int
    page_height: int
    screenshot_path: str
    rendered_html: str
    raw_elements: list[dict[str, Any]]
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SourceElement:
    source_id: str
    kind: str
    tag: str
    role: str | None
    text: str
    accessible_name: str | None
    href: str | None
    src: str | None
    alt: str | None
    placeholder: str | None
    input_type: str | None
    options: list[str]
    x: float
    y: float
    width: float
    height: float
    visible_in_capture: bool
    interactive: bool
    styles: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SourceInventory:
    url: str
    title: str
    viewport_width: int
    page_width: int
    page_height: int
    screenshot_path: str
    elements: list[SourceElement]
    warnings: list[str] = field(default_factory=list)

    def by_id(self) -> dict[str, SourceElement]:
        return {element.source_id: element for element in self.elements}

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ValidationIssue:
    code: str
    message: str
    line_number: int | None = None
    element_id: str | None = None
    source_ids: list[str] = field(default_factory=list)
    deterministic_fix_available: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ValidationReport:
    valid: bool
    errors: list[ValidationIssue] = field(default_factory=list)
    warnings: list[ValidationIssue] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RenderResult:
    html_path: str
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PipelineResult:
    run_directory: str
    maml_path: str
    html_path: str
    rendered_screenshot_path: str
    validation_report_path: str
    evaluation_report_path: str
    metadata_path: str
    model_calls: int
    ssim: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
