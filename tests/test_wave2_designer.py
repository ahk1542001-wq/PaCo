"""Wave 2 Designer formats: banner, carousel, character sheet.

Plus the brand-data completion: the brand foundation values
(colours, fonts, logo usage, template sizes, proof baseline and
the character sheet path) live in the brand-assets layer as data,
seeded for new stores and backfilled for legacy ones.
"""
import io

import pytest
from PIL import Image

from pageops.designer import (
    REPO_ROOT,
    TEMPLATES,
    build_character_sheet,
    carousel_slides,
    produce_visual,
    render_visual,
    template_for,
    verify_visual,
)
from pageops.pipeline import update_brand_voice
from pageops.store import Store

BANNER_ROW = {
    "platform": "facebook",
    "topic": "A wide banner headline for the page",
    "angle": "The supporting line under the headline",
    "format": "Banner",
    "draft": "Banner draft. Message us to get started. #FYFAI",
}

CAROUSEL_ROW = {
    "platform": "facebook",
    "topic": "Three follow-ups that rescue a lost lead",
    "angle": "Practical tips from the CRM pack",
    "format": "Carousel",
    "draft": (
        "First point here. Second point follows. "
        "Message us to get started today. #FYFAI"
    ),
}


def _png_bytes(colour=(255, 0, 0)):
    buf = io.BytesIO()
    Image.new("RGBA", (200, 200), colour + (255,)).save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def repo_reference(tmp_path):
    """A valid red reference image inside the repo tree (cleaned up)."""
    path = REPO_ROOT / "assets" / f"test-{tmp_path.name}-ref.png"
    path.write_bytes(_png_bytes())
    yield path
    path.unlink(missing_ok=True)


def _red_pixels(path):
    with Image.open(path) as img:
        rgb = img.convert("RGB")
        pixels = rgb.load()
        return [
            (x, y)
            for y in range(rgb.height)
            for x in range(rgb.width)
            if pixels[x, y] == (255, 0, 0)
        ]


# -- Banner -------------------------------------------------------------------


def test_banner_template_registered_and_routed():
    assert TEMPLATES["banner"] == (1640, 924)
    assert template_for({"format": "Banner"}) == "banner"
    assert template_for({"format": "Campaign banner"}) == "banner"
    assert template_for({"format": "Carousel"}) == "carousel"


def test_banner_renders_at_template_size(tmp_path):
    path, manifest = render_visual(BANNER_ROW, tmp_path)
    assert manifest["template"] == "banner"
    assert manifest["format"] == "banner"
    with Image.open(path) as img:
        assert img.size == (1640, 924)
    ok, evidence = verify_visual(path, manifest)
    assert ok, evidence


def test_banner_badge_is_larger_and_on_the_right(tmp_path, repo_reference):
    reference = str(repo_reference.relative_to(REPO_ROOT))
    row = dict(BANNER_ROW, character="yes")
    path, manifest = render_visual(
        row, tmp_path, brand_voice={"character_image": reference}
    )
    assert manifest["character"]["used"] is True
    red = _red_pixels(path)
    assert red, "no badge pixels composited on the banner"
    xs = [p[0] for p in red]
    ys = [p[1] for p in red]
    measured = max(max(xs) - min(xs), max(ys) - min(ys)) + 1
    # Banner badge geometry: about 40% of the banner height.
    assert abs(measured - round(924 * 0.40)) <= 1
    centre_x = (min(xs) + max(xs)) // 2
    assert centre_x > 1640 * 0.6  # on the right of the canvas


# -- Carousel -------------------------------------------------------------------


def test_carousel_slide_plan_shape():
    plan = carousel_slides(CAROUSEL_ROW, {})
    assert plan[0]["kind"] == "hook"
    assert plan[-1]["kind"] == "cta"
    assert "Message us" in plan[-1]["text"]  # the draft's own CTA sentence
    assert [s["badge"] for s in plan] == [True] + [False] * (len(plan) - 2) + [True]
    assert all(s["text"] for s in plan)


def test_carousel_caps_middle_points_and_records_truncation(tmp_path):
    draft = ". ".join(f"Point {i}" for i in range(1, 11))
    draft += ". Message us to get started today."
    row = dict(CAROUSEL_ROW, draft=draft)
    plan = carousel_slides(row, {})
    assert len(plan) == 8  # hook + 6 capped points + CTA
    assert [s["kind"] for s in plan] == ["hook"] + ["point"] * 6 + ["cta"]
    _, manifest = render_visual(row, tmp_path)
    assert manifest["slides_truncated"] is True
    assert manifest["points_total"] == 10
    assert len(manifest["slides"]) == 8


def test_carousel_renders_slide_set(tmp_path):
    path, manifest = render_visual(CAROUSEL_ROW, tmp_path)
    assert manifest["format"] == "carousel"
    assert manifest["template"] == "carousel"
    assert manifest["slides_truncated"] is False
    assert manifest["points_total"] == 3
    slides = manifest["slides"]
    assert len(slides) == len(carousel_slides(CAROUSEL_ROW, {}))
    assert str(path) == slides[0]
    for slide in slides:
        with Image.open(slide) as img:
            assert img.size == (1080, 1080)
        ok, evidence = verify_visual(slide, manifest)
        assert ok, evidence


