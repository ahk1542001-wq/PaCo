"""Visibility audit (owner's rule: everything done by hand must
live in the product, 2026-11-04). The manual FYF page audit of
2026-11-04 (scenario openings, no Q&A shape, shifting keyword
spine, no page descriptor) becomes a deterministic product
stage: checks with quoted counts, a fix on every warning, a
figure-checked model read, and a recorded summary the
Strategist reads when planning.
"""
from pageops.context import latest_analyst_summary, load_last_visibility
from pageops.model_client import MockClient
from pageops.pipeline import run_visibility_audit, update_brand_voice
from pageops.store import Store
from pageops.visibility import build_visibility_audit

GOOD = (
    "FYF AI ဆိုတာ ဘာလဲ သိချင်ပါသလား။ FYF AI ဆိုတာ SME page တွေအတွက် "
    "chatbot နဲ့ automation တည်ဆောက်ပေးတဲ့ အဖွဲ့ပါ။ အရင် inbox ကို ကြည့်ပါ၊ "
    "ပြီးရင် message us လို့ ပို့ပါ။ #FYFAI"
)
WEAK = "မနေ့ညက ဆိုင်မှာ အရမ်း အလုပ်ရှုပ်ခဲ့တယ်။ ပစ္စည်းတွေ ထုပ်ရတာ လက်မလည်ဘူး။"


def _store(tmp_path):
    store = Store(tmp_path)
    update_brand_voice(store, "services", "chatbot; automation")
    update_brand_voice(store, "audience", "Myanmar SME page owners")
    return store


def _row(store, draft):
    return store.add_plan_row(
        {"platform": "facebook", "topic": "T", "draft": draft, "status": "scheduled"}
    )


def test_audit_scores_each_check_with_evidence(tmp_path):
    store = _store(tmp_path)
    _row(store, GOOD)
    _row(store, WEAK)
    audit = build_visibility_audit(store)
    by_check = {f["check"]: f for f in audit["findings"]}
    assert by_check["seo_opening_terms"]["status"] == "warn"  # 1/2 = 50%
    assert by_check["aeo_question_answer"]["status"] == "warn"
    assert by_check["geo_brand_entity"]["status"] == "warn"
    assert by_check["cta_funnel_start"]["status"] == "warn"
    assert by_check["page_descriptor"]["status"] == "pass"
    assert "1/2" in by_check["seo_opening_terms"]["evidence"]
    assert "[WARN] seo_opening_terms" in audit["text"]
    assert "Fix:" in audit["text"]


def test_all_good_content_passes(tmp_path):
    store = _store(tmp_path)
    _row(store, GOOD)
    audit = build_visibility_audit(store, client=MockClient())
    assert all(f["status"] == "pass" for f in audit["findings"])
    assert "Read:" in audit["text"]


class RogueClient(MockClient):
    def visibility_read(self, findings_text, brand_voice):
        return "A superb 999 percent of posts are perfectly visible."


def test_rogue_read_is_dropped_by_the_figure_guard(tmp_path):
    store = _store(tmp_path)
    _row(store, GOOD)
    audit = build_visibility_audit(store, client=RogueClient())
    assert "[READ DROPPED]" in audit["text"]
    assert "999" not in audit["text"].split("[READ DROPPED]")[0]


def test_stage_records_audit_and_feeds_the_strategist(tmp_path):
    store = _store(tmp_path)
    _row(store, WEAK)
    audit = run_visibility_audit(store, client=MockClient())
    assert load_last_visibility(store) == audit["text"]
    summary = latest_analyst_summary(store)
    assert "Visibility audit:" in summary
    assert "warned:" in summary


def test_empty_store_audits_cleanly(tmp_path):
    store = _store(tmp_path)
    audit = build_visibility_audit(store)
    assert "no drafted content" in audit["text"]
    assert {f["check"] for f in audit["findings"]} == {"page_descriptor"}


def test_spine_counts_key_term_representation(tmp_path):
    store = _store(tmp_path)
    update_brand_voice(store, "services", "chatbot; Monthly Care")
    _row(store, GOOD)  # carries "chatbot", never "Monthly" or "Care"
    audit = build_visibility_audit(store)
    spine = {f["check"]: f for f in audit["findings"]}["geo_keyword_spine"]
    assert spine["status"] == "warn"
    assert "1/2" in spine["evidence"]
    assert "Monthly Care" in spine["evidence"]
