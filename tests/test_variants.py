"""Cross-platform variants (owner's rule: everything done by
hand must live in the product, 2026-11-04). The manual FYF
adaptation pass (a Facebook master hand-rewritten for Instagram,
TikTok, Threads and X, counted against each cap by eye) becomes
a product stage: the Copywriter adapts, the humaniser passes,
the checker verifies per platform, the owner's toggles decide
which platforms are owed a variant at all.
"""
from pageops.checker import PLATFORM_LIMITS
from pageops.model_client import MockClient
from pageops.pipeline import update_brand_voice
from pageops.store import Store
from pageops.variants import generate_variants, target_platforms

MASTER = (
    "FYF AI ဆိုတာ page ပိုင်ရှင်တွေအတွက် chatbot ဆောက်ပေးတဲ့ အဖွဲ့ပါ။ "
    "message us လို့ ပို့ပြီး free mini-audit ရယူပါ။ "
    "#FYFAI #AIAutomation #SME"
)


def _store(tmp_path, draft=MASTER):
    store = Store(tmp_path)
    store.add_plan_row(
        {"platform": "facebook", "topic": "T", "format": "photo",
         "draft": draft, "status": "scheduled"}
    )
    return store


def test_variants_for_every_other_platform_all_checked(tmp_path):
    store = _store(tmp_path)
    result = generate_variants(store, MockClient())
    assert result["created"] == 4
    assert result["failures"] == []
    rows = store.read_dataset("variants")
    assert {r["platform"] for r in rows} == {"instagram", "tiktok", "threads", "x"}
    assert all(r["check_status"] == "pass" for r in rows)


def test_rerun_updates_in_place(tmp_path):
    store = _store(tmp_path)
    generate_variants(store, MockClient())
    result = generate_variants(store, MockClient())
    assert result["updated"] == 4
    assert len(store.read_dataset("variants")) == 4


def test_toggled_off_platform_gets_no_variant(tmp_path):
    store = _store(tmp_path)
    update_brand_voice(store, "postiz_integration_tiktok", "int-tt")
    update_brand_voice(store, "postiz_enabled_tiktok", "off")
    update_brand_voice(store, "postiz_integration_instagram", "int-ig")
    item = store.read_dataset("plan")[0]
    assert target_platforms(store, item) == ["instagram"]
    result = generate_variants(store, MockClient())
    assert result["created"] == 1
    assert store.read_dataset("variants")[0]["platform"] == "instagram"


def test_long_master_is_trimmed_to_the_x_cap(tmp_path):
    long_master = " ".join(
        f"FYF AI အကြောင်း အပိုင်း {i} မှာ chatbot ဆိုတာ ရှင်းပြထားပါတယ်။" for i in range(30)
    ) + " message us လို့ ပို့ပါ။"
    store = _store(tmp_path, draft=long_master)
    result = generate_variants(store, MockClient())
    x_row = [r for r in store.read_dataset("variants") if r["platform"] == "x"][0]
    assert len(x_row["text"]) <= PLATFORM_LIMITS["x"]


def test_unapproved_items_are_skipped(tmp_path):
    store = Store(tmp_path)
    store.add_plan_row(
        {"platform": "facebook", "topic": "T", "format": "photo",
         "draft": MASTER, "status": "drafted"}
    )
    result = generate_variants(store, MockClient())
    assert result["created"] == 0


class SloppyClient(MockClient):
    """Adapt returns an over-cap text with no hashtags: length must
    still be trimmed, and the remaining failure must name the
    hashtag rule, not the length."""

    def adapt_variant(self, text, brand_voice, platform):
        return "FYF AI ဆိုတာ chatbot ဆောက်ပေးတဲ့ အဖွဲ့ပါ။ " * 30 + "message us"


def test_length_is_trimmed_even_with_other_failures(tmp_path):
    store = _store(tmp_path)
    result = generate_variants(store, SloppyClient())
    x_row = [r for r in store.read_dataset("variants") if r["platform"] == "x"][0]
    assert len(x_row["text"]) <= PLATFORM_LIMITS["x"]
    x_failures = [f for f in result["failures"] if f[1] == "x"]
    assert x_failures and "required_hashtag" in x_failures[0][2]
    assert "length_limit" not in x_failures[0][2]
