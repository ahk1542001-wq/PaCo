"""Video production: storyboard, frames, FFmpeg assembly, QC.

Follows the production pattern script, storyboard, frames,
assembly, QA. Assembly tests use the real FFmpeg and skip cleanly
when ffmpeg or ffprobe is absent.
"""
import shutil
import subprocess
from pathlib import Path

import pytest

from pageops.model_client import MockClient
from pageops.pipeline import draft_and_check, process_week
from pageops.store import Store
from pageops.video import (
    assemble_video,
    produce_video,
    qc_video,
    render_scene_frame,
    seconds_per_scene,
    storyboard_for,
)

HAS_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
needs_ffmpeg = pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg/ffprobe not available")

ROW = {
    "platform": "facebook",
    "topic": "How FYF AI answers page messages while the owner is busy",
    "format": "Short video",
    "draft": (
        "First point here. Second point follows. Third point arrives. "
        "Message us to get started. #FYFAI"
    ),
}


def test_storyboard_shape_and_cap():
    scenes = storyboard_for(ROW, {})
    assert len(scenes) <= 6
    assert [s["kind"] for s in scenes] == [
        "hook", "pain", "reveal", "demo", "proof", "cta",
    ]
    assert scenes[0]["text"] == ROW["topic"]
    assert "Message us" in scenes[-1]["text"]  # the draft's own CTA sentence
    assert [s["index"] for s in scenes] == [1, 2, 3, 4, 5, 6]


def test_storyboard_six_beats_with_four_points():
    row = dict(
        ROW,
        draft=(
            "Pain line one. Reveal line two. Demo line three. "
            "Proof line four. Message us to get started."
        ),
    )
    scenes = storyboard_for(row, {})
    assert [s["kind"] for s in scenes] == [
        "hook", "pain", "reveal", "demo", "proof", "cta",
    ]
    assert scenes[1]["text"] == "Pain line one."
    assert scenes[2]["text"] == "Reveal line two."
    assert scenes[3]["text"] == "Demo line three."
    assert scenes[4]["text"] == "Proof line four."
    assert scenes[5]["text"] == "Message us to get started."


def test_storyboard_single_point_yields_hook_pain_cta():
    row = dict(ROW, draft="Only one point here. Message us to get started.")
    scenes = storyboard_for(row, {})
    assert [s["kind"] for s in scenes] == ["hook", "pain", "cta"]
    assert scenes[1]["text"] == "Only one point here."


def test_storyboard_is_deterministic():
    assert storyboard_for(ROW, {}) == storyboard_for(ROW, {})


def test_storyboard_without_draft_still_has_hook_and_end_card():
    scenes = storyboard_for({"topic": "Only a topic", "format": "Short video"}, {})
    assert [s["kind"] for s in scenes] == ["hook", "cta"]


def test_seconds_per_scene_env_knob(monkeypatch):
    monkeypatch.setenv("PAGEOPS_VIDEO_SECONDS_PER_SCENE", "1.5")
    assert seconds_per_scene() == 1.5
    monkeypatch.setenv("PAGEOPS_VIDEO_SECONDS_PER_SCENE", "not-a-number")
    assert seconds_per_scene() == 2.0
    monkeypatch.delenv("PAGEOPS_VIDEO_SECONDS_PER_SCENE")
    assert seconds_per_scene() == 2.0


def test_seconds_per_scene_rejects_non_finite_and_clamps(monkeypatch):
    for bad in ("inf", "-inf", "nan"):
        monkeypatch.setenv("PAGEOPS_VIDEO_SECONDS_PER_SCENE", bad)
        assert seconds_per_scene() == 2.0
    monkeypatch.setenv("PAGEOPS_VIDEO_SECONDS_PER_SCENE", "100")
    assert seconds_per_scene() == 30.0
    monkeypatch.setenv("PAGEOPS_VIDEO_SECONDS_PER_SCENE", "0")
    assert seconds_per_scene() == 0.2


