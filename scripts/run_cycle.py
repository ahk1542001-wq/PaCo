"""Weekly heartbeat for PaCo: prepare one cycle, then stop at the gate.

The heartbeat reads a standing brief, runs the normal pipeline with
the same live wiring as the dashboard, and records a short summary.
It NEVER calls approve_item, reject_item, or schedule_approved: the
approval gate stays manual, and this entry point only prepares work
and reports that the gate is waiting.

Usage:
    PYTHONPATH=src .venv/bin/python scripts/run_cycle.py
    PYTHONPATH=src .venv/bin/python scripts/run_cycle.py --brief-file PATH
    PYTHONPATH=src .venv/bin/python scripts/run_cycle.py --if-due

With --if-due the cycle runs only when the configured heartbeat
schedule (brand data: heartbeat_weekday, heartbeat_time,
heartbeat_timezone) says a run is owed; a cron line fires it hourly
(see deploy/paco-heartbeat.cron). Every completed cycle records its
run and, when work waits at the gate, leaves the owner one
notification in the store (see pageops.heartbeat).

The standing brief defaults to standing-brief.txt inside the data
directory selected by PAGEOPS_DATA_DIR. PAGEOPS_BRIEF_FILE or the
--brief-file argument can point to a different brief file.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pageops.config import get_settings  # noqa: E402
from pageops.model_client import (  # noqa: E402
    MockClient,
    get_client,
    get_image_client,
    get_judge_client,
)
from pageops.heartbeat import (  # noqa: E402
    heartbeat_due,
    notify_gate_status,
    record_run,
)
from pageops.pipeline import process_week  # noqa: E402
from pageops.research import fetch_research  # noqa: E402
from pageops.store import Store  # noqa: E402


def _brief_path(settings, supplied: str | None) -> Path:
    raw = supplied or os.environ.get("PAGEOPS_BRIEF_FILE")
    if raw:
        return Path(raw).expanduser()
    return settings.data_dir / "standing-brief.txt"


def _read_brief(path: Path) -> str | None:
    try:
        brief = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return brief or None


def _summary(brief: str, rows: list[dict], *, gate_waiting: bool = False) -> str:
    counts = Counter((row.get("status") or "unknown") for row in rows)
    awaiting = counts.get("awaiting_approval", 0)
    lines = [
        "PaCo weekly cycle summary",
        f"Date: {datetime.now(timezone.utc).date().isoformat()}",
        f"Brief: {brief.splitlines()[0].strip()}",
        "Items by status:",
    ]
    if counts:
        lines.extend(f"- {status}: {counts[status]}" for status in sorted(counts))
    else:
        lines.append("- none: 0")
    lines.append(f"Items awaiting approval: {awaiting}")
    if gate_waiting:
        lines.append(
            "The gate is still waiting for the owner, so no new cycle was started."
        )
    else:
        lines.append("The approval gate remains manual on the dashboard.")
    return "\n".join(lines)


def _write_summary(store: Store, summary: str) -> None:
    notes = store.data_dir / "notes"
    notes.mkdir(parents=True, exist_ok=True)
    (notes / "last_cycle.txt").write_text(summary + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one PaCo weekly cycle")
    parser.add_argument(
        "--brief-file",
        help="Standing brief file (default: PAGEOPS_BRIEF_FILE or "
        "standing-brief.txt in the data directory)",
    )
    parser.add_argument(
        "--if-due",
        action="store_true",
        help="Run only when the configured heartbeat schedule is due",
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    brief_file = _brief_path(settings, args.brief_file)
    brief_text = _read_brief(brief_file)
    if brief_text is None:
        print(
            f"Standing brief file is missing or empty: {brief_file}. "
            "No cycle was run.",
            file=sys.stderr,
        )
        return 2

    store = Store(settings.data_dir)
    if args.if_due and not heartbeat_due(store):
        print("Heartbeat not due; no cycle was run.")
        return 0
    rows = store.read_dataset("plan")
    if any(row.get("status") == "awaiting_approval" for row in rows):
        notify_gate_status(store)
        print(_summary(brief_text, rows, gate_waiting=True))
        return 0

    client = get_client()
    # Live mode researches first (Agent-Reach web search, RSS
    # fallback); mock mode stays offline and hermetic, exactly as
    # the dashboard wires its Run action.
    fetcher = None if isinstance(client, MockClient) else fetch_research
    process_week(
        store,
        client,
        brief_text,
        trends_fetcher=fetcher,
        judge=get_judge_client(),
        image_client=get_image_client(),
    )
    summary = _summary(brief_text, store.read_dataset("plan"))
    _write_summary(store, summary)
    record_run(store)
    notify_gate_status(store)
    print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
