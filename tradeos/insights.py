"""Advanced journal intelligence (Slice L): a similar-trade finder, a position scenario simulator,
and an auto journal report. All three operate on the user's OWN journal (object-scoped) and stay on
the right side of the same line the rest of the product holds:

  * The similar-trade finder is DESCRIPTIVE history of the user's own comparable setups — "of your
    trades like this one, here's how they resolved" — with the same small-sample honesty as the
    performance summary (no win rate below the floor). It is not a prediction about the open trade.
  * The scenario simulator is pure ARITHMETIC — P&L, R-multiple, and account-risk across price points
    the user names (target, stop, fixed moves). It never assigns a probability to an outcome or says
    what will happen; a signal base-rate overlay, when present, is labelled a historical base rate for
    that signal bucket, explicitly "not a forecast for this trade".
  * The auto journal report AGGREGATES real journal facts (performance + recurring risk-management
    habits) and, optionally, has the model phrase them — held to the SAME directive + numbers guards as
    every other model path, with a deterministic fallback, so it can teach but never advise.

Pure functions first (similarity, cohort summary, simulation, habit aggregation, deterministic report
prose); the guarded/DB layer (model rephrasing, calibration overlay, cached report) follows.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os

import psycopg
from psycopg.types.json import Json

from . import trades
from .explain.guards import allowed_numbers, directive_guard, numbers_guard

log = logging.getLogger("tradeos.insights")

SIMILAR_MIN_SCORE = 0.45     # below this a candidate isn't "like this one" enough to show
SIMILAR_LIMIT = 6


# ------------------------------------------------------------------ pure: similar-trade finder

def _rr_band(rr):
    """Coarse reward:risk band so 2.0 and 2.2 count as the same kind of setup (None if unframed)."""
    if rr is None:
        return None
    return "sub1" if rr < 1 else "1to2" if rr < 2 else "2to3" if rr < 3 else "3plus"


def _strategy_tokens(strategy):
    return {t for t in (strategy or "").lower().replace("/", " ").split() if len(t) > 2}


def similarity(a: dict, b: dict) -> float:
    """0..1 similarity of trade `b` to target `a`, from the setup fields a trader would compare:
    asset class, direction, strategy words, reward:risk band, and timeframe. Weighted, deterministic,
    and symmetric — no outcome field feeds in (so it can't just cluster winners)."""
    score = 0.0
    if a.get("asset_class") and a.get("asset_class") == b.get("asset_class"):
        score += 0.25
    if a.get("direction") and a.get("direction") == b.get("direction"):
        score += 0.20
    ta, tb = _strategy_tokens(a.get("strategy")), _strategy_tokens(b.get("strategy"))
    if ta and tb:
        score += 0.30 * (len(ta & tb) / len(ta | tb))     # Jaccard on strategy words
    ra, rb = _rr_band(a.get("reward_risk")), _rr_band(b.get("reward_risk"))
    if ra and rb and ra == rb:
        score += 0.15
    if a.get("timeframe") and a.get("timeframe") == b.get("timeframe"):
        score += 0.10
    return round(score, 4)


def find_similar(target: dict, candidates: list[dict], limit: int = SIMILAR_LIMIT,
                 min_score: float = SIMILAR_MIN_SCORE) -> list[dict]:
    """Rank the candidate trades by similarity to `target`, excluding the target itself and anything
    below the floor. Each candidate should carry a `reward_risk` (see trades.reward_risk)."""
    scored = []
    for c in candidates:
        if c.get("id") == target.get("id"):
            continue
        s = similarity(target, c)
        if s >= min_score:
            scored.append({**c, "similarity": s})
    scored.sort(key=lambda x: (x["similarity"], x.get("id") or 0), reverse=True)
    return scored[:limit]


def summarize_cohort(similar: list[dict]) -> dict:
    """Honest outcome summary of a cohort of similar trades, reusing the performance floor: below the
    sample floor it reports counts only and says so, never a win rate inferred from a handful."""
    summary = trades.summarize_performance(similar)
    n = summary["n_closed"]
    if not similar:
        line = "No comparable trades in your journal yet — this is a new kind of setup for you."
    elif summary["sufficient"]:
        wr = round(summary["win_rate"] * 100)
        line = (f"Across {n} closed trades like this one in your journal, the recorded win rate is "
                f"{wr}%. Descriptive history of your own trades, not a prediction about this one.")
    else:
        line = (f"{n} closed trade(s) like this one so far — too few for TradeOS to state a win rate "
                f"(it names a rate only at {trades.PERF_MIN_SAMPLE}). Context, not a prediction.")
    return {"n_similar": len(similar), "summary": summary, "line": line}


# ------------------------------------------------------------------ pure: scenario simulator

def _fixed_moves(entry):
    return [("−10%", round(entry * 0.90, 4)), ("−5%", round(entry * 0.95, 4)),
            ("+5%", round(entry * 1.05, 4)), ("+10%", round(entry * 1.10, 4))]


def _leg(entry, stop, price, direction, size, size_unit):
    """One scenario row at `price`: signed return %, R-multiple vs the recorded risk, and $ P&L for a
    share-denominated size. Pure arithmetic — no probability, no forecast."""
    pnl_pct = trades.realized_pnl_pct(entry, price, direction)
    per_share = (price - entry) if direction == "long" else (entry - price)
    risk_per_share = None
    if stop is not None:
        risk_per_share = (entry - stop) if direction == "long" else (stop - entry)
    r_mult = round(per_share / risk_per_share, 2) if (risk_per_share and risk_per_share > 0) else None
    amount = round(per_share * size, 2) if (size and size_unit == "shares") else None
    return {"price": round(price, 4), "return_pct": round(pnl_pct * 100, 2) if pnl_pct is not None else None,
            "r_multiple": r_mult, "pnl_amount": amount}


def simulate(trade: dict, account_size: float | None = None) -> dict:
    """Deterministic what-if grid for a position from its recorded levels. Returns scenarios at the
    stop, the target, and fixed ±5/10% moves, plus the planned reward:risk, distances to stop/target,
    and — if an account size and a share size are given — the share of the account risked to the stop.
    Never a probability or a claim about what price will do."""
    entry = trade.get("entry_price")
    d = trade.get("direction", "long")
    stop, target = trade.get("stop_price"), trade.get("target_price")
    size, size_unit = trade.get("size"), trade.get("size_unit", "shares")
    if not entry:
        return {"ok": False, "reason": "An entry price is needed to simulate outcomes."}

    rows = []
    if stop is not None:
        rows.append({"label": "stop hit", **_leg(entry, stop, stop, d, size, size_unit)})
    for label, price in _fixed_moves(entry):
        rows.append({"label": label, **_leg(entry, stop, price, d, size, size_unit)})
    if target is not None:
        rows.append({"label": "target hit", **_leg(entry, stop, target, d, size, size_unit)})
    rows.sort(key=lambda r: r["price"])

    rr = trades.reward_risk(entry, stop, target, d)
    dist_stop = round(abs(entry - stop) / entry * 100, 2) if stop is not None else None
    dist_target = round(abs(target - entry) / entry * 100, 2) if target is not None else None
    account_risk_pct = None
    if account_size and size and size_unit == "shares" and stop is not None:
        risk_amt = abs(entry - stop) * size
        account_risk_pct = round(risk_amt / account_size * 100, 2) if account_size > 0 else None

    notes = []
    if stop is None:
        notes.append("No stop recorded — downside and R-multiples can't be framed. Record a stop to "
                     "see account risk.")
    if account_risk_pct is not None and account_risk_pct > 2:
        notes.append(f"This idea risks about {account_risk_pct}% of the account to the stop; many "
                     f"trading plans cap single-trade risk near 1–2% — a framing point, not advice.")
    return {"ok": True, "entry": round(entry, 4), "direction": d, "reward_risk": rr,
            "distance_to_stop_pct": dist_stop, "distance_to_target_pct": dist_target,
            "account_risk_pct": account_risk_pct, "scenarios": rows, "notes": notes}


# ------------------------------------------------------------------ pure: auto journal report

_HABIT_RULES = [
    ("no_stop", "trades logged with no stop level", lambda a: "No stop level was recorded" in " ".join(a["risk_flags"])),
    ("rr_below_1", "trades with a planned reward:risk below 1", lambda a: a.get("reward_risk") is not None and a["reward_risk"] < 1),
    ("timeframe_drift", "short-timeframe trades held longer than planned", lambda a: any("the plan " in f and "diverged" in f for f in a["risk_flags"])),
    ("high_conv_loss", "high-conviction trades that were recorded losses", lambda a: any("high conviction" in o and "loss" in o for o in a["observations"])),
]


def aggregate_habits(analyses: list[dict]) -> list[dict]:
    """Tally recurring risk-management patterns across per-trade analyses (from trades.analyze_trade),
    so the report speaks to habits, not a single trade. Only patterns that actually occur are returned."""
    out = []
    total = len(analyses)
    for key, label, pred in _HABIT_RULES:
        n = sum(1 for a in analyses if pred(a))
        if n:
            out.append({"key": key, "label": label, "count": n, "of": total})
    return out


def build_report(perf: dict, habits: list[dict], n_total: int) -> dict:
    """Structured, all-real-numbers journal report payload the prose is rendered from."""
    return {"n_total": n_total, "n_closed": perf.get("n_closed", 0), "sufficient": perf.get("sufficient"),
            "win_rate": perf.get("win_rate"), "expectancy": perf.get("expectancy"),
            "avg_reward_risk": perf.get("avg_reward_risk"), "by_strategy": perf.get("by_strategy", []),
            "performance_insights": perf.get("insights", []), "habits": habits,
            "min_sample": trades.PERF_MIN_SAMPLE}   # the floor is a real figure the prose may cite


def render_report(report: dict) -> str:
    """Deterministic report prose — the always-available path, built only from the report fields so it
    clears both guards by construction."""
    n, nc = report["n_total"], report["n_closed"]
    parts = [f"Your journal holds {n} logged trade(s), {nc} of them closed with a recorded result."]
    if report.get("sufficient"):
        wr = round(report["win_rate"] * 100)
        parts.append(f"Across the closed trades the recorded win rate is {wr}%.")
        for ins in report.get("performance_insights", []):
            parts.append(ins)
    else:
        parts.append(f"That is below the {report.get('min_sample', trades.PERF_MIN_SAMPLE)}-trade floor "
                     f"TradeOS needs before it reports a win rate, so this stays with counts and habits "
                     f"rather than an edge.")
    for h in report.get("habits", []):
        parts.append(f"{h['count']} of {h['of']} — {h['label']}.")
    parts.append("This is an educational summary of trades you logged — patterns and risk framing, "
                 "not advice about any position.")
    return " ".join(parts)


# ------------------------------------------------------------------ guarded model rephrase

def _report_prose(report: dict, provider: str):
    """Return (prose, model_id, used_template). Optional model rephrasing held to the SAME directive
    and numbers guards as every other model path, with deterministic fallback (mirrors trades._prose)."""
    if provider in ("gemini", "openai"):
        try:
            from .explain import gemini
            llm = gemini.generate_journal_report(report)
        except Exception as exc:
            log.warning("journal report provider unavailable (%s)", type(exc).__name__)
            llm = None
        if llm:
            allowed = allowed_numbers(report, {"_const": [1, 2, 5, 100]})
            if directive_guard(llm) and numbers_guard(llm, allowed):
                return llm, (os.environ.get("OPENAI_MODEL", "openai") if provider == "openai"
                             else os.environ.get("GEMINI_MODEL", "gemini")), False
            log.warning("journal report guard tripped; using deterministic prose")
    return render_report(report), "template", True


# ------------------------------------------------------------------ DB layer

def similar_for_trade(conn: psycopg.Connection, target: dict, user_id: int) -> dict:
    """The user's own trades most like `target`, with an honest cohort outcome. Object-scoped: only
    the requesting user's journal is searched."""
    with conn.cursor() as cur:
        cur.execute("SELECT id, symbol, direction, asset_class, status, strategy, timeframe, "
                    "entry_price, exit_price, stop_price, target_price FROM trades WHERE user_id=%s",
                    (user_id,))
        cands = []
        for r in cur.fetchall():
            d = r[2]
            cands.append({"id": r[0], "symbol": r[1], "direction": d, "asset_class": r[3], "status": r[4],
                          "strategy": r[5], "timeframe": r[6],
                          "reward_risk": trades.reward_risk(r[7], r[9], r[10], d),
                          "realized_pnl_pct": trades.realized_pnl_pct(r[7], r[8], d) if r[4] == "closed" else None,
                          "rr": trades.reward_risk(r[7], r[9], r[10], d)})
    similar = find_similar(target, cands)
    cohort = summarize_cohort(similar)
    trimmed = [{"id": s["id"], "symbol": s["symbol"], "direction": s["direction"], "status": s["status"],
                "strategy": s["strategy"], "reward_risk": s["reward_risk"],
                "realized_pnl_pct": s["realized_pnl_pct"], "similarity": s["similarity"]} for s in similar]
    return {"similar": trimmed, **cohort}


def _bucket_base_rate(conn: psycopg.Connection, bucket: str | None, horizon: int = 90):
    """The backtested base rate for a signal bucket at a horizon, or None if unavailable/insufficient.
    Honest: an insufficient sample returns None (never a made-up rate)."""
    if not bucket:
        return None
    try:
        from .backtest.run import compute_calibration
        cal = compute_calibration(conn)
        b = cal.get("per_bucket", {}).get(bucket, {}).get(str(horizon))
    except Exception:
        return None
    if not b or not b.get("sufficient"):
        return None
    return {"bucket": bucket, "horizon": horizon, "hit_rate_pct": round(b["hit_rate"] * 100),
            "episodes": b.get("episodes"), "sample_start_year": b.get("sample_start_year")}


def simulate_with_context(conn: psycopg.Connection, trade: dict, account_size, entity_id) -> dict:
    """simulate() plus, when the symbol maps to a real convergence signal, that signal's descriptive
    context and its backtested base rate — labelled a historical base rate, not a forecast."""
    sim = simulate(trade, account_size)
    if sim.get("ok") and entity_id:
        sig = trades.signal_context(conn, entity_id)
        if sig:
            sim["signal"] = sig
            sim["base_rate"] = _bucket_base_rate(conn, sig.get("bucket"))
    return sim


def _journal_hash(rows, provider):
    """Inputs-hash over the journal's (id, updated_at) pairs + provider, so the cached report
    regenerates exactly when a trade is added/edited/removed or the provider changes."""
    material = sorted((r[0], r[1].isoformat() if r[1] else None) for r in rows)
    return hashlib.sha256((provider + "|" + json.dumps(material)).encode()).hexdigest()


def journal_report(conn: psycopg.Connection, user_id: int, provider: str | None = None) -> dict:
    """Aggregate the user's whole journal into an honest report and (optionally) have the model phrase
    it — guarded, with a deterministic fallback, cached by an inputs-hash so it doesn't re-spend the
    LLM quota until the journal changes."""
    provider = (provider or os.environ.get("EXPLAIN_PROVIDER", "template")).lower()
    with conn.cursor() as cur:
        cur.execute("SELECT id, updated_at FROM trades WHERE user_id=%s", (user_id,))
        idrows = cur.fetchall()
    h = _journal_hash(idrows, provider)
    with conn.cursor() as cur:
        cur.execute("SELECT content, input_hash FROM journal_reports WHERE user_id=%s", (user_id,))
        cached = cur.fetchone()
    if cached and cached[1] == h:
        return {**cached[0], "from_cache": True}

    with conn.cursor() as cur:
        cur.execute("SELECT direction, status, entry_price, exit_price, stop_price, target_price, "
                    "strategy, symbol, size, size_unit, confidence, timeframe, opened_on, closed_on "
                    "FROM trades WHERE user_id=%s", (user_id,))
        raw = cur.fetchall()
    perf_rows, analyses = [], []
    for (d, status, e, ex, st, tg, strat, sym, size, unit, conf, tf, opened, closed) in raw:
        perf_rows.append({"strategy": strat, "rr": trades.reward_risk(e, st, tg, d),
                          "realized_pnl_pct": trades.realized_pnl_pct(e, ex, d) if status == "closed" else None})
        analyses.append(trades.analyze_trade(
            {"direction": d, "status": status, "entry_price": e, "exit_price": ex, "stop_price": st,
             "target_price": tg, "strategy": strat, "symbol": sym, "size": size, "size_unit": unit,
             "confidence": conf, "timeframe": tf, "opened_on": opened, "closed_on": closed}))
    perf = trades.summarize_performance(perf_rows)
    report = build_report(perf, aggregate_habits(analyses), len(raw))
    prose, model_id, used_template = _report_prose(report, provider)
    report.update({"prose": prose, "model_id": model_id, "used_template": used_template})

    if not (provider != "template" and used_template):   # don't cache a transient model outage
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO journal_reports (user_id, input_hash, provider, model_id, used_template, content)
                   VALUES (%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (user_id) DO UPDATE SET input_hash=EXCLUDED.input_hash,
                     provider=EXCLUDED.provider, model_id=EXCLUDED.model_id,
                     used_template=EXCLUDED.used_template, content=EXCLUDED.content, created_at=now()""",
                (user_id, h, provider, model_id, used_template, Json(report)))
            conn.commit()
    return {**report, "from_cache": False}
