"""AI Market Assistant (Slice G): a grounded, guarded Q&A over REAL platform data.

The assistant speaks only from retrieved facts — the smart-money convergence signals, the
intelligence library, and (for a logged-in user) their own logged trades. It never invents a number
and never gives advice: the model answer clears the SAME directive + numbers guards as the
explanation layer, and falls back to a deterministic answer built from the same context. Topics it
has no data for (live social sentiment, real-time price-move reasons) it says it does not have —
never fabricated. Retrieval is tier-honest (clusters read at the tier's effective as_of) and
object-scoped (only the requester's own trades).

Pure helpers first (intent classification, candidate tickers, deterministic answer), then the DB
retrieval + the guarded orchestrator.
"""
from __future__ import annotations

import json
import logging
import os
import re

import psycopg
from psycopg import sql

from . import config, llm, sentiment, trades
from .explain.guards import allowed_numbers, directive_guard, numbers_guard

log = logging.getLogger("tradeos.assistant")

# all-caps tokens that look like tickers but are not (kept small; the DB is the real filter)
STOP = {"I", "A", "AI", "AN", "THE", "AND", "OR", "FOR", "WHY", "HOW", "IS", "IT", "IF", "SO", "TO",
        "US", "USA", "UK", "EU", "CEO", "CFO", "IPO", "ETF", "EPS", "PE", "YOY", "ATH", "DD", "WSB",
        "FOMO", "OK", "Q", "R", "RR", "PNL", "P", "L", "SEC", "SPY", "MY", "ME", "DO", "OF", "IN", "ON"}

_PERF = ("my trade", "my trades", "my performance", "how am i", "my win", "my journal", "my stats",
         "am i doing", "my habit", "my p&l", "my pnl", "my history")
_SENT = ("discuss", "talking about", "trending", "sentiment", "reddit", "twitter", "buzz", "hype",
         "social", "mentions", "what are traders", "everyone talking")
_MOVE = ("why is", "why did", "why are", "why's", "moving", "dropping", "spiking", "rallying",
         "selling off", "pumping", "tanking", "gap up", "gap down")
_CONCEPT = ("explain", "what is", "what are", "what's a", "how does", "how do", "teach", "definition",
            "mean", "strategy", "learn")
_PERSONAL = ("my portfolio", "my watchlist", "my position", "my holding", "my risk", "risks am i",
             "risk am i missing", "am i missing", "match my", "matches my", "my strategy",
             "should i hold", "my desk", "on my radar", "names i follow", "i own", "i'm holding")


def classify(question: str) -> dict:
    """Cheap intent flags from the raw question. Multiple can be true (a question can ask about a
    ticker AND a concept). The DB retrieval decides what real context actually exists."""
    q = f" {question.lower()} "
    def hit(kws):
        return any(k in q for k in kws)
    return {"performance": hit(_PERF), "sentiment": hit(_SENT), "why_moving": hit(_MOVE),
            "concept": hit(_CONCEPT), "personal": hit(_PERSONAL)}


def candidate_symbols(question: str) -> list[str]:
    """Cashtags ($NVDA) and already-uppercase tokens that could be tickers, minus the stop-list.
    Deduped, order-preserving, capped — the DB then confirms which actually resolve."""
    seen: list[str] = []
    for m in re.finditer(r"\$([A-Za-z]{1,5})\b|\b([A-Z]{1,5})\b", question):  # reading order
        s = (m.group(1) or m.group(2)).upper()
        if s not in STOP and s not in seen:
            seen.append(s)
    return seen[:3]


# ------------------------------------------------------------------ deterministic grounded answer

_CLOSER = ("This describes disclosed smart-money activity and your own records — not advice about any "
           "position.")


