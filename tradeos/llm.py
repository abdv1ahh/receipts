"""Unified LLM transport: one provider chain, one circuit-breaker per provider, one place to add
a backend.

`EXPLAIN_PROVIDER` names the chain, in preference order, comma-separated:

    EXPLAIN_PROVIDER=gemini            one provider
    EXPLAIN_PROVIDER=gemini,openai     fall through to the next when one is down
    EXPLAIN_PROVIDER=template          no model; callers use their deterministic path

Backends:
  gemini     Google AI Studio free tier. GEMINI_API_KEY, GEMINI_MODEL / GEMINI_MODEL_FAST.
  openai     ANY OpenAI-compatible /chat/completions endpoint (Groq, OpenRouter, ...).
             OPENAI_BASE_URL + OPENAI_API_KEY + OPENAI_MODEL / OPENAI_MODEL_FAST.

Two model roles, because the work is not uniform (and free tiers are not free of limits):
  FAST  classification, entity extraction, short rephrasing — a small model, called often.
  DEEP  reasoning about mechanism and consequence — the strongest model available.

This module is only transport. Callers keep their guards and their deterministic fallback. A
provider failure never raises; it returns None *and a plain-language reason*, so the caller can
tell the user what actually happened instead of guessing. Reporting "no model connected" when the
real cause was a quota trip is the kind of lie this product does not tell.
"""
from __future__ import annotations

import base64
import logging
import os
import threading
import time
from urllib.parse import urlparse

import httpx

log = logging.getLogger("tradeos.llm")

COOLDOWN_S = 120                    # after persistent 429s, skip THAT provider for this long
THINKING_HEADROOM = 2048            # tokens reserved for hidden reasoning (see _gemini)
_cooldowns: dict[str, float] = {}   # provider -> monotonic deadline
_lock = threading.Lock()

FAST, DEEP = "fast", "deep"

GEMINI_HOST = "generativelanguage.googleapis.com"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

# Defaults verified working on a free-tier key on 2026-07-25. `gemini-2.0-flash` and
# `gemini-2.5-flash*` are NOT usable defaults: the former has a zero free-tier allowance and the
# latter are closed to new keys.
DEFAULTS = {
    "gemini": {DEEP: "gemini-flash-latest", FAST: "gemini-flash-lite-latest"},
    "openai": {DEEP: "gpt-4o-mini", FAST: "gpt-4o-mini"},
}


def chain(override: str | None = None) -> list[str]:
    """The provider preference order. `override` (a caller forcing 'template', or the AI
    kill-switch flag) replaces the environment entirely."""
    raw = override if override is not None else os.environ.get("EXPLAIN_PROVIDER", "template")
    names = [p.strip().lower() for p in raw.split(",") if p.strip()]
    return names or ["template"]


def provider() -> str:
    """The first provider in the chain — what the app reports it is running on."""
    return chain()[0]


def model_id(prov: str | None = None, role: str = DEEP) -> str:
    """Human label of what actually produced prose (shown to the user)."""
    p = (prov or provider()).split(",")[0].strip().lower()
    if p not in DEFAULTS:
        return p
    key = "GEMINI_MODEL" if p == "gemini" else "OPENAI_MODEL"
    if role == FAST:
        return os.environ.get(f"{key}_FAST") or os.environ.get(key) or DEFAULTS[p][FAST]
    return os.environ.get(key) or DEFAULTS[p][DEEP]


def _has_key(p: str) -> bool:
    return bool(os.environ.get("GEMINI_API_KEY") if p == "gemini" else os.environ.get("OPENAI_API_KEY"))


def available(override: str | None = None) -> bool:
    """True if any provider in the chain is configured and not cooling (a cheap pre-check)."""
    return any(p in DEFAULTS and _has_key(p) and not _cooling(p) for p in chain(override))


def _cooling(p: str) -> bool:
    with _lock:
        return time.monotonic() < _cooldowns.get(p, 0.0)


def _cooldown_left(p: str) -> int:
    with _lock:
        return max(0, int(_cooldowns.get(p, 0.0) - time.monotonic()))


def _trip(p: str, reason: str) -> None:
    with _lock:
        _cooldowns[p] = time.monotonic() + COOLDOWN_S
    log.warning("provider %s unavailable (%s); cooling it for %ds", p, reason, COOLDOWN_S)


def reset_cooldowns() -> None:
    """Test seam: clear every breaker."""
    with _lock:
        _cooldowns.clear()


# ---------------------------------------------------------------- Gemini backend

