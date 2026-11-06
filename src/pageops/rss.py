"""RSS trend fetcher for PageOps Agent.

Feed URLs resolve, in order: an explicit feeds file; the brand's
own rss_feeds key (';'-separated URLs, set in the dashboard brand
panel); the store's own feeds.txt (one URL per line, '#' comments
allowed); and, with no store in play, the repo-default
data/feeds.txt — the historical behaviour, unchanged. Returns
simple title / link / summary items per feed. Network access only
happens when fetch_feeds() is called.
"""

from __future__ import annotations

from pathlib import Path

from .config import DEFAULT_DATA_DIR

DEFAULT_FEEDS_FILE = DEFAULT_DATA_DIR / "feeds.txt"


def _brand_feed_urls(store) -> list[str]:
    raw = {r["key"]: r["value"] for r in store.read_dataset("brand_voice")}
    return [u.strip() for u in (raw.get("rss_feeds") or "").split(";") if u.strip()]


def read_feed_urls(
    feeds_file: Path | str | None = None, store=None
) -> list[str]:
    if feeds_file:
        path = Path(feeds_file)
    elif store is not None:
        brand_urls = _brand_feed_urls(store)
        if brand_urls:
            return brand_urls
        path = Path(store.data_dir) / "feeds.txt"
    else:
        path = DEFAULT_FEEDS_FILE
    if not path.exists():
        return []
    urls = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            urls.append(line)
    return urls


def fetch_feeds(
    feeds_file: Path | str | None = None, limit_per_feed: int = 5, store=None
) -> list[dict]:
    """Fetch every configured feed and return a flat list of items."""
    import feedparser  # lazy import so the rest of the app never needs it

    items: list[dict] = []
    for url in read_feed_urls(feeds_file, store=store):
        parsed = feedparser.parse(url)
        source = parsed.feed.get("title", url) if parsed.feed else url
        for entry in parsed.entries[:limit_per_feed]:
            items.append(
                {
                    "source": source,
                    "title": entry.get("title", ""),
                    "link": entry.get("link", ""),
                    "summary": entry.get("summary", "")[:300],
                }
            )
    return items
