from pageops.sheets_sync import TAB_NAMES, dataset_values
from pageops.store import DATASETS, Store


def test_dataset_values_header_and_rows(tmp_path):
    store = Store(tmp_path)
    store.add_plan_row({"platform": "facebook", "topic": "T", "status": "planned"})
    values = dataset_values(store, "plan")
    assert values[0] == DATASETS["plan"]
    assert "draft" in values[0] and "buffer_id" in values[0]
    assert values[1][values[0].index("topic")] == "T"


def test_brand_voice_values_seeded(tmp_path):
    values = dataset_values(Store(tmp_path), "brand_voice")
    keys = [row[0] for row in values[1:]]
    assert "brand_name" in keys and "required_hashtags" in keys


def test_tab_names_cover_all_datasets():
    assert set(TAB_NAMES) == set(DATASETS)
