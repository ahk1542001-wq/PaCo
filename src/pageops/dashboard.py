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

from .store import Store, open_store

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
:root{
  --ink:#042433; --muted:#595238; --accent:#FA1239; --accent-deep:#BD0221; --blush:#FFD3C6;
  --ground:#FFFBF8; --surface:#FFFFFF; --raised:#FFF4EF; --tint:#FFD3C6; --tint-strong:#FFBBA6;
  --tint-soft:#FFE8DF; --border:#E8DAD2; --border-strong:#CBBBAE;
  --text:#042433; --text-muted:#595238; --text-faint:#7A7261; --on-accent:#FFFFFF;
  --pass-bg:#DCE9E9; --pass-text:#042433; --pass-mark:#042433;
  --fail-bg:#FFD3C6; --fail-text:#BD0221; --fail-mark:#BD0221;
  --warn-bg:#FFE8DF; --warn-text:#595238;
  --r-sm:6px; --r-md:10px; --r-lg:12px; --r-pill:999px;
  --font-latin:"Segoe UI",system-ui,-apple-system,Roboto,Arial,sans-serif;
  --font-burmese:"Padauk","Noto Sans Myanmar","Segoe UI",system-ui,sans-serif;
}
*{box-sizing:border-box}
body{font-family:var(--font-latin);margin:0;background:var(--ground);color:var(--text);font-size:14px;line-height:1.55}
a{color:var(--accent-deep)}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
button{font-family:inherit;font-size:14px;font-weight:600;border-radius:var(--r-md);padding:10px 18px;cursor:pointer;border:1px solid transparent;transition:background-color .12s,border-color .12s}
.btn-primary{background:var(--accent);color:var(--on-accent)}
.btn-secondary{background:var(--surface);border-color:var(--border-strong);color:var(--ink)}
.btn-ghost{background:transparent;color:var(--accent-deep);border-color:transparent;padding:10px 10px}
@media (hover:hover){
  .btn-primary:hover{background:var(--accent-deep)}
  .btn-secondary:hover{background:var(--raised)}
  .btn-ghost:hover{text-decoration:underline}
  .card:hover{border-color:var(--border-strong)}
  .navrow:hover{background:var(--tint-soft)}
  table tr:hover td{background:var(--tint-soft)}
}
.btn-primary:active{background:var(--accent-deep)}
.btn-secondary:active{background:var(--tint)}
button:disabled{background:var(--tint-soft);color:var(--text-faint);border-color:transparent;cursor:not-allowed}
input,textarea,select{font-family:inherit;font-size:14px;background:var(--surface);border:1px solid var(--border-strong);border-radius:var(--r-sm);padding:10px 12px;color:var(--text)}
input:focus,textarea:focus{border-color:var(--accent-deep)}
textarea{font-family:var(--font-burmese);line-height:1.9;width:100%}
label{font-size:13px;font-weight:600;color:var(--ink)}
/* shell */
.shell{display:grid;grid-template-columns:248px 1fr;min-height:100vh}
.sidebar{border-right:1px solid var(--border);padding:32px 12px 24px 20px}
.wordmark{font-size:20px;font-weight:700;color:var(--ink);padding:0 10px}
.wordmark .dot{display:inline-block;width:8px;height:8px;background:var(--accent);margin-left:5px}
.wordmark-sub{font-size:12px;color:var(--text-faint);padding:2px 10px 0}
.navgroup{margin:20px 10px 6px;font-size:12px;font-weight:600;color:var(--text-faint)}
.navrow{display:flex;align-items:center;gap:8px;height:32px;margin-bottom:2px;padding:0 10px;border-radius:8px;color:var(--text);text-decoration:none;font-size:14px;font-weight:500}
.navrow.active{background:var(--tint);font-weight:600}
.navrow .cdot{width:6px;height:6px;border-radius:50%;background:var(--accent);flex:none}
.navrow .badge{margin-left:auto}
.badge{background:var(--raised);color:var(--accent-deep);font-size:12px;font-weight:600;border-radius:var(--r-pill);padding:1px 7px}
.navrow.active .badge{background:var(--surface)}
.udot{width:8px;height:8px;border-radius:50%;background:var(--accent);margin-left:auto;flex:none}
.canvas{padding:34px 36px 48px;min-width:0}
.topbar,.sheet{display:none}
.navtoggle{position:absolute;opacity:0;pointer-events:none}
/* header row */
.headrow{display:flex;align-items:flex-end;justify-content:space-between;gap:16px;margin-bottom:20px}
.headrow h1{font-size:24px;font-weight:700;line-height:1.25;margin:0}
.headrow .sub{font-size:14px;color:var(--text-muted);margin-top:4px}
.headrow .btn-primary{text-decoration:none;display:inline-block}
/* KPI strip */
.kpis{display:grid;grid-template-columns:repeat(4,1fr);background:var(--surface);border:1px solid var(--border);border-radius:var(--r-lg);margin-bottom:24px}
.kpi{padding:16px 20px}
.kpi + .kpi{border-left:1px solid var(--border)}
.kpi .klabel{font-size:14px;font-weight:500;color:var(--text-muted)}
.kpi .kvalue{font-size:24px;font-weight:700;line-height:1.2;margin:2px 0}
.kpi .kcap{font-size:12px;color:var(--text-faint)}
.kpi-accent .kvalue{color:var(--accent-deep)}
.kpi-accent .klabel::before{content:"";display:inline-block;width:6px;height:6px;border-radius:50%;background:var(--accent);margin-right:7px;vertical-align:2px}
a.kpi{display:block;text-decoration:none;color:inherit}
/* sections + panels */
section.panel{background:var(--surface);border:1px solid var(--border);border-radius:var(--r-lg);padding:20px;margin-bottom:24px}
section.panel h2{font-size:16px;font-weight:650;margin:0 0 16px}
section.panel pre{white-space:pre-wrap;font-family:var(--font-burmese);line-height:1.9;font-size:14px;margin:0 0 12px}
section.panel ul{margin:0 0 12px;padding-left:20px}
section.panel li{margin:4px 0}
.gate-rule{height:3px;background:var(--accent);border-radius:2px;margin:-8px 0 16px}
.empty-state{background:var(--tint-soft);border-radius:var(--r-lg);padding:24px 20px;text-align:center}
.empty-state .l1{font-size:14px;font-weight:600;color:var(--ink)}
.empty-state .l2{font-size:12px;color:var(--text-muted);margin-top:4px}
/* board */
.board{display:flex;gap:12px;overflow-x:auto;align-items:flex-start;padding-bottom:8px}
.col{min-width:210px;flex:1}
.col h2{font-size:13px;font-weight:600;color:var(--ink);margin:0 2px 10px;display:flex;align-items:center;gap:7px}
.col h2 .n{color:var(--text-faint);font-size:12px;font-weight:400}
.sdot{width:8px;height:8px;border-radius:50%;flex:none;display:inline-block}
.empty{color:var(--text-faint);font-size:12px;padding:4px 2px}
/* cards */
.card{background:var(--surface);border:1px solid var(--border);border-radius:var(--r-lg);padding:14px;margin-bottom:12px;transition:border-color .12s}
.pillrow{display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:10px}
.pill{font-size:12px;font-weight:500;border-radius:var(--r-pill);padding:2px 9px}
.pill-brief{background:var(--tint-soft);color:var(--muted)}
.pill-planned{background:var(--tint-soft);color:var(--ink)}
.pill-drafted{background:var(--tint);color:var(--ink)}
.pill-checked{background:var(--tint);color:var(--ink)}
.pill-awaiting_approval{background:var(--tint);color:var(--accent-deep);font-weight:600}
.pill-scheduled{background:var(--pass-bg);color:var(--ink)}
.pill-reported{background:transparent;border:1px solid var(--border);color:var(--text-muted)}
.pillrow .date{font-size:12px;color:var(--text-faint)}
.thumb-empty{height:56px;background:var(--tint-soft);border-radius:var(--r-md);display:flex;align-items:center;gap:8px;padding:0 14px;font-size:12px;color:var(--muted);margin-bottom:10px}
.poster{max-width:100%;border-radius:var(--r-md);margin:0 0 10px;display:block}
.card .topic{font-family:var(--font-burmese);font-size:15px;font-weight:600;line-height:1.9;overflow-wrap:anywhere}
.card .meta{color:var(--text-muted);font-size:12px;line-height:1.5;margin-top:2px}
.card .draft{font-family:var(--font-burmese);line-height:1.9;font-size:13px;color:var(--text);margin-top:8px;overflow-wrap:anywhere}
.ladder{display:flex;align-items:center;gap:0;margin:12px 0 4px}
.ladder .ld{width:6px;height:6px;border-radius:50%;background:var(--border-strong);flex:none}
.ladder .ld.done{background:var(--ink)}
.ladder .ld.gate{background:var(--accent);width:10px;height:10px}
.ladder .ld.cur{box-shadow:0 0 0 2px var(--surface),0 0 0 4px var(--accent-deep)}
.ladder .ld.cur-plain{box-shadow:0 0 0 2px var(--surface),0 0 0 4px var(--border-strong)}
.ladder .ll{flex:1;height:1px;background:var(--border)}
.ladder-label{font-size:12px;color:var(--text-muted);margin-left:10px}
.chip{display:inline-block;font-size:12px;font-weight:600;border-radius:var(--r-pill);padding:2px 8px}
.chip-pass{background:var(--pass-bg);color:var(--pass-text)}
.chip-fail{background:var(--fail-bg);color:var(--fail-text)}
.checks-line{margin-top:10px;display:flex;align-items:center;gap:8px;flex-wrap:wrap}
details.checks{margin-top:6px}
details.checks summary{color:var(--accent-deep);font-size:12px;cursor:pointer;padding:6px 0}
details.checks .ev{font-size:12px;color:var(--text-muted);line-height:1.6;overflow-wrap:anywhere}
form.actions{margin-top:10px;display:flex;gap:8px;flex-wrap:wrap;align-items:center}
form.actions input{flex:1;min-width:120px}
form.edit{margin-top:8px}
form.edit button{margin-top:6px}
form.brief{display:flex;gap:8px;flex-wrap:wrap}
form.brief input{flex:1;min-width:140px}
form.brief button{flex:none}
form.brandedit{display:flex;gap:8px;align-items:center;margin:6px 0;flex-wrap:wrap}
form.brandedit label{min-width:170px}
form.brandedit input{flex:1;min-width:160px}
form.brandedit button{padding:8px 14px}
/* chat */
.chat-log{display:flex;flex-direction:column;gap:10px;margin-bottom:14px}
.chat-msg{display:flex;gap:8px;align-items:flex-start}
.chat-who{font-size:12px;font-weight:600;color:var(--text-faint);min-width:38px;padding-top:2px;flex:none}
.chat-owner .chat-who{color:var(--accent-deep)}
.chat-text{font-family:var(--font-burmese);line-height:1.9;font-size:14px;white-space:pre-wrap;overflow-wrap:anywhere}
.chat-prop{border-color:var(--border-strong);margin-bottom:2px}
form.chat-send{display:flex;gap:8px;flex-wrap:wrap}
form.chat-send input{flex:1;min-width:180px}
/* tables */
.twrap{overflow-x:auto}
table{border-collapse:collapse;font-size:14px;width:100%}
th{font-size:12px;font-weight:600;color:var(--text-muted);text-align:left;border-bottom:1px solid var(--border-strong);padding:6px 10px}
td{border-bottom:1px solid var(--border);padding:6px 10px;text-align:left}
/* lower grid */
.lower{display:grid;grid-template-columns:1fr;gap:0}
.refresh-note{font-size:12px;color:var(--text-faint)}
@media (min-width:1280px){
  .lower{grid-template-columns:1fr 320px;gap:24px;align-items:start}
  .lower .panel{margin-bottom:24px}
}
/* phone */
@media (max-width:1023px){
  .shell{grid-template-columns:1fr}
  .sidebar{display:none}
  .topbar{display:flex;align-items:center;gap:10px;height:48px;background:var(--surface);border-bottom:1px solid var(--border);padding:0 8px 0 4px;position:sticky;top:0;z-index:30}
  .topbar .menubtn{width:44px;height:44px;display:flex;align-items:center;justify-content:center;font-size:20px;color:var(--ink);cursor:pointer;text-decoration:none}
  .topbar .tname{font-size:16px;font-weight:650}
  .topbar .badge{margin-left:auto;text-decoration:none}
  .sheet{position:fixed;inset:48px 0 0 0;background:var(--ground);z-index:40;padding:10px 16px 24px;overflow-y:auto}
  .navtoggle:checked ~ .sheet{display:block}
  .sheet .navrow{height:44px;font-size:15px}
  .sheet .closebtn{display:flex;align-items:center;height:44px;font-weight:600;color:var(--accent-deep);cursor:pointer}
  .canvas{padding:20px 16px 40px;display:flex;flex-direction:column}
  .headrow{order:1;margin-bottom:16px}
  .headrow .btn-primary{display:none}
  #approvals{order:2}
  #chat{order:3}
  .kpis{order:4;grid-template-columns:1fr 1fr}
  .kpi:nth-child(3){border-left:none}
  .kpi:nth-child(n+3){border-top:1px solid var(--border)}
  #new-brief{order:5}
  #board-sec{order:6}
  .lower{order:7}
  .board{flex-direction:column;overflow-x:visible}
  .col{min-width:0;width:100%}
  button{min-height:44px}
  form.actions input{min-height:44px}
  details.checks summary{min-height:44px;display:flex;align-items:center}
  section.panel{margin-bottom:16px}
}
@media (prefers-reduced-motion: reduce){
  *{transition:none!important;animation:none!important;scroll-behavior:auto!important}
}
"""


def _actions(row: dict[str, str]) -> str:
    """Action buttons for a card, depending on where it sits in the gate."""
    status = row.get("status", "")
    item_id = html.escape(row.get("id", ""))
    if status == "brief_received":
        return (
            '<form method="post" action="/action" class="actions">'
            f'<input type="hidden" name="id" value="{item_id}">'
            '<button class="btn-secondary" name="action" value="run" type="submit">Run pipeline (plan + drafts)</button>'
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
            '<button class="btn-primary" name="action" value="approve" type="submit">Approve</button>'
            "</form>"
            '<form method="post" action="/action" class="actions">'
            f'<input type="hidden" name="id" value="{item_id}">'
            '<input name="reason" placeholder="Rejection reason (kept on the card)">'
            '<button class="btn-secondary" name="action" value="reject" type="submit">Reject</button>'
            "</form>"
            '<form method="post" action="/action" class="edit">'
            f'<input type="hidden" name="id" value="{item_id}">'
            f'<textarea name="draft" rows="3">{draft_text}</textarea>'
            '<button class="btn-ghost" name="action" value="edit" type="submit">Save edit + re-check</button>'
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
            '<button class="btn-secondary" name="action" value="reject" type="submit">Reject</button>'
            "</form>"
            '<form method="post" action="/action" class="edit">'
            f'<input type="hidden" name="id" value="{item_id}">'
            f'<textarea name="draft" rows="3">{draft_text}</textarea>'
            '<button class="btn-ghost" name="action" value="edit" type="submit">Save edit + re-check</button>'
            "</form>"
        )
    if status == "approved":
        return (
            '<form method="post" action="/action" class="actions">'
            f'<input type="hidden" name="id" value="{item_id}">'
            '<input type="datetime-local" name="scheduled_for" '
            'aria-label="Schedule for (optional)">'
            '<button class="btn-secondary" name="action" value="schedule" type="submit">Schedule (dry-run)</button>'
            "</form>"
        )
    if status == "scheduled":
        # After the post goes out, the operator links the platform
        # post ID here; the report stage can then mark it reported.
        return (
            '<form method="post" action="/action" class="actions">'
            f'<input type="hidden" name="id" value="{item_id}">'
            '<input name="post_id" placeholder="Published post ID">'
            '<button class="btn-secondary" name="action" value="link" type="submit">Link post</button>'
            "</form>"
        )
    return ""


# Stage dot colours (Wonder spec section 4): pale tint ladder rising to
# ink, with the accent red reserved for the human gate.
STAGE_DOTS: dict[str, str] = {
    "brief": "#CBBBAE",
    "planned": "#E5A58F",
    "drafted": "#FFBBA6",
    "checked": "#BD0221",
    "awaiting_approval": "#FA1239",
    "scheduled": "#042433",
    "reported": "#595238",
}
COLUMN_TITLES: dict[str, str] = dict(COLUMNS)


def _column_of(row: dict[str, str]) -> str:
    return STATUS_TO_COLUMN.get(row.get("status", ""), "brief")


def _ladder(row: dict[str, str]) -> str:
    """Department progress ladder: seven stage dots joined by a line.

    Completed stages are ink; the current stage is ringed; the
    Awaiting approval stage is always the enlarged accent gate dot.
    """
    column = _column_of(row)
    order = [key for key, _ in COLUMNS]
    current = order.index(column)
    parts = []
    for i, key in enumerate(order):
        classes = "ld"
        if key == "awaiting_approval":
            classes += " gate"
        elif i < current:
            classes += " done"
        if i == current:
            classes += " cur" if key == "awaiting_approval" else " cur-plain"
            if key == "awaiting_approval":
                classes = classes.replace(" gate", "") + " gate"
        parts.append(f'<span class="{classes}"></span>')
        if i < len(order) - 1:
            parts.append('<span class="ll"></span>')
    if column == "awaiting_approval":
        label = "Your gate"
    elif row.get("status", "") not in STATUS_TO_COLUMN:
        label = html.escape(row.get("status", ""))
    else:
        label = COLUMN_TITLES[column]
    return (
        '<div class="ladder">' + "".join(parts)
        + f'<span class="ladder-label">{label}</span></div>'
    )


def _card(row: dict[str, str]) -> str:
    column = _column_of(row)
    title = row.get("topic") or row.get("brief") or "(untitled)"
    meta_bits = [
        b
        for b in (
            row.get("platform", ""),
            row.get("format", ""),
            row.get("angle", ""),
        )
        if b
    ]
    meta = " \u00b7 ".join(html.escape(b) for b in meta_bits)
    date = html.escape(row.get("date", ""))
    extras = ""
    if row.get("visual"):
        name = row["visual"].split("/")[-1]
        extras += (
            f'<img class="poster" src="/visual/{html.escape(name)}" '
            'alt="Post visual">'
        )
    else:
        extras += (
            '<div class="thumb-empty">'
            f'<span class="sdot" style="background:{STAGE_DOTS[column]}"></span>'
            f'{html.escape(COLUMN_TITLES[column])}</div>'
        )
    extras += f'<div class="topic">{html.escape(title)}</div>'
    if row.get("draft"):
        extras += f'<div class="draft">{html.escape(row["draft"][:220])}</div>'
    if meta:
        extras += f'<div class="meta">{meta}</div>'
    extras += _ladder(row)
    # Check evidence stays quiet: one summary chip, full evidence in
    # a collapsed details block (Wonder spec section 4, element 6).
    evidence_bits = []
    if row.get("check_status"):
        evidence_bits.append(html.escape(row["check_status"]).replace("\n", "<br>"))
    if row.get("brief_check"):
        evidence_bits.append("Brief check: " + html.escape(row["brief_check"]))
    if row.get("reject_reason"):
        evidence_bits.append("Rejected: " + html.escape(row["reject_reason"]))
    if row.get("check_status"):
        failed = "[FAIL]" in row["check_status"] or "FAIL" in row["check_status"].split("\n")[0]
        chip = (
            '<span class="chip chip-fail">Checks: fail</span>'
            if failed
            else '<span class="chip chip-pass">Checks: pass</span>'
        )
        extras += f'<div class="checks-line">{chip}</div>'
    if evidence_bits:
        extras += (
            '<details class="checks"><summary>See checks</summary>'
            f'<div class="ev">{"<br>".join(evidence_bits)}</div></details>'
        )
    if row.get("buffer_id"):
        extras += f'<div class="meta">Queue: {html.escape(row["buffer_id"])}</div>'
    if row.get("video"):
        video_name = row["video"].split("/")[-1]
        extras += (
            f'<div class="meta">Video: '
            f'<a href="/visual/{html.escape(video_name)}">'
            f"{html.escape(video_name)}</a></div>"
        )
    return (
        '<div class="card">'
        f'<div class="pillrow"><span class="pill pill-{column}">'
        f'{html.escape(COLUMN_TITLES[column])}</span>'
        f'<span class="date">{date}</span></div>'
        f"{extras}"
        f"{_actions(row)}"
        "</div>"
    )


def _card_compact(row: dict[str, str]) -> str:
    """A card without action forms.

    Used for Awaiting approval items inside the board column: those
    items render with their live action forms in the approvals queue
    only, so an item never carries two approve forms on one page
    (the gate-safety property the PR #5 review established).
    """
    column = _column_of(row)
    title = row.get("topic") or row.get("brief") or "(untitled)"
    date = html.escape(row.get("date", ""))
    body = ""
    if row.get("visual"):
        name = row["visual"].split("/")[-1]
        body += (
            f'<img class="poster" src="/visual/{html.escape(name)}" '
            'alt="Post visual">'
        )
    else:
        body += (
            '<div class="thumb-empty">'
            f'<span class="sdot" style="background:{STAGE_DOTS[column]}"></span>'
            f'{html.escape(COLUMN_TITLES[column])}</div>'
        )
    body += f'<div class="topic">{html.escape(title)}</div>'
    body += _ladder(row)
    body += (
        '<div class="meta">Waiting at your gate - approve it in the '
        '<a href="#approvals">queue above</a>.</div>'
    )
    return (
        '<div class="card">'
        f'<div class="pillrow"><span class="pill pill-{column}">'
        f'{html.escape(COLUMN_TITLES[column])}</span>'
        f'<span class="date">{date}</span></div>'
        f"{body}</div>"
    )


def _variant_media_html(store: Store, media: str) -> str:
    """A variant's media reference for the variants panel.

    A servable image or clip directly under the store's visuals/
    dir renders as a thumbnail through the /visual route (the
    same convention as the board cards); anything else -- a
    reference outside visuals/, a non-media path -- renders as
    the reference text, so what the variant points at is always
    visible and never silently dropped.
    """
    media = (media or "").strip()
    if not media:
        return ""
    parts = media.replace("\\", "/").split("/")
    if (
        len(parts) == 2
        and parts[0] == "visuals"
        and parts[1].lower().endswith((".png", ".mp4"))
        and (store.data_dir / media).exists()
    ):
        name = html.escape(parts[1])
        if parts[1].lower().endswith(".mp4"):
            return (
                f' <video class="poster" src="/visual/{name}" '
                'controls muted preload="metadata"></video>'
            )
        return f' <img class="poster" src="/visual/{name}" alt="Variant visual">'
    return f' <span class="vmedia">[media: {html.escape(media)}]</span>'


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
        cards = "".join(
            _card_compact(r) if r.get("status") == "awaiting_approval" else _card(r)
            for r in by_column[key]
        ) or '<div class="empty">No items</div>'
        columns_html.append(
            f'<div class="col"><h2>{html.escape(title)} '
            f'<span class="n">{len(by_column[key])}</span>'
            f'<span class="sdot" style="background:{STAGE_DOTS[key]}"></span></h2>{cards}</div>'
        )

    # --- KPI strip values: real store data only, honest zeros --------
    awaiting_rows = [r for r in plan_rows if r.get("status") == "awaiting_approval"]
    scheduled_count = sum(1 for r in plan_rows if r.get("status") == "scheduled")
    insights_rows = store.read_dataset("insights")
    followers = "\u2014"
    if insights_rows:
        latest = sorted(insights_rows, key=lambda r: r.get("period_end", ""))[-1]
        followers = html.escape(latest.get("followers", "") or "\u2014")
    total_reach = 0
    for r in metrics_rows:
        try:
            total_reach += int(r.get("reach", "") or 0)
        except ValueError:
            pass

    services = "".join(f"<li>{html.escape(s)}</li>" for s in brand["services"])
    rules = "".join(f"<li>{html.escape(r)}</li>" for r in brand["rules"])
    from .pipeline import BRAND_KEYS

    raw_brand = {r["key"]: r["value"] for r in store.read_dataset("brand_voice")}
    # One edit form per allowlisted key, existing value or blank:
    # the render surface is BRAND_KEYS itself, so a key the owner
    # has never set (a connect-day input, say) is still reachable,
    # and the render surface and the write surface cannot drift
    # apart. Stored secrets render as password fields.
    secret_keys = ("fb_access_token", "postiz_api_key")
    form_parts = []
    for k in BRAND_KEYS:
        value = html.escape(raw_brand.get(k, ""))
        input_type = ' type="password"' if k in secret_keys else ""
        form_parts.append(
            '<form method="post" action="/brand" class="brandedit">'
            f'<label>{html.escape(k)}</label>'
            f'<input type="hidden" name="key" value="{html.escape(k)}">'
            f'<input{input_type} name="value" value="{value}">'
            '<button class="btn-secondary" type="submit">Save</button></form>'
        )
    edit_forms = "".join(form_parts)
    brand_panel = (
        '<section class="panel" id="brand"><h2>Brand voice</h2>'
        f"<div>Audience: {html.escape(brand['audience'])}</div>"
        f"<div>Tone: {html.escape(brand['tone'])}</div>"
        f"<ul>{services}</ul><ul>{rules}</ul>{edit_forms}</section>"
    )

    metrics_panel = ""
    if metrics_rows:
        head = "".join(f"<th>{html.escape(h)}</th>" for h in metrics_rows[0].keys())
        body = "".join(
            "<tr>" + "".join(f"<td>{html.escape(v)}</td>" for v in r.values()) + "</tr>"
            for r in metrics_rows
        )
        metrics_panel = (
            '<section class="panel" id="metrics"><h2>Latest metrics</h2>'
            f'<div class="twrap"><table><tr>{head}</tr>{body}</table></div></section>'
        )

    from .pipeline import current_report, last_report

    report_panel = ""
    saved_report = last_report(store)
    if metrics_rows or saved_report:
        # The panel prefers the last RECORDED report (which carries
        # the model's figure-checked Read); before any run it shows
        # the pure computed report. Rendering never calls a model.
        narrative = html.escape(
            saved_report if saved_report else current_report(store)["narrative"]
        )
        report_panel = (
            '<section class="panel" id="report"><h2>Performance report</h2>'
            f"<pre>{narrative}</pre>"
            '<form method="post" action="/report">'
            '<button class="btn-primary" type="submit">Run report</button></form></section>'
        )

    from .pipeline import last_visibility

    visibility_panel = ""
    saved_visibility = last_visibility(store)
    if saved_visibility:
        visibility_panel = (
            '<section class="panel" id="visibility"><h2>Visibility audit (SEO / GEO / AEO)</h2>'
            f"<pre>{html.escape(saved_visibility)}</pre>"
            '<form method="post" action="/visibility">'
            '<button class="btn-secondary" type="submit">Run visibility audit</button></form></section>'
        )

    from .pipeline import last_content_analysis

    content_panel = ""
    saved_content = last_content_analysis(store)
    if saved_content:
        content_panel = (
            '<section class="panel" id="content"><h2>Content analysis</h2>'
            f"<pre>{html.escape(saved_content)}</pre>"
            '<form method="post" action="/content">'
            '<button class="btn-secondary" type="submit">Run content analysis</button></form></section>'
        )

    from .pipeline import last_audience_analysis

    audience_panel = ""
    saved_audience = last_audience_analysis(store)
    if saved_audience:
        audience_panel = (
            '<section class="panel" id="audience"><h2>Audience analysis</h2>'
            f"<pre>{html.escape(saved_audience)}</pre>"
            '<form method="post" action="/audience">'
            '<button class="btn-secondary" type="submit">Run audience analysis</button></form></section>'
        )

    variants_panel = ""
    variant_rows = store.read_dataset("variants")
    if variant_rows:
        plan_topics = {r["id"]: r.get("topic", "") for r in plan_rows}

        def _variant_item(v):
            line = html.escape(
                f"{plan_topics.get(v['plan_id'], v['plan_id'])} - {v['platform']} "
                f"[{v['check_status']}]: {v['text'][:90]}"
            )
            return "<li>" + line + _variant_media_html(store, v.get("media", "")) + "</li>"

        items = "".join(_variant_item(v) for v in variant_rows)
        variants_panel = (
            '<section class="panel" id="variants"><h2>Cross-platform variants</h2>'
            f"<ul>{items}</ul>"
            '<form method="post" action="/variants">'
            '<button class="btn-secondary" type="submit">Generate variants</button></form></section>'
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
                '<button class="btn-secondary" type="submit">Draft</button></form>'
            )
        if status == "drafted":
            actions += (
                '<form method="post" action="/brand-level" class="edit">'
                f'<input type="hidden" name="level" value="{lvl}">'
                '<input type="hidden" name="action" value="edit">'
                f'<textarea name="content" rows="4">{html.escape(content)}</textarea>'
                '<button class="btn-ghost" type="submit">Save edit</button></form>'
                '<form method="post" action="/brand-level">'
                f'<input type="hidden" name="level" value="{lvl}">'
                '<input type="hidden" name="action" value="approve">'
                '<button class="btn-primary" type="submit">Approve</button></form>'
            )
        bb_items += (
            f"<li>Level {lvl} {html.escape(spec['name'])} [{status}] "
            f"{preview}{actions}</li>"
        )
    brand_builder_panel = (
        '<section class="panel" id="brand-builder"><h2>Brand Builder</h2>'
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
            '<section class="panel" id="research"><h2>Business research</h2>'
            f"<ul>{r_items}</ul>"
            '<form method="post" action="/research">'
            '<input name="brief" placeholder="Business brief">'
            '<button class="btn-secondary" type="submit">Run research</button></form></section>'
        )

    from .heartbeat import schedule_summary, unread_notifications

    unread = unread_notifications(store)
    heartbeat_panel = (
        '<section class="panel" id="heartbeat"><h2>Heartbeat &amp; notifications</h2>'
        f"<p>{html.escape(schedule_summary(store))}</p>"
        '<p class="refresh-note">This page refreshes every 15 seconds.</p>'
    )
    if unread:
        n_items = "".join(
            "<li>" + html.escape(f"[{n['kind']}] {n['message']}") + "</li>"
            for n in unread
        )
        heartbeat_panel += (
            f"<ul>{n_items}</ul>"
            '<form method="post" action="/notifications-read">'
            '<button class="btn-ghost" type="submit">Mark all read</button></form>'
        )
    else:
        heartbeat_panel += "<p>No unread notifications.</p>"
    heartbeat_panel += "</section>"

    # The standing brief the heartbeat prepares each cycle from:
    # read from the data dir's standing-brief.txt, editable here
    # so the owner never has to touch the file by hand.
    brief_file = store.data_dir / "standing-brief.txt"
    try:
        standing_brief_text = brief_file.read_text(encoding="utf-8")
    except OSError:
        standing_brief_text = ""
    standing_brief_panel = (
        '<section class="panel" id="standing-brief"><h2>Standing brief</h2>'
        '<form method="post" action="/standing-brief">'
        f'<textarea name="brief" rows="4">{html.escape(standing_brief_text)}</textarea>'
        '<button class="btn-secondary" type="submit">Save standing brief</button></form>'
        "<p>The weekly heartbeat prepares each cycle from this brief "
        "and stops at your approval gate.</p></section>"
    )

    # --- Chat panel: the owner directs PaCo here; every change is
    # proposed as an exact-change card and only a confirm executes
    # (chat.py holds the safety property, this is just the surface).
    from .chat import render_transcript

    chat_panel = (
        '<section class="panel" id="chat"><h2>PaCo နှင့် စကားပြောရန်</h2>'
        f'<div class="chat-log">{render_transcript(store)}</div>'
        '<form method="post" action="/chat" class="chat-send">'
        '<input name="message" placeholder="လုပ်ချင်တာကို ဒီမှာ ရေးပါ — ဥပမာ status">'
        '<button class="btn-primary" type="submit">ပို့ရန်</button></form></section>'
    )

    brief_form = (
        '<section class="panel" id="new-brief"><h2>New brief</h2>'
        '<form method="post" action="/brief" class="brief">'
        '<input name="goal" placeholder="Goal">'
        '<input name="offer" placeholder="Offer">'
        '<input name="dates" placeholder="Dates">'
        '<input name="notes" placeholder="Notes">'
        '<button class="btn-primary" type="submit">Add brief</button></form></section>'
    )

    # --- Approvals queue: the gate, first on the phone ---------------
    if awaiting_rows:
        queue_cards = "".join(_card(r) for r in awaiting_rows)
        approvals_section = (
            '<section class="panel" id="approvals"><h2>Awaiting your approval '
            f'<span class="badge">{len(awaiting_rows)}</span></h2>'
            f'<div class="gate-rule"></div>{queue_cards}</section>'
        )
    else:
        approvals_section = (
            '<section class="panel" id="approvals"><h2>Awaiting your approval</h2>'
            '<div class="gate-rule"></div>'
            '<div class="empty-state"><div class="l1">Nothing waiting.</div>'
            '<div class="l2">New drafts will appear here for your decision.</div></div></section>'
        )

    kpis = (
        '<div class="kpis">'
        '<a class="kpi kpi-accent" href="#approvals"><div class="klabel">Awaiting approval</div>'
        f'<div class="kvalue">{len(awaiting_rows)}</div>'
        '<div class="kcap">Needs your decision</div></a>'
        '<div class="kpi"><div class="klabel">Scheduled</div>'
        f'<div class="kvalue">{scheduled_count}</div>'
        '<div class="kcap">Ready to publish</div></div>'
        '<div class="kpi"><div class="klabel">Followers</div>'
        f'<div class="kvalue">{followers}</div>'
        '<div class="kcap">Latest insights</div></div>'
        '<div class="kpi"><div class="klabel">Total reach</div>'
        f'<div class="kvalue">{total_reach}</div>'
        '<div class="kcap">All recorded posts</div></div>'
        "</div>"
    )

    brand_name = html.escape(brand["brand_name"] or "PaCo Agent")
    unread_dot = '<span class="udot"></span>' if unread else ""
    nav_groups = [
        ("Work", [
            ("Approvals", "#approvals", True,
             f'<span class="badge">{len(awaiting_rows)}</span>'),
            ("Chat", "#chat", False, ""),
            ("New brief", "#new-brief", False, ""),
            ("Board", "#board-sec", False, ""),
        ]),
        ("Insights", [
            ("Weekly report", "#report", False, ""),
            ("Visibility audit", "#visibility", False, ""),
            ("Content analysis", "#content", False, ""),
            ("Audience analysis", "#audience", False, ""),
        ]),
        ("Studio", [
            ("Variants", "#variants", False, ""),
            ("Brand Builder", "#brand-builder", False, ""),
            ("Research", "#research", False, ""),
            ("Brand data", "#brand", False, ""),
            ("Metrics", "#metrics", False, ""),
        ]),
        ("System", [
            ("Heartbeat", "#heartbeat", False, ""),
            ("Standing brief", "#standing-brief", False, ""),
            ("Notifications", "#heartbeat", False, unread_dot),
        ]),
    ]

    def nav_html() -> str:
        out = []
        for group, items in nav_groups:
            out.append(f'<div class="navgroup">{html.escape(group)}</div>')
            for text, href, active, extra in items:
                cls = "navrow active" if active else "navrow"
                dot = '<span class="cdot"></span>' if active else ""
                out.append(
                    f'<a class="{cls}" href="{href}">{dot}{html.escape(text)}{extra}</a>'
                )
        return "".join(out)

    sidebar = (
        '<aside class="sidebar">'
        '<div class="wordmark">PaCo<span class="dot"></span></div>'
        f'<div class="wordmark-sub">Marketing agent \u00b7 {brand_name}</div>'
        f"{nav_html()}</aside>"
    )
    topbar = (
        '<div class="topbar"><label class="menubtn" for="navtoggle" '
        'aria-label="Menu">&#9776;</label>'
        '<span class="tname">PaCo \u2014 Approvals</span>'
        f'<a class="badge" href="#approvals">{len(awaiting_rows)}</a></div>'
        '<nav class="sheet"><label class="closebtn" for="navtoggle">Close</label>'
        f"{nav_html()}</nav>"
    )
    headrow = (
        '<div class="headrow"><div><h1>Today at PaCo</h1>'
        '<div class="sub">Approve what\u2019s waiting, then check the week.</div></div>'
        '<a class="btn-primary" href="#new-brief">New brief</a></div>'
    )
    board_section = (
        '<section id="board-sec"><div class="board">'
        + "".join(columns_html)
        + "</div></section>"
    )
    lower = (
        '<div class="lower"><div class="lower-main">'
        f"{report_panel}{visibility_panel}{content_panel}{audience_panel}"
        f"{variants_panel}{brand_builder_panel}{research_panel}"
        '</div><div class="lower-rail">'
        f"{brand_panel}{metrics_panel}{heartbeat_panel}{standing_brief_panel}"
        "</div></div>"
    )
    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta http-equiv="refresh" content="15">'
        f"<title>{brand_name} - PaCo board</title><style>{_CSS}</style></head><body>"
        '<input type="checkbox" id="navtoggle" class="navtoggle">'
        f"{topbar}"
        '<div class="shell">'
        f"{sidebar}"
        '<main class="canvas">'
        f"{headrow}{kpis}{approvals_section}{chat_panel}{brief_form}{board_section}{lower}"
        "</main></div>"
        "</body></html>"
    )


def _switcher_html(registry) -> str:
    """The page switcher, injected into both nav surfaces.

    render_board stays single-store and byte-identical; the
    handler composes the multi-page surface around it. The block
    reuses the sidebar's own classes (navgroup, btn-ghost), so no
    new CSS is needed.
    """
    options = "".join(
        f'<option value="{html.escape(p["name"])}"'
        f'{" selected" if p["active"] else ""}>'
        f'{html.escape(p["label"])}</option>'
        for p in registry.pages()
    )
    return (
        '<div class="navgroup">Page</div>'
        '<form method="post" action="/switch-store">'
        f'<select name="store">{options}</select>'
        '<button class="btn-ghost" type="submit">Switch page</button></form>'
        '<form method="post" action="/create-page">'
        '<input name="name" placeholder="New page name">'
        '<button class="btn-ghost" type="submit">Add page</button></form>'
    )


def render_page(registry) -> str:
    """The board for the registry's active store, switcher included."""
    page = render_board(registry.active())
    block = _switcher_html(registry)
    if "</aside>" in page:
        page = page.replace("</aside>", block + "</aside>", 1)
    if "</nav>" in page:
        page = page.replace("</nav>", block + "</nav>", 1)
    return page


def make_handler(store):
    from .stores import StoreRegistry

    registry = (
        store if isinstance(store, StoreRegistry) else StoreRegistry(store)
    )

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 (stdlib naming)
            store = registry.active()
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
            body = render_page(registry).encode("utf-8")
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
            store = registry.active()
            try:
                if self.path == "/switch-store":
                    registry.switch(form.get("store", ""))
                elif self.path == "/create-page":
                    registry.create_page(form.get("name", ""))
                elif self.path == "/brief":
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
                    bundle = fetch_research(brief=brief, store=store)
                    run_business_research(
                        store, get_client(), brief, bundle.get("items", [])
                    )
                elif self.path == "/brand-level":
                    from .brand_builder import approve_level, draft_level, edit_level

                    level = int(form.get("level", "0") or 0)
                    if form.get("action") == "draft":
                        from .model_client import get_client

                        draft_level(store, level, get_client(), form.get("brief", ""))
                    elif form.get("action") == "edit":
                        edit_level(store, level, form.get("content", ""))
                    elif form.get("action") == "approve":
                        approve_level(store, level)
                elif self.path == "/standing-brief":
                    brief_path = store.data_dir / "standing-brief.txt"
                    brief_path.write_text(form.get("brief", ""), encoding="utf-8")
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
                elif self.path == "/notifications-read":
                    from .heartbeat import mark_notifications_read

                    mark_notifications_read(store)
                elif self.path == "/chat":
                    from .chat import handle_message
                    from .model_client import get_client

                    handle_message(store, get_client(), form.get("message", ""))
                elif self.path == "/chat-confirm":
                    from .chat import confirm_proposal
                    from .model_client import (
                        get_client,
                        get_image_client,
                        get_judge_client,
                    )

                    confirm_proposal(
                        store,
                        get_client(),
                        form.get("proposal", ""),
                        judge=get_judge_client(),
                        image_client=get_image_client(),
                    )
                elif self.path == "/chat-cancel":
                    from .chat import cancel_proposal

                    cancel_proposal(store, form.get("proposal", ""))
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

                        scheduled_for = form.get("scheduled_for", "").strip()
                        if scheduled_for:
                            # The owner picked the moment on the
                            # card: store it on the row first, and
                            # the Postiz client sends at that time
                            # instead of now.
                            store.update_row(
                                "plan", item_id, {"scheduled_for": scheduled_for}
                            )
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

        store = open_store(get_settings().data_dir)
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(store))
    print(f"PaCo dashboard: http://127.0.0.1:{port}")
    return server


if __name__ == "__main__":
    import os

    serve(port=int(os.environ.get("PAGEOPS_DASHBOARD_PORT", "8765"))).serve_forever()
