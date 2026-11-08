"""Guided brand onboarding (chat-first control, Phase 2).

The properties under test are the fix for the product's input
problem: a new owner is interviewed one plain question at a time
instead of facing blank forms; answers are cross-checked against
the page's own evidence before anything is drafted; drafting runs
through the existing Brand Builder and every level still enters
brand data only through its own proposal + confirm; the closing
summary card, not the last answer, is what ends the interview.
"""
import json

from pageops.brand_builder import level_statuses
from pageops.chat import (
    cancel_proposal,
    confirm_proposal,
    handle_message,
    pending_proposal,
)
from pageops.context import save_last_audience_analysis
from pageops.model_client import MockClient
from pageops.onboarding import active_session, current_session
from pageops.pipeline import update_brand_voice
from pageops.store import Store

EXAMPLES = (
    "နမူနာ post တစ်ခု — ကိုယ့်အသံနဲ့ ရေးထားတာ။\n"
    "\n"
    "နမူနာ post နှစ်ခု — နောက်တစ်မျိုး အသံ။"
)
JOINED_SAMPLES = (
    "နမူနာ post တစ်ခု — ကိုယ့်အသံနဲ့ ရေးထားတာ။\n\n"
    "နမူနာ post နှစ်ခု — နောက်တစ်မျိုး အသံ။"
)
BUYERS_NO_CITY = "အသက် ၂၀–၃၅ နှစ် လူငယ်တွေ၊ Facebook က ရှာတွေ့ပါတယ်"


def _raw_brand(store):
    return {row["key"]: row["value"] for row in store.read_dataset("brand_voice")}


def _answers(store):
    session = current_session(store) or store.read_dataset("onboarding")[-1]
    return json.loads(session["answers"])


def _start(store, client):
    return handle_message(store, client, "setup စမယ်")


def _answer_questions(store, client, buyers=BUYERS_NO_CITY):
    """Run the six interview questions with plain answers."""
    _start(store, client)
    handle_message(store, client, "ဖုန်း accessories ရောင်းပါတယ်")
    handle_message(store, client, buyers)
    handle_message(store, client, "ဈေးနှုန်းနဲ့ delivery အချိန် အမေးများပါတယ်")
    handle_message(store, client, "1")
    handle_message(store, client, EXAMPLES)
    return handle_message(store, client, "ကျော်မယ်")


def _confirm_pending(store, client):
    proposal = pending_proposal(store)
    assert proposal is not None
    result = confirm_proposal(store, client, proposal["id"])
    assert result["ok"]
    return proposal


def _options(store):
    """The level options currently on the table, if any."""
    return _answers(store).get("_options") or {}


def _pick(store, client, choice="1"):
    """Answer the pending level-options pick; returns the
    proposal card the pick produces."""
    assert pending_proposal(store) is None
    assert _options(store).get("options")
    handle_message(store, client, choice)
    proposal = pending_proposal(store)
    assert proposal is not None and proposal["intent"] == "approve_brand_level"
    return proposal


def _confirm_all_levels(store, client):
    # Audience and Positioning are picks before they are
    # proposals; Offer and Journey are proposed directly.
    for _level in (2, 3):
        _pick(store, client)
        _confirm_pending(store, client)
    for _level in (4, 5):
        proposal = pending_proposal(store)
        assert proposal is not None and proposal["intent"] == "approve_brand_level"
        _confirm_pending(store, client)


# -- Starting, questions, tone pick -------------------------------------------


def test_start_begins_interview_at_first_question(tmp_path):
    store = Store(tmp_path)
    result = _start(store, MockClient())
    assert result["intent"] == "onboarding"
    assert "ပထမ မေးခွန်း" in result["reply"]
    session = active_session(store)
    assert session is not None and session["step"] == "sells"
    assert session["status"] == "active"


