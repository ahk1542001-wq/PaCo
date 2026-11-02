"""Pipeline for PageOps Agent: brief -> research -> plan -> draft -> check.

This module carries the two top layers of the company. The CEO
control layer sets the assignment, holds the human-approval gate and
consolidates the final report; the MAIN ORCHESTRATOR (process_week)
executes the assignment, calling one role agent per stage in
sequence. Each role has a JD scope, assigned skills and its own
tools (full spec: ARCHITECTURE.md):

Every role is self-contained: its own skills, its own tools, its own
work, and it checks its own work before passing it up.

Department 1 - Content Creation & Branding:
- Strategist / Researcher (rss.fetch_feeds via fetch_trends, then
  generate_week): feeds + insights -> trends -> 7 plan rows
- Copywriter (draft_and_check): plan row -> caption + hashtags
- Graphic Designer (designer stage, M21): draft -> template-built visual
- Brand Checker (checker.check_draft): draft -> pass/fail with quoted
  evidence, then a model verdict
- (Human approval gate; the CEO never crosses it alone. The gate is
  also the department boundary: checked drafts cross into Department 2
  only as the approved content package.)
Department 2 - Digital Marketing:
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


def _trends_for(store: Store, trends_fetcher) -> list | None:
    """Fetch + snapshot trends when a fetcher is supplied.

    Trends are an input, never a gate: a dead feed returns None and
    the week is planned without them.
    """
    if trends_fetcher is None:
        return None
    try:
        return fetch_trends(store=store, fetcher=trends_fetcher)
    except Exception:
        return None


def generate_week(
    store: Store, client, brief_text: str, trends: list | None = None
) -> list[dict]:
    """Generate the content plan for one brief and store each post.

    Research first: current trends (already fetched by the
    orchestrator) and the long-term loop - the Analyst's latest
    history summary as context - both reach the planner, so this
    plan is built on what is happening and what worked before.
    """
    from .context import latest_analyst_summary

    brand = store.get_brand_voice()
    plan = client.generate_plan(
        brief_text, brand, context=latest_analyst_summary(store), trends=trends
    )
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
        # The handoff chain has a named state for this moment.
        store.update_row("plan", item["id"], {"status": "visual_ready"})
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
    """Reject an undecided item; the reason is kept on the card.

    The reason is required: a rejection without one teaches the
    team nothing, and the spec keeps the reason on the card.
    """
    if not reason.strip():
        raise ValueError("A rejection needs a reason; it is kept on the card.")
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


def link_post(store: Store, row_id: str, post_id: str) -> dict:
    """Attach the published post's ID to its plan row.

    The scheduling queue ID and the platform post ID are different
    identifiers; this is the honest join between them, made when
    the post exists. Only a scheduled row can gain a post.
    """
    row = _get_row(store, row_id)
    if row.get("status") != "scheduled":
        raise PermissionError(
            f"Plan item {row_id} has status {row.get('status')!r}; "
            "only scheduled items can be linked to a published post."
        )
    return store.update_row("plan", row["id"], {"post_id": post_id})


def report_week(store: Store, goal: str = "", client=None) -> dict:
    """The Analyst's stage act: build the report and record it.

    Recording means two writes: linked scheduled rows whose posts
    are in the metrics store become "reported", and the period
    joins the Analyst's history that feeds the next plan.
    """
    from .context import append_analyst_history, save_last_report
    from .report import build_report

    report = build_report(store, goal=goal, client=client)
    save_last_report(store, report["narrative"])
    covered = {r.get("post_id", "") for r in store.read_dataset("metrics")}
    for row in store.read_dataset("plan"):
        post_id = row.get("post_id", "")
        if row.get("status") == "scheduled" and post_id and post_id in covered:
            store.update_row("plan", row["id"], {"status": "reported"})
    append_analyst_history(store, report["stats"])
    return report


def last_report(store: Store) -> str:
    """The latest recorded report narrative ("" until one runs)."""
    from .context import load_last_report

    return load_last_report(store)


def current_report(store: Store) -> dict:
    """The Analyst's report, requested through the pipeline."""
    from .report import build_report

    return build_report(store)


def run_brief(store: Store, client, brief_row_id: str, trends_fetcher=None) -> list[dict]:
    """Run the pipeline for one brief card already on the board.

    The dashboard's Run action goes through here, so the sequence
    (plan, then draft + check per post, brief marked planned) is
    assembled by the orchestrator, never by the handler.
    """
    brief_row = _get_row(store, brief_row_id)
    trends = _trends_for(store, trends_fetcher)
    rows = generate_week(store, client, brief_row.get("brief", ""), trends=trends)
    drafted = [draft_and_check(store, client, row) for row in rows]
    store.update_row("plan", brief_row["id"], {"status": "planned"})
    return drafted


def process_week(
    store: Store, client, brief_text: str, trends_fetcher=None
) -> list[dict]:
    """Full mock-safe run: brief, research, plan, draft + check each post."""
    intake_brief(store, brief_text)
    trends = _trends_for(store, trends_fetcher)
    rows = generate_week(store, client, brief_text, trends=trends)
    return [draft_and_check(store, client, row) for row in rows]
