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
    brand = {"min_caption_chars": "500", "brand_name": "FYF AI"}
    short = "FYF AI ဆိုတာ chatbot ဆောက်ပေးတဲ့ အဖွဲ့ပါ။ message us"
    x_result = check_draft(short, "x", brand)
    depth = [r for r in x_result.results if r.rule == "caption_depth"][0]
    assert depth.passed
    assert "not applied on this platform" in depth.evidence
    fb_result = check_draft(short, "facebook", brand)
    fb_depth = [r for r in fb_result.results if r.rule == "caption_depth"][0]
    assert not fb_depth.passed