def build_answer(question: str, ctx: dict) -> tuple[str, list[str]]:
    """Compose a plain-language answer purely from the retrieved context. Descriptive only, so it
    clears the directive guard by construction; every number comes from the context. Returns
    (answer, sources)."""
    parts: list[str] = []
    sources: list[str] = []

    for s in ctx.get("symbols", []):
        c = s.get("cluster")
        if c:
            classes = ", ".join(c.get("source_classes") or []).replace("_", " ") or "disclosures"
            parts.append(
                f"{s['name']} ({s['symbol']}) currently shows a {c['bucket']}-confidence smart-money "
                f"convergence: {c['voices']} independent filers across {classes}, at a convergence "
                f"score of {c['score']}. Its deep-dive lists every contributing filing, each with its "
                f"disclosure delay, and the backtested base rate for that bucket.")
            sources.append(f"signal:{s['symbol']}")
        else:
            parts.append(
                f"{s['name']} ({s['symbol']}) has no active convergence cluster in the current data; "
                f"its activity page shows any individual insider, activist, or fund disclosures on file.")
            sources.append(f"activity:{s['symbol']}")
        att = s.get("attention")
        if att:
            parts.append(f"Public attention on {s['symbol']}: an attention score of {att['score']} from "
                         f"{att['mentions']} recent mentions ({', '.join(att['sources'])}).")
            sources.append(f"attention:{s['symbol']}")
    for u in ctx.get("unrecognized", []):
        parts.append(f"{u} isn't in the smart-money dataset (outside the covered filings, or not a "
                     f"recognized ticker).")

    if ctx.get("why_moving") and ctx.get("symbols"):
        parts.append("I don't have a live price or news feed to explain an intraday move; what I can "
                     "show is the disclosed positioning above.")
        sources.append("gap:price_moves")

    for lib in ctx.get("library", []):
        parts.append(f"On the concept itself, the intelligence library has “{lib['title']}” — "
                     f"an original, sourced explanation of the pattern.")
        sources.append(f"library:{lib['slug']}")

    perf = ctx.get("performance")
    if perf is not None:
        if perf.get("sufficient"):
            wr = round(perf["win_rate"] * 100)
            rr = perf.get("avg_reward_risk")
            rr_txt = f" at an average reward-to-risk of {rr} to 1" if rr is not None else ""
            parts.append(f"Across your {perf['n_closed']} closed trades, your recorded win rate is "
                         f"{wr}%{rr_txt}. The performance tab breaks this down by strategy.")
        else:
            parts.append(f"You've logged {perf['n_closed']} closed trade(s); {config.brand_name()} reports a win rate "
                         f"and habits once there are at least 10, so it never calls an edge from a small "
                         f"sample.")
        sources.append("your_performance")

    wl = ctx.get("watchlist")
    if wl:
        parts.append(f"On your watchlist ({', '.join(wl[:8])}), ask me about any name for its "
                     f"smart-money signal and the backtested base rate for its bucket.")
        sources.append("your_watchlist")
    op = ctx.get("open_positions")
    if op:
        listing = ", ".join(f"{o['direction']} {o['symbol']}" for o in op[:6])
        parts.append(f"Your open positions on record: {listing}. I can pull the disclosed smart-money "
                     f"positioning for any of them — the decision stays yours.")
        sources.append("your_positions")

    tr = ctx.get("trending")
    if tr:
        listing = ", ".join(f"{t['symbol']} ({t['attention']})" for t in tr)
        parts.append(f"By public attention right now, the most-discussed tracked names are {listing} "
                     f"(attention is a velocity score against each name's own baseline).")
        sources.append("trending")

    if ctx.get("sentiment"):
        parts.append("Live social sentiment — what Reddit, X, and YouTube are discussing — isn't "
                     "connected yet; it's the next data layer. For now I can only speak to disclosed "
                     "smart-money activity from SEC filings, which is real and dated.")
        sources.append("gap:sentiment")

    top = ctx.get("top_signals", [])
    if top:
        listing = ", ".join(f"{t['symbol']} ({t['bucket']})" for t in top)
        parts.append(f"The strongest current smart-money convergences include {listing}. Ask about any "
                     f"ticker for its filers and backtested base rate.")
        sources.append("top_signals")

    if not parts:
        parts.append("I can answer about the smart-money signals (insiders, activists, and funds "
                     "converging on a stock), the methodology and intelligence library, and your own "
                     "logged trades. Live social sentiment and price-move explanations aren't connected yet.")

    return " ".join(parts) + " " + _CLOSER, sources


