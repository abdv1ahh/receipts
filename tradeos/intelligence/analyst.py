"""The market-intelligence analyst — the interpretive AI the two-plane split unlocks.

For a real news item it produces the "why it matters": an interpretation that connects the item to the
company, its sector, or the broader market. Honesty is enforced structurally:

  * impact + confidence are DETERMINISTIC (news.intrinsic_impact + _confidence) — never the model's.
  * the model writes ONLY the prose, and it must clear three guards before it is ever shown:
      - directive_guard  : no advice / "what to do" language (reused from the Signal plane)
      - numbers_guard    : no numeric figure the item didn't state (reused)
      - citation_guard   : no OTHER ticker than the ones the item is about (new to this plane)
    a failure of any guard discards the model output and the deterministic template renders instead.
  * every result cites its source item(s) and is framed "AI analysis, not advice".
"""
from __future__ import annotations

import json
import logging
import os
import re
import time

from psycopg.types.json import Json

from .. import llm, news
from ..explain.guards import allowed_numbers, directive_guard, numbers_guard

log = logging.getLogger("tradeos.intelligence.analyst")

INSTRUCTION = (
    "You are the market-intelligence analyst inside a professional trading terminal. You are given ONE "
    "real news item and any signal context. Write 1 to 3 sentences explaining WHY it may matter to a "
    "trader watching this name or the market. Rules, exactly:\n"
    "- Interpret and connect it to the company, its sector, or the broader market. This is analysis; "
    "you may reason about likely relevance.\n"
    "- Ground every statement in the item/context below. Do NOT introduce a company, ticker symbol, or "
    "numeric figure that is not present in the context.\n"
    "- Do NOT give advice or say what anyone should do. Never use buy, sell, hold, should, recommend, "
    "price target, overweight, underweight, outperform, or underperform.\n"
    "- Use measured, probabilistic language (may, could, tends to). Do not overstate certainty.\n"
    "- End with exactly: AI analysis, not advice.\n"
    "CONTEXT (JSON):\n"
)

# ----------------------------------------------------------------- new guard: citation integrity

_OUT_CASHTAG = re.compile(r"\$([A-Z]{1,5}(?:\.[A-Z])?)\b")
_OUT_EXCH = re.compile(r"\((?:NYSE|NASDAQ|NYSEARCA|AMEX|OTC)[:\s]+([A-Z]{1,5}(?:\.[A-Z])?)\)", re.I)


def citation_guard(text: str, allowed_symbols) -> bool:
    """True if the output cites no ticker other than the ones the item is about. Blocks the model
    from smuggling in a different company via a $cashtag or an exchange-qualified mention."""
    allowed = {str(s).upper() for s in (allowed_symbols or [])}
    for m in _OUT_CASHTAG.finditer(text):
        if m.group(1).upper() not in allowed:
            return False
    for m in _OUT_EXCH.finditer(text):
        if m.group(1).upper() not in allowed:
            return False
    return True


# ----------------------------------------------------------------- deterministic confidence + prose

def _confidence(item: dict) -> str:
    """How much weight to put on 'this matters' — deterministic. Primary-source (8-K) material events
    rate higher than a headline mention; smart-money overlap raises it further."""
    primary = item.get("source", "").startswith("sec/")
    heavy = item.get("category") in ("earnings", "ma", "distress", "guidance")
    if primary and (heavy or item.get("has_signal")):
        return "high"
    if primary or item.get("has_signal"):
        return "medium"
    return "low"


# Clauses that follow a ticker: "{SYM} <clause>."
_SYMBOL_PROSE = {
    "earnings": "just reported results — a scheduled catalyst that can reset expectations for it and its peers",
    "ma": "is involved in an acquisition or change of control, which reshapes its size and strategy and can ripple to competitors and suppliers",
    "distress": "flagged a stress event (bankruptcy risk, an impairment, a delisting notice, or restated financials), which tends to weigh on the name until it is resolved",
    "officer_change": "changed its executive suite or board — a shift markets read as a signal about the company's direction",
    "guidance": "updated the forward outlook the market prices it on",
    "agreement": "entered or ended a material agreement, changing its obligations",
    "financing": "changed its financing or capital structure",
    "regulatory": "is subject to a regulatory action that can change the rules it operates under",
    "governance": "disclosed a governance item its shareholders track",
    "disclosure": "disclosed a material item where the detail matters more than the headline",
    "general": "disclosed a material item where the detail matters more than the headline",
}
# Full self-contained sentences for un-tickered macro / market items.
_MARKET_PROSE = {
    "macro": "A macro development like this can move rates, the dollar, and risk appetite across the market as a whole rather than any single name.",
    "markets": "A broad-market headline that helps set today's tape for individual names.",
    "regulatory": "A regulatory or policy development that can shift the rules companies operate under.",
    "general": "A market headline worth a quick scan for second-order effects.",
}


