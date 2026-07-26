"""World context at trade time — the half of a journal that a journal cannot see (Phase 6).

A trading journal records what the trader did. It has no idea what was happening while they did
it, so the only thing it can coach on is the outcome, and coaching on outcomes teaches a trader to
feel good about lucky wins and bad about disciplined losses. That is backwards.

So at the moment a trade is logged, this module freezes the Radar as it stood: which
interpretations were live, ranked by relevance to that reader, and — the load-bearing part —
whether any of them named the same instrument, pointing which way. That single fact turns the
coach from an outcome scorer into a **process** observer. It can now say "eleven of your entries
were made while a live interpretation on that name pointed the other way" — an observation about
how the trader decides, available long before enough closed trades exist to say anything about
whether they are any good.

Three lines this module holds:

  * **The snapshot is written once and never rewritten.** A trade edited a week later must not move
    its own context, or the record drifts toward what the trader now remembers believing — exactly
    the hindsight bias the journal exists to counter.

  * **The system is not the benchmark.** The Ledger publishes a hit rate near four in ten. Framing
    "you traded against a live claim" as a mistake would quietly promote a 41%-accurate machine to
    the arbiter of a human's decision. Every pattern that mentions disagreement carries the
    Ledger's own real number alongside it, so the reader can weigh it correctly.

  * **Constructive, or it does not ship.** A coach that makes someone feel worse after a loss is a
    coach they stop opening, and then it helps nobody. Patterns are phrased as observations with
    their sample size attached, never as verdicts, and the sample floor is enforced rather than
    negotiated.

Nothing here calls a model. Relevance ranking is deterministic (`relevance.py`), and a snapshot
that failed whenever inference was down would leave permanent holes in a point-in-time record.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime

import psycopg
from psycopg.types.json import Json

from . import relevance, trades

log = logging.getLogger("tradeos.journal_context")

SNAPSHOT_LIMIT = 8       # ranked claims frozen onto the trade; the count of live ones is kept separately
MIN_PATTERN_SAMPLE = 5   # below this a behavioural pattern is not stated at all
MIN_COHORT = 5           # per-side floor before two cohorts' recorded results are contrasted
BUSY_NOVELTY = 0.5       # above this the day's live interpretations were genuinely new information


# ------------------------------------------------------------------ pure: reading a claim

# A ticker as it appears inside a claim's asset value. The impact engine does not always write a
# bare symbol — real rows in this database read "AMC Entertainment Holdings Inc. (AMC)" and "$TSLA"
# — so exact matching alone silently misses genuine disagreements, which is the one failure mode
# that matters here: a missed match makes the coach report agreement that was never there.
#
# This is the THIRD ticker-from-prose regex in the package: `ingestion/news_rss.py` and
# `intelligence/analyst.py` carry a byte-identical pair of their own. Deliberately not consolidated
# here — those two parse free-running headline prose and require an exchange qualifier
# ("(NASDAQ: AMC)"), while this parses one short structured field where a bare parenthetical is the
# common form, so a shared helper would have to be the union and would loosen both. If a fourth
# appears, that is the signal to unify all four rather than add to the pile.
_TICKER = re.compile(r"^\$?([A-Z][A-Z.\-]{0,5})$|\(\$?([A-Z][A-Z.\-]{0,5})\)")


def _symbols_named(value: str | None) -> set[str]:
    """The ticker(s) an `affected` asset value can be taken to name. Empty for prose like
    "Treasury bonds", which names no instrument this journal could hold."""
    v = (value or "").strip().upper()
    if not v:
        return set()
    return {g for m in _TICKER.finditer(v) for g in m.groups() if g}


def claims_on_symbol(claims: list[dict], symbol: str | None) -> list[dict]:
    """The live claims that name `symbol` as an affected ASSET, each carrying the direction that
    claim committed to for it.

    Only `kind == "asset"` counts. A claim about the semiconductor sector plainly bears on a
    semiconductor trade, but it did not commit to a direction on *that instrument*, and treating
    it as though it had would let the coach report a disagreement that was never made.
    """
    if not symbol:
        return []
    want = symbol.strip().upper()
    out = []
    for c in claims:
        for a in c.get("affected") or []:
            if a.get("kind") == "asset" and want in _symbols_named(a.get("value")):
                out.append({"claim_id": c.get("id"), "direction": a.get("direction"),
                            "magnitude": a.get("magnitude"), "confidence": c.get("confidence"),
                            "horizon": c.get("horizon"), "headline": c.get("headline"),
                            "named_as": a.get("value"), "mechanism": c.get("mechanism")})
                break               # one row per claim, not per mention
    return out


def alignment(trade_direction: str | None, on_symbol: list[dict]) -> str:
    """Did the live reads on this name point the trader's way? with | against | mixed | none.

    `none` when nothing was live on the instrument — which is not a failing. Most trades are made
    in silence, and the coach says so rather than implying an absence of coverage was a warning.
    """
    if not on_symbol:
        return "none"
    expect = "down" if trade_direction == "short" else "up"
    dirs = {c.get("direction") for c in on_symbol if c.get("direction")}
    if not dirs:
        return "none"
    if dirs == {expect}:
        return "with"
    if expect not in dirs:
        return "against"
    return "mixed"


def _mean(xs: list[float]) -> float | None:
    vals = [float(x) for x in xs if x is not None]
    return round(sum(vals) / len(vals), 4) if vals else None


def summarize(claims: list[dict], trade: dict, as_of: datetime, basis: str = "live",
              limit: int = SNAPSHOT_LIMIT) -> dict:
    """Freeze `claims` (already relevance-ranked, most relevant first) into a trade's context row.

    `n_live` counts everything that was live; only the top `limit` are stored. The count and the
    stored sample are separate numbers because "the Radar had 34 live reads and here are the eight
    that mattered to you" is honest, while silently reporting eight is not.
    """
    on_symbol = claims_on_symbol(claims, trade.get("symbol"))
    kept = claims[:limit]
    return {
        "as_of": as_of,
        "basis": basis,
        "claim_ids": [c["id"] for c in kept if c.get("id") is not None],
        "n_live": len(claims),
        "n_on_symbol": len(on_symbol),
        "alignment": alignment(trade.get("direction"), on_symbol),
        "mean_novelty": _mean([c.get("novelty") for c in claims]),
        "snapshot": {"claims": kept, "on_symbol": on_symbol,
                     "symbol": (trade.get("symbol") or None),
                     "direction": trade.get("direction")},
    }


# ------------------------------------------------------------------ pure: behavioural patterns

def _cohort(rows: list[dict], pred) -> dict:
    """Count and — only where the closed sample is real — the recorded result of a slice."""
    sel = [r for r in rows if pred(r)]
    closed = [r["realized_pnl_pct"] for r in sel if r.get("realized_pnl_pct") is not None]
    n = len(closed)
    return {"n": len(sel), "n_closed": n,
            "win_rate": round(sum(1 for r in closed if r > 0) / n, 4) if n >= MIN_COHORT else None,
            "sufficient": n >= MIN_COHORT}


def behavioural_patterns(rows: list[dict], ledger_hit_rate: float | None = None,
                         min_sample: int = MIN_PATTERN_SAMPLE) -> list[dict]:
    """Process-quality patterns across trades that carry world context.

    Each pattern is {key, headline, detail, count, of, tone}. `tone` is neutral or positive and
    never negative: these are observations about how a trader decides, and the moment one reads as
    an accusation the trader stops opening the page.

    Returns [] below the sample floor rather than a hedged pattern — a tendency named from three
    trades is noise wearing the costume of insight.
    """
    have = [r for r in rows if r.get("alignment")]
    n = len(have)
    if n < min_sample:
        return []

    out: list[dict] = []

    against = _cohort(have, lambda r: r["alignment"] in ("against", "mixed"))
    if against["n"]:
        detail = ("A live interpretation on that name pointed the other way when you entered. "
                  "That is a disagreement, not a mistake")
        if ledger_hit_rate is not None:
            detail += (f" — the Ledger records this system as right on "
                       f"{round(ledger_hit_rate * 100)}% of the calls it has resolved, so it is "
                       f"one read against yours, not a verdict")
        out.append({"key": "entered_against_a_live_read", "count": against["n"], "of": n,
                    "headline": f"{against['n']} of {n} entries went against a live interpretation",
                    "detail": detail + ".", "tone": "neutral",
                    "cohort": against})

    with_ = _cohort(have, lambda r: r["alignment"] == "with")
    if with_["n"]:
        out.append({"key": "entered_with_a_live_read", "count": with_["n"], "of": n,
                    "headline": f"{with_['n']} of {n} entries lined up with a live interpretation",
                    "detail": "You and the impact engine read the same direction on the name at the "
                              "time. Agreement is context, not confirmation.",
                    "tone": "positive", "cohort": with_})

    # Contrast the two only when BOTH closed samples clear the floor. Reporting "your agreeing
    # trades win more" off four trades a side would be the exact small-sample claim the rest of
    # this product refuses to make.
    if with_["sufficient"] and against["sufficient"]:
        gap = with_["win_rate"] - against["win_rate"]
        if abs(gap) >= 0.15:
            better, worse = ("agreed", "disagreed") if gap > 0 else ("disagreed", "agreed")
            out.append({
                "key": "alignment_outcome_gap", "count": with_["n_closed"] + against["n_closed"],
                "of": n, "tone": "neutral",
                "headline": f"Your closed trades resolved better when you {better} with the live read",
                "detail": (f"{round(max(with_['win_rate'], against['win_rate']) * 100)}% of the "
                           f"{better} trades closed positive against "
                           f"{round(min(with_['win_rate'], against['win_rate']) * 100)}% of the "
                           f"{worse} ones. Recorded history of your own trades, not a rule."),
                "cohort": {"with": with_, "against": against}})

    quiet = _cohort(have, lambda r: r.get("mean_novelty") is not None
                    and r["mean_novelty"] < BUSY_NOVELTY)
    busy = _cohort(have, lambda r: r.get("mean_novelty") is not None
                   and r["mean_novelty"] >= BUSY_NOVELTY)
    if busy["n"] and quiet["n"] and busy["n"] + quiet["n"] >= min_sample:
        lean = "days the news was breaking" if busy["n"] > quiet["n"] else "quieter days"
        cnt = max(busy["n"], quiet["n"])
        out.append({"key": "entry_day_novelty", "count": cnt, "of": busy["n"] + quiet["n"],
                    "tone": "neutral",
                    "headline": f"You enter more on {lean}",
                    "detail": (f"{cnt} of {busy['n'] + quiet['n']} entries with context were made "
                               f"on {lean}, measured by how new the live interpretations were. "
                               f"A tendency worth knowing about yourself."),
                    "cohort": {"busy": busy, "quiet": quiet}})

    silent = _cohort(have, lambda r: r["alignment"] == "none")
    if silent["n"] == n:
        out.append({"key": "traded_in_silence", "count": n, "of": n, "tone": "neutral",
                    "headline": f"All {n} entries were made with nothing live on the name",
                    "detail": "No interpretation had committed to a direction on these instruments "
                              "when you entered. These were your own reads, unaccompanied.",
                    "cohort": silent})
    return out


# ------------------------------------------------------------------ DB: capture and read back

_CLAIM_SQL = """
    SELECT c.id, c.created_at, c.mechanism, c.affected, c.horizon, c.confidence, c.model_version,
           e.title, e.source, e.source_url, e.geo, e.category, cl.novelty_score
      FROM claims c
      LEFT JOIN events e ON e.id = c.event_id
      LEFT JOIN event_clusters cl ON cl.id = c.cluster_id
     WHERE c.created_at <= %s
       AND c.created_at + make_interval(days => c.horizon_days) >= %s
  ORDER BY c.created_at DESC
     LIMIT %s