def test_messages_while_active_are_answers_not_intents(tmp_path):
    store = Store(tmp_path)
    client = MockClient()
    _start(store, client)
    result = handle_message(store, client, "status")
    # "status" would be a read-only intent outside the interview;
    # inside it, it is simply the answer to "what do you sell".
    assert result["intent"] == "onboarding"
    assert _answers(store)["sells"] == "status"
    assert active_session(store)["step"] == "buyers"


def test_tone_is_a_pick_and_a_bad_answer_reasks(tmp_path):
    store = Store(tmp_path)
    client = MockClient()
    _start(store, client)
    handle_message(store, client, "ဖုန်း accessories ရောင်းပါတယ်")
    handle_message(store, client, BUYERS_NO_CITY)
    result = handle_message(store, client, "ဈေးနှုန်း အမေးများပါတယ်")
    # The tone question renders the three example captions.
    assert "ရင်းနှီးပျူငှာ" in result["reply"]
    assert "ယဉ်ကျေးတရားဝင်" in result["reply"]
    assert "ပေါ့ပေါ့ပါးပါး ဟာသ" in result["reply"]
    result = handle_message(store, client, "ဘာကြီးလဲ မသိပါ")
    assert active_session(store)["step"] == "tone"
    assert "tone" not in _answers(store)
    result = handle_message(store, client, "၂")
    assert _answers(store)["tone"] == "formal"
    assert active_session(store)["step"] == "examples"
    assert "ပဉ္စမ မေးခွန်း" in result["reply"]


def test_empty_brand_first_reply_offers_setup(tmp_path):
    store = Store(tmp_path)
    update_brand_voice(store, "brand_name", "")
    result = handle_message(store, MockClient(), "hello there")
    assert result["intent"] == "unknown"
    assert "setup စမယ်" in result["reply"]
    assert "brand data မရှိသေးပါ" in result["reply"]


def test_setup_offer_only_when_brand_is_empty(tmp_path):
    store = Store(tmp_path)  # seeded brand: brand_name present
    result = handle_message(store, MockClient(), "hello there")
    assert "နားမလည်လိုက်ပါ" in result["reply"]  # the capability list


# -- Pause / resume -------------------------------------------------------------


def test_exit_word_pauses_and_later_message_is_not_an_answer(tmp_path):
    store = Store(tmp_path)
    client = MockClient()
    _start(store, client)
    handle_message(store, client, "ဖုန်း accessories ရောင်းပါတယ်")
    result = handle_message(store, client, "ရပ်မယ်")
    assert current_session(store)["status"] == "paused"
    result = handle_message(store, client, "status")
    assert result["intent"] == "status"  # normal chat path again
    assert "buyers" not in _answers(store)  # nothing was eaten
    result = handle_message(store, client, "setup စမယ်")
    assert active_session(store) is not None
    assert "ဒုတိယ မေးခွန်း" in result["reply"]  # resumes at buyers


def test_resume_after_restart_rerenders_current_question(tmp_path):
    client = MockClient()
    store = Store(tmp_path)
    _start(store, client)
    handle_message(store, client, "ဖုန်း accessories ရောင်းပါတယ်")
    handle_message(store, client, BUYERS_NO_CITY)
    handle_message(store, client, "ရပ်မယ်")

    reopened = Store(tmp_path)  # a new instance over the same data dir
    session = current_session(reopened)
    assert session is not None and session["status"] == "paused"
    assert session["step"] == "questions"
    result = handle_message(reopened, client, "setup စမယ်")
    assert "တတိယ မေးခွန်း" in result["reply"]
    assert _answers(reopened)["buyers"] == BUYERS_NO_CITY


# -- The full walkthrough ---------------------------------------------------------


