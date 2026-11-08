"""Chat control layer (chat-first control, Phase 1).

The safety properties under test are the product's core promise in
its new interface: a mutating chat message by itself changes
NOTHING; only a confirm executes, through the same pipeline
functions the dashboard buttons call; a proposal whose assumed
state has drifted goes stale and executes nothing; an ambiguous
item reference proposes nothing.
"""
import threading
import urllib.parse
import urllib.request

from pageops.chat import (
    cancel_proposal,
    confirm_proposal,
    handle_message,
    pending_proposal,
    render_transcript,
    resolve_item,
    transcript,
)
from pageops.context import save_last_report
from pageops.dashboard import serve
from pageops.model_client import MockClient
from pageops.store import SqliteStore, Store

PASSING_DRAFT = "Original draft. Message us. #FYFAI #AIAutomation #SME"
EDITED_DRAFT = (
    "Edited caption about inbox replies. Message us to get started. "
    "#FYFAI #AIAutomation #SME"
)


def _awaiting(store, topic="Inbox replies post", draft=PASSING_DRAFT):
    return store.add_plan_row(
        {
            "platform": "facebook",
            "topic": topic,
            "status": "awaiting_approval",
            "draft": draft,
            "date": "2026-11-09",
        }
    )


def _plan_by_id(store):
    return {r["id"]: r for r in store.read_dataset("plan")}


# -- Intent parsing (MockClient's deterministic grammar) ---------------------


def test_mock_parse_intents():
    client = MockClient()
    parsed = client.parse_chat_intent("approve post 3", {})
    assert parsed["intent"] == "approve" and parsed["item_ref"] == "post 3"
    parsed = client.parse_chat_intent("approve the third one", {})
    assert parsed["intent"] == "approve" and parsed["item_ref"] == "third"
    parsed = client.parse_chat_intent('approve "message tips"', {})
    assert parsed["intent"] == "approve" and parsed["item_ref"] == "message tips"
    parsed = client.parse_chat_intent("reject post 2 because the tone is off", {})
    assert parsed["intent"] == "reject" and parsed["reason"] == "the tone is off"
    parsed = client.parse_chat_intent("edit post 1: Brand new draft text", {})
    assert parsed["intent"] == "edit_draft" and parsed["new_text"] == "Brand new draft text"
    parsed = client.parse_chat_intent("schedule post 1 at 2026-11-10T19:00", {})
    assert parsed["intent"] == "schedule" and parsed["datetime"] == "2026-11-10T19:00"
    parsed = client.parse_chat_intent("set tone to Friendly and plain", {})
    assert parsed["intent"] == "set_brand" and parsed["brand_key"] == "tone"
    assert parsed["value"] == "Friendly and plain"
    parsed = client.parse_chat_intent("set standing brief to: Grow leads this month", {})
    assert parsed["intent"] == "set_brief" and parsed["brief"] == "Grow leads this month"
    assert client.parse_chat_intent("status", {})["intent"] == "status"
    assert client.parse_chat_intent("report", {})["intent"] == "report"
    assert client.parse_chat_intent("what is the weather today", {})["intent"] == "unknown"


# -- Read-only intents ---------------------------------------------------------


def test_status_reply_uses_real_store_numbers(tmp_path):
    store = Store(tmp_path)
    _awaiting(store, topic="First post")
    _awaiting(store, topic="Second post")
    result = handle_message(store, MockClient(), "status")
    assert result["intent"] == "status"
    assert "2" in result["reply"] and "First post" in result["reply"]
    assert pending_proposal(store) is None


def test_report_quotes_the_stored_narrative(tmp_path):
    store = Store(tmp_path)
    save_last_report(store, "Recorded report: 170 reach, 13 engagements.")
    result = handle_message(store, MockClient(), "report")
    assert "Recorded report: 170 reach, 13 engagements." in result["reply"]


def test_unknown_message_proposes_nothing(tmp_path):
    store = Store(tmp_path)
    _awaiting(store)
    result = handle_message(store, MockClient(), "tell me a joke")
    assert result["intent"] == "unknown"
    assert pending_proposal(store) is None
    assert _plan_by_id(store)["1"]["status"] == "awaiting_approval"


# -- The confirmation gate -----------------------------------------------------


def test_mutating_message_alone_changes_nothing(tmp_path):
    store = Store(tmp_path)
    row = _awaiting(store)
    before_plan = store.read_dataset("plan")
    before_brand = store.read_dataset("brand_voice")
    result = handle_message(store, MockClient(), "approve post 1")
    assert result["proposal_id"]
    assert store.read_dataset("plan") == before_plan
    assert store.read_dataset("brand_voice") == before_brand
    proposal = pending_proposal(store)
    assert proposal is not None and proposal["item_id"] == row["id"]
    assert "Original draft" in proposal["payload"]


