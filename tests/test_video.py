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
    assert len(scenes) <= 4
    assert [s["kind"] for s in scenes] == ["hook", "point", "point", "cta"]
    assert scenes[0]["text"] == ROW["topic"]
    assert "Message us" in scenes[-1]["text"]  # the draft's own CTA sentence
    assert [s["index"] for s in scenes] == [1, 2, 3, 4]


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
    assert len(scenes) == 4
    assert [s["kind"] for s in scenes] == ["hook", "point", "point", "cta"]


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
    assert 1.0 < qc["duration"] < 2.5  # 4 scenes at 0.4s, container slack allowed
    assert qc["valid"] is True


def test_qc_rejects_missing_and_non_video_files(tmp_path):
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
    assert len(manifest["scenes"]) <= 4
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

    def boom(store, row):
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


def _corrupt_frame_renderer(scene, row, out_dir, brand_voice=None):
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
