"""Business research for PaCo Agent.

The first step of the staircase, before Brand: market,
competition, audience evidence and channels for the business
in the brief. The product form of the manual FYF research
(2026-11-04), including its discipline: every claim carries a
source or is stored as unvalidated in those words, and the
gaps are a deliverable, recorded per kind, never filled by
invention. Claims land in the research dataset that Brand
Builder and the Strategist read.
"""

from __future__ import annotations

from datetime import date

from .store import Store

KINDS = ("market", "audience", "competitor", "channel")


def run_business_research(store: Store, client, brief: str, items: list[dict]) -> dict:
    """Extract structured claims from gathered items and store them.

    Returns {claims, sourced, unvalidated, gaps}. When the
    extraction finds nothing for a kind, a gap row is recorded
    for that kind: silence is never left to masquerade as
    coverage.
    """
    brand = store.get_brand_voice()
    extracted = client.extract_research(brief, items, brand)
    claims = extracted.get("claims") or []
    gaps = list(extracted.get("gaps") or [])
    covered = {c.get("kind") for c in claims}
    normalised = []
    for gap in gaps:
        text = str(gap).strip()
        if text.lower() in KINDS:
            text = f"no {text.lower()} evidence found in the gathered sources"
        if text and text not in normalised:
            normalised.append(text)
    gaps = normalised
    for kind in KINDS:
        if kind not in covered and not any(kind in g for g in gaps):
            gaps.append(f"no {kind} evidence found in the gathered sources")
    rows = store.read_dataset("research")
    next_id = len(rows) + 1
    sourced = unvalidated = 0
    for claim in claims:
        source = (claim.get("source") or "").strip()
        evidence = "sourced" if source else "unvalidated"
        if source:
            sourced += 1
        else:
            unvalidated += 1
        store.append_row(
            "research",
            {
                "id": str(next_id),
                "kind": claim.get("kind", ""),
                "claim": claim.get("claim", ""),
                "source": source,
                "evidence": evidence,
                "recorded": date.today().isoformat(),
            },
        )
        next_id += 1
    for gap in gaps:
        store.append_row(
            "research",
            {
                "id": str(next_id),
                "kind": "gap",
                "claim": gap,
                "source": "",
                "evidence": "gap",
                "recorded": date.today().isoformat(),
            },
        )
        next_id += 1
    return {
        "claims": len(claims),
        "sourced": sourced,
        "unvalidated": unvalidated,
        "gaps": len(gaps),
    }


def research_counts(store: Store) -> dict:
    """Counts by kind and evidence, for summaries and panels."""
    counts: dict = {"sourced": 0, "unvalidated": 0, "gaps": 0, "by_kind": {}}
    for row in store.read_dataset("research"):
        if row.get("evidence") == "gap":
            counts["gaps"] += 1
        elif row.get("evidence") == "sourced":
            counts["sourced"] += 1
            kind = row.get("kind", "")
            counts["by_kind"][kind] = counts["by_kind"].get(kind, 0) + 1
        elif row.get("evidence") == "unvalidated":
            counts["unvalidated"] += 1
    return counts
