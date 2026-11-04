"""Audience analysis for PaCo Agent.

The Analyst's fourth instrument: page-level audience movement
from insights snapshots. One snapshot is a level; two are a
trend. Deltas are computed in code (absolute and percentage,
both quoted so neither floats free), plus two efficiency ratios
(engagements per 100 views, new followers per 100 profile
visits). The model's interpretation is humanised and
figure-checked against the computed deltas.
"""

from __future__ import annotations

import re

from .metrics import _num
from .model_client import humanize_text
from .store import Store

FIELDS = (
    "followers",
    "views",
    "unique_viewers",
    "engagements",
    "profile_visits",
    "new_followers",
    "unfollowers",
)
FLOW_FIELDS = ("views", "unique_viewers", "engagements", "profile_visits", "new_followers")


def import_insights(store: Store, rows: list[dict]) -> int:
    """Pull page-insights snapshots into the store.

    Deduplicated on period_end: a re-pull updates the stored
    snapshot. Returns how many snapshots were newly added.
    """
    existing = store.read_dataset("insights")
    by_key = {r.get("period_end", ""): r for r in existing}
    added = 0
    for row in rows:
        key = str(row.get("period_end", ""))
        if not key:
            continue
        clean = {"period_end": key}
        for field in FIELDS:
            clean[field] = str(row.get(field, ""))
        if key not in by_key:
            added += 1
        by_key[key] = clean
    store.write_dataset("insights", [by_key[k] for k in sorted(by_key)])
    return added


def _pct_change(new: int, old: int) -> float:
    return round(100 * (new - old) / old, 1) if old else 0.0


def analyse_audience(store: Store) -> dict:
    """Deterministic snapshot comparison (latest vs previous)."""
    rows = sorted(store.read_dataset("insights"), key=lambda r: r.get("period_end", ""))
    snapshots = [
        {"period_end": r.get("period_end", ""), **{f: _num(r.get(f)) for f in FIELDS}}
        for r in rows
    ]
    result: dict = {"snapshots": snapshots, "deltas": {}, "ratios": {}}
    if snapshots:
        latest = snapshots[-1]
        result["ratios"] = {
            "engagements_per_100_views": round(
                100 * latest["engagements"] / latest["views"], 1
            )
            if latest["views"]
            else 0.0,
            "followers_per_100_visits": round(
                100 * latest["new_followers"] / latest["profile_visits"], 1
            )
            if latest["profile_visits"]
            else 0.0,
        }
    if len(snapshots) >= 2:
        latest, previous = snapshots[-1], snapshots[-2]
        for field in FIELDS:
            result["deltas"][field] = {
                "from": previous[field],
                "to": latest[field],
                "change": latest[field] - previous[field],
                "pct": _pct_change(latest[field], previous[field]),
            }
    return result


def _numbers(text: str) -> set[int]:
    return {int(n.replace(",", "")) for n in re.findall(r"\d[\d,]*", text)}


def build_audience_analysis(store: Store, client=None) -> dict:
    """Return {analysis, text}. Pure; recording is the pipeline stage."""
    brand = store.get_brand_voice()
    analysis = analyse_audience(store)
    snapshots = analysis["snapshots"]
    if not snapshots:
        return {
            "analysis": analysis,
            "text": "Audience analysis: no insights snapshots yet; ingest page insights first.",
        }
    latest = snapshots[-1]
    lines = [
        f"Audience analysis at {latest['period_end']}: {latest['followers']} followers, "
        f"{latest['views']} views, {latest['unique_viewers']} unique viewers, "
        f"{latest['engagements']} engagements, {latest['profile_visits']} profile visits, "
        f"{latest['new_followers']} new followers, {latest['unfollowers']} unfollowers."
    ]
    ratios = analysis["ratios"]
    lines.append(
        f"Efficiency: {ratios['engagements_per_100_views']} engagements per 100 views; "
        f"{ratios['followers_per_100_visits']} new followers per 100 profile visits."
    )
    if analysis["deltas"]:
        previous_end = snapshots[-2]["period_end"]
        for field in FLOW_FIELDS + ("followers",):
            d = analysis["deltas"][field]
            direction = "up" if d["change"] > 0 else "down" if d["change"] < 0 else "flat"
            lines.append(
                f"Versus {previous_end}: {field} {direction} {abs(d['change'])} "
                f"({d['pct']}%), from {d['from']} to {d['to']}."
            )
    else:
        lines.append("One snapshot only: a level, not a trend, until the next snapshot lands.")
    text = "\n".join(lines)
    if client is not None:
        read = client.audience_read(text, brand)
        read, humanize_error = humanize_text(client, read, brand)
        if humanize_error:
            text += f"\n[HUMANIZER FALLBACK] audience read unedited ({humanize_error})"
        if _numbers(read) <= _numbers(text):
            text += f"\nRead: {read}"
        else:
            text += (
                "\n[READ DROPPED] the model's audience read cited "
                "figures outside the computed snapshots."
            )
    return {"analysis": analysis, "text": text}