def _template_why(item: dict) -> str:
    """Deterministic 'why it matters' — the always-available path, safe by construction (guard-clean:
    no advice, no invented numbers, no foreign tickers)."""
    syms = item.get("symbols") or []
    cat = item.get("category") or "general"
    if syms:
        sym = syms[0]
        parts = [f"{sym} {_SYMBOL_PROSE.get(cat, _SYMBOL_PROSE['general'])}."]
        if item.get("has_signal"):
            parts.append(f"Smart money is already converging on {sym} in TradeOSS signal data, so the reaction here is worth watching.")
    else:
        parts = [_MARKET_PROSE.get(cat, _MARKET_PROSE["general"])]
    parts.append("This is context, not advice.")
    return " ".join(parts)


# ----------------------------------------------------------------- optional model rephrase (via llm.py)

def _ctx(item: dict) -> dict:
    return {"symbols": item.get("symbols"), "category": item.get("category"),
            "headline": item.get("headline"), "summary": item.get("summary"),
            "impact_0_100": item.get("impact"), "smart_money_converging": item.get("has_signal")}


def _why(item: dict, provider: str) -> tuple[str, str, bool]:
    """(prose, model_id, used_template). Optional model rephrase (any provider) held to all three guards."""
    ctx = _ctx(item)
    out = llm.text(INSTRUCTION + json.dumps(ctx), provider=provider)
    if out and directive_guard(out) and numbers_guard(out, allowed_numbers(ctx)) \
            and citation_guard(out, item.get("symbols")):
        return out, llm.model_id(provider), False
    if out:
        log.warning("analyst guard tripped for news %s; using template", item.get("id"))
    return _template_why(item), "template", True


# ----------------------------------------------------------------- DB layer