def test_storyboard_caps_points_for_long_drafts():
    draft = ". ".join(f"Point {i}" for i in range(1, 10))
    draft += ". Message us to get started."
    scenes = storyboard_for(dict(ROW, draft=draft), {})
    assert len(scenes) == 6
    assert [s["kind"] for s in scenes] == [
        "hook", "pain", "reveal", "demo", "proof", "cta",
    ]
    assert [s["text"] for s in scenes[1:5]] == [
        "Point 1.", "Point 2.", "Point 3.", "Point 4.",
    ]


def test_qc_raises_clear_error_when_ffprobe_missing(monkeypatch):
    import pageops.video as video_module

    real_which = shutil.which
    monkeypatch.setattr(
        video_module.shutil,
        "which",
        lambda name: None if name == "ffprobe" else real_which(name),
    )
    with pytest.raises(RuntimeError, match="ffprobe not available"):
        qc_video("anything.mp4")


@needs_ffmpeg
def test_assemble_and_qc_roundtrip(tmp_path):
    scenes = storyboard_for(ROW, {})
    frames = []
    for scene in scenes:
        frame, _ = render_scene_frame(scene, dict(ROW, id="7"), tmp_path)
        frames.append(frame)
    out = assemble_video(frames, tmp_path / "video-7.mp4", 0.4)
    assert out.exists()
    qc = qc_video(out)
    assert qc["has_video"] is True
    assert (qc["width"], qc["height"]) == (1080, 1920)
    # One segment per scene at 0.4s, container slack allowed.
    assert len(scenes) * 0.4 - 0.6 < qc["duration"] < len(scenes) * 0.4 + 0.9
    assert qc["valid"] is True


def test_qc_rejects_missing_and_non_video_files(tmp_path):
    if shutil.which("ffprobe") is None:
        # Without ffprobe the QC step cannot run at all: it must say so
        # honestly (a clear RuntimeError) instead of faking a result.
        with pytest.raises(RuntimeError, match="ffprobe not available"):
            qc_video(tmp_path / "nope.mp4")
        return
    missing = qc_video(tmp_path / "nope.mp4")
    assert missing["valid"] is False
    assert missing["has_video"] is False
    not_video = tmp_path / "still.png"
    from PIL import Image

    Image.new("RGB", (1080, 1920)).save(not_video)
    qc = qc_video(not_video)
    assert qc["valid"] is False


@needs_ffmpeg
def test_produce_video_stores_path_and_manifest(tmp_path, monkeypatch):
    monkeypatch.setenv("PAGEOPS_VIDEO_SECONDS_PER_SCENE", "0.2")
    store = Store(tmp_path / "data")
    row = store.add_plan_row(dict(ROW, status="drafted"))
    path, manifest = produce_video(store, row)
    assert path.exists()
    assert manifest["qc"]["valid"] is True
    assert [s["kind"] for s in manifest["scenes"]] == [
        "hook", "pain", "reveal", "demo", "proof", "cta",
    ]
    assert manifest["plate"]["used"] is False  # no image client supplied
    assert all(Path(f).exists() for f in manifest["frames"])
    reread = [r for r in store.read_dataset("plan") if r["id"] == row["id"]][0]
    assert reread["video"] == "visuals/video-" + row["id"] + ".mp4"
    assert (store.data_dir / reread["video"]).exists()


def test_produce_video_refuses_row_without_draft(tmp_path):
    store = Store(tmp_path / "data")
    row = store.add_plan_row(
        {"platform": "facebook", "topic": "No draft", "format": "Short video", "status": "planned"}
    )
    with pytest.raises(ValueError, match="draft"):
        produce_video(store, row)


