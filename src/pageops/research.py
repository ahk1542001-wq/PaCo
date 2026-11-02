"""Research backends for the Strategist stage (optional Agent-Reach).

Trend discovery tries, in order:

1. Agent-Reach web search (Exa semantic search) when the
   ``agent-reach`` CLI is installed and healthy. Agent-Reach is an
   external local tool, not a product dependency: a machine without
   it must run exactly as before.
2. The RSS feeds (``rss.fetch_feeds``), the standing fallback.

Whichever backend answered is recorded on the returned bundle and in
the trend-notes snapshot, so a fallback is always stated, never
silent. Items keep the RSS shape ({source, title, link, summary}) so
the rest of the pipeline cannot tell the backends apart.

Binary resolution order: $PAGEOPS_AGENT_REACH_BIN, then PATH, then
the known local install under ~/workspace/tools (a local-dev
convenience on the build VM; absent anywhere else, which is fine).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

QUERIES = (
    "social media marketing trends for small business pages",
    "AI chatbots for small business customer messaging",
    "Facebook page content trends this month",
)

_LOCAL_CANDIDATE = (
    Path.home() / "workspace" / "tools" / "agent-reach-venv" / "bin" / "agent-reach"
)


def find_agent_reach() -> str | None:
    """The agent-reach binary path, or None when not installed."""
    configured = os.environ.get("PAGEOPS_AGENT_REACH_BIN", "").strip()
    if configured:
        return configured if Path(configured).exists() else None
    on_path = shutil.which("agent-reach")
    if on_path:
        return on_path
    if _LOCAL_CANDIDATE.exists():
        return str(_LOCAL_CANDIDATE)
    return None


def _search_once(binary: str, query: str, limit: int) -> list[dict]:
    """One Agent-Reach web search, mapped to the RSS item shape."""
    env = {k: v for k, v in os.environ.items() if k.lower() != "no_proxy"}
    proc = subprocess.run(
        [binary, "web", "search", query, "--limit", str(limit)],
        capture_output=True,
        text=True,
        timeout=45,
        env=env,
    )
    # The CLI prints its JSON envelope even on failure (exit 1), and
    # the envelope carries the precise reason; read it before
    # falling back to the bare exit code, so the recorded fallback
    # reason is the real one.
    try:
        payload = json.loads(proc.stdout)
    except (json.JSONDecodeError, ValueError):
        payload = None
    if payload is not None and not payload.get("ok"):
        error = payload.get("error") or {}
        raise RuntimeError(
            f"agent-reach search failed: {error.get('code', 'unknown')} "
            f"{error.get('message', '')}".strip()
        )
    if proc.returncode != 0:
        raise RuntimeError(f"agent-reach exited {proc.returncode}")
    if payload is None:
        raise RuntimeError("agent-reach returned unparseable output")
    items = []
    for raw in payload.get("items", []):
        link = raw.get("url") or raw.get("link") or ""
        summary = raw.get("snippet") or raw.get("summary") or raw.get("text") or ""
        items.append(
            {
                "source": raw.get("source") or "agent-reach/exa",
                "title": raw.get("title", ""),
                "link": link,
                "summary": summary[:300],
            }
        )
    return items


def search_agent_reach(queries=QUERIES, limit_per_query: int = 3) -> list[dict]:
    """All Agent-Reach trend items, or a raised error explaining why not."""
    binary = find_agent_reach()
    if binary is None:
        raise RuntimeError("agent-reach CLI not installed on this machine")
    items: list[dict] = []
    seen: set[str] = set()
    for query in queries:
        for item in _search_once(binary, query, limit_per_query):
            if item["link"] and item["link"] not in seen:
                seen.add(item["link"])
                items.append(item)
    if not items:
        raise RuntimeError("agent-reach search returned no items")
    return items


def fetch_research(feeds_file=None, queries=QUERIES) -> dict:
    """Trend bundle: Agent-Reach first, RSS fallback, provenance kept.

    Returns {"items": [...], "backend": "agent-reach" | "rss",
    "detail": str}. Never raises for a research failure: the RSS
    fallback is part of the contract, and if even that fails the
    caller (pipeline) treats trends as absent, as before.
    """
    try:
        items = search_agent_reach(queries=queries)
        return {
            "items": items,
            "backend": "agent-reach",
            "detail": "Exa web search via the agent-reach CLI",
        }
    except Exception as exc:
        from .rss import fetch_feeds

        return {
            "items": fetch_feeds(feeds_file),
            "backend": "rss",
            "detail": f"agent-reach unavailable ({exc}); RSS feeds used",
        }
