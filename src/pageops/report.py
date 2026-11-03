"""Performance report for PaCo Agent.

The narrative is assembled from the computed metrics only, in the
goal -> strategy -> execution -> result shape that doubles as the
portfolio case-study format. Numbers come from metrics.compute_metrics;
nothing here invents a figure.
"""

from __future__ import annotations

from .metrics import compute_metrics
from .model_client import humanize_text
from .store import Store


def _figures_grounded(text: str, stats: dict) -> bool:
    """True when every number in the prose exists in the stats."""
    import re

    allowed = set()
    for value in stats.get("totals", {}).values():
        allowed.add(int(value))
    best = stats.get("best_post") or {}
    for key in ("reach", "engagement", "clicks"):
        if key in best:
            allowed.add(int(best[key]))
    # Post IDs are identifiers, not figures: strip them before the
    # scan so an ID like fb-123 is never mistaken for a number.
    scrubbed = text
    post_ids = [stats.get("best_post", {}).get("post_id", "")]
    post_ids += [p.get("post_id", "") for p in stats.get("posts", [])]
    for pid in post_ids:
        if pid:
            scrubbed = scrubbed.replace(pid, "")
    found = [int(n.replace(",", "")) for n in re.findall(r"\d[\d,]*", scrubbed)]
    return all(n in allowed for n in found)


def build_report(store: Store, goal: str = "", client=None) -> dict:
    """Return {stats, narrative} for the store's current metrics.

    Pure: no writes. Recording the report (history, reported
    transitions) is pipeline.report_week, the Analyst's stage act.
    """
    brand = store.get_brand_voice()
    stats = compute_metrics(store.read_dataset("metrics"))
    totals = stats["totals"]
    best = stats["best_post"]
    brand_name = brand.get("brand_name", "the brand")
    goal_line = goal or f"Run {brand_name}'s weekly content operation with an approval-gated agent."

    lines = [
        f"Goal: {goal_line}",
        (
            "Strategy: a 7-day plan drafted against the brand voice, every draft "
            "checked by deterministic brand rules with quoted evidence, and a "
            "human approval click before anything is scheduled."
        ),
        (
            f"Execution: {totals['posts']} published posts tracked this period "
            f"across the plan stored in PaCo."
        ),
        (
            f"Result: total reach {totals['reach']}, total engagement "
            f"{totals['engagement']}, total clicks {totals['clicks']}."
        ),
    ]
    if client is not None and totals["posts"]:
        # The model reads ONLY the computed stats and writes the
        # interpretation. Its prose is then figure-checked in code:
        # any number that is not in the stats drops the whole Read
        # line, so an invented figure can never reach the report.
        read = client.narrate(stats, brand)
        # The Analyst is a writer too: the Read passes the same
        # humanising pass as the drafts, BEFORE the figure check,
        # so a rewrite that alters a number still drops the line.
        # A failed pass is named in the narrative, never silent.
        read, humanize_error = humanize_text(client, read, brand)
        if _figures_grounded(read, stats):
            lines.append(f"Read: {read}")
            if humanize_error:
                lines.append(
                    "Humaniser note: the humanising pass was unavailable "
                    f"({humanize_error}); the Read is shown as generated."
                )
    if best:
        lines.append(
            f"Best post: {best['post_id']} on {best['platform']} with "
            f"{best['engagement']} engagement and {best['reach']} reach."
        )
        lines.append(
            "Next adjustment: lead next week's plan with the angle behind "
            f"post {best['post_id']}, and keep the checker evidence review in the loop."
        )
    else:
        lines.append("No metrics recorded yet; the next period will set the baseline.")
    return {"stats": stats, "narrative": "\n".join(lines)}
