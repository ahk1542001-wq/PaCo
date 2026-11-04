"""Graph API insights pull: mapping, dedupe and failure honesty.

All traffic is a MockTransport playing recorded Graph-shaped payloads;
the live pull needs a Page access token (connect-day) and is not
exercised here - what is proven is that IF the API answers like this,
the store receives exactly these rows, and that API errors surface.
"""

import httpx
import pytest

from pageops.fb_insights import (
    GraphClient,
    GraphError,
    pull_insights,
    resolve_fb_config,
)
from pageops.store import Store

PAGE = "736610266201296"


def _transport():
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith(f"/{PAGE}"):
            return httpx.Response(200, json={"followers_count": 21, "fan_count": 21})
        if path.endswith(f"/{PAGE}/insights"):
            return httpx.Response(200, json={"data": [
                {"name": "page_views_total", "values": [{"value": 40}, {"value": 55}]},
                {"name": "page_post_engagements", "values": [{"value": 9}]},
            ]})
        if path.endswith(f"/{PAGE}/posts"):
            return httpx.Response(200, json={"data": [
                {"id": f"{PAGE}_111", "created_time": "2026-11-02T12:00:00+0000"},
                {"id": f"{PAGE}_222", "created_time": "2026-11-03T12:00:00+0000"},
            ]})
        if path.endswith("_111/insights"):
            return httpx.Response(200, json={"data": [
                {"name": "post_impressions", "values": [{"value": 300}]},
                {"name": "post_engaged_users", "values": [{"value": 41}]},
                {"name": "post_clicks", "values": [{"value": 7}]},
            ]})
        if path.endswith("_222/insights"):
            return httpx.Response(200, json={"data": [
                {"name": "post_impressions", "values": [{"value": 120}]},
            ]})
        return httpx.Response(404, json={"error": {"message": "unknown path"}})

    return httpx.MockTransport(handler)


def test_pull_maps_graph_payloads_into_the_store(tmp_path):
    store = Store(tmp_path)
    client = GraphClient("token", transport=_transport())
    summary = pull_insights(store, client, PAGE, "2026-11-05")
    assert summary == {
        "period_end": "2026-11-05",
        "followers": "21",
        "posts_seen": 2,
        "metrics_added": 2,
    }
    insights = store.read_dataset("insights")
    assert len(insights) == 1
    row = insights[0]
    assert row["followers"] == "21"
    assert row["views"] == "55"  # latest daily value, not the first
    assert row["engagements"] == "9"
    assert row["unique_viewers"] == ""  # not returned -> stays blank
    metrics = store.read_dataset("metrics")
    by_id = {r["post_id"]: r for r in metrics}
    assert by_id[f"{PAGE}_111"]["reach"] == "300"
    assert by_id[f"{PAGE}_111"]["engagement"] == "41"
    assert by_id[f"{PAGE}_111"]["date"] == "2026-11-02"
    assert by_id[f"{PAGE}_222"]["reach"] == "120"
    assert by_id[f"{PAGE}_222"]["clicks"] == ""  # metric absent -> blank


def test_repull_same_day_replaces_insights_and_dedupes_metrics(tmp_path):
    store = Store(tmp_path)
    client = GraphClient("token", transport=_transport())
    pull_insights(store, client, PAGE, "2026-11-05")
    summary = pull_insights(store, client, PAGE, "2026-11-05")
    assert summary["metrics_added"] == 0
    assert len(store.read_dataset("insights")) == 1
    assert len(store.read_dataset("metrics")) == 2


def test_graph_error_raises_with_the_api_message():
    def handler(request):
        return httpx.Response(400, json={"error": {"message": "Invalid OAuth access token"}})

    client = GraphClient("bad", transport=httpx.MockTransport(handler))
    with pytest.raises(GraphError, match="Invalid OAuth access token"):
        client.get(PAGE, fields="fan_count")


def test_resolve_config_prefers_env_then_brand(tmp_path, monkeypatch):
    store = Store(tmp_path)
    store.write_dataset("brand_voice", [
        {"key": "fb_page_id", "value": "brand-page"},
        {"key": "fb_access_token", "value": "brand-token"},
    ])
    monkeypatch.delenv("PAGEOPS_FB_PAGE_ID", raising=False)
    monkeypatch.delenv("PAGEOPS_FB_TOKEN", raising=False)
    assert resolve_fb_config(store) == ("brand-page", "brand-token")
    monkeypatch.setenv("PAGEOPS_FB_PAGE_ID", "env-page")
    monkeypatch.setenv("PAGEOPS_FB_TOKEN", "env-token")
    assert resolve_fb_config(store) == ("env-page", "env-token")


def test_resolve_config_empty_when_unconfigured(tmp_path, monkeypatch):
    monkeypatch.delenv("PAGEOPS_FB_PAGE_ID", raising=False)
    monkeypatch.delenv("PAGEOPS_FB_TOKEN", raising=False)
    assert resolve_fb_config(Store(tmp_path)) == ("", "")
