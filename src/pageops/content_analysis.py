"""Content analysis for PaCo Agent.

The Analyst's third instrument: which content worked, broken
down by topic and by format. Every measured post is joined back
to its plan row for topic and format; a post with no plan row
falls back to the topic and format its metrics note records,
and the join coverage is stated in the output so partial joins
never masquerade as complete ones. Groups are ranked by
engagement rate with raw totals quoted alongside. The model's
interpretation is humanised and figure-checked against the
computed groups, like every Analyst output.
"""

from __future__ import annotations

import re

from .metrics import _num
from .model_client import humanize_text
from .store import Store

_FORMAT_WORDS = ("carousel", "video", "reel", "photo")


def _from_note(note: str) -> tuple[str, str]:
    """(format, topic) parsed from a metrics note, or defaults."""
    low = (note or "").lower()
    fmt = next((w for w in _FORMAT_WORDS if w in low), "post")
    match = re.search(r"post on (.+)$", note or "", re.IGNORECASE)
    topic = match.group(1).strip() if match else "untitled"
    return fmt, topic


def _rate(engagement: int, reach: int) -> float:
    return round(100 * engagement / reach, 1) if reach else 0.0


def analyse_content(store: Store) -> dict:
    """Deterministic per-topic and per-format aggregation."""
    plan_by_post = {
        r.get("post_id", ""): r
        for r in store.read_dataset("plan")
        if r.get("post_id")
    }
    posts = []
    linked = 0
    for row in store.read_dataset("metrics"):
        plan = plan_by_post.get(row.get("post_id", ""))
        if plan:
            linked += 1
            topic = plan.get("topic") or "untitled"
            fmt = plan.get("format") or "post"
        else:
            fmt, topic = _from_note(row.get("notes", ""))
        posts.append(
            {
                "post_id": row.get("post_id", ""),
                "topic": topic,
                "format": fmt,
                "reach": _num(row.get("reach")),
                "engagement": _num(row.get("engagement")),
                "clicks": _num(row.get("clicks")),
            }
        )

    def groups(key: str) -> list[dict]:
        by: dict[str, dict] = {}
        for post in posts:
            group = by.setdefault(
                post[key],
                {"name": post[key], "posts": 0, "reach": 0, "engagement": 0, "clicks": 0},
            )
            group["posts"] += 1
            group["reach"] += post["reach"]
            group["engagement"] += post["engagement"]
            group["clicks"] += post["clicks"]
        out = list(by.values())
        for group in out:
            group["rate"] = _rate(group["engagement"], group["reach"])
        out.sort(key=lambda g: (-g["rate"], -g["engagement"], g["name"]))
        return out

    return {
        "posts": posts,
        "linked": linked,
        "by_topic": groups("topic"),
        "by_format": groups("format"),
    }


def _numbers(text: str) -> set[int]:
    return {int(n.replace(",", "")) for n in re.findall(r"\d[\d,]*", text)}


def build_content_analysis(store: Store, client=None) -> dict:
    """Return {analysis, text}. Pure; recording is the pipeline stage."""
    brand = store.get_brand_voice()
    analysis = analyse_content(store)
    posts = analysis["posts"]
    if not posts:
        return {
            "analysis": analysis,
            "text": "Content analysis: no measured posts yet; publish and ingest metrics first.",
        }
    lines = [
        f"Content analysis over {len(posts)} measured post(s); "
        f"{analysis['linked']}/{len(posts)} joined to plan rows."
    ]
    for label, key in (("topic", "by_topic"), ("format", "by_format")):
        for group in analysis[key]:
            lines.append(
                f"By {label}: {group['name']} - {group['posts']} post(s), "
                f"reach {group['reach']}, engagement {group['engagement']}, "
                f"rate {group['rate']}%"
            )
    topics = analysis["by_topic"]
    if topics:
        best = topics[0]
        lines.append(
            f"Strongest topic: {best['name']} at {best['rate']}% engagement "
            f"rate across {best['posts']} post(s)."
        )
        if len(topics) > 1:
            worst = topics[-1]
            lines.append(
                f"Weakest topic: {worst['name']} at {worst['rate']}% "
                f"engagement rate across {worst['posts']} post(s)."
            )
    text = "\n".join(lines)
    if client is not None:
        read = client.content_read(text, brand)
        read, humanize_error = humanize_text(client, read, brand)
        if humanize_error:
            text += f"\n[HUMANIZER FALLBACK] content read unedited ({humanize_error})"
        if _numbers(read) <= _numbers(text):
            text += f"\nRead: {read}"
        else:
            text += (
                "\n[READ DROPPED] the model's content read cited "
                "figures outside the computed groups."
            )
    return {"analysis": analysis, "text": text}