@needs_ffmpeg
def test_pipeline_short_video_rows_gain_video(tmp_path, monkeypatch):
    monkeypatch.setenv("PAGEOPS_VIDEO_SECONDS_PER_SCENE", "0.2")
    store = Store(tmp_path)
    rows = process_week(store, MockClient(), "Promote the chatbot offer")
    video_rows = [r for r in rows if r["format"] == "Short video"]
    assert len(video_rows) == 2
    for row in video_rows:
        assert row["status"] == "awaiting_approval"
        assert row["video"].endswith(".mp4")
        assert (tmp_path / row["video"]).exists()
        assert "[VIDEO] PASS" in row["check_status"]
        assert row["visual"]  # the poster remains the row's visual
    for row in rows:
        if row["format"] != "Short video":
            assert not row["video"]


@needs_ffmpeg
def test_pipeline_flags_row_when_video_production_fails(tmp_path, monkeypatch):
    import pageops.video as video_module

    def boom(store, row, image_client=None):
        raise RuntimeError("ffmpeg exploded")

    monkeypatch.setattr(video_module, "produce_video", boom)
    store = Store(tmp_path)
    row = store.add_plan_row(
        {
            "platform": "facebook",
            "topic": "A short video post",
            "format": "Short video",
            "status": "planned",
        }
    )
    updated = draft_and_check(store, MockClient(), row)
    assert updated["status"] == "checked"  # flagged, never awaiting approval
    assert "[VISUAL] FAIL" in updated["check_status"]
    assert "video production failed" in updated["check_status"]


def _corrupt_frame_renderer(scene, row, out_dir, brand_voice=None, plate_path=None):
    """A scene renderer whose frames are not images at all.

    FFmpeg exits nonzero on these mid-assembly, which is exactly
    the failure the pipeline must turn into a flagged row.
    """
    path = Path(out_dir) / f"video-{row.get('id', 'row')}-frame-{scene.get('index', 0)}.png"
    path.write_bytes(b"this is not a png")
    character = {"used": False, "requested": False, "reference": "", "reason": ""}
    return path, character


@needs_ffmpeg
def test_pipeline_flags_row_on_ffmpeg_nonzero_exit(tmp_path, monkeypatch):
    import pageops.video as video_module

    monkeypatch.setenv("PAGEOPS_VIDEO_SECONDS_PER_SCENE", "0.4")
    monkeypatch.setattr(video_module, "render_scene_frame", _corrupt_frame_renderer)
    store = Store(tmp_path)
    row = store.add_plan_row(
        {
            "platform": "facebook",
            "topic": "A short video post",
            "format": "Short video",
            "status": "planned",
        }
    )
    updated = draft_and_check(store, MockClient(), row)
    assert updated["status"] == "checked"  # flagged, never awaiting approval
    assert "[VISUAL] FAIL" in updated["check_status"]
    assert "video production failed" in updated["check_status"]
    assert "video assembly failed" in updated["check_status"]


@needs_ffmpeg
def test_pipeline_flags_row_on_video_timeout(tmp_path, monkeypatch):
    import pageops.video as video_module

    def timed_out(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="ffmpeg", timeout=600)

    monkeypatch.setattr(video_module.subprocess, "run", timed_out)
    store = Store(tmp_path)
    row = store.add_plan_row(
        {
            "platform": "facebook",
            "topic": "A short video post",
            "format": "Short video",
            "status": "planned",
        }
    )
    updated = draft_and_check(store, MockClient(), row)
    assert updated["status"] == "checked"  # flagged, never a crashed run
    assert "[VISUAL] FAIL" in updated["check_status"]
    assert "video production failed" in updated["check_status"]
    assert "video assembly failed" in updated["check_status"]


@needs_ffmpeg
def test_failed_rerun_preserves_existing_good_video(tmp_path, monkeypatch):
    import pageops.video as video_module

    monkeypatch.setenv("PAGEOPS_VIDEO_SECONDS_PER_SCENE", "0.2")
    store = Store(tmp_path / "data")
    row = store.add_plan_row(dict(ROW, status="drafted"))
    path, _manifest = produce_video(store, row)
    good_bytes = path.read_bytes()
    assert good_bytes

    monkeypatch.setattr(video_module, "render_scene_frame", _corrupt_frame_renderer)
    with pytest.raises(RuntimeError, match="video assembly failed"):
        produce_video(store, row)
    assert path.read_bytes() == good_bytes  # byte-identical afterwards
    tmp_leftover = path.with_name(path.name.replace(".mp4", ".tmp.mp4"))
    assert not tmp_leftover.exists()