def _gemini(parts: list[dict], max_tokens: int, json_mode: bool, model: str) -> str | None:
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return None
    url = GEMINI_URL.format(model=model)
    if urlparse(url).hostname != GEMINI_HOST:
        raise ValueError("Gemini host allowlist violation")
    # No thinkingConfig: models newer than 2.5 reject it with a 400, and for the DEEP role
    # thinking is wanted anyway. Thought parts are filtered out of the response below.
    #
    # maxOutputTokens counts THINKING against the same budget as visible output. Measured on
    # 2026-07-25, gemini-flash-latest spent 769-1360 tokens thinking about one chart image, so a
    # caller asking for 800 got 24 tokens of prose and a truncated, unparseable reply. Callers
    # budget the answer they want to see; the headroom pays for the reasoning.
    gen = {"temperature": 0.3, "maxOutputTokens": max_tokens + THINKING_HEADROOM}
    if json_mode:
        gen["responseMimeType"] = "application/json"
    body = {"contents": [{"parts": parts}], "generationConfig": gen}
    with httpx.Client(timeout=60.0) as client:
        resp = None
        for attempt in range(3):
            resp = client.post(url, params={"key": key}, json=body)
            if resp.status_code in (429, 503) and attempt < 2:
                time.sleep(min(2 ** (attempt + 1), 20))
                continue
            break
        if resp.status_code in (429, 503):
            raise _Quota(f"gemini {resp.status_code}")
        resp.raise_for_status()
        data = resp.json()
    cands = data.get("candidates") or []
    if not cands:
        return None
    ps = cands[0].get("content", {}).get("parts") or []
    out = "".join(p.get("text", "") for p in ps if not p.get("thought")).strip() or None
    if cands[0].get("finishReason") == "MAX_TOKENS":
        # A truncated reply is worse than none: it parses as garbage and the caller blames itself.
        raise _Truncated("the model ran out of output budget")
    return out


# ---------------------------------------------------------------- OpenAI-compatible backend

def _openai(messages: list[dict], max_tokens: int, json_mode: bool, model: str) -> str | None:
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        return None
    base = os.environ.get("OPENAI_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")
    url = base + "/chat/completions"
    if urlparse(url).scheme != "https":                      # operator-configured, but never plaintext
        raise ValueError("OPENAI_BASE_URL must be https")
    body = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": 0.3}
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
            raise _Quota(f"openai {resp.status_code}")
        resp.raise_for_status()
        data = resp.json()
    choices = data.get("choices") or []
    if not choices:
        return None
    return (choices[0].get("message", {}).get("content") or "").strip() or None


class _Quota(RuntimeError):
    """Rate limit or capacity error — cool this provider and try the next one."""


class _Truncated(RuntimeError):
    """The reply was cut off mid-answer. Try the next provider; do not cool this one — the
    budget, not the provider, is at fault."""


# ---------------------------------------------------------------- the chain

def _call(p: str, prompt: str, image: tuple[bytes, str] | None, max_tokens: int,
          json_mode: bool, role: str) -> str | None:
    model = model_id(p, role)
    if p == "gemini":
        parts: list[dict] = [{"text": prompt}]
        if image:
            parts.append({"inlineData": {"mimeType": image[1], "data": base64.b64encode(image[0]).decode()}})
        return _gemini(parts, max_tokens, json_mode, model)
    if p == "openai":
        content: str | list[dict] = prompt
        if image:
            url = f"data:{image[1]};base64,{base64.b64encode(image[0]).decode()}"
            content = [{"type": "text", "text": prompt}, {"type": "image_url", "image_url": {"url": url}}]
        return _openai([{"role": "user", "content": content}], max_tokens, json_mode, model)
    return None


def complete(prompt: str, image: tuple[bytes, str] | None = None, max_tokens: int = 400,
             json_mode: bool = False, provider: str | None = None,
             role: str = DEEP) -> tuple[str | None, str]:
    """Try each provider in the chain. Returns (text, reason). `reason` is empty on success and
    otherwise says in plain language why there is no model output, so the caller can tell the
    user the truth rather than assuming the provider is missing."""
    names = chain(provider)
    if names == ["template"]:
        return None, "AI phrasing is switched off — showing the deterministic analysis."
    problems: list[str] = []
    for p in names:
        if p == "template":
            continue
        if p not in DEFAULTS:
            problems.append(f"{p} is not a known provider")
            continue
        if not _has_key(p):
            problems.append(f"{p} has no API key set")
            continue
        if _cooling(p):
            problems.append(f"{p} is rate-limited (retrying in {_cooldown_left(p)}s)")
            continue
        try:
            out = _call(p, prompt, image, max_tokens, json_mode, role)
        except _Quota as exc:
            _trip(p, str(exc))
            problems.append(f"{p} hit its quota")
            continue
        except _Truncated as exc:
            log.warning("provider %s truncated a reply (budget %d)", p, max_tokens)
            problems.append(f"{p} {exc}")
            continue
        except Exception as exc:
            log.warning("provider %s failed (%s)", p, type(exc).__name__)
            problems.append(f"{p} failed ({type(exc).__name__})")
            continue
        if out:
            return out, ""
        problems.append(f"{p} returned nothing")
    return None, "; ".join(problems) or "no model provider is configured"


def text(prompt: str, max_tokens: int = 400, json_mode: bool = False,
         provider: str | None = None, role: str = DEEP) -> str | None:
    """Model completion for a text prompt, or None so the caller falls back."""
    return complete(prompt, None, max_tokens, json_mode, provider, role)[0]


def vision(prompt: str, image_bytes: bytes, mime: str, max_tokens: int = 800,
           json_mode: bool = False, provider: str | None = None,
           role: str = DEEP) -> str | None:
    """Multimodal completion (prompt + one image), or None so the caller falls back."""
    return complete(prompt, (image_bytes, mime), max_tokens, json_mode, provider, role)[0]
