# Does the PURE-INSIDER signal have an edge?

**Yes, and it is negative. The pure Form 4 signal does not merely fail to predict — it predicts
the wrong way, and that is the one finding here that survives every check.** Across 457 episodes:
**−3.40% mean excess versus SPY at 90 days, 95% interval [−5.40%, −1.40%], n=442**, and **−7.21%
at 180 days, [−10.45%, −3.96%], n=352**. Hit rate 34.9% at 180 days, 5.65 standard errors below a
coin flip.

**The opportunistic cut cannot be compared to the routine cut, because the routine cut is empty.**
Of 60,708 open-market purchases, **27** classify as ROUTINE under Cohen–Malloy–Pomorski, and
**none of the 27 reaches a published cluster**. Running the whole computation with routine
insiders counted as voices produces a byte-identical set of 457 episodes — zero episodes changed,
zero scores changed. CMP's roughly fourfold difference is not measurable on this dataset in either
direction, and the reason is a data limitation, not a result. §"Why the routine arm is empty".

**One cut is positive and it should not be believed: opportunistic-voices-only, +3.61% at 30 days
and +4.26% at 90 days — neither interval excludes zero (n=31), and it is one of 59 tests.**

Measured 2026-09-15 against `convergence_insider-v2`, hash `ea6b6a98227b95b4`.

---

## The verdict, in the three forms the brief asked for

**1. Does the opportunistic cut beat the routine cut, and by how much?**
Not answerable. The routine arm holds zero episodes. The nearest computable substitute —
episodes whose every voice is opportunistic (n=31) against episodes with no opportunistic voice
at all (n=305) — does show a gap in CMP's predicted direction and it is large: **+4.26% versus
−4.37% at 90 days, a spread of 8.6 percentage points.** But the opportunistic arm's interval is
[−0.76%, +9.28%] and spans zero, so the gap is not established. It is the single most interesting
number in this document and it is not evidence yet. §"Cut (a)".

**2. Does any cut show a mean excess return whose 95% interval excludes zero AND survives the
multiple-testing check?**
**Yes — 27 of them, and every single one is negative.** 59 deduplicated tests reached n ≥ 30. At
α = 0.05 chance alone would produce **2.95**. Twenty-seven turned up, **27 negative, 0 positive**.
A multiple-testing artifact scatters significant results on both sides of zero; these are all on
one side. **No positive cut survives. No positive cut even reaches significance before the
multiple-testing check is applied.**

**3. Power.**
The sample is **underpowered to detect a 1% edge** and amply powered for the effect actually
present. At the measured dispersion a 1%-per-episode edge needs **724 / 1,768 / 3,704** episodes
at 30 / 90 / 180 days against **453 / 442 / 352** in hand. But the effect measured is 3–7× larger
than 1%: detecting **−3.40%** at 90 days needs **153** episodes and detecting **−7.21%** at 180
days needs **71**. So "underpowered" disqualifies any small positive that might be hiding here —
it does not disqualify the negative result, which is several times the resolvable floor.

---

## Why this test had never been run

`convergence`'s publish gate is `min_source_classes: 2`. Every one of its 17,669 clusters
therefore blends Form 4 activity with 13F holdings (quarterly, 45-day lag) or 13D/G stakes, and a
pure-insider cluster is unreachable by construction — `signal_edge.md` records cut (a) there as
structurally empty, **n = 0**. The literature the product rests on is about pure Form 4 purchases:

* **Cohen, Malloy & Pomorski (2012)**, *Decoding Inside Information*, Journal of Finance 67(3) —
  routine traders predict nothing; opportunistic traders earned ~82bps/month abnormal.
* **Lakonishok & Lee (2001)**, Review of Financial Studies 14 — the signal strengthens when
  several insiders buy at once.
