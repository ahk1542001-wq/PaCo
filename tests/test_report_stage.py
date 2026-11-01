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
    report_week(store, client=MockClient())
    rows = {r["id"]: r for r in store.read_dataset("plan")}
    assert rows[live["id"]]["status"] == "reported"
    assert rows[other["id"]]["status"] == "scheduled"


def test_model_narrative_reads_only_computed_numbers(tmp_path):
    store = Store(tmp_path)
    import_metrics(store, [METRIC])
    with_model = build_report(store, client=MockClient())
    read_line = next(
        line for line in with_model["narrative"].splitlines() if line.startswith("Read:")
    )
    # Pin the model section itself, not the deterministic Result
    # line (which carries the same figure).
    assert "across 1 tracked posts" in read_line
    assert "500 reach" in read_line
    plain = build_report(store)
    assert "Read:" not in plain["narrative"]


def test_build_report_is_pure_and_report_week_records_history(tmp_path):
    store = Store(tmp_path)
    import_metrics(store, [METRIC])
    build_report(store)
    build_report(store)
    assert latest_analyst_summary(store) == ""  # no side effects from reading
    report_week(store, client=MockClient())
    assert "500" in latest_analyst_summary(store)



def test_dashboard_link_action_joins_the_post(tmp_path):
    import threading
    import urllib.error
    import urllib.parse
    import urllib.request

    from pageops.dashboard import serve

    store = Store(tmp_path)
    live = store.add_plan_row({"topic": "T", "status": "scheduled", "buffer_id": "dry-run-3"})
    waiting = store.add_plan_row({"topic": "W", "status": "awaiting_approval"})
    server = serve(store, port=0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"

    def post(data):
        body = urllib.parse.urlencode(data).encode()
        req = urllib.request.Request(base + "/action", data=body, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status
        except urllib.error.HTTPError as exc:
            return exc.code

    try:
        assert post({"id": live["id"], "action": "link", "post_id": "fb-9"}) == 200
        rows = {r["id"]: r for r in store.read_dataset("plan")}
        assert rows[live["id"]]["post_id"] == "fb-9"
        # The gate holds at the board too: a non-scheduled row refuses.
        assert post({"id": waiting["id"], "action": "link", "post_id": "fb-9"}) == 400
    finally:
        server.shutdown()



def test_linked_but_unmeasured_row_stays_scheduled(tmp_path):
    store = Store(tmp_path)
    import_metrics(store, [METRIC])
    unmeasured = store.add_plan_row(
        {"topic": "U", "status": "scheduled", "buffer_id": "dry-run-11"}
    )
    link_post(store, unmeasured["id"], "fb-unmeasured")
    report_week(store, client=MockClient())
    rows = {r["id"]: r for r in store.read_dataset("plan")}
    assert rows[unmeasured["id"]]["status"] == "scheduled"


class RogueClient(MockClient):
    def narrate(self, stats, brand_voice):
        return "reach exploded to 9999 overnight, a miracle"


def test_invented_figures_drop_the_read_line(tmp_path):
    store = Store(tmp_path)
    import_metrics(store, [METRIC])
    report = build_report(store, client=RogueClient())
    assert "Read:" not in report["narrative"]
    assert "9999" not in report["narrative"]


def test_dashboard_run_report_records_and_displays(tmp_path):
    import threading
    import urllib.request

    from pageops.dashboard import serve

    store = Store(tmp_path)
    import_metrics(store, [METRIC])
    live = store.add_plan_row({"topic": "T2", "status": "scheduled", "buffer_id": "dry-run-9"})
    link_post(store, live["id"], "fb-123")
    server = serve(store, port=0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        req = urllib.request.Request(base + "/report", data=b"", method="POST")
        with urllib.request.urlopen(req, timeout=5) as resp:
            assert resp.status == 200
        rows = {r["id"]: r for r in store.read_dataset("plan")}
        assert rows[live["id"]]["status"] == "reported"
        with urllib.request.urlopen(base + "/", timeout=5) as resp:
            board = resp.read().decode()
        assert "Read:" in board  # the recorded narrative is displayed
    finally:
        server.shutdown()
