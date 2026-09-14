# Does the convergence signal have an edge?

**One cut clears the bar — and it should not be believed: `convergence-v3`, MEDIUM confidence,
90-day horizon, mean excess return +9.09% versus SPY, 95% interval [+0.13%, +18.05%], n=45.**

The next section is why it should not be believed. Measured 2026-09-14 against 741 scored
episodes, every one of them priced.

No other cut — of 60 tested at a usable sample size, across two definition versions, three
confidence buckets, three horizons, and the three additional cuts requested — has a mean excess
return whose 95% interval excludes zero.

---

## Why the one positive result should not be believed

**1. It is fewer positives than chance alone would produce.** 60 cut × horizon combinations
reached n ≥ 30 and were tested. At α = 0.05 you expect **3.0** false positives from pure noise.
**One** turned up. A search that finds less than it would find in random data has not found
anything; reporting that one as a discovery would be selecting the maximum of 60 draws and naming
it an effect.

**2. Its lower bound grazes zero.** +0.13% on an interval 18 percentage points wide. The interval
is consistent with anything from "no effect at all" to "+18% per call", which is another way of
saying 45 episodes cannot resolve the question.

**3. One additional episode destroys it.** The same cut computed across both definition versions —
which adds exactly **one** medium-confidence episode, n=45 → 46 — gives mean +8.00%, interval
**[−1.02%, +17.02%]**. That interval spans zero. A result that changes from significant to
non-significant on the arrival of a single observation is not a finding; and because v4 is
*byte-identical logic* to v3 (below), that one extra episode has every right to be in the sample.

**4. Neither adjacent horizon agrees.** The same bucket and version reads +0.58%, interval
[−3.42%, +4.58%] at 30 days (n=52) and +8.41%, interval [−9.70%, +26.53%] at 180 days (n=21,
insufficient). An effect that exists at 90 days, is absent at 30 and unmeasurable at 180, in a
bucket sitting between two others that show nothing, is the shape of noise.

**5. The bucket that carries the product thesis has never had a sample.** "Strong convergence
outperforms" lives in the HIGH bucket. It reaches n = 24 / 21 / 10 at 30 / 90 / 180 days — below
the reporting threshold at every horizon, exactly as decision-log #39 recorded. **It is still not
measured.** What has changed since #39 is that the reason is no longer price coverage.

**6. Where the sample IS large, the signal loses more often than a coin.** At n = 583 (v3, all
buckets, 30 days) mean excess is **−0.08%**. Hit rate is below 50% at every horizon, and at three
cuts the Wilson interval excludes 0.5 on the *low* side: v3/low at 90 days reads 44.0%
[38.9%, 49.2%], v3/low at 180 days 41.1% [34.4%, 48.2%], v3 overall at 180 days 40.8%
[34.6%, 47.4%]. The one statistic this dataset resolves confidently is that the signal picks
losers slightly more often than chance.

**The honest summary: this measurement does not demonstrate an edge, in either direction, for the
signal as a whole — and it weakly demonstrates the absence of one.** That is not the same as
proving the signal worthless; see "What would change this answer".

---

## STEP 1 — Coverage, before any statistics

### Clusters, and what a "sample" actually is here

| Definition | Clusters | low | medium | high | Span |
|---|---:|---:|---:|---:|---|
| `convergence-v3` | 17,145 | 15,360 | 1,251 | 534 | 2024-10-31 → 2026-07-22 |
| `convergence-v4` | 524 | 520 | 2 | 2 | 2022-03-01 → 2026-07-27 |
| **Total** | **17,669** | 15,880 | 1,253 | 536 | |

