"""Model clients for PageOps Agent.

MetaModelClient talks to the Meta Model API at api.meta.ai using the
OpenAI-compatible chat completions surface, with a Bearer key taken from
the environment. Every call is counted in a JSON-lines usage log. The
same client, pointed at Baseten's base URL, serves the open-weights
route (Muse Spark Open) used for the hackathon's open-weight angle.

MockClient returns canned structured outputs for plan / draft / verdict
so the whole pipeline runs and tests pass with no key and no network.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .config import DEFAULT_DATA_DIR

BASE_URL = "https://api.meta.ai/v1"
BASETEN_BASE_URL = "https://inference.baseten.co/v1"
MODEL_SPARK = "muse-spark-1.3"
MODEL_WONDER = "muse-wonder-1.0"
MODEL_SPARK_OPEN = "meta-models/muse-spark-open-1026"

# Muse Wonder is the product's main LLM (owner's decision, 2026-11-01):
# plan, drafts, report narrative and verdicts all run on Wonder. Spark
# stays available for light utility calls where its lower cost matters.


class UsageLogger:
    """Appends one JSON line per API call to the usage log file."""

    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path else DEFAULT_DATA_DIR / "usage_log.jsonl"

    def record(self, model: str, usage: dict | None) -> dict:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "model": model,
            "usage": usage or {},
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
        return entry


class MetaModelClient:
    """Real client for the Meta Model API. No call is made unless chat()
    or one of the structured helpers is invoked explicitly."""

    def __init__(
        self,
        api_key: str | None = None,
        usage_log: Path | str | None = None,
        base_url: str = BASE_URL,
    ):
        self.api_key = api_key or os.environ.get("MODEL_API_KEY") or None
        self.usage = UsageLogger(usage_log)
        self.base_url = base_url
        # Main LLM for plan/drafts. Default Wonder; set PAGEOPS_MAIN_MODEL
        # to muse-spark-1.3 for cheap development iterations.
        self.main_model = os.environ.get("PAGEOPS_MAIN_MODEL") or MODEL_WONDER
        self.verdict_model = MODEL_WONDER

    def chat(self, messages: list[dict], model: str = MODEL_SPARK, **kwargs) -> dict:
        if not self.api_key:
            raise RuntimeError("MODEL_API_KEY is not set; cannot call the Meta Model API.")
        import httpx  # imported lazily so mock mode never needs the package

        response = httpx.post(
            f"{self.base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={"model": model, "messages": messages, **kwargs},
            timeout=120.0,
        )
        response.raise_for_status()
        payload = response.json()
        self.usage.record(model, payload.get("usage"))
        return payload

    def _structured(self, instruction: str, payload: dict, model: str) -> dict:
        messages = [
            {"role": "system", "content": "You are PageOps Agent. Reply with JSON only."},
            {"role": "user", "content": f"{instruction}\n\nInput:\n{json.dumps(payload)}"},
        ]
        result = self.chat(messages, model=model)
        text = result["choices"][0]["message"]["content"]
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"raw": text}

    def generate_plan(self, brief: str, brand_voice: dict) -> dict:
        return self._structured(
            "Create a 7-day content plan as JSON: {posts: [{day, platform, topic, angle, format}]}.",
            {"brief": brief, "brand_voice": brand_voice},
            self.main_model,
        )

    def generate_draft(self, plan_item: dict, brand_voice: dict) -> dict:
        return self._structured(
            "Write one post caption as JSON: {platform, text, hashtags: []}. Follow the brand rules.",
            {"plan_item": plan_item, "brand_voice": brand_voice},
            self.main_model,
        )

    def verdict(self, draft: dict, check_summary: str) -> dict:
        return self._structured(
            "Give a final verdict as JSON: {verdict: pass|revise, reasons: []} using the rule-check summary.",
            {"draft": draft, "check_summary": check_summary},
            self.verdict_model,
        )


class MockClient:
    """Canned structured outputs. Deterministic, offline, free."""

    def generate_plan(self, brief: str, brand_voice: dict) -> dict:
        brand = brand_voice.get("brand_name", "the brand")
        return {
            "brief": brief,
            "posts": [
                {
                    "day": "Mon",
                    "platform": "facebook",
                    "topic": f"How {brand} answers page messages while the owner is busy",
                    "angle": "Relatable problem, then the fix",
                    "format": "Short video",
                },
                {
                    "day": "Wed",
                    "platform": "facebook",
                    "topic": "Three follow-ups that rescue a lost lead",
                    "angle": "Practical tips from the CRM & Lead Follow-Up Pack",
                    "format": "Carousel",
                },
                {
                    "day": "Fri",
                    "platform": "linkedin",
                    "topic": "What a content pipeline does for a small team",
                    "angle": "Trust and process, with a soft offer",
                    "format": "Text post",
                },
            ],
        }

    def generate_draft(self, plan_item: dict, brand_voice: dict) -> dict:
        topic = plan_item.get("topic", "our latest service")
        text = (
            f"{topic}. We built this for SME owners who sell through their page and "
            "cannot sit in the inbox all day. Message us to get started, and we will "
            "map the first step with you. #FYFAI #AIAutomation"
        )
        return {
            "platform": plan_item.get("platform", "facebook"),
            "text": text,
            "hashtags": ["#FYFAI", "#AIAutomation"],
        }

    def verdict(self, draft: dict, check_summary: str) -> dict:
        passed = "[FAIL]" not in check_summary
        return {
            "verdict": "pass" if passed else "revise",
            "reasons": ["All deterministic brand rules passed."] if passed else [check_summary],
        }


def get_client(settings=None):
    """Factory: real client only in meta mode with a key, else mock."""
    from .config import get_settings

    settings = settings or get_settings()
    if settings.model_mode == "meta" and settings.model_api_key:
        return MetaModelClient(api_key=settings.model_api_key, usage_log=settings.usage_log)
    return MockClient()


def get_baseten_client(api_key: str | None = None, usage_log: Path | str | None = None):
    """Open-weights route: Muse Spark Open served by Baseten.

    Returns None when no Baseten key is configured (BASETEN_API_KEY).
    The hackathon key works with this one model only, so plan, draft
    and verdict calls on this client all use MODEL_SPARK_OPEN.
    """
    key = api_key or os.environ.get("BASETEN_API_KEY") or None
    if not key:
        return None
    client = MetaModelClient(api_key=key, usage_log=usage_log, base_url=BASETEN_BASE_URL)
    client.main_model = MODEL_SPARK_OPEN
    client.verdict_model = MODEL_SPARK_OPEN
    return client
