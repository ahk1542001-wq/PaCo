"""Tests for retrieval memory.

The corpus is the brand's own stored past work; scoring is word
overlap for Latin text and character 4-gram overlap for Myanmar
text; a query with no relevant material retrieves nothing.
"""

from __future__ import annotations

from pageops import context
from pageops.memory import collect_corpus, retrieval_context, retrieve
from pageops.pipeline import generate_week
from pageops.store import Store


def _store(tmp_path) -> Store:
    return Store(tmp_path / "data")


def test_empty_store_has_no_corpus(tmp_path):
    store = _store(tmp_path)
    assert collect_corpus(store) == []
    assert retrieve(store, "anything at all") == []
    assert retrieval_context(store, "anything at all") == ""


def test_corpus_covers_drafts_brand_and_research(tmp_path):
    store = _store(tmp_path)
    store.add_plan_row({"topic": "Chatbots", "draft": "All about chatbots", "status": "scheduled"})
    store.append_row("brand_build", {"id": "1", "level": "2", "status": "approved", "content": "Audience: SME owners", "updated": ""})
    store.append_row("research", {"id": "1", "kind": "market", "claim": "SMEs sell via pages", "source": "report", "evidence": "sourced", "recorded": ""})
    kinds = {chunk["kind"] for chunk in collect_corpus(store)}
    assert {"draft", "brand", "research"} <= kinds


def test_english_query_ranks_the_matching_draft_first(tmp_path):
    store = _store(tmp_path)
    store.add_plan_row({"topic": "Delivery routes", "draft": "Delivery routes and driver schedules across the city", "status": "scheduled"})
    store.add_plan_row({"topic": "Chatbot questions", "draft": "Customers ask the chatbot pricing questions every night", "status": "scheduled"})
    hits = retrieve(store, "chatbot pricing questions from customers")
    assert hits
    assert "Chatbot" in hits[0]["ref"]
    assert hits[0]["score"] > 0


def test_myanmar_query_ranks_by_character_overlap(tmp_path):
    store = _store(tmp_path)
    store.add_plan_row({
        "topic": "Delivery",
        "draft": "ပစ္စည်း ပို့ဆောင်ရေး အချိန်ကြာပုံကို ရှင်းပြထားပါတယ် ပို့ဆောင်ခ အကြောင်းလည်း ပါပါတယ်",
        "status": "scheduled",
    })
    store.add_plan_row({
        "topic": "Pricing",
        "draft": "ဆိုင်ပိတ်ချိန်မှာ ဈေးနှုန်း မေးခွန်းတွေ အများကြီး ဝင်လာပါတယ် ဈေးနှုန်း စာရင်းကို ပို့ပေးလိုက်ပါ",
        "status": "scheduled",
    })
    hits = retrieve(store, "ဈေးနှုန်း မေးခွန်း")
    assert hits
    assert hits[0]["ref"].endswith("Pricing")


def test_irrelevant_query_retrieves_nothing(tmp_path):
    store = _store(tmp_path)
    store.add_plan_row({"topic": "Chatbots", "draft": "All about chatbots and automation", "status": "scheduled"})
    assert retrieve(store, "quantum physics homework") == []


def test_retrieval_context_block_names_its_sources(tmp_path):
    store = _store(tmp_path)
    store.add_plan_row({"topic": "Chatbot questions", "draft": "Customers ask the chatbot pricing questions every night", "status": "scheduled"})
    context.save_last_report(store, "Weekly report: engagement rose after the chatbot post.")
    block = retrieval_context(store, "chatbot engagement")
    assert "retrieved from this brand's own stored past work" in block
    assert "[draft]" in block or "[report]" in block


class _CapturingClient:
    """A plan-only client double that records what it was given."""

    def __init__(self):
        self.context = None

    def generate_plan(self, brief_text, brand, context="", trends=None):
        self.context = context
        return {"posts": []}


def test_generate_week_passes_retrieved_material_to_the_planner(tmp_path):
    store = _store(tmp_path)
    store.add_plan_row({"topic": "Chatbot questions", "draft": "Customers ask the chatbot pricing questions every night", "status": "scheduled"})
    client = _CapturingClient()
    generate_week(store, client, "A week about chatbot pricing questions")
    assert client.context is not None
    assert "retrieved from this brand's own stored past work" in client.context
    assert "Chatbot questions" in client.context
