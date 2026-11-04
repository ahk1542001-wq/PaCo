"""Web kanban dashboard for PaCo Agent.

A single server-rendered page (Python stdlib only) that reads the same
CSV store the pipeline writes to, so the board always shows the real
pipeline state. Columns match the pipeline stages; plan-row statuses map
onto them. The dashboard is the product's only interface: brief form,
approval actions and the report view all live here.

Run:  python -m pageops.dashboard   (port from PAGEOPS_DASHBOARD_PORT,
default 8765; data dir from PAGEOPS_DATA_DIR via Settings)
"""

from __future__ import annotations

import html
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .store import Store

# (column key, display title) in pipeline order.
COLUMNS: list[tuple[str, str]] = [
    ("brief", "Brief"),
    ("planned", "Planned"),
    ("drafted", "Drafted"),
    ("checked", "Checked"),
    ("awaiting_approval", "Awaiting approval"),
    ("scheduled", "Scheduled"),
    ("reported", "Reported"),
]

# Plan-row status -> kanban column. Unknown statuses land in Brief and
# still show their raw status on the card, so nothing silently vanishes.
STATUS_TO_COLUMN: dict[str, str] = {
    "brief_received": "brief",
    "brief": "brief",
    "planned": "planned",
    "drafted": "drafted",
    "visual_ready": "drafted",
    "checked": "checked",
    "awaiting_approval": "awaiting_approval",
    "approved": "awaiting_approval",
    "rejected": "awaiting_approval",
    "scheduled": "scheduled",
    "reported": "reported",
}

_CSS = """
body { font-family: system-ui, sans-serif; margin: 0; background: #0f1420; color: #e8ecf4; }
header { padding: 16px 24px; background: #16203a; }
header h1 { margin: 0; font-size: 22px; }
header p { margin: 4px 0 0; color: #9fb0d0; font-size: 13px; }
.poster { max-width: 100%; border-radius: 8px; margin: 6px 0; display: block; }
.board { display: flex; gap: 12px; padding: 16px 24px; overflow-x: auto; align-items: flex-start; }
.col { background: #1a2438; border-radius: 10px; padding: 10px; min-width: 190px; flex: 1; }
.col h2 { font-size: 13px; text-transform: uppercase; letter-spacing: .06em; color: #9fb0d0; margin: 2px 2px 10px; }
.col h2 .n { color: #e8ecf4; }
.card { background: #232f4a; border-radius: 8px; padding: 10px; margin-bottom: 8px; font-size: 13px; }
.card .topic { font-weight: 600; margin-bottom: 4px; }
.card .meta { color: #9fb0d0; font-size: 12px; line-height: 1.5; }
.card .status { display: inline-block; margin-top: 6px; background: #2e4a7a; border-radius: 4px; padding: 1px 6px; font-size: 11px; }
.empty { color: #5f7099; font-size: 12px; padding: 4px 2px; }
section.panel { margin: 0 24px 20px; background: #1a2438; border-radius: 10px; padding: 14px 18px; font-size: 13px; }
section.panel h2 { font-size: 14px; margin: 0 0 8px; }
section.panel li { margin: 2px 0; }
table { border-collapse: collapse; font-size: 13px; }
th, td { border: 1px solid #2c3a58; padding: 4px 10px; text-align: left; }
th { background: #232f4a; }
form.actions { margin-top: 8px; display: flex; gap: 6px; }
form.actions button, form.brief button { background: #2e4a7a; color: #e8ecf4; border: 0; border-radius: 6px; padding: 5px 10px; cursor: pointer; font-size: 12px; }
form.brief { display: flex; gap: 8px; flex-wrap: wrap; }
form.brief input { background: #232f4a; border: 1px solid #2c3a58; border-radius: 6px; color: #e8ecf4; padding: 6px 8px; font-size: 13px; flex: 1; min-width: 140px; }
section.panel pre { white-space: pre-wrap; font-size: 13px; margin: 0; }
form.edit { margin-top: 6px; }
form.edit textarea { width: 100%; box-sizing: border-box; background: #1a2438; border: 1px solid #2c3a58; border-radius: 6px; color: #e8ecf4; font-size: 12px; padding: 6px; }
form.edit button { margin-top: 4px; background: #2e4a7a; color: #e8ecf4; border: 0; border-radius: 6px; padding: 5px 10px; cursor: pointer; font-size: 12px; }
"""


