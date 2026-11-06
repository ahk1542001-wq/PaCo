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
        good = "Edited and clean. Message us to get started. #FYFAI #AIAutomation #SME"
        assert _post(base + "/action", {"id": row["id"], "action": "edit", "draft": good}) == 200
        after_good = store.read_dataset("plan")[0]
        assert after_good["status"] == "awaiting_approval"
        assert after_good["draft"] == good
    finally:
        server.shutdown()


def test_run_action_in_meta_mode_hands_the_pipeline_a_real_judge(tmp_path, monkeypatch):
    """Regression guard for the 2026-11-05 demo incident.

    The dashboard and the weekly cycle construct their model
    clients identically; the mock drafts that night came from a
    dashboard server launched WITHOUT MODEL_MODE / MODEL_API_KEY
    in its environment, so every factory fell back to mock. With
    meta mode in the environment (what scripts/run_dashboard_live.py
    supplies), the run action must hand the pipeline the dedicated
    Wonder judge: a real MetaModelClient, not None and not a mock.
    The pipeline entry point is captured, not run, and httpx is
    blocked, so nothing leaves the machine.
    """
    import httpx

    from pageops import pipeline
    from pageops.model_client import MODEL_WONDER, MetaImageClient, MetaModelClient

    monkeypatch.setenv("MODEL_MODE", "meta")
    monkeypatch.setenv("MODEL_API_KEY", "test-key-not-real")
    monkeypatch.setenv("PAGEOPS_DATA_DIR", str(tmp_path))

    def _no_network(*args, **kwargs):
        raise AssertionError("network call attempted during run-action wiring test")

    monkeypatch.setattr(httpx, "post", _no_network)

    captured = {}

    def fake_run_brief(store, client, item_id, **kwargs):
        captured["client"] = client
        captured["item_id"] = item_id
        captured.update(kwargs)

    monkeypatch.setattr(pipeline, "run_brief", fake_run_brief)

    store = Store(tmp_path)
    brief = store.add_plan_row({"status": "brief_received", "brief": "Grow leads"})
    server, base = _start(store)
    try:
        assert _post(base + "/action", {"id": brief["id"], "action": "run"}) == 200
    finally:
        server.shutdown()

    assert captured["item_id"] == brief["id"]
    judge = captured["judge"]
    assert isinstance(judge, MetaModelClient)  # a real judge, not None / mock
    assert judge is not captured["client"]  # dedicated pass, its own instance
    assert judge.verdict_model == MODEL_WONDER
    assert isinstance(captured["client"], MetaModelClient)
    assert isinstance(captured["image_client"], MetaImageClient)
    assert captured["trends_fetcher"] is not None  # live mode researches first


def test_standing_brief_panel_saves_the_file(tmp_path):
    from pageops.dashboard import render_board

    store = Store(tmp_path)
    server, base = _start(store)
    try:
        assert _post(base + "/standing-brief", {"brief": "A varied week for FYF AI"}) == 200
        brief_path = tmp_path / "standing-brief.txt"
        assert brief_path.read_text(encoding="utf-8") == "A varied week for FYF AI"
        # The panel renders what is on disk: the owner edits the
        # heartbeat's real input, not a copy of it.
        assert "A varied week for FYF AI" in render_board(store)
        # Saving again overwrites (the file now exists).
        assert _post(base + "/standing-brief", {"brief": "Second version"}) == 200
        assert brief_path.read_text(encoding="utf-8") == "Second version"
    finally:
        server.shutdown()


def test_schedule_with_a_chosen_datetime_stores_it(tmp_path):
    store = Store(tmp_path)
    row = store.add_plan_row(
        {"platform": "facebook", "topic": "Post", "status": "awaiting_approval"}
    )
    server, base = _start(store)
    try:
        assert _post(base + "/action", {"id": row["id"], "action": "approve"}) == 200
        assert _post(
            base + "/action",
            {
                "id": row["id"],
                "action": "schedule",
                "scheduled_for": "2026-11-09T19:00",
            },
        ) == 200
        final = store.read_dataset("plan")[0]
        assert final["status"] == "scheduled"
        assert final["scheduled_for"] == "2026-11-09T19:00"
    finally:
        server.shutdown()


def test_brand_level_edit_via_dashboard_keeps_drafted(tmp_path):
    from pageops.brand_builder import draft_level, level_statuses
    from pageops.model_client import MockClient

    store = Store(tmp_path)  # the seeded FYF identity stands approved
    draft_level(store, 2, MockClient(), "brief")
    server, base = _start(store)
    try:
        assert _post(
            base + "/brand-level",
            {"level": "2", "action": "edit", "content": "Owner-edited audience."},
        ) == 200
        assert level_statuses(store)[2] == "drafted"
        row = [r for r in store.read_dataset("brand_build") if r["level"] == "2"][0]
        assert row["content"] == "Owner-edited audience."
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
