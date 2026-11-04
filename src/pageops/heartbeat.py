"""Heartbeat scheduling and owner notifications.

The weekly heartbeat (scripts/run_cycle.py) prepares one cycle and
stops at the human approval gate. Until now nothing fired it: a
person had to remember to run it. This module carries the schedule
inside the product:

  - The schedule is brand data (opt-in, like the other brand
    switches): heartbeat_weekday (0 = Monday), heartbeat_time
    ("HH:MM") and heartbeat_timezone (IANA name, default
    Asia/Bangkok). No schedule set means the heartbeat is never due.
  - heartbeat_due() compares the most recent scheduled moment with
    the last recorded run, so a missed week is caught up once, not
    replayed.
  - Notifications are a store dataset: when a cycle leaves work at
    the approval gate, one notification waits for the owner. An
    identical unread notification is never duplicated, so an hourly
    tick cannot spam the owner about the same waiting gate.

Firing itself stays outside this module: a cron line (see
deploy/paco-heartbeat.cron) runs the heartbeat entry point with
--if-due, and the entry point asks heartbeat_due() before doing
anything. The gate stays manual either way: nothing here approves,
rejects or schedules a post.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

STATE_NAME = "heartbeat_state.json"


def _notes_dir(store) -> Path:
    notes = store.data_dir / "notes"
    notes.mkdir(parents=True, exist_ok=True)
    return notes


def _now() -> datetime:
    return datetime.now(timezone.utc)


# -- Schedule ---------------------------------------------------------------


def heartbeat_config(store) -> dict | None:
    """The configured heartbeat schedule, or None when not set.

    Opt-in by brand data: both heartbeat_weekday and heartbeat_time
    must be present and valid before any schedule exists.
    """
    raw = {row["key"]: row["value"] for row in store.read_dataset("brand_voice")}
    weekday_raw = raw.get("heartbeat_weekday", "").strip()
    time_raw = raw.get("heartbeat_time", "").strip()
    if not weekday_raw or not time_raw:
        return None
    try:
        weekday = int(weekday_raw)
    except ValueError:
        return None
    if not 0 <= weekday <= 6:
        return None
    match = re.match(r"^(\d{1,2}):(\d{2})$", time_raw)
    if not match:
        return None
    hour, minute = int(match.group(1)), int(match.group(2))
    if hour > 23 or minute > 59:
        return None
    tz_name = raw.get("heartbeat_timezone", "").strip() or "Asia/Bangkok"
    try:
        ZoneInfo(tz_name)
    except (KeyError, ValueError):
        return None
    return {
        "weekday": weekday,
        "hour": hour,
        "minute": minute,
        "timezone": tz_name,
    }


def _scheduled_moment(config: dict, now_local: datetime) -> datetime:
    """The most recent scheduled moment at or before now_local."""
    days_back = (now_local.weekday() - config["weekday"]) % 7
    moment = (now_local - timedelta(days=days_back)).replace(
        hour=config["hour"], minute=config["minute"], second=0, microsecond=0
    )
    if moment > now_local:
        moment -= timedelta(days=7)
    return moment


def last_run(store) -> datetime | None:
    """When the heartbeat last completed a cycle, if ever."""
    path = _notes_dir(store) / STATE_NAME
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return datetime.fromisoformat(data["last_run"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def record_run(store, when: datetime | None = None) -> None:
    """Record a completed heartbeat cycle (manual runs count too:
    a week the owner already prepared by hand is not owed twice)."""
    stamp = (when or _now()).astimezone(timezone.utc)
    path = _notes_dir(store) / STATE_NAME
    path.write_text(
        json.dumps({"last_run": stamp.isoformat(timespec="seconds")}),
        encoding="utf-8",
    )


def heartbeat_due(store, now: datetime | None = None) -> bool:
    """True when a scheduled moment has passed with no run since."""
    config = heartbeat_config(store)
    if config is None:
        return False
    tz = ZoneInfo(config["timezone"])
    now_local = (now or _now()).astimezone(tz)
    moment = _scheduled_moment(config, now_local)
    ran = last_run(store)
    if ran is None:
        return True
    return ran.astimezone(tz) < moment


def next_moment(store, now: datetime | None = None) -> datetime | None:
    """The next scheduled moment (for display), or None."""
    config = heartbeat_config(store)
    if config is None:
        return None
    tz = ZoneInfo(config["timezone"])
    now_local = (now or _now()).astimezone(tz)
    moment = _scheduled_moment(config, now_local)
    if moment <= now_local:
        moment += timedelta(days=7)
    return moment


def schedule_summary(store, now: datetime | None = None) -> str:
    """One human line describing the schedule state."""
    config = heartbeat_config(store)
    if config is None:
        return "Weekly heartbeat: not scheduled (set heartbeat_weekday and heartbeat_time in the brand data to enable it)."
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    base = (
        f"Weekly heartbeat: {days[config['weekday']]} "
        f"{config['hour']:02d}:{config['minute']:02d} {config['timezone']}."
    )
    ran = last_run(store)
    nxt = next_moment(store, now)
    last_txt = ran.astimezone(ZoneInfo(config["timezone"])).strftime("%Y-%m-%d %H:%M") if ran else "never"
    next_txt = nxt.strftime("%Y-%m-%d %H:%M") if nxt else "unknown"
    return f"{base} Last run: {last_txt}. Next due: {next_txt}."


# -- Notifications ------------------------------------------------------------


def notify(store, kind: str, message: str) -> dict | None:
    """Record one owner notification.

    Returns the new row, or None when an identical notification is
    already waiting unread (the same fact never notifies twice).
    """
    rows = store.read_dataset("notifications")
    for row in rows:
        if row["kind"] == kind and row["message"] == message and row["read"] != "yes":
            return None
    return store.append_row(
        "notifications",
        {
            "id": str(len(rows) + 1),
            "created": _now().isoformat(timespec="seconds"),
            "kind": kind,
            "message": message,
            "read": "",
        },
    )


def notify_gate_status(store) -> dict | None:
    """Notify the owner when work is waiting at the approval gate."""
    rows = store.read_dataset("plan")
    awaiting = [row for row in rows if row.get("status") == "awaiting_approval"]
    if not awaiting:
        return None
    return notify(
        store,
        "approval_pending",
        f"{len(awaiting)} item(s) are awaiting your approval on the dashboard.",
    )


def unread_notifications(store) -> list[dict]:
    return [row for row in store.read_dataset("notifications") if row["read"] != "yes"]


def mark_notifications_read(store) -> int:
    """Mark every notification read; returns how many changed."""
    rows = store.read_dataset("notifications")
    changed = 0
    for row in rows:
        if row["read"] != "yes":
            row["read"] = "yes"
            changed += 1
    if changed:
        store.write_dataset("notifications", rows)
    return changed