def test_carousel_slide_names_carry_row_id(tmp_path):
    row = dict(CAROUSEL_ROW, id="42")
    _, manifest = render_visual(row, tmp_path)
    names = [s.rsplit("/", 1)[-1] for s in manifest["slides"]]
    assert names == [f"visual-42-slide-{i}.png" for i in range(1, len(names) + 1)]


def test_carousel_character_on_first_and_last_slides_only(tmp_path, repo_reference):
    reference = str(repo_reference.relative_to(REPO_ROOT))
    row = dict(CAROUSEL_ROW, character="yes")
    _, manifest = render_visual(
        row, tmp_path, brand_voice={"character_image": reference}
    )
    assert manifest["character"]["used"] is True
    slides = manifest["slides"]
    assert _red_pixels(slides[0]), "badge missing on slide 1"
    assert _red_pixels(slides[-1]), "badge missing on the final slide"
    assert not _red_pixels(slides[1]), "badge leaked onto a middle slide"


def test_produce_visual_carousel_stores_slide_one_and_all_slides_exist(tmp_path):
    store = Store(tmp_path / "data")
    row = store.add_plan_row(dict(CAROUSEL_ROW, status="drafted"))
    updated = produce_visual(store, row)
    assert updated["visual"].endswith("-slide-1.png")
    assert (store.data_dir / updated["visual"]).exists()
    slide_files = sorted((store.data_dir / "visuals").glob("*-slide-*.png"))
    assert len(slide_files) == len(carousel_slides(CAROUSEL_ROW, {}))


def test_produce_visual_carousel_character_failure_flags(tmp_path):
    store = Store(tmp_path / "data")
    store.set_brand_value("character_image", "assets/does-not-exist.png")
    row = store.add_plan_row(dict(CAROUSEL_ROW, character="yes", status="drafted"))
    with pytest.raises(RuntimeError, match="character check failed"):
        produce_visual(store, row)


# -- Character sheet ------------------------------------------------------------


def test_build_character_sheet_from_seed_reference(tmp_path):
    voice = Store(tmp_path / "store").get_brand_voice()
    out = build_character_sheet(voice, tmp_path / "sheet.png")
    assert out.exists()
    with Image.open(out) as img:
        assert img.size == (1800, 1200)
    # Content: a panel carries the reference's own dominant colour,
    # derived from the reference image (never a hardcoded value):
    # the sheet is composed from the reference, so its most common
    # non-background colour must appear among the sheet's pixels.
    from collections import Counter

    with Image.open(REPO_ROOT / voice["character_image"]) as ref:
        counts = Counter(ref.convert("RGB").getdata())
    reference_colour = next(
        colour for colour, _n in counts.most_common() if colour != (255, 255, 255)
    )
    with Image.open(out) as sheet:
        sheet_colours = set(sheet.convert("RGB").getdata())
    assert reference_colour in sheet_colours


def test_build_character_sheet_missing_reference_raises(tmp_path):
    with pytest.raises(RuntimeError, match="reference missing"):
        build_character_sheet(
            {"character_image": "assets/does-not-exist.png", "character_name": "PaCo"},
            tmp_path / "sheet.png",
        )


def test_character_sheet_asset_is_in_the_repo():
    sheet = REPO_ROOT / "assets" / "paco-character-sheet.png"
    assert sheet.exists()
    with Image.open(sheet) as img:
        assert img.size == (1800, 1200)


# -- Brand data completion --------------------------------------------------------


def test_brand_seed_carries_foundation_keys(tmp_path):
    voice = Store(tmp_path).get_brand_voice()
    assert voice["character_sheet"] == "assets/paco-character-sheet.png"
    for hexcode in ("#0B3D2E", "#F4FAF5", "#00B140", "#A6E22E"):
        assert hexcode in voice["brand_colors"]
    assert "Padauk" in voice["brand_fonts"]
    assert "Opening Path" in voice["logo_usage"]
    assert "poster 1080x1350" in voice["template_sizes"]
    assert "banner 1640x924" in voice["template_sizes"]
    assert "video frame 1080x1920" in voice["template_sizes"]
    assert "15 followers" in voice["proof_baseline"]
    assert "970 views" in voice["proof_baseline"]


def test_foundation_keys_are_brand_panel_editable(tmp_path):
    store = Store(tmp_path)
    for key in (
        "character_sheet",
        "brand_colors",
        "brand_fonts",
        "logo_usage",
        "template_sizes",
        "proof_baseline",
    ):
        update_brand_voice(store, key, f"edited {key}")
        raw = {r["key"]: r["value"] for r in store.read_dataset("brand_voice")}
        assert raw[key] == f"edited {key}"


def test_legacy_store_backfills_foundation_keys_without_overwriting(tmp_path):
    data = tmp_path / "legacy"
    data.mkdir()
    (data / "brand_voice.csv").write_text(
        "key,value\n"
        "brand_name,Owner Edited Co\n"
        "brand_colors,Primary #000000\n",
        encoding="utf-8",
    )
    voice = Store(data).get_brand_voice()
    assert voice["brand_name"] == "Owner Edited Co"
    assert voice["brand_colors"] == "Primary #000000"  # present key kept
    assert voice["character_sheet"] == "assets/paco-character-sheet.png"
    assert "Padauk" in voice["brand_fonts"]  # absent keys backfilled
    assert "970 views" in voice["proof_baseline"]