@needs_ffmpeg
def test_produce_video_prunes_stale_frames(tmp_path, monkeypatch):
    monkeypatch.setenv("PAGEOPS_VIDEO_SECONDS_PER_SCENE", "0.2")
    store = Store(tmp_path / "data")
    row = store.add_plan_row(dict(ROW, status="drafted"))
    visuals = store.data_dir / "visuals"
    visuals.mkdir(parents=True, exist_ok=True)
    stale = visuals / f"video-{row['id']}-frame-99.png"
    stale.write_bytes(b"old frame from a longer storyboard")
    produce_video(store, row)
    assert not stale.exists()


PLATE_ROW = dict(
    ROW,
    draft=(
        "Pain point one. Reveal point two. Demo point three. "
        "Proof point four. Message us to get started."
    ),
)


def test_reveal_scene_uses_primary_background(tmp_path):
    from PIL import Image

    from pageops.designer import ASSETS

    scenes = storyboard_for(PLATE_ROW, {})
    reveal = next(s for s in scenes if s["kind"] == "reveal")
    hook = scenes[0]
    row = dict(PLATE_ROW, id="9")
    reveal_frame, _ = render_scene_frame(reveal, row, tmp_path)
    hook_frame, _ = render_scene_frame(hook, row, tmp_path)
    # Left-centre: clear of the top band, the text block and the badge.
    assert Image.open(reveal_frame).getpixel((30, 1000)) == ASSETS["primary_rgb"]
    assert Image.open(hook_frame).getpixel((30, 1000)) == ASSETS["background_rgb"]


@needs_ffmpeg
def test_mock_video_draft_produces_six_beats(tmp_path, monkeypatch):
    monkeypatch.setenv("PAGEOPS_VIDEO_SECONDS_PER_SCENE", "0.2")
    store = Store(tmp_path / "data")
    item = {
        "platform": "facebook",
        "topic": "How FYF AI answers page messages while the owner is busy",
        "format": "Short video",
    }
    draft = MockClient().generate_draft(item, store.get_brand_voice())
    row = store.add_plan_row(dict(item, draft=draft["text"], status="drafted"))
    _path, manifest = produce_video(store, row)
    assert [s["kind"] for s in manifest["scenes"]] == [
        "hook", "pain", "reveal", "demo", "proof", "cta",
    ]
    assert manifest["scenes"][1]["text"].startswith("Customers message your page")
    assert "Message us" in manifest["scenes"][-1]["text"]
    assert manifest["qc"]["valid"] is True


def _png_bytes(rgb=(200, 40, 40), size=(72, 128)):
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", size, rgb).save(buf, format="PNG")
    return buf.getvalue()


class _FakeImageClient:
    """Stands in for MetaImageClient: records prompts, returns bytes."""

    def __init__(self, raw):
        self.raw = raw
        self.prompts = []

    def generate_image_bytes(self, prompt):
        self.prompts.append(prompt)
        return self.raw


class _FailingImageClient:
    def generate_image_bytes(self, prompt):
        raise RuntimeError("image backend down")


@needs_ffmpeg
def test_plate_used_for_reveal_scene(tmp_path, monkeypatch):
    from PIL import Image

    from pageops.designer import ASSETS

    monkeypatch.setenv("PAGEOPS_VIDEO_SECONDS_PER_SCENE", "0.2")
    store = Store(tmp_path / "data")
    row = store.add_plan_row(dict(PLATE_ROW, status="drafted"))
    fake = _FakeImageClient(_png_bytes())
    _path, manifest = produce_video(store, row, image_client=fake)
    assert manifest["plate"] == {"used": True, "scene": "reveal", "reason": ""}
    assert manifest["qc"]["valid"] is True
    assert fake.prompts and "No text" in fake.prompts[0]
    plate_file = store.data_dir / "visuals" / f"plate-{row['id']}.png"
    assert plate_file.exists()
    # The reveal frame renders over the plate: its background is
    # the plate blended toward primary, not the flat template fill.
    reveal_index = next(
        i for i, s in enumerate(manifest["scenes"]) if s["kind"] == "reveal"
    )
    pixel = Image.open(manifest["frames"][reveal_index]).getpixel((30, 1000))
    assert pixel != ASSETS["primary_rgb"]
    assert pixel[0] > 100  # the red plate shows through the blend