def test_full_walkthrough_levels_samples_and_closing(tmp_path):
    store = Store(tmp_path)
    client = MockClient()
    before_brand = store.read_dataset("brand_voice")

    result = _answer_questions(store, client)
    # Drafting begins with a level-2 options pick, labelled
    # answers-only (this store holds no page evidence): three
    # options on the table, no proposal yet, nothing drafted,
    # and brand data exactly as it was.
    assert pending_proposal(store) is None
    offered = _options(store)
    assert offered["level"] == 2 and len(offered["options"]) == 3
    assert "ရွေးစရာ 3 ခု" in result["reply"]
    assert "အဖြေများပေါ်တွင်သာ" in result["reply"]
    assert store.read_dataset("brand_voice") == before_brand
    assert level_statuses(store)[2] == "empty"

    # The pick records option 1 as the draft; the proposal card
    # carries exactly that text, and brand data still has not
    # moved - only the confirm writes there.
    proposal = _pick(store, client, "1")
    assert "အဖြေများပေါ်တွင်သာ" in proposal["text"]
    assert json.loads(proposal["payload"])["assumed_content"] == offered["options"][0]
    assert level_statuses(store)[2] == "drafted"
    assert store.read_dataset("brand_voice") == before_brand

    _confirm_pending(store, client)
    assert "Audience for" in store.get_brand_voice()["audience"]
    assert level_statuses(store)[2] == "approved"

    _pick(store, client, "1")  # Positioning is an options pick too
    _confirm_pending(store, client)
    assert level_statuses(store)[3] == "approved"

    for level in (4, 5):
        # Offer and Journey keep the single-draft flow: their
        # proposal is already waiting, no pick in between.
        assert not _options(store)
        proposal = pending_proposal(store)
        assert proposal is not None and proposal["intent"] == "approve_brand_level"
        _confirm_pending(store, client)
        assert level_statuses(store)[level] == "approved"

    # Voice samples are proposed, not written, until confirmed.
    proposal = pending_proposal(store)
    assert proposal is not None and proposal["intent"] == "set_brand"
    assert json.loads(proposal["payload"])["brand_key"] == "voice_samples"
    assert _raw_brand(store).get("voice_samples", "") == ""
    _confirm_pending(store, client)
    assert _raw_brand(store)["voice_samples"] == JOINED_SAMPLES

    # The closing card: the interview is still open until IT is
    # confirmed, and its text carries target / style / offer.
    proposal = pending_proposal(store)
    assert proposal is not None and proposal["intent"] == "close_onboarding"
    assert "Target:" in proposal["text"] and "Style:" in proposal["text"]
    assert "Offer:" in proposal["text"]
    assert current_session(store)["status"] == "active"
    _confirm_pending(store, client)
    assert store.read_dataset("onboarding")[-1]["status"] == "done"
    transcript_text = "\n".join(r["text"] for r in store.read_dataset("chat_log"))
    assert "Setup ပြီးဆုံးပါပြီ" in transcript_text
    assert "brief" in transcript_text  # the first brief is offered


def test_level_proposal_cancel_pauses_and_resume_reproposes(tmp_path):
    store = Store(tmp_path)
    client = MockClient()
    _answer_questions(store, client)
    _pick(store, client, "1")
    proposal = pending_proposal(store)
    first_content = json.loads(proposal["payload"])["assumed_content"]
    cancel_proposal(store, proposal["id"])
    assert current_session(store)["status"] == "paused"
    assert level_statuses(store)[2] == "drafted"  # the draft survives
    assert "Audience for" not in store.get_brand_voice()["audience"]

    result = handle_message(store, client, "setup စမယ်")
    assert active_session(store) is not None
    reproposed = pending_proposal(store)
    assert reproposed is not None and reproposed["id"] != proposal["id"]
    assert json.loads(reproposed["payload"])["assumed_content"] == first_content
    _confirm_pending(store, client)
    assert level_statuses(store)[2] == "approved"


def test_samples_cancel_skips_to_closing_card(tmp_path):
    store = Store(tmp_path)
    client = MockClient()
    _answer_questions(store, client)
    _confirm_all_levels(store, client)
    proposal = pending_proposal(store)
    assert proposal is not None and proposal["intent"] == "set_brand"
    cancel_proposal(store, proposal["id"])
    assert _raw_brand(store).get("voice_samples", "") == ""
    closing = pending_proposal(store)
    assert closing is not None and closing["intent"] == "close_onboarding"
    _confirm_pending(store, client)
    assert store.read_dataset("onboarding")[-1]["status"] == "done"


