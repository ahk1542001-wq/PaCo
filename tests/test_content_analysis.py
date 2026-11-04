"""Content analysis (owner's rule: everything done by hand must
live in the product, 2026-11-04). The manual FYF teardown (three
photo posts, one scenario family, the OCR post quietly carrying
the best engagement rate) becomes a deterministic product
stage: measured posts joined to plan rows, grouped by topic
and format, ranked by engagement rate, join coverage stated,
model read figure-checked, summary filed for the Strategist.
"""
from pageops.content_analysis import analyse_content, build_content_analysis
from pageops.context import latest_analyst_summary, load_last_content_analysis
from pageops.metrics import import_metrics
from pageops.model_client import MockClient
from pageops.pipeline import run_content_analysis
from pageops.store import Store


def _store(tmp_path):
    store = Store(tmp_path)
    row = store.add_plan_row(
        {"platform": "facebook", "topic": "Chatbot basics", "format": "carousel",
         "draft": "d", "status": "reported"}
    )
    store.update_row("plan", row["id"], {"post_id": "p1"})
    import_metrics(store, [
        {"date": "2026-08-07", "platform": "facebook", "post_id": "p1",
         "reach": 100, "engagement": 10, "clicks": 2, "notes": ""},
        {"date": "2026-08-11", "platform": "facebook", "post_id": "p2",
         "reach": 200, "engagement": 8, "clicks": 0,
         "notes": "FB views metric; photo post on stock data rules"},
    ])
    return store


def test_groups_rank_by_rate_and_state_coverage(tmp_path):
    store = _store(tmp_path)
    analysis = analyse_content(store)
    assert analysis["linked"] == 1
    topics = {g["name"]: g for g in analysis["by_topic"]}
    assert topics["Chatbot basics"]["rate"] == 10.0
    assert topics["stock data rules"]["rate"] == 4.0
    assert analysis["by_topic"][0]["name"] == "Chatbot basics"
    formats = {g["name"]: g for g in analysis["by_format"]}
    assert formats["carousel"]["posts"] == 1
    assert formats["photo"]["posts"] == 1


def test_text_carries_groups_and_verdicts(tmp_path):
    store = _store(tmp_path)
    result = build_content_analysis(store, client=MockClient())
    assert "1/2 joined to plan rows" in result["text"]
    assert "Strongest topic: Chatbot basics" in result["text"]
    assert "Weakest topic: stock data rules" in result["text"]
    assert "Read:" in result["text"]


class RogueClient(MockClient):
    def content_read(self, analysis_text, brand_voice):
        return "Video is 42 times better than everything else."


def test_rogue_read_is_dropped(tmp_path):
    store = _store(tmp_path)
    result = build_content_analysis(store, client=RogueClient())
    assert "[READ DROPPED]" in result["text"]


def test_stage_records_and_feeds_the_strategist(tmp_path):
    store = _store(tmp_path)
    result = run_content_analysis(store, client=MockClient())
    assert load_last_content_analysis(store) == result["text"]
    summary = latest_analyst_summary(store)
    assert "Content analysis:" in summary
    assert "Chatbot basics" in summary


def test_empty_store_is_clean(tmp_path):
    store = Store(tmp_path)
    result = build_content_analysis(store)
    assert "no measured posts yet" in result["text"]