def test_confirm_approve_executes_the_gate_action(tmp_path):
    store = Store(tmp_path)
    row = _awaiting(store)
    result = handle_message(store, MockClient(), "approve post 1")
    outcome = confirm_proposal(store, MockClient(), result["proposal_id"])
    assert outcome["ok"] is True
    assert _plan_by_id(store)[row["id"]]["status"] == "approved"
    kinds = [r["kind"] for r in transcript(store)]
    assert kinds == ["message", "proposal", "result"]


def test_stale_proposal_refuses_and_changes_nothing(tmp_path):
    store = Store(tmp_path)
    row = _awaiting(store)
    result = handle_message(store, MockClient(), "approve post 1")
    # The owner edits the draft on the dashboard meanwhile: the
    # proposal card no longer shows the current text.
    store.update_row("plan", row["id"], {"draft": "Changed on the dashboard"})
    outcome = confirm_proposal(store, MockClient(), result["proposal_id"])
    assert outcome["ok"] is False and outcome["reason"] == "stale"
    after = _plan_by_id(store)[row["id"]]
    assert after["status"] == "awaiting_approval"
    assert after["draft"] == "Changed on the dashboard"
    proposal = [r for r in transcript(store) if r["kind"] == "proposal"][0]
    assert proposal["status"] == "stale"


def test_new_mutating_message_supersedes_the_pending_one(tmp_path):
    store = Store(tmp_path)
    first = _awaiting(store, topic="First post")
    second = _awaiting(store, topic="Second post")
    one = handle_message(store, MockClient(), "approve post 1")
    two = handle_message(store, MockClient(), "approve post 2")
    proposals = {r["id"]: r for r in transcript(store) if r["kind"] == "proposal"}
    assert proposals[one["proposal_id"]]["status"] == "superseded"
    assert proposals[two["proposal_id"]]["status"] == "pending"
    outcome = confirm_proposal(store, MockClient(), one["proposal_id"])
    assert outcome["ok"] is False
    assert _plan_by_id(store)[first["id"]]["status"] == "awaiting_approval"
    outcome = confirm_proposal(store, MockClient(), two["proposal_id"])
    assert outcome["ok"] is True
    assert _plan_by_id(store)[second["id"]]["status"] == "approved"


def test_cancel_then_confirm_does_nothing(tmp_path):
    store = Store(tmp_path)
    row = _awaiting(store)
    result = handle_message(store, MockClient(), "approve post 1")
    assert cancel_proposal(store, result["proposal_id"])["ok"] is True
    outcome = confirm_proposal(store, MockClient(), result["proposal_id"])
    assert outcome["ok"] is False
    assert _plan_by_id(store)[row["id"]]["status"] == "awaiting_approval"


# -- Item reference resolution ---------------------------------------------------


def test_ambiguous_topic_reference_proposes_nothing(tmp_path):
    store = Store(tmp_path)
    _awaiting(store, topic="Message tips for shops")
    _awaiting(store, topic="Message tips for salons")
    result = handle_message(store, MockClient(), 'approve "message tips"')
    assert "proposal_id" not in result
    assert pending_proposal(store) is None
    statuses = [r["status"] for r in store.read_dataset("plan")]
    assert statuses == ["awaiting_approval", "awaiting_approval"]


def test_out_of_range_reference_proposes_nothing(tmp_path):
    store = Store(tmp_path)
    _awaiting(store)
    result = handle_message(store, MockClient(), "approve post 9")
    assert "proposal_id" not in result
    assert pending_proposal(store) is None


def test_ordinal_reference_resolves_in_board_order(tmp_path):
    store = Store(tmp_path)
    _awaiting(store, topic="First post")
    target = _awaiting(store, topic="Second post")
    result = handle_message(store, MockClient(), "approve the second one")
    proposal = pending_proposal(store)
    assert proposal["item_id"] == target["id"]
    confirm_proposal(store, MockClient(), result["proposal_id"])
    assert _plan_by_id(store)[target["id"]]["status"] == "approved"


# -- Burmese item references (the owners speak Burmese) --------------------------

_BURMESE_ORDINALS = [
    ("ပထမ", 1),
    ("ပထမဆုံး", 1),
    ("အရင်ဆုံး", 1),
    ("ဒုတိယ", 2),
    ("တတိယ", 3),
    ("စတုတ္ထ", 4),
    ("ပဉ္စမ", 5),
    ("ဆဋ္ဌမ", 6),
    ("သတ္တမ", 7),
]


def _pool(store, count=7):
    return [_awaiting(store, topic=f"Post {i}") for i in range(1, count + 1)]


