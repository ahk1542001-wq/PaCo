import pytest

from pageops.scheduler import PostizClient, schedule_item
from pageops.store import Store


def _row(store, status):
    return store.add_plan_row(
        {"platform": "facebook", "topic": "Post", "status": status}
    )


def test_unapproved_item_cannot_be_scheduled(tmp_path):
    store = Store(tmp_path)
    row = _row(store, "awaiting_approval")
    with pytest.raises(PermissionError):
        schedule_item(store, row["id"], PostizClient())


def test_planned_item_cannot_be_scheduled(tmp_path):
    store = Store(tmp_path)
    row = _row(store, "planned")
    with pytest.raises(PermissionError):
        schedule_item(store, row["id"], PostizClient())


def test_approved_item_schedules_in_dry_run(tmp_path):
    store = Store(tmp_path)
    row = _row(store, "approved")
    updated = schedule_item(store, row["id"], PostizClient())
    assert updated["status"] == "scheduled"
    assert updated["buffer_id"] == f"dry-run-{row['id']}"
