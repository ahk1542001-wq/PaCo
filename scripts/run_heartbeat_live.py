"""Live heartbeat tick: fetch the model credential the supported
way, then run the weekly cycle only if the schedule says it is due.

This is the script a cron line fires (see deploy/paco-heartbeat.cron).
The due decision, the cycle and the gate all live in the product;
this wrapper only supplies the live credential and the data dir,
exactly like the dashboard's own live wiring.

Usage:
    .venv/bin/python scripts/run_heartbeat_live.py [DATA_DIR]

DATA_DIR defaults to the PAGEOPS_DATA_DIR environment variable, or
the product default data directory.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, "/opt/muse/skills/custom-connector-setup/bin")
from dynamic_credentials import dynamic_credential_entry  # noqa: E402

entry = dynamic_credential_entry("custom.meta-model-api", "access_token")
os.environ["MODEL_API_KEY"] = str(entry["surrogate"]).strip()
os.environ["MODEL_MODE"] = "meta"
os.environ.pop("NO_PROXY", None)
os.environ.pop("no_proxy", None)

if len(sys.argv) > 1:
    os.environ["PAGEOPS_DATA_DIR"] = sys.argv[1]
    sys.argv = [sys.argv[0]]

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.chdir(ROOT)

from run_cycle import main  # noqa: E402  (scripts/ is not a package)

if __name__ == "__main__":
    raise SystemExit(main(["--if-due"]))