def test_mock_parse_burmese_references():
    client = MockClient()
    parsed = client.parse_chat_intent(
        "ပထမဆုံး စောင့်နေတဲ့ post ကို approve လုပ်မယ်", {}
    )
    assert parsed["intent"] == "approve" and parsed["item_ref"] == "ပထမဆုံး"
    parsed = client.parse_chat_intent("approve post ၁", {})
    assert parsed["intent"] == "approve" and parsed["item_ref"] == "post ၁"
    parsed = client.parse_chat_intent("approve ၃ ခုမြောက် post", {})
    assert parsed["intent"] == "approve" and parsed["item_ref"] == "၃ ခုမြောက်"
    for word, _position in _BURMESE_ORDINALS:
        parsed = client.parse_chat_intent(f"approve {word} post", {})
        assert parsed["item_ref"] == word
    parsed = client.parse_chat_intent("approve နောက်ဆုံး post", {})
    assert parsed["item_ref"] == "နောက်ဆုံး"


def test_burmese_ordinals_resolve_to_pool_positions(tmp_path):
    store = Store(tmp_path)
    pool = _pool(store)
    for word, position in _BURMESE_ORDINALS:
        row, problem = resolve_item(store, "approve", word)
        assert problem == "" and row["id"] == pool[position - 1]["id"], word


def test_burmese_ordinal_with_counter_resolves(tmp_path):
    store = Store(tmp_path)
    pool = _pool(store, count=3)
    row, problem = resolve_item(store, "approve", "ပထမ တစ်ခု")
    assert problem == "" and row["id"] == pool[0]["id"]
    row, problem = resolve_item(store, "approve", "ဒုတိယ တစ်ခု")
    assert problem == "" and row["id"] == pool[1]["id"]


def test_myanmar_digit_references_resolve(tmp_path):
    store = Store(tmp_path)
    pool = _pool(store)
    row, problem = resolve_item(store, "approve", "post ၂")
    assert problem == "" and row["id"] == pool[1]["id"]
    row, problem = resolve_item(store, "approve", "၃ ခုမြောက်")
    assert problem == "" and row["id"] == pool[2]["id"]
    row, problem = resolve_item(store, "approve", "post ၇")
    assert problem == "" and row["id"] == pool[6]["id"]


def test_last_reference_resolves_to_the_final_pool_item(tmp_path):
    store = Store(tmp_path)
    pool = _pool(store, count=3)
    row, problem = resolve_item(store, "approve", "နောက်ဆုံး")
    assert problem == "" and row["id"] == pool[-1]["id"]


def test_first_waiting_post_sentence_end_to_end(tmp_path):
    # The exact sentence that failed live on 2026-11-08: a natural
    # Burmese reference inside a full sentence must propose the
    # first awaiting item, change nothing until confirm, and then
    # approve exactly that item.
    store = Store(tmp_path)
    first = _awaiting(store, topic="First post")
    second = _awaiting(store, topic="Second post")
    before = store.read_dataset("plan")
    result = handle_message(
        store, MockClient(), "ပထမဆုံး စောင့်နေတဲ့ post ကို approve လုပ်မယ်"
    )
    proposal = pending_proposal(store)
    assert proposal is not None and proposal["item_id"] == first["id"]
    assert store.read_dataset("plan") == before
    outcome = confirm_proposal(store, MockClient(), result["proposal_id"])
    assert outcome["ok"] is True
    rows = _plan_by_id(store)
    assert rows[first["id"]]["status"] == "approved"
    assert rows[second["id"]]["status"] == "awaiting_approval"


def test_burmese_marker_inside_topic_words_stays_a_topic(tmp_path):
    # The positional scan must not swallow a reference carrying
    # real topic words: နောက်ဆုံး + content words is a topic
    # reference, settled by topic matching, not by position.
    store = Store(tmp_path)
    target = _awaiting(store, topic="နောက်ဆုံး သတင်း အကျဉ်း")
    _awaiting(store, topic="Another post")
    row, problem = resolve_item(store, "approve", "နောက်ဆုံး သတင်း")
    assert problem == "" and row["id"] == target["id"]


# -- Each mutating intent, end to end --------------------------------------------


def test_reject_needs_a_reason_and_keeps_it(tmp_path):
    store = Store(tmp_path)
    row = _awaiting(store)
    result = handle_message(store, MockClient(), "reject post 1")
    assert "proposal_id" not in result  # asked for the reason instead
    result = handle_message(store, MockClient(), "reject post 1 because Off-brand tone")
    outcome = confirm_proposal(store, MockClient(), result["proposal_id"])
    assert outcome["ok"] is True
    after = _plan_by_id(store)[row["id"]]
    assert after["status"] == "rejected" and after["reject_reason"] == "Off-brand tone"


