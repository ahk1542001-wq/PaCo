import json

from pageops.checker import check_draft
from pageops.model_client import MetaModelClient, MockClient
from pageops.store import Store


def test_mock_plan_structure():
    client = MockClient()
    plan = client.generate_plan("Promote the chatbot service.", {"brand_name": "FYF AI"})
    assert len(plan["posts"]) >= 3
    for post in plan["posts"]:
        assert {"day", "platform", "topic", "angle", "format"} <= set(post)


def test_mock_draft_passes_brand_checker(tmp_path):
    store = Store(tmp_path)
    voice = store.get_brand_voice()
    client = MockClient()
    plan = client.generate_plan("Brief", voice)
    draft = client.generate_draft(plan["posts"][0], voice)
    result = check_draft(draft["text"], draft["platform"], voice)
    assert result.passed, result.summary()
    verdict = client.verdict(draft, result.summary())
    assert verdict["verdict"] == "pass"


def test_meta_client_requires_key(monkeypatch):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    client = MetaModelClient(api_key=None)
    try:
        client.chat([{"role": "user", "content": "hi"}])
    except RuntimeError as exc:
        assert "MODEL_API_KEY" in str(exc)
    else:
        raise AssertionError("chat() should refuse to run without a key")


def test_main_model_defaults_to_wonder_and_is_switchable(monkeypatch):
    monkeypatch.delenv("PAGEOPS_MAIN_MODEL", raising=False)
    assert MetaModelClient(api_key="k").main_model == "muse-wonder-1.0"
    monkeypatch.setenv("PAGEOPS_MAIN_MODEL", "muse-spark-1.3")
    assert MetaModelClient(api_key="k").main_model == "muse-spark-1.3"


def test_usage_logger_records_tokens(tmp_path):
    log = tmp_path / "usage_log.jsonl"
    client = MetaModelClient(api_key="test-key", usage_log=log)
    client.usage.record("muse-spark-1.3", {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15})
    lines = log.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["model"] == "muse-spark-1.3"
    assert entry["usage"]["total_tokens"] == 15


def test_baseten_client_configuration():
    from pageops.model_client import BASETEN_BASE_URL, MODEL_SPARK_OPEN, get_baseten_client

    client = get_baseten_client(api_key="test-key")
    assert client is not None
    assert client.base_url == BASETEN_BASE_URL
    assert client.main_model == MODEL_SPARK_OPEN
    assert client.verdict_model == MODEL_SPARK_OPEN


def test_baseten_client_absent_without_key(monkeypatch):
    from pageops.model_client import get_baseten_client

    monkeypatch.delenv("BASETEN_API_KEY", raising=False)
    assert get_baseten_client() is None


def test_baseten_chat_posts_to_baseten_url(monkeypatch):
    import httpx

    from pageops.model_client import MODEL_SPARK_OPEN, get_baseten_client

    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {"platform": "facebook", "text": "Hi #FYFAI", "hashtags": ["#FYFAI"]}
                            )
                        }
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            }

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        return FakeResponse()

    monkeypatch.setattr(httpx, "post", fake_post)
    client = get_baseten_client(api_key="test-key")
    draft = client.generate_draft({"topic": "T", "platform": "facebook"}, {"brand_name": "FYF AI"})
    assert captured["url"] == "https://inference.baseten.co/v1/chat/completions"
    assert captured["json"]["model"] == MODEL_SPARK_OPEN
    assert draft["text"] == "Hi #FYFAI"


def test_draft_instruction_states_the_length_window(monkeypatch):
    # The drafter must know the window before writing: the brand's
    # depth floor and the platform cap (2026-11-04 skills run).
    from pageops.model_client import MetaModelClient

    client = MetaModelClient(api_key="test-key")
    captured = {}

    def fake_structured(instruction, payload, model):
        captured["instruction"] = instruction
        return {"platform": "facebook", "text": "x", "hashtags": []}

    monkeypatch.setattr(client, "_structured", fake_structured)
    client.generate_draft(
        {"platform": "Facebook", "format": "poster"},
        {"brand_name": "FYF AI", "min_caption_chars": "500"},
    )
    assert "at least 500 characters" in captured["instruction"]
    assert "at most 2000 characters" in captured["instruction"]

    client.generate_draft({"platform": "Facebook", "format": "poster"}, {})
    assert "at least" not in captured["instruction"]
    assert "at most 2000 characters" in captured["instruction"]