def analyze_item(conn, item: dict, provider: str | None = None) -> dict:
    """Produce + cache the interpretive layer for one news item. impact/confidence deterministic;
    prose guarded with a deterministic fallback. A genuine model success is cached; a template
    fallback from a model provider is not (so a transient outage doesn't poison the cache)."""
    provider = (provider or os.environ.get("EXPLAIN_PROVIDER", "template")).lower()
    impact = news.intrinsic_impact(item.get("category"), bool(item.get("has_signal")))
    confidence = _confidence(item)
    why, model_id, used_template = _why(item, provider)
    sources = [{"id": item["id"], "url": item.get("url"), "headline": item.get("headline")}]
    result = {"news_id": item["id"], "impact_score": impact, "category": item.get("category"),
              "why_it_matters": why, "confidence": confidence, "sources": sources,
              "provider": provider, "model_id": model_id, "used_template": used_template}
    if not (provider != "template" and used_template):   # don't cache a transient model outage
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO news_analysis (news_id, impact_score, category, why_it_matters,
                       confidence, sources, provider, model_id, used_template)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (news_id) DO UPDATE SET impact_score=EXCLUDED.impact_score,
                       category=EXCLUDED.category, why_it_matters=EXCLUDED.why_it_matters,
                       confidence=EXCLUDED.confidence, sources=EXCLUDED.sources,
                       provider=EXCLUDED.provider, model_id=EXCLUDED.model_id,
                       used_template=EXCLUDED.used_template, created_at=now()""",
                (item["id"], impact, item.get("category"), why, confidence, Json(sources),
                 provider, model_id, used_template))
        conn.commit()
    return result


BRIEF_INSTRUCTION = (
    "You are the market-intelligence analyst writing the opening of a trader's MORNING BRIEF. Given the "
    "top items that changed overnight (JSON), write 2 to 3 sentences summarizing what changed and what "
    "is worth watching today. Rules, exactly:\n"
    "- Ground every claim in the items; introduce no ticker, company, or number not present in them.\n"
    "- No advice — never buy, sell, hold, should, recommend, price target, overweight, underweight, "
    "outperform, underperform.\n"
    "- Measured, probabilistic language. End with exactly: AI analysis, not advice.\n"
    "ITEMS (JSON):\n"
)


def executive_summary(items: list[dict], smart_money_lead: dict | None = None,
                      provider: str | None = None) -> dict:
    """The AI-written 'what changed overnight' opener for the Morning Brief. Same guardrails as every
    interpretive path, with a deterministic fallback so the brief always has an opener."""
    provider = (provider or os.environ.get("EXPLAIN_PROVIDER", "template")).lower()
    top = items[:6]
    ctx = {"top_news": [{"headline": it.get("headline"), "symbols": it.get("symbols"),
                         "category": it.get("category"), "why_it_matters": it.get("why_it_matters")}
                        for it in top],
           "smart_money_lead": smart_money_lead}
    allowed_syms = {s for it in top for s in (it.get("symbols") or [])}
    if smart_money_lead and smart_money_lead.get("symbol"):
        allowed_syms.add(smart_money_lead["symbol"])
    out = llm.text(BRIEF_INSTRUCTION + json.dumps(ctx), max_tokens=400, provider=provider)
    if out and directive_guard(out) and numbers_guard(out, allowed_numbers(ctx)) \
            and citation_guard(out, allowed_syms):
        return {"text": out, "model_id": llm.model_id(provider), "used_template": False}
    if out:
        log.warning("brief summary guard tripped; using template")
    return {"text": _template_exec(top, smart_money_lead), "model_id": "template", "used_template": True}


def _template_exec(items: list[dict], smart_money_lead: dict | None) -> str:
    """Deterministic morning-brief opener — always available, guard-clean by construction."""
    n = len(items)
    tickers = list(dict.fromkeys(it["symbols"][0] for it in items if it.get("symbols")))[:2]
    if not items:
        parts = ["No high-impact developments have crossed the wire in the last day."]
    elif tickers:
        parts = [f"Overnight, {n} material development{'s' if n != 1 else ''} stand out, "
                 f"led by {' and '.join(tickers)}."]
    else:
        parts = [f"Overnight, {n} development{'s' if n != 1 else ''} stand out across macro and market headlines."]
    if smart_money_lead and smart_money_lead.get("symbol"):
        parts.append(f"Smart money is also converging on {smart_money_lead['symbol']} in TradeOSS signal data.")
    parts.append("Details below — context, not advice.")
    return " ".join(parts)


SOCIAL_INSTRUCTION = (
    "You are the market-intelligence analyst. A name is drawing unusual PUBLIC ATTENTION. Given its "
    "attention data and any recent news (JSON), write 1 to 2 sentences on WHY it may be drawing "
    "attention. Rules, exactly:\n"
    "- If a recent news item plausibly explains the attention, connect them. If none does, say the "
    "attention has no obvious catalyst in the data — do NOT invent one.\n"
    "- Ground every claim in the data; introduce no other ticker, company, or number not present.\n"
    "- No advice — never buy, sell, hold, should, recommend, target, overweight, underweight.\n"
    "- Measured language. End with exactly: attention, not advice.\n"
    "DATA (JSON):\n"
)


def _attention_confidence(attention: dict, news_items: list) -> str:
    vel = attention.get("velocity") or 0
    if news_items and vel and vel >= 1.3:
        return "high"          # a real spike with a plausible catalyst
    if news_items:
        return "medium"
    return "low"               # attention without an obvious cause


def _template_attention(symbol: str, attention: dict, news_items: list) -> str:
    vel = attention.get("velocity")
    lead = f"{symbol}'s public attention is running about {vel}x its usual level" if vel else f"{symbol} is drawing unusual public attention"
    if news_items:
        return f"{lead}; a likely driver is coverage such as \"{news_items[0]['headline']}\". This is attention, not advice."
    return f"{lead}, with no obvious news catalyst in TradeOSS sources — a watch-it signal, not advice."


def attention_why(symbol: str, attention: dict, news_items: list[dict], provider: str | None = None) -> dict:
    """Why a name is drawing attention — connect its spike to a recent news catalyst if one fits, else
    say so honestly. Guarded (cite, no advice) with deterministic fallback and deterministic confidence."""
    provider = (provider or os.environ.get("EXPLAIN_PROVIDER", "template")).lower()
    top = news_items[:3]
    confidence = _attention_confidence(attention, top)
    ctx = {"symbol": symbol, "attention_score": attention.get("attention"),
           "velocity_x": attention.get("velocity"), "sources": attention.get("sources"),
           "sentiment": attention.get("sentiment"),
           "recent_news": [{"headline": n.get("headline"), "category": n.get("category")} for n in top]}
    out = llm.text(SOCIAL_INSTRUCTION + json.dumps(ctx), max_tokens=300, provider=provider)
    if out and directive_guard(out) and numbers_guard(out, allowed_numbers(ctx)) \
            and citation_guard(out, [symbol]):
        return {"text": out, "confidence": confidence, "model_id": llm.model_id(provider), "used_template": False}
    if out:
        log.warning("attention_why guard tripped for %s; using template", symbol)
    return {"text": _template_attention(symbol, attention, top), "confidence": confidence,
            "model_id": "template", "used_template": True}


def analyze_recent(conn, hours: int = 48, limit: int = 12, provider: str | None = None,
                   throttle_s: float = 13.0) -> dict:
    """Analyze the top un-analyzed recent items by intrinsic impact, so scarce LLM quota goes to what
    matters most. Throttled between model calls to stay under the free tier's ~5-req/min ceiling; the
    deterministic template covers everything not (yet) model-analyzed, so the brief is never blocked."""
    provider = (provider or os.environ.get("EXPLAIN_PROVIDER", "template")).lower()
    items = news.ranked_news(conn, hours=hours, limit=250)
    todo = [it for it in items if not it["analyzed"]][:limit]
    done = 0
    for i, it in enumerate(todo):
        analyze_item(conn, it, provider)
        done += 1
        if llm.wants_model(provider) and i < len(todo) - 1:
            time.sleep(throttle_s)
    return {"analyzed": done, "candidates_recent": len(items)}
