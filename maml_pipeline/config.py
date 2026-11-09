# Purpose: Load runtime settings from environment variables without embedding credentials in code.

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    model: str
    api_key: str | None
    api_base: str | None
    viewport_width: int
    viewport_height: int
    max_inventory_elements: int
    max_repair_attempts: int


def load_settings(project_root: Path | None = None) -> Settings:
    """Load .env values while allowing shell environment variables to override them."""
    if project_root is not None:
        load_dotenv(project_root / ".env", override=False)

    return Settings(
        model=os.getenv("MAML_MODEL", "openai/@vertexai/gemini-2.5-pro"),
        api_key=os.getenv("PORTKEY_API_KEY") or os.getenv("OPENAI_API_KEY") or os.getenv("GOOGLE_API_KEY"),
        api_base=os.getenv("MAML_API_BASE", "https://ai-gateway.apps.cloud.rt.nyu.edu/v1"),
        viewport_width=int(os.getenv("MAML_VIEWPORT_WIDTH", "1200")),
        viewport_height=int(os.getenv("MAML_VIEWPORT_HEIGHT", "900")),
        max_inventory_elements=int(os.getenv("MAML_MAX_INVENTORY_ELEMENTS", "350")),
        max_repair_attempts=int(os.getenv("MAML_MAX_REPAIR_ATTEMPTS", "1")),
    )
