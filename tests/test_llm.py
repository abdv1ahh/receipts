"""Offline tests for the unified LLM transport: the provider chain and its failover, the
OpenAI-compatible request/response shape (so a free Groq / OpenRouter key just works), the Gemini
shape, per-provider circuit breakers, and the plain-language reason a caller shows the user when
there is no model output. Fully mocked — no network."""
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
    """One mock client. `resp` may be a single response or a per-host mapping."""

    def __init__(self, resp, capture):
        self._resp, self._capture = resp, capture

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def post(self, url, **kw):
        self._capture.update({"url": url, **kw})
        if isinstance(self._resp, dict):
            for host, r in self._resp.items():
                if host in url:
                    return r
            raise AssertionError(f"no mock response for {url}")
        return self._resp


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    llm.reset_cooldowns()                                     # breakers must not leak between tests
    monkeypatch.setattr(llm.time, "sleep", lambda *_: None)   # never actually sleep in a unit test
    yield
    llm.reset_cooldowns()


def _mock(monkeypatch, resp):
    cap: dict = {}
    monkeypatch.setattr(llm.httpx, "Client", lambda *a, **k: _Client(resp, cap))
    return cap


def test_chain_parses_a_comma_list(monkeypatch):
    monkeypatch.setenv("EXPLAIN_PROVIDER", "gemini,openai")
    assert llm.chain() == ["gemini", "openai"]
    assert llm.provider() == "gemini"
    monkeypatch.setenv("EXPLAIN_PROVIDER", " gemini ")
    assert llm.chain() == ["gemini"]
    monkeypatch.setenv("EXPLAIN_PROVIDER", "")
    assert llm.chain() == ["template"]
    assert llm.chain("template") == ["template"]              # caller override beats the env


def test_wants_model_accepts_the_chain_form_not_just_a_single_name(monkeypatch):
    """The bug this exists to prevent, found in Phase 6 and live in production at the time.

    Four callers that own their own prompt — the signal explainer, the trade analyst, the journal
    coach and the assistant — each gated their model call on `provider in ("gemini", "openai")`.
    That is correct for one name and silently False for `gemini,openai`, which is the documented
    chain form and the value actually configured. All four served their deterministic template
    while reporting the model had been tried: not a crash, not a visible failure, just every AI
    surface quietly switched off. The gate now parses the chain exactly as the transport does."""
    monkeypatch.setenv("EXPLAIN_PROVIDER", "gemini,openai")
    assert llm.wants_model() is True
    assert llm.wants_model("gemini,openai") is True
    assert llm.wants_model("gemini") is True
    assert llm.wants_model("template") is False
    assert llm.wants_model("template,gemini") is True         # any real link means try the chain
    assert llm.wants_model("nonsense") is False


def test_no_caller_gates_a_model_call_on_a_bare_provider_name():
    """A static check, because the failure is silent and reappears by copy-paste. Any call site
    testing membership against a literal provider tuple is the bug above, rewritten."""
    import pathlib
    import re

    root = pathlib.Path(llm.__file__).parent
    bad = []
    for path in root.rglob("*.py"):
        for n, line in enumerate(path.read_text().splitlines(), 1):
            # Only real branch code — the docstrings above quote the broken pattern on purpose.
            if re.match(r"\s*(el)?if\s+.*provider\s+in\s+\(\s*[\"']gemini[\"']", line):
                bad.append(f"{path.name}:{n}")
    assert not bad, f"gate the model call on llm.wants_model() instead: {bad}"


def test_model_id_per_role(monkeypatch):
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    monkeypatch.delenv("GEMINI_MODEL_FAST", raising=False)
    assert llm.model_id("gemini") == "gemini-flash-latest"                 # DEEP default
    assert llm.model_id("gemini", llm.FAST) == "gemini-flash-lite-latest"  # FAST default
    monkeypatch.setenv("GEMINI_MODEL", "custom-deep")
    assert llm.model_id("gemini") == "custom-deep"
    assert llm.model_id("gemini", llm.FAST) == "custom-deep"               # FAST falls back to DEEP
    monkeypatch.setenv("GEMINI_MODEL_FAST", "custom-fast")
    assert llm.model_id("gemini", llm.FAST) == "custom-fast"
    assert llm.model_id("template") == "template"


def test_template_and_missing_key_return_none_with_a_reason(monkeypatch):
    monkeypatch.setenv("EXPLAIN_PROVIDER", "template")
    out, why = llm.complete("hi")
    assert out is None and "switched off" in why
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    out, why = llm.complete("hi", provider="openai")
    assert out is None and why == "openai has no API key set"


