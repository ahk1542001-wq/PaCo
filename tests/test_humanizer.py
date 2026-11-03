"""The humanising pass (owner's rule, 2026-11-04): every writer
output in the product passes it AUTOMATICALLY, in the workflow,
before it is checked or shown. The Copywriter's drafts are
humanised before the Brand Checker sees them (the checker judges
the text that would actually be published), the single revision
is humanised too, and the Analyst's report Read passes the same
pass before the figure check. A failing pass falls back visibly.
The owner's own edits are never rewritten.
"""
import pytest

from pageops.model_client import MetaModelClient, MockClient
from pageops.pipeline import draft_and_check, edit_item
from pageops.report import build_report
from pageops.store import Store

ROWS = [
    {"date": "2026-10-27", "platform": "facebook", "post_id": "p1",
     "reach": "1000", "engagement": "120", "clicks": "30", "notes": ""},
    {"date": "2026-10-29", "platform": "facebook", "post_id": "p2",
     "reach": "2500", "engagement": "300", "clicks": "45", "notes": ""},
]


def _planned_row(store):
    return store.add_plan_row(
        {"platform": "facebook", "topic": "Offer post", "status": "planned"}
    )


class RewritingClient(MockClient):
    """Drafts open with a banned phrase; the humaniser removes
    it, the way a voice edit would."""

    def __init__(self):
        self.humanize_calls = 0

    def generate_draft(self, plan_item, brand_voice):
        draft = super().generate_draft(plan_item, brand_voice)
        draft["text"] = "Get guaranteed income from your page. " + draft["text"]
        return draft

    def humanize(self, text, brand_voice):
        self.humanize_calls += 1
        return text.replace("Get guaranteed income from your page. ", "")


def test_checker_sees_the_humanised_text(tmp_path):
    store = Store(tmp_path)
    client = RewritingClient()
    updated = draft_and_check(store, client, _planned_row(store))
    # The raw draft would fail the banned-phrase rule; it passed,
    # so the checker must have run on the humanised text.
    assert client.humanize_calls == 1
    assert updated["status"] == "awaiting_approval"
    assert "guaranteed income" not in updated["draft"].lower()


class FailingHumanizer(MockClient):
    def humanize(self, text, brand_voice):
        raise RuntimeError("humaniser down")


def test_humanizer_failure_falls_back_visibly(tmp_path):
    store = Store(tmp_path)
    updated = draft_and_check(store, FailingHumanizer(), _planned_row(store))
    assert updated["status"] == "awaiting_approval"  # mock draft is compliant
    assert "[HUMANIZER FALLBACK]" in updated["check_status"]


class BadThenGoodHumanized(MockClient):
    def __init__(self):
        self.drafts = 0
        self.humanize_calls = 0

    def generate_draft(self, plan_item, brand_voice):
        self.drafts += 1
        if self.drafts == 1:
            return {
                "platform": "facebook",
                "text": "Get guaranteed income. Message us. #FYFAI",
                "hashtags": ["#FYFAI"],
            }
        return super().generate_draft(plan_item, brand_voice)

    def humanize(self, text, brand_voice):
        self.humanize_calls += 1
        return text


def test_revision_draft_is_humanised_too(tmp_path):
    store = Store(tmp_path)
    client = BadThenGoodHumanized()
    updated = draft_and_check(store, client, _planned_row(store))
    assert updated["status"] == "awaiting_approval"
    assert client.humanize_calls == 2  # first draft AND the revision


class EmptyHumanizer(MockClient):
    def humanize(self, text, brand_voice):
        return "   "


def test_empty_rewrite_falls_back_visibly(tmp_path):
    """A blanked rewrite must never reach the checker as an empty
    draft; the pass falls back and the evidence says so."""
    store = Store(tmp_path)
    updated = draft_and_check(store, EmptyHumanizer(), _planned_row(store))
    assert updated["status"] == "awaiting_approval"
    assert updated["draft"]  # the generated text, not the blank rewrite
    assert "[HUMANIZER FALLBACK]" in updated["check_status"]


def test_mock_humanize_is_identity():
    assert MockClient().humanize("Some text. #FYFAI", {}) == "Some text. #FYFAI"


def test_meta_humanize_instruction_preserves_facts(tmp_path, monkeypatch):
    """The outgoing instruction must demand exact preservation of
    facts and hashtags and carry the brand voice data."""
    client = MetaModelClient(api_key="test-key", usage_log=tmp_path / "u.jsonl")
    seen = {}

    def capturing_chat(messages, model=None, **kwargs):
        seen["messages"] = messages
        seen["model"] = model
        return {"choices": [{"message": {"content": "Rewritten."}}]}

    monkeypatch.setattr(client, "chat", capturing_chat)
    out = client.humanize("Draft text. #FYFAI", {"brand_name": "FYF AI"})
    assert out == "Rewritten."
    assert seen["model"] == client.main_model  # a writer step: Wonder tier
    sent = " ".join(m["content"] for m in seen["messages"])
    assert "EXACTLY" in sent
    assert "hashtag" in sent
    assert "FYF AI" in sent  # brand voice data went with the text


