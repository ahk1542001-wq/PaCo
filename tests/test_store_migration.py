"""Store schema migration: older data dirs gain new fields safely."""
import csv

from pageops.store import DATASETS, Store

OLD_PLAN_FIELDS = [f for f in DATASETS["plan"] if f != "visual"]


def test_old_plan_csv_gains_visual_column_and_keeps_rows(tmp_path):
    path = tmp_path / "plan.csv"
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=OLD_PLAN_FIELDS)
        writer.writeheader()
        writer.writerow(
            {f: "" for f in OLD_PLAN_FIELDS}
            | {"id": "7", "topic": "Legacy row", "status": "drafted"}
        )
    store = Store(tmp_path)  # opening the store migrates the header
    rows = store.read_dataset("plan")
    legacy = [r for r in rows if r["id"] == "7"][0]
    assert legacy["topic"] == "Legacy row"
    assert legacy["visual"] == ""
    with path.open(newline="", encoding="utf-8") as fh:
        header = next(csv.reader(fh))
    assert header == DATASETS["plan"]
