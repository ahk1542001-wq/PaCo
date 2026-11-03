"""Concept mode: directed, generated still visuals in two styles.

The planner chooses a visual_style per item ("scene" or
"concept"); the director (Wonder in production, MockClient here)
writes a concept line and an image prompt; one generated plate
becomes the full-bleed background and the Designer composites the
typography in code. Templates remain the fallback: any failure in
direction or generation renders the template and records why.
"""
import io
import json
from pathlib import Path

import pytest
from PIL import Image

from pageops.designer import (
    _FONT_CANDIDATES,
    ASSETS,
    TEMPLATES,
    direct_plate,
    produce_visual,
    render_visual,
    verify_visual,
    visual_style_for,
)
from pageops.model_client import MetaModelClient, MockClient
from pageops.pipeline import process_week
from pageops.store import Store

SCENE_ROW = {
    "platform": "facebook",
    "topic": "Before and after: one inbox, zero missed price questions",
    "angle": "Show the saved replies, then the offer",
    "format": "Poster",
    "visual_style": "scene",
    "draft": "One inbox, zero missed price questions. Message us to get started. #FYFAI",
}

CONCEPT_ROW = dict(SCENE_ROW, visual_style="concept")

CAROUSEL_ROW = {
    "platform": "facebook",
    "topic": "Three follow-ups that rescue a lost lead",
    "angle": "Practical tips from the CRM pack",
    "format": "Carousel",
    "visual_style": "scene",
    "draft": (
        "First point here. Second point follows. "
        "Message us to get started today. #FYFAI"
    ),
}


