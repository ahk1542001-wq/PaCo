"""Audience analysis (owner's rule: everything done by hand must
live in the product, 2026-11-04). The manual FYF page audit read
the insights by hand (745 views vs 1,246 prior, 15 followers);
the product form is a snapshots dataset with an ingest, period
deltas computed in code with their bases quoted, two efficiency
ratios, a figure-checked model read, and a Strategist summary.
"""
from pageops.audience import analyse_audience, build_audience_analysis, import_insights
from pageops.context import latest_analyst_summary, load_last_audience_analysis
from pageops.model_client import MockClient
from pageops.pipeline import run_audience_analysis
from pageops.store import Store

PRIOR = {"period_end": "2026-08-05", "followers": 14, "views": 1246,
         "unique_viewers": 386, "engagements": 59, "profile_visits": 37,
         "new_followers": 1, "unfollowers": 0}
LATEST = {"period_end": "2026-11-03", "followers": 15, "views": 745,
          "unique_viewers": 115, "engagements": 29, "profile_visits": 23,
          "new_followers": 1, "unfollowers": 0}


def test_import_dedupes_and_deltas_are_exact(tmp_path):
    store = Store(tmp_path)
    assert import_insights(store, [PRIOR, LATEST]) == 2
    assert import_insights(store, [LATEST]) == 0
    analysis = analyse_audience(store)
    views = analysis["deltas"]["views"]
    assert views == {"from": 1246, "to": 745, "change": -501, "pct": -40.2}
    assert analysis["deltas"]["followers"]["change"] == 1
    assert analysis["ratios"]["engagements_per_100_views"] == 3.9
    assert analysis["ratios"]["followers_per_100_visits"] == 4.3


def test_text_quotes_bases_and_read_is_kept(tmp_path):
    store = Store(tmp_path)
    import_insights(store, [PRIOR, LATEST])
    result = build_audience_analysis(store, client=MockClient())
    assert "15 followers" in result["text"]
    assert "from 1246 to 745" in result["text"]
    assert "Read:" in result["text"]


class RogueClient(MockClient):
    def audience_read(self, analysis_text, brand_voice):
        return "The page will surely reach 1000000 followers soon."


def test_rogue_read_is_dropped(tmp_path):
    store = Store(tmp_path)
    import_insights(store, [PRIOR, LATEST])
    result = build_audience_analysis(store, client=RogueClient())
    assert "[READ DROPPED]" in result["text"]


def test_stage_records_and_feeds_the_strategist(tmp_path):
    store = Store(tmp_path)
    import_insights(store, [PRIOR, LATEST])
    result = run_audience_analysis(store, client=MockClient())
    assert load_last_audience_analysis(store) == result["text"]
    summary = latest_analyst_summary(store)
    assert "Audience:" in summary
    assert "15 followers" in summary


def test_single_snapshot_is_a_level_not_a_trend(tmp_path):
    store = Store(tmp_path)
    import_insights(store, [LATEST])
    result = build_audience_analysis(store)
    assert "a level, not a trend" in result["text"]


def test_empty_store_is_clean(tmp_path):
    store = Store(tmp_path)
    result = build_audience_analysis(store)
    assert "no insights snapshots yet" in result["text"]