class NarratingClient(MockClient):
    def narrate(self, stats, brand_voice):
        return "The page reached 3500 people this week."

    def humanize(self, text, brand_voice):
        return text.replace("The page reached", "This week the page reached")


def _metrics_store(tmp_path):
    store = Store(tmp_path)
    for row in ROWS:
        store.append_row("metrics", row)
    return store


def test_report_read_is_humanised(tmp_path):
    report = build_report(_metrics_store(tmp_path), client=NarratingClient())
    assert "Read: This week the page reached 3500 people this week." in report["narrative"]


class FailingReportHumanizer(NarratingClient):
    def humanize(self, text, brand_voice):
        raise RuntimeError("humaniser down")


def test_report_humanizer_failure_is_named_not_silent(tmp_path):
    report = build_report(_metrics_store(tmp_path), client=FailingReportHumanizer())
    assert "Read: The page reached 3500 people this week." in report["narrative"]
    assert "Humaniser note:" in report["narrative"]
    assert "humaniser down" in report["narrative"]


class FigureChangingClient(NarratingClient):
    def humanize(self, text, brand_voice):
        return text.replace("3500", "9999")


def test_humanised_read_is_still_figure_checked(tmp_path):
    """The figure check runs AFTER the humanising pass, so a
    rewrite that alters a number still drops the Read line."""
    report = build_report(_metrics_store(tmp_path), client=FigureChangingClient())
    assert "Read:" not in report["narrative"]


class PlanClient(MockClient):
    """A one-post plan whose headline carries a banned phrase."""

    def generate_plan(self, brief, brand_voice, context=None, trends=None):
        return {"posts": [{
            "day": "Mon", "platform": "facebook",
            "topic": "Get guaranteed income from your inbox",
            "angle": "The honest angle", "format": "Poster",
        }]}


class PlanRewritingClient(PlanClient):
    def humanize(self, text, brand_voice):
        return text.replace("Get guaranteed income from", "Steady replies for")


def test_plan_headlines_are_humanised_before_storage(tmp_path):
    """The Strategist writes too: topic and angle become the
    headline and subline on every visual, so they pass the
    humanising pass at plan time, before they are stored."""
    from pageops.pipeline import generate_week

    store = Store(tmp_path)
    rows = generate_week(store, PlanRewritingClient(), "Brief text")
    assert "guaranteed income" not in rows[0]["topic"].lower()
    assert rows[0]["angle"] == "The honest angle"
    assert rows[0]["brief_check"] == ""


class PlanFailingClient(PlanClient):
    def humanize(self, text, brand_voice):
        raise RuntimeError("humaniser down")


def test_plan_humanizer_failure_is_recorded_on_the_row(tmp_path):
    from pageops.pipeline import generate_week

    store = Store(tmp_path)
    rows = generate_week(store, PlanFailingClient(), "Brief text")
    assert rows[0]["topic"] == "Get guaranteed income from your inbox"
    assert "[HUMANIZER FALLBACK]" in rows[0]["brief_check"]
    assert "humaniser down" in rows[0]["brief_check"]


class PlanMergingClient(PlanClient):
    def humanize(self, text, brand_voice):
        return "Both lines merged into one."


def test_plan_structure_break_keeps_the_original_lines(tmp_path):
    """If the rewrite breaks the two-line structure, the lines
    cannot be mapped back, so the originals stay and it is noted."""
    from pageops.pipeline import generate_week

    store = Store(tmp_path)
    rows = generate_week(store, PlanMergingClient(), "Brief text")
    assert rows[0]["topic"] == "Get guaranteed income from your inbox"
    assert rows[0]["angle"] == "The honest angle"
    assert "[HUMANIZER FALLBACK]" in rows[0]["brief_check"]


def test_owner_edit_is_not_humanised(tmp_path):
    store = Store(tmp_path)
    client = RewritingClient()
    updated = draft_and_check(store, client, _planned_row(store))
    assert updated["status"] == "awaiting_approval"
    client.humanize_calls = 0
    good = MockClient().generate_draft(updated, store.get_brand_voice())
    edited = edit_item(store, client, updated["id"], good["text"])
    assert edited["status"] == "awaiting_approval"
    assert client.humanize_calls == 0  # the owner's words stay the owner's
