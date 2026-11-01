import threading
import urllib.parse
import urllib.request

from pageops.dashboard import serve
from pageops.store import Store


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


def test_brief_form_creates_card(tmp_path):
    store = Store(tmp_path)
    server, base = _start(store)
    try:
        assert _post(base + "/brief", {"goal": "Grow leads", "offer": "Chatbot"}) == 200
        rows = store.read_dataset("plan")
        assert rows and rows[0]["status"] == "brief_received"
        assert "Grow leads" in rows[0]["brief"]
    finally:
        server.shutdown()


def test_run_pipeline_from_brief_card(tmp_path):
    store = Store(tmp_path)
    brief = store.add_plan_row({"status": "brief_received", "brief": "Grow leads"})
    server, base = _start(store)
    try:
        assert _post(base + "/action", {"id": brief["id"], "action": "run"}) == 200
        rows = store.read_dataset("plan")
        statuses = [r["status"] for r in rows]
        assert "awaiting_approval" in statuses  # drafts generated + checked
        brief_row = {r["id"]: r for r in rows}[brief["id"]]
        assert brief_row["status"] == "planned"
    finally:
        server.shutdown()


def test_approve_then_schedule_flow(tmp_path):
    store = Store(tmp_path)
    row = store.add_plan_row(
        {"platform": "facebook", "topic": "Post", "status": "awaiting_approval"}
    )
    server, base = _start(store)
    try:
        assert _post(base + "/action", {"id": row["id"], "action": "approve"}) == 200
        assert store.read_dataset("plan")[0]["status"] == "approved"
        assert _post(base + "/action", {"id": row["id"], "action": "schedule"}) == 200
        final = store.read_dataset("plan")[0]
        assert final["status"] == "scheduled"
        assert final["buffer_id"].startswith("dry-run-")
    finally:
        server.shutdown()


def test_edit_rechecks_the_draft(tmp_path):
    store = Store(tmp_path)
    row = store.add_plan_row(
        {
            "platform": "facebook",
            "topic": "Post",
            "status": "awaiting_approval",
            "draft": "Clean draft. Message us. #FYFAI",
        }
    )
    server, base = _start(store)
    try:
        bad = "Get guaranteed income now. Message us. #FYFAI"
        assert _post(base + "/action", {"id": row["id"], "action": "edit", "draft": bad}) == 200
        after_bad = store.read_dataset("plan")[0]
        assert after_bad["status"] == "checked"
        assert "[FAIL] banned_phrases" in after_bad["check_status"]
        good = "Edited and clean. Message us to get started. #FYFAI #AIAutomation"
        assert _post(base + "/action", {"id": row["id"], "action": "edit", "draft": good}) == 200
        after_good = store.read_dataset("plan")[0]
        assert after_good["status"] == "awaiting_approval"
        assert after_good["draft"] == good
    finally:
        server.shutdown()


def test_schedule_without_approval_is_rejected(tmp_path):
    store = Store(tmp_path)
    row = store.add_plan_row(
        {"platform": "facebook", "topic": "Post", "status": "awaiting_approval"}
    )
    server, base = _start(store)
    try:
        assert _post(base + "/action", {"id": row["id"], "action": "schedule"}) == 400
        assert store.read_dataset("plan")[0]["status"] == "awaiting_approval"
    finally:
        server.shutdown()