def _actions(row: dict[str, str]) -> str:
    """Action buttons for a card, depending on where it sits in the gate."""
    status = row.get("status", "")
    item_id = html.escape(row.get("id", ""))
    if status == "brief_received":
        return (
            '<form method="post" action="/action" class="actions">'
            f'<input type="hidden" name="id" value="{item_id}">'
            '<button name="action" value="run" type="submit">Run pipeline (plan + drafts)</button>'
            "</form>"
        )
    if status == "awaiting_approval":
        draft_text = html.escape(row.get("draft", ""))
        # Approve and Reject are SEPARATE forms on purpose: with both
        # buttons in one form, pressing Enter in the reason input
        # submits via the first button and approves by accident
        # (Standards review of PR #5). The reason lives with Reject.
        return (
            '<form method="post" action="/action" class="actions">'
            f'<input type="hidden" name="id" value="{item_id}">'
            '<button name="action" value="approve" type="submit">Approve</button>'
            "</form>"
            '<form method="post" action="/action" class="actions">'
            f'<input type="hidden" name="id" value="{item_id}">'
            '<input name="reason" placeholder="Rejection reason (kept on the card)">'
            '<button name="action" value="reject" type="submit">Reject</button>'
            "</form>"
            '<form method="post" action="/action" class="edit">'
            f'<input type="hidden" name="id" value="{item_id}">'
            f'<textarea name="draft" rows="3">{draft_text}</textarea>'
            '<button name="action" value="edit" type="submit">Save edit + re-check</button>'
            "</form>"
        )
    if status == "checked":
        # Flagged for the human: no Approve (the gate), but the human
        # can fix the draft or reject it with a reason from the board.
        draft_text = html.escape(row.get("draft", ""))
        return (
            '<form method="post" action="/action" class="actions">'
            f'<input type="hidden" name="id" value="{item_id}">'
            '<input name="reason" placeholder="Rejection reason (kept on the card)">'
            '<button name="action" value="reject" type="submit">Reject</button>'
            "</form>"
            '<form method="post" action="/action" class="edit">'
            f'<input type="hidden" name="id" value="{item_id}">'
            f'<textarea name="draft" rows="3">{draft_text}</textarea>'
            '<button name="action" value="edit" type="submit">Save edit + re-check</button>'
            "</form>"
        )
    if status == "approved":
        return (
            '<form method="post" action="/action" class="actions">'
            f'<input type="hidden" name="id" value="{item_id}">'
            '<button name="action" value="schedule" type="submit">Schedule (dry-run)</button>'
            "</form>"
        )
    if status == "scheduled":
        # After the post goes out, the operator links the platform
        # post ID here; the report stage can then mark it reported.
        return (
            '<form method="post" action="/action" class="actions">'
            f'<input type="hidden" name="id" value="{item_id}">'
            '<input name="post_id" placeholder="Published post ID">'
            '<button name="action" value="link" type="submit">Link post</button>'
            "</form>"
        )
    return ""


def _card(row: dict[str, str]) -> str:
    title = row.get("topic") or row.get("brief") or "(untitled)"
    meta_bits = [
        b
        for b in (
            row.get("platform", ""),
            row.get("date", ""),
            row.get("format", ""),
            row.get("angle", ""),
        )
        if b
    ]
    meta = " · ".join(html.escape(b) for b in meta_bits)
    status = html.escape(row.get("status", ""))
    extras = ""
    if row.get("draft"):
        extras += f'<div class="meta draft">{html.escape(row["draft"][:220])}</div>'
    if row.get("check_status"):
        checks = html.escape(row["check_status"]).replace("\n", "<br>")
        extras += f'<div class="meta checks">{checks}</div>'
    if row.get("buffer_id"):
        extras += f'<div class="meta">Queue: {html.escape(row["buffer_id"])}</div>'
    if row.get("visual"):
        name = row["visual"].split("/")[-1]
        extras += (
            f'<img class="poster" src="/visual/{html.escape(name)}" '
            'alt="Post visual">'
        )
    if row.get("video"):
        video_name = row["video"].split("/")[-1]
        extras += (
            f'<div class="meta">Video: '
            f'<a href="/visual/{html.escape(video_name)}">'
            f"{html.escape(video_name)}</a></div>"
        )
    if row.get("brief_check"):
        extras += f'<div class="meta">Brief check: {html.escape(row["brief_check"])}</div>'
    if row.get("reject_reason"):
        extras += f'<div class="meta">Rejected: {html.escape(row["reject_reason"])}</div>'
    return (
        '<div class="card">'
        f'<div class="topic">{html.escape(title)}</div>'
        f'<div class="meta">{meta}</div>'
        f"{extras}"
        f'<span class="status">{status}</span>'
        f"{_actions(row)}"
        "</div>"
    )


