"""Routine vs opportunistic insider classification (Cohen, Malloy & Pomorski 2012).

WHY THIS EXISTS. Every cluster this repository has ever published blends Form 4 insider
activity with 13F institutional holdings and 13D/G stakes, because `convergence`'s publish
gate is `min_source_classes: 2` — a pure-insider cluster is unreachable by construction
(`docs/analysis/signal_edge.md`, cut (a)). The academic result the product rests on concerns
**pure Form 4 open-market purchases**, so it had never actually been tested here. This module
is the first half of testing it; `convergence.py`'s `insider_purchases_only` /
`exclude_routine_from_gate` params are the second.

THE RULE, and its citation.

    Cohen, L., Malloy, C. & Pomorski, L. (2012). "Decoding Inside Information."
    Journal of Finance 67(3), 1009-1043.

CMP split insiders into two groups and find that the split is the whole result: routine
traders predict nothing, while opportunistic traders earned roughly 82bps per month in
abnormal returns. An insider is ROUTINE in a firm if, looking back, they placed a trade in
the same calendar month in each of the three preceding years — a January buyer every January
is running a diversification or compensation schedule, not acting on information. Everyone
else with enough history to judge is OPPORTUNISTIC.

Supporting results this classification is meant to be read against:
  * Lakonishok, J. & Lee, I. (2001), Review of Financial Studies 14, 79-111 — the signal
    strengthens when several insiders buy at once. (Tested as cut (b).)
  * Jeng, L., Metrick, A. & Zeckhauser, R. (2003), Review of Economics and Statistics 85,
    453-471 — purchases carry signal, sales do not. (Already honoured: `insider_sale` has
    scored 0.0 since v1, decision #21.)

DELIBERATE DEVIATIONS FROM THE PAPER, each with its reason:

1. **Per trade, not per insider-year.** CMP assign a trader a label for a firm-year. This
   classifies one trade at its own date, because the convergence engine scores events, not
   traders, and a label attached to a trade is the one a point-in-time replay can use without
   leaking a year's worth of hindsight into a single day's cluster.

2. **Prior history counts EVERY transaction code, while only code-P purchases are scored.**
   CMP establish the routine *pattern* from the insider's trading calendar as a whole; a
   sell-every-March insider is just as scheduled as a buy-every-March one. Passing only
   purchases as history would mislabel scheduled sellers as opportunistic. The caller is
   therefore expected to pass the insider's full trade history in that issuer.

3. **"Three years of prior history" is measured in calendar months, not 1,095 days.** The
   test itself is a calendar-month test, so the depth check has to use the same units or the
   two disagree: an insider whose earliest trade is 2023-03-28, classified on 2026-03-20, has
   1,069 days of history but does hold the (Y-3, March) slot the rule asks about. Days would
   call that UNCLASSIFIED while the month test called it ROUTINE. Months are consistent.

4. **10b5-1 plan flags are NOT used, because this database does not have them.** CMP's later
   literature separates scheduled trades using the plan indicator. `ingestion/form4.py` does
   not parse one and `insider_transactions` has no column for it; the SEC only added an
   explicit checkbox to Form 4 in late 2022 (adopting release 33-11138), and before that the
   fact lives in free-text footnotes when it is disclosed at all. Inferring it would be
   fabrication. It is reported as a data limitation instead — see
   `docs/analysis/signal_edge_v5.md`.

POINT-IN-TIME DISCIPLINE. This function is pure and knows nothing about knowability: it
compares dates it is given. The caller must have already filtered the history to what was
public at the cluster's `as_of` (`knowable_time <= as_of`), exactly as `gather_events` does
for everything else.
"""
from __future__ import annotations

from datetime import date

ROUTINE = "routine"
OPPORTUNISTIC = "opportunistic"
UNCLASSIFIED = "unclassified"

LOOKBACK_YEARS = 3


def _month_key(d: date) -> tuple[int, int]:
    return (d.year, d.month)


def classify_insider(trade_history: list[date], as_of: date) -> str:
    """Classify one trade dated `as_of` from this insider's prior trades in the same issuer.

    `trade_history` is the insider's trade dates in THIS issuer (all transaction codes — see
    deviation 2). Dates on or after `as_of` are ignored, so a trade can never classify itself
    and the caller may pass an unfiltered history without corrupting the answer.

    Returns ROUTINE when the insider traded in the same calendar month in each of the three
    preceding years; UNCLASSIFIED when there is not three years of prior history to judge
    from (never ROUTINE — an absent record is not evidence of a schedule); OPPORTUNISTIC
    otherwise.
    """
    prior = [d for d in trade_history if d < as_of]
    if not prior:
        return UNCLASSIFIED                             # first ever trade in this issuer

    # Depth first, so a short record can never be read as a schedule. The window the rule asks
    # about reaches back to month `as_of.month` of year `as_of.year - 3`; if the insider's
    # earliest trade is later than that month, the window is not covered and the answer is
    # "we cannot tell", not "routine".
    window_start = (as_of.year - LOOKBACK_YEARS, as_of.month)
    if _month_key(min(prior)) > window_start:
        return UNCLASSIFIED

    months = {_month_key(d) for d in prior}
    same_month_each_year = all(
        (as_of.year - k, as_of.month) in months for k in range(1, LOOKBACK_YEARS + 1)
    )
    return ROUTINE if same_month_each_year else OPPORTUNISTIC


def counts_toward_gate(classification: str) -> bool:
    """Whether a voice with this label counts toward `min_voices`.

    Routine insiders do not: CMP's finding is that their trades predict nothing, so letting
    three January-buyers manufacture a cluster would rebuild the very thing the split exists
    to remove. Unclassified DOES count — it means "not enough record to judge", and on this
    dataset that is almost every insider (see the data limitation in the analysis). Treating
    unknown as routine would silently empty the signal; treating it as opportunistic would
    overclaim. It counts as a voice and is reported separately.
    """
    return classification != ROUTINE
