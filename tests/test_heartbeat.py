"""Tests for the heartbeat schedule and owner notifications.

The schedule is opt-in brand data; the due rule compares the most
recent scheduled moment with the last recorded run; a notification
for the same waiting fact is never duplicated while unread.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from pageops.dashboard import render_board
from pageops.heartbeat import (
    heartbeat_config,
    heartbeat_due,
    mark_notifications_read,
    notify,
    notify_gate_status,
    record_run,
    schedule_summary,
    unread_notifications,
)
from pageops.store import Store

ROOT = Path(__file__).resolve().parents[1]
CYCLE = ROOT / "scripts" / "run_cycle.py"
BKK = ZoneInfo("Asia/Bangkok")


def _store(tmp_path) -> Store:
    return Store(tmp_path / "data")


def _schedule(store: Store) -> None:
    store.set_brand_value("heartbeat_weekday", "0")  # Monday
    store.set_brand_value("heartbeat_time", "07:00")
    store.set_brand_value("heartbeat_timezone", "Asia/Bangkok")


def _a_monday(hour: int) -> datetime:
    """A Monday at the given Bangkok hour (2026-11-02 is a Monday)."""
    return datetime(2026, 11, 2, hour, 0, tzinfo=BKK)


def test_no_config_means_no_schedule(tmp_path):
    store = _store(tmp_path)
    assert heartbeat_config(store) is None
    assert heartbeat_due(store, now=_a_monday(8)) is False
    assert "not scheduled" in schedule_summary(store)


def test_invalid_config_values_are_ignored(tmp_path):
    store = _store(tmp_path)
    store.set_brand_value("heartbeat_weekday", "7")
    store.set_brand_value("heartbeat_time", "07:00")
    assert heartbeat_config(store) is None
    store.set_brand_value("heartbeat_weekday", "0")
    store.set_brand_value("heartbeat_time", "25:00")
    assert heartbeat_config(store) is None
    store.set_brand_value("heartbeat_time", "07:00")
    store.set_brand_value("heartbeat_timezone", "Not/AZone")
    assert heartbeat_config(store) is None


def test_due_when_moment_passed_and_never_ran(tmp_path):
    store = _store(tmp_path)
    _schedule(store)
    assert heartbeat_due(store, now=_a_monday(8)) is True


def test_not_due_before_the_moment(tmp_path):
    store = _store(tmp_path)
    _schedule(store)
    # Monday 06:00 Bangkok: this week's moment has not arrived, and
    # last week's was already served by a run then.
    record_run(store, _a_monday(6) - timedelta(days=6, hours=-1))
    assert heartbeat_due(store, now=_a_monday(6)) is False


def test_recorded_run_clears_the_due(tmp_path):
    store = _store(tmp_path)
    _schedule(store)
    record_run(store, _a_monday(7) + timedelta(minutes=5))
    assert heartbeat_due(store, now=_a_monday(9)) is False
    # The following Monday the schedule is owed again.
    assert heartbeat_due(store, now=_a_monday(8) + timedelta(days=7)) is True


def test_notify_dedupes_while_unread(tmp_path):
    store = _store(tmp_path)
    first = notify(store, "approval_pending", "2 item(s) are awaiting your approval on the dashboard.")
    assert first is not None
    assert notify(store, "approval_pending", "2 item(s) are awaiting your approval on the dashboard.") is None
    assert len(unread_notifications(store)) == 1
    assert mark_notifications_read(store) == 1
    assert unread_notifications(store) == []
    # After it is read, the same fact may notify again.
    assert notify(store, "approval_pending", "2 item(s) are awaiting your approval on the dashboard.") is not None


def test_gate_notification_counts_awaiting_items(tmp_path):
    store = _store(tmp_path)
    assert notify_gate_status(store) is None
    store.add_plan_row({"topic": "One", "status": "awaiting_approval"})
    store.add_plan_row({"topic": "Two", "status": "scheduled"})
    store.add_plan_row({"topic": "Three", "status": "awaiting_approval"})
    note = notify_gate_status(store)
    assert note is not None
    assert note["message"].startswith("2 item(s)")


def test_dashboard_shows_heartbeat_panel_and_notifications(tmp_path):
    store = _store(tmp_path)
    board = render_board(store)
    assert "Heartbeat" in board and "not scheduled" in board
    notify(store, "approval_pending", "1 item(s) are awaiting your approval on the dashboard.")
    board = render_board(store)
    assert "awaiting your approval" in board
    assert "Mark all read" in board


def _load_cycle():
    spec = importlib.util.spec_from_file_location("run_cycle_hb", CYCLE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_cycle_if_due_without_schedule_runs_nothing(tmp_path, monkeypatch, capsys):
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    (data_dir / "standing-brief.txt").write_text("A standing brief", encoding="utf-8")
    monkeypatch.setenv("PAGEOPS_DATA_DIR", str(data_dir))
    monkeypatch.setenv("MODEL_MODE", "mock")
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    cycle = _load_cycle()
    assert cycle.main(["--if-due"]) == 0
    assert "not due" in capsys.readouterr().out
    store = Store(data_dir)
    assert store.read_dataset("plan") == []
