"""Report stage completion (M18 fix, PR #11).

The Analyst's stage as an explicit act: metrics are pulled into
the store (deduplicated), a published post is linked to its plan
row, running the report marks linked scheduled rows as reported,
and the narrative gains a model-written reading of the computed
numbers. build_report itself stays a pure function of the store.
"""
import pytest

from pageops.context import latest_analyst_summary
from pageops.metrics import import_metrics
from pageops.model_client import MockClient
from pageops.pipeline import link_post, report_week
from pageops.report import build_report
from pageops.store import Store

METRIC = {
    "date": "2026-11-03",
    "platform": "facebook",
    "post_id": "fb-123",
    "reach": "500",
    "engagement": "40",
    "clicks": "6",
    "notes": "",
}


def test_import_metrics_dedupes_on_post_and_date(tmp_path):
    store = Store(tmp_path)
    assert import_metrics(store, [METRIC]) == 1
    assert import_metrics(store, [METRIC]) == 0
    assert len(store.read_dataset("metrics")) == 1
    changed = dict(METRIC, reach="650")
    assert import_metrics(store, [changed]) == 0  # same key: updated, not duplicated
    assert store.read_dataset("metrics")[0]["reach"] == "650"


def test_link_post_only_for_scheduled_rows(tmp_path):
    store = Store(tmp_path)
    waiting = store.add_plan_row({"topic": "T", "status": "awaiting_approval"})
    with pytest.raises(PermissionError):
        link_post(store, waiting["id"], "fb-123")
    live = store.add_plan_row({"topic": "T2", "status": "scheduled", "buffer_id": "dry-run-9"})
    updated = link_post(store, live["id"], "fb-123")
    assert updated["post_id"] == "fb-123"


def test_report_week_marks_linked_rows_reported(tmp_path):
    store = Store(tmp_path)
    import_metrics(store, [METRIC])
    live = store.add_plan_row({"topic": "T2", "status": "scheduled", "buffer_id": "dry-run-9"})
    link_post(store, live["id"], "fb-123")
    other = store.add_plan_row({"topic": "T3", "status": "scheduled", "buffer_id": "dry-run-10"})
    report_week(store, MockClient())
    rows = {r["id"]: r for r in store.read_dataset("plan")}
    assert rows[live["id"]]["status"] == "reported"
    assert rows[other["id"]]["status"] == "scheduled"


def test_model_narrative_reads_only_computed_numbers(tmp_path):
    store = Store(tmp_path)
    import_metrics(store, [METRIC])
    with_model = build_report(store, client=MockClient())
    assert "Read:" in with_model["narrative"]
    assert "reach 500" in with_model["narrative"]
    plain = build_report(store)
    assert "Read:" not in plain["narrative"]


def test_build_report_is_pure_and_report_week_records_history(tmp_path):
    store = Store(tmp_path)
    import_metrics(store, [METRIC])
    build_report(store)
    build_report(store)
    assert latest_analyst_summary(store) == ""  # no side effects from reading
    report_week(store, MockClient())
    assert "500" in latest_analyst_summary(store)
