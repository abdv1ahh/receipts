# Alpaca vs Tiingo — price source validation

**Written 2026-09-13.** Status: **PREPARED, NOT YET MEASURED — blocked on an Alpaca API key.**

The comparison is a single command and the symbols are already chosen. It has not been run because
no Alpaca credential exists on this machine: `.env` contains no `ALPACA_*` variables and neither
does the environment. **Nothing was switched over on the strength of an assumption** — per the
brief, a mean absolute difference above 0.5% stops the migration, and a gate you have not measured
is not a gate.

---

## Why the source is being replaced

Not because Tiingo is inaccurate. Because its free tier makes a complete refresh **impossible**, and
the way it fails is biased rather than random.

Tiingo free allows roughly **50 requests an hour**, **500 unique symbols a month**, and — the part
that actually breaks things — **one symbol per request**. A 500-symbol top-up is therefore 500
requests against a 50/hour ceiling. It cannot finish. And because every selector in
`backtest/run.py` ordered its work list `ORDER BY symbol`, every run walked the alphabet and died in
roughly the same place.

**That produced a measurable, systematic bias, not random staleness.** Measured 2026-09-13 against
the live table:

| First letter | Symbols | Avg bars held | Newest bar |
|---|---:|---:|---|
| A | 103 | 566 | 2026-09-01 |
| B | 46 | 656 | 2026-09-01 |
| C | 76 | 541 | 2026-09-01 |
| … | | | 2026-09-01/02 |
| P | 20 | 680 | **2026-09-02** |
| **Q** | 2 | 1313 | **2026-08-21** |
| **R** | 9 | 509 | **2026-08-21** |
| **T** | 9 | **149** | **2026-08-21** |
| **U** | 6 | **160** | **2026-08-21** |
| **V** | 6 | **129** | **2026-08-21** |
| **W** | 5 | **155** | **2026-08-21** |
| **X** | 1 | **160** | **2026-08-21** |
| **Y** | 1 | **160** | **2026-08-21** |

Two cliffs, both alphabetical. **Everything from Q onward is eleven days staler than A–P**, and the
deep history thins from ~550 bars to ~150 once you pass S. A symbol's data quality in this database
depended on its first letter.

Alpaca's free tier allows **200 requests/minute**, unlimited historical bars, 7+ years of history,
and **many symbols per request**. 500 symbols becomes five requests. The constraint disappears
rather than being rationed, which is why the fix is a source swap and not a smarter scheduler.

**The ordering bug is fixed independently of the source swap**, because it is a correctness bug in
its own right: a truncated run must leave the table *evenly* stale, not biased. All four selectors
now order oldest-data-first with an `md5(symbol)` tie-break, held by four tests in
`tests/test_price_worklist_order.py`.

---

## What has to be checked before switching

**The free Alpaca tier serves the IEX feed, not the consolidated tape.** IEX is one exchange
carrying roughly 2–3% of US equity volume, so a daily close computed from IEX prints can differ from
the official consolidated close Tiingo reports — most visibly on thin names. This is recorded in the
`prices_alpaca` module docstring and is **not hidden**.

The question is whether that difference is small enough to be irrelevant. It plausibly is: every
outcome in this product is an **excess return against SPY** over 7, 30 or 90 days, both legs come
from the same feed so a systematic feed offset largely cancels, and `receipts.scoring` already
applies a **2% noise floor**. A few basis points of close-price noise sits far underneath that.

**Plausible is not measured.** Hence the gate.

---

## Method

- **25 symbols**, one per first letter A–Y, each holding more than 120 Tiingo bars.
- **10 of the 25 are after P** — far more than the three required, because the post-P tail is
  precisely the biased region and the one most likely to show a difference.
- Tiingo closes are read **straight from `prices_eod`** (`source LIKE 'tiingo%'`). No Tiingo API
  call is made and no Tiingo quota is spent.
- Alpaca is fetched live over the same window in **one batched request**.
- Compared **day by day on shared trading days only**; days present in one source and not the other
  are counted separately rather than silently dropped, because a missing session is its own finding.

The 25 symbols:

```
AAT, BA, CACC, DMLP, ELAN, FBIN, GABC, HUBS, IRD, JCTC, KNSL, LWAY, MED,
NCLH, OCFC, PAHC, QTRX, ROCK, SPY, TKO, UA, VITL, WGS, XPOF, YEXT
```

## The command

```bash
docker compose exec -T api python -m tradeos.cli compare-prices \
  --symbols AAT,BA,CACC,DMLP,ELAN,FBIN,GABC,HUBS,IRD,JCTC,KNSL,LWAY,MED,NCLH,OCFC,PAHC,QTRX,ROCK,SPY,TKO,UA,VITL,WGS,XPOF,YEXT \
  --start 2026-06-02 --end 2026-08-21
```

The window ends **2026-08-21** deliberately: that is the newest bar the post-P symbols hold, so the
comparison covers days where *both* sources have data for *every* symbol, including the stale tail.

Output is JSON: per-symbol day counts, exact matches, mean absolute percentage difference, the
single largest divergence with its symbol and date, and a `verdict` field that applies the gate.

---

## Results

> **NOT YET RUN.** Requires `ALPACA_API_KEY_ID` and `ALPACA_API_SECRET_KEY`. Paste them into `.env`,
> run `docker compose up -d api worker` (the compose file enumerates variables explicitly, so a
> value in `.env` alone does not reach the container), then run the command above and fill in this
> section.

| Metric | Value |
|---|---|
| Symbols compared | — |
| Total day-pairs compared | — |
| Exact close matches | — |
| **Mean absolute % difference** | — |
| Largest single divergence | — |
| Days Tiingo-only / Alpaca-only | — |

### The gate

| Outcome | Action |
|---|---|
| **mean abs diff ≤ 0.5%** | PASS. Proceed to the backfill and make Alpaca the price source. |
| **mean abs diff > 0.5%** | **STOP.** Do not backfill. Report and investigate before switching. |

The command computes `verdict` itself so the decision is not left to someone eyeballing a number.

### What a failure would most likely mean

Worth writing down in advance, so a bad result is diagnosed rather than panicked over:

- **A handful of thin names dominating the mean** — check the `worst` field and the per-symbol
  table before condemning the feed. An IEX close on an illiquid name is the expected weak point.
- **A systematic offset across every symbol** — points at an adjustment mismatch, not a feed
  difference. Tiingo rows here are split/dividend adjusted (`tiingo:adjusted`) and the Alpaca
  request uses `adjustment=all`; if one side were unadjusted, dividend-paying names would diverge
  progressively rather than randomly.
- **Large `tiingo_only` day counts** — a session Alpaca has no IEX print for. That is a coverage
  gap, and it matters more than a small price difference, because a missing exit price leaves a
  call OPEN rather than scored.

---

## Backfill baseline (measured 2026-09-13, before any Alpaca fetch)

So the after-numbers have something to be compared against:

| Metric | Value |
|---|---:|
| Distinct symbols in `signal_clusters` | **344** |
| …with any price history | **311** |
| …with **none** | **33** |
| Distinct symbols in `prices_eod` | 500 |
| Symbols with a bar at the latest real session (2026-09-08) | **0** |

The 33 with no prices at all, by first letter: A 8 · B 3 · C 3 · D 1 · F 3 · G 3 · I 4 · P 3 · S 3 ·
V 2.

Note that `prices_eod` holds **500** symbols while only **344** are cluster symbols — the table
carries names no longer behind any cluster. The backfill targets the cluster set, which is the set
that actually has to be scoreable.
