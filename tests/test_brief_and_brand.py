"""Brief restatement + brand panel editing (M18 fix, PR #9).

The agent restates every brief in structured form and flags what
is missing, instead of storing raw form text. The brand voice is
editable as data from the dashboard, through the pipeline.
"""
import threading
import urllib.parse
import urllib.request

import pytest

from pageops.dashboard import serve
from pageops.pipeline import intake_brief, update_brand_voice
from pageops.store import Store


def test_intake_restates_brief_and_flags_missing_fields(tmp_path):
    store = Store(tmp_path)
    row = intake_brief(store, "ignored", fields={"goal": "Grow leads", "offer": "", "dates": "", "notes": ""})
    check = row["brief_check"]
    assert "Grow leads" in check
    assert "missing: offer" in check
    assert "missing: dates" in check


def test_intake_with_all_fields_flags_nothing(tmp_path):
    store = Store(tmp_path)
    row = intake_brief(
        store,
        "ignored",
        fields={"goal": "G", "offer": "Chatbot", "dates": "Nov 10-16", "notes": "N"},
    )
    assert "missing:" not in row["brief_check"]


def test_update_brand_voice_round_trips(tmp_path):
    store = Store(tmp_path)
    update_brand_voice(store, "tone", "Warm and direct")
    assert store.get_brand_voice()["tone"] == "Warm and direct"


def test_update_brand_voice_refuses_unknown_keys(tmp_path):
    store = Store(tmp_path)
    with pytest.raises(ValueError):
        update_brand_voice(store, "not_a_real_key", "x")


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


def test_dashboard_brand_edit_updates_the_store(tmp_path):
    store = Store(tmp_path)
    server, base = _start(store)
    try:
        code = _post(base + "/brand", {"key": "tone", "value": "Calm and clear"})
        assert code in (200, 303)
        assert store.get_brand_voice()["tone"] == "Calm and clear"
        assert _post(base + "/brand", {"key": "bogus", "value": "x"}) == 400
    finally:
        server.shutdown()


def test_dashboard_brief_flags_missing_offer(tmp_path):
    store = Store(tmp_path)
    server, base = _start(store)
    try:
        assert _post(base + "/brief", {"goal": "Grow leads"}) in (200, 303)
        brief = [r for r in store.read_dataset("plan") if r["status"] == "brief_received"][0]
        assert "missing: offer" in brief["brief_check"]
    finally:
        server.shutdown()