"""
_CLAIM_COLS = ("id", "created_at", "mechanism", "affected", "horizon", "confidence",
               "model_version", "headline", "source", "url", "geo", "category", "novelty")


def live_claims_at(cur, as_of: datetime, limit: int = 200) -> list[dict]:
    """Claims that were live at `as_of` — made on or before it, horizon not yet elapsed.

    The horizon test is what makes this reconstructable after the fact: a claim's own recorded
    created_at and horizon prove it was live then. No judgement is involved, so a snapshot rebuilt
    later is the same set the reader would have seen, only ranked against a newer frame.
    """
    cur.execute(_CLAIM_SQL, (as_of, as_of, limit))
    rows = [dict(zip(_CLAIM_COLS, r, strict=True)) for r in cur.fetchall()]
    for r in rows:
        r["created_at"] = r["created_at"].isoformat()
    return rows


def ranked_for(cur, user_id: int, as_of: datetime, limit: int = 200) -> list[dict]:
    """The live claims at `as_of`, ranked by relevance to this reader — the Radar's own order."""
    profile, exposure, watchlist = relevance.reader_frame(cur, user_id)
    out = []
    for r in live_claims_at(cur, as_of, limit):
        scored = relevance.score(r, profile, exposure, watchlist, r.get("novelty"))
        out.append({**r, **scored, "why_shown": relevance.explain(scored["parts"])})
    out.sort(key=lambda x: x["relevance"], reverse=True)
    return out


