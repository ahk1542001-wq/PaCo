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
