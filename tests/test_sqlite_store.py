"""SQLite backend parity: same behaviours as the CSV store.

The migration promise is that SqliteStore is Store with different
persistence, so these tests pin the shared semantics (seed, backfill,
ids, updates, brand parsing) plus the migration's row-for-row proof.
"""

from pageops.store import DATASETS, SqliteStore, Store, open_store


def test_sqlite_seeds_brand_voice_like_csv(tmp_path):
    store = SqliteStore(tmp_path / "db")
    voice = store.get_brand_voice()
    assert voice["brand_name"] == "FYF AI"
    assert voice["character_name"] == "PaCo"  # backfilled key present
    assert (tmp_path / "db" / "paco.db").exists()


def test_sqlite_plan_row_ids_and_updates(tmp_path):
    store = SqliteStore(tmp_path / "db")
    first = store.add_plan_row({"topic": "One", "status": "brief_received"})
    second = store.add_plan_row({"topic": "Two", "status": "planned"})
    assert (first["id"], second["id"]) == ("1", "2")
    updated = store.update_row("plan", "2", {"status": "drafted"})
    assert updated["status"] == "drafted"
    rows = store.read_dataset("plan")
    assert [r["topic"] for r in rows] == ["One", "Two"]


def test_sqlite_roundtrip_hard_text(tmp_path):
    store = SqliteStore(tmp_path / "db")
    hard = 'Burmese ၊၊|"\nsecond line, with comma'
    store.write_dataset("research", [
        {"id": "1", "kind": "market", "claim": hard, "source": "s",
         "evidence": "sourced", "recorded": "2026-11-05"},
    ])
    assert store.read_dataset("research")[0]["claim"] == hard


def test_sqlite_set_brand_value_roundtrip(tmp_path):
    store = SqliteStore(tmp_path / "db")
    store.set_brand_value("tone", "Calm and plain")
    assert store.get_brand_voice()["tone"] == "Calm and plain"
    store.set_brand_value("new_key", "x")  # appends when absent
    raw = {r["key"]: r["value"] for r in store.read_dataset("brand_voice")}
    assert raw["new_key"] == "x"


def test_migration_is_row_for_row_equal(tmp_path):
    source = Store(tmp_path / "csv")
    source.add_plan_row({"topic": "Migrate me", "status": "scheduled"})
    target = SqliteStore(tmp_path / "db")
    for name in DATASETS:
        target.write_dataset(name, source.read_dataset(name))
    for name in DATASETS:
        assert target.read_dataset(name) == source.read_dataset(name)


def test_open_store_backend_switch(tmp_path, monkeypatch):
    monkeypatch.delenv("PAGEOPS_STORE_BACKEND", raising=False)
    assert type(open_store(tmp_path / "a")) is Store
    monkeypatch.setenv("PAGEOPS_STORE_BACKEND", "sqlite")
    assert type(open_store(tmp_path / "b")) is SqliteStore
