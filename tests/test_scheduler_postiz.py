"""Postiz publishing (owner's decisions, 2026-11-04): Buffer's
free tier caps at 3 channels and 5 would cost money, so the live
target is Postiz, open-source and self-hosted. Each platform
connects one by one IN the product (its Postiz integration id as
brand data) and each has its own on/off toggle: a connected
platform is on unless postiz_enabled_<platform> is off, and a
switched-off platform refuses scheduling with the item left
approved. The HTTP layer is faked here; the real send is
verified when the owner connects his instance.
"""
import pytest

from pageops.config import Settings
from pageops.pipeline import update_brand_voice
from pageops.scheduler import PostizClient, make_postiz_client, schedule_item
from pageops.store import Store

CHANNELS = {
    "facebook": {"integration": "int-fb", "enabled": True},
    "tiktok": {"integration": "int-tt", "enabled": False},
}


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
    return store.add_plan_row(
        {"platform": platform, "topic": "T", "draft": "Caption text", "status": "approved"}
    )


def test_live_schedule_posts_to_the_platform_integration(tmp_path):
    store = Store(tmp_path)
    row = _approved(store)
    calls = []

    def fake_post(url, json_body, headers):
        calls.append((url, json_body, headers))
        return FakeResponse([{"id": "pz-1"}])

    client = PostizClient("KEY", "https://postiz.example.com/api", CHANNELS, post=fake_post)
    updated = schedule_item(store, row["id"], client)
    assert updated["status"] == "scheduled"
    assert updated["buffer_id"] == "pz-1"
    url, body, headers = calls[0]
    assert url == "https://postiz.example.com/api/public/v1/posts"
    assert headers["Authorization"] == "KEY"
    post = body["posts"][0]
    assert post["integration"]["id"] == "int-fb"
    assert post["value"][0]["content"] == "Caption text"
    assert post["settings"]["__type"] == "facebook"


def test_switched_off_platform_refuses_and_stays_approved(tmp_path):
    store = Store(tmp_path)
    row = _approved(store, platform="tiktok")
    client = PostizClient("KEY", "https://postiz.example.com/api", CHANNELS, post=lambda u, b, h: FakeResponse([]))
    with pytest.raises(RuntimeError, match="switched off"):
        schedule_item(store, row["id"], client)
    assert store.read_dataset("plan")[0]["status"] == "approved"


def test_unconnected_platform_raises_and_stays_approved(tmp_path):
    store = Store(tmp_path)
    row = _approved(store, platform="x")
    client = PostizClient("KEY", "https://postiz.example.com/api", CHANNELS, post=lambda u, b, h: FakeResponse([]))
    with pytest.raises(RuntimeError, match="postiz_integration_x"):
        schedule_item(store, row["id"], client)
    assert store.read_dataset("plan")[0]["status"] == "approved"


def test_http_failure_raises_and_stays_approved(tmp_path):
    store = Store(tmp_path)
    row = _approved(store)
    client = PostizClient(
        "KEY", "https://postiz.example.com/api", CHANNELS,
        post=lambda u, b, h: FakeResponse({}, ok=False),
    )
    with pytest.raises(RuntimeError, match="Postiz scheduling failed"):
        schedule_item(store, row["id"], client)
    assert store.read_dataset("plan")[0]["status"] == "approved"


def test_make_postiz_client_reads_connection_data_and_toggles(tmp_path):
    store = Store(tmp_path)
    update_brand_voice(store, "postiz_integration_facebook", "int-fb")
    update_brand_voice(store, "postiz_integration_tiktok", "int-tt")
    update_brand_voice(store, "postiz_enabled_tiktok", "off")
    live = make_postiz_client(
        store, Settings(postiz_api_key="KEY", postiz_base_url="https://postiz.example.com/api")
    )
    assert live.dry_run is False
    assert live.channels["facebook"] == {"integration": "int-fb", "enabled": True}
    assert live.channels["tiktok"] == {"integration": "int-tt", "enabled": False}
    dry = make_postiz_client(store, Settings())
    assert dry.dry_run is True
    assert dry.schedule({"id": "9"}) == "dry-run-9"
