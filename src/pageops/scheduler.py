"""Scheduling gate for PageOps Agent.

The one rule that matters: an item can be scheduled ONLY when its status
is "approved" (a human clicked Approve on the dashboard). The gate lives
here, in the scheduling layer itself, not in the UI, so no caller can
bypass it. Buffer runs in dry-run mode until a real API key is wired at
the Nov 3 step; dry-run records exactly what would be scheduled.
"""

from __future__ import annotations

from .store import Store


class BufferClient:
    """Buffer scheduling client. Dry-run unless a real key is provided."""

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or None
        self.dry_run = not self.api_key

    def schedule(self, item: dict) -> str:
        """Return the queue id for one approved item."""
        if self.dry_run:
            return f"dry-run-{item['id']}"
        raise RuntimeError(
            "Buffer live mode is not wired yet (Nov 3 step). "
            "Unset BUFFER_API_KEY to use dry-run mode."
        )


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
