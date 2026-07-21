"""User trade journal + educational analysis (Slice E).

Users log their OWN trades; this is journaling and post-hoc education, never advice. Every string
the analyzer emits is descriptive and clears the same `directive_guard` as the signal explanation
layer, so the product can teach, frame risk, and cross-reference the real smart-money signal — but
it can never tell a user to buy, sell, or hold. Performance analytics obey the same small-sample
honesty as calibration: an edge is named only once the sample is real, never inferred from a handful
of trades.

Pure functions first (reward:risk, realized P&L, the analysis, the performance summary); the DB
helpers below cross-reference the crown-jewel signal, link the intelligence library, optionally
rephrase via a guarded model, and cache the result (mirroring `explanation_cache`).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import date

import psycopg
from psycopg.types.json import Json

from .explain.guards import allowed_numbers, directive_guard, numbers_guard

log = logging.getLogger("tradeos.trades")

PERF_MIN_SAMPLE = 10     # below this: report counts, never a win rate or a named edge
STRAT_MIN_SAMPLE = 8     # below this: a per-strategy rate stays silent
_EDGE_GAP = 0.15         # min win-rate gap before we contrast one strategy with another


# ------------------------------------------------------------------ pure math

def reward_risk(entry, stop, target, direction="long"):
    """Planned reward-to-risk ratio, or None when it cannot be framed from the levels given.
    A long risks entry->stop below and targets above; a short is the mirror. A leg on the wrong
    side (non-positive risk or reward) yields None rather than a misleading ratio."""
    if entry is None or stop is None or target is None:
        return None
    if direction == "long":
        risk, reward = entry - stop, target - entry
    else:
        risk, reward = stop - entry, entry - target
    if risk <= 0 or reward <= 0:
        return None
    return round(reward / risk, 2)


def realized_pnl_pct(entry, exit_, direction="long"):
    """Signed realized return as a fraction (0.1 == +10%), or None if it cannot be computed."""
    if not entry or exit_ is None:
        return None
    r = (exit_ / entry - 1.0) if direction == "long" else (entry - exit_) / entry
    return round(r, 6)


# ------------------------------------------------------------------ pure analysis

def analyze_trade(trade, signal_context=None):
    """Structured, descriptive, guard-safe review of one logged trade. Returns dict of
    {reward_risk, realized_pnl_pct, observations[], risk_flags[], context[]}. `signal_context`
    (optional) is the real smart-money convergence for this issuer, shown for context only."""
    d = trade.get("direction", "long")
    entry, stop = trade.get("entry_price"), trade.get("stop_price")
    target, exit_ = trade.get("target_price"), trade.get("exit_price")
    rr = reward_risk(entry, stop, target, d)
    pnl = realized_pnl_pct(entry, exit_, d) if trade.get("status") == "closed" else None

    observations, risk_flags, context = [], [], []

    if rr is not None:
        observations.append(f"Planned reward-to-risk is {rr} to 1, from the entry, stop, and profit "
                            f"target recorded.")
        if rr < 1:
            risk_flags.append("Planned reward-to-risk is below 1 to 1 — the recorded downside is "
                              "larger than the recorded upside.")
    elif stop is None:
        risk_flags.append("No stop level was recorded, so the downside on this idea is undefined.")
    elif target is None:
        observations.append("No profit target was recorded, so a planned reward-to-risk cannot be framed.")

    size = trade.get("size")
    if entry and stop and size and trade.get("size_unit") == "shares":
        risk_amt = round(abs(entry - stop) * size, 2)
        observations.append(f"At {size} shares with the recorded stop, the idea risks about "
                            f"{risk_amt} to the stop.")

    conf = trade.get("confidence")
    if pnl is not None and conf:
        if pnl < 0 and conf >= 4:
            observations.append(f"Logged at high conviction ({conf} of 5); the recorded result was a "
                                f"loss — a data point for review, not a verdict.")
        elif pnl > 0 and conf <= 2:
            observations.append(f"Logged at low conviction ({conf} of 5); the recorded result was a gain.")

    opened, closed = trade.get("opened_on"), trade.get("closed_on")
    if isinstance(opened, date) and isinstance(closed, date) and trade.get("timeframe") in ("scalp", "day"):
        held = (closed - opened).days
        if held >= 2:
            risk_flags.append(f"Tagged as a {trade['timeframe']} trade but held {held} days — the plan "
                              f"and the execution diverged.")

    if pnl is not None:
        pct = round(abs(pnl) * 100, 2)
        observations.append(f"Recorded result: a {pct}% {'gain' if pnl >= 0 else 'loss'} on the "
                            f"entry-to-exit move.")

    if signal_context and signal_context.get("bucket"):
        sym = trade.get("symbol") or "the issuer"
        n = signal_context.get("voices")
        voices_txt = f" across {n} independent filers" if n else ""
        near = (signal_context.get("as_of") or "")[:10]
        context.append(f"Around this window TradeOS recorded a {signal_context['bucket']}-confidence "
                       f"smart-money convergence in {sym}{voices_txt} (as of {near}) — disclosed "
                       f"third-party activity, shown for context only.")

    return {"reward_risk": rr, "realized_pnl_pct": pnl, "observations": observations,
            "risk_flags": risk_flags, "context": context}


_PROSE_QUALIFIER = ("This is an educational review of a trade you logged — descriptive context and "
                    "risk framing, not advice about any position.")


def render_prose(analysis, trade):
    """Deterministic natural-language paragraph of an analysis — the always-available path, built
    only from the analysis fields, so it clears both guards by construction."""
    sym = trade.get("symbol") or "this idea"
    rr = analysis.get("reward_risk")
    lead = (f"On {sym}, the plan carries a reward-to-risk of about {rr} to 1."
            if rr is not None else
            f"On {sym}, a reward-to-risk could not be framed from the levels recorded.")
    body = " ".join(analysis.get("observations", []) + analysis.get("risk_flags", [])
                    + analysis.get("context", []))
    return " ".join(x for x in (lead, body, _PROSE_QUALIFIER) if x)


# ------------------------------------------------------------------ pure performance

def summarize_performance(trades, min_sample=PERF_MIN_SAMPLE):
    """Honest personal analytics over the CLOSED trades that carry a realized return. Below the
    sample floor we report counts and say so; win rate, expectancy, and any named edge appear only
    once the sample is real. Each trade dict is expected to carry `realized_pnl_pct` (fraction or
    None), `strategy`, and optionally `rr`."""
    closed = [t for t in trades if t.get("realized_pnl_pct") is not None]
    rets = [t["realized_pnl_pct"] for t in closed]
    n = len(rets)
    wins = [r for r in rets if r > 0]
    losses = [r for r in rets if r < 0]
    rrs = [t["rr"] for t in closed if t.get("rr") is not None]

    out = {
        "n_closed": n, "sufficient": n >= min_sample,
        "wins": len(wins), "losses": len(losses),
        "avg_win": round(sum(wins) / len(wins), 6) if wins else None,
        "avg_loss": round(sum(losses) / len(losses), 6) if losses else None,
        "avg_reward_risk": round(sum(rrs) / len(rrs), 2) if rrs else None,
        "win_rate": None, "expectancy": None, "by_strategy": [], "insights": [],
    }
    if n < min_sample:
        out["note"] = (f"{n} closed trade(s) logged — TradeOS starts reporting win rate and habits at "
                       f"{min_sample} closed trades, so it never calls an edge from a small sample.")
        return out

    out["win_rate"] = round(len(wins) / n, 4)
    out["expectancy"] = round(sum(rets) / n, 6)      # average return per closed trade

    by_strat: dict[str, list[float]] = {}
    for t in closed:
        by_strat.setdefault((t.get("strategy") or "unlabeled").strip().lower() or "unlabeled", []).append(
            t["realized_pnl_pct"])
    for s, rs in sorted(by_strat.items()):
        if len(rs) >= STRAT_MIN_SAMPLE:
            out["by_strategy"].append({"strategy": s, "n": len(rs),
                                       "win_rate": round(sum(1 for r in rs if r > 0) / len(rs), 4),
                                       "avg_return": round(sum(rs) / len(rs), 6)})
    if len(out["by_strategy"]) >= 2:
        best = max(out["by_strategy"], key=lambda x: x["win_rate"])
        worst = min(out["by_strategy"], key=lambda x: x["win_rate"])
        if best["win_rate"] - worst["win_rate"] >= _EDGE_GAP:
            out["insights"].append(
                f"Your recorded win rate is higher on {best['strategy']} "
                f"({round(best['win_rate'] * 100)}%, {best['n']} trades) than on {worst['strategy']} "
                f"({round(worst['win_rate'] * 100)}%, {worst['n']} trades).")
    return out


# ------------------------------------------------------------------ DB: cross-reference, library, cache

def signal_context(conn: psycopg.Connection, entity_id):
    """The most recent smart-money convergence for this issuer, or None. Read-only, tier-agnostic
    context (public SEC-derived signal); shown descriptively, never as a directive."""
    if not entity_id:
        return None
    with conn.cursor() as cur:
        cur.execute("SELECT confidence_bucket, voices, as_of FROM signal_clusters "
                    "WHERE issuer_entity=%s ORDER BY as_of DESC LIMIT 1", (entity_id,))
        r = cur.fetchone()
    return {"bucket": r[0], "voices": r[1], "as_of": r[2].isoformat()} if r else None


def library_links(conn: psycopg.Connection, strategy, asset_class, limit=2):
    """Up to `limit` intelligence-library concepts whose title matches a token of the strategy —
    'teach in the same moment it informs'. Empty when nothing matches (never fabricated)."""
    terms = [t for t in (strategy or "").lower().replace("/", " ").split() if len(t) > 3]
    if not terms:
        return []
    where = " OR ".join(["title ILIKE %s"] * len(terms))
    with conn.cursor() as cur:
        cur.execute(f"SELECT slug, title FROM library_entries WHERE kind='concept' AND ({where}) "
                    f"ORDER BY created_at LIMIT %s", (*[f"%{t}%" for t in terms], limit))
        return [{"slug": s, "title": t} for s, t in cur.fetchall()]


def _material(trade):
    return {k: trade.get(k) for k in ("symbol", "direction", "asset_class", "status", "entry_price",
            "exit_price", "stop_price", "target_price", "size", "size_unit", "timeframe", "strategy",
            "confidence", "opened_on", "closed_on")}


def _input_hash(trade, provider):
    m = {k: (v.isoformat() if isinstance(v, date) else v) for k, v in _material(trade).items()}
    return hashlib.sha256((provider + "|" + json.dumps(m, sort_keys=True, default=str)).encode()).hexdigest()


def _prose(analysis, trade, provider):
    """Return (prose, model_id, used_template). Optional model rephrasing held to the SAME directive
    and numbers guards as the signal explanation, with deterministic fallback on any failure or trip —
    the model can never widen the compliance envelope. Mirrors `explain.base`."""
    if provider == "gemini":
        try:
            from .explain import gemini
            llm = gemini.generate_trade_prose(analysis, trade)
        except Exception as exc:  # missing key / API error -> deterministic
            log.warning("trade prose provider unavailable (%s)", type(exc).__name__)
            llm = None
        if llm:
            allowed = allowed_numbers(analysis, _material(trade), {"_const": [1, 5, 100]})
            if directive_guard(llm) and numbers_guard(llm, allowed):
                return llm, os.environ.get("GEMINI_MODEL", "gemini"), False
            log.warning("trade prose guard tripped; using deterministic prose")
    return render_prose(analysis, trade), "template", True


def build_analysis(conn: psycopg.Connection, trade, provider=None):
    provider = (provider or os.environ.get("EXPLAIN_PROVIDER", "template")).lower()
    analysis = analyze_trade(trade, signal_context(conn, trade.get("entity_id")))
    analysis["learn"] = library_links(conn, trade.get("strategy"), trade.get("asset_class"))
    prose, model_id, used_template = _prose(analysis, trade, provider)
    analysis.update({"prose": prose, "model_id": model_id, "used_template": used_template})
    return analysis


def cached_analysis(conn: psycopg.Connection, trade, provider=None):
    """Analysis with an inputs-hash cache. A genuine model success is cached; a template fallback
    from a model provider is NOT (so a transient outage never poisons the cache — mirrors base.py)."""
    provider = (provider or os.environ.get("EXPLAIN_PROVIDER", "template")).lower()
    h = _input_hash(trade, provider)
    with conn.cursor() as cur:
        cur.execute("SELECT content, input_hash FROM trade_analyses WHERE trade_id=%s", (trade["id"],))
        r = cur.fetchone()
    if r and r[1] == h:
        return {**r[0], "from_cache": True}

    a = build_analysis(conn, trade, provider)
    if not (provider != "template" and a["used_template"]):
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO trade_analyses (trade_id, input_hash, provider, model_id, used_template, content)
                   VALUES (%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (trade_id) DO UPDATE SET input_hash=EXCLUDED.input_hash,
                     provider=EXCLUDED.provider, model_id=EXCLUDED.model_id,
                     used_template=EXCLUDED.used_template, content=EXCLUDED.content, created_at=now()""",
                (trade["id"], h, provider, a["model_id"], a["used_template"], Json(a)))
            conn.commit()
    return {**a, "from_cache": False}
