import threading
import urllib.request

from pageops.dashboard import render_board, serve
from pageops.store import Store


def _seeded_store(tmp_path):
    store = Store(tmp_path)
    store.add_plan_row(
        {"platform": "Facebook", "topic": "Chatbot launch post", "status": "brief_received"}
    )
    store.add_plan_row(
        {"platform": "Facebook", "topic": "CRM follow-up tips", "status": "awaiting_approval"}
    )
    return store


def test_render_contains_columns_and_cards(tmp_path):
    page = render_board(_seeded_store(tmp_path))
    for column in ("Brief", "Planned", "Awaiting approval", "Scheduled", "Reported"):
        assert column in page
    assert "Chatbot launch post" in page
    assert "CRM follow-up tips" in page
    assert "FYF AI" in page  # brand voice seed reaches the header/panel


def test_render_escapes_html_and_handles_unknown_status(tmp_path):
    store = Store(tmp_path)
    store.add_plan_row({"topic": "<script>alert(1)</script>", "status": "mystery_state"})
    page = render_board(store)
    assert "<script>alert(1)</script>" not in page
    assert "mystery_state" in page  # raw status still visible on the card


def test_http_server_serves_board(tmp_path):
    server = serve(_seeded_store(tmp_path), port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/"
        with urllib.request.urlopen(url, timeout=5) as resp:
            body = resp.read().decode("utf-8")
        assert resp.status == 200
        assert "Chatbot launch post" in body
    finally:
        server.shutdown()
