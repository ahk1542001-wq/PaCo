import pytest

from pageops.model_client import MockClient
from pageops.pipeline import draft_and_check, fetch_trends, process_week
from pageops.store import Store

BRIEF = "Promote the chatbot offer to SME page owners this week"


def test_mock_pipeline_end_to_end(tmp_path):
    store = Store(tmp_path)
    rows = process_week(store, MockClient(), BRIEF)
    assert len(rows) == 7  # mock plan size: a full week
    for row in rows:
        assert row["status"] == "awaiting_approval"
        assert row["draft"]
        assert "[PASS] banned_phrases" in row["check_status"]
    statuses = {r["status"] for r in store.read_dataset("plan")}
    assert "brief_received" in statuses  # the brief itself is on the board


class BadThenGoodClient(MockClient):
    def __init__(self):
        self.calls = 0

    def generate_draft(self, plan_item, brand_voice):
        self.calls += 1
        if self.calls == 1:
            return {
                "platform": plan_item.get("platform", "facebook"),
                "text": "Get guaranteed income from your page. Message us. #FYFAI",
                "hashtags": ["#FYFAI"],
            }
        return super().generate_draft(plan_item, brand_voice)


def test_failing_draft_is_revised_once_and_passes(tmp_path):
    store = Store(tmp_path)
    row = store.add_plan_row(
        {"platform": "facebook", "topic": "Offer post", "status": "planned"}
    )
    updated = draft_and_check(store, BadThenGoodClient(), row)
    assert updated["status"] == "awaiting_approval"
    assert "guaranteed income" not in updated["draft"].lower()


class AlwaysBadClient(MockClient):
    def generate_draft(self, plan_item, brand_voice):
        return {
            "platform": "facebook",
            "text": "Get rich fast with guaranteed income. #FYFAI",
            "hashtags": ["#FYFAI"],
        }


def test_still_failing_draft_is_flagged_not_approved(tmp_path):
    store = Store(tmp_path)
    row = store.add_plan_row(
        {"platform": "facebook", "topic": "Offer post", "status": "planned"}
    )
    updated = draft_and_check(store, AlwaysBadClient(), row)
    assert updated["status"] == "checked"
    assert "[FAIL] banned_phrases" in updated["check_status"]
    assert "guaranteed income" in updated["check_status"]  # quoted evidence


class ReviseVerdictClient(MockClient):
    def verdict(self, draft, check_summary):
        return {"verdict": "revise", "reasons": ["Tone is too salesy for this brand."]}


def test_wonder_revise_verdict_flags_card(tmp_path):
    store = Store(tmp_path)
    row = store.add_plan_row(
        {"platform": "facebook", "topic": "Offer post", "status": "planned"}
    )
    updated = draft_and_check(store, ReviseVerdictClient(), row)
    assert updated["status"] == "checked"  # flagged, not awaiting approval
    assert "[MODEL VERDICT] revise" in updated["check_status"]


def test_fetch_trends_uses_injected_fetcher():
    fake = lambda _f: [{"source": "s", "title": "t", "link": "https://x", "summary": ""}]
    items = fetch_trends(fetcher=fake, limit=5)
    assert items and items[0]["link"] == "https://x"
