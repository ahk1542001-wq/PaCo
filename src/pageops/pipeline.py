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

from .checker import PLATFORM_LIMITS, check_draft, trim_to_cap
from .designer import produce_visual
from .model_client import humanize_text, shorten_text
from .store import Store


BRIEF_FIELDS = ("goal", "offer", "dates", "notes")

BRAND_KEYS = (
    "brand_name", "services", "audience", "tone", "rules",
    "required_hashtags", "banned_phrases", "cta_markers",
    "character_name", "character_image", "character_rules",
    "character_sheet", "brand_colors", "brand_fonts", "logo_usage",
    "positioning", "journey",
    "template_sizes", "proof_baseline", "min_caption_chars", "voice_samples",
    "postiz_integration_facebook", "postiz_integration_instagram",
    "postiz_integration_tiktok", "postiz_integration_threads",
    "postiz_integration_x", "postiz_enabled_facebook",
    "postiz_enabled_instagram", "postiz_enabled_tiktok",
    "postiz_enabled_threads", "postiz_enabled_x",
    "postiz_base_url", "postiz_api_key",
    "fb_page_id", "fb_access_token",
    "heartbeat_weekday", "heartbeat_time", "heartbeat_timezone",
    "rss_feeds",
)


def intake_brief(store: Store, brief_text: str, fields: dict | None = None) -> dict:
    """Record an incoming brief as a plan row in the Brief column.

    With form fields, the brief is also restated in structured form
    on the row (brief_check), with anything missing flagged by name,
    so a thin brief is visible before the pipeline spends on it.
    """
    row = {"status": "brief_received", "brief": brief_text}
    if fields is not None:
        present, missing = [], []
        for key in BRIEF_FIELDS:
            value = (fields.get(key) or "").strip()
            if value:
                present.append(f"{key.capitalize()}: {value}")
            else:
                missing.append(key)
        parts = present + [f"missing: {key}" for key in missing]
        row["brief_check"] = " | ".join(parts)
    return store.add_plan_row(row)


def update_brand_voice(store: Store, key: str, value: str) -> None:
    """Edit the brand-assets layer as data, through the pipeline."""
    if key not in BRAND_KEYS:
        raise ValueError(f"Unknown brand voice key: {key}")
    store.set_brand_value(key, value)


def fetch_trends(
    store=None, feeds_file=None, fetcher=None, limit: int = 5, brief: str = ""
) -> list[dict]:
    """Trend items with source links. Network only via the real fetcher.

    When a store is given, the fetched trends are snapshotted into
    the Strategist's private notes (the private context layer).
    """
    if fetcher is None:
        from .rss import fetch_feeds

        fetcher = fetch_feeds
    try:
        # Brief-aware fetchers (the research backend) search for
        # what the brief asks about; plain feed fetchers ignore it.
        # Store-aware fetchers resolve the brand's own feed list
        # (rss_feeds) and its feeds.txt; older doubles take fewer
        # arguments, so narrow the call until one fits.
        result = fetcher(feeds_file, brief=brief, store=store)
    except TypeError:
        try:
            result = fetcher(feeds_file, brief=brief)
        except TypeError:
            result = fetcher(feeds_file)
    source = None
    if isinstance(result, dict):
        # A research bundle carries its provenance: which backend
        # answered, and the fallback reason when one happened.
        items = result.get("items", [])
        source = {
            "backend": result.get("backend", "unknown"),
            "detail": result.get("detail", ""),
        }
    else:
        items = result
    items = items[:limit]
    if store is not None:
        from .context import save_trend_notes

        save_trend_notes(store, items, source=source)
    return items


