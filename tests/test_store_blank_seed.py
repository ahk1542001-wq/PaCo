"""Per-brand data separation: a store created for a real new page
starts BLANK — the demo brand's seed must never leak into it.

Regression for 2026-11-10: the AI Premium Myanmar 2.0 store was
created as a clone of the FYF AI seed (colours, hashtags, tone and
the PaCo character all carried over), which put the wrong wordmark,
palette and mascot on that page's posts. Owner rule: each brand's
data is its own.
"""
from pageops.store import BRAND_VOICE_SEED, SqliteStore, Store
from pageops.stores import StoreRegistry

IDENTITY_KEYS = (
    "brand_name",
    "services",
    "audience",
    "tone",
    "brand_colors",
    "logo_usage",
    "character_name",
    "character_image",
    "character_rules",
    "proof_baseline",
)


def _assert_no_seed_leak(store):
    rows = store.read_dataset("brand_voice")
    assert rows, "brand_voice rows exist (keys present, values blank)"
    for row in rows:
        assert row["value"] == "", f"{row['key']} should start blank, got {row['value']!r}"
    voice = store.get_brand_voice()
    assert voice["services"] == []
    assert voice["rules"] == []
    assert voice["required_hashtags"] == []


def test_blank_store_starts_empty_and_stays_empty(tmp_path):
    store = Store(tmp_path / "data-new", blank=True)
    _assert_no_seed_leak(store)
    # Reopening without the flag must not backfill the demo seed:
    # every key is already present, so nothing can be filled in.
    reopened = Store(tmp_path / "data-new")
    _assert_no_seed_leak(reopened)


def test_blank_sqlite_store_starts_empty(tmp_path):
    store = SqliteStore(tmp_path / "data-new", blank=True)
    _assert_no_seed_leak(store)


def test_default_store_still_seeds_the_demo_brand(tmp_path):
    store = Store(tmp_path / "data-demo")
    assert store.get_brand_voice()["brand_name"] == BRAND_VOICE_SEED["brand_name"]


def test_registry_create_page_is_blank_but_named(tmp_path):
    launch = Store(tmp_path / "data-launch", blank=True)
    registry = StoreRegistry(launch)
    created = registry.create_page("Shwe Mart")
    assert created.get_brand_voice()["brand_name"] == "Shwe Mart"
    for row in created.read_dataset("brand_voice"):
        if row["key"] == "brand_name":
            continue
        assert row["value"] == "", f"{row['key']} should start blank, got {row['value']!r}"
