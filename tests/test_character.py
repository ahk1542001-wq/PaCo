"""Brand character (PaCo mascot) support.

The brand-assets layer carries the character reference; the
Designer composites it as a circular badge on rows that request it;
the Brand Checker verifies the badge came from the brand reference.
A missing or unreadable reference degrades honestly: no badge, and
a requested row is flagged rather than silently passed.

References resolve with repo-root containment, so a usable test
reference must live inside the repo tree (fixtures below write
into assets/ and clean up); files outside the repo, including
tmp_path, correctly read as missing.
"""
import io
import os

import pytest
from PIL import Image

from pageops import designer
from pageops.checker import check_character
from pageops.designer import (
    ASSETS,
    REPO_ROOT,
    produce_visual,
    render_visual,
    verify_visual,
)
from pageops.model_client import MockClient
from pageops.pipeline import draft_and_check, update_brand_voice
from pageops.store import Store

ROW = {
    "platform": "facebook",
    "topic": "A big announcement for page owners",
    "angle": "PaCo presents the news",
    "format": "poster",
    "character": "yes",
    "draft": "Announcement draft. Message us to get started. #FYFAI",
}


def _png_bytes(colour=(255, 0, 0)):
    buf = io.BytesIO()
    Image.new("RGBA", (200, 200), colour + (255,)).save(buf, format="PNG")
    return buf.getvalue()


def _tiny_reference(path, colour=(255, 0, 0)):
    Image.new("RGBA", (200, 200), colour + (255,)).save(path)
    return path


@pytest.fixture
def repo_file(tmp_path):
    """Write a file inside the repo tree (assets/); removed after."""
    created = []

    def make(name, data: bytes):
        path = REPO_ROOT / "assets" / f"test-{tmp_path.name}-{name}"
        path.write_bytes(data)
        created.append(path)
        return path

    yield make
    for path in created:
        path.unlink(missing_ok=True)


@pytest.fixture
def repo_reference(repo_file):
    """A valid red reference image inside the repo tree."""
    return repo_file("ref.png", _png_bytes())


def test_brand_seed_carries_character_keys(tmp_path):
    voice = Store(tmp_path).get_brand_voice()
    assert voice["character_name"] == "PaCo"
    assert voice["character_image"] == "assets/paco-character.png"
    assert "circular badge" in voice["character_rules"]


def test_character_keys_are_brand_panel_editable(tmp_path):
    store = Store(tmp_path)
    update_brand_voice(store, "character_image", "assets/other.png")
    assert store.get_brand_voice()["character_image"] == "assets/other.png"
    update_brand_voice(store, "character_name", "PaCo")
    update_brand_voice(store, "character_rules", "Badge only.")


def test_legacy_store_backfills_character_keys_without_overwriting(tmp_path):
    data = tmp_path / "legacy"
    data.mkdir()
    (data / "brand_voice.csv").write_text(
        "key,value\n"
        "brand_name,Owner Edited Co\n"
        "character_image,assets/owner-custom.png\n",
        encoding="utf-8",
    )
    voice = Store(data).get_brand_voice()
    assert voice["brand_name"] == "Owner Edited Co"  # owner values untouched
    assert voice["character_image"] == "assets/owner-custom.png"  # present key kept
    assert voice["character_name"] == "PaCo"  # absent keys backfilled from the seed
    assert "circular badge" in voice["character_rules"]


def test_mock_plan_marks_exactly_two_character_posts():
    plan = MockClient().generate_plan("Brief", {"brand_name": "FYF AI"})
    marked = [p for p in plan["posts"] if p.get("character") == "yes"]
    assert len(marked) == 2
    assert len(plan["posts"]) == 7


