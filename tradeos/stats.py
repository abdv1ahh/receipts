"""The four statistics a public record is not allowed to quote a number without.

LIFTED OUT OF `ledger.py`, VERBATIM, when the signal plane was deleted. They were written for the
Ledger — the self-scoring record of the interpretation engine — and they are the part of it worth
keeping, because every one of them exists to stop a specific overclaim this project has actually
made in public:

  mean_ci          a point estimate without an interval invites a verdict the sample cannot
                   support, IN BOTH DIRECTIONS. The signal plane reads 43.2% of 412 with -1.18%
                   expectancy, and the 95% interval on that mean is [-2.93%, +0.57%] and SPANS
                   ZERO: no edge is demonstrated either way. It was reported internally as "it
                   does not work", which the sample does not support either.
  proportion_z     what IS significant on that sample is the FREQUENCY — 2.76 standard errors
                   below a coin flip — and the two statistics genuinely disagree because the wins
                   are bigger than the losses. Only one of them is conclusive, and a record that
                   published one without the other would be choosing which.
  sample_needed    how many resolved calls it would take to detect a 1% per-call edge at the
                   measured dispersion. On the signal plane that is 1,268 against 412 held, which
                   is the honest answer to "is this working yet".
  confidence_bucket  the one mapping between a numeric score and low/medium/high, so the
                   calibration table and the seeded house records cannot disagree about what a
                   caller's stated confidence meant.

Pure: no database, no clock, no I/O. `receipts/record.py` imports them rather than reimplementing,
because this product's only asset is that its numbers are the same numbers everywhere and the
fastest way to lose that is a second Wilson interval.
"""
from __future__ import annotations

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
