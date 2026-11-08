"""Chat control layer for PaCo (chat-first control, Phase 1).

The owner directs PaCo by chatting, in the dashboard. This module is
the whole layer:

  - Every owner message is parsed into a structured intent by the
    model client (parse_chat_intent). The model classifies and
    copies parameters; it never decides and never supplies facts.
  - Read-only intents (status, report) are answered in code from
    the store: counts, topics and the recorded report text exactly
    as stored. Numbers never come from the model.
  - A mutating intent NEVER executes on the message itself. It
    creates one pending proposal in the chat_log dataset, rendered
    in the transcript as an exact-change card (the item's title and
    FULL draft, the parsed schedule moment rendered in
    Asia/Bangkok, old -> new for a brand value, the full new
    standing brief). Only a separate confirm executes, and it calls
    the same pipeline functions the dashboard buttons call
    (approve_item, reject_item, edit_item, schedule_approved,
    update_brand_voice, the standing-brief file write) - there is
    no second implementation of any action.
  - At confirm time the preconditions the proposal assumed are
    re-validated against the store (item status, the exact draft
    text shown, the brand value, the brief text). Any drift marks
    the proposal stale and nothing executes.
  - One pending proposal at a time: a new mutating message
    supersedes the old pending one, visibly in the transcript.
  - Item references ("the third one", Burmese ordinals like
    ပထမဆုံး, Myanmar digits, topic words) are resolved
    deterministically in code against the board's own order. An
    ambiguous reference proposes nothing and asks.

The transcript lives in the store like everything else (chat_log
dataset), so the CSV and SQLite backends carry it identically.
"""

from __future__ import annotations

import html
import json
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from .pipeline import BRAND_KEYS
from .store import Store

BANGKOK = ZoneInfo("Asia/Bangkok")

READONLY_INTENTS = ("status", "report")
MUTATING_INTENTS = (
    "approve",
    "reject",
    "edit_draft",
    "schedule",
    "set_brand",
    "set_brief",
)

# The plan-row statuses each item intent may act on. These mirror
# the pipeline gates exactly: approve_item takes awaiting_approval
# only; reject_item and edit_item take the two undecided states;
# scheduling takes approved only.
_ITEM_POOLS: dict[str, tuple[str, ...]] = {
    "approve": ("awaiting_approval",),
    "reject": ("awaiting_approval", "checked"),
    "edit_draft": ("awaiting_approval", "checked"),
    "schedule": ("approved",),
}

_ORDINALS = {
    "first": 1,
    "second": 2,
    "third": 3,
    "fourth": 4,
    "fifth": 5,
    "sixth": 6,
    "seventh": 7,
    "eighth": 8,
    "ninth": 9,
    "tenth": 10,
}

# Myanmar digits, in Latin order 1..9,0: a reference written with
# them means exactly what the same digits mean in Latin form.
_MY_DIGIT_TRANSLATION = str.maketrans("၁၂၃၄၅၆၇၈၉၀", "1234567890")

# Burmese ordinals for the queue positions a reference can name.
# Compound forms come before their prefixes (ပထမဆုံး before ပထမ)
# so a fused token matches the longest ordinal it starts with.
_BURMESE_ORDINALS = {
    "ပထမဆုံး": 1,
    "အရင်ဆုံး": 1,
    "ပထမ": 1,
    "ဒုတိယ": 2,
    "တတိယ": 3,
    "စတုတ္ထ": 4,
    "ပဉ္စမ": 5,
    "ဆဋ္ဌမ": 6,
    "သတ္တမ": 7,
}

# The Burmese word for "last" is a position only the pool's own
# length can settle, so the resolver returns it as a marker.
_LAST = "last"
_LAST_WORD = "နောက်ဆုံး"

