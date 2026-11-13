"""Multi-product badge tests (owner rule, 2026-11-13).

A post selling more than one named product must badge EVERY
product it sells with its real logo — one badge (or none) leaves
viewers unable to tell what the other product is.
"""
from pathlib import Path

from PIL import Image

from pageops import designer


def _logo(path: Path, colour):
    Image.new("RGB", (200, 100), colour).save(path)


def _brand(tmp_path):
    vis = tmp_path / "product-logos"
    vis.mkdir()
    _logo(vis / "coursera.png", (0, 86, 210))
    _logo(vis / "edx.png", (200, 0, 100))
    return {
        "product_logos": "canva: product-logos/canva.png; "
        "coursera: product-logos/coursera.png; edx: product-logos/edx.png",
        "brand_name": "Test Brand",
    }


def test_all_matching_products_returned_in_brand_order(tmp_path):
    row = {"topic": "Coursera နဲ့ edX ရပါပြီ", "angle": "edx 20,000 / coursera 25,000"}
    found = designer.product_logos_for(row, _brand(tmp_path))
    assert [slug for slug, _ in found] == ["coursera", "edx"]


def test_single_match_and_no_match_still_behave(tmp_path):
    brand = _brand(tmp_path)
    one = {"topic": "Canva Education Pro အသစ်", "angle": ""}
    assert [s for s, _ in designer.product_logos_for(one, brand)] == ["canva"]
    none = {"topic": "ဘာရွေးရမလဲ", "angle": "education"}
    assert designer.product_logos_for(none, brand) == []
    # The single-match helper keeps its old contract.
    assert designer.product_logo_for(one, brand)[0] == "canva"
    assert designer.product_logo_for(none, brand) is None


def test_badge_row_joins_two_logos(tmp_path):
    brand = _brand(tmp_path)
    vis = tmp_path
    paths = [vis / rel for _, rel in designer.product_logos_for(
        {"topic": "Coursera နဲ့ edX", "angle": ""}, brand)]
    strip = designer._product_badge_row(paths)
    single = designer._product_badge(paths[0])
    assert strip is not None and single is not None
    assert strip.width > single.width
    assert designer._product_badge_row([vis / "missing.png"]) is None
