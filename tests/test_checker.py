from pageops.checker import check_draft

BRAND_VOICE = {
    "brand_name": "FYF AI",
    "required_hashtags": ["#FYFAI", "#AIAutomation", "#SME"],
    "rules": ["Every post needs a clear CTA"],
}

CLEAN_DRAFT = (
    "Your page inbox does not have to eat your whole day. Our chatbot answers "
    "common questions the moment they arrive, and hands the serious chats to you. "
    "Message us to get started. #FYFAI #AIAutomation #SME"
)

# Deliberate violation: a get-rich promise, no CTA, no required hashtag.
VIOLATING_DRAFT = (
    "Our secret system gives you guaranteed income while you sleep. "
    "Everyone is doing it, do not miss out."
)


def test_clean_draft_passes():
    result = check_draft(CLEAN_DRAFT, "facebook", BRAND_VOICE)
    assert result.passed, result.summary()
    assert all(r.passed for r in result.results)


def test_violating_draft_fails_with_evidence():
    result = check_draft(VIOLATING_DRAFT, "facebook", BRAND_VOICE)
    assert not result.passed
    by_rule = {r.rule: r for r in result.results}
    assert not by_rule["banned_phrases"].passed
    assert "guaranteed income" in by_rule["banned_phrases"].evidence
    assert not by_rule["cta_present"].passed
    assert not by_rule["required_hashtag"].passed


def test_length_limit_fails_with_evidence():
    long_draft = ("x" * 2100) + " Message us to get started. #FYFAI"
    result = check_draft(long_draft, "facebook", BRAND_VOICE)
    by_rule = {r.rule: r for r in result.results}
    assert not by_rule["length_limit"].passed
    assert "2000" in by_rule["length_limit"].evidence


def test_depth_floor_stands_down_when_the_platform_cap_is_smaller():
    # Semantics updated by the checker-hardening PR: the PR #50
    # stand-down passed every short-platform draft unconditionally.
    # Now, when the cap is at or below the floor, depth is judged
    # against the cap itself (at least half the cap) -- a stub
    # fails even on X, a substantive short draft still passes.
    brand = {"min_caption_chars": "500", "brand_name": "FYF AI"}
    short = "FYF AI ဆိုတာ chatbot ဆောက်ပေးတဲ့ အဖွဲ့ပါ။ message us"
    x_result = check_draft(short, "x", brand)
    depth = [r for r in x_result.results if r.rule == "caption_depth"][0]
    assert not depth.passed
    assert "judged against the cap instead" in depth.evidence
    fb_result = check_draft(short, "facebook", brand)
    fb_depth = [r for r in fb_result.results if r.rule == "caption_depth"][0]
    assert not fb_depth.passed


def test_depth_on_x_passes_at_half_the_cap():
    brand = {"min_caption_chars": "500", "brand_name": "FYF AI"}
    half_cap = "FYF AI " + ("က" * 150) + " message us"  # > 140 = half of 280
    depth = [
        r for r in check_draft(half_cap, "x", brand).results
        if r.rule == "caption_depth"
    ][0]
    assert depth.passed
    assert "reaches at least half the cap" in depth.evidence


def test_depth_threads_cap_equal_to_floor_judged_against_cap():
    # The FYF shape: floor 500, Threads cap 500. Before this PR a
    # 300-char Threads draft failed depth outright even though it
    # fills most of what the platform allows.
    brand = {"min_caption_chars": "500", "brand_name": "FYF AI"}
    three_hundred = "FYF AI " + ("က" * 285) + " message us"  # ~300 chars
    depth = [
        r for r in check_draft(three_hundred, "threads", brand).results
        if r.rule == "caption_depth"
    ][0]
    assert depth.passed
    assert "judged against the cap instead" in depth.evidence
    stub = "FYF AI " + ("က" * 100) + " message us"  # ~115 chars < 250
    stub_depth = [
        r for r in check_draft(stub, "threads", brand).results
        if r.rule == "caption_depth"
    ][0]
    assert not stub_depth.passed
    assert "below half the cap" in stub_depth.evidence


