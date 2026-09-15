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
import math
from datetime import timedelta

from psycopg import sql

from .backtest.engine import Series, excess_return

log = logging.getLogger("tradeos.ledger")

# Below this, a move is noise rather than confirmation. A claim saying "up" that produced +0.1%
# excess has not been demonstrated right; calling it a hit would inflate the record.
NOISE_FLOOR = 0.02          # 2% excess vs SPY

CONFIDENCE_BUCKETS = ((0.0, 0.4, "low"), (0.4, 0.7, "medium"), (0.7, 1.01, "high"))


# ------------------------------------------------------------------ is the number distinguishable
#
# A track record that publishes a point estimate and no interval invites the wrong conclusion in
# BOTH directions, and this ledger did exactly that. 282 calls at a 40.8% hit rate looks damning;
# the mean excess return behind it is -1.31% with a 95% interval of [-3.31%, +0.68%], which
# INCLUDES ZERO. The honest reading is "no edge demonstrated either way", not "it loses money" —
# and the difference between those two sentences is the difference between an instrument and a
# vanity metric. Both are computed here, pure, so they can be tested without a database.


def mean_ci(values: list[float], z: float = 1.96) -> dict:
    """Mean of a sample with its confidence interval, and whether it clears zero.

    `z` defaults to 95%. Returns `significant: False` whenever the interval spans zero, which is
    the whole point: an average that cannot be distinguished from no effect must not be reported
    as an effect."""
    n = len(values)
    if n < 2:
        return {"n": n, "mean": values[0] if n else None, "lo": None, "hi": None,
                "significant": False, "sd": None}
    mean = sum(values) / n
    var = sum((v - mean) ** 2 for v in values) / (n - 1)
    sd = var ** 0.5
    half = z * sd / (n ** 0.5)
    lo, hi = mean - half, mean + half
    return {"n": n, "mean": round(mean, 5), "lo": round(lo, 5), "hi": round(hi, 5),
            "sd": round(sd, 5), "significant": lo > 0 or hi < 0}


def proportion_z(successes: int, n: int, p0: float = 0.5) -> float | None:
    """How many standard errors a hit rate sits from chance. None when there is no sample.

    Reported alongside the rate because "41%" means nothing without knowing whether 41% on this
    many calls is distinguishable from a coin."""
    if n <= 0:
        return None
    se = (p0 * (1 - p0) / n) ** 0.5
    return round((successes / n - p0) / se, 2) if se else None


def sample_needed(sd: float, edge: float, z: float = 1.96) -> int | None:
    """How many resolved calls it would take to detect an edge of `edge` at this volatility.

    This is the number that turns "we do not know yet" from an excuse into a plan. At the measured
    18% dispersion, detecting a 1% per-call edge needs roughly 1,300 calls."""
    if not sd or not edge:
        return None
    return int(round((z * sd / abs(edge)) ** 2))


def confidence_bucket(c: float) -> str:
    for lo, hi, name in CONFIDENCE_BUCKETS:
        if lo <= c < hi:
            return name
    return "high"


# Why a subject could not be scored, in the reader's words. `excess_return` already distinguishes
# these; the Ledger used to bind its answer to `_why` and throw it away, so all 273 unscoreable
# rows carried the same sentence and two completely different problems looked like one.
#
# The distinction is not cosmetic. "no price series" says the subject is unpriceable and always
# will be — a region, a currency, the word "tourism". "the price feed ends before the claim" says
# the subject is perfectly scoreable and the FEED is stale, which is a fixable operational fault
# and was invisible for as long as the note lied about it. BA and SPY, with 1,293 price rows each,
# were both filed under "no price series".
# The last two are OURS, not the subject's, and the wording has to make that unmistakable: the
# Receipts plane seals permanently on some of these reasons and refuses to seal on others, and it
# decides which by asking whose gap it is. A benchmark sentence that mentioned only the subject is
# how a healthy symbol came to carry a permanent `unscoreable`.
UNSCOREABLE_REASONS = {
    "not_priceable_kind": "{subject} is a {kind}, which has no price series here",
    "no_symbol": "no price history for this subject",
    "no_entry_price": "the price feed ends before this claim was made, so there is no entry price",
    "horizon_open_or_delisted": "the price feed ends before the horizon closed",
    "no_benchmark_entry_price": "our benchmark series is missing the entry session, so there is "
                               "nothing to measure this against yet. That is a gap on our side",
    "no_benchmark_exit_price": "our benchmark series does not reach the end of the horizon yet. "
                              "That is a gap on our side",
}
DEFAULT_UNSCOREABLE = "no price series for this subject"


