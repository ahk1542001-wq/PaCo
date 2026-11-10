"""Tests for pipeline.process_single: the owner-asked single post.

The owner's rule (2026-11-10): produce only what the owner asks for,
never a batch. process_single must create exactly one plan row from
the ask, must never call the week planner, and must land that row at
the same approval gate as a week item.
"""

from __future__ import annotations

from pageops.model_client import MockClient
from pageops.pipeline import process_single
from pageops.store import Store

ASK = "Launch post for the new Gemini Pro offer, pain point first"


class NoWeekClient(MockClient):
    """A client whose week planner must never be called."""

    def generate_plan(self, *args, **kwargs):  # pragma: no cover
        raise AssertionError("process_single must not plan a week")


def test_single_post_creates_exactly_one_row_at_the_gate(tmp_path):
    store = Store(tmp_path / "data")
    result = process_single(store, NoWeekClient(), ASK, topic="Gemini Pro launch")

    rows = store.read_dataset("plan")
    # intake_brief also stores the brief itself as a brief row (the
    # convention process_week follows); exactly one POST row may exist.
    singles = [
        r
        for r in rows
        if r.get("brief") == ASK and r.get("status") != "brief_received"
    ]
    assert len(singles) == 1
    assert result["id"] == singles[0]["id"]
    assert result["status"] in ("awaiting_approval", "checked")
    assert singles[0]["topic"] == "Gemini Pro launch"


def test_single_post_defaults_topic_to_the_ask(tmp_path):
    store = Store(tmp_path / "data")
    result = process_single(store, NoWeekClient(), ASK)

    assert result["topic"] == ASK