# Words that frame a reference inside a natural sentence without
# pointing at a topic: English function words, Burmese particles
# and classifiers, words describing the waiting pool the owner is
# pointing into, and the intent verbs themselves (they land in the
# reference when a parser copies a whole sentence). A reference
# resolves positionally when, once these are removed, exactly one
# positional marker is all that remains.
_REF_FILLER = frozenset(
    {
        "the", "post", "posts", "item", "items", "one", "no", "number",
        "ကို", "ဟာ", "က", "တွေ", "ရဲ့", "တဲ့", "တာ",
        "တစ်ခု", "တခု", "ခု", "ခုမြောက်",
        "စောင့်နေတဲ့", "စောင့်နေတာ", "စောင့်နေသော",
        "approve", "reject", "edit", "schedule",
        "လုပ်မယ်", "လုပ်ပါ", "လုပ်ပေးပါ", "လုပ်ပေးမယ်",
    }
)

CAPABILITY_TEXT = (
    "အဲ့ဒါကို နားမလည်လိုက်ပါ။ ကျွန်တော် လုပ်ပေးနိုင်တာတွေက —\n"
    "• အခြေအနေ ကြည့်ရန်: \"status\"\n"
    "• နောက်ဆုံး report: \"report\"\n"
    "• Approve: \"approve post 1\" (သို့) \"approve the third one\" "
    "(သို့) \"ပထမဆုံး post ကို approve လုပ်မယ်\"\n"
    "• Reject: \"reject post 2 because <အကြောင်းရင်း>\"\n"
    "• Draft ပြင်: \"edit post 1: <စာသားအသစ်>\"\n"
    "• Schedule: \"schedule post 1 at 2026-11-10T19:00\"\n"
    "• Brand data ပြင်: \"set tone to <တန်ဖိုးအသစ်>\"\n"
    "• Standing brief လဲ: \"set standing brief to: <brief အသစ်>\"\n"
    "ပြောင်းလဲမှု တိုင်းကို အရင် အဆိုပြုချက် အဖြစ် အတိအကျ ပြပေးပြီး၊ "
    "အတည်ပြုချက်ရမှသာ လုပ်ဆောင်ပါမယ်။"
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _append(
    store: Store,
    role: str,
    kind: str,
    text: str,
    intent: str = "",
    item_id: str = "",
    payload: str = "",
    status: str = "",
) -> dict:
    rows = store.read_dataset("chat_log")
    return store.append_row(
        "chat_log",
        {
            "id": str(len(rows) + 1),
            "created": _now(),
            "role": role,
            "kind": kind,
            "text": text,
            "intent": intent,
            "item_id": item_id,
            "payload": payload,
            "status": status,
        },
    )


def transcript(store: Store) -> list[dict]:
    """The full chat transcript, oldest first."""
    return store.read_dataset("chat_log")


def pending_proposal(store: Store) -> dict | None:
    """The one pending proposal, if any (invariant: at most one)."""
    for row in store.read_dataset("chat_log"):
        if row.get("kind") == "proposal" and row.get("status") == "pending":
            return row
    return None


# -- Intent context and item resolution ------------------------------------


def _intent_context(store: Store) -> dict:
    """What the parser may ground on: the actionable board, in
    board order, and the brand keys it may name. Advisory only -
    resolution and validation happen in code below."""
    rows = store.read_dataset("plan")

    def pool(statuses: tuple[str, ...]) -> list[dict]:
        out = []
        for row in rows:
            if row.get("status") in statuses:
                out.append(
                    {
                        "position": len(out) + 1,
                        "topic": row.get("topic", ""),
                        "platform": row.get("platform", ""),
                        "date": row.get("date", ""),
                        "status": row.get("status", ""),
                    }
                )
        return out

    return {
        "awaiting_decision": pool(("awaiting_approval", "checked")),
        "approved": pool(("approved",)),
        "brand_keys": list(BRAND_KEYS),
    }


def _token_marker(token: str) -> int | str | None:
    """The positional marker a single reference token carries, if
    any: a bare number or counted number ("3", "3ခုမြောက်"), a
    Burmese ordinal (possibly fused with its classifier,
    "ပထမတစ်ခု"), or the last marker (နောက်ဆုံး)."""
    if token == _LAST_WORD:
        return _LAST
    counted = re.fullmatch(r"(\d+)ခုမြောက်", token)
    if counted:
        return int(counted.group(1))
    bare = re.fullmatch(r"(\d+)(?:ခု)?", token)
    if bare:
        return int(bare.group(1))
    for word, position in _BURMESE_ORDINALS.items():
        if token == word:
            return position
        if token.startswith(word) and token[len(word):] in _REF_FILLER:
            return position
    return None


def _ref_index(ref: str) -> int | str | None:
    """How a reference points into its pool: a 1-based position,
    the string "last" for the pool's final item, or None when the
    reference is not positional (it is topic words then).

    Strict shapes first ("post 3", "#3", "the third one" - Latin
    or Myanmar digits alike). Then the natural-sentence scan the
    product's Burmese-speaking owners actually produce: drop the
    filler words that frame a reference and, if exactly one
    positional marker (an English or Burmese ordinal, an
    "N ခုမြောက်" count, နောက်ဆုံး) is all that remains, that
    marker is the position. A reference carrying real content
    words never resolves this way, so a topic containing a digit
    or an ordinal cannot be misread as a position."""
    r = (ref or "").strip().lower().strip('"').translate(_MY_DIGIT_TRANSLATION)
    if not r:
        return None
    if re.fullmatch(r"(post|item|#|no\.?|number)?\s*\d+", r):
        return int(re.search(r"\d+", r).group(0))
    words = [w.strip(".,'\"၊။") for w in r.split()]
    words = [w for w in words if w]
    core = [w for w in words if w not in ("the", "post", "item", "one", "no", "number")]
    if len(words) <= 4 and len(core) == 1 and core[0] in _ORDINALS:
        return _ORDINALS[core[0]]
    markers: list[int | str] = []
    remainder = []
    for token in words:
        marker = _token_marker(token)
        if marker is not None:
            markers.append(marker)
        elif token in _ORDINALS:
            markers.append(_ORDINALS[token])
        elif token not in _REF_FILLER:
            remainder.append(token)
    if len(markers) == 1 and not remainder:
        return markers[0]
    return None


def resolve_item(store: Store, intent: str, item_ref: str) -> tuple[dict | None, str]:
    """Resolve an owner's item reference against the board.

    Queue order is the plan dataset's own order - the same order
    the dashboard's approvals queue renders - so "the third one"
    means the third card the owner sees. Returns (row, "") on a
    unique resolution, else (None, explanation in Burmese).
    """
    pool = [
        row
        for row in store.read_dataset("plan")
        if row.get("status") in _ITEM_POOLS[intent]
    ]
    if not pool:
        return None, "အခု အဲ့ဒီ လုပ်ဆောင်ချက်အတွက် သက်ဆိုင်တဲ့ post မရှိသေးပါ။"
    ref = (item_ref or "").strip()
    if not ref:
        if len(pool) == 1:
            return pool[0], ""
        listing = "\n".join(
            f"{i}. {row.get('topic', '')}" for i, row in enumerate(pool, 1)
        )
        return None, (
            f"post {len(pool)} ခု ရှိနေပါတယ်။ ဘယ်တစ်ခုလဲ နံပါတ်ဖြင့် ပြောပါ —\n{listing}"
        )
    index = _ref_index(ref)
    if index is not None:
        if index == _LAST:
            index = len(pool)
        if 1 <= index <= len(pool):
            return pool[index - 1], ""
        return None, (
            f"post {len(pool)} ခုပဲ ရှိပါတယ်။ {index} ခုမြောက် ဆိုတာ မရှိပါ။"
        )
    words = [w for w in re.split(r"\s+", ref.lower()) if len(w) >= 3]
    probe = words if words else [ref.lower()]
    matches = [
        row
        for row in pool
        if all(w in (row.get("topic", "").lower()) for w in probe)
    ]
    if len(matches) == 1:
        return matches[0], ""
    if not matches:
        return None, (
            "ပြောတဲ့ post ကို မတွေ့ပါ။ နံပါတ် (ဥပမာ post 1) သို့ "
            "topic စာသားဖြင့် ထပ်ပြောပါ။"
        )
    listing = "\n".join(
        f"{i}. {row.get('topic', '')}" for i, row in enumerate(pool, 1)
    )
    return None, (
        f"post {len(matches)} ခု ကိုက်ညီနေပါတယ်။ နံပါတ်ဖြင့် အတိအကျ ပြောပါ —\n{listing}"
    )


# -- Read-only answers (facts from the store, composed in code) ------------


def _status_text(store: Store) -> str:
    rows = store.read_dataset("plan")
    counts: dict[str, int] = {}
    for row in rows:
        status = row.get("status", "")
        counts[status] = counts.get(status, 0) + 1
    awaiting = [r for r in rows if r.get("status") == "awaiting_approval"]
    checked = [r for r in rows if r.get("status") == "checked"]
    approved = [r for r in rows if r.get("status") == "approved"]
    scheduled = [r for r in rows if r.get("status") == "scheduled"]
    lines = ["လက်ရှိ အခြေအနေ —"]
    lines.append(f"• အတည်ပြုရန် စောင့်ဆိုင်းနေသည်: {len(awaiting)} ခု")
    for i, row in enumerate(awaiting, 1):
        lines.append(
            f"  {i}. {row.get('topic', '')} ({row.get('platform', '')}, {row.get('date', '')})"
        )
    if checked:
        lines.append(f"• စစ်ဆေးမှု မအောင်မြင်သေး (checked): {len(checked)} ခု")
    lines.append(f"• Approve လုပ်ပြီး schedule မလုပ်ရသေး: {len(approved)} ခု")
    lines.append(f"• Schedule လုပ်ပြီး: {len(scheduled)} ခု")
    for row in scheduled:
        when = row.get("scheduled_for", "") or row.get("date", "")
        lines.append(f"  - {row.get('topic', '')} ({when})")
    others = {
        s: n
        for s, n in counts.items()
        if s not in ("awaiting_approval", "checked", "approved", "scheduled")
    }
    for status, n in sorted(others.items()):
        lines.append(f"• {status}: {n} ခု")
    return "\n".join(lines)


def _report_text(store: Store) -> str:
    from .pipeline import current_report, last_report

    saved = last_report(store)
    if saved:
        return "နောက်ဆုံး မှတ်တမ်းတင်ထားသော report —\n" + saved
    narrative = current_report(store)["narrative"]
    return "မှတ်တမ်းတင်ထားသော report မရှိသေးပါ။ လက်ရှိ ဂဏန်းများဖြင့် တွက်ထားသော အခြေအနေ —\n" + narrative


# -- Schedule moments --------------------------------------------------------


def _schedule_moment(raw: str) -> datetime | None:
    """Validate a model-proposed moment in code.

    A naive value is read as Asia/Bangkok wall time (the zone the
    product's owner lives in); an offset-aware value is converted.
    Returns the Bangkok moment, or None when the text is not a real
    datetime at all - an invalid moment proposes nothing.
    """
    text = (raw or "").strip()
    if not text:
        return None
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=BANGKOK)
    return moment.astimezone(BANGKOK)