def _trends_for(store: Store, trends_fetcher, brief: str = "") -> list | None:
    """Fetch + snapshot trends when a fetcher is supplied.

    Trends are an input, never a gate: a dead feed returns None and
    the week is planned without them.
    """
    if trends_fetcher is None:
        return None
    try:
        return fetch_trends(store=store, fetcher=trends_fetcher, brief=brief)
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
    Retrieval memory rides alongside the summary: the pieces of
    this brand's own stored past work most relevant to this brief
    (past drafts, reports, analyses) join the planner's context.
    """
    from .context import latest_analyst_summary
    from .memory import retrieval_context

    brand = store.get_brand_voice()
    context_parts = [
        latest_analyst_summary(store),
        retrieval_context(store, brief_text),
    ]
    plan = client.generate_plan(
        brief_text,
        brand,
        context="\n\n".join(part for part in context_parts if part),
        trends=trends,
    )
    rows = []
    for post in plan.get("posts", []):
        # The Strategist is a writer too: the topic and angle are
        # model-written and become the headline and subline on
        # every visual, so they pass the humanising pass before
        # they are stored. One call carries both lines; the line
        # structure the pass promises is what maps them back.
        topic = post.get("topic", "")
        angle = post.get("angle", "")
        plan_error = ""
        parts = [p for p in (topic, angle) if p and p.strip()]
        if parts:
            combined, plan_error = humanize_text(client, "\n".join(parts), brand)
            lines = [ln.strip() for ln in combined.splitlines() if ln.strip()]
            if not plan_error and len(lines) == len(parts):
                if len(parts) == 2:
                    topic, angle = lines
                elif topic:
                    topic = lines[0]
                else:
                    angle = lines[0]
            elif not plan_error:
                plan_error = "humaniser changed the plan text structure"
        rows.append(
            store.add_plan_row(
                {
                    "date": post.get("day", ""),
                    "platform": post.get("platform", ""),
                    "topic": topic,
                    "angle": angle,
                    "brief_check": (
                        f"[HUMANIZER FALLBACK] plan text pass unavailable "
                        f"({plan_error})"
                        if plan_error
                        else ""
                    ),
                    "format": post.get("format", ""),
                    "character": post.get("character", ""),
                    "visual_style": post.get("visual_style", ""),
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


def draft_and_check(
    store: Store, client, row: dict, judge=None, image_client=None
) -> dict:
    """Draft one plan item, humanise it, run the checker, revise
    once on failure.

    Ends with status awaiting_approval (checks passed) or checked
    (still failing after the single revision, flagged for the human).
    The checker's summary is stored on the row as quoted evidence.
    """
    brand = store.get_brand_voice()
    item = dict(row)
    draft = client.generate_draft(item, brand)
    text = _full_text(draft)
    text, humanize_error = humanize_text(client, text, brand)
    result = check_draft(text, item.get("platform", ""), brand)
    if not result.passed:
        item["revision_feedback"] = result.summary()
        draft = client.generate_draft(item, brand)
        text = _full_text(draft)
        text, revision_error = humanize_text(client, text, brand)
        humanize_error = humanize_error or revision_error
        result = check_draft(text, item.get("platform", ""), brand)
    # Length repair: a draft whose ONLY failing rule is the
    # platform length cap gets one targeted shortening pass. A
    # full redraft can expand again (a 2,457-char draft survived
    # its revision on the 2026-11-04 board), so the repair edits
    # the existing text down to the cap, humanises the result
    # like every writer output, and re-checks: only a passing
    # repair is adopted, anything else stays flagged as revised.
    repair_note = ""
    failed_rules = [r.rule for r in result.results if not r.passed]
    if not result.passed and failed_rules == ["length_limit"]:
        cap = PLATFORM_LIMITS.get((item.get("platform") or "").lower())
        if cap:
            before = len(text)
            # Measure-and-repeat: the model cannot count Burmese
            # codepoints reliably (combining marks inflate the
            # count), so one shortening pass can still land over
            # the cap. The code measures after every pass and
            # repeats, up to three passes, until the text is
            # genuinely under the cap.
            current = text
            repair_error = ""
            passes = 0
            while len(current) > cap and passes < 3:
                shortened, repair_error = shorten_text(client, current, cap, brand)
                if repair_error or len(shortened) >= len(current):
                    break
                current = shortened
                passes += 1
            trimmed = False
            if not repair_error and len(current) > cap:
                # The model's passes did not converge (Wonder
                # under-counts Burmese codepoints and trims only a
                # few percent per pass): finish the job in code by
                # dropping whole middle sentences, then let the
                # checks judge the result like any other draft.
                cut = trim_to_cap(current, cap, brand.get("cta_markers") or [])
                if len(cut) < len(current):
                    current, trimmed = cut, True
            if repair_error:
                repair_note = (
                    f"\n[LENGTH REPAIR] shortening pass unavailable "
                    f"({repair_error}); draft flagged as revised"
                )
            elif len(current) <= cap:
                current, repair_herr = humanize_text(client, current, brand)
                humanize_error = humanize_error or repair_herr
                if len(current) > cap:
                    # The humaniser re-expanded it: one last
                    # deterministic trim, adopted only if it lands
                    # under the cap.
                    cut = trim_to_cap(current, cap, brand.get("cta_markers") or [])
                    if len(cut) <= cap:
                        current, trimmed = cut, True
                repair_result = check_draft(
                    current, item.get("platform", ""), brand
                )
                if repair_result.passed:
                    text, result = current, repair_result
                    repair_note = (
                        f"\n[LENGTH REPAIR] draft shortened {before} -> "
                        f"{len(text)} chars in {passes} pass(es)"
                        + (" + sentence trim" if trimmed else "")
                        + f" to meet the {cap} character platform cap"
                    )
                else:
                    repair_note = (
                        "\n[LENGTH REPAIR] shortened draft still fails "
                        "the checks; flagged as revised"
                    )
            else:
                repair_note = (
                    f"\n[LENGTH REPAIR] draft still over the cap after "
                    f"{passes} shortening pass(es); flagged as revised"
                )
    summary = result.summary()
    if humanize_error:
        summary += (
            f"\n[HUMANIZER FALLBACK] humanising pass unavailable "
            f"({humanize_error}); draft checked as generated"
        )
    if repair_note:
        summary += repair_note
    # The draft now exists: record it before the check completes, so
    # the board's Drafted column and the write log show the real
    # progression instead of a jump from planned to checked.
    store.update_row("plan", row["id"], {"draft": text, "status": "drafted"})
    summary, status = _review_tail(
        store, client, item, text, summary, result.passed,
        judge=judge, image_client=image_client,
    )
    return store.update_row(
        "plan",
        row["id"],
        {"check_status": summary, "status": status},
    )


def _review_tail(
    store: Store,
    client,
    item: dict,
    text: str,
    summary: str,
    rules_passed: bool,
    judge=None,
    image_client=None,
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
    video_note = ""
    try:
        updated = produce_visual(
            store, {**item, "draft": text}, image_client=image_client, director=client
        )
        visual_note = f"[VISUAL] PASS - {updated.get('visual', '')}"
        visual_ok = True
        # The handoff chain has a named state for this moment.
        store.update_row("plan", item["id"], {"status": "visual_ready"})
        if "video" in (item.get("format") or "").lower():
            # Short video rows also get the produced video (the
            # poster stays the row's visual). A video failure flags
            # the row exactly like a visual failure: it never
            # reaches awaiting_approval on a broken video.
            from .video import produce_video

            try:
                video_path, video_manifest = produce_video(
                    store, {**item, "draft": text}, image_client=image_client
                )
                video_note = (
                    f"\n[VIDEO] PASS - {video_path.name} "
                    f"({video_manifest['qc']['duration']:.1f}s, "
                    f"{len(video_manifest['scenes'])} scenes)"
                )
            except (ValueError, RuntimeError) as exc:
                video_note = f"\n[VISUAL] FAIL - video production failed: {exc}"
                visual_ok = False
    except (ValueError, RuntimeError) as exc:
        visual_note = f"[VISUAL] FAIL - {exc}"
    summary += f"\n{visual_note}{video_note}"
    status = "checked"
    if rules_passed and visual_ok:
        # Deterministic rules passed; the judge model gives the
        # judgement verdict. A "revise" verdict flags the card for
        # the human instead of letting it through to approval.
        # The verdict runs as the Judge role's own pass, through a
        # dedicated judge client: a same-object judge is treated as
        # no judge, so the drafting client object never doubles as
        # the judge through this path.
        verdict_client = judge if (judge is not None and judge is not client) else client
        try:
            verdict = verdict_client.verdict(
                {"text": text, "platform": item.get("platform", "")}, summary
            )
        except Exception as exc:
            if verdict_client is client:
                raise
            # A failing judge must not strand the run: fall back to
            # the drafting client's verdict and SAY SO in the
            # evidence, so the degradation is visible on the card.
            verdict = client.verdict(
                {"text": text, "platform": item.get("platform", "")}, summary
            )
            summary += f"\n[JUDGE FALLBACK] judge error ({exc}); verdict from the drafting client"
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


def edit_item(
    store: Store, client, row_id: str, new_text: str, judge=None, image_client=None
) -> dict:
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
        store, client, row, new_text, result.summary(), result.passed,
        judge=judge, image_client=image_client,
    )
    return store.update_row(
        "plan", row["id"], {"check_status": summary, "status": status}
    )


def schedule_approved(store: Store, row_id: str) -> dict:
    """Scheduling goes through the pipeline (the gate lives in scheduler)."""
    from .scheduler import make_postiz_client, schedule_item

    return schedule_item(store, row_id, make_postiz_client(store))


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


def run_visibility_audit(store: Store, client=None) -> dict:
    """The Analyst's visibility stage act (SEO/GEO/AEO).

    Builds the deterministic audit over the drafted content,
    records it for the dashboard, and files a one-line summary in
    the visibility history the Strategist reads when planning
    (via context.latest_analyst_summary).
    """
    from .context import append_visibility_history, save_last_visibility
    from .visibility import build_visibility_audit

    audit = build_visibility_audit(store, client=client)
    save_last_visibility(store, audit["text"])
    findings = audit["findings"]
    warns = [f["check"] for f in findings if f["status"] == "warn"]
    summary = (
        f"{len(findings) - len(warns)}/{len(findings)} checks pass"
        + (f"; warned: {', '.join(warns)}" if warns else "; no warnings")
    )
    append_visibility_history(store, summary)
    return audit


def run_content_analysis(store: Store, client=None) -> dict:
    """The Analyst's content stage act: build the topic/format
    breakdown, record it, and file the one-line summary the
    Strategist reads when planning."""
    from .content_analysis import build_content_analysis
    from .context import append_content_history, save_last_content_analysis

    result = build_content_analysis(store, client=client)
    save_last_content_analysis(store, result["text"])
    topics = result["analysis"]["by_topic"]
    if topics:
        best = topics[0]
        summary = (
            f"strongest topic {best['name']} at {best['rate']}% engagement "
            f"rate across {best['posts']} post(s)"
        )
        if len(topics) > 1:
            worst = topics[-1]
            summary += f"; weakest {worst['name']} at {worst['rate']}%"
    else:
        summary = "no measured posts yet"
    append_content_history(store, summary)
    return result


def run_audience_analysis(store: Store, client=None) -> dict:
    """The Analyst's audience stage act: build the snapshot
    comparison, record it, and file the summary the Strategist
    reads when planning."""
    from .audience import build_audience_analysis
    from .context import append_audience_history, save_last_audience_analysis

    result = build_audience_analysis(store, client=client)
    save_last_audience_analysis(store, result["text"])
    snapshots = result["analysis"]["snapshots"]
    if snapshots:
        latest = snapshots[-1]
        deltas = result["analysis"]["deltas"]
        views = deltas.get("views", {})
        trend = (
            f"; views {views.get('change', 0):+d} ({views.get('pct', 0.0)}%) period over period"
            if views
            else ""
        )
        summary = f"{latest['followers']} followers at {latest['period_end']}{trend}"
    else:
        summary = "no insights snapshots yet"
    append_audience_history(store, summary)
    return result


def last_audience_analysis(store: Store) -> str:
    """The latest recorded audience analysis ("" until one runs)."""
    from .context import load_last_audience_analysis

    return load_last_audience_analysis(store)


def last_content_analysis(store: Store) -> str:
    """The latest recorded content analysis ("" until one runs)."""
    from .context import load_last_content_analysis

    return load_last_content_analysis(store)


def last_visibility(store: Store) -> str:
    """The latest recorded visibility audit ("" until one runs)."""
    from .context import load_last_visibility

    return load_last_visibility(store)


def last_report(store: Store) -> str:
    """The latest recorded report narrative ("" until one runs)."""
    from .context import load_last_report

    return load_last_report(store)


def current_report(store: Store) -> dict:
    """The Analyst's report, requested through the pipeline."""
    from .report import build_report

    return build_report(store)