def test_closing_cancel_pauses_instead_of_closing(tmp_path):
    store = Store(tmp_path)
    client = MockClient()
    _answer_questions(store, client)
    _confirm_all_levels(store, client)
    _confirm_pending(store, client)  # voice samples
    closing = pending_proposal(store)
    assert closing is not None and closing["intent"] == "close_onboarding"
    cancel_proposal(store, closing["id"])
    assert current_session(store)["status"] == "paused"  # NOT done
    handle_message(store, client, "setup စမယ်")
    reproposed = pending_proposal(store)
    assert reproposed is not None and reproposed["intent"] == "close_onboarding"
    _confirm_pending(store, client)
    assert store.read_dataset("onboarding")[-1]["status"] == "done"


# -- Evidence cross-check ---------------------------------------------------------


def test_conflict_with_evidence_is_asked_before_drafting(tmp_path):
    store = Store(tmp_path)
    client = MockClient()
    save_last_audience_analysis(
        store, "Most engagers live in Mandalay and comment late at night."
    )
    _start(store, client)
    handle_message(store, client, "ဖုန်း accessories ရောင်းပါတယ်")
    handle_message(
        store, client, "အသက် ၂၅–၄၀၊ ရန်ကုန်က လူတွေ အများဆုံး ဝယ်ပါတယ်"
    )
    handle_message(store, client, "ဈေးနှုန်း အမေးများပါတယ်")
    handle_message(store, client, "1")
    handle_message(store, client, EXAMPLES)
    result = handle_message(store, client, "ကျော်မယ်")
    # Owner said Yangon; the page's data says Mandalay. The
    # interview asks, in plain words, and drafts nothing yet.
    assert "မန္တလေး" in result["reply"] and "ရန်ကုန်" in result["reply"]
    assert active_session(store)["step"] == "conflict:buyers"
    assert pending_proposal(store) is None
    assert level_statuses(store)[2] == "empty"

    result = handle_message(store, client, "နှစ်မြို့လုံး target ထားပါ")
    assert _answers(store)["conflict_buyers"] == "နှစ်မြို့လုံး target ထားပါ"
    # Drafting opens with the level-2 options pick; the
    # proposal follows the pick.
    assert pending_proposal(store) is None
    assert _options(store)["level"] == 2
    _pick(store, client, "1")
    proposal = pending_proposal(store)
    assert proposal is not None and proposal["intent"] == "approve_brand_level"
    # Evidence exists here, so no answers-only label.
    assert "အဖြေများပေါ်တွင်သာ" not in proposal["text"]


def test_no_conflict_when_answer_and_evidence_agree(tmp_path):
    store = Store(tmp_path)
    client = MockClient()
    save_last_audience_analysis(store, "Most engagers live in Mandalay.")
    _start(store, client)
    handle_message(store, client, "ဖုန်း accessories ရောင်းပါတယ်")
    handle_message(store, client, "အသက် ၂၅–၄၀၊ မန္တလေးက လူတွေ ဝယ်ပါတယ်")
    handle_message(store, client, "ဈေးနှုန်း အမေးများပါတယ်")
    handle_message(store, client, "1")
    handle_message(store, client, EXAMPLES)
    handle_message(store, client, "ကျော်မယ်")
    assert active_session(store)["step"] == "review"
    # The review opens with the level-2 options pick, and the
    # first proposal follows the pick.
    assert _options(store)["level"] == 2
    _pick(store, client, "1")
    assert pending_proposal(store) is not None


def test_mock_conflict_check_shapes():
    client = MockClient()
    assert client.check_onboarding_conflicts({"buyers": "ရန်ကုန်"}, "") == []
    assert client.check_onboarding_conflicts(
        {"buyers": "ရန်ကုန်က လူတွေ"}, "no city data here"
    ) == []
    conflicts = client.check_onboarding_conflicts(
        {"buyers": "ရန်ကုန်က လူတွေ"}, "Audience analysis: Mandalay leads."
    )
    assert len(conflicts) == 1 and conflicts[0]["field"] == "buyers"
    assert "မန္တလေး" in conflicts[0]["question"]


