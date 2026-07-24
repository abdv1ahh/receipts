"""Offline tests for the unified LLM transport (Milestone 8): provider dispatch, the OpenAI-compatible
request/response shape (so a free GitHub Models / Groq / OpenRouter key just works), the Gemini shape,
and the shared quota circuit-breaker. Fully mocked — no network."""
import pytest

from tradeos import llm


class _Resp:
    def __init__(self, status, data):
        self.status_code, self._data, self.text = status, data, ""

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _Client:
    def __init__(self, resp, capture):
        self._resp, self._capture = resp, capture

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def post(self, url, **kw):
        self._capture.update({"url": url, **kw})
        return self._resp


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    llm._COOLDOWN_UNTIL = 0.0                      # module global must not leak between tests
    monkeypatch.setattr(llm.time, "sleep", lambda *_: None)   # never actually sleep in a unit test
    yield
    llm._COOLDOWN_UNTIL = 0.0


def _mock(monkeypatch, resp):
    cap: dict = {}
    monkeypatch.setattr(llm.httpx, "Client", lambda *a, **k: _Client(resp, cap))
    return cap


def test_provider_and_model_id(monkeypatch):
    monkeypatch.setenv("EXPLAIN_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_MODEL", "openai/gpt-4o-mini")
    assert llm.provider() == "openai"
    assert llm.model_id() == "openai/gpt-4o-mini"
    monkeypatch.setenv("GEMINI_MODEL", "gemini-flash-latest")
    assert llm.model_id("gemini") == "gemini-flash-latest"
    assert llm.model_id("template") == "template"


def test_template_and_missing_key_return_none(monkeypatch):
    monkeypatch.setenv("EXPLAIN_PROVIDER", "template")
    assert llm.text("hi") is None
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert llm.text("hi", provider="openai") is None      # no key -> None (caller falls back)


def test_openai_text_request_and_parse(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.groq.com/openai/v1")
    monkeypatch.setenv("OPENAI_MODEL", "llama-3.3-70b-versatile")
    cap = _mock(monkeypatch, _Resp(200, {"choices": [{"message": {"content": "hello world"}}]}))
    out = llm.text("say hi", provider="openai")
    assert out == "hello world"
    assert cap["url"] == "https://api.groq.com/openai/v1/chat/completions"
    assert cap["json"]["model"] == "llama-3.3-70b-versatile"
    assert cap["json"]["messages"][0] == {"role": "user", "content": "say hi"}
    assert cap["headers"]["Authorization"] == "Bearer k"


def test_gemini_text_parse(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    _mock(monkeypatch, _Resp(200, {"candidates": [{"content": {"parts": [{"text": "gem out"}]}}]}))
    assert llm.text("x", provider="gemini") == "gem out"


def test_circuit_breaker_opens_on_persistent_429(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    _mock(monkeypatch, _Resp(429, {}))
    assert llm.text("x", provider="openai") is None            # 429 -> None + trips the breaker
    # breaker now open: even a would-be-200 is skipped instantly (no re-paying the retry cost)
    _mock(monkeypatch, _Resp(200, {"choices": [{"message": {"content": "nope"}}]}))
    assert llm.text("x", provider="openai") is None


def test_openai_vision_builds_image_message(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://models.github.ai/inference")
    cap = _mock(monkeypatch, _Resp(200, {"choices": [{"message": {"content": '{"is_chart": true}'}}]}))
    out = llm.vision("read this chart", b"IMGBYTES", "image/png", provider="openai", json_mode=True)
    assert out == '{"is_chart": true}'
    content = cap["json"]["messages"][0]["content"]
    assert content[0] == {"type": "text", "text": "read this chart"}
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert cap["json"]["response_format"] == {"type": "json_object"}
