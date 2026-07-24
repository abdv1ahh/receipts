"""The Morning Brief composer (Milestone 1) — the reason a trader opens TradeOSS before their charts.

One briefing that answers "what changed overnight and why does it matter", assembled across BOTH planes:
  * the Intelligence plane — impact-ranked, cited news with the analyst's "why it matters" (news.py +
    intelligence/analyst.py), plus an AI executive-summary opener;
  * the Signal plane — the smart-money convergence digest, its numbers untouched and guarded as ever.

Personalized to the names a user follows when signed in, and cached per (user, date) by an inputs-hash
so the LLM opener isn't re-spent until the underlying facts change. Everything degrades to deterministic
prose, so the brief is never blocked on a model being up.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone

import psycopg
from psycopg.types.json import Json

from . import events, news, presentation, social
from .intelligence import analyst

WHAT_CHANGED_LIMIT = 10
YOUR_NEWS_LIMIT = 6


# ------------------------------------------------------------------ smart-money digest (Signal plane)

def smart_money_digest(conn: psycopg.Connection, as_of, voice_name_fn, limit: int = 6) -> dict:
    """Top convergences + biggest recent insider buys + newest activist stakes at `as_of`. Canonical
    home for this digest (the /api/brief endpoint delegates here). `voice_name_fn(cur, lists)` resolves
    filing voice keys to display names (injected so this module stays decoupled from app.py)."""
    top: list[dict] = []
    biggest_buys: list[dict] = []
    new_activist: list[dict] = []
    with conn.cursor() as cur:
        if as_of is not None:
            cur.execute(
                """SELECT c.issuer_entity, e.name, c.score, c.confidence_bucket, c.inputs,
                          (SELECT symbol FROM security_map m WHERE m.entity_id=c.issuer_entity
                             AND m.source='sec_company_tickers' ORDER BY confidence DESC LIMIT 1)
                   FROM signal_clusters c JOIN entities e ON e.id=c.issuer_entity
                   WHERE c.as_of=%s ORDER BY c.score DESC LIMIT %s""",
                (as_of, limit))
            rows = cur.fetchall()
            names = voice_name_fn(cur, [(r[4] or {}).get("contributions", []) for r in rows])
            for ent, name, score, bucket, inputs, sym in rows:
                story = presentation.cluster_story((inputs or {}).get("contributions", []), names)
                top.append({"issuer_entity": ent, "symbol": sym, "name": name,
                            "smart_money_score": presentation.smart_money_score(float(score)),
                            "confidence_bucket": bucket, "headline": story["headline"]})
        cur.execute(
            """SELECT t.owner_name, t.issuer_entity, e.name,
                      (SELECT symbol FROM security_map m WHERE m.entity_id=t.issuer_entity
                         AND m.source='sec_company_tickers' ORDER BY confidence DESC LIMIT 1),
                      round(sum(t.shares * t.price_per_share)) AS value_usd, t.knowable_time::date AS day
               FROM insider_transactions t JOIN entities e ON e.id=t.issuer_entity
               WHERE t.transaction_code='P' AND t.acquired_disposed='A'
                 AND t.shares IS NOT NULL AND t.price_per_share IS NOT NULL AND t.issuer_entity IS NOT NULL
                 AND t.knowable_time <= COALESCE(%s, now())
                 AND t.knowable_time > (SELECT max(knowable_time) FROM insider_transactions) - interval '30 days'
               GROUP BY t.owner_name, t.issuer_entity, e.name, t.knowable_time::date
               ORDER BY value_usd DESC LIMIT 40""",
            (as_of,))
        seen: set[int] = set()
        for nm, ent, name, sym, v, d in cur.fetchall():
            if ent in seen:
                continue
            seen.add(ent)
            biggest_buys.append({"insider": nm, "issuer_entity": ent, "name": name, "symbol": sym,
                                 "value_usd": float(v) if v is not None else None, "date": d.isoformat()})
            if len(biggest_buys) >= 6:
                break
        cur.execute(
            """SELECT s.filer_entity, f.name, s.issuer_entity, e.name,
                      (SELECT symbol FROM security_map m WHERE m.entity_id=s.issuer_entity
                         AND m.source='sec_company_tickers' ORDER BY confidence DESC LIMIT 1), s.knowable_time::date
               FROM stake_events s JOIN entities f ON f.id=s.filer_entity JOIN entities e ON e.id=s.issuer_entity
               WHERE s.form_type='SCHEDULE 13D' AND s.issuer_entity IS NOT NULL
               ORDER BY s.knowable_time DESC LIMIT 6""")
        new_activist = [{"filer_entity": fe, "filer": f, "issuer_entity": ie, "issuer": iss,
                         "symbol": sym, "date": d.isoformat()} for fe, f, ie, iss, sym, d in cur.fetchall()]

    lead = top[0] if top else None
    intro = (f"{len(top)} name{'s' if len(top) != 1 else ''} show smart-money convergence right now"
             + (f", led by {lead['symbol'] or lead['name']} (score {lead['smart_money_score']})." if lead else ".")
             + " Below: the biggest recent insider buys and the newest activist stakes.")
    return {"intro": intro, "top_convergences": top, "biggest_buys": biggest_buys,
            "new_activist_stakes": new_activist, "lead": lead}


# ------------------------------------------------------------------ compose

def _your_names(conn, followed_symbols: list[str], signal_syms: set[str]) -> dict | None:
    if not followed_symbols:
        return None
    syms = sorted({s.upper() for s in followed_symbols})
    items: list[dict] = []
    for s in syms:
        items.extend(news.ranked_news(conn, symbol=s, hours=120, limit=3))
    items.sort(key=lambda x: x["rank"], reverse=True)
    seen, deduped = set(), []
    for it in items:
        if it["id"] in seen:
            continue
        seen.add(it["id"])
        deduped.append(it)
    return {"symbols": syms, "with_signal": sorted(set(syms) & signal_syms),
            "news": deduped[:YOUR_NEWS_LIMIT]}


def _input_hash(as_of, what_changed, followed_symbols, provider, sm_lead) -> str:
    material = {
        "as_of": as_of.isoformat() if as_of else None,
        "news_ids": [it["id"] for it in what_changed],
        "followed": sorted(s.upper() for s in (followed_symbols or [])),
        "provider": provider,
        "sm_lead": (sm_lead or {}).get("symbol"),
    }
    return hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()


def compose(conn: psycopg.Connection, *, as_of, tier: str, delayed_hours: int,
            followed_symbols: list[str], provider: str, voice_name_fn) -> dict:
    """Assemble the full brief (no caching — see cached_compose). Reads what's there; safe on empty
    data (every section can be empty and the brief still renders)."""
    signal_syms = news.signal_symbols(conn)
    what_changed = news.ranked_news(conn, hours=72, limit=WHAT_CHANGED_LIMIT)
    sm = smart_money_digest(conn, as_of, voice_name_fn)
    exec_sum = analyst.executive_summary(what_changed, sm.get("lead"), provider=provider)
    your = _your_names(conn, followed_symbols, signal_syms)
    crowd = social.board(conn, hours=96, limit=6, enrich_top=6)   # what the crowd is watching (attention velocity + why)
    coming = events.brief_events(conn, days=7, limit=6)            # what's coming (earnings + macro, cross-plane)
    return {
        "date": (as_of.date() if as_of else datetime.now(timezone.utc).date()).isoformat(),
        "as_of": as_of.isoformat() if as_of else None,
        "tier": tier, "delayed_hours": delayed_hours,
        "scope": "personal" if followed_symbols else "market",
        "executive_summary": exec_sum,
        "what_changed": what_changed,
        "crowd_watching": crowd,
        "whats_coming": coming,
        "smart_money": {k: v for k, v in sm.items() if k != "lead"},
        "your_names": your,
        "sources_status": news.sources_status(conn),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def cached_compose(conn: psycopg.Connection, *, user_id: int | None, as_of, tier: str,
                   delayed_hours: int, followed_symbols: list[str], provider: str, voice_name_fn) -> dict:
    """compose(), but memoized in daily_briefs by an inputs-hash so the LLM opener isn't re-spent until
    the underlying facts (as_of, the top news set, the user's names, the provider) actually change."""
    scope = "personal" if followed_symbols else "market"
    today = (as_of.date() if as_of else datetime.now(timezone.utc).date())
    # cheap pre-read to build the hash key without the (possibly LLM) executive summary
    what_changed = news.ranked_news(conn, hours=72, limit=WHAT_CHANGED_LIMIT)
    sm_lead_sym = None
    with conn.cursor() as cur:
        if as_of is not None:
            cur.execute("""SELECT (SELECT symbol FROM security_map m WHERE m.entity_id=c.issuer_entity
                                     AND m.source='sec_company_tickers' ORDER BY confidence DESC LIMIT 1)
                           FROM signal_clusters c WHERE c.as_of=%s ORDER BY c.score DESC LIMIT 1""", (as_of,))
            r = cur.fetchone()
            sm_lead_sym = r[0] if r else None
    h = _input_hash(as_of, what_changed, followed_symbols, provider, {"symbol": sm_lead_sym})

    with conn.cursor() as cur:
        if user_id is None:
            cur.execute("SELECT content, input_hash FROM daily_briefs WHERE user_id IS NULL AND brief_date=%s AND scope=%s",
                        (today, scope))
        else:
            cur.execute("SELECT content, input_hash FROM daily_briefs WHERE user_id=%s AND brief_date=%s AND scope=%s",
                        (user_id, today, scope))
        row = cur.fetchone()
    if row is not None and row[1] == h:
        return {**row[0], "from_cache": True}

    result = compose(conn, as_of=as_of, tier=tier, delayed_hours=delayed_hours,
                     followed_symbols=followed_symbols, provider=provider, voice_name_fn=voice_name_fn)
    result["input_hash"] = h
    used_template = result["executive_summary"]["used_template"]
    model_id = result["executive_summary"]["model_id"]
    # don't cache a transient model outage as if it were the day's brief (mirrors the other planes)
    if not (provider != "template" and used_template):
        _store(conn, user_id, today, scope, h, provider, model_id, used_template, result)
    return {**result, "from_cache": False}


def _store(conn, user_id, today, scope, h, provider, model_id, used_template, result) -> None:
    """Upsert the composed brief into the right partial-unique index (market vs personal)."""
    cols = "input_hash=EXCLUDED.input_hash, provider=EXCLUDED.provider, model_id=EXCLUDED.model_id, " \
           "used_template=EXCLUDED.used_template, content=EXCLUDED.content, created_at=now()"
    with conn.cursor() as cur:
        if user_id is None:
            cur.execute(
                "INSERT INTO daily_briefs (user_id, brief_date, scope, input_hash, provider, model_id, "
                "used_template, content) VALUES (NULL,%s,%s,%s,%s,%s,%s,%s) "
                f"ON CONFLICT (brief_date, scope) WHERE user_id IS NULL DO UPDATE SET {cols}",
                (today, scope, h, provider, model_id, used_template, Json(result)))
        else:
            cur.execute(
                "INSERT INTO daily_briefs (user_id, brief_date, scope, input_hash, provider, model_id, "
                "used_template, content) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) "
                f"ON CONFLICT (user_id, brief_date, scope) WHERE user_id IS NOT NULL DO UPDATE SET {cols}",
                (user_id, today, scope, h, provider, model_id, used_template, Json(result)))
    conn.commit()