def test_unexpected_script_catches_the_arabic_incident_word():
    # The exact 2026-11-05 incident string: an Arabic word inside
    # an otherwise Burmese Day-7 style draft.
    brand = {"brand_name": "FYF AI", "required_hashtags": ["#FYFAI"]}
    draft = (
        "ပို့ဆောင်မှုနဲ့ ပတ်သက်ပြီး شکایت ရှိရင် Messenger ကနေ message us "
        "ပို့ပါ။ #FYFAI"
    )
    result = check_draft(draft, "facebook", brand)
    rule = [r for r in result.results if r.rule == "unexpected_script"][0]
    assert not rule.passed
    assert "شکایت" in rule.evidence or "ش" in rule.evidence
    assert "Arabic" in rule.evidence
    assert not result.passed


def test_unexpected_script_allows_myanmar_latin_digits_emoji():
    brand = {"brand_name": "FYF AI", "required_hashtags": ["#FYFAI"]}
    draft = (
        "FYF AI က chatbot ဆောက်ပေးပါတယ် 123 → အဆင့် ၁ ✅ message us ပို့ပါ။ #FYFAI"
    )
    result = check_draft(draft, "facebook", brand)
    rule = [r for r in result.results if r.rule == "unexpected_script"][0]
    assert rule.passed, rule.evidence


def test_unexpected_script_brand_extension_allows_thai():
    thai = "ขอบคุณค่ะ message us ပို့ပါ။ #FYFAI"
    brand = {"brand_name": "FYF AI", "required_hashtags": ["#FYFAI"]}
    denied = check_draft(thai, "facebook", brand)
    rule = [r for r in denied.results if r.rule == "unexpected_script"][0]
    assert not rule.passed
    assert "Thai" in rule.evidence
    allowed_brand = dict(brand, allowed_scripts=["Thai"])
    allowed = check_draft(thai, "facebook", allowed_brand)
    rule = [r for r in allowed.results if r.rule == "unexpected_script"][0]
    assert rule.passed, rule.evidence


def test_length_evidence_names_protected_blockers():
    # The archived item-4 X shape in miniature: hook + brand
    # sentence + CTA/hashtag sentence are all protected and total
    # over the cap, so no trim can fit it and the evidence must
    # name the brand-name sentence as a blocker.
    brand = {
        "brand_name": "FYF AI",
        "required_hashtags": ["#FYFAI", "#AIAutomation", "#SME"],
        "cta_markers": ["message us"],
    }
    hook = "က" * 120 + "ပါ။"
    brand_sentence = "FYF AI " + ("ခ" * 90) + "ပါ။"
    cta_sentence = "message us " + ("ဂ" * 80) + "ပါ။ #FYFAI #AIAutomation #SME"
    draft = hook + " " + brand_sentence + " " + cta_sentence
    assert len(draft) > 280
    result = check_draft(draft, "x", brand)
    length = [r for r in result.results if r.rule == "length_limit"][0]
    assert not length.passed
    assert "cannot be trimmed to fit" in length.evidence
    assert "brand name" in length.evidence


def test_trim_protects_brand_name_sentence():
    from pageops.checker import trim_to_cap

    text = (
        "က" * 40 + "ပါ။ "
        + "ဂ" * 60 + "ပါ။ "
        + "FYF AI " + "ခ" * 110 + "ပါ။ "
        + "ဂ" * 60 + "ပါ။ "
        + "message us ပို့ပါ။ #FYFAI #AIAutomation #SME"
    )
    # Without token protection the brand sentence is the longest
    # droppable unit and is cut (the archived failure); with it,
    # the fillers go instead and both rules can pass.
    unprotected = trim_to_cap(text, 280, ["message us"])
    assert "FYF AI" not in unprotected
    protected = trim_to_cap(
        text, 280, ["message us"],
        protected_tokens=["FYF AI", "#FYFAI", "#AIAutomation", "#SME"],
    )
    assert "FYF AI" in protected
    assert len(protected) <= 280


def test_allowed_scripts_round_trips_through_brand_data(tmp_path):
    from pageops.pipeline import update_brand_voice
    from pageops.store import Store

    store = Store(tmp_path)
    update_brand_voice(store, "allowed_scripts", "Thai")
    voice = store.get_brand_voice()
    assert voice["allowed_scripts"] == ["Thai"]
    thai = "ขอบคุณค่ะ message us ပို့ပါ။ #FYFAI #AIAutomation #SME"
    result = check_draft(thai, "facebook", voice)
    rule = [r for r in result.results if r.rule == "unexpected_script"][0]
    assert rule.passed, rule.evidence