* **Jeng, Metrick & Zeckhauser (2003)** — purchases carry signal, sales do not. (Already honoured:
  `insider_sale` has scored 0.0 since v1, decision #21.)

None of it had ever been computed here. `convergence_insider` is that computation:
`min_source_classes: 1`, `min_voices: 2`, transaction code **P** only (no sales, no option
exercises, no grants, no tax withholding), routine insiders excluded from both voices and score,
and convergence v3's **$2M / 90-day median dollar volume** floor unchanged so the comparison is
like for like.

### It is registered under its own NAME, not as `convergence` v5

Two measured reasons, both of which would have caused damage:

1. **`smartmoney_claims._definition_version()` read `SELECT max(version) FROM signal_definitions`
   with no name filter**, and the scheduler calls it every cycle. A row numbered 5 would have
   restamped new claims `convergence-v5` when v3 logic produced them — and those claims are the
   source `seed-house-records` imports into `calls`, whose rows are sealed by trigger and can
   never be corrected. Verified after registering: `max(version)` is still **4**. The underlying
   bug is fixed separately (it now reads each cluster's own `definition_id`).
2. **`convergence.py` is left byte-identical**, so its hash still matches the registered v4 row
   and **v3 and v4 remain recomputable from this commit**. Editing it to carry new params would
   have made the two versions this analysis is compared against unreproducible.

`convergence.score_cluster` is imported and reused unmodified — its gate was already fully
params-driven, so `min_source_classes: 1` needed no new code. A v5 score and a v3 score therefore
mean the same thing.

### The clusters are NOT stored in `signal_clusters`, deliberately

30 read sites across 12 live modules query that table with **no definition filter** —
`/api/signals` is `WHERE c.as_of = %s` and nothing more. v3 and v4 do not collide today only
because they were computed on disjoint as_of days (measured: **0** colliding (issuer, as_of)
pairs). Replaying a third definition over v3's range would collide on every one of its 419 days,
and the Smart Money feed, the dashboard, the Morning Brief, alerts and the **public** methodology
calibration would each double-count. The episodes live in `docs/analysis/v5_episodes.json`
instead. Everything else — params from the registered definition row through the hash guard,
`score_cluster`, `bucket_for`, the floor, `group_episodes` at `EPISODE_GAP_DAYS = 14` — is the
engine's own code.

---

## Why the routine arm is empty, and what that costs

**The three-year lookback has no data to reach through.** Dense Form 4 history in this database
begins **2024-01**. CMP's rule asks whether an insider traded in the same calendar month in each
of the three *preceding* years; for a 2026 purchase that means 2025, 2024 and **2023**, and 2023
holds 10,473 rows against 2025's 320,861.

| Purchase year | Code-P purchases | With ≥3 years of prior history | Would classify ROUTINE |
|---|---:|---:|---:|
| 2024 | 16,601 | 1,016 (6.1%) | 5 |
| 2025 | 30,118 | 7,321 (24.3%) | 9 |
| 2026 | 12,290 | 2,258 (18.4%) | 3 |
| **All years** | **71,942** | **10,994 (15.3%)** | **27** |

Final labels over the 60,708 purchases with a resolved issuer: **27 routine (0.04%), 10,882
opportunistic (17.9%), 49,799 unclassified (82.0%)**. Unclassified means "not enough record to
judge", and per the rule it counts as a voice — treating it as routine would have emptied the
signal rather than measured it.

**A second, larger gap was found and fixed during this work.** The classifier originally looked up
an insider's history keyed on `issuer_entity`. That column is this system's *resolution artifact*
and is **NULL on 94,775 of 759,698 rows — almost all of them 2021–2023**, precisely the years the
lookback needs. Keying the lookup on `issuer_cik`, which comes off the filing itself and is NOT
NULL on every row, is strictly more correct and recovers six times as many labels:

| History keyed on | routine | opportunistic | unclassified |
|---|---:|---:|---:|
| `issuer_entity` (v1) | 26 | 1,833 (3.0%) | 58,849 (96.9%) |
| **`issuer_cik` (v2)** | **27** | **10,882 (17.9%)** | **49,799 (82.0%)** |

Same rule, same trades. This is why the definition is at v2: the hash guard refused to recompute
until the change was registered with a changelog, which is exactly what it exists for.

**None of it rescues the routine arm.** 27 routine trades is 27 whichever key is used, and **none
of them lands in a published cluster**: the `--include-routine` control run returns 457 episodes,
359 symbols, identical scores, **zero episodes containing a routine voice**.

### The 10b5-1 flag is absent, and is not inferred

`ingestion/form4.py` does not parse a 10b5-1 plan indicator and `insider_transactions` has no
column for one — `grep -n "10b5\|rule10\|footnote\|plan" tradeos/ingestion/form4.py` returns
nothing. The SEC only added an explicit Form 4 checkbox in late 2022 (adopting release 33-11138);
before that the fact appears in free-text footnotes when it is disclosed at all. **Reported as a
data limitation, not inferred and not fabricated.** CMP's later literature uses that flag to
separate scheduled trades; without it, the calendar rule is the only instrument available, and on
this history it is a blunt one.

---

## STEP 1 — Coverage, before any statistics

**251,688 clusters passed the gate across 2,188 issuers and 1,943 symbols.** They do not survive
contact with the rest of the pipeline:

| Stage | Clusters | Note |
|---|---:|---|
| Passed the 1-class / 2-voice gate | 251,688 | over 2,188 issuers |
| Dropped: no ticker mapped to the issuer | −30,723 | 245 issuers unresolved |
| Dropped: below the $2M liquidity floor | **−195,461** | **77.7% of the rest** |
| **Published** | **25,504** | 359 issuers |
| **Episodes after 14-day collapsing** | **457** | 359 distinct symbols |

**The floor removing 78% is itself a finding.** Insider buying concentrates in small, illiquid
companies; v3's blended gate needed a 13F or 13D/G filer to agree, and those cluster on larger
names. The pure-insider signal points almost entirely at companies the product's own liquidity
rule refuses to publish.

**25,504 clusters are 457 observations, a 56× reduction.** `EPISODE_GAP_DAYS = 14`: with a 90-day
window, one burst of insider buying makes every business day for the next quarter a cluster, and
all of them are one episode entered at the first (decision #26). Median 64 clusters per episode,
max 510. That is the same convention v3 used, where the reduction was 24×; v5's episodes run
longer because insider buying at an active company is more continuous than a filing cluster is.

### Scoreable sample per bucket per horizon

| Bucket | Episodes | 30d | 90d | 180d |
|---|---:|---:|---:|---:|
| low | 358 | 354 | 344 | 278 |
| medium | 70 | 70 | 70 | 54 |
| high | 29 | **29 ✗** | **28 ✗** | **20 ✗** |
| **ALL** | **457** | **453** | **442** | **352** |

✗ = under 30 scoreable episodes. **No percentage is computed or reported for these.** As in v3,
the HIGH bucket — the one carrying the "strong convergence outperforms" thesis — still has no
sample at any horizon.

Unscoreable causes are separated, never pooled: **4 episodes have no price series at all**
(`BBBY-WT`, `DGAC-RI`, `SAGU-WT`, `VECA-UN` — two warrants, a rights line and a SPAC unit); every
other gap is `horizon_open_or_delisted`, a horizon that has not closed.

---

## STEP 2 — Mean excess return vs SPY, hit rate, intervals

Entry = close of the first session after as_of; exit = first session on/after entry + horizon
calendar days; a hit is excess > 0. `ledger.mean_ci` for means, Wilson for proportions — the two
are not interchangeable.

| Bucket | H | n | Mean excess | 95% interval | Hit rate | z vs coin |
|---|---|---:|---:|---|---:|---:|
| ALL | 30d | 453 | −0.53% | [−1.80%, +0.73%] | 46.6% | −1.46 |
| **ALL** | **90d** | **442** | **−3.40%** | **[−5.40%, −1.40%]** | **40.7%** | **−3.90** |
| **ALL** | **180d** | **352** | **−7.21%** | **[−10.45%, −3.96%]** | **34.9%** | **−5.65** |
| low | 30d | 354 | −0.34% | [−1.80%, +1.13%] | 48.0% | −0.74 |
| low | 90d | 344 | −2.44% | [−4.60%, −0.28%] | 42.7% | −2.70 |
| low | 180d | 278 | −7.24% | [−10.60%, −3.89%] | 33.5% | −5.52 |
| medium | 30d | 70 | −1.04% | [−3.96%, +1.87%] | 40.0% | −1.67 |
| medium | 90d | 70 | −6.52% | [−12.29%, −0.74%] | 30.0% | −3.35 |
| medium | 180d | 54 | −4.35% | [−15.62%, +6.91%] | 37.0% | −1.91 |
| high | all | 20–29 | — | insufficient (n<30) | — | — |

**The 180-day hit rate of 34.9% is the most conclusive single statistic in this document.** It is
5.65 standard errors below chance on 352 observations. v3's comparable figure was 40.8% on 223.

### Beside v3, measured the same way

| | v3 ALL 90d | **v5 ALL 90d** | v3 ALL 180d | **v5 ALL 180d** |
|---|---|---|---|---|
| n | 423 | **442** | 223 | **352** |
| Mean excess | +0.83% | **−3.40%** | +1.79% | **−7.21%** |
| 95% interval | [−2.39%, +4.06%] | **[−5.40%, −1.40%]** | [−5.13%, +8.71%] | **[−10.45%, −3.96%]** |
| Verdict | spans zero | **excludes zero, negative** | spans zero | **excludes zero, negative** |

v3 and v5 are **different signals and are never pooled**. What the comparison shows is that
removing the institutional half of the evidence does not isolate a cleaner insider signal — it
isolates a worse one. The blend was, if anything, diluting the damage.

---

## STEP 3 — The three cuts

### Cut (a) — opportunistic versus routine. **The control arm is empty.**

| Cut | H | n | Mean excess | 95% interval | Hit rate |
|---|---|---:|---:|---|---:|
| opportunistic voices only | 30d | 31 | **+3.61%** | [−0.78%, +8.00%] | 58.1% |
| opportunistic voices only | 90d | 31 | **+4.26%** | [−0.76%, +9.28%] | 51.6% |
| opportunistic voices only | 180d | 27 | — | insufficient (n<30) | — |
| ≥1 opportunistic voice | 30d | 148 | −0.21% | [−1.83%, +1.41%] | 48.6% |
| ≥1 opportunistic voice | 90d | 145 | −1.40% | [−4.64%, +1.84%] | 44.1% |
| ≥1 opportunistic voice | 180d | 114 | −1.65% | [−8.27%, +4.97%] | 40.4% |
| no opportunistic voice | 90d | 297 | **−4.37%** | **[−6.89%, −1.85%]** | 39.1% |
| no opportunistic voice | 180d | 238 | **−9.87%** | **[−13.43%, −6.30%]** | 32.4% |
| **CONTROL: incl. routine** | all | — | **identical to ALL** | zero routine episodes | — |

**This is the closest thing to a positive result in the document and it is not one yet.** The
ordering is exactly what CMP predict — pure-opportunistic clusters are the only cut that is
positive at any horizon, clusters with no opportunistic voice are the most negative cut of all,
and the mixed case sits between them. The 90-day spread is **8.6 percentage points**. But:

* n = 31, and the interval **[−0.76%, +9.28%] spans zero**;
* it is one of 59 tests, and the 180-day horizon falls under the reporting threshold;
* the "no opportunistic voice" arm is not a routine arm. It is an *unclassified* arm — 82% of
  purchases, mostly meaning the insider's record is too short — so the contrast is partly
  "insiders with three years of history" versus "insiders without", which is a proxy for company
  age and listing tenure as much as for information.

**What would settle it:** a deeper Form 4 backfill (below) raises the classifiable fraction, and
the opportunistic-only arm grows with it. This row is the reason to do that work.

### Cut (b) — distinct insider count. **Lakonishok & Lee runs backwards, monotonically.**

| Cut | 30d | 90d | 180d |
|---|---|---|---|
| ≥2 insiders (= every episode) | n=453, −0.53% | n=442, **−3.40%** | n=352, **−7.21%** |
| ≥3 insiders | n=149, −1.24% | n=145, **−6.07%** | n=109, **−10.84%** |
| ≥5 insiders | n=61, −2.74% | n=58, **−8.82%** | n=44, **−13.89%** |
| ≥8 insiders | n=16, insufficient | n=16, insufficient (−13.90%) | n=12, insufficient (−17.85%) |

Bold = 95% interval excludes zero. **Every step up in insider agreement makes the outcome worse,
at every horizon, without a single reversal.** This is the same direction v3 showed (−0.08% →
−2.29% at 30 days) but far stronger and now significant: at 180 days the slope is −7.21% →
−10.84% → −13.89%, and the ≥8 cut is the most negative of all before it runs out of sample.

More insiders buying at once does not mean more conviction in this data. It means more distress.

### Cut (c) — total dollars committed, quartiles

Breaks: Q1 ≤ $371,066 · Q2 ≤ $961,792 · Q3 ≤ $3,101,298 · Q4 above. 451 episodes with a dollar
value.

| Quartile | 30d | 90d | 180d |
|---|---|---|---|
| Q1 smallest | n=112, −0.15% | n=109, +0.26% | n=88, −2.56% |
| Q2 | n=113, +0.10% | n=113, +0.27% | n=88, −4.83% |
| Q3 | n=113, −1.02% | n=109, **−7.54%** | n=88, **−7.13%** |
| Q4 largest | n=111, −1.07% | n=107, **−6.85%** | n=85, **−14.11%** |

The same shape as cut (b): the two quartiles committing the most money are the two significant
losers, and Q4 at 180 days is the worst single quartile cell in the table. Dollars committed
carry no positive information here either.

---

## STEP 4 — Multiple testing

**59 deduplicated cut × horizon combinations reached n ≥ 30.** At α = 0.05, chance alone produces
**2.95** false positives.

| | Count |
|---|---:|
| Tests with n ≥ 30 | **59** |
| Expected false positives at α = 0.05 | **2.95** |
| Mean-excess intervals excluding zero | **27** |
| — of which **negative** | **27** |
| — of which **positive** | **0** |
| Hit-rate Wilson intervals excluding 0.5 | **32** (all below) |

**Two cuts were excluded as duplicates before counting**, in both directions: `(b) insiders>=2` is
every episode (because `min_voices` **is** 2) and `(a) CONTROL all insiders incl. routine` is
every episode (because no episode contains a routine voice). Counting three names for one test
would have inflated the denominator and the numerator together.

**The count is the weaker argument and it is stated as such.** These cuts are heavily *nested* —
`low` is 78% of ALL, the dollar quartiles partition it, the IWM/IJR rows are the same episodes
against a different index — so the effective number of independent tests is well below 59, and
both 2.95 and 27 are inflated by the same nesting.

**The argument that does not depend on the count is direction.** A multiple-testing artifact
scatters significant results on both sides of zero. **All 27 are on one side, and all 32
significant hit rates are below a coin flip.** No amount of nesting produces that from noise.

This is the mirror image of `signal_edge.md`, where 60 tests produced **one** positive result
against 3.0 expected — *fewer* than chance, which is why that one was discarded. Here the search
finds nine times what chance would give, all pointing the same way.

---

## STEP 5 — Power

| H | n | sd | Needed for a 1% edge | Needed for the effect measured | Reached? |
|---|---:|---:|---:|---:|---|
| 30d | 453 | 0.1372 | 724 | 2,576 (effect −0.53%) | **no** |
| 90d | 442 | 0.2146 | 1,768 | **153** (effect −3.40%) | **yes, 2.9×** |
| 180d | 352 | 0.3105 | 3,704 | **71** (effect −7.21%) | **yes, 5.0×** |

**Stated plainly, because an underpowered positive is worthless:** this sample **cannot** resolve
a 1%-per-episode edge at any horizon, and any small positive that might be hiding in it is
undetectable. It **can** resolve the effect that is actually there, which is 3–7× larger than the
floor and clears it by a factor of three to five at the two long horizons. The 30-day horizon
resolves nothing in either direction and is reported as such.

For comparison, v3 needed ~1,268 episodes for a 1% edge and had 223.

---

## Robustness — the three ways this result could have been an artifact

### 1. Is it a small-cap effect rather than an insider effect?

This is the objection that would void the whole document. `excess_return` benchmarks against SPY
with **no size or beta control**, while CMP measure abnormal returns against characteristic-matched
portfolios. Insider buying concentrates in small caps; a small-cap drawdown would produce this
exact shape with no insider content at all.

| Benchmark | 30d | 90d | 180d |
|---|---|---|---|
| SPY (headline) | −0.53% | **−3.40%** [−5.40, −1.40] | **−7.21%** [−10.45, −3.96] |
| IWM (Russell 2000) | −1.23% | **−4.39%** [−6.40, −2.38] | **−9.30%** [−12.58, −6.02] |
| IJR (S&P SmallCap 600) | −0.94% | **−3.69%** [−5.70, −1.69] | **−7.33%** [−10.62, −4.03] |

**Ruled out, and in the inconvenient direction: against small-cap benchmarks the result is
worse.** Over these same entry dates the small-cap indices *beat* SPY — IWM by +0.98% at 90 days
and +2.07% at 180 — so small caps were not in a relative drawdown. The underperformance belongs to
the selected names, not to their size class.

This is not a full characteristic match — it controls for size, not for book-to-market, momentum
or industry — so it is a strong disconfirmation of the simplest alternative, not a CMP-grade
abnormal return.

### 2. Is it one bad market window?

| Entry year | 30d | 90d | 180d |
|---|---|---|---|
| 2024 (n=59) | −1.49% | +0.18% | **−9.36%** [−16.86, −1.86] |
| 2025 (n=218) | +0.01% | −1.81% | **−4.74%** [−9.10, −0.38] |
| 2026 (n=176/165/75) | −0.88% | **−6.77%** [−9.92, −3.62] | **−12.68%** [−18.58, −6.78] |

Negative and significant at 180 days in **every** entry year. Not one window.

### 3. Is it the long-episode entry convention?

Episodes are long here (median 64 clusters, max 510) and entered at the first. Split by length:

| Episode length | 30d | 90d | 180d |
|---|---|---|---|
| ≤47 clusters (n=151) | −0.47% | **−5.88%** | **−9.45%** |
| 48–64 (n=176) | −0.98% | **−3.51%** | **−7.36%** |
| >64 (n=126) | +0.03% | −0.47% | −4.23% |

Negative in all three terciles at 180 days, significant in two. The effect is **strongest in the
shortest episodes**, which is the opposite of what an entry-convention artifact would produce —
a stale-entry artifact would concentrate in the long episodes, and those are the mildest.

**Survivorship runs the same way.** Episodes whose horizon has not closed or whose symbol delisted
are dropped, so names that failed outright are under-represented. That biases the measured return
**up**, which makes −7.21% conservative.

---

## Price coverage, and the symbols with none

v5 introduced **1,664 symbols with no prices**. Backfilled from Alpaca over 2020-09-01 →
present: **1,664 symbols, 1,515 with data, 149 no_data, ~1.85M rows, 17 batches, ~355 seconds.**

**It is materially slower than the 345-symbol benchmark, and the reason is rows, not symbols.**
That run was 345 symbols / 349,480 rows / 4 batches / 47s. This one is 4.8× the symbols and 5.3×
the rows for 7.6× the time. The cost driver is **pagination**: Alpaca caps a page at 10,000 bars,
so 1.85M rows is ~185 page fetches regardless of how they are batched. Throughput per *row* fell
only modestly (7,436 → ~5,200 rows/s). **Note that the counter named "batches" counts symbol
groups, not HTTP requests** — the "4 requests" in `CLAUDE.md` §0h undercounts the real round trips
by the pagination factor, and a backfill reaching years back pays that factor in full.

### BATRB, FIISO, and the 24 symbols that share their gap

Both hold Tiingo rows and **zero Alpaca rows**: BATRB 1,320 rows and FIISO 603, each stopping at
**2026-09-01**, which is Tiingo's last day rather than Alpaca's 2026-09-14. They are not missing —
they are frozen, and will drift further every day the scheduler runs.

**26 symbols in `prices_eod` have no Alpaca row at all**, and they are one kind of instrument:

| Class | Symbols |
|---|---|
| Warrants | `AESPW` `GWHWW` `INVLW` `MNTSW` `NAKAW` `NXNVW` `SRZNW` |
| Preferreds | `CTRVP` `FIISO` `INPAP` `PEB-PH` |
| Units / rights | `DGAC-UN` |
| Foreign OTC / ADR | `AEGOF` `FMTOF` `IVEVF` `LEEEF` `AASP` `AWHL` `CRSF` `CWGL` `FEAV` |
| B-class shares | `BATRB` `FCNCB` `LILAB` |
| Bankruptcy (`Q`) | `IOBTQ` |
| Other | `CORZR` |

**This is the free IEX feed's coverage boundary, not a bug.** IEX quotes roughly 2–3% of US
equity volume and does not carry most warrants, units, thin preferreds or OTC foreign lines.
Separately, **4 episode symbols have no price series from either source** and are excluded from
every statistic above: `BBBY-WT`, `DGAC-RI`, `SAGU-WT`, `VECA-UN`.

The operational consequence is that these 26 are permanently stale under an Alpaca-only top-up,
and `--only-stale` will re-select them every run and never fix them. They should either keep a
Tiingo top-up or be excluded from the staleness work list explicitly.

---

## The 36 stale `signal_outcomes` rows — **not deleted, and they must not be**

`signal_outcomes` holds 631 rows: 595 written 2026-09-14, and **36 dated 2026-07-17/19** whose
cluster is no longer an episode entry. The brief asked for them to be cleaned up or for a reason
not to. The reason is decisive:

**All 36 have already been expressed as claims, all 36 claims carry `model_version =
'convergence-v3'`, and all 323 `convergence-v3` claims with outcomes are exactly the 323 calls
sealed into the `@convergence-v3` Receipts record.** Those calls are protected by
`calls_append_only_trg`, which refuses every delete and every edit to a sealed column. Deleting
the `signal_outcomes` rows would leave permanent, publicly verifiable calls whose upstream
evidence had been removed — and nothing could ever put it back or correct the calls.

They are also **inert where it matters**. `compute_calibration` looks outcomes up *by episode-entry
cluster id*, so a row whose cluster is not an entry is never read; every figure in `signal_edge.md`
and in this document is computed from the engine rather than from the table. The one consumer that
does read them unfiltered, `smartmoney_claims.build`, has already consumed them and dedupes on
`source_ref`, so re-running creates nothing new.

**Recommendation: leave them and filter on `computed_at` when querying the table directly**, which
is what `signal_edge.md` already advises. A `DELETE` here buys tidiness and spends the provenance
of a record whose entire value is that it cannot be edited.

---

## What this changes, and what to do next

1. **The pure-insider hypothesis is not merely unproven here, it is contradicted.** Any surface
   that implies clustered insider buying is bullish is, on this database, claiming the opposite of
   what the data says. Nothing currently ships that claim from this signal — `convergence_insider`
   is not wired to any route — and it should not be wired to one.

2. **Cut (a) is the one live thread.** Pure-opportunistic clusters are the only positive cut and
   the ordering matches CMP exactly; the sample is 31. **Deepening the Form 4 backfill is the only
   thing that grows it**, and it grows it two ways at once — more classifiable insiders, and more
   episodes. Measured cost is ~35 minutes per week of Form 4 (CLAUDE.md §0a3).

3. **Run `resolve-entities` over the 2021–2023 backlog.** 94,775 rows (12.5% of the table) have a
   NULL `issuer_entity` and are invisible to `candidate_issuers` entirely. Fixing the *history*
   key to `issuer_cik` recovered the classifier; it did not make those rows visible to the
   **signal**, which still keys on the entity. This is the cheapest remaining improvement and it
   was deliberately not run here because it writes outside this analysis's read-only boundary.

4. **Do not re-cut this dataset looking for a better number.** 59 tests have been run against 457
   episodes. Each further cut raises the chance of a false positive without adding an observation.

5. **The liquidity floor deserves its own decision.** It removes 77.7% of pure-insider clusters.
   That is either correct (illiquid names were the v3 performance drag, decision #38) or it is
   discarding the population the literature is actually about. Both readings are defensible and
   the question has never been measured directly.

---

## Reproducing this

```bash
# 1. register the definition (idempotent; refuses if the module hash already matches)
docker compose run --rm -T -w /app -e PYTHONPATH=/app -v "$PWD/tradeos:/app/tradeos" \
  api python -c "
from tradeos import db; from tradeos.signals import definitions, insider
with db.connect() as c: print(definitions.register(c, '<changelog>', module=insider))"

# 2. which symbols does the gate admit that have no prices?
docker compose run --rm -T -w /app -e PYTHONPATH=/app \
  -v "$PWD/tradeos:/app/tradeos" -v "$PWD/scripts:/app/scripts" -v "$PWD/docs:/app/docs" \
  api python scripts/analysis/compute_v5.py --stage a

docker compose exec -T api python -m tradeos.cli ingest-prices --symbols "<list>" --start 2020-09-01

# 3. compute the episodes, and the routine control arm
docker compose run ... api python scripts/analysis/compute_v5.py --stage b
docker compose run ... api python scripts/analysis/compute_v5.py --stage b --include-routine

# 4. every figure in this document
docker compose run ... api python scripts/analysis/signal_edge_v5.py
```

Steps 2–4 are **read-only against the database** and write only `docs/analysis/v5_episodes*.json`.
Step 1 inserts one `signal_definitions` row. The price backfill in step 2 inserts into
`prices_eod`. **Nothing writes `signal_clusters`, `signal_outcomes`, `claims`, `calls` or any
Receipts table.**

The liquidity floor is computed in memory for speed (251,688 checks) and is **verified against the
real `convergence.passes_liquidity_floor` SQL on a seeded 300-pair sample every run** — 300
checked, **0 mismatches**, reported in the artifact. A mismatch aborts the run rather than
producing a quietly different number.
