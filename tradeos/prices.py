"""Prices in, and the one decision about what a number means.

LIFTED OUT OF `ledger.py`, VERBATIM, when the signal plane was deleted.

`price_series` is the only way a price reaches the scorer, and it reads `prices_eod` and nothing
else. `verdict_for` is the one implementation of "does that count as a hit" — the noise floor
applied to an excess return, plus the honest reasons a call cannot be scored at all. Two copies of
either would drift, and the copy that drifted would be the one writing a permanent record.

WHY THE UNSCOREABLE REASONS MATTER MORE THAN THEY LOOK. Four of them, and the split is between
faults in the SUBJECT and faults in OURS. `no_entry_price` and `horizon_open_or_delisted` are the
subject's; `no_benchmark_entry_price` and `no_benchmark_exit_price` are ours. Before that split
existed, `excess_return` returned `no_entry_price` for both, and one missing SPY session
permanently sealed a healthy MSFT call as unscoreable with the note "our price feed for MSFT ends
before this call was published" — while MSFT's series ran ten days past it. A verdict cannot be
taken back, so a reason that blames the wrong side is not a cosmetic defect.
"""
from __future__ import annotations

import math

from .backtest.engine import Series
from .stats import NOISE_FLOOR

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
