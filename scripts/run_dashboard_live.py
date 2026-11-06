"""Live dashboard: fetch the model credential the supported way,
then serve the dashboard in meta mode.

Why this wrapper exists (the 2026-11-05 demo incident): a
dashboard server launched as a bare `python -m pageops.dashboard`
carries no MODEL_MODE / MODEL_API_KEY in its environment, so the
factories behind every dashboard action (get_client,
get_judge_client, get_image_client) fall back to mock. The Run
button then produces short mock drafts that fail the brand
checks, with no visible sign the server is not live. This script
is the dashboard twin of run_heartbeat_live.py: it supplies the
live credential and meta mode first, then serves the dashboard
exactly the way the module itself is launched.

Usage:
    .venv/bin/python scripts/run_dashboard_live.py [DATA_DIR]

DATA_DIR defaults to the PAGEOPS_DATA_DIR environment variable,
or the product default data directory. The port comes from
PAGEOPS_DASHBOARD_PORT (default 8765), as with
`python -m pageops.dashboard`.
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

from pageops.dashboard import serve  # noqa: E402

if __name__ == "__main__":
    serve(port=int(os.environ.get("PAGEOPS_DASHBOARD_PORT", "8765"))).serve_forever()