def test_openai_text_request_and_parse(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.groq.com/openai/v1")
    monkeypatch.setenv("OPENAI_MODEL", "llama-3.3-70b-versatile")
    cap = _mock(monkeypatch, _Resp(200, {"choices": [{"message": {"content": "hello world"}}]}))
    assert llm.text("say hi", provider="openai") == "hello world"
    assert cap["url"] == "https://api.groq.com/openai/v1/chat/completions"
    assert cap["json"]["model"] == "llama-3.3-70b-versatile"
    assert cap["json"]["messages"][0] == {"role": "user", "content": "say hi"}
    assert cap["headers"]["Authorization"] == "Bearer k"


def test_gemini_text_parse_drops_thought_parts(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    _mock(monkeypatch, _Resp(200, {"candidates": [{"content": {"parts": [
        {"text": "internal", "thought": True}, {"text": "gem out"}]}}]}))
    assert llm.text("x", provider="gemini") == "gem out"


def test_gemini_request_omits_thinking_config(monkeypatch):
    """Models newer than 2.5 reject thinkingConfig with a 400; sending it locked the app onto
    legacy models. It must not come back."""
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    cap = _mock(monkeypatch, _Resp(200, {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}))
    llm.text("x", provider="gemini")
    assert "thinkingConfig" not in cap["json"]["generationConfig"]


def test_circuit_breaker_is_per_provider(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    _mock(monkeypatch, _Resp(429, {}))
    assert llm.text("x", provider="openai") is None            # 429 -> None + trips openai's breaker
    _mock(monkeypatch, _Resp(200, {"choices": [{"message": {"content": "nope"}}]}))
    assert llm.text("x", provider="openai") is None            # breaker open: skipped instantly
    # ...but gemini is untouched by openai's quota trip.
    _mock(monkeypatch, _Resp(200, {"candidates": [{"content": {"parts": [{"text": "gem"}]}}]}))
    assert llm.text("x", provider="gemini") == "gem"


def test_chain_falls_through_to_the_next_provider(monkeypatch):
    """The whole point of the chain: one provider dying does not blank the app."""
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://openrouter.ai/api/v1")
    _mock(monkeypatch, {
        "generativelanguage": _Resp(429, {}),
        "openrouter": _Resp(200, {"choices": [{"message": {"content": "from the fallback"}}]}),
    })
    out, why = llm.complete("x", provider="gemini,openai")
    assert out == "from the fallback" and why == ""


def test_reason_names_a_quota_trip_rather_than_blaming_configuration(monkeypatch):
    """Reporting 'no model connected' when the real cause was a rate limit is the lie B-01 told."""
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    _mock(monkeypatch, _Resp(429, {}))
    out, why = llm.complete("x", provider="gemini")
    assert out is None and why == "gemini hit its quota"
    out, why = llm.complete("x", provider="gemini")            # second call sees the open breaker
    assert out is None and "rate-limited" in why and "retrying in" in why


def test_available_reflects_keys_and_breakers(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert llm.available("gemini") is False
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    assert llm.available("gemini") is True
    _mock(monkeypatch, _Resp(429, {}))
    llm.complete("x", provider="gemini")
    assert llm.available("gemini") is False
    assert llm.available("template") is False


def test_openai_vision_builds_image_message(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://openrouter.ai/api/v1")
    cap = _mock(monkeypatch, _Resp(200, {"choices": [{"message": {"content": '{"is_chart": true}'}}]}))
    out = llm.vision("read this chart", b"IMGBYTES", "image/png", provider="openai", json_mode=True)
    assert out == '{"is_chart": true}'
    content = cap["json"]["messages"][0]["content"]
    assert content[0] == {"type": "text", "text": "read this chart"}
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert cap["json"]["response_format"] == {"type": "json_object"}


def test_gemini_vision_builds_inline_data_part(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    cap = _mock(monkeypatch, _Resp(200, {"candidates": [{"content": {"parts": [{"text": "{}"}]}}]}))
    llm.vision("read this", b"IMGBYTES", "image/png", provider="gemini")
    parts = cap["json"]["contents"][0]["parts"]
    assert parts[0] == {"text": "read this"}
    assert parts[1]["inlineData"]["mimeType"] == "image/png"
    assert parts[1]["inlineData"]["data"]                       # base64 of the bytes


def test_plaintext_base_url_is_refused(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://insecure.example")
    out, why = llm.complete("x", provider="openai")
    assert out is None and "failed" in why                      # ValueError caught, never raised out


def test_gemini_budget_reserves_headroom_for_hidden_reasoning(monkeypatch):
    """maxOutputTokens counts thinking. Measured: gemini-flash-latest spent 769-1360 tokens
    reasoning about one chart, so a caller asking for 800 got 24 tokens of prose and a truncated
    reply. Callers budget the answer they want; the headroom pays for the reasoning."""
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    cap = _mock(monkeypatch, _Resp(200, {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}))
    llm.text("x", max_tokens=800, provider="gemini")
    assert cap["json"]["generationConfig"]["maxOutputTokens"] == 800 + llm.THINKING_HEADROOM


def test_truncated_reply_is_reported_not_returned(monkeypatch):
    """A cut-off reply parses as garbage and makes the caller blame its own prompt."""
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    _mock(monkeypatch, _Resp(200, {"candidates": [
        {"finishReason": "MAX_TOKENS", "content": {"parts": [{"text": '{"pattern": "up'}]}}]}))
    out, why = llm.complete("x", provider="gemini")
    assert out is None and "ran out of output budget" in why
    assert llm.available("gemini") is True          # truncation is our fault, so no breaker trip


def test_a_content_filter_rejection_is_reported_as_a_refusal_not_a_crash(monkeypatch):
    """Azure's filter returns 400 with content_filter in the body. That is a REFUSED PROMPT, not a
    broken transport: retrying never helps and the caller must be told which it was. Found the hard
    way — the filter flagged our own prompt-injection defence as a jailbreak attempt."""
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://models.example.ai/inference")

    class _Filtered(_Resp):
        def __init__(self):
            super().__init__(400, {})
            self.text = '{"error":{"code":"content_filter","innererror":{"code":"ResponsibleAIPolicyViolation"}}}'

    _mock(monkeypatch, _Filtered())
    out, why = llm.complete("x", provider="openai")
    assert out is None
    assert "refused the prompt" in why and "safety filter" in why