def _plate_bytes(fmt="PNG"):
    """A distinctive gradient plate (burnt orange), photo-like size."""
    img = Image.new("RGB", (480, 640))
    px = img.load()
    for y in range(640):
        for x in range(480):
            px[x, y] = (200 - y // 8, 90 + x // 6, 30)
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()


class _FakeImageClient:
    def __init__(self, raw):
        self.raw = raw
        self.prompts = []

    def generate_image_bytes(self, prompt):
        self.prompts.append(prompt)
        return self.raw


class _FailingImageClient:
    def generate_image_bytes(self, prompt):
        raise RuntimeError("image backend down")


class _FailingDirector:
    def direct_visual(self, plan_item, draft_text, brand_voice, style):
        raise RuntimeError("director down")


def _store_row(tmp_path, row):
    store = Store(tmp_path / "data")
    stored = store.add_plan_row(dict(row, status="drafted"))
    return store, stored


# -- Plan contract -----------------------------------------------------------


def test_mock_plan_carries_both_styles():
    plan = MockClient().generate_plan("Brief", {"brand_name": "FYF AI"})
    styles = [p.get("visual_style", "") for p in plan["posts"]]
    assert "concept" in styles
    assert "scene" in styles
    assert all(s in ("scene", "concept", "") for s in styles)


def test_meta_plan_prompt_asks_for_visual_style(tmp_path, monkeypatch):
    client = MetaModelClient(api_key="<redacted>", usage_log=tmp_path / "u.jsonl")
    captured = {}

    def fake_chat(messages, model=None, **kwargs):
        captured["messages"] = messages
        return {"choices": [{"message": {"content": json.dumps({"posts": []})}}]}

    monkeypatch.setattr(client, "chat", fake_chat)
    client.generate_plan("Brief", {"brand_name": "FYF AI"})
    instruction = captured["messages"][1]["content"]
    assert "visual_style" in instruction
    assert '"scene"' in instruction and '"concept"' in instruction


# -- Direction ---------------------------------------------------------------


def test_mock_direct_visual_is_deterministic_and_complete():
    client = MockClient()
    item = {"topic": "Zero missed messages", "character": "yes"}
    voice = {"brand_name": "FYF AI", "character_name": "PaCo"}
    scene_a = client.direct_visual(item, "draft", voice, "scene")
    scene_b = client.direct_visual(item, "draft", voice, "scene")
    assert scene_a == scene_b
    assert "top third" in scene_a["prompt"]
    assert "No text" in scene_a["prompt"] and "no logos" in scene_a["prompt"]
    assert "PaCo" in scene_a["prompt"]  # character-marked row names the character

    concept = client.direct_visual(item, "draft", voice, "concept")
    for header in ("Concept", "Composition", "Subject", "Setting", "Camera and style", "Constraints"):
        assert header in concept["prompt"]
    constraints = concept["prompt"].split("Constraints:")[1]
    for required in ("no text", "no letters", "no logos", "no watermark", "clean negative space"):
        assert required in constraints
    assert concept["no_exceptions"].startswith("No exceptions")
    assert "No exceptions" in constraints  # the clause rides inside the prompt too


def _meta_client(tmp_path, monkeypatch, reply):
    client = MetaModelClient(api_key="<redacted>", usage_log=tmp_path / "u.jsonl")

    def fake_chat(messages, model=None, **kwargs):
        return {"choices": [{"message": {"content": reply}}]}

    monkeypatch.setattr(client, "chat", fake_chat)
    return client


CONCEPT_PROMPT = (
    "Concept: chat bubbles rain down and one wide umbrella keeps the shop dry.\n"
    "Composition: the umbrella centred, the shop beneath it, clean sky above.\n"
    "Subject: a wide gold umbrella over a small shop counter.\n"
    "Setting: night rain made of glowing chat bubbles.\n"
    "Camera and style: straight-on, soft light, high detail.\n"
    "Constraints: no text, no letters, no logos, no watermark, clean negative "
    "space for a headline. No exceptions: every bubble lands on the umbrella, "
    "none reaches the shop."
)


def test_meta_direct_visual_concept_parses(tmp_path, monkeypatch):
    reply = json.dumps(
        {
            "concept": "Chat bubbles rain; one umbrella keeps the shop dry.",
            "prompt": CONCEPT_PROMPT,
            "no_exceptions": "No exceptions: every bubble lands on the umbrella.",
        }
    )
    client = _meta_client(tmp_path, monkeypatch, reply)
    out = client.direct_visual({"topic": "T"}, "draft", {}, "concept")
    assert out["concept"].startswith("Chat bubbles rain")
    assert out["no_exceptions"].startswith("No exceptions")
    assert "Constraints" in out["prompt"]


def test_meta_direct_visual_scene_parses(tmp_path, monkeypatch):
    reply = json.dumps(
        {
            "concept": "The inbox as a warm evening shop counter.",
            "prompt": "A rich warm scene in deep blue and gold, clean space in "
            "the top third for a headline. No text, no logos anywhere.",
        }
    )
    client = _meta_client(tmp_path, monkeypatch, reply)
    out = client.direct_visual({"topic": "T"}, "draft", {}, "scene")
    assert out["concept"].startswith("The inbox")
    assert out["no_exceptions"] == ""


def test_meta_direct_visual_rejects_bad_replies(tmp_path, monkeypatch):
    item, voice = {"topic": "T"}, {}
    client = _meta_client(tmp_path, monkeypatch, "not json at all")
    with pytest.raises(ValueError):
        client.direct_visual(item, "draft", voice, "scene")

    # Concept reply without the no-exceptions line: the metaphor is
    # not airtight on paper, so direction fails and callers fall back.
    reply = json.dumps({"concept": "C", "prompt": CONCEPT_PROMPT})
    client = _meta_client(tmp_path, monkeypatch, reply)
    with pytest.raises(ValueError):
        client.direct_visual(item, "draft", voice, "concept")

    # Concept prompt missing a section.
    broken = CONCEPT_PROMPT.replace("Setting:", "Place:")
    reply = json.dumps(
        {"concept": "C", "prompt": broken, "no_exceptions": "No exceptions: x."}
    )
    client = _meta_client(tmp_path, monkeypatch, reply)
    with pytest.raises(ValueError):
        client.direct_visual(item, "draft", voice, "concept")


# -- Production --------------------------------------------------------------


def test_scene_plate_compositing(tmp_path):
    store, row = _store_row(tmp_path, SCENE_ROW)
    fake = _FakeImageClient(_plate_bytes())
    updated = produce_visual(store, row, image_client=fake, director=MockClient())
    assert updated["visual"]
    path = store.data_dir / updated["visual"]
    with Image.open(path) as img:
        assert img.size == TEMPLATES["poster"]
        # Scrim: the very top row is exactly the brand primary.
        assert img.convert("RGB").getpixel((30, 0)) == ASSETS["primary_rgb"]
        # Below the scrim the plate shows through (burnt orange).
        pixel = img.convert("RGB").getpixel((540, 1100))
        assert pixel[0] > 120 and pixel[2] < 90
    assert (store.data_dir / "visuals" / f"plate-{row['id']}.png").exists()
    assert fake.prompts and "No text" in fake.prompts[0]

    # The manifest records the plate and the style.
    plate_file = store.data_dir / "visuals" / f"plate-{row['id']}.png"
    _p, manifest = render_visual(
        row, tmp_path / "again", brand_voice=store.get_brand_voice(),
        plate_path=plate_file, style="scene",
    )
    assert manifest["plate"] == {"used": True, "reason": ""}
    assert manifest["style"] == "scene"
    ok, evidence = verify_visual(_p, manifest)
    assert ok, evidence

    # The concept record from the direction step.
    concept, plate, _path = direct_plate(
        row, store.get_brand_voice(), tmp_path / "direct", MockClient(), fake
    )
    assert concept["style"] == "scene"
    assert concept["concept"] and concept["prompt"]
    assert plate == {"used": True, "reason": ""}


def test_concept_plate_compositing_and_record(tmp_path):
    store, row = _store_row(tmp_path, CONCEPT_ROW)
    concept, plate, plate_path = direct_plate(
        row, store.get_brand_voice(), tmp_path / "direct", MockClient(),
        _FakeImageClient(_plate_bytes()),
    )
    assert concept["style"] == "concept"
    assert concept["no_exceptions"].startswith("No exceptions")
    assert "No exceptions" in concept["prompt"]
    assert plate["used"] is True

    updated = produce_visual(
        store, row, image_client=_FakeImageClient(_plate_bytes()), director=MockClient()
    )
    path = store.data_dir / updated["visual"]
    with Image.open(path) as img:
        assert img.size == TEMPLATES["poster"]
        # The wordmark chip is solid primary in the top-left corner.
        assert img.convert("RGB").getpixel((50, 45)) == ASSETS["primary_rgb"]


def test_banner_plate_compositing(tmp_path):
    store, row = _store_row(tmp_path, dict(SCENE_ROW, format="Banner"))
    updated = produce_visual(
        store, row, image_client=_FakeImageClient(_plate_bytes()), director=MockClient()
    )
    with Image.open(store.data_dir / updated["visual"]) as img:
        assert img.size == TEMPLATES["banner"]


def test_webp_plate_is_normalised_to_png(tmp_path):
    store, row = _store_row(tmp_path, SCENE_ROW)
    updated = produce_visual(
        store, row, image_client=_FakeImageClient(_plate_bytes("WEBP")),
        director=MockClient(),
    )
    assert updated["visual"]
    plate_file = store.data_dir / "visuals" / f"plate-{row['id']}.png"
    with Image.open(plate_file) as img:
        assert img.format == "PNG"


# -- Fallbacks ---------------------------------------------------------------


def _template_bytes(tmp_path, store, row):
    path, _m = render_visual(row, tmp_path / "template", brand_voice=store.get_brand_voice())
    return path.read_bytes()


def test_image_failure_falls_back_to_template(tmp_path):
    store, row = _store_row(tmp_path, SCENE_ROW)
    updated = produce_visual(
        store, row, image_client=_FailingImageClient(), director=MockClient()
    )
    produced = (store.data_dir / updated["visual"]).read_bytes()
    assert produced == _template_bytes(tmp_path, store, row)
    assert not (store.data_dir / "visuals" / f"plate-{row['id']}.png").exists()

    concept, plate, plate_path = direct_plate(
        row, store.get_brand_voice(), tmp_path / "d", MockClient(), _FailingImageClient()
    )
    assert concept["prompt"]  # direction is recorded even though generation failed
    assert plate["used"] is False and "image backend down" in plate["reason"]
    assert plate_path is None


def test_direction_failure_falls_back_to_template(tmp_path):
    store, row = _store_row(tmp_path, CONCEPT_ROW)
    updated = produce_visual(
        store, row, image_client=_FakeImageClient(_plate_bytes()),
        director=_FailingDirector(),
    )
    produced = (store.data_dir / updated["visual"]).read_bytes()
    assert produced == _template_bytes(tmp_path, store, row)

    concept, plate, plate_path = direct_plate(
        row, store.get_brand_voice(), tmp_path / "d", _FailingDirector(),
        _FakeImageClient(_plate_bytes()),
    )
    assert concept["concept"] == "" and concept["prompt"] == ""
    assert plate["used"] is False and "direction failed" in plate["reason"]
    assert plate_path is None


class _NoneDirector:
    """A director that returns garbage instead of raising."""

    def direct_visual(self, plan_item, draft_text, brand_voice, style):
        return None


def test_garbage_direction_falls_back_to_template(tmp_path):
    store, row = _store_row(tmp_path, CONCEPT_ROW)
    updated = produce_visual(
        store, row, image_client=_FakeImageClient(_plate_bytes()),
        director=_NoneDirector(),
    )
    produced = (store.data_dir / updated["visual"]).read_bytes()
    assert produced == _template_bytes(tmp_path, store, row)

    concept, plate, plate_path = direct_plate(
        row, store.get_brand_voice(), tmp_path / "d", _NoneDirector(),
        _FakeImageClient(_plate_bytes()),
    )
    assert concept["concept"] == "" and concept["prompt"] == ""
    assert plate["used"] is False and "direction failed" in plate["reason"]
    assert plate_path is None


def test_no_clients_renders_template_as_before(tmp_path):
    store, row = _store_row(tmp_path, SCENE_ROW)
    updated = produce_visual(store, row)
    produced = (store.data_dir / updated["visual"]).read_bytes()
    assert produced == _template_bytes(tmp_path, store, row)


# -- Carousel ----------------------------------------------------------------


def test_carousel_plate_applies_to_slide_one_only(tmp_path):
    store, row = _store_row(tmp_path, CAROUSEL_ROW)
    updated = produce_visual(
        store, row, image_client=_FakeImageClient(_plate_bytes()), director=MockClient()
    )
    slide1 = store.data_dir / updated["visual"]
    slide2 = slide1.with_name(f"visual-{row['id']}-slide-2.png")
    tpath, tmanifest = render_visual(
        row, tmp_path / "template", brand_voice=store.get_brand_voice()
    )
    assert slide1.read_bytes() != tpath.read_bytes()  # plate on slide 1
    template_slide2 = Path(tmanifest["slides"][1])
    assert slide2.read_bytes() == template_slide2.read_bytes()  # template after
    with Image.open(slide1) as img:
        assert img.size == TEMPLATES["carousel"]


# -- Legacy rows + plumbing ---------------------------------------------------


def test_legacy_row_without_style_defaults_to_scene(tmp_path):
    row = {k: v for k, v in SCENE_ROW.items() if k != "visual_style"}
    assert visual_style_for(row) == "scene"
    store, stored = _store_row(tmp_path, row)
    concept, plate, _p = direct_plate(
        stored, store.get_brand_voice(), tmp_path / "d", MockClient(),
        _FakeImageClient(_plate_bytes()),
    )
    assert concept["style"] == "scene"
    assert plate["used"] is True


def test_pipeline_wires_director_and_image_client(tmp_path):
    store = Store(tmp_path / "data")
    fake = _FakeImageClient(_plate_bytes())
    rows = process_week(store, MockClient(), "Promote the chatbot offer", image_client=fake)
    assert len(rows) == 7
    assert all(r["status"] == "awaiting_approval" for r in rows)
    assert fake.prompts  # the pipeline's client directed visuals
    plates = list((store.data_dir / "visuals").glob("plate-*.png"))
    assert plates  # and plates were generated through the pipeline


def test_mock_week_stays_hermetic_and_stores_styles(tmp_path):
    store = Store(tmp_path / "data")
    rows = process_week(store, MockClient(), "Promote the chatbot offer")
    assert all(r["status"] == "awaiting_approval" for r in rows)
    styles = [r.get("visual_style", "") for r in rows]
    assert "concept" in styles and "scene" in styles
    assert all(r.get("visual") for r in rows)
    assert not list((store.data_dir / "visuals").glob("plate-*.png"))


@pytest.mark.skipif(
    not any(path.exists() for path in _FONT_CANDIDATES),
    reason="brand font not available in this environment",
)
def test_scene_scrim_covers_the_whole_text_block(tmp_path):
    """Regression: in the first real Concept run the scene subline ran
    off the scrim onto the bare photograph and was unreadable. The
    scrim is now sized to the measured text block with a slower fade;
    over a white plate, points at the right edge (beyond the text
    measure, so pure scrim) must be visibly darkened deep into the
    text zone."""
    buf = io.BytesIO()
    Image.new("RGB", (480, 640), (255, 255, 255)).save(buf, format="PNG")
    row = dict(
        SCENE_ROW,
        topic=(
            "How one small shop answers every customer question about "
            "prices, delivery times and opening hours automatically, "
            "even while the owner is asleep"
        ),
        angle=(
            "Teach Myanmar and Thai SME owners to automate replies for "
            "prices, delivery and opening hours; invite them to message "
            "us on Messenger for the example list and a free mini-audit "
            "of their own page this week"
        ),
    )
    store, stored = _store_row(tmp_path, row)
    updated = produce_visual(
        store, stored,
        image_client=_FakeImageClient(buf.getvalue()),
        director=MockClient(),
    )
    img = Image.open(store.data_dir / updated["visual"]).convert("RGB")
    w, h = img.size
    assert img.getpixel((w - 30, int(h * 0.48)))[1] < 215
    assert img.getpixel((w - 30, int(h * 0.59)))[1] < 250


def test_meta_concept_instruction_demands_legibility(tmp_path, monkeypatch):
    """The direction instruction itself must carry the one-glance
    legibility clause (owner's rule, 2026-11-03): metaphor elements
    drawn as the literal thing they represent, never abstract orbs."""
    client = MetaModelClient(api_key="<redacted>", usage_log=tmp_path / "u.jsonl")
    seen = {}

    def capturing_chat(messages, model=None, **kwargs):
        seen["messages"] = messages
        reply = json.dumps(
            {"concept": "C", "prompt": CONCEPT_PROMPT,
             "no_exceptions": "No exceptions: every bubble lands on the umbrella."}
        )
        return {"choices": [{"message": {"content": reply}}]}

    monkeypatch.setattr(client, "chat", capturing_chat)
    client.direct_visual({"topic": "T"}, "draft", {}, "concept")
    sent = " ".join(m["content"] for m in seen["messages"])
    assert "instantly recognisable" in sent
    assert "never as abstract orbs" in sent
