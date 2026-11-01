"""Dataset-driven checker (M18 fix, PR #8).

The brand rules live in the brand DATA, not in code constants:
editing the brand's banned phrases, CTA markers or required
hashtags changes the verdicts. Code keeps only platform facts
(length caps) and fallback defaults for stores that predate the
data keys. Required hashtags means ALL of them.
"""
from pageops.checker import check_draft

BASE = {"brand_name": "Test", "required_hashtags": ["#FYFAI", "#AIAutomation", "#SME"]}

DRAFT = "A helpful post for page owners. Message us to get started. #FYFAI #AIAutomation #SME"


def _by_rule(result):
    return {r.rule: r for r in result.results}


def test_brand_data_drives_the_banned_rule():
    brand = dict(BASE, banned_phrases=["purple banana"], cta_markers=["message us"])
    result = check_draft("Try our purple banana method. Message us.", "facebook", brand)
    assert not _by_rule(result)["banned_phrases"].passed
    clean = check_draft(DRAFT, "facebook", brand)
    assert _by_rule(clean)["banned_phrases"].passed


def test_brand_data_drives_the_cta_rule():
    brand = dict(BASE, banned_phrases=[], cta_markers=["smoke signal us"])
    result = check_draft("A post. Smoke signal us today. #FYFAI #AIAutomation #SME", "facebook", brand)
    assert _by_rule(result)["cta_present"].passed
    standard = check_draft(DRAFT, "facebook", brand)
    assert not _by_rule(standard)["cta_present"].passed


def test_all_required_hashtags_must_appear():
    partial = check_draft("A post. Message us. #FYFAI", "facebook", BASE)
    rule = _by_rule(partial)["required_hashtag"]
    assert not rule.passed
    assert "#AIAutomation" in rule.evidence and "#SME" in rule.evidence
    full = check_draft(DRAFT, "facebook", BASE)
    assert _by_rule(full)["required_hashtag"].passed


def test_defaults_apply_when_brand_data_lacks_the_keys():
    result = check_draft(
        "Secret guaranteed income for everyone. #FYFAI #AIAutomation #SME",
        "facebook",
        BASE,
    )
    rules = _by_rule(result)
    assert not rules["banned_phrases"].passed  # built-in defaults still protect
    assert not rules["cta_present"].passed
