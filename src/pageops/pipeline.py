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
from .designer import produce_visual
from .store import Store


def intake_brief(store: Store, brief_text: str) -> dict:
    """Record an incoming brief as a plan row in the Brief column."""
    return store.add_plan_row({"status": "brief_received", "brief": brief_text})


def fetch_trends(store=None, feeds_file=None, fetcher=None, limit: int = 5) -> list[dict]:
    """Trend items with source links. Network only via the real fetcher.

    When a store is given, the fetched trends are snapshotted into
    the Strategist's private notes (the private context layer).
    """
    if fetcher is None:
        from .rss import fetch_feeds

        fetcher = fetch_feeds
    items = fetcher(feeds_file)[:limit]
    if store is not None:
        from .context import save_trend_notes

        save_trend_notes(store, items)
    return items


def generate_week(store: Store, client, brief_text: str) -> list[dict]:
    """Generate the content plan for one brief and store each post.

    The long-term loop: the Analyst's latest history summary goes to
    the planner as context, so last period's results shape this plan.
    """
    from .context import latest_analyst_summary

    brand = store.get_brand_voice()
    plan = client.generate_plan(brief_text, brand, context=latest_analyst_summary(store))
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
    # The draft now exists: record it before the check completes, so
    # the board's Drafted column and the write log show the real
    # progression instead of a jump from planned to checked.
    store.update_row("plan", row["id"], {"draft": text, "status": "drafted"})
    summary, status = _review_tail(store, client, item, text, summary, result.passed)
    return store.update_row(
        "plan",
        row["id"],
        {"check_status": summary, "status": status},
    )


def _review_tail(
    store: Store, client, item: dict, text: str, summary: str, rules_passed: bool
) -> tuple[str, str]:
    """Visuals + model verdict for a settled draft text.

    Shared by draft_and_check and edit_item, so an edited draft goes
    through exactly the same judgement as a fresh one. Returns the
    extended evidence summary and the final status.
    """
    # Visuals stage (Graphic Designer): the visual is produced from
    # the final draft text, self-checked for template compliance, and
    # its evidence joins the check evidence for the human. A failed
    # visual flags the item instead of letting it through.
    visual_ok = False
    try:
        updated = produce_visual(store, {**item, "draft": text})
        visual_note = f"[VISUAL] PASS - {updated.get('visual', '')}"
        visual_ok = True
    except (ValueError, RuntimeError) as exc:
        visual_note = f"[VISUAL] FAIL - {exc}"
    summary += f"\n{visual_note}"
    status = "checked"
    if rules_passed and visual_ok:
        # Deterministic rules passed; the judge model gives the
        # judgement verdict. A "revise" verdict flags the card for
        # the human instead of letting it through to approval.
        verdict = client.verdict({"text": text, "platform": item.get("platform", "")}, summary)
        reasons = "; ".join(verdict.get("reasons", []))
        summary += f"\n[MODEL VERDICT] {verdict.get('verdict', '')} - {reasons}"
        status = "awaiting_approval" if verdict.get("verdict") == "pass" else "checked"
    return summary, status


def _get_row(store: Store, row_id: str) -> dict:
    rows = {r["id"]: r for r in store.read_dataset("plan")}
    row = rows.get(str(row_id))
    if row is None:
        raise KeyError(f"No plan row with id {row_id}")
    return row


def approve_item(store: Store, row_id: str) -> dict:
    """The human gate, enforced here: only awaiting_approval approves.

    A checked item (failed rules or a revise verdict) can never be
    approved into the scheduling queue from any caller.
    """
    row = _get_row(store, row_id)
    if row.get("status") != "awaiting_approval":
        raise PermissionError(
            f"Plan item {row_id} has status {row.get('status')!r}; "
            "only 'awaiting_approval' items can be approved."
        )
    return store.update_row("plan", row["id"], {"status": "approved"})


def reject_item(store: Store, row_id: str, reason: str = "") -> dict:
    """Reject an undecided item; the reason is kept on the card."""
    row = _get_row(store, row_id)
    if row.get("status") not in ("awaiting_approval", "checked"):
        raise PermissionError(
            f"Plan item {row_id} has status {row.get('status')!r}; "
            "only undecided items can be rejected."
        )
    return store.update_row(
        "plan", row["id"], {"status": "rejected", "reject_reason": reason}
    )


def edit_item(store: Store, client, row_id: str, new_text: str) -> dict:
    """Apply a human edit, then re-check AND re-verdict the new text.

    Editing is a pre-approval act: approved or scheduled content is
    locked. The edited text is never promoted on the checker alone.
    """
    row = _get_row(store, row_id)
    if row.get("status") not in ("awaiting_approval", "checked"):
        raise PermissionError(
            f"Plan item {row_id} has status {row.get('status')!r}; "
            "only items awaiting a decision can be edited."
        )
    brand = store.get_brand_voice()
    result = check_draft(new_text, row.get("platform", ""), brand)
    store.update_row("plan", row["id"], {"draft": new_text, "status": "drafted"})
    summary, status = _review_tail(
        store, client, row, new_text, result.summary(), result.passed
    )
    return store.update_row(
        "plan", row["id"], {"check_status": summary, "status": status}
    )


def schedule_approved(store: Store, row_id: str) -> dict:
    """Scheduling goes through the pipeline (the gate lives in scheduler)."""
    from .scheduler import BufferClient, schedule_item

    return schedule_item(store, row_id, BufferClient())


def current_report(store: Store) -> dict:
    """The Analyst's report, requested through the pipeline."""
    from .report import build_report

    return build_report(store)


def process_week(store: Store, client, brief_text: str) -> list[dict]:
    """Full mock-safe run: brief, plan, then draft + check for each post."""
    intake_brief(store, brief_text)
    rows = generate_week(store, client, brief_text)
    return [draft_and_check(store, client, row) for row in rows]
