"""Graphic Designer stage (M21): template-based visual production.

The Designer produces a post's visual from brand templates only,
after the Copywriter's draft exists, and checks its own work
(template compliance) before the row moves on.
"""
import pytest
from PIL import Image

from pageops.designer import (
    ASSETS,
    produce_visual,
    render_visual,
    verify_visual,
)
from pageops.model_client import MockClient
from pageops.pipeline import process_week
from pageops.store import Store

ROW = {
    "platform": "facebook",
    "topic": "Replying to customers when you are busy",
    "angle": "Show the owner answering once, the bot answering after",
    "format": "poster",
    "draft": "Busy day? Your page still answers. FYF AI chatbots reply "
    "to price and delivery questions while you work. #FYFAI",
}


def test_render_produces_template_sized_png(tmp_path):
    path, manifest = render_visual(ROW, tmp_path)
    assert path.exists()
    with Image.open(path) as img:
        assert img.size == manifest["size"] == (1080, 1350)
    assert manifest["template"] == "poster"
    assert manifest["wordmark"] == ASSETS["brand_name"]


def test_render_uses_brand_primary_colour(tmp_path):
    path, _ = render_visual(ROW, tmp_path)
    with Image.open(path) as img:
        pixels = img.convert("RGB")
        found = any(
            pixels.getpixel((x, y)) == ASSETS["primary_rgb"]
            for x in range(0, 1080, 60)
            for y in range(0, 120, 10)
        )
    assert found, "brand primary colour missing from the top band"


def test_thumb_format_uses_thumb_template(tmp_path):
    row = dict(ROW, format="thumbnail")
    path, manifest = render_visual(row, tmp_path)
    with Image.open(path) as img:
        assert img.size == (1080, 1080)
    assert manifest["template"] == "thumb"


def test_verify_visual_accepts_own_output_and_rejects_wrong_size(tmp_path):
    path, manifest = render_visual(ROW, tmp_path)
    ok, evidence = verify_visual(path, manifest)
    assert ok, evidence
    bad = tmp_path / "bad.png"
    Image.new("RGB", (400, 400)).save(bad)
    ok, evidence = verify_visual(bad, manifest)
    assert not ok
    assert "size" in evidence


def test_produce_visual_refuses_row_without_draft(tmp_path):
    store = Store(tmp_path)
    row = store.add_plan_row(
        {"platform": "facebook", "topic": "No draft yet", "status": "planned"}
    )
    with pytest.raises(ValueError, match="draft"):
        produce_visual(store, row)


def test_produce_visual_stores_path_on_row(tmp_path):
    store = Store(tmp_path)
    row = store.add_plan_row(dict(ROW, status="drafted"))
    updated = produce_visual(store, row)
    assert updated["visual"]
    visual_path = tmp_path / updated["visual"]
    assert visual_path.exists()
    reread = [r for r in store.read_dataset("plan") if r["id"] == row["id"]][0]
    assert reread["visual"] == updated["visual"]


def test_pipeline_rows_gain_visuals(tmp_path):
    store = Store(tmp_path)
    rows = process_week(store, MockClient(), "Promote the chatbot offer")
    for row in rows:
        assert row["visual"], "pipeline row has no visual"
        assert (tmp_path / row["visual"]).exists()
        assert "visual" in row["check_status"].lower()
