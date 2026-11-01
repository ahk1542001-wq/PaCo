"""Pipeline for PageOps Agent: brief -> research -> plan -> draft -> check.

This module carries the two top layers of the company. The CEO
control layer sets the assignment, holds the human-approval gate and
consolidates the final report; the MAIN ORCHESTRATOR (process_week)
executes the assignment, calling one role agent per stage in
sequence. Each role has a JD scope, assigned skills and its own
tools (full spec: ARCHITECTURE.md):

Every role is self-contained: its own skills, its own tools, its own
work, and it checks its own work before passing it up.

Department 1 — Content Creation & Branding:
- Strategist / Researcher (rss.fetch_feeds via fetch_trends, then
  generate_week): feeds + insights -> trends -> 7 plan rows
- Copywriter (draft_and_check): plan row -> caption + hashtags
- Graphic Designer (designer stage, M21): draft -> template-built visual
- Brand Checker (checker.check_draft): draft -> pass/fail with quoted
  evidence, then a model verdict
- (Human approval gate; the CEO never crosses it alone. The gate is
  also the department boundary: checked drafts cross into Department 2
  only as the approved content package.)
Department 2 — Digital Marketing:
- Scheduler / Publisher (scheduler.schedule_item): approved -> queue ID
- Performance Analyst (report.build_report): metrics -> report

Layering rule: roles never call each other. Every handoff between
roles flows through this orchestrator and the store, and stages run
in sequence, step to step.

Every stage writes its state to the store, so the dashboard board is a
live view of real pipeline state. Model calls go through the client
interface (mock by default); the brand-rule checker is deterministic
code. A draft that fails the checker is revised once, then flagged.
"""

from __future__ import annotations

from .checker import check_draft
from .store import Store


def intake_brief(store: Store, brief_text: str) -> dict:
    """Record an incoming brief as a plan row in the Brief column."""
    return store.add_plan_row({"status": "brief_received", "brief": brief_text})


def fetch_trends(feeds_file=None, fetcher=None, limit: int = 5) -> list[dict]:
    """Trend items with source links. Network only via the real fetcher."""
    if fetcher is None:
        from .rss import fetch_feeds

        fetcher = fetch_feeds
    return fetcher(feeds_file)[:limit]


def generate_week(store: Store, client, brief_text: str) -> list[dict]:
    """Generate the content plan for one brief and store each post."""
    brand = store.get_brand_voice()
    plan = client.generate_plan(brief_text, brand)
    rows = []
    for post in plan.get("posts", []):
        rows.append(
            store.add_plan_row(
                {
                    "date": post.get("day", ""),
                    "platform": post.get("platform", ""),
                    "topic": post.get("topic", ""),
                    "angle": post.get("angle", ""),
                    "format": post.get("format", ""),
                    "status": "planned",
                    "brief": brief_text,
                }
            )
        )
    return rows


def _full_text(draft: dict) -> str:
    text = draft.get("text", "")
    tags = [t for t in draft.get("hashtags", []) if t and t not in text]
    if tags:
        text = (text + " " + " ".join(tags)).strip()
    return text


def draft_and_check(store: Store, client, row: dict) -> dict:
    """Draft one plan item, run the checker, revise once on failure.

    Ends with status awaiting_approval (checks passed) or checked
    (still failing after the single revision, flagged for the human).
    The checker's summary is stored on the row as quoted evidence.
    """
    brand = store.get_brand_voice()
    item = dict(row)
    draft = client.generate_draft(item, brand)
    text = _full_text(draft)
    result = check_draft(text, item.get("platform", ""), brand)
    if not result.passed:
        item["revision_feedback"] = result.summary()
        draft = client.generate_draft(item, brand)
        text = _full_text(draft)
        result = check_draft(text, item.get("platform", ""), brand)
    summary = result.summary()
    status = "checked"
    if result.passed:
        # Deterministic rules passed; Muse Wonder gives the judgement
        # verdict. A "revise" verdict flags the card for the human
        # instead of letting it through to approval.
        verdict = client.verdict({"text": text, "platform": item.get("platform", "")}, summary)
        reasons = "; ".join(verdict.get("reasons", []))
        summary += f"\n[MODEL VERDICT] {verdict.get('verdict', '')} - {reasons}"
        status = "awaiting_approval" if verdict.get("verdict") == "pass" else "checked"
    return store.update_row(
        "plan",
        row["id"],
        {"draft": text, "check_status": summary, "status": status},
    )


def process_week(store: Store, client, brief_text: str) -> list[dict]:
    """Full mock-safe run: brief, plan, then draft + check for each post."""
    intake_brief(store, brief_text)
    rows = generate_week(store, client, brief_text)
    return [draft_and_check(store, client, row) for row in rows]
