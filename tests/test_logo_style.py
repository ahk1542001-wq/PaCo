"""Per-brand logo_style setting (owner, 2026-11-18).

The logo treatment is a SETTING in each brand's own data —
never a hardcoded rule, because every client page differs.
"hero" composes the showcase/concept plate around the single
product's logo as the large central hero element; "badge" is
the badge strip every brand has today; "none" composites no
product logos. Unset or unrecognised is exactly today's
behaviour, so a brand that never chose never changes.
"""
from pathlib import Path

from PIL import Image

from pageops import designer
from pageops.chat import confirm_proposal, handle_message, pending_proposal
from pageops.designer import logo_style_for, produce_visual, render_visual
from pageops.model_client import MockClient
from pageops.store import Store

PLATE = (16, 26, 48)
LOGO_RED = (220, 30, 30)


def _write_logo(path: Path, colour=LOGO_RED):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (200, 100), colour).save(path)


def _brand(tmp_path, style=None):
    vis = tmp_path / "visuals"
    _write_logo(vis / "product-logos" / "coursera.png")
    _write_logo(vis / "product-logos" / "edx.png", (30, 30, 220))
    brand = {
        "brand_name": "Test Brand",
        "product_logos": (
            "coursera: product-logos/coursera.png; "
            "edx: product-logos/edx.png"
        ),
    }
    if style is not None:
        brand["logo_style"] = style
    return brand


def _plate(tmp_path, colour=PLATE):
    plate = tmp_path / "plate.png"
    Image.new("RGB", (1080, 1350), colour).save(plate)
    return plate


def _row(topic):
    return {
        "id": "7", "topic": topic, "angle": "",
        "platform": "facebook", "format": "post",
    }


def _render(tmp_path, brand, topic, style="concept", headline="Short hook"):
    path, manifest = render_visual(
        _row(topic), tmp_path / "visuals", brand_voice=brand,
        plate_path=_plate(tmp_path), style=style, headline=headline,
    )
    with Image.open(path) as img:
        rgb = img.convert("RGB")
        return rgb, manifest


def _is_logo_red(pixel):
    r, g, b = pixel
    return r > 150 and g < 90 and b < 90


# -- The setting's resolution ---------------------------------------------------


def test_logo_style_resolution_defaults_to_badge():
    assert logo_style_for(None) == "badge"
    assert logo_style_for({}) == "badge"
    assert logo_style_for({"logo_style": ""}) == "badge"
    assert logo_style_for({"logo_style": "bogus"}) == "badge"
    assert logo_style_for({"logo_style": "badge"}) == "badge"
    assert logo_style_for({"logo_style": " Hero "}) == "hero"
    assert logo_style_for({"logo_style": "NONE"}) == "none"


# -- Rendered behaviour ---------------------------------------------------------


def test_unset_logo_style_badges_exactly_as_today(tmp_path):
    rgb, manifest = _render(tmp_path, _brand(tmp_path), "Coursera ရပါပြီ")
    # The badge strip's white padding sits top-right...
    assert rgb.getpixel((890, 80)) == (255, 255, 255)
    # ...and the plate's centre carries no hero element.
    assert rgb.getpixel((540, 783)) == PLATE
    assert manifest["product_logo"] == "coursera"
    assert manifest["logo_style"] == "badge"
    assert manifest["logo_mode"] == "badge"


def test_badge_style_keeps_the_badge_strip(tmp_path):
    rgb, manifest = _render(
        tmp_path, _brand(tmp_path, style="badge"), "Coursera ရပါပြီ"
    )
    assert rgb.getpixel((890, 80)) == (255, 255, 255)
    assert rgb.getpixel((540, 783)) == PLATE
    assert manifest["logo_style"] == "badge"
    assert manifest["logo_mode"] == "badge"


def test_hero_single_product_composes_around_the_logo(tmp_path):
    rgb, manifest = _render(
        tmp_path, _brand(tmp_path, style="hero"), "Coursera ရပါပြီ",
        headline=None,
    )
    # The logo itself is the large central hero element...
    assert _is_logo_red(rgb.getpixel((540, 783)))
    # ...and no badge rides in the top-right corner.
    assert rgb.getpixel((890, 80)) == PLATE
    assert manifest["product_logo"] == "coursera"
    assert manifest["logo_style"] == "hero"
    assert manifest["logo_mode"] == "hero"


def test_hero_with_two_products_falls_back_to_the_badge_strip(tmp_path):
    rgb, manifest = _render(
        tmp_path, _brand(tmp_path, style="hero"),
        "Coursera နဲ့ edX ရပါပြီ",
    )
    # Both logos ride the strip (white padding top-right)...
    assert rgb.getpixel((890, 80)) == (255, 255, 255)
    # ...and no single hero takes the centre.
    assert rgb.getpixel((540, 783)) == PLATE
    assert manifest["product_logo"] == "coursera,edx"
    # The manifest records what was actually rendered, not
    # only the setting: a hero that fell back manifests as badge.
    assert manifest["logo_style"] == "hero"
    assert manifest["logo_mode"] == "badge"