def capture(conn: psycopg.Connection, user_id: int, trade: dict, as_of: datetime,
            basis: str = "live") -> dict:
    """Freeze the world context for one trade. Idempotent per trade: the first capture wins.

    ON CONFLICT DO NOTHING rather than DO UPDATE, deliberately. A second capture would mean the
    trade was edited or re-imported, and letting a later write move the context is precisely the
    drift this record exists to prevent.
    """
    with conn.cursor() as cur:
        ctx = summarize(ranked_for(cur, user_id, as_of), trade, as_of, basis)
        cur.execute(
            """INSERT INTO trade_context (trade_id, as_of, basis, claim_ids, n_live, n_on_symbol,
                                          alignment, mean_novelty, snapshot)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (trade_id) DO NOTHING""",
            (trade["id"], ctx["as_of"], ctx["basis"], ctx["claim_ids"], ctx["n_live"],
             ctx["n_on_symbol"], ctx["alignment"], ctx["mean_novelty"], Json(ctx["snapshot"])))
    conn.commit()
    return ctx


def for_trade(conn: psycopg.Connection, trade_id: int) -> dict | None:
    """The frozen context for one trade, or None if it was logged before capture existed."""
    with conn.cursor() as cur:
        cur.execute("""SELECT captured_at, as_of, basis, n_live, n_on_symbol, alignment,
                              mean_novelty, snapshot
                         FROM trade_context WHERE trade_id = %s""", (trade_id,))
        r = cur.fetchone()
    if not r:
        return None
    return {"captured_at": r[0].isoformat(), "as_of": r[1].isoformat(), "basis": r[2],
            "n_live": r[3], "n_on_symbol": r[4], "alignment": r[5],
            "mean_novelty": round(float(r[6]), 3) if r[6] is not None else None,
            **(r[7] or {})}


