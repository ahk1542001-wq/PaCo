"""Operator ingest: pull published-post metrics into the store.

Reads a CSV whose header matches the metrics dataset (date,
platform, post_id, reach, engagement, clicks, notes) - for
example an export shaped from the page's insights - and imports
it through metrics.import_metrics, so re-running the same export
updates numbers instead of duplicating posts.

Usage:
    PYTHONPATH=src .venv/bin/python scripts/ingest_metrics.py export.csv
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pageops.config import get_settings  # noqa: E402
from pageops.metrics import import_metrics  # noqa: E402
from pageops.store import Store  # noqa: E402


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    with open(sys.argv[1], newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    store = Store(get_settings().data_dir)
    added = import_metrics(store, rows)
    print(f"imported {len(rows)} rows ({added} new) into {store.data_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