def render_board(store: Store) -> str:
    """Render the full dashboard HTML from the store's current data."""
    brand = store.get_brand_voice()
    plan_rows = store.read_dataset("plan")
    metrics_rows = store.read_dataset("metrics")

    by_column: dict[str, list[dict[str, str]]] = {key: [] for key, _ in COLUMNS}
    for row in plan_rows:
        column = STATUS_TO_COLUMN.get(row.get("status", ""), "brief")
        by_column[column].append(row)

    columns_html = []
    for key, title in COLUMNS:
        cards = "".join(_card(r) for r in by_column[key]) or '<div class="empty">No items</div>'
        columns_html.append(
            f'<div class="col"><h2>{html.escape(title)} '
            f'<span class="n">{len(by_column[key])}</span></h2>{cards}</div>'
        )

    services = "".join(f"<li>{html.escape(s)}</li>" for s in brand["services"])
    rules = "".join(f"<li>{html.escape(r)}</li>" for r in brand["rules"])
    from .pipeline import BRAND_KEYS

    raw_brand = {r["key"]: r["value"] for r in store.read_dataset("brand_voice")}
    # Edit forms only for keys the pipeline will accept, so the
    # render surface and the write surface cannot drift apart.
    edit_forms = "".join(
        '<form method="post" action="/brand" class="brandedit">'
        f'<label>{html.escape(k)}</label>'
        f'<input type="hidden" name="key" value="{html.escape(k)}">'
        f'<input name="value" value="{html.escape(v)}">'
        '<button type="submit">Save</button></form>'
        for k, v in raw_brand.items()
        if k in BRAND_KEYS
    )
    brand_panel = (
        '<section class="panel"><h2>Brand voice</h2>'
        f"<div>Audience: {html.escape(brand['audience'])}</div>"
        f"<div>Tone: {html.escape(brand['tone'])}</div>"
        f"<ul>{services}</ul><ul>{rules}</ul>{edit_forms}</section>"
    )

    metrics_panel = ""
    report_panel = ""
    if metrics_rows:
        head = "".join(f"<th>{html.escape(h)}</th>" for h in metrics_rows[0].keys())
        body = "".join(
            "<tr>" + "".join(f"<td>{html.escape(v)}</td>" for v in r.values()) + "</tr>"
            for r in metrics_rows
        )
        metrics_panel = (
            '<section class="panel"><h2>Latest metrics</h2>'
            f"<table><tr>{head}</tr>{body}</table></section>"
        )

    from .pipeline import current_report, last_report

    saved_report = last_report(store)
    if metrics_rows or saved_report:
        # The panel prefers the last RECORDED report (which carries
        # the model's figure-checked Read); before any run it shows
        # the pure computed report. Rendering never calls a model.
        narrative = html.escape(
            saved_report if saved_report else current_report(store)["narrative"]
        )
        report_panel = (
            '<section class="panel"><h2>Performance report</h2>'
            f"<pre>{narrative}</pre>"
            '<form method="post" action="/report">'
            '<button type="submit">Run report</button></form></section>'
        )

    from .pipeline import last_visibility

    visibility_panel = ""
    saved_visibility = last_visibility(store)
    if saved_visibility:
        visibility_panel = (
            '<section class="panel"><h2>Visibility audit (SEO / GEO / AEO)</h2>'
            f"<pre>{html.escape(saved_visibility)}</pre>"
            '<form method="post" action="/visibility">'
            '<button type="submit">Run visibility audit</button></form></section>'
        )

    from .pipeline import last_content_analysis

    content_panel = ""
    saved_content = last_content_analysis(store)
    if saved_content:
        content_panel = (
            '<section class="panel"><h2>Content analysis</h2>'
            f"<pre>{html.escape(saved_content)}</pre>"
            '<form method="post" action="/content">'
            '<button type="submit">Run content analysis</button></form></section>'
        )

    from .pipeline import last_audience_analysis

    audience_panel = ""
    saved_audience = last_audience_analysis(store)
    if saved_audience:
        audience_panel = (
            '<section class="panel"><h2>Audience analysis</h2>'
            f"<pre>{html.escape(saved_audience)}</pre>"
            '<form method="post" action="/audience">'
            '<button type="submit">Run audience analysis</button></form></section>'
        )

    variants_panel = ""
    variant_rows = store.read_dataset("variants")
    if variant_rows:
        plan_topics = {r["id"]: r.get("topic", "") for r in plan_rows}
        items = "".join(
            "<li>"
            + html.escape(
                f"{plan_topics.get(v['plan_id'], v['plan_id'])} - {v['platform']} "
                f"[{v['check_status']}]: {v['text'][:90]}"
            )
            + "</li>"
            for v in variant_rows
        )
        variants_panel = (
            '<section class="panel"><h2>Cross-platform variants</h2>'
            f"<ul>{items}</ul>"
            '<form method="post" action="/variants">'
            '<button type="submit">Generate variants</button></form></section>'
        )

    from .brand_builder import LEVELS, level_statuses

    bb_statuses = level_statuses(store)
    bb_rows = {r["level"]: r for r in store.read_dataset("brand_build")}
    bb_items = ""
    for lvl, spec in LEVELS.items():
        status = bb_statuses[lvl]
        content = (bb_rows.get(str(lvl)) or {}).get("content", "")
        preview = html.escape(content[:110])
        actions = ""
        if lvl > 1 and status in ("empty", "drafted"):
            actions += (
                '<form method="post" action="/brand-level">'
                f'<input type="hidden" name="level" value="{lvl}">'
                '<input type="hidden" name="action" value="draft">'
                '<input name="brief" placeholder="Business brief">'
                '<button type="submit">Draft</button></form>'
            )
        if status == "drafted":
            actions += (
                '<form method="post" action="/brand-level">'
                f'<input type="hidden" name="level" value="{lvl}">'
                '<input type="hidden" name="action" value="approve">'
                '<button type="submit">Approve</button></form>'
            )
        bb_items += (
            f"<li>Level {lvl} {html.escape(spec['name'])} [{status}] "
            f"{preview}{actions}</li>"
        )
    brand_builder_panel = (
        '<section class="panel"><h2>Brand Builder</h2>'
        f"<ul>{bb_items}</ul></section>"
    )

    research_panel = ""
    research_rows = store.read_dataset("research")
    if research_rows:
        r_items = "".join(
            "<li>" + html.escape(
                f"[{r['evidence']}] {r['kind']}: {r['claim'][:120]}"
                + (f" ({r['source']})" if r["source"] else "")
            ) + "</li>"
            for r in research_rows
        )
        research_panel = (
            '<section class="panel"><h2>Business research</h2>'
            f"<ul>{r_items}</ul>"
            '<form method="post" action="/research">'
            '<input name="brief" placeholder="Business brief">'
            '<button type="submit">Run research</button></form></section>'
        )

    brief_form = (
        '<section class="panel"><h2>New brief</h2>'
        '<form method="post" action="/brief" class="brief">'
        '<input name="goal" placeholder="Goal">'
        '<input name="offer" placeholder="Offer">'
        '<input name="dates" placeholder="Dates">'
        '<input name="notes" placeholder="Notes">'
        '<button type="submit">Add brief</button></form></section>'
    )

    brand_name = html.escape(brand["brand_name"] or "PaCo Agent")
    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        '<meta http-equiv="refresh" content="15">'
        f"<title>{brand_name} - PaCo board</title><style>{_CSS}</style></head><body>"
        f"<header><h1>{brand_name} - content pipeline</h1>"
        "<p>PaCo Agent, a digital marketing and content creation agent: brief, plan, checks, approvals, scheduling, report.</p></header>"
        f"{brief_form}"
        f"<div class='board'>{''.join(columns_html)}</div>"
        f"{brand_panel}{metrics_panel}{report_panel}{visibility_panel}{content_panel}{audience_panel}{variants_panel}{brand_builder_panel}{research_panel}"
        "</body></html>"
    )


