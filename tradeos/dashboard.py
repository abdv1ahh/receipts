"""The Dashboard composer — the calm command center that answers "what does a trader need right now?".

One fast call that assembles, from engines that already exist, the few things that matter on open:
  * a **Market Pulse** — a transparent, flow-and-positioning read of the tape (tone + 0..100 score +
    an event-risk level) whose DRIVERS are always shown, so it is explainable and never a black box;
  * today's biggest smart-money opportunities (with which are highest-conviction);
  * what matters now in the news (impact-ranked);
  * the smart-money digest and what's on the radar (macro + earnings, cross-plane flagged).

Design rule inherited from the rest of the product: every number here is computed from real records.
There is no technical-analysis engine for arbitrary tickers and social *sentiment* is thin, so the
Market Pulse deliberately measures **flow & positioning** (insider buy/sell breadth, convergence,
attention, news load, imminent macro) rather than claiming to read a crowd mood it cannot see. It
degrades gracefully: with no data the pulse still renders as a neutral, honestly-labelled reading.
"""
from __future__ import annotations

from datetime import UTC, date, datetime

import psycopg

from . import brief, events, news, social

HIGH_IMPACT = 60          # a news item at/above this intrinsic impact is "high-impact"
SPIKE_VELOCITY = 1.5      # attention running >=1.5x a name's own baseline is an unusual spike


# ------------------------------------------------------------------ real-data probes for the pulse

def _insider_flow(conn: psycopg.Connection, as_of) -> dict:
    """Insider buy vs sell breadth over the trailing 30 days — the tape's clearest directional tell
    from primary filings. Counts and dollar value are facts; the ratio is buys / (buys + sells)."""
    with conn.cursor() as cur:
        cur.execute(
            """SELECT
                 count(*) FILTER (WHERE transaction_code='P' AND acquired_disposed='A') AS buys,
                 count(*) FILTER (WHERE transaction_code='S' AND acquired_disposed='D') AS sells,
                 coalesce(sum(shares*price_per_share)
                          FILTER (WHERE transaction_code='P' AND acquired_disposed='A'), 0) AS buy_usd,
                 coalesce(sum(shares*price_per_share)
                          FILTER (WHERE transaction_code='S' AND acquired_disposed='D'), 0) AS sell_usd
               FROM insider_transactions
               WHERE shares IS NOT NULL AND price_per_share IS NOT NULL
                 AND knowable_time <= COALESCE(%s, now())
                 AND knowable_time >  COALESCE(%s, now()) - interval '30 days'""",
            (as_of, as_of))
        buys, sells, buy_usd, sell_usd = cur.fetchone()
    buys, sells = int(buys or 0), int(sells or 0)
    total = buys + sells
    return {"buys": buys, "sells": sells, "buy_usd": float(buy_usd or 0),
            "sell_usd": float(sell_usd or 0), "total": total,
            "ratio": (buys / total) if total else None}


def _convergence_breadth(conn: psycopg.Connection, as_of) -> dict:
    """How many issuers are showing smart-money convergence at as_of, by confidence bucket."""
    out = {"high": 0, "medium": 0, "low": 0, "total": 0}
    if as_of is None:
        return out
    with conn.cursor() as cur:
        cur.execute("SELECT confidence_bucket, count(*) FROM signal_clusters WHERE as_of=%s "
                    "GROUP BY confidence_bucket", (as_of,))
        for bucket, n in cur.fetchall():
            if bucket in out:
                out[bucket] = int(n)
            out["total"] += int(n)
    return out


def _nearest_high_macro(radar: list[dict]) -> tuple[int | None, str | None]:
    """(days_out, title) of the soonest high-importance macro event on the forward calendar, or
    (None, None). Pure over the already-fetched radar events."""
    today = date.today()
    best_days, best_title = None, None
    for e in radar:
        if e.get("scope") == "macro" and e.get("importance") == "high" and e.get("date"):
            try:
                d = (date.fromisoformat(e["date"]) - today).days
            except ValueError:
                continue
            if d >= 0 and (best_days is None or d < best_days):
                best_days, best_title = d, e.get("title")
    return best_days, best_title


# ------------------------------------------------------------------ the Market Pulse