def test_designer_composites_badge_and_records_manifest(tmp_path, repo_reference):
    reference = str(repo_reference.relative_to(REPO_ROOT))
    brand = {"character_image": reference}
    path, manifest = render_visual(ROW, tmp_path / "out", brand_voice=brand)
    assert manifest["character"] == {
        "used": True,
        "requested": True,
        "reference": reference,
        "reason": "",
    }
    ok, evidence = verify_visual(path, manifest)
    assert ok, evidence
    with Image.open(path) as img:
        rgb = img.convert("RGB")
        width, height = rgb.size
        pixels = rgb.load()
        red = [
            (x, y)
            for y in range(height)
            for x in range(width)
            if pixels[x, y] == (255, 0, 0)
        ]
        assert red, "no pixels from the reference image were composited"
        xs = [p[0] for p in red]
        ys = [p[1] for p in red]
        measured = max(max(xs) - min(xs), max(ys) - min(ys)) + 1
        # Documented badge size: about 22% of the poster width.
        assert abs(measured - round(width * 0.22)) <= 1
        centre = ((min(xs) + max(xs)) // 2, (min(ys) + max(ys)) // 2)
        assert rgb.getpixel(centre) == (255, 0, 0)  # the reference itself, unrecoloured
        assert centre[0] > width // 2 and centre[1] > height // 2  # bottom-right
        # The accent ring hugs the badge: the pixel directly above
        # the badge's topmost reference pixel is ring-coloured.
        assert rgb.getpixel((centre[0], min(ys) - 1)) == ASSETS["accent_rgb"]


def test_designer_records_requested_but_unused_when_reference_missing(tmp_path):
    brand = {"character_image": "assets/does-not-exist.png"}
    path, manifest = render_visual(ROW, tmp_path / "out", brand_voice=brand)
    assert manifest["character"] == {
        "used": False,
        "requested": True,
        "reference": "assets/does-not-exist.png",
        "reason": "reference missing",
    }
    ok, evidence = verify_visual(path, manifest)
    assert ok, evidence


def test_designer_treats_reference_outside_repo_as_missing(tmp_path):
    outside = _tiny_reference(tmp_path / "outside.png")
    # Absolute path outside the repo root: refused by containment,
    # even though the file exists.
    _, manifest = render_visual(
        ROW, tmp_path / "out", brand_voice={"character_image": str(outside)}
    )
    assert manifest["character"]["used"] is False
    assert manifest["character"]["reason"] == "reference missing"
    # A relative value that traverses out of the repo is refused too.
    traversal = os.path.relpath(outside, REPO_ROOT)
    assert traversal.startswith("..")
    _, manifest = render_visual(
        ROW, tmp_path / "out2", brand_voice={"character_image": traversal}
    )
    assert manifest["character"]["used"] is False
    assert manifest["character"]["reason"] == "reference missing"


def test_designer_records_unreadable_reference(tmp_path, repo_file):
    cases = {
        "truncated.png": _png_bytes()[:40],  # valid header, cut body
        "not-an-image.png": b"this is not an image at all",
    }
    for name, data in cases.items():
        bad = repo_file(name, data)
        brand = {"character_image": str(bad)}
        path, manifest = render_visual(ROW, tmp_path / "out", brand_voice=brand)
        assert manifest["character"] == {
            "used": False,
            "requested": True,
            "reference": str(bad),
            "reason": "reference unreadable",
        }
        ok, evidence = verify_visual(path, manifest)
        assert ok, evidence
        result = check_character(ROW, manifest, brand)
        assert not result.passed
        assert "reference unreadable" in result.results[0].evidence


def test_produce_visual_fails_cleanly_on_unreadable_reference(tmp_path, repo_file):
    bad = repo_file("corrupt.png", _png_bytes()[:40])
    store = Store(tmp_path / "data")
    store.set_brand_value("character_image", str(bad))
    row = store.add_plan_row(dict(ROW, status="drafted"))
    with pytest.raises(RuntimeError) as excinfo:
        produce_visual(store, row)
    assert "character check failed" in str(excinfo.value)
    assert "reference unreadable" in str(excinfo.value)


def test_designer_no_character_when_not_requested(tmp_path):
    row = {k: v for k, v in ROW.items() if k != "character"}
    _, manifest = render_visual(row, tmp_path / "out", brand_voice={})
    assert manifest["character"] == {
        "used": False,
        "requested": False,
        "reference": "",
        "reason": "",
    }


def test_non_string_character_flag_does_not_crash(tmp_path):
    row = dict(ROW, character=True)
    _, manifest = render_visual(
        row,
        tmp_path / "out",
        brand_voice={"character_image": "assets/paco-character.png"},
    )
    assert manifest["character"] == {
        "used": False,
        "requested": False,
        "reference": "",
        "reason": "",
    }
    result = check_character(
        row, manifest, {"character_image": "assets/paco-character.png"}
    )
    assert result.passed


def test_check_character_not_required_passes():
    result = check_character({"topic": "plain post"}, {}, {"character_image": "a.png"})
    assert result.passed
    assert "not required" in result.results[0].evidence


def test_check_character_passes_on_matching_reference():
    manifest = {"character": {"used": True, "reference": "assets/paco-character.png"}}
    result = check_character(ROW, manifest, {"character_image": "assets/paco-character.png"})
    assert result.passed


def test_check_character_fails_when_requested_but_unused():
    manifest = {"character": {"used": False, "requested": True, "reason": "reference missing"}}
    result = check_character(ROW, manifest, {"character_image": "assets/paco-character.png"})
    assert not result.passed
    assert "reference missing" in result.results[0].evidence


def test_check_character_fails_on_reference_mismatch():
    manifest = {"character": {"used": True, "reference": "assets/somebody-else.png"}}
    result = check_character(ROW, manifest, {"character_image": "assets/paco-character.png"})
    assert not result.passed
    assert "mismatch" in result.results[0].evidence
    assert "somebody-else.png" in result.results[0].evidence


def test_produce_visual_with_existing_reference_succeeds(tmp_path, repo_reference):
    store = Store(tmp_path / "data")
    store.set_brand_value("character_image", str(repo_reference))
    row = store.add_plan_row(dict(ROW, status="drafted"))
    updated = produce_visual(store, row)
    assert updated["visual"]
    assert (store.data_dir / updated["visual"]).exists()


def test_produce_visual_fails_on_reference_mismatch(
    tmp_path, monkeypatch, repo_reference, repo_file
):
    other = repo_file("other.png", _png_bytes(colour=(0, 0, 255)))
    store = Store(tmp_path / "data")
    store.set_brand_value("character_image", str(repo_reference))
    row = store.add_plan_row(dict(ROW, status="drafted"))
    real_render = designer.render_visual

    def swapped_render(row_, out_dir, brand_voice=None):
        # Fault injection: the Designer composited a substituted
        # reference instead of the brand-assets layer's own file.
        return real_render(row_, out_dir, brand_voice={"character_image": str(other)})

    monkeypatch.setattr(designer, "render_visual", swapped_render)
    with pytest.raises(RuntimeError) as excinfo:
        produce_visual(store, row)
    assert "character check failed" in str(excinfo.value)
    assert "mismatch" in str(excinfo.value)


def test_pipeline_flags_character_row_when_reference_missing(tmp_path):
    store = Store(tmp_path)
    update_brand_voice(store, "character_image", "assets/missing.png")
    row = store.add_plan_row(
        {
            "platform": "facebook",
            "topic": "Launch announcement",
            "status": "planned",
            "character": "yes",
        }
    )
    updated = draft_and_check(store, MockClient(), row)
    assert updated["status"] == "checked"  # flagged, never awaiting approval
    assert "[VISUAL] FAIL" in updated["check_status"]
    assert "character" in updated["check_status"]
