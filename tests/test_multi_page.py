"""Multi-page dashboard (one process, several page stores).

The registry discovers data-* store dirs beside the launch
store, the switcher moves every route to the active store, and
the selection persists server-side. Single-store behaviour is
covered by the existing suite; these tests pin the multi-store
properties: discovery, switch isolation, create-page seeding,
unknown-store refusal, and state persistence.
"""
import threading
import urllib.error
import urllib.parse
import urllib.request

from pageops.dashboard import render_board, serve
from pageops.store import Store
from pageops.stores import StoreRegistry

STATE_FILE = ".paco-dashboard-state.json"


def _make_store(tmp_path, dirname, brand):
    store = Store(tmp_path / dirname)
    store.set_brand_value("brand_name", brand)
    return store


def _start(store):
    server = serve(store, port=0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def _post(url, data):
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    try:
        with _OPENER.open(req, timeout=10) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code


def _get(url):
    with urllib.request.urlopen(url, timeout=10) as resp:
        return resp.read().decode("utf-8")


def test_discovery_launch_first_and_only_real_stores(tmp_path):
    alpha = _make_store(tmp_path, "data-alpha", "Alpha")
    _make_store(tmp_path, "data-beta", "Beta")
    (tmp_path / "data-empty").mkdir()
    (tmp_path / "random-dir").mkdir()
    registry = StoreRegistry(alpha)
    assert registry.discover() == ["data-alpha", "data-beta"]
    pages = {p["name"]: p for p in registry.pages()}
    assert pages["data-alpha"]["label"] == "Alpha"
    assert pages["data-beta"]["label"] == "Beta"
    assert pages["data-alpha"]["active"] is True
    assert pages["data-beta"]["active"] is False


def test_switch_isolation_chat_and_plan_writes(tmp_path):
    alpha = _make_store(tmp_path, "data-alpha", "Alpha")
    _make_store(tmp_path, "data-beta", "Beta")
    server, base = _start(alpha)
    try:
        assert "Alpha" in _get(base + "/")
        assert _post(base + "/chat", {"message": "status"}) == 303
        assert Store(tmp_path / "data-alpha").read_dataset("chat_log")
        assert Store(tmp_path / "data-beta").read_dataset("chat_log") == []

        assert _post(base + "/switch-store", {"store": "data-beta"}) == 303
        assert "Beta" in _get(base + "/")
        assert _post(base + "/brief", {"goal": "Sell more"}) == 303
        beta_plan = Store(tmp_path / "data-beta").read_dataset("plan")
        assert any(r["status"] == "brief_received" for r in beta_plan)
        alpha_plan = Store(tmp_path / "data-alpha").read_dataset("plan")
        assert not any(r["status"] == "brief_received" for r in alpha_plan)
    finally:
        server.shutdown()


def test_unknown_store_switch_is_refused(tmp_path):
    alpha = _make_store(tmp_path, "data-alpha", "Alpha")
    _make_store(tmp_path, "data-beta", "Beta")
    server, base = _start(alpha)
    try:
        assert _post(base + "/switch-store", {"store": "data-nope"}) == 400
        assert "Alpha" in _get(base + "/")
    finally:
        server.shutdown()


def test_create_page_seeds_and_switches(tmp_path):
    alpha = _make_store(tmp_path, "data-alpha", "Alpha")
    server, base = _start(alpha)
    try:
        assert _post(base + "/create-page", {"name": "Gamma Page"}) == 303
        created = tmp_path / "data-gamma-page"
        assert (created / "brand_voice.csv").exists()
        assert (created / "plan.csv").exists()
        store = Store(created)
        assert store.get_brand_voice()["brand_name"] == "Gamma Page"
        assert "Gamma Page" in _get(base + "/")
        assert (tmp_path / STATE_FILE).exists()
    finally:
        server.shutdown()


def test_selection_persists_across_registry_instances(tmp_path):
    alpha = _make_store(tmp_path, "data-alpha", "Alpha")
    _make_store(tmp_path, "data-beta", "Beta")
    registry = StoreRegistry(alpha)
    registry.switch("data-beta")
    fresh = StoreRegistry(Store(tmp_path / "data-alpha"))
    assert fresh.active_name() == "data-beta"
    assert fresh.active().get_brand_voice()["brand_name"] == "Beta"


def test_render_board_itself_has_no_switcher(tmp_path):
    store = _make_store(tmp_path, "data-alpha", "Alpha")
    board = render_board(store)
    assert "/switch-store" not in board
    assert "/create-page" not in board
