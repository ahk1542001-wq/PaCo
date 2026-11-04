"""Scheduling gate for PageOps Agent.

The one rule that matters: an item can be scheduled ONLY when its status
is "approved" (a human clicked Approve on the dashboard). The gate lives
here, in the scheduling layer itself, not in the UI, so no caller can
bypass it.

Publishing runs through Postiz (owner's decision, 2026-11-04):
open-source and self-hosted on the owner's own VM, so no
per-channel fees, and every platform connects in the product, one
by one, each with its own on/off toggle. (Buffer was the earlier
placeholder seam; its free tier caps at 3 channels and 5 would
cost real money, so the live target moved. The store column that
holds the returned queue id is still called buffer_id for schema
stability.)

Dry-run until the connection is made in the product: live takes a
Postiz base URL and API key in the settings (POSTIZ_BASE_URL,
POSTIZ_API_KEY) plus each platform's Postiz integration id in the
brand data (postiz_integration_<platform>, editable in the
dashboard brand panel). A connected platform is ON unless its
postiz_enabled_<platform> toggle is set to off; a switched-off
platform refuses scheduling with a clear reason and the item
stays approved. Any live failure raises and the item stays
approved: it is never marked scheduled on a failed send.
"""

from __future__ import annotations

from .store import Store


def _default_post(url, json_body, headers):
    import httpx

    return httpx.post(url, json=json_body, headers=headers, timeout=30)


class PostizClient:
    """Postiz scheduling client. Dry-run unless URL and key are set."""

    def __init__(self, api_key=None, base_url=None, channels=None, post=None):
        self.api_key = api_key or None
        self.base_url = (base_url or "").rstrip("/")
        self.channels = channels or {}
        self.dry_run = not (self.api_key and self.base_url)
        self._post = post or _default_post

    def schedule(self, item: dict) -> str:
        """Return the queue id for one approved item."""
        if self.dry_run:
            return f"dry-run-{item['id']}"
        platform = (item.get("platform") or "").lower()
        entry = self.channels.get(platform) or {}
        integration = entry.get("integration")
        if not integration:
            raise RuntimeError(
                f"No Postiz channel connected for platform {platform!r}: "
                f"connect it in Postiz, then add its integration id as "
                f"postiz_integration_{platform} in the brand panel."
            )
        if not entry.get("enabled", True):
            raise RuntimeError(
                f"Platform {platform!r} is switched off in the product "
                f"(postiz_enabled_{platform}); the item stays approved "
                f"and nothing was sent."
            )
        body = {
            "type": "schedule" if item.get("scheduled_for") else "now",
            "shortLink": True,
            "tags": [],
            "posts": [
                {
                    "integration": {"id": integration},
                    "value": [{"content": item.get("draft", ""), "image": []}],
                    "settings": {"__type": platform},
                }
            ],
        }
        if item.get("scheduled_for"):
            body["date"] = item["scheduled_for"]
        try:
            resp = self._post(
                f"{self.base_url}/public/v1/posts",
                body,
                {"Authorization": self.api_key},
            )
            resp.raise_for_status()
            payload = resp.json()
        except Exception as exc:
            raise RuntimeError(
                f"Postiz scheduling failed for item {item.get('id')}: {exc}"
            ) from exc
        post_id = ""
        if isinstance(payload, list) and payload and isinstance(payload[0], dict):
            post_id = str(payload[0].get("id") or "")
        elif isinstance(payload, dict):
            post_id = str(payload.get("id") or "")
        return post_id or "postiz-queued"


def make_postiz_client(store: Store, settings=None) -> PostizClient:
    """Build the client from the product's own connection data:
    the instance URL and API key from settings, the per-platform
    integrations and toggles from the brand data. Filling those in
    is the whole connection step."""
    if settings is None:
        from .config import get_settings

        settings = get_settings()
    channels = store.get_brand_voice().get("postiz_channels", {})
    return PostizClient(settings.postiz_api_key, settings.postiz_base_url, channels)


def schedule_item(store: Store, item_id: str, client: PostizClient) -> dict:
    """Schedule one item. Raises PermissionError unless it is approved."""
    rows = {r["id"]: r for r in store.read_dataset("plan")}
    row = rows.get(str(item_id))
    if row is None:
        raise KeyError(f"No plan row with id {item_id}")
    if row.get("status") != "approved":
        raise PermissionError(
            f"Plan item {item_id} has status {row.get('status')!r}; "
            "only 'approved' items can be scheduled."
        )
    queue_id = client.schedule(row)
    return store.update_row(
        "plan", row["id"], {"status": "scheduled", "buffer_id": queue_id}
    )
