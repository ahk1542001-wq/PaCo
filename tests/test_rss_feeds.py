"""RSS feed resolution (complete-control work, 2026-11-06).

The Strategist's feeds used to come from one hardcoded place:
the repo-default data/feeds.txt, whatever store the product was
actually running on. Resolution now runs: an explicit feeds file;
the brand's own rss_feeds key (';'-separated, set in the dashboard
brand panel); the store's own feeds.txt; and only with no store
in play, the repo-default file — the historical behaviour,
unchanged.
"""
import pageops.research as research
import pageops.rss as rss
from pageops.pipeline import fetch_trends, update_brand_voice
from pageops.store import Store


def test_brand_rss_feeds_take_precedence_over_store_feeds_file(tmp_path):
    store = Store(tmp_path)
    (tmp_path / "feeds.txt").write_text(
        "https://file.example.com/feed\n", encoding="utf-8"
    )
    update_brand_voice(
        store, "rss_feeds", "https://a.example.com/rss; https://b.example.com/rss"
    )
    assert rss.read_feed_urls(store=store) == [
        "https://a.example.com/rss",
        "https://b.example.com/rss",
    ]


def test_store_feeds_file_used_when_no_brand_key(tmp_path):
    store = Store(tmp_path)
    (tmp_path / "feeds.txt").write_text(
        "# a comment\nhttps://store.example.com/feed\n\n", encoding="utf-8"
    )
    assert rss.read_feed_urls(store=store) == ["https://store.example.com/feed"]


def test_default_feeds_file_when_no_store(tmp_path, monkeypatch):
    default = tmp_path / "feeds.txt"
    default.write_text("https://default.example.com/feed\n", encoding="utf-8")
    monkeypatch.setattr(rss, "DEFAULT_FEEDS_FILE", default)
    assert rss.read_feed_urls() == ["https://default.example.com/feed"]
    assert rss.read_feed_urls(tmp_path / "missing.txt") == []


def test_explicit_feeds_file_still_wins(tmp_path):
    store = Store(tmp_path)
    update_brand_voice(store, "rss_feeds", "https://brand.example.com/rss")
    explicit = tmp_path / "explicit.txt"
    explicit.write_text("https://explicit.example.com/feed\n", encoding="utf-8")
    assert rss.read_feed_urls(explicit, store=store) == [
        "https://explicit.example.com/feed"
    ]


def test_fetch_research_passes_the_store_to_the_rss_fallback(tmp_path, monkeypatch):
    store = Store(tmp_path)
    seen = {}

    def no_agent_reach(queries=None):
        raise RuntimeError("agent-reach CLI not installed")

    def fake_fetch_feeds(feeds_file=None, store=None):
        seen["store"] = store
        return [{"source": "F", "title": "T", "link": "L", "summary": "S"}]

    monkeypatch.setattr(research, "search_agent_reach", no_agent_reach)
    monkeypatch.setattr(rss, "fetch_feeds", fake_fetch_feeds)
    bundle = research.fetch_research(store=store)
    assert bundle["backend"] == "rss"
    assert bundle["items"][0]["title"] == "T"
    assert seen["store"] is store


def test_fetch_trends_hands_the_store_to_the_fetcher(tmp_path):
    store = Store(tmp_path)
    seen = {}

    def fetcher(feeds_file=None, brief="", store=None):
        seen["store"] = store
        return [{"title": "T", "link": "https://x.example.com"}]

    items = fetch_trends(store=store, fetcher=fetcher)
    assert items and items[0]["title"] == "T"
    assert seen["store"] is store
