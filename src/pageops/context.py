"""Context architecture mechanics: the private layer + the loop.

One shared store, three layers (see ARCHITECTURE.md). This module
owns the private layer's files inside the data directory:

  notes/strategist_trends.json  - the Strategist's trend snapshots
  notes/analyst_history.jsonl   - the Analyst's performance history

and the long-term loop: the Analyst's history is summarised for the
Strategist's next plan. The store's write log (writes.log) lives in
store.py, next to the writes it records.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


def _notes_dir(store) -> Path:
    notes = store.data_dir / "notes"
    notes.mkdir(parents=True, exist_ok=True)
    return notes


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def save_trend_notes(store, trends: list[dict], source: dict | None = None) -> None:
    payload = {"saved_at": _now(), "items": trends}
    if source is not None:
        # Provenance is part of the snapshot: which research backend
        # produced these trends, and why, is never left implicit.
        payload["source"] = source
    (_notes_dir(store) / "strategist_trends.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
    )


def load_trend_notes(store) -> list[dict]:
    path = _notes_dir(store) / "strategist_trends.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8")).get("items", [])


def append_analyst_history(store, stats: dict) -> None:
    totals = stats.get("totals", {})
    entry = {
        "date": _now()[:10],
        "reach": totals.get("reach", 0),
        "engagement": totals.get("engagement", 0),
        "clicks": totals.get("clicks", 0),
        "posts": totals.get("posts", 0),
    }
    with (_notes_dir(store) / "analyst_history.jsonl").open(
        "a", encoding="utf-8"
    ) as fh:
        fh.write(json.dumps(entry) + "\n")


def latest_analyst_summary(store) -> str:
    path = _notes_dir(store) / "analyst_history.jsonl"
    if not path.exists():
        visibility = latest_visibility_summary(store)
        return f"Visibility audit: {visibility}" if visibility else ""
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if not lines:
        visibility = latest_visibility_summary(store)
        return f"Visibility audit: {visibility}" if visibility else ""
    last = json.loads(lines[-1])
    summary = (
        f"Last period: reach {last['reach']}, engagement {last['engagement']}, "
        f"clicks {last['clicks']} across {last['posts']} posts."
    )
    visibility = latest_visibility_summary(store)
    if visibility:
        summary += f" Visibility audit: {visibility}"
    return summary


def save_last_report(store, narrative: str) -> None:
    """Persist the latest recorded report narrative (Analyst layer)."""
    path = store.data_dir / "notes" / "last_report.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(narrative, encoding="utf-8")


def save_last_visibility(store, text: str) -> None:
    """Persist the latest visibility audit (Analyst layer)."""
    path = store.data_dir / "notes" / "last_visibility.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def load_last_visibility(store) -> str:
    """The latest recorded visibility audit, or "" if none ran yet."""
    path = store.data_dir / "notes" / "last_visibility.txt"
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def append_visibility_history(store, summary: str) -> None:
    entry = {"date": _now()[:10], "summary": summary}
    with (_notes_dir(store) / "visibility_history.jsonl").open(
        "a", encoding="utf-8"
    ) as fh:
        fh.write(json.dumps(entry) + "\n")


def latest_visibility_summary(store) -> str:
    path = _notes_dir(store) / "visibility_history.jsonl"
    if not path.exists():
        return ""
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if not lines:
        return ""
    return json.loads(lines[-1]).get("summary", "")


def load_last_report(store) -> str:
    """The latest recorded report narrative, or "" if none ran yet."""
    path = store.data_dir / "notes" / "last_report.txt"
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")