def truncated_pct(value: float, places: int = 2) -> str:
    """`value` as a percentage, rounded TOWARD ZERO rather than to nearest.

    The one formatter for a percentage that appears in the same sentence as a threshold. A move of
    0.019959 printed with `{:+.2%}` reads "+2.00%", and the note around it said "inside the 2%
    noise floor" -- a sentence contradicting itself, on a product whose whole pitch is that its
    numbers mean exactly what they say. Truncating toward zero can never make a move print as
    larger than it was, so the statement stays true at the boundary. The cost is understating our
    own measurement by under 0.01 of a percentage point, in the only direction that is safe.

    One copy, used by both planes. `pct` lived as four near-identical copies in this codebase once
    and the fourth one omitted the x100 (CLAUDE.md 0b2).
    """
    scale = 10 ** (places + 2)
    return f"{math.trunc(value * scale) / scale:+.{places}%}"


def verdict_for(direction: str, excess: float | None,
                reason: str | None = None) -> tuple[str, str | None]:
    """(verdict, note) for one measured subject. Pure.

    `inconclusive` is a real outcome, not a hedge: a claim that said "up" and got +0.3% did not
    move enough to be evidence either way, and counting it as a hit would flatter the record.

    `reason` is the second element of `excess_return`, or one of the keys above when the lookup
    never got that far. It is what makes the unscoreable note TRUE rather than merely plausible;
    without it every unscoreable row says the same thing and the real fault stays hidden."""
    if excess is None:
        return "unscoreable", (reason or DEFAULT_UNSCOREABLE)
    # STRICT `<`. A move that REACHES the floor has cleared it, so exactly +2.000000% is a hit.
    # `docs/receipts_gap_analysis.md` stated this as `<=`; the document was wrong and was corrected.
    if abs(excess) < NOISE_FLOOR:
        return "inconclusive", (f"moved {truncated_pct(excess)} vs SPY, inside the "
                                f"{NOISE_FLOOR:.0%} noise floor")
    went_up = excess > 0
    predicted_up = direction == "up"
    return ("hit" if went_up == predicted_up else "miss"), None