def _market_pulse(conn, as_of, sm: dict, news_items: list[dict], radar: list[dict],
                  attention: list[dict]) -> dict:
    """A transparent flow-and-positioning read. The score starts neutral (50) and each REAL signal
    nudges it; every nudge that fires becomes a human-readable driver so the number is explainable."""
    flow = _insider_flow(conn, as_of)
    conv = _convergence_breadth(conn, as_of)
    high_news = [n for n in news_items if (n.get("impact") or 0) >= HIGH_IMPACT]
    spikes = [a for a in attention if (a.get("velocity") or 0) >= SPIKE_VELOCITY and a.get("symbol")]
    macro_days, macro_title = _nearest_high_macro(radar)

    score = 50.0
    drivers: list[dict] = []

    # 1) insider flow — the strongest directional input
    if flow["ratio"] is not None and flow["total"] >= 5:
        tilt = round((flow["ratio"] - 0.5) * 44)          # -22..+22
        score += tilt
        pol = "pos" if tilt > 2 else "neg" if tilt < -2 else "neutral"
        verb = "net buyers" if flow["ratio"] >= 0.5 else "net sellers"
        drivers.append({"pol": pol, "label": "Insider flow",
                        "text": f"Company insiders are **{verb}** — {flow['buys']} buys vs "
                                f"{flow['sells']} sells across the last 30 days."})

    # 2) convergence breadth — constructive positioning
    if conv["total"]:
        score += min(15, conv["high"] * 6 + conv["medium"] * 2)
        hc = f" · {conv['high']} high-conviction" if conv["high"] else ""
        drivers.append({"pol": "pos" if conv["high"] else "neutral", "label": "Convergence",
                        "text": f"**{conv['total']} name{'s' if conv['total'] != 1 else ''}** show "
                                f"smart-money convergence{hc}."})

    # 3) attention — activity, not direction
    if spikes:
        score += min(6, len(spikes) * 2)
        names = ", ".join(a["symbol"] for a in spikes[:3])
        drivers.append({"pol": "neutral", "label": "Attention",
                        "text": f"Unusual public attention building on **{names}**."})

    # 4) news load — uncertainty drag
    if high_news:
        score -= min(8, len(high_news) * 2)
        drivers.append({"pol": "warn", "label": "News load",
                        "text": f"**{len(high_news)} high-impact** "
                                f"stor{'ies' if len(high_news) != 1 else 'y'} crossed the wire recently."})

    # 5) imminent macro — scheduled volatility
    if macro_days is not None:
        score -= 6 if macro_days <= 2 else 3
        when = "today" if macro_days == 0 else "tomorrow" if macro_days == 1 else f"in {macro_days} days"
        drivers.append({"pol": "warn", "label": "Macro",
                        "text": f"**{macro_title}** {when} — a scheduled volatility event."})

    score = max(2, min(98, round(score)))
    tone = "risk_on" if score >= 60 else "risk_off" if score < 42 else "mixed"

    if (macro_days is not None and macro_days <= 2) or len(high_news) >= 4:
        risk = "high"
    elif (macro_days is not None and macro_days <= 5) or len(high_news) >= 2 \
            or (flow["ratio"] is not None and flow["ratio"] < 0.45 and flow["total"] >= 5):
        risk = "elevated"
    else:
        risk = "low"

    return {
        "tone": tone, "score": score, "risk": risk,
        "measures": "flow & positioning",     # honest label of WHAT the score reflects
        "drivers": drivers,
        "have_data": bool(drivers),
        "headline": _headline(tone, sm.get("lead"), macro_title, macro_days),
    }


def _headline(tone: str, lead: dict | None, macro_title: str | None, macro_days: int | None) -> str:
    """A crisp, deterministic one-liner built from the same real inputs — instant and always available
    (no model call on the dashboard's hot path), guard-clean by construction (no advice, no invented
    numbers)."""
    tone_txt = {"risk_on": "Positioning leans constructive",
                "mixed": "A mixed, two-sided tape",
                "risk_off": "Positioning leans defensive"}[tone]
    parts = [f"{tone_txt}."]
    if lead and lead.get("symbol"):
        parts.append(f"Smart money is converging hardest on {lead['symbol']}.")
    if macro_days is not None and macro_days <= 3 and macro_title:
        when = "today" if macro_days == 0 else "tomorrow" if macro_days == 1 else f"in {macro_days} days"
        parts.append(f"{macro_title} lands {when}.")
    parts.append("Context, not advice.")
    return " ".join(parts)


# ------------------------------------------------------------------ compose

def compose(conn: psycopg.Connection, *, as_of, tier: str, delayed_hours: int,
            followed_symbols: list[str], provider: str, voice_name_fn) -> dict:
    """Assemble the dashboard. Reads what's there; safe on empty data (every section can be empty and
    the dashboard still renders). `followed_symbols`/`provider` are accepted for parity with the brief
    and future personalization; the current pulse is market-wide and deterministic (fast, always up)."""
    sm = brief.smart_money_digest(conn, as_of, voice_name_fn, limit=8)
    news_items = news.ranked_news(conn, hours=48, limit=8)
    radar = events.brief_events(conn, days=6, limit=6)
    attention = social.board(conn, hours=72, limit=8, enrich_top=4)

    pulse = _market_pulse(conn, as_of, sm, news_items, radar, attention)
    opportunities = sm.get("top_convergences", [])
    high_conviction = [o for o in opportunities if o.get("confidence_bucket") == "high"]

    return {
        "date": (as_of.date() if as_of else datetime.now(UTC).date()).isoformat(),
        "as_of": as_of.isoformat() if as_of else None,
        "tier": tier, "delayed_hours": delayed_hours,
        "market_pulse": pulse,
        "opportunities": opportunities[:5],
        "high_conviction_count": len(high_conviction),
        "news": news_items[:5],
        "smart_money": {k: v for k, v in sm.items() if k != "lead"},
        "radar": radar,
        "attention": [a for a in attention if a.get("symbol")][:5],
        "sources_status": news.sources_status(conn),
        "generated_at": datetime.now(UTC).isoformat(),
    }