# ------------------------------------------------------------------ DB retrieval

def _resolve(cur, sym: str):
    cur.execute("SELECT m.entity_id, e.name FROM security_map m JOIN entities e ON e.id=m.entity_id "
                "WHERE m.symbol=%s AND m.source='sec_company_tickers' ORDER BY m.confidence DESC LIMIT 1",
                (sym,))
    return cur.fetchone()


def _latest_cluster(cur, entity_id, as_of):
    cur.execute("SELECT confidence_bucket, voices, score, source_classes FROM signal_clusters "
                "WHERE issuer_entity=%s AND as_of<=%s ORDER BY as_of DESC LIMIT 1", (entity_id, as_of))
    r = cur.fetchone()
    if not r:
        return None
    return {"bucket": r[0], "voices": r[1], "score": round(float(r[2]), 2), "source_classes": r[3]}


def _library_matches(cur, question, limit=2):
    terms = [t for t in re.sub(r"[^a-z ]", " ", question.lower()).split() if len(t) > 4]
    if not terms:
        return []
    # One placeholder per term, composed. The terms themselves are still bound values — the only
    # thing being built is the number of OR branches.
    where = sql.SQL(" OR ").join(sql.SQL("title ILIKE {}").format(sql.Placeholder()) for _ in terms)
    cur.execute(sql.SQL("SELECT slug, title, body_md FROM library_entries WHERE ({where}) "
                        "ORDER BY created_at LIMIT %s").format(where=where),
                (*[f"%{t}%" for t in terms], limit))
    # include a body excerpt so the assistant can actually explain the concept, not just name it
    return [{"slug": s, "title": t, "excerpt": " ".join((b or "").split())[:600]}
            for s, t, b in cur.fetchall()]


def _top_signals(cur, as_of, limit=4):
    cur.execute("SELECT DISTINCT ON (c.issuer_entity) e.name, c.confidence_bucket, c.issuer_entity, "
                "(SELECT symbol FROM security_map m WHERE m.entity_id=c.issuer_entity "
                " AND m.source='sec_company_tickers' ORDER BY confidence DESC LIMIT 1) AS sym "
                "FROM signal_clusters c JOIN entities e ON e.id=c.issuer_entity "
                "WHERE c.as_of<=%s AND c.confidence_bucket IN ('high','medium') "
                "ORDER BY c.issuer_entity, c.as_of DESC", (as_of,))
    rows = [r for r in cur.fetchall() if r[3]]
    rank = {"high": 0, "medium": 1}
    rows.sort(key=lambda r: rank.get(r[1], 2))
    return [{"symbol": r[3], "bucket": r[1]} for r in rows[:limit]]


def _user_performance(cur, user_id):
    cur.execute("SELECT direction, status, entry_price, exit_price, stop_price, target_price, strategy "
                "FROM trades WHERE user_id=%s", (user_id,))
    rows = []
    for d, status, entry, exit_, stop, target, strat in cur.fetchall():
        rows.append({"strategy": strat,
                     "rr": trades.reward_risk(entry, stop, target, d),
                     "realized_pnl_pct": trades.realized_pnl_pct(entry, exit_, d) if status == "closed" else None})
    return trades.summarize_performance(rows)


