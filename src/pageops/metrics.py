"""Performance metrics maths for PageOps Agent.

All numbers are computed in code from the metrics dataset. The report
narrative may only cite numbers produced here.
"""

from __future__ import annotations


def _num(value) -> int:
    try:
        return int(float(str(value).replace(",", "")))
    except (TypeError, ValueError):
        return 0


def compute_metrics(rows: list[dict]) -> dict:
    """Totals and the best-performing post for a list of metric rows."""
    posts = []
    for row in rows:
        posts.append(
            {
                "post_id": row.get("post_id", ""),
                "platform": row.get("platform", ""),
                "date": row.get("date", ""),
                "reach": _num(row.get("reach")),
                "engagement": _num(row.get("engagement")),
                "clicks": _num(row.get("clicks")),
                "notes": row.get("notes", ""),
            }
        )
    totals = {
        "posts": len(posts),
        "reach": sum(p["reach"] for p in posts),
        "engagement": sum(p["engagement"] for p in posts),
        "clicks": sum(p["clicks"] for p in posts),
    }
    best = max(posts, key=lambda p: p["engagement"], default=None)
    return {"totals": totals, "posts": posts, "best_post": best}


def import_metrics(store, rows: list[dict]) -> int:
    """Pull published-post metrics into the store.

    Deduplicated on (post_id, date): a re-pull updates the stored
    numbers instead of duplicating the post. Returns how many rows
    were newly added. This is the ingest the Analyst's stage runs
    on connector-shaped rows; the maths above never changes.
    """
    existing = store.read_dataset("metrics")
    by_key = {(r.get("post_id", ""), r.get("date", "")): r for r in existing}
    added = 0
    for row in rows:
        key = (str(row.get("post_id", "")), str(row.get("date", "")))
        clean = {
            "date": key[1],
            "platform": str(row.get("platform", "")),
            "post_id": key[0],
            "reach": str(row.get("reach", "")),
            "engagement": str(row.get("engagement", "")),
            "clicks": str(row.get("clicks", "")),
            "notes": str(row.get("notes", "")),
        }
        if key in by_key:
            by_key[key].update(clean)
        else:
            by_key[key] = clean
            added += 1
    store.write_dataset("metrics", list(by_key.values()))
    return added
