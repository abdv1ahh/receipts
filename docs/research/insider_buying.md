# Clustered insider buying, measured over 25 months: no edge, and the sign is wrong

**This tested one construction of one signal over one window. It is not a finding about insider
buying in general, and the section "Why this may differ from the published literature" is not a
disclaimer bolted on the end — it is the most important part of the document.**

---

## What was tested

A **pure Form 4 open-market-purchase signal**: clusters of independent insiders buying shares of
one issuer inside a short window, scored as excess return against SPY over the following 30, 90
and 180 days.

"Independent" is the whole idea. One purchase can be a liquidity event, a scheduled plan or a tax
decision. Several unrelated people buying the same company within days of each other is harder to
explain that way, and the hypothesis under test is that the cluster carries information the market
has not priced.

**Only open-market purchases count.** Option exercises, grants, gifts, and any transaction code
that is not a P are excluded, because an insider who exercises an option has not chosen to buy
anything at today's price.

---

## The window

**2 July 2024 to 12 August 2026.** Twenty-five months, one regime, one clustering rule, one
benchmark, one liquidity profile.

---

## The method

| Stage | Count |
|---|---:|
| Open-market purchases ingested from SEC Form 4 | 60,708 |
| Clusters passing the publish gate | 251,688 |
| Clusters published (above the score floor) | 25,504 |
| **Episodes after 14-day de-duplication** | **457** |
| Distinct issuers | 359 |

The collapse from 25,504 to 457 is the step that matters most and it is not a filter, it is a
correction. Insider buying concentrates in small illiquid names, and with a 90-day clustering
window one burst of buying makes *every business day for the next quarter* a fresh cluster on that
issuer. Counting those 25,504 as 25,504 observations would be counting one event 56 times, and a
confidence interval built on them would be roughly seven times too narrow. `EPISODE_GAP_DAYS = 14`
collapses each burst to one episode.

**Point-in-time throughout.** Every derived value uses `knowable_time` — when a filing became
publicly knowable — and never the transaction date or the filing date. A Form 4 is due within two
business days of the trade, so the gap is real and using the wrong one lets a backtest see the
future. Insider classifications are fixed at each purchase's own `knowable_time`, which sees
strictly *less* history than a later re-classification would, so the error can only push a trade
from ROUTINE toward UNCLASSIFIED and never toward seeing the future.

---

## The result

**Negative, significant, and consistent across every cut.**

| Horizon | n | Mean excess vs SPY | 95% interval |
|---|---:|---:|---|
| 90 days | 442 | **−3.40%** | **[−5.40%, −1.40%]** |
| 180 days | 352 | **−7.21%** | **[−10.45%, −3.96%]** |

Hit rate at 180 days: **34.9%**, which is **5.65 standard errors** below a coin flip.

Neither interval contains zero. **Over this window this construction did not merely fail to
predict — it predicted the wrong way.**

Fifty-nine de-duplicated tests reached n ≥ 30. At α = 0.05, chance alone would produce about three
significant results. Twenty-seven turned up, and **all twenty-seven are negative**. That asymmetry
is what distinguishes this from a multiple-comparisons artifact: an artifact scatters significant
results on both sides of zero.

**On power.** The sample cannot detect a 1% per-episode edge — that would need 1,768 episodes at
90 days against 442 in hand. "Underpowered" therefore disqualifies any small positive that might
be hiding here. It does not disqualify the negative result: detecting −3.40% at 90 days needs 153
episodes, and detecting −7.21% at 180 days needs 71.

---

## The one positive cut, and why it should not be believed

Episodes whose every voice was classified **opportunistic** returned **+3.61% at 30 days** and
**+4.26% at 90 days** — the direction Cohen–Malloy–Pomorski predicts.

It should not be believed, for three reasons, any one of which is sufficient:

1. **Neither interval excludes zero.** At 90 days it is [−0.76%, +9.28%].
2. **n = 31.**
3. **It is one of 59 tests**, and it is the only positive one among them. Reporting it as a
   finding would be exactly the error the rest of this document exists to avoid.

It is the most interesting number here and it is not evidence.

**And the comparison it belongs to cannot be made at all.** Of 60,708 purchases, **27** classify
as ROUTINE under Cohen–Malloy–Pomorski, and **none of the 27 reaches a published cluster**. Running
the entire computation with routine insiders counted as voices produces a byte-identical set of 457
episodes: zero episodes changed, zero scores changed. The routine arm is empty, so "opportunistic
beats routine" is not answerable on this dataset in either direction. That is a data limitation,
not a result.

---

## Why this may differ from the published literature

