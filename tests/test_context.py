"""Context architecture (M19 formalisation): one store, three layers.

- Every store write is appended to writes.log (the audit trail).
- Private layer: the Strategist's trend notes and the Analyst's
  performance history live as per-role files in the data dir.
- Long-term loop: the Analyst's history feeds the next plan — the
  latest summary reaches generate_plan as context.
"""
import json

from pageops.context import (
    append_analyst_history,
    latest_analyst_summary,
    load_trend_notes,
    save_trend_notes,
)
from pageops.model_client import MockClient
from pageops.pipeline import fetch_trends, generate_week
from pageops.report import build_report
from pageops.store import Store


def test_store_writes_are_logged(tmp_path):
    store = Store(tmp_path)
    row = store.add_plan_row({"topic": "Logged", "status": "planned"})
    store.update_row("plan", row["id"], {"status": "drafted"})
    log = (tmp_path / "writes.log").read_text(encoding="utf-8")
    assert "dataset=plan" in log
    assert f"id={row['id']}" in log
    assert "status" in log


def test_trend_notes_round_trip(tmp_path):
    store = Store(tmp_path)
    trends = [{"title": "Agents in marketing", "source": "https://example.com"}]
    save_trend_notes(store, trends)
    assert load_trend_notes(store) == trends


def test_fetch_trends_snapshots_notes_when_store_given(tmp_path):
    store = Store(tmp_path)
    fake = lambda feeds_file=None: [{"title": "T", "link": "https://x"}]  # noqa: E731
    items = fetch_trends(store=store, fetcher=fake)
    assert items and load_trend_notes(store)


def test_analyst_history_and_summary(tmp_path):
    store = Store(tmp_path)
    assert latest_analyst_summary(store) == ""
    append_analyst_history(
        store, {"totals": {"reach": 170, "engagement": 13, "clicks": 1, "posts": 3}}
    )
    summary = latest_analyst_summary(store)
    assert "170" in summary and "13" in summary
    lines = (tmp_path / "notes" / "analyst_history.jsonl").read_text().strip().split("\n")
    assert json.loads(lines[0])["reach"] == 170


def test_report_week_appends_history(tmp_path):
    store = Store(tmp_path)
    store.append_row(
        "metrics",
        {"date": "2026-08-20", "platform": "facebook", "post_id": "p1",
         "reach": "36", "engagement": "5", "clicks": "0", "notes": ""},
    )
    from pageops.pipeline import report_week

    report_week(store, client=MockClient())
    assert latest_analyst_summary(store) != ""


class SpyClient(MockClient):
    def __init__(self):
        self.context = None

    def generate_plan(self, brief, brand_voice, context="", trends=None):
        self.context = context
        return super().generate_plan(brief, brand_voice, context=context, trends=trends)


def test_generate_week_receives_last_report_as_context(tmp_path):
    store = Store(tmp_path)
    append_analyst_history(
        store, {"totals": {"reach": 999, "engagement": 42, "clicks": 7, "posts": 5}}
    )
    spy = SpyClient()
    generate_week(store, spy, "Next week's brief")
    assert spy.context is not None and "999" in spy.context
