"""One-way sync from the CSV store to the Google Sheets mirror.

The CSV store is the working state; this module pushes the same three
datasets into the "PageOps Agent" spreadsheet (tabs: Brand Voice, Plan,
Metrics) so the Sheets view always matches the board. Shaping is pure
and tested; the push shells out to the Sheets connector CLI.
"""

from __future__ import annotations

import json
import subprocess

from .store import DATASETS, Store

SPREADSHEET_ID = "1VGhgw2pj-aW5gh2aeUGEhaD-ERy0FdZ4ReFKybthlKA"
TAB_NAMES = {"brand_voice": "Brand Voice", "plan": "Plan", "metrics": "Metrics", "insights": "Insights", "variants": "Variants", "brand_build": "Brand Build", "research": "Research", "notifications": "Notifications", "chat_log": "Chat Log"}
CLI = "/opt/hatch/bin/hatch_gws_cli"


def dataset_values(store: Store, dataset: str) -> list[list[str]]:
    """Header + rows for one dataset, in schema field order."""
    fields = DATASETS[dataset]
    rows = store.read_dataset(dataset)
    return [fields] + [[row.get(f, "") for f in fields] for row in rows]


def push_dataset(store: Store, dataset: str, spreadsheet_id: str = SPREADSHEET_ID) -> None:
    values = dataset_values(store, dataset)
    params = {
        "spreadsheetId": spreadsheet_id,
        "range": f"{TAB_NAMES[dataset]}!A1",
        "valueInputOption": "RAW",
    }
    result = subprocess.run(
        [
            CLI, "sheets", "spreadsheets", "values", "update",
            "--params", json.dumps(params),
            "--json", json.dumps({"values": values}),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Sheets push failed for {dataset}: {result.stderr.strip()}")


def sync_all(store: Store, spreadsheet_id: str = SPREADSHEET_ID) -> list[str]:
    pushed = []
    for dataset in DATASETS:
        push_dataset(store, dataset, spreadsheet_id)
        pushed.append(dataset)
    return pushed


if __name__ == "__main__":
    from .config import get_settings

    store = Store(get_settings().data_dir)
    print("Pushed to Sheets:", ", ".join(sync_all(store)))
