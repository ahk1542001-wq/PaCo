"""Designer brand resolution: a store's own brand voice must drive
the template renders (wordmark + palette), not the interim seed.

Regression for the 2026-11-10 AI Premium Myanmar 2.0 cycle, whose
posters came out wordmarked "FYF AI" in the seed navy/gold because
designer.ASSETS was used unconditionally.
"""
from PIL import Image

from pageops.designer import ASSETS, render_visual, resolve_assets, verify_visual

VOICE_20 = {
    "brand_name": "AI Premium Myanmar 2.0",
    "brand_colors": (
        "Deep navy #0A1728 (main, from the logo); bright blue #2090F0 "
        "(accent, from the logo); white for text space and contrast."
    ),
}

VOICE_FYF = {
    "brand_name": "FYF AI",
    "brand_colors": (
        "Deep Forest #0B3D2E (main, 55%: trust and all text); "
        "Fresh Paper #F4FAF5 (background, 20%); Live Green #00B140 "
        "(energy accent, 15%: symbol on dark versions, highlights, "
        "calls to action); Lime Spark #A6E22E (spark accent, 10%, "
        "sparing). Body text is always Deep Forest"
    ),
}

ROW = {
    "platform": "facebook",
    "topic": "Introducing the page",
    "angle": "What it sells and how to order",
    "format": "poster",
    "draft": "Hello. This is the new page. Message us to get started.",
}


def test_resolve_uses_store_name_and_labelled_colours():
    assets = resolve_assets(VOICE_20)
    assert assets["brand_name"] == "AI Premium Myanmar 2.0"
    assert assets["primary"] == "#0A1728"
    assert assets["accent"] == "#2090F0"
    assert assets["primary_rgb"] == (0x0A, 0x17, 0x28)
    assert assets["accent_rgb"] == (0x20, 0x90, 0xF0)


def test_resolve_reads_annotated_palette_roles():
    assets = resolve_assets(VOICE_FYF)
    assert assets["primary"] == "#0B3D2E"
    assert assets["background"] == "#F4FAF5"
    # The energy accent wins; the background and the sparing spark
    # accent are never picked as the main accent.
    assert assets["accent"] == "#00B140"


def test_resolve_falls_back_to_seed_without_identity():
    for voice in (None, {}, {"character_image": "assets/x.png"}):
        assets = resolve_assets(voice)
        assert assets["brand_name"] == ASSETS["brand_name"]
        assert assets["primary"] == ASSETS["primary"]
        assert assets["accent"] == ASSETS["accent"]
        assert assets["background"] == ASSETS["background"]


def test_render_uses_store_wordmark_and_primary(tmp_path):
    path, manifest = render_visual(ROW, tmp_path, brand_voice=VOICE_20)
    assert manifest["wordmark"] == "AI Premium Myanmar 2.0"
    assert manifest["primary"] == "#0A1728"
    with Image.open(path) as img:
        rgb = img.convert("RGB")
        assert rgb.getpixel((30, 30)) == (0x0A, 0x17, 0x28)
    ok, evidence = verify_visual(path, manifest)
    assert ok, evidence


def test_render_without_voice_keeps_seed_wordmark(tmp_path):
    _path, manifest = render_visual(ROW, tmp_path)
    assert manifest["wordmark"] == ASSETS["brand_name"]
    assert manifest["primary"] == ASSETS["primary"]
