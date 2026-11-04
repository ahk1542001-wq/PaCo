"""Voice samples (owner's requirement, 2026-11-04): a client can
send paragraphs they wrote themselves; the samples live in the
brand data, the brand panel can edit them, and every writer
(the Copywriter's drafts and the humanising pass) is told to
match that tone of voice. Brands without samples are untouched.
The same change pins the sentence rule for every platform:
complete, connected sentences, never blunt chopped fragments.
"""
import json

from pageops.model_client import MetaModelClient, voice_instruction
from pageops.pipeline import update_brand_voice
from pageops.skills import load_skills
from pageops.store import Store

SAMPLES = "ကျွန်တော်တို့ ဆိုင်က မနက်တိုင်း ၈ နာရီ ဖွင့်ပါတယ်။ မေးချင်တာ ရှိရင် စာပို့ထားပါနော်။"


def test_voice_samples_round_trip_through_brand_data(tmp_path):
    store = Store(tmp_path)
    assert "voice_samples" not in store.get_brand_voice()
    update_brand_voice(store, "voice_samples", SAMPLES)
    assert store.get_brand_voice()["voice_samples"] == SAMPLES


def test_voice_instruction_only_when_samples_exist():
    assert voice_instruction({}) == ""
    assert voice_instruction({"voice_samples": "  "}) == ""
    block = voice_instruction({"voice_samples": SAMPLES})
    assert "tone of voice" in block
    assert SAMPLES in block


class CapturingClient(MetaModelClient):
    def __init__(self):
        super().__init__(api_key="test")
        self.seen = []

    def chat(self, messages, model=None, **kwargs):
        self.seen.append(messages)
        return {"choices": [{"message": {"content": json.dumps(
            {"platform": "facebook", "text": "draft", "hashtags": []})}}]}


def test_draft_prompt_carries_the_samples():
    client = CapturingClient()
    client.generate_draft(
        {"platform": "facebook", "format": "post", "topic": "T"},
        {"voice_samples": SAMPLES},
    )
    user_text = client.seen[0][1]["content"]
    assert SAMPLES in user_text


def test_draft_prompt_without_samples_stays_clean():
    client = CapturingClient()
    client.generate_draft(
        {"platform": "facebook", "format": "post", "topic": "T"}, {}
    )
    assert "Voice samples" not in client.seen[0][1]["content"]


def test_humanize_prompt_carries_the_samples():
    client = CapturingClient()
    client.chat = lambda messages, model=None, **kw: (
        client.seen.append(messages),
        {"choices": [{"message": {"content": "rewritten"}}]},
    )[1]
    out = client.humanize("some text", {"voice_samples": SAMPLES})
    assert out == "rewritten"
    assert SAMPLES in client.seen[0][0]["content"]


def test_copywriter_skills_carry_both_rules():
    text = load_skills("copywriter")
    assert "voice samples" in text
    assert "complete,\nconnected sentences" in text or "complete, connected sentences" in text
    assert "blunt fragments" in text
