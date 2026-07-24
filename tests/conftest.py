"""Test isolation. The dev `.env` may configure a live AI provider (EXPLAIN_PROVIDER=openai + a key);
tests must never depend on it or hit the network. This autouse fixture forces the deterministic
'template' provider and clears provider keys for every test. Tests that exercise a provider set it
explicitly AND mock the transport (see test_llm.py)."""
import pytest


@pytest.fixture(autouse=True)
def _isolate_ai_provider(monkeypatch):
    monkeypatch.setenv("EXPLAIN_PROVIDER", "template")
    for key in ("OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_MODEL", "GEMINI_API_KEY"):
        monkeypatch.delenv(key, raising=False)