The literature this signal was built on is strong, and it is not contradicted here.

* **Lakonishok & Lee (2001)**, *Review of Financial Studies* 14 — two decades of insider
  transactions.
* **Jeng, Metrick & Zeckhauser (2003)**, *Review of Economics and Statistics* 85 — a
  performance-evaluation approach across a long panel.
* **Cohen, Malloy & Pomorski (2012)**, *Decoding Inside Information*, *Journal of Finance* 67(3) —
  routine traders predict nothing; opportunistic traders earned roughly 82bps/month abnormal.

Those cover **decades**. This covers **25 months**. Six specific reasons the two can disagree
without either being wrong:

1. **One regime.** Twenty-five months is a single market environment. A signal can be real across
   forty years and absent, or inverted, inside any two of them.
2. **A different object.** The literature measures purchases by insiders. This measures
   *clusters* of purchases passing a particular score floor and a particular voice count. Those
   are not the same signal, and the clustering rule is this project's, not the literature's.
3. **The routine/opportunistic split could not be applied.** CMP's entire result rests on that
   split, and the routine arm here holds 27 purchases and zero episodes. Whatever this measured,
   it is not CMP's test.
4. **A liquidity profile the literature does not share.** These episodes concentrate in small,
   thinly traded names, where the 2% noise floor this project uses to absorb price noise is
   *smaller* than the disagreement between two price feeds on the least liquid symbols — measured
   at 2.86% and 2.29%. On such a name the choice of price feed alone can move a verdict.
5. **One benchmark.** Excess against SPY, with no size, sector or factor adjustment. A signal
   concentrated in small caps measured against a large-cap index is partly measuring the size
   factor.
6. **Survivorship and coverage.** The price series is one exchange's prints (IEX) rather than the
   consolidated tape, and symbols with no series at all are absent rather than zero.

**What this document claims, in full: this construction, over this window, against this benchmark,
measured −3.40% at 90 days. It does not claim that insider buying does not work.**

---

## How to reproduce it

Everything below runs against the tag `research_platform`, which preserves the whole
pre-extraction system. The Receipts repository on `main` does not contain the signal engine.

```bash
git checkout research_platform
./scripts/setup.sh                 # writes .env with a generated database password
# add SEC_USER_AGENT="Your Name you@example.com" — the SEC's fair-access policy requires a
# contact address, and the backfill below is the only thing in this project that ever needed it
docker compose up -d --build
docker compose exec -T api python -m tradeos.cli migrate
```

**The expensive part is the SEC backfill**, and there is no way around it: EDGAR is rate limited
by fair-access policy, not by anything this code controls.

```bash
docker compose exec -T api python -m tradeos.cli backfill-form4 --from 2024-07-01 --to 2026-08-12
docker compose exec -T api python -m tradeos.cli resolve-entities
docker compose exec -T api python -m tradeos.cli ingest-prices --symbols-from-clusters --start 2024-01-01
```

Measured cost: **about 35 minutes per week of Form 4**, so 25 months is roughly **76 hours**. It
resumes; it does not have to run in one pass. Weekends are skipped and market holidays return 404
and are logged past.

Then the computation itself, which is read-only and takes minutes:

```bash
docker compose exec -T api python -m tradeos.cli signals-register \
    --changelog "convergence_insider v2"
docker compose exec -T api python scripts/analysis/compute_v5.py
```

**The check that you reproduced this document and not something else:** the artifact it writes
must carry

```
definition : convergence_insider-v2
code hash  : ea6b6a98227b95b4
episodes   : 457      distinct symbols: 359
span       : 2024-07-02 .. 2026-08-12
```

A different code hash means the scoring module's source differs from the one measured here, and
the numbers above do not apply to it. That guard is the reason the hash is quoted rather than the
version alone.

`scripts/analysis/compute_v5.py` deliberately computes in memory and writes a JSON artifact rather
than storing clusters, because `signal_clusters` has no definition filter on any of its 30 read
sites — storing a third definition over a range an existing one already covers would make the
public calibration page double-count. The artifact this run produced is committed at
`docs/analysis/v5_episodes.json`, and the control run with routine insiders included is
`v5_episodes_with_routine.json`. They are byte-identical in their episode set, which is the claim
in §"the routine arm is empty" made checkable without re-running anything.

The full working record, including every one of the 59 tests and the cuts not summarised here, is
`docs/analysis/signal_edge_v5.md`. The earlier mixed-source version of the same question is
`docs/analysis/signal_edge.md`.

---

*Nothing in this document is investment advice. It is a measurement of a signal this project built
and then published the negative result for.*
