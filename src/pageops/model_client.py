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
        # Set by the Baseten factory: verdict-style calls measure best
        # at LOW reasoning effort. None means the parameter is not sent.
        self.reasoning_effort: str | None = None

    def chat(self, messages: list[dict], model: str = MODEL_WONDER, **kwargs) -> dict:
        if not self.api_key:
            raise RuntimeError("MODEL_API_KEY is not set; cannot call the Meta Model API.")
        import httpx  # imported lazily so mock mode never needs the package

        response = httpx.post(
            f"{self.base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": messages,
                **({"reasoning_effort": self.reasoning_effort} if self.reasoning_effort else {}),
                **kwargs,
            },
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

    def generate_plan(
        self, brief: str, brand_voice: dict, context: str = "", trends: list | None = None
    ) -> dict:
        payload = {"brief": brief, "brand_voice": brand_voice}
        if context:
            payload["previous_period"] = context
        if trends:
            payload["trends"] = trends
        return self._structured(
            "Create a 7-day content plan as JSON: {posts: [{day, platform, topic, angle, format}]}.",
            payload,
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

    def narrate(self, stats: dict, brand_voice: dict) -> str:
        """Interpret computed stats in prose. Figures come from stats only."""
        messages = [
            {
                "role": "system",
                "content": (
                    "You are PageOps Agent's performance analyst. Write two or "
                    "three plain sentences interpreting the numbers you are "
                    "given. Never invent a figure that is not in the input."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {"stats": stats, "brand": brand_voice.get("brand_name", "")}
                ),
            },
        ]
        result = self.chat(messages, model=self.main_model)
        return result["choices"][0]["message"]["content"].strip()


class MockClient:
    """Canned structured outputs. Deterministic, offline, free."""

    def generate_plan(
        self, brief: str, brand_voice: dict, context: str = "", trends: list | None = None
    ) -> dict:
        brand = brand_voice.get("brand_name", "the brand")
        return {
            "brief": brief,
            "context": context,
            "trends": trends or [],
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
                    "day": "Tue",
                    "platform": "facebook",
                    "topic": "Before and after: one inbox, zero missed price questions",
                    "angle": "Show the saved replies, then the offer",
                    "format": "Poster",
                },
                {
                    "day": "Thu",
                    "platform": "facebook",
                    "topic": "Five questions your page should answer without you",
                    "angle": "Checklist the owner can test tonight",
                    "format": "Carousel",
                },
                {
                    "day": "Fri",
                    "platform": "linkedin",
                    "topic": "What a content pipeline does for a small team",
                    "angle": "Trust and process, with a soft offer",
                    "format": "Text post",
                },
                {
                    "day": "Sat",
                    "platform": "facebook",
                    "topic": "Weekend orders while the shop is closed",
                    "angle": "The bot takes the order, the owner confirms later",
                    "format": "Short video",
                },
                {
                    "day": "Sun",
                    "platform": "facebook",
                    "topic": "This week in your page inbox, in one report",
                    "angle": "Tease the weekly performance report",
                    "format": "Poster",
                },
            ],
        }

    def generate_draft(self, plan_item: dict, brand_voice: dict) -> dict:
        topic = plan_item.get("topic", "our latest service")
        text = (
            f"{topic}. We built this for SME owners who sell through their page and "
            "cannot sit in the inbox all day. Message us to get started, and we will "
            "map the first step with you. #FYFAI #AIAutomation #SME"
        )
        return {
            "platform": plan_item.get("platform", "facebook"),
            "text": text,
            "hashtags": ["#FYFAI", "#AIAutomation", "#SME"],
        }

    def narrate(self, stats: dict, brand_voice: dict) -> str:
        totals = stats.get("totals", {})
        best = stats.get("best_post") or {}
        return (
            f"across {totals.get('posts', 0)} tracked posts the page earned "
            f"{totals.get('reach', 0)} reach and {totals.get('engagement', 0)} "
            f"engagement; the strongest post was {best.get('post_id', 'n/a')} "
            f"with {best.get('engagement', 0)} engagement, so its angle leads "
            "the next plan."
        )

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
    client.reasoning_effort = "low"
    return client


def get_judge_client():
    """The decision/judge model: Muse Spark Open via Baseten.

    A second model judging the main model's drafts (the owner's
    Model map designation). Returns None when no Baseten key is
    configured; callers then fall back to the drafting client's
    verdict, so the pipeline never depends on the judge existing.
    """
    return get_baseten_client()