def across_trades(conn: psycopg.Connection, user_id: int) -> list[dict]:
    """One row per trade of this user's that carries context, joined to its recorded result.

    Object-scoped by construction: the user_id is in the WHERE clause, not applied afterwards.
    """
    with conn.cursor() as cur:
        cur.execute("""SELECT t.id, t.symbol, t.direction, t.status, t.entry_price, t.exit_price,
                              x.alignment, x.mean_novelty, x.n_on_symbol, x.n_live, x.basis
                         FROM trades t JOIN trade_context x ON x.trade_id = t.id
                        WHERE t.user_id = %s
                     ORDER BY t.created_at""", (user_id,))
        rows = cur.fetchall()
    out = []
    for tid, sym, d, status, entry, exit_, align, novelty, n_sym, n_live, basis in rows:
        out.append({"id": tid, "symbol": sym, "direction": d, "status": status,
                    "alignment": align, "n_on_symbol": n_sym, "n_live": n_live, "basis": basis,
                    "mean_novelty": float(novelty) if novelty is not None else None,
                    "realized_pnl_pct": (trades.realized_pnl_pct(entry, exit_, d)
                                         if status == "closed" else None)})
    return out


def backfill(conn: psycopg.Connection, limit: int = 500) -> dict:
    """Reconstruct context for trades logged before capture existed, marked `reconstructed`.

    Honest but weaker than a live capture, and labelled as such everywhere it surfaces: the claims
    are genuinely the ones that were live, but they are ranked against the reader's frame TODAY,
    and a novelty score may have been recomputed since. Never call this on a trade that already
    has a live capture — the INSERT declines to overwrite one.
    """
    with conn.cursor() as cur:
        cur.execute("""SELECT t.id, t.user_id, t.symbol, t.direction, t.created_at
                         FROM trades t LEFT JOIN trade_context x ON x.trade_id = t.id
                        WHERE x.trade_id IS NULL
                     ORDER BY t.created_at LIMIT %s""", (limit,))
        pending = cur.fetchall()
    done, with_claims = 0, 0
    for tid, uid, sym, direction, created in pending:
        ctx = capture(conn, uid, {"id": tid, "symbol": sym, "direction": direction},
                      created, basis="reconstructed")
        done += 1
        with_claims += 1 if ctx["n_live"] else 0
    return {"trades": done, "with_live_claims": with_claims,
            "empty": done - with_claims, "basis": "reconstructed"}
