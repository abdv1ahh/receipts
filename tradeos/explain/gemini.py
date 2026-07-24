"""Prose-generation prompts for the Signal plane + journal (Slice 5, Decision 10).

The model rephrases the computed facts into fluent prose — it never measures. Each function builds the
prompt from ONLY the computed values and delegates the call to llm.py (any configured provider: gemini,
or a free OpenAI-compatible endpoint). Whatever comes back is re-validated by the numbers + directive
guards in base.py before it is ever shown; None -> the deterministic template, so the product never
depends on a model being up. (Module keeps the name its callers import; transport is provider-agnostic.)
"""
from __future__ import annotations

import json
import logging
from collections import Counter

from .. import llm

log = logging.getLogger("tradeos.explain.prose")

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
    return llm.text(INSTRUCTION + json.dumps(_payload(detail, cal, horizon)), max_tokens=512)


TRADE_INSTRUCTION = (
    "You are writing a short, neutral, educational review of a trade a user logged in their own "
    "journal, for a financial-intelligence terminal. Follow these rules exactly:\n"
    "- Rephrase ONLY the facts in the data below into 2 to 4 fluent sentences. This is post-hoc "
    "journaling and risk framing, never advice.\n"
    "- NEVER tell the user what to do. NEVER use the words buy, sell, hold, should, recommend, "
    "price target, outperform, underperform, or any directive/advice language.\n"
    "- NEVER introduce a number that is not present in the data (no invented prices, ratios, or "
    "percentages).\n"
    "- End with: this is an educational review of a logged trade, not advice about any position.\n"
    "DATA (JSON):\n"
)


def generate_trade_prose(analysis: dict, trade: dict) -> str | None:
    """Rephrase a computed trade analysis into fluent prose — never measures. The caller re-checks
    both guards; None with no provider / on failure so the deterministic prose is used."""
    payload = {
        "symbol": trade.get("symbol"), "direction": trade.get("direction"),
        "asset_class": trade.get("asset_class"), "status": trade.get("status"),
        "reward_risk": analysis.get("reward_risk"), "realized_pnl_pct": analysis.get("realized_pnl_pct"),
        "observations": analysis.get("observations"), "risk_flags": analysis.get("risk_flags"),
        "context": analysis.get("context"),
    }
    return llm.text(TRADE_INSTRUCTION + json.dumps(payload), max_tokens=512)


REPORT_INSTRUCTION = (
    "You are writing a short, neutral, educational summary of a user's OWN trading journal for a "
    "financial-intelligence terminal. Follow these rules exactly:\n"
    "- Synthesise ONLY the aggregate facts in the data below (counts, win rate if present, recurring "
    "risk-management habits) into 3 to 5 fluent sentences. This is post-hoc journaling and risk "
    "framing, never advice.\n"
    "- NEVER tell the user what to do or what to trade. NEVER use the words buy, sell, hold, should, "
    "recommend, price target, outperform, underperform, or any directive/advice language.\n"
    "- NEVER introduce a number that is not present in the data (no invented rates, counts, or "
    "percentages). If win_rate is null, do not state a win rate.\n"
    "- Speak to habits and patterns, encouragingly and neutrally. End with: this is an educational "
    "summary of trades you logged, not advice about any position.\n"
    "DATA (JSON):\n"
)


def generate_journal_report(report: dict) -> str | None:
    return llm.text(REPORT_INSTRUCTION + json.dumps(report), max_tokens=640)


ASSISTANT_INSTRUCTION = (
    "You are the assistant inside a financial-intelligence terminal. Answer the user's question using "
    "ONLY the CONTEXT JSON below, which is real platform data. Rules, exactly:\n"
    "- Describe only what is in the context. If the context does not contain something the user asked "
    "about (e.g. it marks sentiment or price moves unavailable), say plainly that it is not connected "
    "yet — NEVER invent a sentiment reading, a price reason, a signal, or a number.\n"
    "- NEVER give advice or tell the user what to do. NEVER use buy, sell, hold, should, recommend, "
    "price target, outperform, or any directive/advice language.\n"
    "- NEVER introduce a number that is not in the context.\n"
    "- Be concrete: name the tickers and library titles from the context. 2 to 5 sentences.\n"
    "CONTEXT (JSON):\n"
)


def answer_question(question: str, ctx: dict) -> str | None:
    return llm.text(ASSISTANT_INSTRUCTION + json.dumps(ctx) + "\n\nQUESTION: " + question[:500], max_tokens=640)


VISION_INSTRUCTION = (
    "Extract ONLY the stock ticker symbols visible in this image. Return ONLY a JSON array of "
    "uppercase ticker symbols, e.g. [\"AAPL\",\"MSFT\"]. Ignore all prices, quantities, dollar "
    "amounts, gains, losses, percentages, and any personal or account information. Do not describe "
    "the image. Do not comment on any position. If there are no tickers, return []."
)


def extract_tickers(image_bytes: bytes, mime: str) -> list[str]:
    """Vision call: candidate ticker strings from an image, or [] if no provider / on failure. The
    caller applies the ^[A-Z.]{1,6}$ output guard and validates against the universe."""
    raw = llm.vision(VISION_INSTRUCTION, image_bytes, mime, max_tokens=512, json_mode=True)
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        return [str(x) for x in parsed] if isinstance(parsed, list) else []
    except (ValueError, TypeError):
        return []
