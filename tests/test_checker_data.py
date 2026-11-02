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



def test_seed_lists_match_checker_defaults():
    # The seed (fresh stores) and the fallback defaults (legacy
    # stores) are two copies of the same lists; pin them together
    # so they cannot drift into enforcing different rules.
    from pageops.checker import DEFAULT_BANNED_PHRASES, DEFAULT_CTA_MARKERS
    from pageops.store import BRAND_VOICE_SEED

    seed_banned = [p.strip() for p in BRAND_VOICE_SEED["banned_phrases"].split(";")]
    seed_cta = [m.strip() for m in BRAND_VOICE_SEED["cta_markers"].split(";")]
    assert seed_banned == DEFAULT_BANNED_PHRASES
    assert seed_cta == DEFAULT_CTA_MARKERS


def test_store_seed_parse_and_edit_drive_the_verdict(tmp_path):
    # The full store path: seed -> get_brand_voice -> checker, then
    # a data edit through the dataset changes the outcome.
    from pageops.store import Store

    store = Store(tmp_path)
    brand = store.get_brand_voice()
    violating = check_draft(
        "Secret guaranteed income. Message us. #FYFAI #AIAutomation #SME",
        "facebook",
        brand,
    )
    assert not _by_rule(violating)["banned_phrases"].passed

    rows = store.read_dataset("brand_voice")
    for row in rows:
        if row["key"] == "banned_phrases":
            row["value"] = "purple banana"
    store.write_dataset("brand_voice", rows)
    edited = store.get_brand_voice()
    now_clean = check_draft(
        "Secret guaranteed income. Message us. #FYFAI #AIAutomation #SME",
        "facebook",
        edited,
    )
    assert _by_rule(now_clean)["banned_phrases"].passed
    now_banned = check_draft(
        "Try the purple banana method. Message us. #FYFAI #AIAutomation #SME",
        "facebook",
        edited,
    )
    assert not _by_rule(now_banned)["banned_phrases"].passed


def test_legacy_store_without_rule_keys_keeps_default_protection(tmp_path):
    from pageops.store import Store

    store = Store(tmp_path)
    rows = [r for r in store.read_dataset("brand_voice") if r["key"] not in ("banned_phrases", "cta_markers")]
    store.write_dataset("brand_voice", rows)
    brand = store.get_brand_voice()
    assert "banned_phrases" not in brand  # checker falls back to defaults
    result = check_draft(
        "Secret guaranteed income. #FYFAI #AIAutomation #SME", "facebook", brand
    )
    assert not _by_rule(result)["banned_phrases"].passed
