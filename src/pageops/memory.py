"""Retrieval memory: the brand's own past work, searchable.

PaCo already had a summary loop (the Analyst's latest findings ride
into the next plan as a fixed summary). This module adds retrieval:
given a query - a new brief, a topic - it searches everything this
brand's store already holds (past drafts, the recorded reports and
analyses, brand-build levels, research claims) and returns the most
relevant pieces, so a plan can be written against the brand's own
history instead of only its latest summary.

Scoring is deliberately plain and inspectable: word overlap for
Latin-script text, character 4-gram overlap for Myanmar script
(Burmese does not separate words with spaces), counted per term with
the counts kept on the result. No embeddings, no external service,
nothing leaves the store. A query that matches nothing returns
nothing - retrieval never pads the context with irrelevant text.
"""

from __future__ import annotations

import re

_LATIN = re.compile(r"[a-z0-9]+")
_MYANMAR_RUN = re.compile(r"[\u1000-\u109f]+")
SNIPPET_CHARS = 500


def _terms(text: str) -> dict[str, int]:
    """Term counts for one text: Latin words + Myanmar 4-grams."""
    terms: dict[str, int] = {}
    lowered = text.lower()
    for word in _LATIN.findall(lowered):
        if len(word) >= 3:
            terms[word] = terms.get(word, 0) + 1
    for run in _MYANMAR_RUN.findall(text):
        if len(run) <= 4:
            terms[run] = terms.get(run, 0) + 1
        else:
            for i in range(len(run) - 3):
                gram = run[i : i + 4]
                terms[gram] = terms.get(gram, 0) + 1
    return terms


def collect_corpus(store) -> list[dict]:
    """Every retrievable piece of this brand's stored past work.

    Each chunk: {ref, kind, text}. Order is stable and roughly
    chronological per source, so ties in scoring fall to the most
    recently stored chunk.
    """
    from . import context

    chunks: list[dict] = []

    def add(ref: str, kind: str, text: str) -> None:
        text = (text or "").strip()
        if text:
            chunks.append({"ref": ref, "kind": kind, "text": text})

    for row in store.read_dataset("plan"):
        draft = (row.get("draft") or "").strip()
        if draft:
            topic = row.get("topic", "")
            add(
                f"plan {row.get('id', '?')}: {topic}",
                "draft",
                f"{topic}\n{draft}",
            )
    add("latest performance report", "report", context.load_last_report(store))
    add("latest visibility audit", "visibility", context.load_last_visibility(store))
    add("latest content analysis", "content", context.load_last_content_analysis(store))
    add("latest audience analysis", "audience", context.load_last_audience_analysis(store))
    summary = context.latest_analyst_summary(store)
    add("analyst summary loop", "summary", summary)
    for row in store.read_dataset("brand_build"):
        add(
            f"brand build level {row.get('level', '?')} ({row.get('status', '')})",
            "brand",
            row.get("content", ""),
        )
    for row in store.read_dataset("research"):
        add(
            f"research ({row.get('kind', '')}, {row.get('evidence', '')})",
            "research",
            f"{row.get('claim', '')} {row.get('source', '')}",
        )
    return chunks


def retrieve(store, query: str, limit: int = 3, exclude_refs=None) -> list[dict]:
    """The stored chunks most relevant to the query.

    Each result carries its score and the matched term count behind
    it. Zero-score chunks are never returned. Chunks whose ref
    starts with any of exclude_refs (ref prefixes, e.g. "plan 7:")
    are never returned -- a draft being written must not retrieve
    its own plan row's stored draft as reference material.
    """
    query_terms = _terms(query or "")
    if not query_terms:
        return []
    prefixes = tuple(exclude_refs or ())
    scored = []
    for idx, chunk in enumerate(collect_corpus(store)):
        if prefixes and chunk["ref"].startswith(prefixes):
            continue
        chunk_terms = _terms(chunk["text"])
        matched = {t: chunk_terms[t] for t in query_terms if t in chunk_terms}
        if not matched:
            continue
        scored.append(
            {
                **chunk,
                "score": float(len(matched)),
                "matched_terms": len(matched),
                "_idx": idx,
            }
        )
    # Highest score first; ties to the most recently stored chunk.
    scored.sort(key=lambda c: (c["score"], c["_idx"]), reverse=True)
    results = scored[:limit]
    for result in results:
        result.pop("_idx", None)
    return results


def retrieval_context(store, query: str, limit: int = 3, exclude_refs=None) -> str:
    """Retrieved material as a prompt-ready context block.

    Empty string when nothing in the store is relevant, so callers
    can join it with other context without leaving gaps.
    """
    hits = retrieve(store, query, limit=limit, exclude_refs=exclude_refs)
    if not hits:
        return ""
    lines = [
        "Relevant material retrieved from this brand's own stored past work "
        "(drafts, reports, analyses, brand build, research):"
    ]
    for hit in hits:
        snippet = hit["text"]
        if len(snippet) > SNIPPET_CHARS:
            snippet = snippet[:SNIPPET_CHARS].rstrip() + "..."
        lines.append(f"- [{hit['kind']}] {hit['ref']}: {snippet}")
    return "\n".join(lines)
