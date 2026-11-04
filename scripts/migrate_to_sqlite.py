"""Migrate a CSV data directory to a SQLite store directory.

Usage: python scripts/migrate_to_sqlite.py <csv-dir> <sqlite-dir>

Copies every dataset row-for-row into paco.db in the target
directory (created fresh; the source is never touched), carries the
writes.log audit file across, then VERIFIES: both stores are read
back and compared exactly. Exit code is non-zero on any mismatch -
a migration that cannot prove equality has not happened.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pageops.store import DATASETS, SqliteStore, Store


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    src_dir, dst_dir = Path(sys.argv[1]), Path(sys.argv[2])
    source = Store(src_dir)
    target = SqliteStore(dst_dir)
    ok = True
    for name in DATASETS:
        rows = source.read_dataset(name)
        target.write_dataset(name, rows)
        back = target.read_dataset(name)
        equal = back == [
            {f: str(r.get(f, "")) for f in DATASETS[name]} for r in rows
        ]
        print(f"{name}: {len(rows)} rows -> {'EQUAL' if equal else 'MISMATCH'}")
        ok = ok and equal
    log = src_dir / "writes.log"
    if log.exists():
        shutil.copyfile(log, dst_dir / "writes.log")
        print("writes.log carried across")
    notes = src_dir / "notes"
    if notes.is_dir():
        # The analyst instruments keep their last texts + history
        # beside the datasets; they are store state too.
        shutil.copytree(notes, dst_dir / "notes", dirs_exist_ok=True)
        print("notes/ carried across")
    print("MIGRATION VERIFIED" if ok else "MIGRATION FAILED - do not switch")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
