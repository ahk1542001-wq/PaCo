"""Approval-gate integrity (M18 fix, PR #5).

The gate is the product's core promise, so its preconditions live
in the pipeline, not in button rendering: approve only from
awaiting_approval, edits only before approval and always re-checked
AND re-verdicted, rejections keep their reason.
"""
import threading
import urllib.parse
import urllib.request

import pytest

from pageops.dashboard import serve
from pageops.model_client import MockClient
from pageops.pipeline import (
    approve_item,
    draft_and_check,
    edit_item,
    reject_item,
)
from pageops.store import Store


def _row(store, status, **kw):
    return store.add_plan_row(
        {"platform": "facebook", "topic": "T", "status": status, **kw}
    )


def test_approve_refuses_checked_row(tmp_path):
    store = Store(tmp_path)
    row = _row(store, "checked", draft="Weak draft", check_status="[FAIL] cta")
    with pytest.raises(PermissionError):
        approve_item(store, row["id"])


def test_approve_accepts_awaiting_row(tmp_path):
    store = Store(tmp_path)
    row = _row(store, "awaiting_approval", draft="Good draft")
    updated = approve_item(store, row["id"])
    assert updated["status"] == "approved"


def test_reject_keeps_reason(tmp_path):
    store = Store(tmp_path)
    row = _row(store, "awaiting_approval", draft="Good draft")
    updated = reject_item(store, row["id"], reason="Off-brand tone")
    assert updated["status"] == "rejected"
    assert updated["reject_reason"] == "Off-brand tone"


def test_reject_refuses_scheduled_row(tmp_path):
    store = Store(tmp_path)
    row = _row(store, "scheduled", draft="Live draft", buffer_id="dry-run-1")
    with pytest.raises(PermissionError):
        reject_item(store, row["id"], reason="Too late")


def test_edit_refuses_scheduled_row(tmp_path):
    store = Store(tmp_path)
    row = _row(store, "scheduled", draft="Live draft", buffer_id="dry-run-1")
    with pytest.raises(PermissionError):
        edit_item(store, MockClient(), row["id"], "New text")


def test_edit_reruns_the_model_verdict(tmp_path):
    store = Store(tmp_path)
    row = _row(
        store,
        "awaiting_approval",
        draft="Old draft. Message us. #FYFAI #AIAutomation #SME",
        check_status="old evidence",
    )
    updated = edit_item(
        store,
        MockClient(),
        row["id"],
        "Edited draft. Message us today. #FYFAI #AIAutomation #SME",
    )
    assert "[MODEL VERDICT]" in updated["check_status"]
    assert updated["status"] == "awaiting_approval"


def test_draft_and_check_passes_through_drafted(tmp_path):
    store = Store(tmp_path)
    seen: list[str] = []
    original = store.update_row

    def spy(dataset, row_id, updates):
        if "status" in updates:
            seen.append(updates["status"])
        return original(dataset, row_id, updates)

    store.update_row = spy
    row = _row(store, "planned", topic="Spy topic")
    draft_and_check(store, MockClient(), row)
    assert "drafted" in seen
    assert "visual_ready" in seen
    assert seen[-1] == "awaiting_approval"


def test_reject_without_reason_is_refused(tmp_path):
    store = Store(tmp_path)
    row = _row(store, "awaiting_approval", draft="Good draft")
    with pytest.raises(ValueError):
        reject_item(store, row["id"], reason="  ")


def test_checked_card_offers_edit_and_reject_on_the_board(tmp_path):
    from pageops.dashboard import render_board

    store = Store(tmp_path)
    _row(store, "checked", draft="Flagged draft", check_status="[FAIL] cta")
    board = render_board(store)
    assert "Save edit + re-check" in board
    assert 'value="reject"' in board
    assert 'value="approve"' not in board


def test_run_brief_through_the_orchestrator(tmp_path):
    from pageops.pipeline import intake_brief, run_brief

    store = Store(tmp_path)
    brief = intake_brief(store, "Promote the chatbot offer")
    drafted = run_brief(store, MockClient(), brief["id"])
    assert drafted and all(r["status"] == "awaiting_approval" for r in drafted)
    reread = [r for r in store.read_dataset("plan") if r["id"] == brief["id"]][0]
    assert reread["status"] == "planned"


def _start(store):
    server = serve(store, port=0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def _post(url, data):
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code


def test_dashboard_approve_of_checked_row_is_400(tmp_path):
    store = Store(tmp_path)
    row = _row(store, "checked", draft="Weak", check_status="[FAIL] cta")
    server, base = _start(store)
    try:
        code = _post(base + "/action", {"id": row["id"], "action": "approve"})
        assert code == 400
        reread = [r for r in store.read_dataset("plan") if r["id"] == row["id"]][0]
        assert reread["status"] == "checked"
    finally:
        server.shutdown()


def test_dashboard_reject_records_reason(tmp_path):
    store = Store(tmp_path)
    row = _row(store, "awaiting_approval", draft="Good")
    server, base = _start(store)
    try:
        code = _post(
            base + "/action",
            {"id": row["id"], "action": "reject", "reason": "Wrong offer"},
        )
        assert code in (200, 303)
        reread = [r for r in store.read_dataset("plan") if r["id"] == row["id"]][0]
        assert reread["status"] == "rejected"
        assert reread["reject_reason"] == "Wrong offer"
    finally:
        server.shutdown()
