"""Length repair (owner's fix order, 2026-11-04): a draft whose
only failing rule is the platform length cap used to stay held
at `checked` whenever its one revision also came back long (a
2,457-char draft against the 2,000 Facebook cap). Now the
pipeline runs one targeted shortening pass, humanises the
result, and re-checks. Only a passing repair is adopted; any
other failure pattern never triggers the repair at all.
"""
from pageops.model_client import MockClient
from pageops.pipeline import draft_and_check
from pageops.store import Store

LONG = ("ဒီစာသားက အရမ်းရှည်ပါတယ်။ " * 120) + " message us #FYFAI #AIAutomation #SME"
SHORT = "တိုတိုလေး ပြန်ရေးထားတဲ့ စာသားပါ။ message us #FYFAI #AIAutomation #SME"


def _row(store):
    return store.add_plan_row(
        {"platform": "facebook", "topic": "Length topic", "status": "planned"}
    )


class LongClient(MockClient):
    """Drafts and revisions both come back over the cap; the
    shortening pass is the only way under it."""

    def __init__(self, shortened=SHORT):
        self.shorten_calls = 0
        self._shortened = shortened

    def generate_draft(self, plan_item, brand_voice):
        return {"platform": "facebook", "text": LONG, "hashtags": []}

    def shorten(self, text, max_chars, brand_voice):
        self.shorten_calls += 1
        return self._shortened


def test_length_only_failure_is_repaired(tmp_path):
    store = Store(tmp_path)
    client = LongClient()
    updated = draft_and_check(store, client, _row(store))
    assert client.shorten_calls == 1
    assert updated["status"] == "awaiting_approval"
    assert len(updated["draft"]) <= 2000
    assert "[LENGTH REPAIR]" in updated["check_status"]
    assert "shortened" in updated["check_status"]


UNBREAKABLE = ("word " * 500) + "message us #FYFAI #AIAutomation #SME"


class UnbreakableClient(MockClient):
    """One giant unit with no sentence boundary: neither the
    model's pass (returns it unchanged) nor the sentence trim
    can cut it, so the gate must keep holding it."""

    def generate_draft(self, plan_item, brand_voice):
        return {"platform": "facebook", "text": UNBREAKABLE, "hashtags": []}

    def shorten(self, text, max_chars, brand_voice):
        return text


def test_repair_that_still_fails_stays_checked(tmp_path):
    store = Store(tmp_path)
    updated = draft_and_check(store, UnbreakableClient(), _row(store))
    assert updated["status"] == "checked"
    assert "[LENGTH REPAIR]" in updated["check_status"]


class BannedClient(MockClient):
    def __init__(self):
        self.shorten_calls = 0

    def generate_draft(self, plan_item, brand_voice):
        return {
            "platform": "facebook",
            "text": "Short text with guaranteed income. message us #FYFAI #AIAutomation #SME",
            "hashtags": [],
        }

    def shorten(self, text, max_chars, brand_voice):
        self.shorten_calls += 1
        return text


def test_other_failures_never_trigger_the_repair(tmp_path):
    store = Store(tmp_path)
    client = BannedClient()
    updated = draft_and_check(store, client, _row(store))
    assert client.shorten_calls == 0
    assert updated["status"] == "checked"


def test_mock_shorten_trims_inside_the_budget():
    client = MockClient()
    out = client.shorten(LONG, 2000, {})
    assert 0 < len(out) <= 2000
    assert client.shorten("short", 2000, {}) == "short"


class StubbornClient(MockClient):
    """Each shortening pass only trims a little (the model
    under-counts Burmese codepoints); the repair must measure
    and repeat until the text is genuinely under the cap."""

    def __init__(self):
        self.shorten_calls = 0

    def generate_draft(self, plan_item, brand_voice):
        return {"platform": "facebook", "text": LONG, "hashtags": []}

    def shorten(self, text, max_chars, brand_voice):
        self.shorten_calls += 1
        keep = int(len(text) * 0.7)
        return text[:keep] + " message us #FYFAI #AIAutomation #SME"


def test_repair_repeats_until_under_the_cap(tmp_path):
    store = Store(tmp_path)
    client = StubbornClient()
    updated = draft_and_check(store, client, _row(store))
    assert client.shorten_calls >= 2
    assert updated["status"] == "awaiting_approval"
    assert len(updated["draft"]) <= 2000
    assert "pass(es)" in updated["check_status"]


def test_sentence_trim_rescues_a_non_converging_model(tmp_path):
    """Wonder's live behaviour (2026-11-04): each shorten pass
    trims only a few percent, so the model loop alone never
    converges; the deterministic sentence trim finishes the job."""
    store = Store(tmp_path)
    client = LongClient(shortened=LONG)
    updated = draft_and_check(store, client, _row(store))
    assert updated["status"] == "awaiting_approval"
    assert len(updated["draft"]) <= 2000
    assert "sentence trim" in updated["check_status"]


def test_trim_to_cap_keeps_hook_cta_and_hashtags():
    from pageops.checker import trim_to_cap

    text = ("Hook sentence stays. " + "A very long middle sentence that rambles on and on. " * 8
            + "message us for the free audit #FYFAI #AIAutomation")
    out = trim_to_cap(text, 200, ["message us"])
    assert len(out) <= 200
    assert out.startswith("Hook sentence stays.")
    assert "message us" in out and "#FYFAI" in out
    assert trim_to_cap("short", 200, []) == "short"