def test_edit_confirm_replaces_and_rechecks_the_draft(tmp_path):
    store = Store(tmp_path)
    row = _awaiting(store)
    result = handle_message(store, MockClient(), f"edit post 1: {EDITED_DRAFT}")
    outcome = confirm_proposal(store, MockClient(), result["proposal_id"])
    assert outcome["ok"] is True
    after = _plan_by_id(store)[row["id"]]
    assert after["draft"] == EDITED_DRAFT
    assert after["status"] in ("awaiting_approval", "checked")
    assert after["check_status"]  # the re-check evidence is on the row


def test_schedule_proposal_renders_bangkok_and_confirm_stores_it(tmp_path):
    store = Store(tmp_path)
    row = store.add_plan_row(
        {"platform": "facebook", "topic": "Launch post", "status": "approved",
         "draft": PASSING_DRAFT}
    )
    result = handle_message(store, MockClient(), "schedule post 1 at 2026-11-10T19:00")
    proposal = pending_proposal(store)
    assert "2026-11-10 19:00 (Asia/Bangkok)" in proposal["payload"]
    outcome = confirm_proposal(store, MockClient(), result["proposal_id"])
    assert outcome["ok"] is True
    after = _plan_by_id(store)[row["id"]]
    assert after["status"] == "scheduled"
    assert after["scheduled_for"] == "2026-11-10T19:00"
    assert after["buffer_id"].startswith("dry-run-")


def test_schedule_without_a_real_datetime_proposes_nothing(tmp_path):
    store = Store(tmp_path)
    store.add_plan_row(
        {"platform": "facebook", "topic": "Launch post", "status": "approved",
         "draft": PASSING_DRAFT}
    )
    result = handle_message(store, MockClient(), "schedule post 1 at next friday")
    assert "proposal_id" not in result
    assert pending_proposal(store) is None


def test_set_brand_proposal_and_confirm(tmp_path):
    store = Store(tmp_path)
    old_tone = {r["key"]: r["value"] for r in store.read_dataset("brand_voice")}["tone"]
    result = handle_message(store, MockClient(), "set tone to Friendly, plain, warm")
    proposal = pending_proposal(store)
    assert old_tone in proposal["payload"]
    assert {r["key"]: r["value"] for r in store.read_dataset("brand_voice")}["tone"] == old_tone
    outcome = confirm_proposal(store, MockClient(), result["proposal_id"])
    assert outcome["ok"] is True
    assert {r["key"]: r["value"] for r in store.read_dataset("brand_voice")}["tone"] == (
        "Friendly, plain, warm"
    )


def test_set_brand_unknown_key_proposes_nothing(tmp_path):
    store = Store(tmp_path)
    result = handle_message(store, MockClient(), "set nope_key to x")
    assert "proposal_id" not in result
    assert pending_proposal(store) is None


def test_set_brief_confirm_writes_the_file(tmp_path):
    store = Store(tmp_path)
    result = handle_message(
        store, MockClient(), "set standing brief to: Grow chatbot leads this month"
    )
    outcome = confirm_proposal(store, MockClient(), result["proposal_id"])
    assert outcome["ok"] is True
    assert (tmp_path / "standing-brief.txt").read_text(encoding="utf-8") == (
        "Grow chatbot leads this month"
    )


# -- Rendering + HTTP surface -----------------------------------------------------


def test_transcript_renders_the_full_draft_and_confirm_form(tmp_path):
    store = Store(tmp_path)
    _awaiting(store)
    handle_message(store, MockClient(), "approve post 1")
    html_out = render_transcript(store)
    assert PASSING_DRAFT in html_out  # the FULL draft, not a summary
    assert 'action="/chat-confirm"' in html_out
    assert 'action="/chat-cancel"' in html_out
    assert 'value="approve"' not in html_out  # the board's gate property


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


def test_chat_over_http_propose_then_confirm(tmp_path):
    store = Store(tmp_path)
    row = _awaiting(store)
    server, base = _start(store)
    try:
        assert _post(base + "/chat", {"message": "approve post 1"}) == 200
        assert _plan_by_id(store)[row["id"]]["status"] == "awaiting_approval"
        proposal = pending_proposal(store)
        assert proposal is not None
        with urllib.request.urlopen(base + "/", timeout=5) as resp:
            board = resp.read().decode("utf-8")
        assert 'id="chat"' in board and PASSING_DRAFT in board
        assert _post(base + "/chat-confirm", {"proposal": proposal["id"]}) == 200
        assert _plan_by_id(store)[row["id"]]["status"] == "approved"
    finally:
        server.shutdown()


def test_chat_works_on_the_sqlite_backend(tmp_path):
    store = SqliteStore(tmp_path)
    row = _awaiting(store)
    result = handle_message(store, MockClient(), "approve post 1")
    outcome = confirm_proposal(store, MockClient(), result["proposal_id"])
    assert outcome["ok"] is True
    assert _plan_by_id(store)[row["id"]]["status"] == "approved"
    assert len(transcript(store)) == 3
