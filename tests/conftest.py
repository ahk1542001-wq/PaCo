import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


@pytest.fixture(autouse=True)
def _stub_video_production(request, monkeypatch):
    """Keep real FFmpeg encodes inside tests/test_video.py only.

    Every full-week pipeline test would otherwise synchronously
    encode two 1080x1920 videos, which ballooned the suite past
    100s. Outside test_video.py, produce_video is stubbed with a
    double that honours the real call contract exactly: it writes
    the mp4 file under the store's visuals/, records the relative
    path on the row's video field via store.update_row, and returns
    (path, manifest) with qc and scenes keys the pipeline reads.
    Tests that need the knob set PAGEOPS_VIDEO_SECONDS_PER_SCENE
    explicitly; there is no global mutation here.
    """
    if Path(request.module.__file__).name == "test_video.py":
        return
    import pageops.pipeline as pipeline_module
    import pageops.video as video_module

    def fake_produce_video(store, row):
        out_dir = store.data_dir / "visuals"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"video-{row.get('id', 'row')}.mp4"
        out_path.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64)
        relative = out_path.relative_to(store.data_dir)
        store.update_row("plan", row["id"], {"video": str(relative)})
        manifest = {
            "scenes": [
                {"index": 1, "kind": "hook", "text": row.get("topic", "")}
            ],
            "frames": [],
            "qc": {
                "duration": 1.0,
                "width": 1080,
                "height": 1920,
                "has_video": True,
                "valid": True,
            },
            "path": str(out_path),
            "seconds_per_scene": 0.0,
            "character": {
                "used": False,
                "requested": False,
                "reference": "",
                "reason": "",
            },
        }
        return out_path, manifest

    monkeypatch.setattr(video_module, "produce_video", fake_produce_video)
    monkeypatch.setattr(
        pipeline_module, "produce_video", fake_produce_video, raising=False
    )
