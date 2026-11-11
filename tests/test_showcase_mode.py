"""Showcase visual style: the designed product-experience poster
(owner, 2026-11-11 — the JBL x Spotify register). The product
experience is the picture; selling info (headline, price, up to
three icon-row features) is set into the design. Neither an
abstract metaphor nor a product card.
"""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from pageops.designer import produce_visual, visual_style_for
from pageops.model_client import MetaModelClient, MockClient
from pageops.store import Store


def test_visual_style_for_accepts_showcase():
    assert visual_style_for({"visual_style": "showcase"}) == "showcase"


class _ImageClient:
    def generate_image_bytes(self, prompt: str) -> bytes:
        from io import BytesIO

        buf = BytesIO()
        Image.new("RGB", (900, 1125), (24, 60, 44)).save(buf, format="PNG")
        return buf.getvalue()


class _ShowcaseDirector:
    def direct_visual(self, plan_item, draft_text, brand_voice, style):
        assert style == "showcase"
        return {
            "concept": "The Gemini app experience woven into one scene",
            "prompt": (
                "Concept: x\nComposition: y\nSubject: z\nSetting: s\n"
                "Camera and style: c\nConstraints: no text, no letters, "
                "no logos, no watermark."
            ),
            "headline": "Pay once, use all year",
            "emphasis": "once",
            "features": ["Argon + Claude", "YouTube free", "Own email"],
            "price_line": "29,500 MMK",
        }


def test_produce_visual_showcase_renders_over_plate(tmp_path):
    store = Store(tmp_path / "data")
    row = store.add_plan_row(
        {"topic": "Gemini Pro launch", "platform": "facebook",
         "visual_style": "showcase", "status": "planned"}
    )
    row = store.update_row("plan", row["id"], {"draft": "Gemini Pro, 29,500 MMK."})
    result = produce_visual(
        store, row, image_client=_ImageClient(), director=_ShowcaseDirector()
    )
    visual = Path(store.data_dir) / result["visual"]
    assert visual.exists()
    with Image.open(visual) as img:
        assert img.size == (1080, 1350)


def test_meta_showcase_direction_contract(tmp_path, monkeypatch):
    client = MetaModelClient(api_key="<redacted>", usage_log=tmp_path / "u.jsonl")
    seen = {}

    def capturing_chat(messages, model=None, **kwargs):
        seen["messages"] = messages
        prompt = (
            "Concept: x\nComposition: y\nSubject: z\nSetting: s\n"
            "Camera and style: c\nConstraints: no text, no letters, "
            "no logos, no watermark."
        )
        reply = json.dumps(
            {"concept": "scene", "prompt": prompt, "headline": "Pay once",
             "emphasis": "once", "features": ["Own email"],
             "price_line": "29,500 MMK"}
        )
        return {"choices": [{"message": {"content": reply}}]}

    monkeypatch.setattr(client, "chat", capturing_chat)
    result = client.direct_visual({"topic": "T"}, "draft", {}, "showcase")
    assert result["features"] == ["Own email"]
    assert result["price_line"] == "29,500 MMK"
    sent = " ".join(m["content"] for m in seen["messages"])
    assert "showcase" in sent
    assert "never a product card" in sent
    assert "can tell what product this is" in sent or "unmistakable" in sent


def test_mock_showcase_direction_shape():
    result = MockClient().direct_visual({"topic": "Gemini Pro launch"}, "d", {}, "showcase")
    assert result["headline"]
    assert "no text" in result["prompt"]
    assert result["features"] == []


def test_clean_features_trims_and_deellipsises():
    from pageops.designer import _clean_features

    assert _clean_features(["Gemini 4 Argon +...", "YouTube Premium 1 month free bonus"]) == [
        "Gemini 4 Argon",
        "YouTube Premium 1 month",
    ]
    assert _clean_features([]) == []
    assert _clean_features(["Own email", "  ", "Flow + NotebookLM + Colab"]) == [
        "Own email",
        "Flow + NotebookLM",
    ]
