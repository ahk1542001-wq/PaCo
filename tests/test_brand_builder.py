"""Brand Builder (owner's rule: everything done by hand must
live in the product, 2026-11-04). The five FYF brand levels
become a gated product workflow: one level at a time, drafting
locked until the level below stands approved, approval writing
straight into the brand data. Identity is derived from the
brand data itself, never drafted as prose (the owner's blunt
correction that a staircase is walked one step at a time).
"""
import pytest

from pageops.brand_builder import approve_level, draft_level, level_statuses
from pageops.model_client import MockClient
from pageops.pipeline import update_brand_voice
from pageops.store import Store

BRIEF = "A page selling AI automation services to Myanmar SME owners."


def _identity_done(tmp_path):
    store = Store(tmp_path)
    update_brand_voice(store, "brand_colors", "Deep Forest #0B3D2E")
    update_brand_voice(store, "brand_fonts", "Padauk")
    update_brand_voice(store, "logo_usage", "Opening Path emblem")
    return store


def test_identity_is_derived_not_drafted(tmp_path):
    # The seeded FYF brand already carries complete identity data,
    # so its level 1 stands approved; blank one key and it does not.
    store = Store(tmp_path)
    update_brand_voice(store, "logo_usage", "")
    assert level_statuses(store)[1] == "empty"
    store = _identity_done(tmp_path)
    assert level_statuses(store)[1] == "approved"
    with pytest.raises(ValueError):
        draft_level(store, 1, MockClient(), BRIEF)


def test_gate_locks_out_of_order_levels(tmp_path):
    store = _identity_done(tmp_path)
    with pytest.raises(ValueError) as exc:
        draft_level(store, 3, MockClient(), BRIEF)
    assert "locked" in str(exc.value)


def test_draft_then_approve_writes_brand_data(tmp_path):
    store = _identity_done(tmp_path)
    draft_level(store, 2, MockClient(), BRIEF)
    assert level_statuses(store)[2] == "drafted"
    approve_level(store, 2)
    assert level_statuses(store)[2] == "approved"
    assert "Audience for" in store.get_brand_voice()["audience"]


def test_offer_lines_become_the_services_list(tmp_path):
    store = _identity_done(tmp_path)
    draft_level(store, 2, MockClient(), BRIEF)
    approve_level(store, 2)
    draft_level(store, 3, MockClient(), BRIEF)
    approve_level(store, 3)

    class MenuClient(MockClient):
        def draft_brand_level(self, level_name, brief, brand_voice):
            if level_name == "Offer":
                return "Chatbot builds\nMonthly care plans"
            return super().draft_brand_level(level_name, brief, brand_voice)

    draft_level(store, 4, MenuClient(), BRIEF)
    approve_level(store, 4)
    assert store.get_brand_voice()["services"] == [
        "Chatbot builds",
        "Monthly care plans",
    ]


def test_approve_without_a_draft_refuses(tmp_path):
    store = _identity_done(tmp_path)
    with pytest.raises(ValueError):
        approve_level(store, 2)
