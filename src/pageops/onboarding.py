"""Guided brand onboarding for PaCo (chat-first control, Phase 2).

The fix for the product's real input problem (owner, 2026-11-08):
a new SME page owner cannot fill brand forms correctly, and wrong
target/style input poisons every downstream step. So onboarding
is not a blank form - it is an interview the chat runs one
question at a time, in plain Burmese, over the same transcript
and the same proposal + confirm gate as everything else here:

  - State lives in the store (onboarding dataset), so an
    interview survives a server restart and can be paused
    ("ရပ်မယ်") and resumed ("setup စမယ်") at any point. While a
    session is active, chat messages ARE answers to the current
    question - chat.handle_message checks for an active session
    before intent parsing ever sees the message.
  - Before anything is drafted, the answers are cross-checked
    against the page's own evidence (insights, metrics, existing
    drafts, the analyst summaries), built by build_evidence. A
    genuine contradiction is asked about in plain words and the
    resolution is stored with the answers; the interview never
    silently picks a side. With no evidence, every drafting
    proposal is labelled "based on your answers only".
  - Drafting reuses the Brand Builder untouched: levels 2-5 are
    drafted with draft_level from a brief composed of the
    answers (+ resolutions + evidence), and each draft reaches
    the owner as a proposal card whose confirm is the existing
    approve_level path. Nothing enters brand data before its
    own confirm.
  - The Audience (2) and Positioning (3) levels - the two where
    a wrong call poisons everything downstream - arrive as a
    pick between 2-3 genuinely distinct options first
    (draft_brand_level_options): the owner answers with a
    number, the picked text is recorded as the level's draft
    (record_draft) and only then flows into the same proposal
    card. Picking is a selection, not a brand write, so it has
    no confirm gate of its own. When the model cannot offer a
    real choice (fewer than two usable options), the level
    falls back to the single-draft path and the interview never
    blocks. Levels 4-5 keep the single-draft flow.
  - The pasted own-voice posts are proposed as voice_samples
    through the same set_brand proposal machinery, and the
    closing summary card ("Your target is X. Your style is Y.
    Your offer is Z.") closes the interview only on its own
    confirm. Nothing here runs a content cycle.

Cancelling a proposal is part of the flow, not an error: a level
proposal cancel pauses the session (the draft stays drafted; the
owner may edit it in the dashboard, PR #59, and resume), a
voice-samples cancel skips the samples and moves to the closing
card, and a closing-card cancel pauses so a resume re-proposes it.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from .brand_builder import LEVELS, draft_level, level_statuses, record_draft
from .chat import _append, _propose, pending_proposal
from .context import load_last_audience_analysis, load_last_content_analysis
from .store import Store

QUESTION_STEPS = ("sells", "buyers", "questions", "tone", "examples", "admire")

QUESTION_TEXT = {
    "sells": (
        "ပထမ မေးခွန်းပါ — ဒီ page က ဘာတွေ ရောင်းလဲ၊ ဘာဝန်ဆောင်မှုတွေ "
        "ပေးလဲ ဆိုတာ စာကြောင်းတိုတိုနဲ့ ပြောပြပါ။"
    ),
    "buyers": (
        "ဒုတိယ မေးခွန်း — တကယ် ဝယ်တဲ့သူတွေက ဘယ်သူတွေလဲ။ အသက်အရွယ်၊ "
        "နေတဲ့ မြို့/နေရာ၊ ဒီ page ကို ဘယ်လို ရှာတွေ့လဲ ဆိုတာတွေ "
        "ပါအောင် ပြောပြပါ။"
    ),
    "questions": (
        "တတိယ မေးခွန်း — Messenger မှာ customer တွေ အမေးအများဆုံး "
        "မေးခွန်းတွေက ဘာတွေလဲ။"
    ),
    "examples": (
        "ပဉ္စမ မေးခွန်း — ကိုယ့်အသံနဲ့ ရေးထားတဲ့ post နမူနာ ၂–၃ ခုကို "
        "ဒီမှာ paste လုပ်ပေးပါ။ post တစ်ခုနဲ့ တစ်ခုကြားမှာ စာကြောင်း "
        "အလွတ် တစ်ကြောင်း ခြားပေးပါ။"
    ),
    "admire": (
        "နောက်ဆုံး မေးခွန်း — ကြိုက်တဲ့ / အားကျတဲ့ page တစ်ခု ရှိရင် "
        "နာမည် ပြောပြပါ။ မရှိရင် \"ကျော်မယ်\" လို့ ပြောလိုက်ပါ။"
    ),
}

# Tone is a pick, never a description: three short example
# captions in genuinely different registers, rendered inside the
# question. The owner answers with a number or a name.
TONE_OPTIONS = (
    (
        "friendly",
        "ရင်းနှီးပျူငှာ",
        "မင်္ဂလာပါ အစ်ကို/အစ်မတို့ — ဒီနေ့ ပစ္စည်းအသစ်လေးတွေ "
        "ရောက်ပါတယ်။ ကြိုက်တာလေး တွေ့ရင် message ပို့ပြီး "
        "မေးလိုက်ပါနော်၊ ချက်ချင်း ပြန်ဖြေပေးပါမယ်။",
    ),
    (
        "formal",
        "ယဉ်ကျေးတရားဝင်",
        "မင်္ဂလာပါ။ ကျွန်တော်တို့ page မှ ပစ္စည်းအသစ်များကို "
        "ယနေ့မှ စတင်၍ ရောင်းချပေးနေပါပြီ။ အသေးစိတ် သိရှိလိုပါက "
        "ဆက်သွယ် မေးမြန်းနိုင်ပါသည်။",
    ),
    (
        "playful",
        "ပေါ့ပေါ့ပါးပါး ဟာသ",
        "ဟေ့ — ပစ္စည်းအသစ်တွေ ရောက်နေပြီနော်။ မဝယ်သေးလည်း "
        "လာကြည့်သွားဦး၊ ကြည့်ရင်းနဲ့ ကြိုက်သွားရင်တော့ "
        "မပြောတတ်ဘူး။",
    ),
)

TONE_QUESTION = (
    "စတုတ္ထ မေးခွန်း — page ရဲ့ စကားပြော လေသံကို နမူနာ caption "
    "၃ ခုထဲက ရွေးပါ —\n"
    + "\n".join(
        f"{i}. {label} — \"{caption}\""
        for i, (_key, label, caption) in enumerate(TONE_OPTIONS, 1)
    )
    + "\nနံပါတ် 1 / 2 / 3 နဲ့ ပြန်ဖြေပါ။"
)

_MY_DIGITS = str.maketrans("၁၂၃၄၅၆၇၈၉၀", "1234567890")

# The review phase offers these levels as a pick between
# options before the single draft is proposed: Audience and
# Positioning, the two framing decisions everything else
# inherits. Levels 4-5 keep the single-draft flow.
OPTION_LEVELS = (2, 3)

# Burmese ordinals a pick answer can use, longest first so a
# compound form wins over its own prefix (ပထမဆုံး before ပထမ).
_PICK_ORDINALS = (
    ("ပထမဆုံး", 1),
    ("အရင်ဆုံး", 1),
    ("ပထမ", 1),
    ("ဒုတိယ", 2),
    ("တတိယ", 3),
    ("စတုတ္ထ", 4),
    ("ပဉ္စမ", 5),
    ("ဆဋ္ဌမ", 6),
    ("သတ္တမ", 7),
)

_EXIT_WORDS = {"ရပ်မယ်", "ရပ်ထားမယ်"}
_EXIT_WORDS_EN = {"cancel", "pause", "stop"}
_SKIP_WORDS = {"ကျော်မယ်", "ကျော်", "မရှိ", "မရှိပါ", "skip"}

INTRO_TEXT = (
    "Brand setup စပါမယ်။ form ဖြည့်စရာ မလိုပါဘူး — မေးခွန်း ၆ ခု "
    "တစ်ချင်းစီ မေးပြီး၊ အဖြေတွေနဲ့ page data ကို တိုက်စစ်ပြီး brand "
    "အဆင့်တွေကို ရေးပေးပါမယ်။ အဆင့်တိုင်း အတည်ပြုချက်ရမှ brand data "
    "ထဲ ဝင်မှာပါ။ ကြားထဲမှာ ရပ်ချင်ရင် \"ရပ်မယ်\" လို့ ပြောပါ။\n\n"
)

PAUSED_TEXT = (
    "Setup ကို ခဏ ရပ်ထားပါပြီ။ ပေးထားတဲ့ အဖြေတွေ သိမ်းထားပါတယ် — "
    "ဆက်လုပ်ချင်ရင် \"setup စမယ်\" လို့ ပြောပါ။"
)

SETUP_OFFER_TEXT = (
    "မင်္ဂလာပါ — ဒီ page အတွက် brand data မရှိသေးပါ။ form ဖြည့်စရာ "
    "မလိုပါဘူး၊ ကျွန်တော် မေးခွန်းတွေ တစ်ချင်းစီ မေးပြီး brand setup "
    "ကို chat ထဲမှာပဲ လုပ်ပေးပါမယ်။ စချင်ရင် \"setup စမယ်\" လို့ ပြောပါ။"
)

ANSWERS_ONLY_LABEL = "အဖြေများပေါ်တွင်သာ အခြေခံထားသည် — page data မရှိသေးပါ"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _say(store: Store, text: str) -> dict:
    _append(store, "paco", "reply", text, intent="onboarding")
    return {"intent": "onboarding", "reply": text}


# -- Session state (the store is the state; nothing in memory) --------------


def session_by_id(store: Store, session_id: str) -> dict | None:
    for row in store.read_dataset("onboarding"):
        if row.get("id") == str(session_id):
            return row
    return None


def current_session(store: Store) -> dict | None:
    """The latest unfinished session (active or paused), if any."""
    for row in reversed(store.read_dataset("onboarding")):
        if row.get("status") in ("active", "paused"):
            return row
    return None


def active_session(store: Store) -> dict | None:
    for row in reversed(store.read_dataset("onboarding")):
        if row.get("status") == "active":
            return row
    return None


def _save(store: Store, session: dict, **updates: str) -> dict:
    store.update_row("onboarding", session["id"], updates)
    session.update(updates)
    return session


def _answers(session: dict) -> dict:
    try:
        data = json.loads(session.get("answers") or "{}")
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _store_answers(store: Store, session: dict, answers: dict) -> None:
    _save(store, session, answers=json.dumps(answers, ensure_ascii=False))


def complete_session(store: Store, session_id: str) -> None:
    """Mark a session done (the closing card's confirm action)."""
    session = session_by_id(store, session_id)
    if session is not None and session.get("status") == "active":
        _save(store, session, status="done", step="done")


def brand_is_empty(store: Store) -> bool:
    """The essentially-empty test the setup offer hangs on."""
    return not (store.get_brand_voice().get("brand_name") or "").strip()


# -- Message shapes ------------------------------------------------------------


def is_start_message(message: str) -> bool:
    text = (message or "").strip()
    low = text.lower()
    return "setup စမယ်" in text or low in ("setup", "start setup")


def _is_exit(message: str) -> bool:
    text = (message or "").strip()
    return text in _EXIT_WORDS or text.lower() in _EXIT_WORDS_EN


def _is_skip(message: str) -> bool:
    text = (message or "").strip()
    return text in _SKIP_WORDS or text.lower() == "skip"


# -- Questions -------------------------------------------------------------------


def question_text(step: str, session: dict | None = None) -> str:
    if step == "tone":
        return TONE_QUESTION
    if step.startswith("conflict:") and session is not None:
        answers = _answers(session)
        conflicts = answers.get("_conflicts") or []
        index = int(answers.get("_conflict_index") or 0)
        if index < len(conflicts):
            return conflicts[index].get("question", "")
        return ""
    return QUESTION_TEXT.get(step, "")


def parse_tone(message: str) -> str | None:
    """The tone pick: a number (Latin or Myanmar digits), a
    Burmese ordinal, or the option's own name. Anything else is
    not a pick - the question is asked again."""
    text = (message or "").strip()
    translated = text.translate(_MY_DIGITS)
    if translated in ("1", "2", "3"):
        return TONE_OPTIONS[int(translated) - 1][0]
    for word, key in (("ပထမ", "friendly"), ("ဒုတိယ", "formal"), ("တတိယ", "playful")):
        if word in text:
            return key
    low = text.lower()
    for key, label, _caption in TONE_OPTIONS:
        if label in text or key in low:
            return key
    for word, key in (("ရင်းနှီး", "friendly"), ("ယဉ်ကျေး", "formal"), ("ဟာသ", "playful"), ("ပေါ့ပေါ့", "playful")):
        if word in text:
            return key
    bare = re.search(r"(?<![0-9])([123])(?![0-9])", translated)
    if bare:
        return TONE_OPTIONS[int(bare.group(1)) - 1][0]
    return None


def _tone_label(key: str) -> str:
    for option_key, label, _caption in TONE_OPTIONS:
        if option_key == key:
            return label
    return key


def parse_pick(message: str, count: int) -> int | None:
    """A level-options pick: a number (Latin or Myanmar digits)
    or a Burmese ordinal naming one of the offered options -
    the tone step's parsing discipline. Returns the 1-based
    position, or None (out of range or not a pick at all), in
    which case the step simply asks again."""
    text = (message or "").strip()
    translated = text.translate(_MY_DIGITS)
    if translated.isdigit():
        number = int(translated)
        return number if 1 <= number <= count else None
    for word, position in _PICK_ORDINALS:
        if word in text:
            return position if position <= count else None
    bare = re.search(r"(?<![0-9])([1-9])(?![0-9])", translated)
    if bare:
        number = int(bare.group(1))
        return number if number <= count else None
    return None


def _split_examples(text: str) -> list[str]:
    parts = [p.strip() for p in re.split(r"\n\s*\n", (text or "").strip()) if p.strip()]
    return parts or [(text or "").strip()]


# -- Evidence pack + drafting brief ---------------------------------------------


def build_evidence(store: Store) -> str:
    """One evidence block from what the store already holds:
    insights figures, the metrics' strongest post, existing plan
    drafts/topics, and the recorded audience + content analyses.
    "" when the store holds no page data at all - the caller then
    labels every proposal 'based on your answers only'."""
    parts: list[str] = []
    insights = store.read_dataset("insights")
    if insights:
        last = insights[-1]
        bits = [
            f"{label} {last.get(field, '')}"
            for field, label in (
                ("followers", "followers"),
                ("views", "views"),
                ("unique_viewers", "unique viewers"),
                ("engagements", "engagements"),
                ("new_followers", "new followers"),
            )
            if str(last.get(field, "")).strip()
        ]
        if bits:
            parts.append(
                f"Page insights (period ending {last.get('period_end', '')}): "
                + ", ".join(bits)
                + "."
            )
    plan = store.read_dataset("plan")
    metrics = store.read_dataset("metrics")
    if metrics:
        topics = {r.get("post_id", ""): r.get("topic", "") for r in plan if r.get("post_id")}

        def engagement(row: dict) -> int:
            try:
                return int(row.get("engagement") or 0)
            except ValueError:
                return 0

        top = max(metrics, key=engagement)
        name = topics.get(top.get("post_id", "")) or top.get("post_id", "")
        parts.append(
            f"Metrics: {len(metrics)} recorded post snapshots; the strongest "
            f"is '{name}' on {top.get('platform', '')} with "
            f"{top.get('engagement', '')} engagement and {top.get('reach', '')} reach."
        )
    drafted = [r for r in plan if (r.get("draft") or "").strip()]
    if drafted:
        topics = "; ".join(r.get("topic", "") for r in drafted[:5] if r.get("topic"))
        if topics:
            parts.append(f"Existing post topics on the board: {topics}.")
    audience = load_last_audience_analysis(store)
    if audience.strip():
        parts.append("Audience analysis: " + audience.strip()[:600])
    content = load_last_content_analysis(store)
    if content.strip():
        parts.append("Content analysis: " + content.strip()[:600])
    return "\n".join(parts)


def _drafting_brief(store: Store, session: dict) -> str:
    """The Brand Builder brief: the interview answers verbatim,
    the cross-check resolutions, and the evidence block."""
    answers = _answers(session)
    lines = ["Guided onboarding answers (the owner was interviewed in chat):"]
    lines.append(f"- What the page sells/does: {answers.get('sells', '')}")
    lines.append(f"- Who actually buys: {answers.get('buyers', '')}")
    lines.append(f"- Questions customers ask most: {answers.get('questions', '')}")
    tone = answers.get("tone", "")
    if tone:
        lines.append(
            f"- Tone the owner picked: {_tone_label(tone)} - example: "
            f"{answers.get('tone_example', '')}"
        )
    if answers.get("admire"):
        lines.append(f"- A page the owner admires: {answers['admire']}")
    for key, value in answers.items():
        if key.startswith("conflict_"):
            lines.append(f"- Cross-check resolution ({key[len('conflict_') :]}): {value}")
    evidence = answers.get("_evidence") or ""
    lines.append(
        "Evidence from the page's own data:\n" + evidence
        if evidence
        else "Evidence from the page's own data: (none - base this only on the owner's answers)"
    )
    return "\n".join(lines)


# -- Flow ---------------------------------------------------------------------


def start_or_resume(store: Store, client) -> dict:
    """'setup စမယ်': resume the unfinished session where it
    stopped, or open a new interview at the first question."""
    session = current_session(store)
    if session is not None:
        resumed = session.get("status") == "paused"
        if resumed:
            _save(store, session, status="active")
        result = _continue(store, client, session)
        if resumed and result.get("reply"):
            result = dict(result)
            result["reply"] = "ဆက်လုပ်ပါမယ် — ရပ်ထားတဲ့ နေရာကနေ ပြန်စပါမယ်။\n\n" + result["reply"]
        return result
    rows = store.read_dataset("onboarding")
    session = store.append_row(
        "onboarding",
        {
            "id": str(len(rows) + 1),
            "created": _now(),
            "step": "sells",
            "answers": "{}",
            "status": "active",
        },
    )
    return _say(store, INTRO_TEXT + question_text("sells"))


def _continue(store: Store, client, session: dict) -> dict:
    """Re-render wherever a (resumed) session currently stands."""
    step = session.get("step", "")
    if step in QUESTION_STEPS or step.startswith("conflict:"):
        return _say(store, question_text(step, session))
    return advance(store, client, session)


def handle_active_message(store: Store, client, session: dict, message: str) -> dict:
    """One owner message while a session is active: it IS the
    answer to the current question (checked before intent
    parsing), except the exit word, which pauses, and the start
    phrase, which re-renders the current question."""
    text = (message or "").strip()
    if _is_exit(text):
        _save(store, session, status="paused")
        return _say(store, PAUSED_TEXT)
    if is_start_message(text):
        return _continue(store, client, session)
    step = session.get("step", "")
    answers = _answers(session)

    if step in ("review", "closing"):
        if answers.get("_options"):
            return _handle_pick(store, client, session, answers, text)
        if pending_proposal(store) is not None:
            return _say(
                store,
                "အဆိုပြုချက် တစ်ခု အတည်ပြုရန် စောင့်နေပါတယ် — card မှာ "
                "အတည်ပြု / ဖျက် နှိပ်ပါ။ ရပ်ချင်ရင် \"ရပ်မယ်\" လို့ ပြောပါ။",
            )
        return advance(store, client, session)

    if step.startswith("conflict:"):
        field = step.split(":", 1)[1]
        answers[f"conflict_{field}"] = text
        answers["_conflict_index"] = int(answers.get("_conflict_index") or 0) + 1
        _store_answers(store, session, answers)
        return _next_conflict_or_drafting(store, client, session, answers)

    if step == "tone":
        key = parse_tone(text)
        if key is None:
            return _say(store, "ဘယ်တစ်ခုလဲ မရှင်းလိုက်ပါ —\n" + TONE_QUESTION)
        answers["tone"] = key
        answers["tone_example"] = next(c for k, _l, c in TONE_OPTIONS if k == key)
        _store_answers(store, session, answers)
        _save(store, session, step="examples")
        return _say(store, question_text("examples"))

    if step == "examples":
        answers["examples"] = _split_examples(text)
        _store_answers(store, session, answers)
        _save(store, session, step="admire")
        return _say(store, question_text("admire"))

    if step == "admire":
        answers["admire"] = "" if _is_skip(text) else text
        _store_answers(store, session, answers)
        return _finish_questions(store, client, session, answers)

    if step in QUESTION_STEPS:
        answers[step] = text
        _store_answers(store, session, answers)
        nxt = QUESTION_STEPS[QUESTION_STEPS.index(step) + 1]
        _save(store, session, step=nxt)
        return _say(store, question_text(nxt))

    return _continue(store, client, session)


def _finish_questions(store: Store, client, session: dict, answers: dict) -> dict:
    """Questions done: build the evidence pack, cross-check, and
    either ask the first conflict question or start drafting."""
    evidence = build_evidence(store)
    answers["_evidence"] = evidence
    try:
        conflicts = client.check_onboarding_conflicts(answers, evidence) or []
    except Exception:
        conflicts = []
    answers["_conflicts"] = [
        {"field": str(c.get("field") or ""), "question": str(c.get("question") or "")}
        for c in conflicts
        if isinstance(c, dict) and c.get("question")
    ]
    answers["_conflict_index"] = 0
    _store_answers(store, session, answers)
    if answers["_conflicts"]:
        first = answers["_conflicts"][0]
        _save(store, session, step=f"conflict:{first['field']}")
        return _say(
            store,
            "အဖြေတွေ ရပါပြီ။ ဒါပေမယ့် page data နဲ့ တိုက်စစ်တဲ့အခါ "
            "မေးစရာ တစ်ခု ထွက်လာပါတယ် —\n\n" + first["question"],
        )
    return _begin_review(store, client, session, answers)


def _next_conflict_or_drafting(store: Store, client, session: dict, answers: dict) -> dict:
    conflicts = answers.get("_conflicts") or []
    index = int(answers.get("_conflict_index") or 0)
    if index < len(conflicts):
        _save(store, session, step=f"conflict:{conflicts[index]['field']}")
        return _say(store, conflicts[index]["question"])
    return _begin_review(store, client, session, answers)


def _begin_review(store: Store, client, session: dict, answers: dict) -> dict:
    _save(store, session, step="review")
    note = (
        "ကျေးဇူးပါ — အဖြေတွေ စုံပါပြီ။ အခု brand အဆင့် ၂–၅ ကို "
        "တစ်ဆင့်ချင်း ရေးပေးပါမယ်။ အဆင့်တိုင်း အတည်ပြုမှ brand data "
        "ထဲ ဝင်မှာပါ။"
    )
    if not answers.get("_evidence"):
        note += f"\n({ANSWERS_ONLY_LABEL} — မူကြမ်းတွေက အဖြေများပေါ်တွင်သာ အခြေခံပါမယ်။)"
    _say(store, note)
    return advance(store, client, session)


# -- Review phase: drafting, voice samples, closing card -----------------------


def _options_text(session: dict, level: int, options: list) -> str:
    """The pick step's rendering: how many options were offered,
    each one numbered in full, and how to answer. The message
    lands in the transcript, so what was offered - and how many
    - stays on the record."""
    name = LEVELS[level]["name"]
    label = "" if _answers(session).get("_evidence") else f" ({ANSWERS_ONLY_LABEL})"
    lines = [
        f"Brand အဆင့် {level} ({name}) အတွက် ရွေးစရာ {len(options)} ခု "
        f"ပြင်ထားပါတယ်{label} — တစ်ခုချင်းစီ ရှုထောင့် မတူပါဘူး။ "
        "ကြိုက်တဲ့ တစ်ခုကို နံပါတ်နဲ့ ရွေးပါ။ ရွေးပြီးမှ "
        "အတည်ပြုချက် card ထပ်ပြပါမယ်။"
    ]
    lines += [f"{i}. {text}" for i, text in enumerate(options, 1)]
    lines.append(f"နံပါတ် (1 မှ {len(options)} အထိ) နဲ့ ပြန်ဖြေပါ။")
    return "\n".join(lines)


def _level_options(store: Store, client, session: dict, level: int) -> list | None:
    """The distinct options for one level, cleaned - or None
    when the client cannot offer a real choice (the call failed,
    or fewer than two usable options came back), in which case
    the caller takes the single-draft path and the interview
    never blocks on a pick that is not a choice."""
    brand = store.get_brand_voice()
    try:
        raw = client.draft_brand_level_options(
            LEVELS[level]["name"], _drafting_brief(store, session), brand, count=3
        )
    except Exception:
        return None
    options: list[str] = []
    for entry in raw or []:
        text = str(entry or "").strip()
        if text and text not in options:
            options.append(text)
    return options[:3] if len(options) >= 2 else None


def _handle_pick(store: Store, client, session: dict, answers: dict, text: str) -> dict:
    """One message while level options wait: it IS the pick.
    Picking is a selection, not a brand write - the chosen text
    is recorded as the level's draft and advance then proposes
    it on the ordinary confirm card. Anything that is not a
    valid pick re-renders the options and nothing moves."""
    pick = answers.get("_options") or {}
    options = pick.get("options") or []
    level = int(pick.get("level") or 0)
    if level not in LEVELS or not options:
        answers.pop("_options", None)
        _store_answers(store, session, answers)
        return advance(store, client, session)
    choice = parse_pick(text, len(options))
    if choice is None:
        return _say(store, "ဘယ်တစ်ခုလဲ မရှင်းလိုက်ပါ —\n" + _options_text(session, level, options))
    chosen = options[choice - 1]
    del answers["_options"]
    _store_answers(store, session, answers)
    try:
        record_draft(store, level, chosen)
    except ValueError:
        # The board moved under the pick (the level's gate is no
        # longer open): the stale offer is already dropped, so
        # let advance re-derive the review as the levels stand.
        return advance(store, client, session)
    _say(
        store,
        f"ရွေးစရာ {choice} ကို ရွေးထားပါတယ် — အဲ့ဒီ စာသားကို "
        f"Brand အဆင့် {level} ({LEVELS[level]['name']}) မူကြမ်းအဖြစ် "
        "သတ်မှတ်ပြီး အတည်ပြုချက် card ပြပါမယ်။",
    )
    return advance(store, client, session)


def advance(store: Store, client, session: dict) -> dict:
    """Move the review phase one visible step: propose approval
    of the first unapproved level (drafting it first if needed -
    Audience and Positioning are offered as an options pick
    before their draft is proposed), then the voice samples,
    then the closing card. Idempotent - options already on the
    table are re-rendered, never regenerated, and a level
    already drafted is re-proposed, never re-drafted."""
    if pending_proposal(store) is not None:
        return _say(
            store,
            "အဆိုပြုချက် တစ်ခု အတည်ပြုရန် စောင့်နေပါတယ် — card မှာ "
            "အတည်ပြု / ဖျက် နှိပ်ပါ။",
        )
    answers = _answers(session)
    pending_options = answers.get("_options") or {}
    if pending_options.get("options") and int(pending_options.get("level") or 0) in LEVELS:
        return _say(
            store,
            _options_text(
                session,
                int(pending_options.get("level") or 0),
                pending_options["options"],
            ),
        )
    statuses = level_statuses(store)
    if statuses[1] != "approved":
        _save(store, session, status="paused")
        return _say(
            store,
            "Identity အဆင့် (brand name, အရောင်, font, logo အသုံးပြုပုံ) "
            "အရင် ပြည့်စုံဖို့ လိုပါတယ် — dashboard ရဲ့ brand panel မှာ "
            "ဖြည့်ပြီးမှ \"setup စမယ်\" နဲ့ ပြန်ဆက်ပါ။ setup ကို ခဏ "
            "ရပ်ထားပါတယ်။",
        )
    for level in (2, 3, 4, 5):
        if statuses[level] == "approved":
            continue
        if statuses[level] == "empty":
            if client is None:
                _save(store, session, status="paused")
                return _say(store, PAUSED_TEXT)
            if level in OPTION_LEVELS:
                options = _level_options(store, client, session, level)
                if options is not None:
                    answers["_options"] = {"level": level, "options": options}
                    _store_answers(store, session, answers)
                    return _say(store, _options_text(session, level, options))
            draft_level(store, level, client, _drafting_brief(store, session))
        row = next(
            r for r in store.read_dataset("brand_build") if r.get("level") == str(level)
        )
        return _propose_level(store, session, level, row.get("content", ""))
    return _after_levels(store, session)


def _propose_level(store: Store, session: dict, level: int, content: str) -> dict:
    name = LEVELS[level]["name"]
    label = "" if _answers(session).get("_evidence") else f" ({ANSWERS_ONLY_LABEL})"
    summary = (
        f"Brand အဆင့် {level} ({name}) မူကြမ်း{label} — "
        "အတည်ပြုရင် brand data ထဲ ရေးပါမယ်"
    )
    return _propose(
        store,
        "approve_brand_level",
        summary,
        "",
        {
            "level": level,
            "level_name": name,
            "assumed_content": content,
            "onboarding": session["id"],
        },
    )


def _after_levels(store: Store, session: dict) -> dict:
    """All levels approved: propose the voice samples (unless
    already decided), then the closing summary card."""
    answers = _answers(session)
    samples = answers.get("examples") or []
    if samples and not answers.get("samples_decision"):
        joined = "\n\n".join(samples)
        current = {
            row["key"]: row["value"] for row in store.read_dataset("brand_voice")
        }.get("voice_samples", "")
        if current != joined:
            summary = (
                f"ကိုယ်ပိုင် အသံ နမူနာများ (voice samples) — paste လုပ်ခဲ့တဲ့ "
                f"post {len(samples)} ခုကို brand data ထဲ သိမ်းရန် အဆိုပြုချက်။ "
                "ဒီစာသားတွေက ကိုယ့်အသံနဲ့ တူရဲ့လား စစ်ပေးပါ။"
            )
            return _propose(
                store,
                "set_brand",
                summary,
                "",
                {
                    "brand_key": "voice_samples",
                    "old_value": current,
                    "new_value": joined,
                    "onboarding": session["id"],
                },
            )
        answers["samples_decision"] = "already_present"
        _store_answers(store, session, answers)
    if session.get("step") != "closing":
        _save(store, session, step="closing")
    return _propose_closing(store, session)


def _propose_closing(store: Store, session: dict) -> dict:
    brand = store.get_brand_voice()
    answers = _answers(session)
    audience_line = (brand.get("audience") or "")[:200]
    offer_line = "; ".join(brand.get("services") or [])[:200]
    style_line = _tone_label(answers.get("tone", ""))
    if answers.get("samples_decision") in ("set", "already_present"):
        style_line += f" · ကိုယ်ပိုင် နမူနာ post {len(answers.get('examples') or [])} ခု"
    summary = (
        "Setup အနှစ်ချုပ် — အတည်ပြုရင် setup ပြီးဆုံးပါမယ်\n"
        f"• Target: {audience_line}\n"
        f"• Style: {style_line}\n"
        f"• Offer: {offer_line}"
    )
    return _propose(
        store,
        "close_onboarding",
        summary,
        "",
        {
            "onboarding": session["id"],
            "audience_line": audience_line,
            "style_line": style_line,
            "offer_line": offer_line,
        },
    )


# -- Confirm / cancel hooks (called by the chat layer) --------------------------


def on_confirmed(store: Store, client, proposal: dict) -> None:
    """A confirmed onboarding proposal moves the flow forward:
    the next level is drafted/proposed, samples lead to the
    closing card. The closing card itself completes the session
    inside the confirm's own execution."""
    try:
        payload = json.loads(proposal.get("payload") or "{}")
    except json.JSONDecodeError:
        return
    session = session_by_id(store, payload.get("onboarding", ""))
    if session is None or session.get("status") != "active":
        return
    intent = proposal.get("intent", "")
    if intent == "approve_brand_level":
        advance(store, client, session)
    elif intent == "set_brand" and payload.get("brand_key") == "voice_samples":
        answers = _answers(session)
        answers["samples_decision"] = "set"
        _store_answers(store, session, answers)
        _after_levels(store, session)


def on_cancelled(store: Store, proposal: dict) -> None:
    """Cancels are flow decisions: a level cancel pauses (the
    draft survives for dashboard editing + resume), a samples
    cancel skips the samples and offers the closing card, a
    closing cancel pauses so a resume re-proposes it."""
    try:
        payload = json.loads(proposal.get("payload") or "{}")
    except json.JSONDecodeError:
        return
    session = session_by_id(store, payload.get("onboarding", ""))
    if session is None or session.get("status") != "active":
        return
    intent = proposal.get("intent", "")
    if intent == "approve_brand_level":
        _save(store, session, status="paused")
        _append(
            store,
            "paco",
            "result",
            "Setup ကို ခဏ ရပ်ထားပါတယ် — မူကြမ်းကို dashboard မှာ "
            "ပြင်နိုင်ပြီး \"setup စမယ်\" နဲ့ ပြန်ဆက်နိုင်ပါတယ်။",
        )
    elif intent == "set_brand" and payload.get("brand_key") == "voice_samples":
        answers = _answers(session)
        answers["samples_decision"] = "skipped"
        _store_answers(store, session, answers)
        _after_levels(store, session)
    elif intent == "close_onboarding":
        _save(store, session, status="paused")
