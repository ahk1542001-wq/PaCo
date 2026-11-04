"""Ready-to-connect (owner's direction, 2026-11-04): real
profiles connect IN the product. Live Buffer scheduling is now
wired behind the product's own connection data: a Buffer API
key in settings plus each platform's Buffer profile id in the
brand data (buffer_channel_<platform>, editable in the brand
panel). Without them, scheduling stays a dry-run. A live failure
raises and the item stays approved: never marked scheduled on a
failed send. The HTTP layer is faked here; the real connection
is verified when the owner connects an account.
"""
import pytest

from pageops.config import Settings
from pageops.pipeline import update_brand_voice
from pageops.scheduler import BufferClient, make_buffer_client, schedule_item
from pageops.store import Store


class FakeResponse:
    def __init__(self, body, ok=True):
        self._body = body
        self._ok = ok

    def raise_for_status(self):
        if not self._ok:
            raise RuntimeError("400 Bad Request")

    def json(self):
        return self._body


def _approved(store, platform="facebook"):
    row = store.add_plan_row(
        {"platform": platform, "topic": "T", "draft": "Caption text", "status": "approved"}
    )
    return row


def test_live_schedule_posts_to_the_connected_channel(tmp_path):
    store = Store(tmp_path)
    row = _approved(store)
    calls = []

    def fake_post(url, data):
        calls.append((url, data))
        return FakeResponse({"success": True, "updates": [{"id": "buf-123"}]})

    client = BufferClient(api_key="KEY", channels={"facebook": "prof-fb"}, post=fake_post)
    updated = schedule_item(store, row["id"], client)
    assert updated["status"] == "scheduled"
    assert updated["buffer_id"] == "buf-123"
    url, data = calls[0]
    assert "updates/create" in url
    assert data["profile_ids[]"] == "prof-fb"
    assert data["text"] == "Caption text"
    assert data["access_token"] == "KEY"


def test_live_schedule_without_channel_raises_and_stays_approved(tmp_path):
    store = Store(tmp_path)
    row = _approved(store, platform="tiktok")
    client = BufferClient(api_key="KEY", channels={"facebook": "prof-fb"}, post=lambda u, d: FakeResponse({}))
    with pytest.raises(RuntimeError, match="buffer_channel_tiktok"):
        schedule_item(store, row["id"], client)
    assert store.read_dataset("plan")[0]["status"] == "approved"


def test_live_http_failure_raises_and_stays_approved(tmp_path):
    store = Store(tmp_path)
    row = _approved(store)
    client = BufferClient(
        api_key="KEY",
        channels={"facebook": "prof-fb"},
        post=lambda u, d: FakeResponse({}, ok=False),
    )
    with pytest.raises(RuntimeError, match="Buffer scheduling failed"):
        schedule_item(store, row["id"], client)
    assert store.read_dataset("plan")[0]["status"] == "approved"


def test_make_buffer_client_reads_the_product_connection_data(tmp_path):
    store = Store(tmp_path)
    update_brand_voice(store, "buffer_channel_facebook", "prof-fb")
    live = make_buffer_client(store, Settings(buffer_api_key="KEY"))
    assert live.dry_run is False
    assert live.channels == {"facebook": "prof-fb"}
    dry = make_buffer_client(store, Settings())
    assert dry.dry_run is True
    assert dry.schedule({"id": "9"}) == "dry-run-9"
