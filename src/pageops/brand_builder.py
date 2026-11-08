"""Brand Builder for PaCo Agent.

The five brand levels the operator walked by hand for FYF AI,
as a product workflow owned by Dept 1's brand-assets layer:
Identity, Audience, Positioning, Offer, Journey, in that
order, one at a time. A level can be drafted only when the
level below it stands approved; approval writes the level's
text straight into the brand data every later stage reads.
Identity is the exception: it is decided through design work,
so its approval is derived from the brand data itself (name,
palette, fonts and logo usage all present), never drafted as
prose. Nothing here auto-approves: the owner clicks.
"""

from __future__ import annotations

from datetime import date

from .store import Store

LEVELS: dict[int, dict] = {
    1: {"name": "Identity", "keys": ("brand_name", "brand_colors", "brand_fonts", "logo_usage")},
    2: {"name": "Audience", "keys": ("audience",)},
    3: {"name": "Positioning", "keys": ("positioning",)},
    4: {"name": "Offer", "keys": ("services",)},
    5: {"name": "Journey", "keys": ("journey",)},
}


def _rows(store: Store) -> dict[int, dict]:
    return {int(r["level"]): r for r in store.read_dataset("brand_build") if r.get("level")}


def level_statuses(store: Store) -> dict[int, str]:
    """level -> empty | drafted | approved, for all five levels."""
    rows = _rows(store)
    brand = store.get_brand_voice()
    statuses: dict[int, str] = {}
    for level, spec in LEVELS.items():
        if level == 1:
            present = all((brand.get(k) or "").strip() for k in spec["keys"])
            statuses[level] = "approved" if present else "empty"
        else:
            row = rows.get(level)
            statuses[level] = row["status"] if row else "empty"
    return statuses


def _upsert(store: Store, level: int, status: str, content: str) -> dict:
    rows = store.read_dataset("brand_build")
    for row in rows:
        if row.get("level") == str(level):
            return store.update_row(
                "brand_build",
                row["id"],
                {"status": status, "content": content, "updated": date.today().isoformat()},
            )
    return store.append_row(
        "brand_build",
        {
            "id": str(len(rows) + 1),
            "level": str(level),
            "status": status,
            "content": content,
            "updated": date.today().isoformat(),
        },
    )


def _check_draftable(store: Store, level: int) -> None:
    """The gate every draft write passes: a known level, never
    Identity, and the level below standing approved."""
    if level not in LEVELS:
        raise ValueError(f"Unknown brand level: {level}")
    if level == 1:
        raise ValueError(
            "Identity is recorded from design work, not drafted: "
            "set brand_name, brand_colors, brand_fonts and logo_usage."
        )
    statuses = level_statuses(store)
    if statuses[level - 1] != "approved":
        raise ValueError(
            f"Level {level} is locked: level {level - 1} "
            f"({LEVELS[level - 1]['name']}) is {statuses[level - 1]}, not approved."
        )


def draft_level(store: Store, level: int, client, brief: str) -> dict:
    """Draft one level's text. Refuses out of order."""
    _check_draftable(store, level)
    brand = store.get_brand_voice()
    content = client.draft_brand_level(LEVELS[level]["name"], brief, brand)
    return _upsert(store, level, "drafted", content)


def record_draft(store: Store, level: int, content: str) -> dict:
    """Record text drafted outside draft_level as a level's
    draft - the guided-onboarding options pick, where the owner
    chose one of several client-drafted options and the chosen
    text becomes the draft. Same gate, same write: the level
    stands drafted, awaiting the ordinary approval."""
    _check_draftable(store, level)
    return _upsert(store, level, "drafted", content)


def edit_level(store: Store, level: int, content: str) -> dict:
    """Save the owner's edit of a drafted level.

    The level stays drafted: editing is the owner improving the
    draft before the approval click, never a silent approval.
    """
    if level not in LEVELS:
        raise ValueError(f"Unknown brand level: {level}")
    row = _rows(store).get(level)
    if not row or row.get("status") != "drafted":
        raise ValueError(f"Level {level} has no draft to edit.")
    return _upsert(store, level, "drafted", content)


def approve_level(store: Store, level: int) -> dict:
    """Approve a drafted level and write it into the brand data."""
    if level not in LEVELS:
        raise ValueError(f"Unknown brand level: {level}")
    if level == 1:
        raise ValueError("Identity approves itself once its data is complete.")
    row = _rows(store).get(level)
    if not row or row.get("status") != "drafted":
        raise ValueError(f"Level {level} has no draft awaiting approval.")
    content = row["content"]
    key = LEVELS[level]["keys"][0]
    if key == "services":
        content = "; ".join(
            line.strip() for line in content.splitlines() if line.strip()
        )
    from .pipeline import update_brand_voice

    update_brand_voice(store, key, content)
    return _upsert(store, level, "approved", row["content"])
