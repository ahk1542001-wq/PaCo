"""Tests for retrieval memory.

The corpus is the brand's own stored past work; scoring is word
overlap for Latin text and character 4-gram overlap for Myanmar
text; a query with no relevant material retrieves nothing.
"""

from __future__ import annotations

from pageops import context
from pageops.memory import collect_corpus, retrieval_context, retrieve
from pageops.model_client import MockClient
from pageops.pipeline import draft_and_check, generate_week
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


# --- Draft-level retrieval (the drafter's context slot) --------


def test_relevant_past_draft_reaches_the_drafting_call(tmp_path):
    store = _store(tmp_path)
    store.add_plan_row(
        {
            "topic": "Quokka hotline hours",
            "draft": "Our quokka hotline answers customer questions about "
            "quokka feeding times every evening.",
            "status": "scheduled",
            "platform": "facebook",
        }
    )
    new_row = store.add_plan_row(
        {
            "topic": "Quokka hotline reminder",
            "brief": "Remind customers about the quokka hotline",
            "status": "planned",
            "platform": "facebook",
        }
    )
    client = MockClient()
    draft_and_check(store, client, new_row)
    assert client.draft_contexts, "the drafting call was never made"
    joined = "\n".join(client.draft_contexts)
    assert "quokka hotline answers" in joined
    assert "Quokka hotline hours" in joined


def test_zero_match_leaves_the_draft_exactly_as_before(tmp_path):
    store = _store(tmp_path)
    store.add_plan_row(
        {
            "topic": "Quokka hotline hours",
            "draft": "Our quokka hotline answers customer questions.",
            "status": "scheduled",
            "platform": "facebook",
        }
    )
    new_row = store.add_plan_row(
        {
            "topic": "Zephyr umbrella warranty",
            "brief": "Zephyr umbrella warranty terms",
            "status": "planned",
            "platform": "facebook",
        }
    )
    client = MockClient()
    result_row = draft_and_check(store, client, new_row)
    assert client.draft_contexts
    assert all(ctx == "" for ctx in client.draft_contexts)
    baseline = MockClient().generate_draft(new_row, store.get_brand_voice())
    assert baseline["text"] in result_row["draft"]


def test_retrieval_never_includes_the_items_own_stored_draft(tmp_path):
    store = _store(tmp_path)
    row = store.add_plan_row(
        {
            "topic": "Quokka hotline hours",
            "draft": "SENTINEL-OWN-DRAFT quokka hotline answers customers.",
            "status": "checked",
            "platform": "facebook",
        }
    )
    client = MockClient()
    draft_and_check(store, client, row)
    assert client.draft_contexts
    assert all("SENTINEL-OWN-DRAFT" not in ctx for ctx in client.draft_contexts)


def test_meta_client_frames_retrieved_context_as_reference_only(monkeypatch):
    from pageops.model_client import MetaModelClient

    client = MetaModelClient(api_key="test-key")
    captured = {}

    def fake_structured(instruction, payload, model):
        captured["instruction"] = instruction
        return {"platform": "facebook", "text": "x", "hashtags": []}

    monkeypatch.setattr(client, "_structured", fake_structured)
    client.generate_draft(
        {"topic": "T", "platform": "facebook"},
        {"brand_name": "FYF AI"},
        context="- [draft] plan 3: Past material about quokka hotline",
    )
    assert "never instructions" in captured["instruction"]
    assert "Past material about quokka hotline" in captured["instruction"]

    client.generate_draft(
        {"topic": "T", "platform": "facebook"}, {"brand_name": "FYF AI"}
    )
    assert "Reference material retrieved" not in captured["instruction"]