def test_none_style_composites_no_product_logos(tmp_path):
    rgb, manifest = _render(
        tmp_path, _brand(tmp_path, style="none"), "Coursera ရပါပြီ",
        headline=None,
    )
    assert rgb.getpixel((890, 80)) == PLATE
    assert rgb.getpixel((540, 783)) == PLATE
    assert manifest["product_logo"] == ""
    assert manifest["logo_style"] == "none"
    assert manifest["logo_mode"] == "none"


def test_hero_with_missing_logo_file_falls_back_cleanly(tmp_path):
    brand = _brand(tmp_path, style="hero")
    # The brand data names a logo the visuals folder does not hold.
    (tmp_path / "visuals" / "product-logos" / "coursera.png").unlink()
    rgb, manifest = _render(tmp_path, brand, "Coursera ရပါပြီ", headline=None)
    assert rgb.getpixel((890, 80)) == PLATE
    assert rgb.getpixel((540, 783)) == PLATE
    assert manifest["product_logo"] == ""
    assert manifest["logo_mode"] == "badge"


def test_showcase_hero_centres_the_logo_in_the_upper_frame(tmp_path):
    path, manifest = render_visual(
        _row("Coursera ရပါပြီ"), tmp_path / "visuals",
        brand_voice=_brand(tmp_path, style="hero"),
        plate_path=_plate(tmp_path, colour=(24, 60, 44)),
        style="showcase", headline="Pay once",
        features=["Own email"], price_line="25,000 MMK",
    )
    with Image.open(path) as img:
        rgb = img.convert("RGB")
    # The hero logo owns the upper frame's centre...
    assert _is_logo_red(rgb.getpixel((540, 324)))
    # ...and the top-right badge spot keeps the plate's pixels.
    assert rgb.getpixel((1000, 80)) == (24, 60, 44)
    assert manifest["logo_style"] == "hero"
    assert manifest["logo_mode"] == "hero"


def test_hero_two_products_one_logo_missing_stays_a_badge_post(tmp_path):
    brand = _brand(tmp_path, style="hero")
    # The post sells TWO products, but only one logo file exists.
    (tmp_path / "visuals" / "product-logos" / "edx.png").unlink()
    rgb, manifest = _render(
        tmp_path, brand, "Coursera နဲ့ edX ရပါပြီ", headline=None
    )
    # The surviving logo rides the badge strip (white top-right)...
    assert rgb.getpixel((890, 80)) == (255, 255, 255)
    # ...and is NOT promoted to a hero centre just because it is
    # the only file on disk: hero needs exactly one product sold.
    assert rgb.getpixel((540, 783)) == PLATE
    assert manifest["product_logo"] == "coursera"
    assert manifest["logo_style"] == "hero"
    assert manifest["logo_mode"] == "badge"


def test_corrupt_logo_file_falls_back_without_raising(tmp_path):
    brand = _brand(tmp_path, style="hero")
    # The file exists but its bytes are not an image. The plan
    # counts only decodable files, so it degrades to the badge
    # path with no usable logo — and the manifest says so,
    # instead of recording a hero that never rendered.
    logo = tmp_path / "visuals" / "product-logos" / "coursera.png"
    logo.write_bytes(b"this is not a png")
    rgb, manifest = _render(tmp_path, brand, "Coursera ရပါပြီ", headline=None)
    assert rgb.getpixel((890, 80)) == PLATE
    assert rgb.getpixel((540, 783)) == PLATE
    assert manifest["logo_style"] == "hero"
    assert manifest["logo_mode"] == "badge"
    assert manifest["product_logo"] == ""


def test_product_hero_caps_the_upscale_at_twice_native(tmp_path):
    small = tmp_path / "small.png"
    Image.new("RGB", (100, 50), LOGO_RED).save(small)
    hero = designer._product_hero(small, 712, 540)
    assert hero is not None
    # The logo is capped at 2x native (200x100); the panel adds
    # its padding (2 x 44) and the shadow margin (16) around it —
    # it never grows to fill the whole hero box.
    assert hero.width <= 200 + 88 + 16
    assert hero.height <= 100 + 88 + 16


# -- Promo and carousel honour the setting too ---------------------------------


def _render_promo(tmp_path, brand, topic="Coursera ရပါပြီ"):
    direction = {"headline": "", "benefits": [], "price_line": ""}
    path, manifest = designer._render_promo(
        _row(topic), tmp_path / "visuals", brand, direction
    )
    with Image.open(path) as img:
        return img.convert("RGB"), manifest


def test_promo_default_style_renders_the_logo_tile(tmp_path):
    rgb, manifest = _render_promo(tmp_path, _brand(tmp_path))
    # The white tile sits centre-frame with the logo on it.
    assert rgb.getpixel((335, 300)) == (255, 255, 255)
    assert _is_logo_red(rgb.getpixel((540, 371)))
    assert manifest["product_logo"] == "coursera"


