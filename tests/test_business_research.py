"""Business research (owner's rule: everything done by hand
must live in the product, 2026-11-04). The manual FYF research
becomes a product stage whose discipline is the point: a claim
carries a source or is stored unvalidated in those words, and
an uncovered kind becomes a recorded gap, never an invention.
"""
from pageops.business_research import research_counts, run_business_research
from pageops.context import latest_analyst_summary
from pageops.model_client import MockClient
from pageops.store import Store


def test_claims_store_with_honest_evidence_labels(tmp_path):
    store = Store(tmp_path)
    result = run_business_research(store, MockClient(), "brief", items=[])
    assert result == {"claims": 2, "sourced": 1, "unvalidated": 1, "gaps": 2}
    rows = store.read_dataset("research")
    by_evidence = {r["evidence"] for r in rows}
    assert by_evidence == {"sourced", "unvalidated", "gap"}
    counts = research_counts(store)
    assert counts["by_kind"] == {"audience": 1}
    # competitor and channel were uncovered: both became gaps
    gap_text = " ".join(r["claim"] for r in rows if r["evidence"] == "gap")
    assert "competitor" in gap_text and "channel" in gap_text


def test_research_reaches_the_strategist_summary(tmp_path):
    store = Store(tmp_path)
    run_business_research(store, MockClient(), "brief", items=[])
    summary = latest_analyst_summary(store)
    assert "Research: 1 sourced claims, 1 unvalidated, 2 gaps." in summary


class EmptyClient(MockClient):
    def extract_research(self, brief, items, brand_voice):
        return {"claims": [], "gaps": []}


def test_empty_extraction_records_a_gap_per_kind(tmp_path):
    store = Store(tmp_path)
    result = run_business_research(store, EmptyClient(), "brief", items=[])
    assert result["claims"] == 0
    assert result["gaps"] == 4


class KindNameGapsClient(MockClient):
    def extract_research(self, brief, items, brand_voice):
        return {"claims": [], "gaps": ["market", "audience", "competitor", "channel"]}


def test_kind_name_gaps_are_stored_as_sentences(tmp_path):
    store = Store(tmp_path)
    result = run_business_research(store, KindNameGapsClient(), "brief", items=[])
    assert result["gaps"] == 4
    claims = [r["claim"] for r in store.read_dataset("research")]
    assert all(c.startswith("no ") for c in claims)