**17,669 clusters are not 17,669 observations.** `EPISODE_GAP_DAYS = 14`: clusters on one issuer
within a fortnight are one episode, and only the entry cluster is scored (decision #26). That is
correct — scoring 50 clusters on one issuer in one month as 50 independent outcomes would be
counting the same bet 50 times — but it means **the sample is 741 episodes, a 24× reduction**, and
any statement of the form "17,145 clusters" as a sample size is wrong by that factor.

### Scoreable sample, per version per bucket

Computed with the engine's own `excess_return`, so these numbers agree with what the backtest
scores. **Every episode has price data** — `no_symbol` = 0 and `no_price_history` = 0 across all
741, which was not true before this week's backfill.

| Version / bucket | Episodes | Scoreable 30d | Scoreable 90d | Scoreable 180d |
|---|---:|---:|---:|---:|
| v3 / low | 507 | 507 | 357 | 192 |
| v3 / medium | 52 | 52 | 45 | **21 ✗** |
| v3 / high | 24 | **24 ✗** | **21 ✗** | **10 ✗** |
| v3 / **all** | 583 | 583 | 423 | 223 |
| v4 / low | 154 | 154 | **11 ✗** | **11 ✗** |
| v4 / medium | 2 | **2 ✗** | **1 ✗** | **1 ✗** |
| v4 / high | 2 | **2 ✗** | **0 ✗** | **0 ✗** |
| v4 / **all** | 158 | 158 | **12 ✗** | **12 ✗** |

✗ = under 30 scoreable episodes. **No percentage is computed or reported for these**, per the
brief. v4's medium and high buckets hold two episodes each; they are listed to show they exist,
not to be read.

Every unscoreable case is `horizon_open_or_delisted` — the horizon has not closed yet. **None is a
missing price.** v4's collapse from 158 at 30 days to 12 at 90 is not a data gap: v4 was
registered in late July 2026, so its episodes are mostly younger than 90 days.

---

## Method, and two things worth stating before the tables

**`mean_ci` for means, Wilson for proportions.** A Wilson score interval is a statement about a
*proportion* and is used here only for hit rate. Mean excess return gets the sample-mean interval
(`ledger.mean_ci`). Applying Wilson to a mean would be a category error.

**The per-version split had to be recomputed, not read from `signal_outcomes`.** `run_backtest`
forms episodes with `_by_issuer`, which keys on **issuer alone**. A v3 and a v4 cluster on the
same issuer within 14 days therefore merge into ONE episode, attributed to whichever fired first.
Measured: **146 of its 595 episodes span both versions**, and it credits v4 with **12** entries
against v3's 583. Splitting `signal_outcomes` by version would report v4's sample as 12 when it is
158 — an artifact of absorption, not a fact about v4. Every per-version figure here is therefore
computed by grouping episodes on **(issuer, version)**, giving 741 episodes rather than 595. No
signal logic was changed and no row was written differently; `run_backtest` ran exactly as
designed and wrote its 595 rows.

**v3 and v4 are the same signal.** v4's own changelog: *"NO BEHAVIOURAL CHANGE. Re-registers the
identical scoring logic after the only edit since v3 — the Phase 1 lint pass removing an unused
'timezone' import."* The version boundary is a commit, not a change in behaviour. The brief
requires the split and it is given; a pooled figure appears **only** where labelled
POOLED-SUPPLEMENT, and never substitutes for a per-version number. It is legitimate here precisely
because the logic is identical (CLAUDE.md §0a).

---

## STEP 3 — Mean excess return vs SPY, hit rate, and intervals

Hit rate = the episode beat SPY over the horizon. Intervals are 95%.

### convergence-v3

| Bucket | H | n | Mean excess | 95% interval | Hit rate | Wilson |
|---|---|---:|---:|---|---:|---|
| all | 30d | 583 | −0.08% | [−1.46%, +1.29%] | 47.5% | [43.5%, 51.6%] |
| all | 90d | 423 | +0.83% | [−2.39%, +4.06%] | 46.1% | [41.4%, 50.9%] |
| all | 180d | 223 | +1.79% | [−5.13%, +8.71%] | 40.8% | [34.6%, 47.4%] |
| low | 30d | 507 | −0.19% | [−1.68%, +1.29%] | 47.3% | [43.0%, 51.7%] |
| low | 90d | 357 | −0.35% | [−3.83%, +3.13%] | 44.0% | [38.9%, 49.2%] |
| low | 180d | 192 | +1.79% | [−5.90%, +9.48%] | 41.1% | [34.4%, 48.2%] |
| medium | 30d | 52 | +0.58% | [−3.42%, +4.58%] | 46.2% | [33.3%, 59.5%] |
| **medium** | **90d** | **45** | **+9.09%** | **[+0.13%, +18.05%]** | **62.2%** | **[47.6%, 74.9%]** |
| medium | 180d | 21 | — | insufficient (n<30) | — | — |
| high | 30d | 24 | — | insufficient | — | — |
| high | 90d | 21 | — | insufficient | — | — |
| high | 180d | 10 | — | insufficient | — | — |

### convergence-v4

| Bucket | H | n | Mean excess | 95% interval | Hit rate | Wilson |
|---|---|---:|---:|---|---:|---|
| all | 30d | 158 | +0.37% | [−2.67%, +3.41%] | 44.9% | [37.4%, 52.7%] |
| low | 30d | 154 | +0.18% | [−2.93%, +3.29%] | 44.2% | [36.5%, 52.0%] |
| all / low | 90d, 180d | 11–12 | — | insufficient | — | — |
| medium, high | all | 1–2 | — | insufficient | — | — |

### POOLED-SUPPLEMENT (v3 + v4; identical logic, labelled, never a substitute)

| Bucket | H | n | Mean excess | 95% interval | Hit rate |
|---|---|---:|---:|---|---:|
| all | 30d | 741 | +0.01% | [−1.25%, +1.27%] | 47.0% |
| all | 90d | 435 | +0.66% | [−2.48%, +3.81%] | 45.8% |
| all | 180d | 235 | +1.80% | [−4.85%, +8.44%] | 40.0% |
| medium | 90d | 46 | +8.00% | **[−1.02%, +17.02%]** | 60.9% |

That last row is item 3 above: the one significant result, plus a single episode, minus its
significance.

---

## The three additional cuts

### (a) Insider Form 4 open-market purchases only (code P), excluding stakes — **n = 0, structurally**

**This cut cannot contain anything, and that is a fact about the signal's design rather than a
measurement.** The publish gate is `min_source_classes: 2` (`signals/convergence.py`), so a
cluster must draw on at least two of `insider`, `passive_stake`, `activist` to exist at all. Every
one of the 17,669 clusters has 2 or 3 source classes; **none has 1**. A pure-insider cluster is
unreachable by construction.

So the comparison the cut was meant to support — insider-only versus insider-plus-institutional —
is not available from this dataset. Its complement is the whole dataset: all 583 v3 episodes
contain at least one stake filing, which is why "(a) has-stake-filing" reproduces v3/ALL exactly.
Answering this question would require re-running the signal with `min_source_classes: 1`, which is
a change to signal logic and out of scope here.

### (b) Distinct insider count

| Cut | H | n | Mean excess | 95% interval | Hit rate |
|---|---|---:|---:|---|---:|
| v3, ≥3 insiders | 30d | 125 | **−2.29%** | [−5.16%, +0.58%] | 43.2% |
| v3, ≥3 insiders | 90d | 69 | +3.77% | [−5.24%, +12.77%] | 50.7% |
| v3, ≥3 insiders | 180d | 39 | +5.33% | [−12.50%, +23.17%] | 38.5% |
| v3, ≥5 insiders | 30d | 65 | −1.26% | [−6.01%, +3.49%] | 49.2% |
| v3, ≥5 insiders | 90d | 37 | +3.25% | [−11.93%, +18.43%] | 46.0% |
| v3, ≥8 insiders | 30d | 18 | — | insufficient | — |
| v3, ≥8 insiders | 90d | 10 | — | insufficient (−13.07%) | — |
| v4, ≥3 insiders | 30d | 51 | −2.34% | [−7.13%, +2.46%] | 39.2% |

Nothing excludes zero. The direction is worth noting because it is the opposite of the thesis:
requiring **more** insiders makes the 30-day mean **more negative** (−0.08% at all episodes →
−2.29% at ≥3 → and −2.34% for v4 at ≥3), and the ≥8 cut is the most negative of all at 90 days
before running out of sample. More agreement among insiders does not buy performance here.

### (c) Total dollar value bought, quartiles

v3 breaks: Q1 ≤ $103,349 · Q2 ≤ $423,970 · Q3 ≤ $2,076,584 · Q4 above.

| Quartile | 30d (n, mean) | 90d (n, mean) | 180d (n, mean) |
|---|---|---|---|
| Q1 smallest | 112, −1.07% | 87, +0.05% | 45, +2.90% |
| Q2 | 111, +2.70% | 85, +3.61% | 47, +1.06% |
| Q3 | 112, +0.29% | 79, +5.64% | 44, +5.37% |
| Q4 largest | 109, −0.35% | 62, +1.30% | 33, **−4.38%** |

No interval excludes zero, and there is no monotonic relationship between dollars committed and
outcome. If conviction expressed in dollars carried information, Q4 should lead; it is last at 180
days and negative. v4's quartiles reach n ≈ 30 at 30 days only and show the same absence.

---

## What would change this answer

The binding constraint has moved, and that is the one genuinely good piece of news here.

**It is no longer price coverage.** Decision-log #39 deferred high-bucket validation because
"~3,411 convergent historical issuers have symbols but no prices" on free Tiingo. After this
week's Alpaca migration, **all 741 episodes are priced** and `excluded_no_price_history` is **0**.
That blocker is gone.

**It is now the number of high-confidence events that have ever happened.** v3's 534
high-bucket clusters collapse to **24 episodes**, of which **10** have a closed 180-day horizon.
(The 741 episodes overall arise from 271 distinct issuers.) No
backfill of *prices* fixes this. It needs either more filing history (deeper EDGAR backfill
extends the universe backwards) or more time.

At the measured dispersion, detecting a 1%-per-episode edge needs roughly **1,268** resolved
episodes (`ledger.sample_needed`, CLAUDE.md §0a2). There are 223 at 180 days.

**A concrete next step, in order of value:**

1. **Deep EDGAR backfill before 2024-10** for v3's window. v3 starts 2024-10-31 while v4 reaches
   back to 2022-03-01, so the filing history to support a longer v3 sample partly exists already.
   `make backfill-full` over both Form 4 *and* 13D/G — one source alone produces zero clusters
   (CLAUDE.md §0a3), measured at ~35 minutes per week of Form 4.
2. **Re-run with `min_source_classes: 1`** if the insider-only question matters, as a separate
   registered definition version. That is a signal change and must not be done silently.
3. **Do not re-cut this dataset looking for a better number.** 60 tests have already been run
   against 741 episodes. Each additional cut raises the chance of a false positive without adding
   an observation.

---

## Reproducing this

```bash
docker compose exec -T api python -m tradeos.cli run-backtest      # writes signal_outcomes
docker compose exec -T api python - < scripts/analysis/coverage.py     # STEP 1 table
docker compose exec -T api python - < scripts/analysis/signal_edge.py  # every figure above
```

Both scripts are read-only. `run-backtest` writes only `signal_outcomes`, the rows it is designed
to write: 17,669 raw clusters → 595 episodes → 595 outcomes, 0 excluded for missing prices.

> **Note on `signal_outcomes` hygiene.** The table held **620** rows before this run and holds
> **631** after: 584 were updated, 11 inserted, and **36 rows dated 2026-07-17/19 were not
> rewritten** because their cluster is no longer an episode entry. Those 36 are stale and are
> excluded from everything above, which is computed from the engine rather than from the table.
> They are left in place rather than deleted — nothing here removes data — but a future reader
> querying `signal_outcomes` directly should filter on `computed_at`.
