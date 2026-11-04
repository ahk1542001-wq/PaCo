"""Scheduling gate for PageOps Agent.

The one rule that matters: an item can be scheduled ONLY when its status
is "approved" (a human clicked Approve on the dashboard). The gate lives
here, in the scheduling layer itself, not in the UI, so no caller can
bypass it.

Buffer runs in dry-run mode until the connection is made in the
product (owner's direction, 2026-11-04: real profiles connect in
the product, not outside it). Going live takes exactly two things,
both already in the product: a Buffer API key in the settings
(BUFFER_API_KEY) and each platform's Buffer profile id in the
brand data (buffer_channel_<platform>, editable in the dashboard
brand panel). With neither, scheduling records exactly what would
be sent and changes nothing outside the store. A live failure
raises and the item stays approved: it is never marked scheduled
on a failed send.
"""

from __future__ import annotations

from .store import Store

BUFFER_API_URL = "https://api.bufferapp.com/1/updates/create.json"


def _default_post(url, data):
    import httpx

    return httpx.post(url, data=data, timeout=30)


class BufferClient:
    """Buffer scheduling client. Dry-run unless a real key is provided."""

    def __init__(self, api_key: str | None = None, channels: dict | None = None, post=None):
        self.api_key = api_key or None
        self.channels = {str(k).lower(): v for k, v in (channels or {}).items()}
        self.dry_run = not self.api_key
        self._post = post or _default_post

    def schedule(self, item: dict) -> str:
        """Return the queue id for one approved item."""
        if self.dry_run:
            return f"dry-run-{item['id']}"
        platform = (item.get("platform") or "").lower()
        channel = self.channels.get(platform)
        if not channel:
            raise RuntimeError(
                f"No Buffer channel connected for platform {platform!r}: "
                f"add the platform's Buffer profile id as "
                f"buffer_channel_{platform} in the brand panel first."
            )
        payload = {
            "access_token": self.api_key,
            "text": item.get("draft", ""),
            "profile_ids[]": channel,
        }
        if item.get("scheduled_for"):
            payload["scheduled_at"] = item["scheduled_for"]
        try:
            resp = self._post(BUFFER_API_URL, payload)
            resp.raise_for_status()
            body = resp.json()
        except Exception as exc:
            raise RuntimeError(
                f"Buffer scheduling failed for item {item.get('id')}: {exc}"
            ) from exc
        updates = body.get("updates") or []
        update_id = str(updates[0].get("id") or "") if updates else ""
        if not body.get("success", False) or not update_id:
            raise RuntimeError(
                f"Buffer scheduling failed for item {item.get('id')}: "
                f"{body.get('message') or body}"
            )
        return update_id


def make_buffer_client(store: Store, settings=None) -> BufferClient:
    """Build the client from the product's own connection data:
    the API key from settings, the per-platform channels from the
    brand data. This is the ready-to-connect seam: filling those
    two in is the whole connection step."""
    if settings is None:
        from .config import get_settings

        settings = get_settings()
    channels = store.get_brand_voice().get("buffer_channels", {})
    return BufferClient(api_key=settings.buffer_api_key, channels=channels)


def schedule_item(store: Store, item_id: str, buffer_client: BufferClient) -> dict:
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
    queue_id = buffer_client.schedule(row)
    return store.update_row(
        "plan", row["id"], {"status": "scheduled", "buffer_id": queue_id}
    )
