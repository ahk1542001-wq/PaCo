"""Pull Facebook Page insights into the PaCo store (Graph API).

Usage: python scripts/pull_fb_insights.py [data-dir]

Configuration: PAGEOPS_FB_PAGE_ID + PAGEOPS_FB_TOKEN environment
variables, or fb_page_id / fb_access_token keys in the brand data.
The token is Page access token material from a connected Meta app -
connect-day setup. Without it this script refuses plainly and exits
non-zero; it never fabricates numbers.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pageops.fb_insights import GraphClient, pull_insights, resolve_fb_config
from pageops.store import Store


def main() -> int:
    data_dir = sys.argv[1] if len(sys.argv) > 1 else "data"
    store = Store(Path(data_dir))
    page_id, token = resolve_fb_config(store)
    if not page_id or not token:
        print(
            "Facebook pull is not configured: set PAGEOPS_FB_PAGE_ID and "
            "PAGEOPS_FB_TOKEN (a Page access token from the connected Meta "
            "app), or add fb_page_id / fb_access_token to the brand data. "
            "This is connect-day setup; nothing was pulled."
        )
        return 2
    summary = pull_insights(store, GraphClient(token), page_id, date.today().isoformat())
    print(
        f"Pulled Facebook insights for {summary['period_end']}: "
        f"followers={summary['followers'] or 'n/a'}, "
        f"posts seen={summary['posts_seen']}, "
        f"new metric rows={summary['metrics_added']}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
