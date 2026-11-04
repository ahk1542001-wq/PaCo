from pageops.store import Store


def test_brand_voice_seed(tmp_path):
    store = Store(tmp_path)
    voice = store.get_brand_voice()
    assert voice["brand_name"] == "FYF AI"
    assert any("chatbot" in s for s in voice["services"])
    assert any("$150" in s for s in voice["services"])
    assert "Myanmar" in voice["audience"]
    assert "#FYFAI" in voice["required_hashtags"]


def test_plan_round_trip(tmp_path):
    store = Store(tmp_path)
    store.add_plan_row(
        {
            "date": "2026-11-02",
            "platform": "facebook",
            "topic": "Inbox automation",
            "status": "brief_received",
            "brief": "Promote the chatbot service this week.",
        }
    )
    rows = store.read_dataset("plan")
    assert len(rows) == 1
    assert rows[0]["topic"] == "Inbox automation"
    assert rows[0]["status"] == "brief_received"
    assert rows[0]["brief"] == "Promote the chatbot service this week."
    assert rows[0]["id"] == "1"


def test_metrics_round_trip(tmp_path):
    store = Store(tmp_path)
    store.append_row(
        "metrics",
        {"date": "2026-11-03", "platform": "facebook", "post_id": "p1", "reach": "1200"},
    )
    rows = store.read_dataset("metrics")
    assert rows[0]["reach"] == "1200"


def test_brand_voice_seed_speaks_burmese_with_a_depth_floor(tmp_path):
    # FYF's audience is Burmese-first and its captions carry the
    # depth standard: both live in the seed brand data, so a fresh
    # store starts with them (2026-11-04 skills run drafted in
    # English because the seed never named the language).
    store = Store(tmp_path)
    voice = store.get_brand_voice()
    assert "Burmese" in voice["tone"]
    assert any("Burmese" in r for r in voice["rules"])
    # The depth floor and the Audit CTA marker are brand DATA,
    # set on the FYF stores themselves, never forced by the seed:
    # the seed stays usable by short-form brands and the mock
    # harness alike.
    assert "min_caption_chars" not in voice