def retrieve(conn: psycopg.Connection, question: str, user, as_of) -> dict:
    intents = classify(question)
    ctx: dict = {"symbols": [], "unrecognized": [], "library": [], "why_moving": intents["why_moving"]}
    with conn.cursor() as cur:
        for sym in candidate_symbols(question):
            r = _resolve(cur, sym)
            if r:
                entry = {"symbol": sym, "name": r[1], "cluster": _latest_cluster(cur, r[0], as_of)}
                sdata = sentiment.symbol_sentiment(conn, sym)   # real public-attention data, if any
                if sdata:
                    entry["attention"] = {"score": sdata["attention"], "mentions": sdata["mentions"],
                                          "sources": sdata["sources"]}
                ctx["symbols"].append(entry)
            elif f"${sym}".lower() in question.lower() or intents["why_moving"]:
                ctx["unrecognized"].append(sym)
        if intents["concept"] or not ctx["symbols"]:
            ctx["library"] = _library_matches(cur, question)
        if intents["performance"] and user:
            perf = _user_performance(cur, user["id"])   # clean keys only (no raw fractions to restate)
            ctx["performance"] = {k: perf[k] for k in ("n_closed", "sufficient", "win_rate", "avg_reward_risk")}
        if user and (intents["personal"] or intents["performance"]):
            # the user's own desk — object-scoped, non-numeric (so it never trips the numbers guard)
            cur.execute("SELECT ref FROM follows WHERE user_id=%s AND kind='symbol' LIMIT 12", (user["id"],))
            wl = [r[0] for r in cur.fetchall() if r[0]]
            if wl:
                ctx["watchlist"] = wl
            cur.execute("SELECT symbol, direction FROM trades WHERE user_id=%s AND status='open' "
                        "AND symbol IS NOT NULL LIMIT 8", (user["id"],))
            op = [{"symbol": s, "direction": d} for s, d in cur.fetchall()]
            if op:
                ctx["open_positions"] = op
        if intents["sentiment"]:
            board = sentiment.trending_board(conn, limit=6)
            if board:
                ctx["trending"] = [{"symbol": b["symbol"], "attention": b["attention"], "sentiment": b["sentiment"]}
                                   for b in board]
            else:
                ctx["sentiment"] = True     # honest gap: asked about discussion, none connected/ingested yet
        if not ctx["symbols"] and not intents["performance"]:   # general question -> ground on real signals
            ctx["top_signals"] = _top_signals(cur, as_of)
    return ctx


# ------------------------------------------------------------------ guarded orchestrator

TOOL_INSTRUCTION = """You answer questions about world events and what they mean for markets, using
ONLY data retrieved from this system's own stores.

Choose the lookups that would answer the question. Reply with JSON only:
  {"tools": [{"name": "<tool>", "args": {...}}], "why": "<one line>"}

Available lookups:
%s

Pick at most 3. Pick none (an empty list) if the question needs no data — but prefer looking
something up over answering from memory, because answering from memory is how a wrong number
reaches a user.

If the question is about how reliable this system is, call track_record. If it is about what this
system can or cannot see, call data_coverage.

QUESTION: """


ANSWER_INSTRUCTION = """Answer the question using ONLY the retrieved data below. Rules:

- Cite what you used. Refer to specific events, claims or figures that appear in the data.
- If the data does not answer the question, SAY SO plainly. Do not fill the gap from memory. "The
  store has nothing on that" is a good answer; an invented figure is not.
- Never state a number that does not appear in the retrieved data.
- Describe and explain; never tell anyone what to do. No buy, sell, hold, or price targets.
- If a claim carries a confidence, give it. A prediction without its confidence is misleading.
- Keep it to a short paragraph or two.

QUESTION: {question}

RETRIEVED DATA (from this system's stores):
{data}
"""


