"""Poster typography: designed emphasis (owner, 2026-11-10).

Headlines are short and punchy; the director names the one phrase
that carries the punch and the renderer sets it on a highlight
chip. Flat single-weight type is a defect this suite pins down.
"""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw

from pageops.designer import (
    _draw_rich_headline,
    _emphasis_words,
    _font,
    _rich_lines,
    produce_visual,
)
from pageops.model_client import MetaModelClient
from pageops.store import Store


def test_emphasis_words_marks_the_exact_run_only():
    assert _emphasis_words("Pay once use all year", "once") == {1}
    assert _emphasis_words("Pay once use all year", "all year") == {3, 4}
    assert _emphasis_words("Pay once", "year all") == set()
    assert _emphasis_words("Pay once", "") == set()
    assert _emphasis_words("Pay once", "missing") == set()


def test_rich_lines_wrap_and_carry_flags():
    img = Image.new("RGB", (400, 200))
    draw = ImageDraw.Draw(img)
    lines = _rich_lines(draw, "one two three four five", "three", _font(40), 170)
    flat = [w for line in lines for w, _ in line]
    assert flat == ["one", "two", "three", "four", "five"]
    assert dict((w, hot) for line in lines for w, hot in line)["three"] is True


def test_draw_rich_headline_paints_a_chip_pixel():
    img = Image.new("RGB", (600, 300), (240, 244, 230))
    draw = ImageDraw.Draw(img)
    font = _font(60)
    lines = _rich_lines(draw, "Pay ONCE yearly", "ONCE", font, 560)
    _draw_rich_headline(
        draw, lines, 40, 60, font, (15, 42, 29), (109, 144, 113), (15, 42, 29)
    )
    # A pixel inside the emphasis word's chip is the chip colour.
    x = 40 + int(draw.textlength("Pay ", font=font)) + 8
    assert img.getpixel((x, 70)) == (109, 144, 113)


class _PromoDirector:
    def direct_visual(self, plan_item, draft_text, brand_voice, style):
        return {
            "concept": "Gemini Pro, one year",
            "headline": "GEMINI PRO one year",
            "emphasis": "one year",
            "benefits": ["On your own email"],
            "price_line": "29,500 MMK",
        }


def test_produce_visual_promo_with_emphasis_still_composes(tmp_path):
    store = Store(tmp_path / "data")
    row = store.add_plan_row(
        {"topic": "Gemini Pro launch", "platform": "facebook",
         "visual_style": "promo", "status": "planned"}
    )
    row = store.update_row("plan", row["id"], {"draft": "Gemini Pro, 29,500 MMK."})
    result = produce_visual(store, row, image_client=None, director=_PromoDirector())
    assert (Path(store.data_dir) / result["visual"]).exists()


def test_meta_concept_direction_asks_for_emphasis(tmp_path, monkeypatch):
    client = MetaModelClient(api_key="<redacted>", usage_log=tmp_path / "u.jsonl")
    seen = {}

    def capturing_chat(messages, model=None, **kwargs):
        seen["messages"] = messages
        prompt = (
            "Concept: x\nComposition: y\nSubject: z\nSetting: s\n"
            "Camera and style: c\nConstraints: no text, no letters, "
            "no logos, no watermark. No exceptions: all inside."
        )
        reply = json.dumps(
            {"concept": "c", "prompt": prompt, "no_exceptions": "No exceptions: all",
             "headline": "Pay once", "emphasis": "once"}
        )
        return {"choices": [{"message": {"content": reply}}]}

    monkeypatch.setattr(client, "chat", capturing_chat)
    result = client.direct_visual({"topic": "T"}, "draft", {}, "concept")
    assert result["emphasis"] == "once"
    sent = " ".join(m["content"] for m in seen["messages"])
    assert "emphasis" in sent and "highlighted" in sent