# -- Level options: the Audience / Positioning picks ----------------------------


def test_options_render_for_level_two_with_three_choices(tmp_path):
    store = Store(tmp_path)
    client = MockClient()
    result = _answer_questions(store, client)
    offered = _options(store)
    assert offered["level"] == 2
    assert len(offered["options"]) == 3
    assert len(set(offered["options"])) == 3  # distinct, not rewordings
    for i, text in enumerate(offered["options"], 1):
        assert f"{i}. {text}" in result["reply"]
    # The transcript itself notes how many options were offered.
    transcript_text = "\n".join(r["text"] for r in store.read_dataset("chat_log"))
    assert "ရွေးစရာ 3 ခု" in transcript_text
    # Nothing is drafted and nothing is proposed before the pick.
    assert pending_proposal(store) is None
    assert level_statuses(store)[2] == "empty"


def test_picking_in_myanmar_digits_selects_that_option(tmp_path):
    store = Store(tmp_path)
    client = MockClient()
    before_brand = store.read_dataset("brand_voice")
    _answer_questions(store, client)
    offered = _options(store)["options"]
    proposal = _pick(store, client, "၂")
    # The proposal carries exactly the second option's text.
    assert json.loads(proposal["payload"])["assumed_content"] == offered[1]
    assert level_statuses(store)[2] == "drafted"
    # The pick alone wrote nothing to brand data; the confirm does.
    assert store.read_dataset("brand_voice") == before_brand
    _confirm_pending(store, client)
    assert store.get_brand_voice()["audience"] == offered[1]


def test_invalid_pick_reasks_without_advancing(tmp_path):
    store = Store(tmp_path)
    client = MockClient()
    _answer_questions(store, client)
    result = handle_message(store, client, "ဘာကြီးလဲ မသိပါ")
    assert "ဘယ်တစ်ခုလဲ မရှင်းလိုက်ပါ" in result["reply"]
    assert _options(store)["level"] == 2
    assert pending_proposal(store) is None
    assert level_statuses(store)[2] == "empty"
    result = handle_message(store, client, "5")  # out of range
    assert "ဘယ်တစ်ခုလဲ မရှင်းလိုက်ပါ" in result["reply"]
    assert _options(store)["level"] == 2
    _pick(store, client, "တတိယ")  # a Burmese ordinal also picks
    assert level_statuses(store)[2] == "drafted"


class _OneOptionClient(MockClient):
    """A model that can only ever offer a single 'option'."""

    def draft_brand_level_options(self, level_name, brief, brand_voice, count=3):
        return ["One lonely option, not a choice."]


def test_fewer_than_two_options_falls_back_to_single_draft(tmp_path):
    store = Store(tmp_path)
    client = _OneOptionClient()
    _answer_questions(store, client)
    # No pick is offered; the level arrives as the ordinary
    # single-draft proposal and the interview never blocked.
    assert not _options(store)
    proposal = pending_proposal(store)
    assert proposal is not None and proposal["intent"] == "approve_brand_level"
    content = json.loads(proposal["payload"])["assumed_content"]
    assert content.startswith("Audience for")  # the single-draft shape
    assert level_statuses(store)[2] == "drafted"


def test_pick_and_mock_option_shapes():
    from pageops.onboarding import parse_pick

    client = MockClient()
    options = client.draft_brand_level_options(
        "Audience", "a brief", {"brand_name": "FYF AI"}
    )
    assert len(options) == 3 and len(set(options)) == 3
    assert parse_pick("2", 3) == 2
    assert parse_pick("၂", 3) == 2
    assert parse_pick("ဒုတိယ", 3) == 2
    assert parse_pick("ပထမဆုံး", 3) == 1
    assert parse_pick("5", 3) is None
    assert parse_pick("ဘာကြီးလဲ", 3) is None