def plan_tools(question: str, provider=None) -> list[dict]:
    """Ask the model which lookups would answer this. Returns [] on any failure, so the assistant
    falls back to the deterministic retrieval rather than answering blind."""
    from . import assistant_tools
    raw = llm.text(TOOL_INSTRUCTION % assistant_tools.describe() + question[:500],
                   max_tokens=300, json_mode=True, provider=provider, role=llm.FAST)
    if not raw:
        return []
    try:
        parsed = json.loads(raw.strip().strip("`").split("\n", 1)[-1]
                            if raw.strip().startswith("```") else raw)
    except (ValueError, TypeError):
        return []
    tools = parsed.get("tools") if isinstance(parsed, dict) else None
    if not isinstance(tools, list):
        return []
    out = []
    for t in tools[:3]:
        if isinstance(t, dict) and isinstance(t.get("name"), str):
            out.append({"name": t["name"], "args": t.get("args") if isinstance(t.get("args"), dict) else {}})
    return out


def run_tools(conn, plan: list[dict]) -> tuple[dict, list[dict]]:
    """Execute the plan. Returns (data, citations). Every tool is read-only and parameterised —
    see assistant_tools for why that boundary matters here specifically."""
    from . import assistant_tools
    data, citations = {}, []
    for step in plan:
        result = assistant_tools.call(conn, step["name"], step.get("args"))
        data[step["name"]] = result
        for ev in (result.get("events") or []):
            if ev.get("url"):
                citations.append({"label": ev["title"][:120], "url": ev["url"]})
        for cl in (result.get("claims") or []):
            if cl.get("url"):
                citations.append({"label": cl.get("headline") or "interpretation", "url": cl["url"]})
    return data, citations[:8]


def answer(conn: psycopg.Connection, question: str, user, as_of, provider=None) -> dict:
    provider = (provider or os.environ.get("EXPLAIN_PROVIDER", "template")).lower()
    ctx = retrieve(conn, question, user, as_of)
    det, sources = build_answer(question, ctx)
    grounded = bool(ctx.get("symbols") or ctx.get("library") or ctx.get("performance")
                    or ctx.get("top_signals"))

    # Tool-using path first: let the model choose lookups, run them, then answer from what came
    # back. Falls through to the previous behaviour whenever the model is unavailable.
    tool_data, tool_citations, tools_used = {}, [], []
    if llm.available(provider):
        plan = plan_tools(question, provider=provider)
        if plan:
            tool_data, tool_citations = run_tools(conn, plan)
            tools_used = [p["name"] for p in plan]

    text, model_id, used_template = det, "template", True
    if tool_data:
        out = llm.text(
            ANSWER_INSTRUCTION.format(question=question[:500],
                                      data=json.dumps(tool_data, default=str)[:9000]),
            max_tokens=700, provider=provider, role=llm.DEEP)
        # The numbers guard is deliberately relaxed here versus the Signal plane: the model is
        # quoting figures out of OUR OWN stores, which it was just handed, so the relevant risk is
        # advice language rather than invented measurements.
        if out and directive_guard(out):
            return {"answer": out, "sources": sources + [c["label"] for c in tool_citations],
                    "citations": tool_citations, "tools_used": tools_used,
                    "model_id": llm.model_id(provider), "used_template": False, "grounded": True}
        if out:
            log.warning("assistant tool answer tripped the advice guard; using deterministic answer")

    if llm.wants_model(provider):
        try:
            from .explain import gemini
            phrased = gemini.answer_question(question, ctx)
        except Exception as exc:  # missing key / API error -> deterministic
            log.warning("assistant provider unavailable (%s)", type(exc).__name__)
            phrased = None
        if phrased:
            allowed = allowed_numbers(ctx, {"_const": [1, 5, 10, 100]})
            if directive_guard(phrased) and numbers_guard(phrased, allowed):
                text, model_id, used_template = phrased, llm.model_id(provider), False
            else:
                log.warning("assistant guard tripped; using deterministic answer")

    return {"answer": text, "sources": sources, "citations": tool_citations,
            "tools_used": tools_used, "model_id": model_id,
            "used_template": used_template, "grounded": grounded}
