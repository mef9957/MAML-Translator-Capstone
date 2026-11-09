# Purpose: Provide deterministic webpage capture and source-inventory functionality.

from maml_pipeline.extraction.browser_capture import capture_page
from maml_pipeline.extraction.source_inventory import build_source_inventory

__all__ = ["capture_page", "build_source_inventory"]
