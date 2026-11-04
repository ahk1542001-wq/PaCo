"""Cross-platform variants for PaCo Agent.

One approved master draft becomes a native post per platform.
This is the product form of the manual adaptation pass the
operator ran for the FYF week (one Facebook master rewritten
for Instagram, TikTok, Threads and X, counted by hand against
each platform's cap). Here each variant is written by the
Copywriter against the platform-variants skill, humanised,
then run through the same deterministic checker as any draft;
a variant that fails only on length is shortened by the
checker's sentence trim, never by cutting a sentence in half.
Platforms the owner toggled off in the connection data get no
variant. Variants are stored in their own dataset, keyed by
plan item and platform, so re-running updates in place.
"""

from __future__ import annotations

from .checker import PLATFORM_LIMITS, check_draft, trim_to_cap
from .model_client import humanize_text
from .store import Store

ALL_PLATFORMS = ("facebook", "instagram", "tiktok", "threads", "x")
VARIANT_STATUSES = ("approved", "scheduled", "reported")


def target_platforms(store: Store, item: dict) -> list[str]:
    """Platforms a variant is owed for one plan item.

    The owner's toggles rule: when connection data exists, only
    enabled platforms are targets. With no connection data yet,
    every platform except the item's own is a target.
    """
    brand = store.get_brand_voice()
    channels = brand.get("postiz_channels") or {}
    if channels:
        targets = [
            p for p in ALL_PLATFORMS if (channels.get(p) or {}).get("enabled")
        ]
    else:
        targets = list(ALL_PLATFORMS)
    own = (item.get("platform") or "").lower()
    return [p for p in targets if p != own]


def _upsert_variant(store: Store, plan_id: str, platform: str, text: str, status: str) -> str:
    rows = store.read_dataset("variants")
    for row in rows:
        if row.get("plan_id") == str(plan_id) and row.get("platform") == platform:
            store.update_row(
                "variants", row["id"], {"text": text, "check_status": status}
            )
            return "updated"
    store.append_row(
        "variants",
        {
            "id": str(len(rows) + 1),
            "plan_id": str(plan_id),
            "platform": platform,
            "text": text,
            "check_status": status,
        },
    )
    return "created"


def generate_variants(store: Store, client) -> dict:
    """Adapt every approved-or-later item's draft per platform.

    Returns counts plus a failures list of (plan_id, platform,
    failing rules) for any variant that still fails its checks
    after the length trim.
    """
    brand = store.get_brand_voice()
    markers = brand.get("cta_markers") or []
    result: dict = {"created": 0, "updated": 0, "failures": []}
    for item in store.read_dataset("plan"):
        draft = (item.get("draft") or "").strip()
        if not draft or item.get("status") not in VARIANT_STATUSES:
            continue
        for platform in target_platforms(store, item):
            text = client.adapt_variant(draft, brand, platform)
            text, _err = humanize_text(client, text, brand)
            check = check_draft(text, platform, brand)
            if not check.passed:
                failing = [r.rule for r in check.results if not r.passed]
                if "length_limit" in failing:
                    cap = PLATFORM_LIMITS[platform]
                    text = trim_to_cap(text, cap, protected_markers=markers)
                    check = check_draft(text, platform, brand)
            status = "pass" if check.passed else "fail"
            outcome = _upsert_variant(store, item["id"], platform, text, status)
            result[outcome] += 1
            if not check.passed:
                result["failures"].append(
                    (
                        item["id"],
                        platform,
                        [r.rule for r in check.results if not r.passed],
                    )
                )
    return result
