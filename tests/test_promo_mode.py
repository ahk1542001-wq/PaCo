"""Promo visual style: the bright direct-response poster register
the owner picked (2026-11-10). It composes from brand assets with
direction only — no generated plate — and lands in the manifest as
style "promo"; any direction failure falls back to the normal flow.
"""

from __future__ import annotations

import json
from pathlib import Path

from pageops.designer import produce_visual, visual_style_for
from pageops.model_client import MetaModelClient, MockClient
from pageops.store import Store


def test_visual_style_for_accepts_promo():
    assert visual_style_for({"visual_style": "promo"}) == "promo"
    assert visual_style_for({"visual_style": "bogus"}) == "scene"
    assert visual_style_for({}) == "scene"


class _PromoDirector:
    def direct_visual(self, plan_item, draft_text, brand_voice, style):
        assert style == "promo"
        return {
            "concept": "Gemini Pro, one year",
            "headline": "GEMINI PRO - one year",
            "benefits": ["On your own email", "YouTube Premium 1 month free"],
            "price_line": "29,500 MMK",
        }


def test_produce_visual_promo_composes_without_a_plate(tmp_path):
    store = Store(tmp_path / "data")
    row = store.add_plan_row(
        {
            "topic": "Gemini Pro launch",
            "platform": "facebook",
            "visual_style": "promo",
            "status": "planned",
        }
    )
    row = store.update_row("plan", row["id"], {"draft": "Gemini Pro, 29,500 MMK."})
    result = produce_visual(store, row, image_client=None, director=_PromoDirector())
    visual = Path(store.data_dir) / result["visual"]
    assert visual.exists()
    assert visual.name.endswith("-poster.png")


def test_meta_promo_direction_returns_benefits_and_price(tmp_path, monkeypatch):
    client = MetaModelClient(api_key="<redacted>", usage_log=tmp_path / "u.jsonl")
    seen = {}

    def capturing_chat(messages, model=None, **kwargs):
        seen["messages"] = messages
        reply = json.dumps(
            {
                "concept": "Gemini Pro, one year",
                "headline": "GEMINI PRO - one year",
                "benefits": ["On your own email"],
                "price_line": "29,500 MMK",
            }
        )
        return {"choices": [{"message": {"content": reply}}]}

    monkeypatch.setattr(client, "chat", capturing_chat)
    result = client.direct_visual({"topic": "T"}, "draft", {}, "promo")
    assert result["price_line"] == "29,500 MMK"
    assert result["benefits"] == ["On your own email"]
    sent = " ".join(m["content"] for m in seen["messages"])
    assert "price_line" in sent
    assert "sales conversation" in sent


def test_mock_promo_direction_shape():
    result = MockClient().direct_visual({"topic": "Gemini Pro launch"}, "d", {}, "promo")
    assert result["headline"]
    assert result["benefits"] == []
    assert result["price_line"] == ""
