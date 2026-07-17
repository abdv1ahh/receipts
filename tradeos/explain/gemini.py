"""Gemini explanation provider (Slice 5, Decision 10).

The model rephrases the computed facts into fluent prose — it never measures. It is given
ONLY the computed values and is instructed to introduce no new numbers and no directive
language; whatever it returns is then validated by the numbers guard and the directive guard
in base.py before it is ever shown. If the key is unset or the call fails, this returns None
and the deterministic template is used — the product never depends on the model being up.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import time
from collections import Counter
from urllib.parse import urlparse

import httpx

log = logging.getLogger("tradeos.explain.gemini")

GEMINI_HOST = "generativelanguage.googleapis.com"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

INSTRUCTION = (
    "You are writing a short, neutral explanation of a convergence signal for a financial-"
    "intelligence terminal. Follow these rules exactly:\n"
    "- Describe ONLY what disclosed third parties did. Attribute facts to their source class "
    "(insider, activist, passive stake, institutional holding) and note staleness where given.\n"
    "- Use probability-framed, descriptive language. NEVER tell anyone what to do. NEVER use "
    "the words buy, sell, hold, should, recommend, or any directive/advice language.\n"
    "- NEVER introduce any number that is not present in the data below. Do not compute new "
    "figures, do not add a scale (no 'out of 10'), and do not editorialize ('near-perfect', "
    "'strong'). State only the exact values given.\n"
    "- Write 2 to 4 sentences. End with: this describes disclosed activity, not a prediction "
    "about any position.\n"
    "DATA (JSON):\n"
)


def _payload(detail: dict, cal: dict | None, horizon: int) -> dict:
    inp = detail.get("inputs", {})
    counts = Counter(c["source_class"] for c in inp.get("contributions", []))
    hit = round(cal["hit_rate"] * 100) if (cal and cal.get("sufficient")) else None
    return {
        "issuer": detail.get("name"), "symbol": detail.get("symbol"),
        "convergence_score": round(detail.get("score", 0), 2),
        "confidence_bucket": detail.get("confidence_bucket"),
        "voices": detail.get("voices"), "source_classes": detail.get("source_classes"),
        "composition": dict(counts), "window_days": inp.get("window_days"),
        "freshest_knowable": (inp.get("freshest_knowable") or "")[:10],
        "stalest_knowable": (inp.get("stalest_knowable") or "")[:10],
        "backtested": {"horizon_days": horizon, "episodes": (cal or {}).get("episodes"),
                       "hit_rate_pct": hit, "sufficient_sample": bool(cal and cal.get("sufficient"))},
    }


def generate(detail: dict, cal: dict | None, horizon: int) -> str | None:
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return None
    model = os.environ.get("GEMINI_MODEL", "gemini-flash-latest")
    url = GEMINI_URL.format(model=model)
    if urlparse(url).hostname != GEMINI_HOST:
        raise ValueError("Gemini host allowlist violation")
    body = {
        "contents": [{"parts": [{"text": INSTRUCTION + json.dumps(_payload(detail, cal, horizon))}]}],
        # disable "thinking" (this is a rephrasing task, not a reasoning one) so the whole
        # token budget goes to the answer; low temperature to curb editorializing.
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 512,
                             "thinkingConfig": {"thinkingBudget": 0}},
    }
    with httpx.Client(timeout=45.0) as client:
        for attempt in range(3):  # transient 429/503 (quota spikes, model overload) -> brief retry
            resp = client.post(url, params={"key": key}, json=body)
            if resp.status_code in (429, 503) and attempt < 2:
                time.sleep(2 * (attempt + 1))
                continue
            resp.raise_for_status()
            break
        data = resp.json()
    candidates = data.get("candidates") or []
    if not candidates:  # safety block or empty -> let the template render
        log.warning("Gemini returned no candidates; using template")
        return None
    parts = candidates[0].get("content", {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts if not p.get("thought")).strip()
    return text or None


VISION_INSTRUCTION = (
    "Extract ONLY the stock ticker symbols visible in this image. Return ONLY a JSON array of "
    "uppercase ticker symbols, e.g. [\"AAPL\",\"MSFT\"]. Ignore all prices, quantities, dollar "
    "amounts, gains, losses, percentages, and any personal or account information. Do not describe "
    "the image. Do not comment on any position. If there are no tickers, return []."
)


def extract_tickers(image_bytes: bytes, mime: str) -> list[str]:
    """Vision call: return candidate ticker strings from an image, or [] if no key / on failure.
    The caller applies the ^[A-Z.]{1,6}$ output guard and validates against the universe."""
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return []
    model = os.environ.get("GEMINI_MODEL", "gemini-flash-latest")
    url = GEMINI_URL.format(model=model)
    if urlparse(url).hostname != GEMINI_HOST:
        raise ValueError("Gemini host allowlist violation")
    body = {
        "contents": [{"parts": [
            {"text": VISION_INSTRUCTION},
            {"inlineData": {"mimeType": mime, "data": base64.b64encode(image_bytes).decode()}},
        ]}],
        "generationConfig": {"temperature": 0.0, "maxOutputTokens": 512,
                             "thinkingConfig": {"thinkingBudget": 0},
                             "responseMimeType": "application/json"},
    }
    try:
        with httpx.Client(timeout=45.0) as client:
            resp = client.post(url, params={"key": key}, json=body)
            resp.raise_for_status()
            data = resp.json()
        parts = (data.get("candidates") or [{}])[0].get("content", {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts if not p.get("thought")).strip()
        parsed = json.loads(text)
        return [str(x) for x in parsed] if isinstance(parsed, list) else []
    except Exception as exc:  # any failure -> empty -> manual entry
        log.warning("Gemini vision extract failed (%s)", type(exc).__name__)
        return []
