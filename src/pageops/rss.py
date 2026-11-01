"""RSS trend fetcher for PageOps Agent.

Reads feed URLs from data/feeds.txt (one per line, '#' comments allowed)
and returns simple title / link / summary items per feed. Network access
only happens when fetch_feeds() is called.
"""

from __future__ import annotations

from pathlib import Path

from .config import DEFAULT_DATA_DIR

DEFAULT_FEEDS_FILE = DEFAULT_DATA_DIR / "feeds.txt"


def read_feed_urls(feeds_file: Path | str | None = None) -> list[str]:
    path = Path(feeds_file) if feeds_file else DEFAULT_FEEDS_FILE
    if not path.exists():
        return []
    urls = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            urls.append(line)
    return urls


def fetch_feeds(feeds_file: Path | str | None = None, limit_per_feed: int = 5) -> list[dict]:
    """Fetch every configured feed and return a flat list of items."""
    import feedparser  # lazy import so the rest of the app never needs it

    items: list[dict] = []
    for url in read_feed_urls(feeds_file):
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
