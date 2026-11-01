"""Research stage wiring (M18 fix, PR #6).

The pipeline story starts with research: trends fetched through
the orchestrator reach the planner, are snapshotted into the
Strategist's private notes, and never gate the run (a dead feed
must not stop a week of content).
"""
from pageops.model_client import MockClient
from pageops.pipeline import generate_week, process_week
from pageops.context import load_trend_notes
from pageops.store import Store

FAKE_TRENDS = [
    {"title": "AI agents in small business", "link": "https://example.com/a"},
    {"title": "Chatbots for page sellers", "link": "https://example.com/b"},
]


def fake_fetcher(feeds_file=None):
    return list(FAKE_TRENDS)


def broken_fetcher(feeds_file=None):
    raise RuntimeError("feed unreachable")


SENTINEL = object()


class TrendSpy(MockClient):
    def __init__(self):
        # Sentinel, not None: lets the hermetic test distinguish
        # "planner called with trends=None" from "never called".
        self.trends = SENTINEL

    def generate_plan(self, brief, brand_voice, context="", trends=None):
        self.trends = trends
        return super().generate_plan(brief, brand_voice, context=context, trends=trends)


def test_process_week_threads_trends_to_the_planner(tmp_path):
    store = Store(tmp_path)
    spy = TrendSpy()
    rows = process_week(store, spy, "Weekly brief", trends_fetcher=fake_fetcher)
    assert spy.trends == FAKE_TRENDS
    assert len(rows) == 7
    assert load_trend_notes(store) == FAKE_TRENDS


def test_process_week_without_fetcher_stays_hermetic(tmp_path):
    store = Store(tmp_path)
    spy = TrendSpy()
    rows = process_week(store, spy, "Weekly brief")
    assert spy.trends is None
    assert len(rows) == 7


def test_broken_feed_never_gates_the_run(tmp_path):
    store = Store(tmp_path)
    rows = process_week(store, MockClient(), "Weekly brief", trends_fetcher=broken_fetcher)
    assert len(rows) == 7
    assert all(r["status"] == "awaiting_approval" for r in rows)


def test_run_brief_survives_a_broken_feed(tmp_path):
    # run_brief is the dashboard's entry point; the no-gate rule
    # must hold there too, not only in process_week.
    from pageops.pipeline import intake_brief, run_brief

    store = Store(tmp_path)
    brief = intake_brief(store, "Weekly brief")
    rows = run_brief(store, MockClient(), brief["id"], trends_fetcher=broken_fetcher)
    assert len(rows) == 7


def test_generate_week_threads_trends(tmp_path):
    store = Store(tmp_path)
    spy = TrendSpy()
    generate_week(store, spy, "Brief", trends=FAKE_TRENDS)
    assert spy.trends == FAKE_TRENDS


def test_mock_plan_is_a_full_week():
    plan = MockClient().generate_plan("b", {"brand_name": "FYF AI"})
    days = [p["day"] for p in plan["posts"]]
    assert len(days) == 7 and len(set(days)) == 7
