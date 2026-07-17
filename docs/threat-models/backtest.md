# Threat model: Backtest + calibration

Written before the engine, per the security mandate. The backtest is where the platform
makes its central promise — "when we say 70%, reality agrees about 70% of the time." A
dishonest backtest is not a bug, it is fraud that a regulator and a skeptical trader will
both eventually catch, so every threat here is an integrity threat. Each names the design
property that removes or bounds it.

## Who / what attacks this and how

**1. Look-ahead leakage (the cardinal sin).** A backtest that peeks at anything not public
on its as_of date manufactures performance that cannot be earned live. Removed structurally
by: clusters are computed strictly point-in-time (`knowable_time <= as_of`) — enforced in
the SQL gather AND, defense-in-depth, in `score_cluster`, which drops any event with
`knowable_time > as_of` even if mis-fed (convergence v2, decision #28). Forward returns only
ever read prices dated on/after the entry day (the first trading day AFTER as_of). The
look-ahead test smuggles a future-knowable event in and asserts it is excluded.

**2. Survivorship bias.** Backtesting only the companies that still exist inflates results.
Bounded by: the symbol universe comes from filers — companies that existed and filed at the
time — not from a current index, so dead companies are present in the universe. Where a
delisted/renamed symbol lacks price history, its episode is **counted and displayed as an
exclusion** ("N episodes excluded for missing price history"), never silently dropped. The
exclusion count is part of the public methodology.

**3. Small-sample overclaim.** A "100% hit rate" on 3 episodes is astrology. Removed by: any
confidence bucket with fewer than 30 resolved episodes shows "insufficient sample," never a
percentage; every displayed rate carries its episode count and a binomial 95% interval.

**4. Episode double-counting.** Daily recomputation produces many clusters for one ongoing
situation; counting each as an independent success inflates n and the hit rate. Removed by:
consecutive clusters on one issuer with no gap > 14 days are one **episode**, entered once at
its first day; statistics count episodes, and both the episode count and the raw cluster
count are reported (decision #26).

**5. Benchmark / horizon cherry-picking.** Choosing the flattering benchmark or horizon after
seeing results is researcher-degrees-of-freedom fraud. Bounded by: a single fixed benchmark
(SPY), excess return, and three pre-declared horizons (30/90/180 calendar days), all fixed in
code and stated in the methodology before any number is shown (decision #25, and Phase-0
decision #12).

**6. Dirty price supply chain.** The whole business rests on a clean data supply chain, so the
price source must be one we have the right to use programmatically. Stooq's free CSV endpoint
is, at implementation time, gated behind a JavaScript proof-of-work anti-bot challenge;
fetching from it would require circumventing that measure — ToS-violating scraping the founding
brief forbids. Removed by: refusing to scrape it. The price source is deferred to a founder-
selected feed with a clean API and clear terms, labeled "demo-grade" on the methodology page;
a licensed EOD feed is the first post-funding purchase (decision #27).

**7. Unadjusted-price distortion.** Splits/dividends corrupt raw-price returns. Bounded by:
prefer the source's split/dividend-adjusted series, record per symbol which series was used in
the `source` column, and state the adjustment limitation on the methodology page. Never hide a
data limitation.

## What this engine explicitly does not claim yet

Until a chosen price feed is wired and enough history has elapsed for the 30/90/180-day windows
to CLOSE, buckets honestly read "insufficient sample" — the engine reports the absence of a
calibrated rate rather than inventing one. A publishable calibration curve requires the 24-month
historical backfill (build-plan 7.5); the demo calibration states its actual sample window and
the live curve replaces it at 200 resolved signals per type.
