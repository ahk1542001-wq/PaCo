"""Context architecture mechanics: the private layer + the loop.

One shared store, three layers (see ARCHITECTURE.md). This module
owns the private layer's files inside the data directory:

  notes/strategist_trends.json  — the Strategist's trend snapshots
  notes/analyst_history.jsonl   — the Analyst's performance history

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


def save_trend_notes(store, trends: list[dict]) -> None:
    payload = {"saved_at": _now(), "items": trends}
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
        return ""
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if not lines:
        return ""
    last = json.loads(lines[-1])
    return (
        f"Last period: reach {last['reach']}, engagement {last['engagement']}, "
        f"clicks {last['clicks']} across {last['posts']} posts."
    )
