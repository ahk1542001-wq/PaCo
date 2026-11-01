"""Endpoint smoke test for the Meta Model API.

Run BEFORE any real build work once MODEL_API_KEY exists:
    PYTHONPATH=src .venv/bin/python scripts/smoke_test.py

Makes ONE minimal chat call with muse-wonder (the product's main LLM),
prints the reply and
the token usage (which is also written to the usage log). With no key
or MODEL_MODE=mock it prints a clear skip message and exits cleanly.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pageops.config import get_settings  # noqa: E402
from pageops.model_client import MODEL_WONDER, MetaModelClient  # noqa: E402


def main() -> int:
    settings = get_settings()
    if settings.model_mode != "meta" or not settings.model_api_key:
        print(
            "SKIP: no live call made. Set MODEL_MODE=meta and MODEL_API_KEY "
            "in .env first (key comes from dev.meta.ai, never from chat)."
        )
        return 0
    client = MetaModelClient(api_key=settings.model_api_key, usage_log=settings.usage_log)
    result = client.chat(
        [{"role": "user", "content": "Reply with exactly: PageOps smoke test OK"}],
        model=MODEL_WONDER,
    )
    reply = result["choices"][0]["message"]["content"]
    print("Reply:", reply)
    print("Usage:", result.get("usage"))
    print(f"Usage log: {settings.usage_log}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
