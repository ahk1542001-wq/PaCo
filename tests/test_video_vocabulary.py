"""The planner's format vocabulary is not constrained: a row whose
format is plain "video" (not "Short video") is still a video row.

Regression test for the 2026-11-03 Concept acceptance run, where
Muse Wonder labelled two rows "video" and they silently received
poster visuals only, because every video trigger matched the exact
phrase "short video". The conftest stub stands in for produce_video
outside test_video.py.
"""
from pageops.model_client import MockClient
from pageops.pipeline import draft_and_check
from pageops.store import Store


def test_plain_video_format_produces_a_video(tmp_path):
    store = Store(tmp_path / "data")
    row = store.add_plan_row({
        "platform": "facebook",
        "topic": "Watch the chatbot answer a price question",
        "angle": "Show the reply arriving in seconds",
        "format": "video",
        "status": "planned",
    })
    draft_and_check(store, MockClient(), row)
    stored = store.read_dataset("plan")[0]
    assert stored["video"]
    assert "[VIDEO] PASS" in stored["check_status"]
