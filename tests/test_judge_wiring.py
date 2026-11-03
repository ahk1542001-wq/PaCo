"""Judge wiring (Model map, PR #10; judge changed 2026-11-03).

Verdicts are Muse Wonder's job, in a dedicated judge pass: the
owner moved every big-decision role to Wonder, so the judge is a
Wonder client of its own (never the drafting client object), and
the deterministic checker in code is the independent layer under
the verdict. The pipeline takes an optional judge client; without
one (mock mode, or meta mode with no key configured), the drafting
client gives the verdict, exactly as before. The Baseten route
(Muse Spark Open) stays in the code as an optional alternate; its
verdict calls run at LOW reasoning effort.
"""
import httpx
import pytest

from pageops.model_client import (
    BASE_URL,
    MODEL_SPARK_OPEN,
    MODEL_WONDER,
    MetaModelClient,
    MockClient,
    get_baseten_client,
    get_judge_client,
)
from pageops.pipeline import draft_and_check
from pageops.store import Store


class SpyClient(MockClient):
    def __init__(self):
        self.verdict_calls = 0

    def verdict(self, draft, check_summary):
        self.verdict_calls += 1
        return super().verdict(draft, check_summary)


def _planned_row(store):
    return store.add_plan_row(
        {"platform": "facebook", "topic": "Judge topic", "status": "planned"}
    )


def test_verdict_comes_from_the_judge_when_configured(tmp_path):
    store = Store(tmp_path)
    main, judge = SpyClient(), SpyClient()
    row = _planned_row(store)
    updated = draft_and_check(store, main, row, judge=judge)
    assert judge.verdict_calls == 1
    assert main.verdict_calls == 0
    assert updated["status"] == "awaiting_approval"


def test_without_a_judge_the_drafting_client_verdicts(tmp_path):
    store = Store(tmp_path)
    main = SpyClient()
    row = _planned_row(store)
    draft_and_check(store, main, row)
    assert main.verdict_calls == 1


def test_judge_client_absent_in_mock_mode(monkeypatch):
    monkeypatch.setenv("MODEL_MODE", "mock")
    monkeypatch.setenv("MODEL_API_KEY", "test-key")
    assert get_judge_client() is None


def test_judge_client_absent_without_a_meta_key(monkeypatch):
    monkeypatch.setenv("MODEL_MODE", "meta")
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    assert get_judge_client() is None


def test_judge_client_is_a_dedicated_wonder_client(monkeypatch):
    monkeypatch.setenv("MODEL_MODE", "meta")
    monkeypatch.setenv("MODEL_API_KEY", "test-key")
    monkeypatch.delenv("PAGEOPS_MAIN_MODEL", raising=False)
    judge = get_judge_client()
    assert judge is not None
    assert isinstance(judge, MetaModelClient)
    assert judge.base_url == BASE_URL
    assert judge.verdict_model == MODEL_WONDER
    # The Meta route is not forced into Baseten-specific settings:
    # no reasoning_effort is sent on verdict calls.
    assert judge.reasoning_effort is None


def test_wonder_judge_verdict_flows_through_the_pipeline(tmp_path, monkeypatch):
    """The factory-built Wonder judge gives the verdict end to end:
    a [MODEL VERDICT] from the judge, not a [JUDGE FALLBACK]."""
    monkeypatch.setenv("MODEL_MODE", "meta")
    monkeypatch.setenv("MODEL_API_KEY", "test-key")
    monkeypatch.setenv("PAGEOPS_DATA_DIR", str(tmp_path / "data"))

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "choices": [
                    {"message": {"content": '{"verdict": "pass", "reasons": ["Reads clean."]}'}}
                ],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
            }

    monkeypatch.setattr(httpx, "post", lambda *a, **k: FakeResponse())

    store = Store(tmp_path)
    main = SpyClient()
    judge = get_judge_client()
    assert judge is not None
    assert judge is not main
    row = _planned_row(store)
    updated = draft_and_check(store, main, row, judge=judge)
    assert main.verdict_calls == 0
    assert updated["status"] == "awaiting_approval"
    assert "[MODEL VERDICT] pass" in updated["check_status"]
    assert "[JUDGE FALLBACK]" not in updated["check_status"]


def test_judge_calls_send_low_reasoning_effort(monkeypatch):
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "choices": [
                    {"message": {"content": '{"verdict": "pass", "reasons": []}'}}
                ],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
            }

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["json"] = json
        return FakeResponse()

    monkeypatch.setattr(httpx, "post", fake_post)
    judge = get_baseten_client(api_key="<redacted>")
    judge.verdict({"text": "x", "platform": "facebook"}, "summary")
    assert captured["json"]["reasoning_effort"] == "low"
    assert captured["json"]["model"] == MODEL_SPARK_OPEN



class ExplodingJudge(MockClient):
    def verdict(self, draft, check_summary):
        raise RuntimeError("judge timeout")


def test_failing_judge_falls_back_visibly(tmp_path):
    store = Store(tmp_path)
    row = _planned_row(store)
    updated = draft_and_check(store, MockClient(), row, judge=ExplodingJudge())
    assert updated["status"] == "awaiting_approval"
    assert "[JUDGE FALLBACK]" in updated["check_status"]
    assert "[MODEL VERDICT] pass" in updated["check_status"]


def test_edit_routes_its_verdict_to_the_judge(tmp_path):
    from pageops.pipeline import edit_item

    store = Store(tmp_path)
    row = store.add_plan_row(
        {"platform": "facebook", "topic": "T", "status": "checked", "draft": "Old. Message us."}
    )
    judge = SpyClient()
    updated = edit_item(
        store,
        MockClient(),
        row["id"],
        "Edited and clean. Message us to get started. #FYFAI #AIAutomation #SME",
        judge=judge,
    )
    assert judge.verdict_calls == 1
    assert updated["status"] == "awaiting_approval"



def test_same_object_judge_is_treated_as_no_judge(tmp_path):
    store = Store(tmp_path)
    row = _planned_row(store)
    main = SpyClient()
    updated = draft_and_check(store, main, row, judge=main)
    assert main.verdict_calls == 1  # the drafting client verdicts
    assert updated["status"] == "awaiting_approval"
