"""Dashboard UX layer (M22).

Board-level assertions for every kanban state: the right actions
on the right cards, and the gate visible in the UI itself - a
flagged (checked) card offers no Approve, an approved card is the
only one that can schedule, finished cards carry no forms.
"""
from pageops.dashboard import render_board
from pageops.store import Store


def _board_with(tmp_path, **rows):
    store = Store(tmp_path)
    for status, extra in rows.items():
        store.add_plan_row({"topic": f"Post {status}", "status": status, "draft": "D", **extra})
    return render_board(store)


def _column_section(board, title):
    """The HTML of one kanban column, heading to the next column."""
    marker = f"<h2>{title}"
    start = board.index(marker)
    nxt = board.find('<div class="col">', start)
    return board[start:] if nxt == -1 else board[start:nxt]


def test_every_state_renders_its_column(tmp_path):
    board = _board_with(
        tmp_path,
        brief_received={},
        planned={},
        drafted={},
        visual_ready={},
        checked={},
        awaiting_approval={},
        approved={},
        scheduled={},
        reported={},
        rejected={"reject_reason": "Off brand"},
    )
    # Column headings render even on an empty board, so the real
    # assertion is placement: each card's topic must land inside
    # its own column's section of the HTML.
    expected = {
        "brief_received": "Brief",
        "planned": "Planned",
        "drafted": "Drafted",
        "visual_ready": "Drafted",
        "checked": "Checked",
        "awaiting_approval": "Awaiting approval",
        "approved": "Awaiting approval",
        "scheduled": "Scheduled",
        "reported": "Reported",
        "rejected": "Awaiting approval",
    }
    for status, title in expected.items():
        assert f"Post {status}" in _column_section(board, title), status


def test_checked_card_offers_no_approve(tmp_path):
    board = _board_with(tmp_path, checked={})
    assert 'value="approve"' not in board
    # but the human can still fix or reject it from the board
    assert 'value="edit"' in board
    assert 'value="reject"' in board


def test_awaiting_card_separates_approve_and_reject(tmp_path):
    board = _board_with(tmp_path, awaiting_approval={})
    assert 'value="approve"' in board
    assert 'value="reject"' in board
    assert 'value="edit"' in board


def test_only_approved_cards_can_schedule(tmp_path):
    board = _board_with(tmp_path, approved={}, scheduled={}, reported={})
    assert board.count('value="schedule"') == 1


def test_brief_card_offers_run_only(tmp_path):
    board = _board_with(tmp_path, brief_received={"brief": "Goal: grow"})
    assert 'value="run"' in board
    assert 'value="approve"' not in board


def test_rejected_card_shows_its_reason(tmp_path):
    board = _board_with(tmp_path, rejected={"reject_reason": "Wrong audience"})
    assert "Rejected: Wrong audience" in board


def test_visual_column_holds_visual_ready_and_drafted(tmp_path):
    board = _board_with(tmp_path, visual_ready={"visual": "visuals/v.png"})
    assert "/visual/v.png" in board


def test_visual_route_serves_posters_and_blocks_traversal(tmp_path):
    import threading
    import urllib.error
    import urllib.request

    from pageops.dashboard import serve

    store = Store(tmp_path)
    (tmp_path / "visuals").mkdir(exist_ok=True)
    (tmp_path / "visuals" / "v.png").write_bytes(b"\x89PNG")
    server = serve(store, port=0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        with urllib.request.urlopen(base + "/visual/v.png", timeout=5) as resp:
            assert resp.status == 200
            assert resp.headers.get_content_type() == "image/png"
        for bad in ("/visual/..%2fstore.py", "/visual/missing.png", "/visual/x.jpg"):
            try:
                urllib.request.urlopen(base + bad, timeout=5)
                raise AssertionError(f"{bad} should 404")
            except urllib.error.HTTPError as exc:
                assert exc.code == 404
    finally:
        server.shutdown()



def test_visual_route_refuses_symlink_escape(tmp_path):
    import threading
    import urllib.error
    import urllib.request

    from pageops.dashboard import serve

    store = Store(tmp_path)
    outside = tmp_path / "secret.png"
    outside.write_bytes(b"PNG")
    visuals = tmp_path / "visuals"
    visuals.mkdir(parents=True, exist_ok=True)
    (visuals / "escape.png").symlink_to(outside)
    server = serve(store, port=0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        try:
            urllib.request.urlopen(base + "/visual/escape.png", timeout=5)
            raise AssertionError("symlink escape was served")
        except urllib.error.HTTPError as exc:
            assert exc.code == 404
    finally:
        server.shutdown()
