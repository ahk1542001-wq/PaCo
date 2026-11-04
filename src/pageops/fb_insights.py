"""Facebook Page insights pull (Graph API -> the PaCo store).

The Analyst's instruments read the `insights` and `metrics` datasets.
Until now those rows only arrived by manual ingest. This module pulls
them from the Facebook Graph API: a page snapshot (followers), the
latest daily page insight values (views, engagements), and per-post
reach/engagement/clicks for recent posts, mapped onto the exact
dataset shapes the rest of the product already consumes.

Honesty rules, same as everywhere in PaCo: a metric the API does not
return stays blank, never estimated; a Graph error raises GraphError
with the API's own message; nothing here runs without a page access
token, which is connect-day material (a Meta app + Page token), so
configuration resolves from the environment or brand data and the
pull script refuses clearly when it is absent.
"""

from __future__ import annotations

import os

import httpx

from .metrics import import_metrics

GRAPH_BASE = "https://graph.facebook.com/v21.0"


class GraphError(Exception):
    """The Graph API refused or failed; carries its own message."""


class GraphClient:
    """Minimal Graph API GET client (token auth, injectable transport)."""

    def __init__(self, token: str, transport: httpx.BaseTransport | None = None,
                 base: str = GRAPH_BASE):
        self._token = token
        self._transport = transport
        self._base = base.rstrip("/")

    def get(self, path: str, **params) -> dict:
        params["access_token"] = self._token
        with httpx.Client(transport=self._transport, timeout=30) as client:
            response = client.get(f"{self._base}/{path.lstrip('/')}", params=params)
        try:
            payload = response.json()
        except ValueError:
            raise GraphError(f"Graph API returned non-JSON (HTTP {response.status_code})")
        if response.status_code >= 400 or "error" in payload:
            err = payload.get("error", {})
            raise GraphError(
                f"Graph API error: {err.get('message', response.status_code)}"
            )
        return payload


def page_followers(client: GraphClient, page_id: str) -> str:
    """Current follower count for the page ('' when the API omits it)."""
    payload = client.get(page_id, fields="followers_count,fan_count")
    value = payload.get("followers_count", payload.get("fan_count", ""))
    return str(value) if value != "" else ""


def page_insight_values(client: GraphClient, page_id: str) -> dict[str, str]:
    """Latest daily value per requested page insight metric.

    Only metrics the API actually returns appear in the result; the
    caller leaves the rest blank rather than guessing.
    """
    payload = client.get(
        f"{page_id}/insights",
        metric="page_views_total,page_post_engagements",
        period="day",
    )
    values: dict[str, str] = {}
    for series in payload.get("data", []):
        points = series.get("values", [])
        if points:
            values[series["name"]] = str(points[-1].get("value", ""))
    return values


def recent_post_rows(client: GraphClient, page_id: str, limit: int = 25) -> list[dict]:
    """Recent posts mapped to metrics-dataset rows via post insights."""
    payload = client.get(f"{page_id}/posts", fields="id,created_time", limit=limit)
    rows: list[dict] = []
    for post in payload.get("data", []):
        post_id = post.get("id", "")
        if not post_id:
            continue
        insights = client.get(
            f"{post_id}/insights",
            metric="post_impressions,post_engaged_users,post_clicks",
        )
        by_metric = {
            entry["name"]: str((entry.get("values") or [{}])[0].get("value", ""))
            for entry in insights.get("data", [])
        }
        rows.append(
            {
                "date": (post.get("created_time", "") or "")[:10],
                "platform": "facebook",
                "post_id": post_id,
                "reach": by_metric.get("post_impressions", ""),
                "engagement": by_metric.get("post_engaged_users", ""),
                "clicks": by_metric.get("post_clicks", ""),
                "notes": "Pulled from Facebook Graph API",
            }
        )
    return rows


def pull_insights(store, client: GraphClient, page_id: str, today: str) -> dict:
    """Pull page + post insights into the store. Returns a summary.

    The insights row for `today` is replaced on a re-pull (one row per
    period end); metrics rows go through import_metrics, which
    dedupes on (post_id, date) and updates numbers in place.
    """
    followers = page_followers(client, page_id)
    values = page_insight_values(client, page_id)
    insight_row = {
        "period_end": today,
        "followers": followers,
        "views": values.get("page_views_total", ""),
        "unique_viewers": "",
        "engagements": values.get("page_post_engagements", ""),
        "profile_visits": "",
        "new_followers": "",
        "unfollowers": "",
    }
    existing = [r for r in store.read_dataset("insights") if r.get("period_end") != today]
    store.write_dataset("insights", existing + [insight_row])

    post_rows = recent_post_rows(client, page_id)
    added = import_metrics(store, post_rows)
    return {
        "period_end": today,
        "followers": followers,
        "posts_seen": len(post_rows),
        "metrics_added": added,
    }


def resolve_fb_config(store) -> tuple[str, str]:
    """(page_id, token) from the environment first, then brand data.

    Both default to "" — an unconfigured pull is a clear refusal at
    the script layer, never a silent no-op.
    """
    brand = {r["key"]: r["value"] for r in store.read_dataset("brand_voice")}
    page_id = os.environ.get("PAGEOPS_FB_PAGE_ID", "") or brand.get("fb_page_id", "")
    token = os.environ.get("PAGEOPS_FB_TOKEN", "") or brand.get("fb_access_token", "")
    return page_id.strip(), token.strip()
