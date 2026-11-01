"""Web kanban dashboard for PageOps Agent.

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
        return (
            '<form method="post" action="/action" class="actions">'
            f'<input type="hidden" name="id" value="{item_id}">'
            '<button name="action" value="approve" type="submit">Approve</button>'
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
    brand_panel = (
        '<section class="panel"><h2>Brand voice</h2>'
        f"<div>Audience: {html.escape(brand['audience'])}</div>"
        f"<div>Tone: {html.escape(brand['tone'])}</div>"
        f"<ul>{services}</ul><ul>{rules}</ul></section>"
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
        from .pipeline import current_report

        narrative = html.escape(current_report(store)["narrative"])
        report_panel = (
            '<section class="panel"><h2>Performance report</h2>'
            f"<pre>{narrative}</pre></section>"
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

    brand_name = html.escape(brand["brand_name"] or "PageOps Agent")
    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        '<meta http-equiv="refresh" content="15">'
        f"<title>{brand_name} - PageOps board</title><style>{_CSS}</style></head><body>"
        f"<header><h1>{brand_name} - content pipeline</h1>"
        "<p>PageOps Agent, a digital marketing and content creation agent: brief, plan, checks, approvals, scheduling, report.</p></header>"
        f"{brief_form}"
        f"<div class='board'>{''.join(columns_html)}</div>"
        f"{brand_panel}{metrics_panel}{report_panel}"
        "</body></html>"
    )


def make_handler(store: Store):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 (stdlib naming)
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
                    from .pipeline import intake_brief

                    parts = [
                        form.get(k, "").strip()
                        for k in ("goal", "offer", "dates", "notes")
                    ]
                    intake_brief(store, " | ".join(p for p in parts if p))
                elif self.path == "/action":
                    item_id = form.get("id", "")
                    action = form.get("action", "")
                    if action == "run":
                        from .model_client import MockClient, get_client
                        from .pipeline import run_brief
                        from .rss import fetch_feeds

                        client = get_client()
                        # Live mode researches the live feeds; mock
                        # mode stays offline and hermetic.
                        fetcher = None if isinstance(client, MockClient) else fetch_feeds
                        run_brief(store, client, item_id, trends_fetcher=fetcher)
                    elif action == "edit":
                        from .model_client import get_client
                        from .pipeline import edit_item

                        edit_item(store, get_client(), item_id, form.get("draft", ""))
                    elif action == "approve":
                        from .pipeline import approve_item

                        approve_item(store, item_id)
                    elif action == "reject":
                        from .pipeline import reject_item

                        reject_item(store, item_id, form.get("reason", ""))
                    elif action == "schedule":
                        from .pipeline import schedule_approved

                        schedule_approved(store, item_id)
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
    print(f"PageOps dashboard: http://127.0.0.1:{port}")
    return server


if __name__ == "__main__":
    import os

    serve(port=int(os.environ.get("PAGEOPS_DASHBOARD_PORT", "8765"))).serve_forever()
