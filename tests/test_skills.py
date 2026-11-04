"""Role skills: the fitted skill files load and reach the prompts,
and the checker's opt-in depth rules block stub captions."""

from pageops.checker import check_draft
from pageops.skills import SKILLS_ROOT, load_skills, with_skills


def test_skills_root_has_every_role():
    for role in ("strategist", "copywriter", "designer", "brand-checker", "analyst"):
        assert (SKILLS_ROOT / role).is_dir(), role
        assert load_skills(role), role


def test_copywriter_skills_carry_the_depth_standard():
    text = load_skills("copywriter")
    assert "information dump" in text
    assert "mini-audit" in text
    assert "Chopped fragments" in text


def test_designer_skills_carry_the_treatment():
    text = load_skills("designer")
    assert "type LAST" in text
    assert "GROWN out of the" in text
    assert "crop the subject away" in text


def test_unknown_role_is_empty_not_an_error():
    assert load_skills("no-such-role") == ""
    assert with_skills("base instruction", "no-such-role") == "base instruction"


def test_with_skills_appends_the_block():
    out = with_skills("base instruction", "copywriter")
    assert out.startswith("base instruction")
    assert "ROLE SKILLS for copywriter" in out


BRAND = {
    "brand_name": "FYF AI",
    "min_caption_chars": 300,
    "cta_markers": ["Audit"],
    "banned_phrases": [],
    "required_hashtags": [],
}


def test_depth_floor_blocks_a_stub_caption():
    result = check_draft("FYF AI. Send Audit.", "facebook", BRAND)
    rules = {r.rule: r.passed for r in result.results}
    assert rules["caption_depth"] is False
    assert result.passed is False


def test_depth_floor_passes_a_full_caption():
    text = ("FYF AI builds answering systems for page owners. " * 8) + "Send Audit in Messenger."
    result = check_draft(text, "facebook", BRAND)
    rules = {r.rule: r.passed for r in result.results}
    assert rules["caption_depth"] is True
    assert rules["brand_named"] is True


def test_brand_must_be_named_when_depth_is_on():
    text = ("We build answering systems for page owners. " * 9) + "Send Audit in Messenger."
    result = check_draft(text, "facebook", BRAND)
    rules = {r.rule: r.passed for r in result.results}
    assert rules["brand_named"] is False


def test_depth_rules_stay_off_without_the_brand_opt_in():
    result = check_draft("Short one. Audit.", "facebook", {"brand_name": "FYF AI"})
    rules = {r.rule for r in result.results}
    assert "caption_depth" not in rules
    assert "brand_named" not in rules


def test_wonder_client_defaults_to_low_reasoning_effort():
    # 2026-11-04: unset reasoning effort let Wonder spend the whole
    # token budget on hidden reasoning and return empty content.
    from pageops.model_client import MetaModelClient

    client = MetaModelClient(api_key="test-key")
    assert client.reasoning_effort == "low"


def test_brand_voice_carries_the_depth_floor_from_the_store(tmp_path):
    # The depth rules only protect a real run if the brand layer
    # actually delivers min_caption_chars to the checker.
    import csv

    from pageops.pipeline import update_brand_voice
    from pageops.store import Store

    store = Store(tmp_path)
    with open(tmp_path / "brand_voice.csv", "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["key", "value"])
        writer.writerow(["brand_name", "FYF AI"])
    update_brand_voice(store, "min_caption_chars", "500")
    voice = store.get_brand_voice()
    assert voice["min_caption_chars"] == "500"
    result = check_draft("FYF AI. Audit.", "facebook", voice)
    rules = {r.rule: r.passed for r in result.results}
    assert rules["caption_depth"] is False
