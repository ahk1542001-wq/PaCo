"""Research backend adapter: Agent-Reach first, RSS fallback, and
the provenance is always recorded. All CLI calls hit a fake binary;
no network, no real agent-reach, in any test."""

import json
import stat

import pytest

from pageops import research
from pageops.pipeline import fetch_trends
from pageops.store import Store

SEARCH_PAYLOAD = {
    "ok": True,
    "channel": "web",
    "action": "search",
    "backend": "exa",
    "items": [
        {
            "title": "Chatbots are the new front desk",
            "url": "https://example.com/chatbot-trends",
            "snippet": "Small pages answer faster with bots.",
        },
        {
            "title": "Short video still rules",
            "url": "https://example.com/video-trends",
            "text": "Reels and Shorts dominate discovery.",
        },
    ],
}


def _fake_cli(tmp_path, body: str, exit_code: int = 0):
    script = tmp_path / "agent-reach"
    script.write_text(f"#!/bin/sh\nprintf '%s' '{body}'\nexit {exit_code}\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return str(script)


def _ok_cli(tmp_path):
    return _fake_cli(tmp_path, json.dumps(SEARCH_PAYLOAD).replace("'", ""))


def test_agent_reach_items_map_to_the_rss_shape(tmp_path, monkeypatch):
    monkeypatch.setenv("PAGEOPS_AGENT_REACH_BIN", _ok_cli(tmp_path))
    bundle = research.fetch_research(queries=("anything",))
    assert bundle["backend"] == "agent-reach"
    assert bundle["items"][0] == {
        "source": "agent-reach/exa",
        "title": "Chatbots are the new front desk",
        "link": "https://example.com/chatbot-trends",
        "summary": "Small pages answer faster with bots.",
    }
    assert bundle["items"][1]["summary"] == "Reels and Shorts dominate discovery."


def test_missing_binary_falls_back_to_rss(tmp_path, monkeypatch):
    monkeypatch.setenv("PAGEOPS_AGENT_REACH_BIN", str(tmp_path / "nope"))
    monkeypatch.setattr(
        "pageops.rss.fetch_feeds",
        lambda feeds_file=None: [{"source": "Feed", "title": "T", "link": "L", "summary": "S"}],
    )
    bundle = research.fetch_research()
    assert bundle["backend"] == "rss"
    assert "not installed" in bundle["detail"]
    assert bundle["items"][0]["title"] == "T"


def test_failing_search_falls_back_to_rss(tmp_path, monkeypatch):
    payload = {"ok": False, "error": {"code": "UPSTREAM_BROKEN", "message": "paused"}}
    monkeypatch.setenv("PAGEOPS_AGENT_REACH_BIN", _fake_cli(tmp_path, json.dumps(payload)))
    monkeypatch.setattr("pageops.rss.fetch_feeds", lambda feeds_file=None: [])
    bundle = research.fetch_research(queries=("q",))
    assert bundle["backend"] == "rss"
    assert "UPSTREAM_BROKEN" in bundle["detail"]


def test_trend_notes_record_the_backend(tmp_path, monkeypatch):
    monkeypatch.setenv("PAGEOPS_AGENT_REACH_BIN", _ok_cli(tmp_path))
    store = Store(tmp_path)
    items = fetch_trends(store=store, fetcher=research.fetch_research)
    assert items and items[0]["link"].startswith("https://example.com/")
    payload = json.loads((tmp_path / "notes" / "strategist_trends.json").read_text())
    assert payload["source"]["backend"] == "agent-reach"
    assert payload["items"] == items


def test_trend_notes_record_a_fallback_honestly(tmp_path, monkeypatch):
    monkeypatch.setenv("PAGEOPS_AGENT_REACH_BIN", str(tmp_path / "missing"))
    monkeypatch.setattr(
        "pageops.rss.fetch_feeds",
        lambda feeds_file=None: [{"source": "F", "title": "T", "link": "L", "summary": "S"}],
    )
    store = Store(tmp_path)
    fetch_trends(store=store, fetcher=research.fetch_research)
    payload = json.loads((tmp_path / "notes" / "strategist_trends.json").read_text())
    assert payload["source"]["backend"] == "rss"
    assert "unavailable" in payload["source"]["detail"]



def test_nonzero_exit_still_reports_the_envelope_reason(tmp_path, monkeypatch):
    payload = {"ok": False, "error": {"code": "UPSTREAM_BROKEN", "message": "exa paused"}}
    monkeypatch.setenv(
        "PAGEOPS_AGENT_REACH_BIN", _fake_cli(tmp_path, json.dumps(payload), exit_code=1)
    )
    monkeypatch.setattr("pageops.rss.fetch_feeds", lambda feeds_file=None: [])
    bundle = research.fetch_research(queries=("q",))
    assert bundle["backend"] == "rss"
    assert "UPSTREAM_BROKEN" in bundle["detail"]
    assert "exited 1" not in bundle["detail"]
