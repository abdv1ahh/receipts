"""The Ledger: the system scoring itself, including where it was wrong.

Every claim commits to a direction on named subjects over a stated horizon. When that horizon
elapses, this module measures what actually happened and writes a verdict. The Ledger surface is
then just a read over claims joined to outcomes — there is deliberately no separate "results"
store that could drift from, or flatter, the record it summarises.

Three rules that make the number worth believing:

**Excess return, not raw return.** A claim that said "up" during a week when everything went up
has not demonstrated anything. Subjects are scored against SPY, reusing the point-in-time price
machinery the signal backtest already uses.

**Unscoreable is its own verdict, not a quiet drop.** A claim about a currency or a region has no
price series here. Silently excluding those would let the hit rate be computed over a
self-selected sample — the exact way track records get flattered. They are counted and reported as
unscoreable.

**Misses are first-class.** `recent_misses()` exists so the surface can lead with them. Nobody
else shows theirs, which is precisely why showing ours is worth something.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from psycopg import sql

from .backtest.engine import Series, excess_return

log = logging.getLogger("tradeos.ledger")

# Below this, a move is noise rather than confirmation. A claim saying "up" that produced +0.1%
# excess has not been demonstrated right; calling it a hit would inflate the record.
NOISE_FLOOR = 0.02          # 2% excess vs SPY

CONFIDENCE_BUCKETS = ((0.0, 0.4, "low"), (0.4, 0.7, "medium"), (0.7, 1.01, "high"))


def confidence_bucket(c: float) -> str:
    for lo, hi, name in CONFIDENCE_BUCKETS:
        if lo <= c < hi:
            return name
    return "high"


def verdict_for(direction: str, excess: float | None) -> tuple[str, str | None]:
    """(verdict, note) for one measured subject. Pure.

    `inconclusive` is a real outcome, not a hedge: a claim that said "up" and got +0.3% did not
    move enough to be evidence either way, and counting it as a hit would flatter the record."""
    if excess is None:
        return "unscoreable", "no price series for this subject"
    if abs(excess) < NOISE_FLOOR:
        return "inconclusive", f"moved {excess:+.2%} vs SPY, inside the {NOISE_FLOOR:.0%} noise floor"
    went_up = excess > 0
    predicted_up = direction == "up"
    return ("hit" if went_up == predicted_up else "miss"), None


def _series(conn, symbol: str) -> Series:
    with conn.cursor() as cur:
        cur.execute("SELECT day, close FROM prices_eod WHERE symbol = %s ORDER BY day", (symbol,))
        return Series.from_rows(cur.fetchall())


def measure_claim(conn, claim_id: int, spy: Series | None = None) -> dict:
    """Score one claim, one row per affected subject. Idempotent — re-running replaces the rows.

    Only ever reads prices STRICTLY AFTER the claim was made, which is what makes the resulting
    hit rate mean anything."""
    spy = spy if spy is not None else _series(conn, "SPY")
    with conn.cursor() as cur:
        cur.execute("SELECT created_at, horizon_days, affected FROM claims WHERE id = %s", (claim_id,))
        row = cur.fetchone()
        if not row:
            return {"error": "claim not found"}
        created, horizon_days, affected = row
        if not affected:
            cur.execute("UPDATE claims SET status='unscoreable', resolved_at=now() WHERE id=%s",
                        (claim_id,))
            conn.commit()
            return {"claim_id": claim_id, "status": "unscoreable", "reason": "claim named no subjects"}

        as_of_day = created.date()
        if as_of_day + timedelta(days=horizon_days) > _today(conn):
            return {"claim_id": claim_id, "status": "open", "reason": "horizon has not elapsed"}

        counts = {"hit": 0, "miss": 0, "inconclusive": 0, "unscoreable": 0}
        for item in affected:
            subject = str(item.get("value", "")).upper()
            direction = item.get("direction")
            excess, entry, exit_day = None, None, None
            # Only equity-like subjects have a price series here. A currency or a region is
            # honestly unscoreable rather than quietly dropped.
            if item.get("kind") in ("asset",) and subject:
                sym = _series(conn, subject)
                if sym.days:
                    excess, _why = excess_return(sym, spy, as_of_day, horizon_days)
                    entry = _entry_day(sym, as_of_day)
                    exit_day = _exit_day(sym, entry, horizon_days) if entry else None
            v, note = verdict_for(direction, excess)
            counts[v] += 1
            cur.execute(
                """INSERT INTO claim_outcomes (claim_id, subject, predicted, magnitude, entry_day,
                                               exit_day, excess_return, verdict, note)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (claim_id, subject) DO UPDATE SET
                       entry_day=EXCLUDED.entry_day, exit_day=EXCLUDED.exit_day,
                       excess_return=EXCLUDED.excess_return, verdict=EXCLUDED.verdict,
                       note=EXCLUDED.note, measured_at=now()""",
                (claim_id, subject, direction, item.get("magnitude"), entry, exit_day,
                 excess, v, note))

        scoreable = counts["hit"] + counts["miss"]
        status = "resolved" if scoreable else "unscoreable"
        cur.execute("UPDATE claims SET status=%s, resolved_at=now() WHERE id=%s", (status, claim_id))
    conn.commit()
    return {"claim_id": claim_id, "status": status, **counts}


def _today(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT current_date")
        return cur.fetchone()[0]


def _entry_day(sym: Series, as_of_day):
    from .backtest.engine import entry_day_after
    return entry_day_after(sym, as_of_day)


def _exit_day(sym: Series, entry, horizon_days: int):
    target = entry + timedelta(days=horizon_days)
    later = [d for d in sym.days if d >= target]
    return later[0] if later else None


def measure_due(conn, limit: int = 200) -> dict:
    """Score every open claim whose horizon has elapsed. The scheduler's job."""
    spy = _series(conn, "SPY")
    if not spy.days:
        return {"error": "no SPY prices; run ingest-prices first (SPY is the benchmark)"}
    with conn.cursor() as cur:
        cur.execute(
            """SELECT id FROM claims
                WHERE status = 'open'
                  AND created_at::date + make_interval(days => horizon_days) <= now()
             ORDER BY created_at LIMIT %s""", (limit,))
        ids = [r[0] for r in cur.fetchall()]
    totals = {"measured": 0, "hit": 0, "miss": 0, "inconclusive": 0, "unscoreable": 0}
    for cid in ids:
        out = measure_claim(conn, cid, spy=spy)
        if out.get("status") in ("resolved", "unscoreable"):
            totals["measured"] += 1
            for k in ("hit", "miss", "inconclusive", "unscoreable"):
                totals[k] += out.get(k, 0)
    return totals