def run_brief(
    store: Store,
    client,
    brief_row_id: str,
    trends_fetcher=None,
    judge=None,
    image_client=None,
) -> list[dict]:
    """Run the pipeline for one brief card already on the board.

    The dashboard's Run action goes through here, so the sequence
    (plan, then draft + check per post, brief marked planned) is
    assembled by the orchestrator, never by the handler.
    """
    brief_row = _get_row(store, brief_row_id)
    trends = _trends_for(store, trends_fetcher, brief=brief_row.get("brief", ""))
    rows = generate_week(store, client, brief_row.get("brief", ""), trends=trends)
    drafted = [
        draft_and_check(store, client, row, judge=judge, image_client=image_client)
        for row in rows
    ]
    store.update_row("plan", brief_row["id"], {"status": "planned"})
    return drafted


def process_week(
    store: Store,
    client,
    brief_text: str,
    trends_fetcher=None,
    judge=None,
    image_client=None,
) -> list[dict]:
    """Full mock-safe run: brief, research, plan, draft + check each post."""
    intake_brief(store, brief_text)
    trends = _trends_for(store, trends_fetcher, brief=brief_text)
    rows = generate_week(store, client, brief_text, trends=trends)
    return [
        draft_and_check(store, client, row, judge=judge, image_client=image_client)
        for row in rows
    ]