@needs_ffmpeg
def test_plate_failure_falls_back_to_template(tmp_path, monkeypatch):
    from PIL import Image

    from pageops.designer import ASSETS

    monkeypatch.setenv("PAGEOPS_VIDEO_SECONDS_PER_SCENE", "0.2")
    store = Store(tmp_path / "data")
    row = store.add_plan_row(dict(PLATE_ROW, status="drafted"))
    _path, manifest = produce_video(
        store, row, image_client=_FailingImageClient()
    )
    assert manifest["qc"]["valid"] is True  # the video still produces
    assert manifest["plate"]["used"] is False
    assert "image backend down" in manifest["plate"]["reason"]
    reveal_index = next(
        i for i, s in enumerate(manifest["scenes"]) if s["kind"] == "reveal"
    )
    pixel = Image.open(manifest["frames"][reveal_index]).getpixel((30, 1000))
    assert pixel == ASSETS["primary_rgb"]  # template render, no plate


def test_meta_draft_instruction_directs_video_beats(monkeypatch):
    from pageops.model_client import MetaModelClient

    client = MetaModelClient(api_key="test-key")
    captured = {}

    def fake_structured(instruction, payload, model):
        captured["instruction"] = instruction
        return {"platform": "facebook", "text": "x", "hashtags": []}

    monkeypatch.setattr(client, "_structured", fake_structured)
    client.generate_draft(
        {"topic": "T", "platform": "facebook", "format": "Short video"}, {}
    )
    instruction = captured["instruction"]
    for beat in ("pain point", "product reveal", "demo", "social proof", "call-to-action"):
        assert beat in instruction
    assert "never invent results" in instruction

    client.generate_draft({"topic": "T", "platform": "facebook", "format": "Poster"}, {})
    assert captured["instruction"].startswith("Write one post caption")


def test_meta_image_client_posts_and_decodes(monkeypatch, tmp_path):
    import base64
    import json as json_module

    import httpx

    from pageops.model_client import MetaImageClient

    captured = {}
    raw = _png_bytes((10, 20, 30), size=(8, 8))

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "data": [{"b64_json": base64.b64encode(raw).decode()}],
                "usage": {},
            }

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        return FakeResponse()

    monkeypatch.setattr(httpx, "post", fake_post)
    client = MetaImageClient(api_key="test-key", usage_log=tmp_path / "usage.jsonl")
    assert client.generate_image_bytes("a shop scene") == raw
    assert captured["url"] == "https://api.meta.ai/v1/images/generations"
    assert captured["json"]["model"] == "muse-image-1.0"
    assert captured["json"]["prompt"] == "a shop scene"
    assert json_module.dumps(captured["json"])  # payload stays JSON-shaped


def test_meta_image_client_raises_clear_error_on_failure(monkeypatch):
    import httpx

    from pageops.model_client import MetaImageClient

    def boom(url, headers=None, json=None, timeout=None):
        raise httpx.ConnectError("no route", request=None)

    monkeypatch.setattr(httpx, "post", boom)
    client = MetaImageClient(api_key="test-key")
    with pytest.raises(RuntimeError, match="Muse Image generation failed"):
        client.generate_image_bytes("a shop scene")


def test_get_image_client_none_in_mock_mode(monkeypatch):
    from pageops.model_client import get_image_client

    monkeypatch.setenv("MODEL_MODE", "mock")
    assert get_image_client() is None
