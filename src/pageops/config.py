"""Environment-based settings for PageOps Agent.

Everything is read from environment variables so no secret ever lives in
code. MODEL_MODE defaults to "mock" so the whole pipeline runs with no
API key at all.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"


@dataclass
class Settings:
    model_mode: str = "mock"  # "mock" or "meta"
    model_api_key: str | None = None
    buffer_api_key: str | None = None
    data_dir: Path = DEFAULT_DATA_DIR
    usage_log: Path = DEFAULT_DATA_DIR / "usage_log.jsonl"

    @classmethod
    def from_env(cls) -> "Settings":
        data_dir = Path(os.environ.get("PAGEOPS_DATA_DIR", str(DEFAULT_DATA_DIR)))
        return cls(
            model_mode=os.environ.get("MODEL_MODE", "mock").strip().lower() or "mock",
            model_api_key=os.environ.get("MODEL_API_KEY") or None,
            buffer_api_key=os.environ.get("BUFFER_API_KEY") or None,
            data_dir=data_dir,
            usage_log=data_dir / "usage_log.jsonl",
        )


def get_settings() -> Settings:
    return Settings.from_env()
