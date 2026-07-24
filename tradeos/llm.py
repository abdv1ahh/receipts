"""Unified LLM transport for every AI plane (Milestone 8): one provider dispatch, one quota
circuit-breaker, one place to add a backend.

Providers (env EXPLAIN_PROVIDER):
  template   no model — text()/vision() return None and callers use their deterministic path.
  gemini     Google AI Studio (free tier). GEMINI_API_KEY, GEMINI_MODEL.
  openai     ANY OpenAI-compatible /chat/completions endpoint. Set OPENAI_BASE_URL + OPENAI_API_KEY +
             OPENAI_MODEL. Works on the FREE tiers of GitHub Models (free with GitHub Pro), Groq, and
             OpenRouter, among others — see FREE-AI.md.

This module is only transport: callers keep the guards + deterministic fallback, and an ordinary
provider failure returns None (never raises) so the caller falls back cleanly.
"""
from __future__ import annotations

import base64
import logging
import os
import time
from urllib.parse import urlparse

import httpx

log = logging.getLogger("tradeos.llm")

_COOLDOWN_UNTIL = 0.0
COOLDOWN_S = 120                    # after persistent 429s, skip the model for this long (all callers)

GEMINI_HOST = "generativelanguage.googleapis.com"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def provider() -> str:
    return os.environ.get("EXPLAIN_PROVIDER", "template").lower()


def model_id(prov: str | None = None) -> str:
    """Human label of what actually produced prose (shown to the user)."""
    p = prov or provider()
    if p == "gemini":
        return os.environ.get("GEMINI_MODEL", "gemini")
    if p == "openai":
        return os.environ.get("OPENAI_MODEL", "openai")
    return p


def available() -> bool:
    """True if a model provider is configured and not in cooldown (a cheap pre-check for callers)."""
    return provider() in ("gemini", "openai") and not _cooling()


def _cooling() -> bool:
    return time.monotonic() < _COOLDOWN_UNTIL


def _trip(reason: str) -> None:
    global _COOLDOWN_UNTIL
    _COOLDOWN_UNTIL = time.monotonic() + COOLDOWN_S
    log.warning("LLM unavailable (%s); cooling model calls for %ds", reason, COOLDOWN_S)


# ---------------------------------------------------------------- Gemini backend

def _gemini(parts: list[dict], max_tokens: int, json_mode: bool) -> str | None:
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return None
    url = GEMINI_URL.format(model=os.environ.get("GEMINI_MODEL", "gemini-flash-latest"))
    if urlparse(url).hostname != GEMINI_HOST:
        raise ValueError("Gemini host allowlist violation")
    gen = {"temperature": 0.3, "maxOutputTokens": max_tokens, "thinkingConfig": {"thinkingBudget": 0}}
    if json_mode:
        gen["responseMimeType"] = "application/json"
    with httpx.Client(timeout=60.0) as client:
        resp = None
        for attempt in range(3):
            resp = client.post(url, params={"key": key}, json={"contents": [{"parts": parts}], "generationConfig": gen})
            if resp.status_code in (429, 503) and attempt < 2:
                time.sleep(min(2 ** (attempt + 1), 20))
                continue
            break
        if resp.status_code in (429, 503):
            _trip("gemini 429")
            return None
        resp.raise_for_status()
        data = resp.json()
    cands = data.get("candidates") or []
    if not cands:
        return None
    ps = cands[0].get("content", {}).get("parts") or []
    return "".join(p.get("text", "") for p in ps if not p.get("thought")).strip() or None


# ---------------------------------------------------------------- OpenAI-compatible backend

def _openai(messages: list[dict], max_tokens: int, json_mode: bool) -> str | None:
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        return None
    base = os.environ.get("OPENAI_BASE_URL", "https://models.github.ai/inference").rstrip("/")
    url = base + "/chat/completions"
    if urlparse(url).scheme != "https":                      # operator-configured, but never plaintext
        raise ValueError("OPENAI_BASE_URL must be https")
    body = {"model": os.environ.get("OPENAI_MODEL", "gpt-4o-mini"), "messages": messages,
            "max_tokens": max_tokens, "temperature": 0.3}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    with httpx.Client(timeout=60.0) as client:
        resp = None
        for attempt in range(3):
            resp = client.post(url, json=body, headers=headers)
            if resp.status_code in (429, 503) and attempt < 2:
                time.sleep(min(2 ** (attempt + 1), 20))
                continue
            break
        if resp.status_code in (429, 503):
            _trip("openai 429")
            return None
        resp.raise_for_status()
        data = resp.json()
    choices = data.get("choices") or []
    if not choices:
        return None
    return (choices[0].get("message", {}).get("content") or "").strip() or None


# ---------------------------------------------------------------- public API

def text(prompt: str, max_tokens: int = 400, json_mode: bool = False, provider: str | None = None) -> str | None:
    """Model completion for a text prompt, or None (no provider / in cooldown / failure) so the caller
    falls back to its deterministic path. `provider` overrides the env (e.g. a caller forcing template)."""
    p = (provider or os.environ.get("EXPLAIN_PROVIDER", "template")).lower()
    if p == "template" or _cooling():
        return None
    try:
        if p == "gemini":
            return _gemini([{"text": prompt}], max_tokens, json_mode)
        if p == "openai":
            return _openai([{"role": "user", "content": prompt}], max_tokens, json_mode)
    except Exception as exc:
        log.warning("llm.text provider %s failed (%s)", p, type(exc).__name__)
    return None


def vision(prompt: str, image_bytes: bytes, mime: str, max_tokens: int = 800,
           json_mode: bool = False, provider: str | None = None) -> str | None:
    """Multimodal completion (prompt + one image), or None so the caller falls back."""
    p = (provider or os.environ.get("EXPLAIN_PROVIDER", "template")).lower()
    if p == "template" or _cooling():
        return None
    b64 = base64.b64encode(image_bytes).decode()
    try:
        if p == "gemini":
            return _gemini([{"text": prompt}, {"inlineData": {"mimeType": mime, "data": b64}}], max_tokens, json_mode)
        if p == "openai":
            content = [{"type": "text", "text": prompt},
                       {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}]
            return _openai([{"role": "user", "content": content}], max_tokens, json_mode)
    except Exception as exc:
        log.warning("llm.vision provider %s failed (%s)", p, type(exc).__name__)
    return None