def make_handler(store: Store):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 (stdlib naming)
            if self.path.startswith("/visual/"):
                from pathlib import Path as _Path
                from urllib.parse import unquote as _unquote

                name = _unquote(self.path[len("/visual/"):])
                # Only media files directly under visuals/, no traversal.
                is_mp4 = name.endswith(".mp4")
                visuals_dir = (store.data_dir / "visuals").resolve()
                target = visuals_dir / name
                if (
                    name != _Path(name).name
                    or not (name.endswith(".png") or is_mp4)
                    or not target.exists()
                    # Containment is structural: a symlink inside
                    # visuals/ pointing outside is refused too.
                    or visuals_dir not in target.resolve().parents
                ):
                    self.send_response(404)
                    self.end_headers()
                    return
                # Deliberate limit: the file is read whole and
                # served without Range support; acceptable for the
                # short clips this board serves.
                data = target.read_bytes()
                self.send_response(200)
                self.send_header(
                    "Content-Type", "video/mp4" if is_mp4 else "image/png"
                )
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            body = render_board(store).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):  # noqa: N802 (stdlib naming)
            from urllib.parse import parse_qs

            length = int(self.headers.get("Content-Length", 0))
            form = {
                k: v[0]
                for k, v in parse_qs(self.rfile.read(length).decode("utf-8")).items()
            }
            try:
                if self.path == "/brief":
                    from .pipeline import BRIEF_FIELDS, intake_brief

                    fields = {
                        k: form.get(k, "").strip() for k in BRIEF_FIELDS
                    }
                    parts = [v for v in fields.values() if v]
                    intake_brief(store, " | ".join(parts), fields=fields)
                elif self.path == "/report":
                    from .model_client import get_client
                    from .pipeline import report_week

                    report_week(store, client=get_client())
                elif self.path == "/research":
                    from .business_research import run_business_research
                    from .model_client import get_client
                    from .research import fetch_research

                    brief = form.get("brief", "")
                    bundle = fetch_research(brief=brief)
                    run_business_research(
                        store, get_client(), brief, bundle.get("items", [])
                    )
                elif self.path == "/brand-level":
                    from .brand_builder import approve_level, draft_level

                    level = int(form.get("level", "0") or 0)
                    if form.get("action") == "draft":
                        from .model_client import get_client

                        draft_level(store, level, get_client(), form.get("brief", ""))
                    elif form.get("action") == "approve":
                        approve_level(store, level)
                elif self.path == "/variants":
                    from .model_client import get_client
                    from .variants import generate_variants

                    generate_variants(store, get_client())
                elif self.path == "/audience":
                    from .model_client import get_client
                    from .pipeline import run_audience_analysis

                    run_audience_analysis(store, client=get_client())
                elif self.path == "/content":
                    from .model_client import get_client
                    from .pipeline import run_content_analysis

                    run_content_analysis(store, client=get_client())
                elif self.path == "/visibility":
                    from .model_client import get_client
                    from .pipeline import run_visibility_audit

                    run_visibility_audit(store, client=get_client())
                elif self.path == "/brand":
                    from .pipeline import update_brand_voice

                    update_brand_voice(store, form.get("key", ""), form.get("value", ""))
                elif self.path == "/action":
                    item_id = form.get("id", "")
                    action = form.get("action", "")
                    if action == "run":
                        from .model_client import (
                            MockClient,
                            get_client,
                            get_image_client,
                            get_judge_client,
                        )
                        from .pipeline import run_brief
                        from .research import fetch_research

                        client = get_client()
                        # Live mode researches first (Agent-Reach
                        # web search, RSS fallback); mock mode stays
                        # offline and hermetic.
                        fetcher = None if isinstance(client, MockClient) else fetch_research
                        run_brief(
                            store,
                            client,
                            item_id,
                            trends_fetcher=fetcher,
                            judge=get_judge_client(),
                            image_client=get_image_client(),
                        )
                    elif action == "edit":
                        from .model_client import (
                            get_client,
                            get_image_client,
                            get_judge_client,
                        )
                        from .pipeline import edit_item

                        edit_item(
                            store,
                            get_client(),
                            item_id,
                            form.get("draft", ""),
                            judge=get_judge_client(),
                            image_client=get_image_client(),
                        )
                    elif action == "approve":
                        from .pipeline import approve_item

                        approve_item(store, item_id)
                    elif action == "reject":
                        from .pipeline import reject_item

                        reject_item(store, item_id, form.get("reason", ""))
                    elif action == "schedule":
                        from .pipeline import schedule_approved

                        schedule_approved(store, item_id)
                    elif action == "link":
                        from .pipeline import link_post

                        link_post(store, item_id, form.get("post_id", ""))
                    else:
                        raise ValueError(f"Unknown action: {action}")
                else:
                    self.send_response(404)
                    self.end_headers()
                    return
            except (KeyError, PermissionError, ValueError) as exc:
                body = f"Action failed: {exc}".encode("utf-8")
                self.send_response(400)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self.send_response(303)
            self.send_header("Location", "/")
            self.end_headers()

        def log_message(self, *args):  # keep the console quiet
            pass

    return Handler


def serve(store: Store | None = None, port: int = 8765) -> ThreadingHTTPServer:
    if store is None:
        from .config import get_settings

        store = Store(get_settings().data_dir)
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(store))
    print(f"PaCo dashboard: http://127.0.0.1:{port}")
    return server


if __name__ == "__main__":
    import os

    serve(port=int(os.environ.get("PAGEOPS_DASHBOARD_PORT", "8765"))).serve_forever()
