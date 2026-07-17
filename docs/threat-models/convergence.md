# Threat model: Convergence signal v1

Written before the signal code, per the security mandate. The convergence signal is where
the platform is most dangerous to itself: a number here can move a user's money decision,
so the defining attack is an adversary manufacturing a cluster to make TradeOS pump an
asset for them (the poisoning threat from the founding brief). Each attack names the design
property that removes or bounds it.

## Who attacks this and how

**1. Single-origin echo (sockpuppet convergence).** An attacker controls several filers
(or files many events themselves) to fake "many independent sources agreeing." Removed as
a structural inflation by: **independence collapse**. Events are grouped by voice (an
insider by owner CIK; an institution by filer entity — its 13D and 13F count as one voice,
not two). A voice's single strongest event counts fully and its additional events add at
only 25%, so hammering one issuer from one identity cannot manufacture a high score. The
publish gate additionally requires **≥3 distinct voices across ≥2 distinct source classes**,
so one filer, or one class alone (e.g. only index-fund 13Gs), can never clear the bar.

**2. Micro-cap manipulation.** Convergence on a thin, illiquid name is the cheapest to
fake and the most dangerous to surface. Bounded by: the **liquidity floor**. In this slice
(pre-price-data) the floor is exchange-listing (issuer present in the SEC company_tickers
file); below-floor issuers are forced to the 'low' bucket and excluded from the default
dashboard feed. Slice 4 tightens this to a 90-day median-dollar-volume threshold, after
which sub-floor clusters do not publish at all. This interim state is logged (decision #23).

**3. Look-ahead leakage.** A backtest or a live score that peeks at data not yet public on
its `as_of` date would be silent fraud. Removed structurally by: every event is gathered
strictly with `knowable_time <= as_of`; the score is a pure function of the gathered
events and the as_of. There is no code path that reads `event_time` for windowing or
admission — only `knowable_time`. (Slice 4 adds an explicit test that smuggling a
future-knowable record raises.)

**4. Silent redefinition of the signal.** The most insidious integrity failure is the
meaning of "score 6" changing between releases without anyone noticing — calibration is the
brand, and a moved goalpost is a broken promise. Removed by: **mechanical version locking**.
Each signal_definitions row stores the params and a `code_hash` (sha256 of the computing
module). `compute-signals` refuses to run if the module's current hash does not match the
latest registered definition; changing a constant or a line of logic forces a new version
row with a changelog before any cluster can be computed (decision #24). The methodology
(all versions, params, changelogs) is public at /api/definitions — the definition is
product, not documentation.

**5. Stale input dressed as fresh conviction.** A quarter-old 13F counted as if it were a
today signal would overstate conviction. Bounded by: **per-class freshness decay** (half-
lives: insider 14d, 13D/13G 30d, 13F 60d) applied on `as_of - knowable_time`, and by
class base weights that already discount stale/derived sources. 13F additionally does not
contribute to the score at all in this slice, because "new or increased position" is a
quarter-over-quarter fact and the demo has one quarter (decision #22): it is shown as
context, never scored on a single snapshot.

**6. Insider noise mistaken for signal.** Routine insider sales, option exercises, and tax
withholdings are not bullish conviction; scoring them would flood the feed with noise an
attacker could hide inside. Bounded by: only open-market purchases (code P, acquired)
carry insider weight; sales score zero and are shown as context (decision #21).

## What this signal explicitly does not claim yet

Confidence buckets in this slice are score-threshold placeholders labeled "Backtested
calibration pending" in the UI. They are NOT calibrated probabilities until Slice 4 replaces
them with backtested hit rates. Nothing in the product may present a bucket as a calibrated
likelihood before then. The signal describes disclosed third-party activity; it never tells
a user what to buy.