def price_series(conn, symbol: str) -> Series:
    """Every daily close this database holds for one symbol, oldest first.

    Public because Receipts scores against the same prices this Ledger does, and two loaders would
    eventually disagree about what "the price series" means. One definition, both planes.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT day, close FROM prices_eod WHERE symbol = %s ORDER BY day", (symbol,))
        return Series.from_rows(cur.fetchall())


def measure_claim(conn, claim_id: int, spy: Series | None = None) -> dict:
    """Score one claim, one row per affected subject. Idempotent — re-running replaces the rows.

    Only ever reads prices STRICTLY AFTER the claim was made, which is what makes the resulting
    hit rate mean anything."""
    spy = spy if spy is not None else price_series(conn, "SPY")
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
            kind = item.get("kind")
            excess, entry, exit_day = None, None, None
            # Only equity-like subjects have a price series here. A currency or a region is
            # honestly unscoreable rather than quietly dropped — but it must say WHICH of these it
            # is. Four different failures used to arrive here wearing the same sentence.
            if kind not in ("asset",) or not subject:
                why = UNSCOREABLE_REASONS["not_priceable_kind"].format(
                    subject=subject or "an unnamed subject", kind=kind or "non-asset subject")
            else:
                sym = price_series(conn, subject)
                if not sym.days:
                    why = UNSCOREABLE_REASONS["no_symbol"]
                else:
                    excess, why = excess_return(sym, spy, as_of_day, horizon_days)
                    why = UNSCOREABLE_REASONS.get(why, why)
                    entry = _entry_day(sym, as_of_day)
                    exit_day = _exit_day(sym, entry, horizon_days) if entry else None
            v, note = verdict_for(direction, excess, why)
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
    spy = price_series(conn, "SPY")
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

        # Open work split the same way `by.origin` splits resolved work. Without this the surfaces
        # can only say "80 open" and cannot say WHOSE — which is how the marketing site came to
        # present the signal plane's resolved record as though it were the impact engine's. The
        # engine's record being empty is a fact about the product and has to be sayable.
        cur.execute(
            """SELECT CASE WHEN event_id IS NULL THEN 'signal plane (backtested)'
                           ELSE 'impact engine (model)' END AS origin,
                      count(*) FILTER (WHERE status = 'open')     AS open,
                      count(*) FILTER (WHERE status = 'resolved') AS resolved
                 FROM claims GROUP BY 1""")
        open_by_origin = [{"key": k, "open": o, "resolved": r} for k, o, r in cur.fetchall()]

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

        # Magnitude. A hit rate on its own cannot tell you whether a record is any good, in EITHER
        # direction: 40% right with winners twice the size of losers is a good record, and 60%
        # right with tiny winners and large losers is a bad one. This is the number that settles
        # it, and leaving it out is how a hit rate becomes misleading while staying true.
        #
        # `expectancy` is the average excess return of FOLLOWING every scored call — the direction
        # it named, against SPY, over its own horizon. It is the closest thing here to "what would
        # this have been worth", and it is reported whichever way it points.
        cur.execute(
            """SELECT avg(o.excess_return) FILTER (WHERE o.verdict='hit'),
                      avg(o.excess_return) FILTER (WHERE o.verdict='miss')
                 FROM claim_outcomes o
                WHERE o.verdict IN ('hit','miss') AND o.excess_return IS NOT NULL""")
        avg_hit, avg_miss = cur.fetchone()

        # Every per-call return, so the interval can be computed rather than only the average.
        cur.execute(
            """SELECT CASE WHEN o.predicted='up' THEN o.excess_return ELSE -o.excess_return END
                 FROM claim_outcomes o
                WHERE o.verdict IN ('hit','miss') AND o.excess_return IS NOT NULL""")
        followed = [float(r[0]) for r in cur.fetchall()]
        ci = mean_ci(followed)
        magnitude = {
            "avg_excess_on_hits": round(float(avg_hit), 4) if avg_hit is not None else None,
            "avg_excess_on_misses": round(float(avg_miss), 4) if avg_miss is not None else None,
            "expectancy": ci["mean"],
            # The interval is the point. A -1.3% average whose interval spans zero is "no edge
            # shown", not "it loses money", and publishing the first without the second is how a
            # record misleads while every figure in it is true.
            "expectancy_ci": [ci["lo"], ci["hi"]],
            "expectancy_significant": ci["significant"],
            "expectancy_sd": ci["sd"],
            # Below chance on frequency is a separate question from below zero on return, and the
            # two genuinely disagree here: these names went down more often, but went up by more.
            "hit_rate_z": proportion_z(hit, scoreable) if (scoreable := hit + miss) else None,
            # What it would take to actually know, at the dispersion actually measured.
            "sample_for_1pct_edge": sample_needed(ci["sd"] or 0, 0.01),
        }

    scoreable = hit + miss
    return {
        "overall": {"hit": hit, "miss": miss, "inconclusive": inconclusive,
                    "unscoreable": unscoreable, "n": scoreable,
                    "hit_rate": round(hit / scoreable, 3) if scoreable else None,
                    "sufficient": scoreable >= min_sample,
                    **magnitude},
        "claims_scored": claims_scored, "open_claims": open_claims,
        "open_by_origin": open_by_origin,
        "by": by, "calibration": calibration, "min_sample": min_sample,
        "note": ("Hit rate is measured as excess return versus SPY, so a claim that said 'up' in a "
                 f"week when everything rose is not credited. Moves inside {NOISE_FLOOR:.0%} are "
                 "recorded as inconclusive rather than counted either way. Claims about "
                 "currencies and regions have no price series here and are reported as "
                 "unscoreable rather than dropped from the sample. `expectancy` is the average "
                 "excess return of following every scored call; a hit rate without it can be "
                 "flattering or damning for the wrong reason, because it counts calls without "
                 "weighing them."),
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