def test_promo_none_style_renders_no_logo_tile(tmp_path):
    brand = _brand(tmp_path, style="none")
    rgb, manifest = _render_promo(tmp_path, brand)
    background = designer.resolve_assets(brand)["background_rgb"]
    # Where the tile would sit, the bare background shows.
    assert rgb.getpixel((335, 300)) == background
    assert rgb.getpixel((540, 371)) == background
    assert manifest["product_logo"] == ""


def _render_carousel(tmp_path, brand, topic, headline="Short hook"):
    row = {
        "id": "7", "topic": topic, "angle": "",
        "platform": "facebook", "format": "carousel",
    }
    path, manifest = render_visual(
        row, tmp_path / "visuals", brand_voice=brand,
        plate_path=_plate(tmp_path), style="concept", headline=headline,
    )
    with Image.open(path) as img:
        return img.convert("RGB"), manifest


def test_carousel_slide_one_concept_honours_hero(tmp_path):
    rgb, manifest = _render_carousel(
        tmp_path, _brand(tmp_path, style="hero"), "Coursera ရပါပြီ",
        headline=None,
    )
    # Slide 1 is square; the hero owns its middle band...
    assert _is_logo_red(rgb.getpixel((540, 626)))
    # ...and no badge rides in the top-right corner.
    assert rgb.getpixel((890, 80)) == PLATE
    assert manifest["product_logo"] == "coursera"
    assert manifest["logo_style"] == "hero"
    assert manifest["logo_mode"] == "hero"


def test_carousel_slide_one_concept_honours_none(tmp_path):
    rgb, manifest = _render_carousel(
        tmp_path, _brand(tmp_path, style="none"), "Coursera ရပါပြီ",
        headline=None,
    )
    assert rgb.getpixel((890, 80)) == PLATE
    assert rgb.getpixel((540, 626)) == PLATE
    assert manifest["product_logo"] == ""
    assert manifest["logo_style"] == "none"
    assert manifest["logo_mode"] == "none"


# -- The full produce path reads the setting from the brand rows -----------------


class _ImageClient:
    def generate_image_bytes(self, prompt: str) -> bytes:
        from io import BytesIO

        buf = BytesIO()
        Image.new("RGB", (900, 1125), (24, 60, 44)).save(buf, format="PNG")
        return buf.getvalue()


def _store_with_logo(tmp_path, style=None):
    store = Store(tmp_path / "data")
    store.set_brand_value("brand_name", "Test Brand")
    store.set_brand_value(
        "product_logos", "coursera: product-logos/coursera.png"
    )
    if style is not None:
        store.set_brand_value("logo_style", style)
    _write_logo(store.data_dir / "visuals" / "product-logos" / "coursera.png")
    row = store.add_plan_row(
        {"topic": "Coursera အသစ်", "platform": "facebook",
         "visual_style": "concept", "status": "planned"}
    )
    return store, store.update_row(
        "plan", row["id"], {"draft": "Coursera, 25,000 MMK."}
    )


def test_produce_visual_honours_the_stored_hero_setting(tmp_path):
    store, row = _store_with_logo(tmp_path, style="hero")
    result = produce_visual(
        store, row, image_client=_ImageClient(), director=MockClient()
    )
    visual = Path(store.data_dir) / result["visual"]
    with Image.open(visual) as img:
        centre = img.convert("RGB").getpixel((540, 783))
    assert _is_logo_red(centre)


def test_produce_visual_without_the_setting_badges_as_today(tmp_path):
    store, row = _store_with_logo(tmp_path)
    result = produce_visual(
        store, row, image_client=_ImageClient(), director=MockClient()
    )
    visual = Path(store.data_dir) / result["visual"]
    with Image.open(visual) as img:
        centre = img.convert("RGB").getpixel((540, 783))
    # No hero: the centre keeps the plate's own colour.
    assert centre == (24, 60, 44)


# -- Chat settability -------------------------------------------------------------


def test_set_brand_logo_style_hero_proposes_and_confirms(tmp_path):
    store = Store(tmp_path)
    result = handle_message(store, MockClient(), "set logo_style to hero")
    assert "proposal_id" in result
    outcome = confirm_proposal(store, MockClient(), result["proposal_id"])
    assert outcome["ok"] is True
    raw = {r["key"]: r["value"] for r in store.read_dataset("brand_voice")}
    assert raw["logo_style"] == "hero"


def test_set_brand_logo_style_rejects_a_value_outside_the_three(tmp_path):
    store = Store(tmp_path)
    result = handle_message(store, MockClient(), "set logo_style to bogus")
    assert "proposal_id" not in result
    assert pending_proposal(store) is None
    assert "hero" in result["reply"] and "badge" in result["reply"]
    assert "none" in result["reply"]
