"""Dashboard media serving: mp4 under the same containment as PNGs.

The /visual route serves the produced short videos next to the
poster images. The structural containment is identical: only
media files directly under visuals/, and a symlink pointing
outside the data dir is refused.
"""
import http.client
import threading

from pageops.dashboard import render_board, serve
from pageops.store import Store

MP4_BYTES = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64
PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
)


def _start(store):
    server = serve(store, port=0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, server.server_address[1]


def _get(port, path):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        conn.request("GET", path)
        resp = conn.getresponse()
        body = resp.read()
        return resp.status, resp.getheader("Content-Type"), body
    finally:
        conn.close()


def _media_store(tmp_path):
    store = Store(tmp_path)
    visuals = store.data_dir / "visuals"
    visuals.mkdir(parents=True, exist_ok=True)
    (visuals / "video-3.mp4").write_bytes(MP4_BYTES)
    (visuals / "visual-3-poster.png").write_bytes(PNG_BYTES)
    (visuals / "notes.txt").write_bytes(b"not media")
    return store


def test_mp4_served_with_video_content_type(tmp_path):
    server, port = _start(_media_store(tmp_path))
    try:
        status, content_type, body = _get(port, "/visual/video-3.mp4")
        assert status == 200
        assert content_type == "video/mp4"
        assert body == MP4_BYTES
    finally:
        server.shutdown()


def test_png_still_served_as_image(tmp_path):
    server, port = _start(_media_store(tmp_path))
    try:
        status, content_type, body = _get(port, "/visual/visual-3-poster.png")
        assert status == 200
        assert content_type == "image/png"
        assert body == PNG_BYTES
    finally:
        server.shutdown()


def test_non_media_extension_refused(tmp_path):
    server, port = _start(_media_store(tmp_path))
    try:
        status, _, _ = _get(port, "/visual/notes.txt")
        assert status == 404
    finally:
        server.shutdown()


def test_traversal_refused(tmp_path):
    store = _media_store(tmp_path)
    (tmp_path / "secret.mp4").write_bytes(MP4_BYTES)
    server, port = _start(store)
    try:
        status, _, _ = _get(port, "/visual/..%2Fsecret.mp4")
        assert status == 404
        status, _, _ = _get(port, "/visual/%2E%2E%2Fsecret.mp4")
        assert status == 404
    finally:
        server.shutdown()


def test_symlink_escape_refused(tmp_path):
    store = _media_store(tmp_path)
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(MP4_BYTES)
    (store.data_dir / "visuals" / "escape.mp4").symlink_to(outside)
    server, port = _start(store)
    try:
        status, _, _ = _get(port, "/visual/escape.mp4")
        assert status == 404
    finally:
        server.shutdown()


def test_card_shows_video_link(tmp_path):
    store = Store(tmp_path)
    store.add_plan_row(
        {
            "platform": "facebook",
            "topic": "A short video post",
            "format": "Short video",
            "status": "awaiting_approval",
            "visual": "visuals/visual-9-poster.png",
            "video": "visuals/video-9.mp4",
        }
    )
    page = render_board(store)
    assert 'href="/visual/video-9.mp4"' in page
    assert "Video:" in page


def test_card_without_video_has_no_video_link(tmp_path):
    store = Store(tmp_path)
    store.add_plan_row(
        {"platform": "facebook", "topic": "Plain poster", "status": "awaiting_approval"}
    )
    page = render_board(store)
    assert "Video:" not in page
