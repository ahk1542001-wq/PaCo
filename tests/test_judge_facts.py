"""The judge works from the owner's approved brand facts.

Owner case (2026-11-10): the judge flagged the shop's real model
names as "invented" because it judged from its own priors. Approved
Brand Builder content is the ground truth for this business's offer:
it must reach the verdict call, and only approved content may.
"""

from __future__ import annotations

import json

from pageops.model_client import MetaModelClient, MockClient
from pageops.pipeline import _approved_brand_facts, draft_and_check
from pageops.store import Store

APPROVED = "Gemini Pro with Gemini 4 Argon, owner approved offer text"
UNAPPROVED = "UnapprovedSecretOffer should never reach the judge"


def _seed_brand_build(store):
    store.write_dataset(
        "brand_build",
        [
            {"id": "1", "level": "4", "status": "approved", "content": APPROVED},
            {"id": "2", "level": "3", "status": "draft", "content": UNAPPROVED},
        ],
    )


def test_approved_brand_facts_include_only_approved(tmp_path):
    store = Store(tmp_path / "data")
    _seed_brand_build(store)
    facts = _approved_brand_facts(store)
    assert "Gemini 4 Argon" in facts
    assert UNAPPROVED not in facts


class _CapturingJudge:
    def __init__(self):
        self.draft = None

    def verdict(self, draft, check_summary):
        self.draft = draft
        return {"verdict": "pass", "reasons": []}


def test_verdict_receives_brand_facts_and_brief(tmp_path):
    store = Store(tmp_path / "data")
    _seed_brand_build(store)
    row = store.add_plan_row(
        {"topic": "Gemini Pro launch", "platform": "facebook",
         "brief": "Launch the Gemini Pro offer", "status": "planned"}
    )
    judge = _CapturingJudge()
    draft_and_check(store, MockClient(), row, judge=judge)
    assert judge.draft is not None
    assert "Gemini 4 Argon" in judge.draft["brand_facts"]
    assert UNAPPROVED not in judge.draft["brand_facts"]
    assert judge.draft["brief"] == "Launch the Gemini Pro offer"


def test_meta_verdict_instruction_declares_brand_facts_ground_truth(tmp_path, monkeypatch):
    client = MetaModelClient(api_key="<redacted>", usage_log=tmp_path / "u.jsonl")
    seen = {}

    def capturing_chat(messages, model=None, **kwargs):
        seen["messages"] = messages
        return {"choices": [{"message": {"content": json.dumps({"verdict": "pass", "reasons": []})}}]}

    monkeypatch.setattr(client, "chat", capturing_chat)
    client.verdict({"text": "t", "brand_facts": APPROVED}, "summary")
    sent = " ".join(m["content"] for m in seen["messages"])
    assert "never flag them as invented" in sent
    assert "Gemini 4 Argon" in sent
