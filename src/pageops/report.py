"""Performance report for PageOps Agent.

The narrative is assembled from the computed metrics only, in the
goal -> strategy -> execution -> result shape that doubles as the
portfolio case-study format. Numbers come from metrics.compute_metrics;
nothing here invents a figure.
"""

from __future__ import annotations

from .metrics import compute_metrics
from .store import Store


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
            f"across the plan stored in PageOps."
        ),
        (
            f"Result: total reach {totals['reach']}, total engagement "
            f"{totals['engagement']}, total clicks {totals['clicks']}."
        ),
    ]
    if client is not None and totals["posts"]:
        # The model reads ONLY the computed stats and writes the
        # interpretation; every figure in its prose traces to the
        # stats dict it was handed.
        lines.append(f"Read: {client.narrate(stats, brand)}")
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