# ------------------------------------------------------------------ the Ledger read

def published_rate(conn, min_sample: int = 20) -> float | None:
    """The one headline number — hits over scoreable calls — or None below the sample floor.

    A one-query alternative to reading `summary()["overall"]` for callers that want only the rate.
    It exists because the Journal coach cites this number when it reports a disagreement between
    the trader and a live claim, and the coach must not be able to state a rate the Ledger itself
    would refuse to publish."""
    with conn.cursor() as cur:
        cur.execute("""SELECT count(*) FILTER (WHERE verdict='hit'),
                              count(*) FILTER (WHERE verdict='miss') FROM claim_outcomes""")
        hit, miss = cur.fetchone()
    n = (hit or 0) + (miss or 0)
    return round(hit / n, 3) if n >= min_sample else None


def summary(conn, min_sample: int = 20) -> dict:
    """The whole record: overall, and broken down by category, horizon, source and confidence.

    `sufficient` is reported per breakdown so a 2-of-3 slice is never displayed as "67% accurate".
    That single flag is the difference between an honest ledger and a misleading one."""
    with conn.cursor() as cur:
        cur.execute(
            """SELECT count(*) FILTER (WHERE o.verdict = 'hit'),
                      count(*) FILTER (WHERE o.verdict = 'miss'),
                      count(*) FILTER (WHERE o.verdict = 'inconclusive'),
                      count(*) FILTER (WHERE o.verdict = 'unscoreable'),
                      count(DISTINCT o.claim_id)
                 FROM claim_outcomes o""")
        hit, miss, inconclusive, unscoreable, claims_scored = cur.fetchone()
        cur.execute("SELECT count(*) FROM claims WHERE status = 'open'")
        open_claims = cur.fetchone()[0]

        by = {}
        # `origin` falls back to the model version so signal-plane claims stay separable from
        # model-generated ones. A reader has to be able to ask "how does the MODEL do on its own?"
        # — if the two were pooled under one hit rate, neither number would mean anything.
        for label, expr in (("category", sql.SQL("coalesce(e.category, 'smart-money signal')")),
                            ("horizon", sql.SQL("c.horizon")),
                            ("source", sql.SQL("coalesce(e.source, c.model_version)")),
                            ("origin", sql.SQL("case when c.event_id is null "
                                               "then 'signal plane (backtested)' "
                                               "else 'impact engine (model)' end"))):
            cur.execute(
                sql.SQL("""SELECT {expr} AS k,
                           count(*) FILTER (WHERE o.verdict='hit') AS hits,
                           count(*) FILTER (WHERE o.verdict='miss') AS misses
                      FROM claim_outcomes o
                      JOIN claims c ON c.id = o.claim_id
                      LEFT JOIN events e ON e.id = c.event_id
                     WHERE o.verdict IN ('hit','miss')
                     GROUP BY 1 ORDER BY 2 DESC NULLS LAST""").format(expr=expr))
            by[label] = [_rate(k, h, m, min_sample) for k, h, m in cur.fetchall()]

        # Calibration: when it says 70%, does it land near 70%? This is the honest question, and
        # it is the one a hit rate alone cannot answer.
        cur.execute(
            """SELECT width_bucket(c.confidence, 0, 1, 5) AS b,
                      min(c.confidence), max(c.confidence), avg(c.confidence),
                      count(*) FILTER (WHERE o.verdict='hit'),
                      count(*) FILTER (WHERE o.verdict='miss')
                 FROM claim_outcomes o JOIN claims c ON c.id = o.claim_id
                WHERE o.verdict IN ('hit','miss')
             GROUP BY 1 ORDER BY 1""")
        calibration = []
        for _b, lo, hi, avg_conf, h, m in cur.fetchall():
            n = h + m
            calibration.append({
                "stated_range": [round(float(lo), 2), round(float(hi), 2)],
                "stated_avg": round(float(avg_conf), 3),
                "observed": round(h / n, 3) if n else None,
                "n": n, "sufficient": n >= min_sample,
            })

    scoreable = hit + miss
    return {
        "overall": {"hit": hit, "miss": miss, "inconclusive": inconclusive,
                    "unscoreable": unscoreable, "n": scoreable,
                    "hit_rate": round(hit / scoreable, 3) if scoreable else None,
                    "sufficient": scoreable >= min_sample},
        "claims_scored": claims_scored, "open_claims": open_claims,
        "by": by, "calibration": calibration, "min_sample": min_sample,
        "note": ("Hit rate is measured as excess return versus SPY, so a claim that said 'up' in a "
                 f"week when everything rose is not credited. Moves inside {NOISE_FLOOR:.0%} are "
                 "recorded as inconclusive rather than counted either way. Claims about "
                 "currencies and regions have no price series here and are reported as "
                 "unscoreable rather than dropped from the sample."),
    }


def _rate(key, hits: int, misses: int, min_sample: int) -> dict:
    n = hits + misses
    return {"key": key or "uncategorised", "hits": hits, "misses": misses, "n": n,
            "hit_rate": round(hits / n, 3) if n else None, "sufficient": n >= min_sample}


def recent_misses(conn, limit: int = 10) -> list[dict]:
    """The misses, newest first. A separate function because the surface must be able to lead with
    them rather than bury them — that is the whole marketing argument."""
    with conn.cursor() as cur:
        cur.execute(
            """SELECT o.claim_id, o.subject, o.predicted, o.excess_return, o.exit_day,
                      c.confidence, c.horizon, c.mechanism, e.title, e.source_url
                 FROM claim_outcomes o
                 JOIN claims c ON c.id = o.claim_id
                 LEFT JOIN events e ON e.id = c.event_id
                WHERE o.verdict = 'miss'
             ORDER BY o.measured_at DESC LIMIT %s""", (limit,))
        cols = ("claim_id", "subject", "predicted", "excess_return", "exit_day", "confidence",
                "horizon", "mechanism", "headline", "url")
        return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]