def _moment_store(moment: datetime) -> str:
    """The stored shape: Bangkok wall time, the same naive
    'YYYY-MM-DDTHH:MM' the dashboard's datetime-local input writes,
    so a chat schedule and a card schedule are indistinguishable."""
    return moment.strftime("%Y-%m-%dT%H:%M")


def _moment_display(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%d %H:%M") + " (Asia/Bangkok)"


# -- Message handling --------------------------------------------------------


def _standing_brief(store: Store) -> str:
    try:
        return (store.data_dir / "standing-brief.txt").read_text(encoding="utf-8")
    except OSError:
        return ""


def _raw_brand_value(store: Store, key: str) -> str:
    raw = {row["key"]: row["value"] for row in store.read_dataset("brand_voice")}
    return raw.get(key, "")


def _supersede_pending(store: Store) -> None:
    """A new mutating message cancels the old pending proposal,
    visibly: the proposal is marked and a note joins the transcript."""
    old = pending_proposal(store)
    if old is None:
        return
    store.update_row("chat_log", old["id"], {"status": "superseded"})
    _append(
        store,
        "paco",
        "result",
        f"ယခင် အဆိုပြုချက် (#{old['id']}) ကို ဖျက်လိုက်ပါပြီ — "
        "အဆိုပြုချက် အသစ် ဝင်လာလို့ ဖြစ်ပါတယ်။",
    )


def _propose(store: Store, intent: str, summary: str, item_id: str, payload: dict) -> dict:
    row = _append(
        store,
        "paco",
        "proposal",
        summary,
        intent=intent,
        item_id=item_id,
        payload=json.dumps(payload, ensure_ascii=False),
        status="pending",
    )
    return {"intent": intent, "proposal_id": row["id"], "reply": summary}


def _reply(store: Store, intent: str, text: str) -> dict:
    _append(store, "paco", "reply", text, intent=intent)
    return {"intent": intent, "reply": text}


def handle_message(store: Store, client, message: str) -> dict:
    """Take one owner message: record it, parse the intent, and
    either answer (read-only), ask (ambiguous / incomplete), or
    record ONE pending proposal (mutating). Nothing mutating ever
    executes here - see confirm_proposal."""
    message = (message or "").strip()
    if not message:
        return {"intent": "empty", "reply": ""}
    _append(store, "owner", "message", message)
    try:
        parsed = client.parse_chat_intent(message, _intent_context(store)) or {}
    except Exception:
        parsed = {}
    intent = str(parsed.get("intent") or "unknown").strip().lower()
    fields = {
        name: str(parsed.get(name) or "").strip()
        for name in ("item_ref", "reason", "new_text", "datetime", "brand_key", "value", "brief")
    }

    if intent == "status":
        return _reply(store, intent, _status_text(store))
    if intent == "report":
        return _reply(store, intent, _report_text(store))
    if intent not in MUTATING_INTENTS:
        return _reply(store, "unknown", CAPABILITY_TEXT)

    _supersede_pending(store)

    if intent in _ITEM_POOLS:
        row, problem = resolve_item(store, intent, fields["item_ref"])
        if row is None:
            return _reply(store, intent, problem)
        base = {
            "item_id": row["id"],
            "topic": row.get("topic", ""),
            "assumed_status": row.get("status", ""),
            "assumed_draft": row.get("draft", ""),
        }
        if intent == "approve":
            return _propose(
                store, intent, f"Approve လုပ်ရန် အဆိုပြုချက် — {base['topic']}",
                row["id"], base,
            )
        if intent == "reject":
            if not fields["reason"]:
                return _reply(
                    store, intent,
                    "Reject လုပ်ဖို့ အကြောင်းရင်း လိုပါတယ်။ "
                    "\"reject post 1 because <အကြောင်းရင်း>\" လို့ ပြောပါ။",
                )
            return _propose(
                store, intent,
                f"Reject လုပ်ရန် အဆိုပြုချက် — {base['topic']}",
                row["id"], {**base, "reason": fields["reason"]},
            )
        if intent == "edit_draft":
            if not fields["new_text"]:
                return _reply(
                    store, intent,
                    "Draft အသစ် စာသား မပါလာပါ။ "
                    "\"edit post 1: <စာသားအသစ်>\" လို့ ပြောပါ။",
                )
            return _propose(
                store, intent,
                f"Draft ပြင်ရန် အဆိုပြုချက် — {base['topic']}",
                row["id"], {**base, "new_text": fields["new_text"]},
            )
        # schedule
        moment = _schedule_moment(fields["datetime"])
        if moment is None:
            return _reply(
                store, intent,
                "Schedule အချိန်ကို နားမလည်လိုက်ပါ။ "
                "\"schedule post 1 at 2026-11-10T19:00\" လို့ အတိအကျ ပြောပါ။",
            )
        return _propose(
            store, intent,
            f"Schedule လုပ်ရန် အဆိုပြုချက် — {base['topic']} · {_moment_display(moment)}",
            row["id"],
            {**base, "scheduled_for": _moment_store(moment),
             "scheduled_display": _moment_display(moment)},
        )

    if intent == "set_brand":
        key = fields["brand_key"]
        if key not in BRAND_KEYS:
            return _reply(
                store, intent,
                f"\"{key}\" ဆိုတဲ့ brand data key မရှိပါ။ "
                "Brand panel ထဲမှာ ရှိတဲ့ key နာမည်ဖြင့် ပြောပါ (ဥပမာ tone)။",
            )
        if not fields["value"]:
            return _reply(store, intent, "တန်ဖိုး အသစ် မပါလာပါ။ ထပ်ပြောပါ။")
        old = _raw_brand_value(store, key)
        return _propose(
            store, intent, f"Brand data ပြင်ရန် အဆိုပြုချက် — {key}",
            "",
            {"brand_key": key, "old_value": old, "new_value": fields["value"]},
        )

    # set_brief
    if not fields["brief"]:
        return _reply(
            store, intent,
            "Standing brief အသစ် စာသား မပါလာပါ။ "
            "\"set standing brief to: <brief>\" လို့ ပြောပါ။",
        )
    return _propose(
        store, intent, "Standing brief လဲရန် အဆိုပြုချက်",
        "",
        {"old_brief": _standing_brief(store), "new_brief": fields["brief"]},
    )


# -- Confirm / cancel ----------------------------------------------------------


def _plan_row(store: Store, item_id: str) -> dict | None:
    for row in store.read_dataset("plan"):
        if row.get("id") == str(item_id):
            return row
    return None


def _stale_reason(store: Store, intent: str, payload: dict) -> str:
    """Why the proposal's assumed state no longer holds, or "".

    The proposal card showed the owner an exact change; if the
    world moved under it (a dashboard edit, a status change), the
    confirm must refuse rather than act on a stale picture.
    """
    if intent in _ITEM_POOLS:
        row = _plan_row(store, payload.get("item_id", ""))
        if row is None:
            return "အဲ့ဒီ post က board ပေါ်မှာ မရှိတော့ပါ။"
        if row.get("status", "") != payload.get("assumed_status", ""):
            return (
                f"post ရဲ့ အခြေအနေ ပြောင်းသွားပါပြီ "
                f"({payload.get('assumed_status', '')} → {row.get('status', '')})။"
            )
        if intent in ("approve", "reject", "edit_draft") and (
            row.get("draft", "") != payload.get("assumed_draft", "")
        ):
            return "post ရဲ့ draft စာသား ပြောင်းသွားပါပြီ။ အဆိုပြုချက်က ပြခဲ့တဲ့ စာသား မဟုတ်တော့ပါ။"
        return ""
    if intent == "set_brand":
        current = _raw_brand_value(store, payload.get("brand_key", ""))
        if current != payload.get("old_value", ""):
            return f"{payload.get('brand_key', '')} ရဲ့ လက်ရှိ တန်ဖိုး ပြောင်းသွားပါပြီ။"
        return ""
    if intent == "set_brief":
        if _standing_brief(store) != payload.get("old_brief", ""):
            return "Standing brief စာသား ပြောင်းသွားပါပြီ။"
        return ""
    return "အဆိုပြုချက် အမျိုးအစား မသိပါ။"


def _execute(store: Store, client, intent: str, payload: dict, judge, image_client) -> str:
    """Run a confirmed proposal through the dashboard's own code
    paths and describe the outcome from the resulting store state."""
    from .pipeline import approve_item, edit_item, reject_item, schedule_approved, update_brand_voice

    item_id = payload.get("item_id", "")
    topic = payload.get("topic", "")
    if intent == "approve":
        approve_item(store, item_id)
        return f"Approve လုပ်ပြီးပါပြီ — {topic}"
    if intent == "reject":
        reject_item(store, item_id, payload.get("reason", ""))
        return f"Reject လုပ်ပြီးပါပြီ — {topic}"
    if intent == "edit_draft":
        row = edit_item(
            store, client, item_id, payload.get("new_text", ""),
            judge=judge, image_client=image_client,
        )
        return (
            f"Draft ပြင်ပြီး ပြန်စစ်ပြီးပါပြီ — {topic} "
            f"(အခြေအနေ: {row.get('status', '')})"
        )
    if intent == "schedule":
        scheduled_for = payload.get("scheduled_for", "")
        if scheduled_for:
            store.update_row("plan", item_id, {"scheduled_for": scheduled_for})
        row = schedule_approved(store, item_id)
        return (
            f"Schedule လုပ်ပြီးပါပြီ — {topic} · "
            f"{payload.get('scheduled_display', '')} (queue: {row.get('buffer_id', '')})"
        )
    if intent == "set_brand":
        update_brand_voice(store, payload.get("brand_key", ""), payload.get("new_value", ""))
        return f"Brand data ပြင်ပြီးပါပြီ — {payload.get('brand_key', '')}"
    # set_brief: the same file write the /standing-brief route does.
    (store.data_dir / "standing-brief.txt").write_text(
        payload.get("new_brief", ""), encoding="utf-8"
    )
    return "Standing brief လဲပြီးပါပြီ။"


def confirm_proposal(
    store: Store, client, proposal_id: str, judge=None, image_client=None
) -> dict:
    """Execute one pending proposal - the ONLY way chat mutates.

    Re-validates the proposal's assumed state first; on drift the
    proposal is marked stale, an explanation joins the transcript,
    and nothing executes. Execution failures from the pipeline's
    own gates land the same way: visibly, with nothing half-done
    claimed as done.
    """
    proposal = None
    for row in store.read_dataset("chat_log"):
        if row.get("id") == str(proposal_id) and row.get("kind") == "proposal":
            proposal = row
            break
    if proposal is None:
        raise KeyError(f"No chat proposal with id {proposal_id}")
    if proposal.get("status") != "pending":
        _append(
            store, "paco", "result",
            f"အဆိုပြုချက် #{proposal_id} က {proposal.get('status', '')} "
            "ဖြစ်သွားပြီမို့ လုပ်ဆောင်လို့ မရတော့ပါ။",
        )
        return {"ok": False, "reason": "not_pending"}
    intent = proposal.get("intent", "")
    try:
        payload = json.loads(proposal.get("payload") or "{}")
    except json.JSONDecodeError:
        payload = {}
    stale = _stale_reason(store, intent, payload)
    if stale:
        store.update_row("chat_log", proposal["id"], {"status": "stale"})
        _append(
            store, "paco", "result",
            f"အဆိုပြုချက် #{proposal_id} ကို မလုပ်တော့ပါ — {stale}",
        )
        return {"ok": False, "reason": "stale"}
    try:
        outcome = _execute(store, client, intent, payload, judge, image_client)
    except (KeyError, PermissionError, ValueError) as exc:
        store.update_row("chat_log", proposal["id"], {"status": "stale"})
        _append(
            store, "paco", "result",
            f"အဆိုပြုချက် #{proposal_id} ကို မလုပ်နိုင်ခဲ့ပါ — {exc}",
        )
        return {"ok": False, "reason": "execution_failed"}
    store.update_row("chat_log", proposal["id"], {"status": "confirmed"})
    _append(store, "paco", "result", outcome)
    return {"ok": True, "outcome": outcome}


def cancel_proposal(store: Store, proposal_id: str) -> dict:
    """Cancel one pending proposal; the transcript keeps the fact."""
    for row in store.read_dataset("chat_log"):
        if row.get("id") == str(proposal_id) and row.get("kind") == "proposal":
            if row.get("status") == "pending":
                store.update_row("chat_log", row["id"], {"status": "cancelled"})
                _append(
                    store, "paco", "result",
                    f"အဆိုပြုချက် #{proposal_id} ကို ဖျက်လိုက်ပါပြီ။ "
                    "ဘာမှ မပြောင်းလဲပါ။",
                )
                return {"ok": True}
            _append(
                store, "paco", "result",
                f"အဆိုပြုချက် #{proposal_id} က {row.get('status', '')} "
                "ဖြစ်သွားပြီမို့ ဖျက်စရာ မလိုတော့ပါ။",
            )
            return {"ok": False, "reason": "not_pending"}
    raise KeyError(f"No chat proposal with id {proposal_id}")


# -- Transcript rendering (dashboard) -----------------------------------------

_PROPOSAL_OUTCOMES = {
    "confirmed": "အတည်ပြုပြီး လုပ်ဆောင်ပြီးပါပြီ။",
    "cancelled": "ဖျက်လိုက်ပါပြီ။",
    "superseded": "အဆိုပြုချက် အသစ်နှင့် လဲလိုက်ပါပြီ။",
    "stale": "အခြေအနေ ပြောင်းသွားလို့ မလုပ်တော့ပါ။",
}


def _proposal_card(store: Store, row: dict, plan_by_id: dict) -> str:
    try:
        payload = json.loads(row.get("payload") or "{}")
    except json.JSONDecodeError:
        payload = {}
    intent = row.get("intent", "")
    item = plan_by_id.get(row.get("item_id", ""), {})
    topic = payload.get("topic") or item.get("topic", "")
    parts = [f'<div class="topic">{html.escape(row.get("text", ""))}</div>']
    meta_bits = [
        b for b in (item.get("platform", ""), item.get("date", "")) if b
    ]
    if meta_bits:
        parts.append(
            '<div class="meta">' + " \u00b7 ".join(html.escape(b) for b in meta_bits) + "</div>"
        )
    if intent in ("approve", "reject"):
        parts.append(
            f'<div class="chat-text">{html.escape(payload.get("assumed_draft", ""))}</div>'
        )
    if intent == "reject":
        parts.append(
            f'<div class="meta">အကြောင်းရင်း: {html.escape(payload.get("reason", ""))}</div>'
        )
    if intent == "edit_draft":
        parts.append('<div class="meta">လက်ရှိ draft:</div>')
        parts.append(
            f'<div class="chat-text">{html.escape(payload.get("assumed_draft", ""))}</div>'
        )
        parts.append('<div class="meta">အသစ် draft:</div>')
        parts.append(
            f'<div class="chat-text">{html.escape(payload.get("new_text", ""))}</div>'
        )
    if intent == "schedule":
        parts.append(
            f'<div class="meta">အချိန်: {html.escape(payload.get("scheduled_display", ""))}</div>'
        )
    if intent == "set_brand":
        parts.append(
            f'<div class="meta">{html.escape(payload.get("brand_key", ""))}</div>'
            f'<div class="chat-text">လက်ရှိ: {html.escape(payload.get("old_value", ""))}</div>'
            f'<div class="chat-text">အသစ်: {html.escape(payload.get("new_value", ""))}</div>'
        )
    if intent == "set_brief":
        parts.append(
            f'<div class="chat-text">{html.escape(payload.get("new_brief", ""))}</div>'
        )
    if row.get("status") == "pending":
        parts.append(
            '<form method="post" action="/chat-confirm" class="actions">'
            f'<input type="hidden" name="proposal" value="{html.escape(row.get("id", ""))}">'
            '<button class="btn-primary" type="submit">အတည်ပြုရန်</button></form>'
            '<form method="post" action="/chat-cancel" class="actions">'
            f'<input type="hidden" name="proposal" value="{html.escape(row.get("id", ""))}">'
            '<button class="btn-secondary" type="submit">ဖျက်ရန်</button></form>'
        )
    else:
        outcome = _PROPOSAL_OUTCOMES.get(row.get("status", ""), row.get("status", ""))
        parts.append(f'<div class="meta">{html.escape(outcome)}</div>')
    return '<div class="card chat-prop">' + "".join(parts) + "</div>"


def render_transcript(store: Store, limit: int = 60) -> str:
    """The transcript as HTML for the dashboard chat panel:
    owner lines, PaCo replies, and proposal cards, oldest first."""
    rows = transcript(store)[-limit:]
    plan_by_id = {r["id"]: r for r in store.read_dataset("plan")}
    out = []
    for row in rows:
        kind = row.get("kind", "")
        if kind == "proposal":
            out.append(_proposal_card(store, row, plan_by_id))
        elif row.get("role") == "owner":
            out.append(
                '<div class="chat-msg chat-owner"><span class="chat-who">သင်</span>'
                f'<div class="chat-text">{html.escape(row.get("text", ""))}</div></div>'
            )
        else:
            out.append(
                '<div class="chat-msg"><span class="chat-who">PaCo</span>'
                f'<div class="chat-text">{html.escape(row.get("text", ""))}</div></div>'
            )
    if not out:
        return (
            '<div class="empty-state"><div class="l1">စကားဝိုင်း မရှိသေးပါ။</div>'
            '<div class="l2">အောက်မှာ ရေးပြီး စတင်ပါ — ဥပမာ "status"။</div></div>'
        )
    return "".join(out)
