# Release plan — Receipts as a public, self-hostable project

Written 2026-09-22 as a plan. **Sections A, B, C, E, F, G, H and J were executed on 2026-09-23;
section K is still only specified.** The repository is private and stays private; no history has
been rewritten, no repository created, no visibility changed.

**Sections A–J below are left as they were written**, including the places where doing the work
proved them wrong, because the corrections are worth more than a tidy document. What actually
happened, and where the plan was mistaken, is in `docs/release_readiness.md`. Section K has been
rewritten, because it is the only part still to be carried out.

Every number here was measured on this machine on 2026-09-22 against the live stack, not estimated.
Where a figure is quoted from an earlier measurement its date is given, because undated figures in
this project have gone stale before.

The whole pre-extraction system is preserved at the tag **`research_platform`** (`845d689`, pushed
2026-09-22). Everything section B proposes dropping is runnable there, including the Tiingo adapter
that `main` has already removed and the research that produced section E.

---

## A. What `main` keeps

### A.1 The import closure, measured

An AST walk from every module in `tradeos/receipts/`, following `import`, `from x import y` and
relative imports at every level, transitively. **21 modules:**

| Module | Why it is reached |
|---|---|
| `receipts.{__init__,calls,chain,scoring,record,card,page,universe,verification,context,seed}` | the product |
| `backtest.engine` | `Series`, `entry_day_after`, `exit_day_for`, `excess_return`, `wilson_interval` |
| `ledger` | `price_series`, `verdict_for`, `NOISE_FLOOR`, `mean_ci`, `proportion_z`, `sample_needed` |
| `config` | `brand_name`, `public_base_url`, `alpaca_credentials` |
| `journal_context` | **only** via `receipts/context.py:21` — `from .. import journal_context` |
| `relevance`, `geography`, `trades`, `llm`, `explain`, `explain.guards` | transitively, through `journal_context` |

**The first thing to notice is the last row.** `docs/receipts_gap_analysis.md` §5.4 called this an
import-time-only collision and proposed a one-line lazy import. It is still live: `context.capture`
freezes "what the system was showing about this symbol" at publish time, and that snapshot is a
**sealed column** (migration 035). So the LLM chain, the relevance engine and the trade journal are
all still in Receipts' closure today.

My first AST pass reported 13 modules and missed this, because `from .. import journal_context` has
`module=None` and my resolver only handled `from ..pkg import x`. The corrected walk is above.
**Anyone re-deriving this graph should check that their walker handles that form** — it is the one
that hides a dependency.

### A.2 The routes `main` keeps — 33 of 146

```
/health
/api/auth/{register,registration,login,logout,me}
/api/auth/{verify,reset}/{request,confirm}
/api/auth/google/{start,callback}
/api/callers            /api/callers/me
/api/callers/verify/{start,confirm}
/api/admin/callers/pending          /api/admin/callers/{id}/verify
/api/calls              /api/calls/{scoreability,symbols,preview}    /api/calls/{call_id}
/api/receipts/methodology
/api/receipts/{handle}  /api/receipts/{handle}/verify   /api/receipts/{handle}/chain
/api/board
/api/card/receipt/{handle}.png      /api/card/receipt/{handle}.svg
/r/{handle}             /receipt-verify.js
```

`/api/card/{symbol}.svg` is in the grep above but belongs in section B — it is the Smart Money
share card, not the Receipts one.

### A.3 Also kept, outside the import graph

- **Price ingestion**: `ingestion/prices_alpaca.py`, `ingestion/common.py` (the `reject`/`redact`
  pair), and the `--universe` selector. **Alpaca only** — see section J and the Tiingo note below.
- **`cli`**: `migrate`, `ingest-prices`, `resolve-calls`, `verify-chain`, `seed-admin`,
  `seed-demo`, `seed-house-records`, `create-invites`, `status`, `preflight`, `scheduler`.
- **`scheduler.py`**, reduced to two jobs: `ingest_prices` and `resolve_calls`.
- **`scripts/`**: `setup.sh`, `backup.sh`, `backup-scheduled.sh`.
- **Infra**: `db.py`, `authn.py`, `apikeys.py`, `flags.py`, `ratelimit.py`, `mail.py`, `sources.py`,
  `oauth.py`, `onboarding.py` (or drop — see H), `app.py` (split, see below).
- **Frontend**: `board.jsx`, `record.jsx`, `publish.jsx`, `calldetail.jsx`, `methodology.jsx`,
  `receiptsui.jsx`, `shell.jsx`, `api.js`, `format.js`, `icons.jsx`, `brand.js`, `account.jsx`,
  `views.jsx` (auth panel only), `admin.jsx` (verification queue only), `styles.css`.

### A.4 The one structural change that should land with the deletion

`tradeos/app.py` is **3,841 lines and 146 routes**, and the deletion touches most of it. CLAUDE.md
says to split it by surface when a phase touches it. This is that phase: `tradeos/routes/receipts.py`
should be the file that survives, and the deletion is the cheapest time to do it because most of
what would have to be moved is being deleted anyway.

---

## B. What `main` drops

**77 of 98 modules, 111 of 146 routes.** Listed by subsystem, with the frontend surface and the
`scheduler.JOBS` / `sources.CATALOG` entry each one also requires removing — a module deleted
without its catalogue entry leaves the integration page describing a source that no longer exists.

| Subsystem | Modules | Frontend | Routes |
|---|---|---|---|
| **LLM + assistant** | `llm`, `explain/{base,gemini,template,guards}`, `intelligence/{analyst,vision}`, `assistant_tools` | `assistant.jsx` | 9 |
| **Event spine + ingestion** | `spine`, `claims`, `ingestion/{gdelt,news_rss,news_sec,news_adapter,social_bluesky,social_reddit,sentiment_hn,attention_wiki,calendar_nasdaq,derivatives,coingecko}` | `events.jsx`, `news.jsx`, `calendar.jsx`, `social.jsx` | 22 |
| **SEC ingestion + signal** | `ingestion/{edgar_client,form4,form13f,schedule13,runner,sgml,finra}`, `resolution/{entities,openfigi,tickers}`, `signals/{convergence,definitions,insider,opportunistic}`, `smartmoney_claims`, `backtest/run` | `smartmoney.jsx` | 14 |
| **Research surfaces** | `crypto`, `crypto_intel`, `news`, `sentiment`, `social`, `brief`, `dashboard`, `events`, `insights`, `portfolio`, `library`, `community`, `search`, `radar`, `exposure`, `watchlist_accounts`, `trades`, `journal_context`, `relevance`, `geography` | `crypto.jsx`, `journal.jsx`, `community.jsx`, `brief.jsx`, `dashboard.jsx`, `portfolios.jsx`, `discover.jsx`, `radar.jsx`, `radarfilters.jsx`, `exposure.jsx`, `globe.jsx`, `globe3d.jsx`, `coverage.jsx`, `world-110m.geo.json` | 58 |
| **Ledger (signal plane)** | `ledger` — **partially**: `mean_ci`, `proportion_z`, `sample_needed`, `NOISE_FLOOR`, `price_series`, `verdict_for` must MOVE to `receipts/stats.py` + `receipts/prices.py`, never be reimplemented | `ledger.jsx` | 3 |
| **Billing, alerts, misc** | `billing`, `alerts`, `admin` (most), `presentation` | `pricing.jsx`, `alerts.jsx` | 5 |
| **Marketing site** | — | `site/` (whole sibling project, 44 MB) | the `/site` mount |

**Line counts.** `tradeos/` is 23,632 lines of Python today; `receipts/` is 3,064 of them (13%).
The frontend is 9,309 lines of JS/JSX across 40 files; the Receipts surfaces are roughly 2,400.

**Two ordering constraints that are not optional:**

1. **Sever `receipts/context.py` FIRST** (§A.1). The honest option, per gap analysis §5.5, is to
   retire the snapshot: stop capturing, and store `context.empty(now, "the interpretation engine
   this recorded was retired on <date>")`. Deleting the engine while still calling `ranked_for`
   would return `[]` and record `n_live: 0, basis: "live"` — asserting *"we looked and there was
   nothing"* when the truth is *"there is no engine"*. `context_snapshot` is sealed, so old
   snapshots keep meaning what they meant; only new ones change.
2. **Repoint `/` to `/board` in the same commit that deletes `site/`** (gap analysis GAP 4), or a
   signed-out stranger lands on a research terminal.

**After every deletion step:** `make test`, then `cli verify-chain convergence-v3` (323),
`convergence-v4` (150), `a-real-stranger` (1). **If a link count or a head hash ever changes, stop.**

---

## C. Migrations

**Today: 37 ordered `.sql` files producing 64 tables.** A fresh Receipts install needs about 20.
The tables the `receipts` package and the kept routes actually touch:

```
calls  callers  caller_verifications  prices_eod  users  sessions  auth_tokens
login_attempts  api_keys  audit_log  feature_flags  invites  subscriptions
schema_migrations
```

(`claims` and `claim_outcomes` appear in `receipts/seed.py` only — see D.)

**Recommendation: a baseline migration for new installs; existing installs keep their history.**

- Add `tradeos/migrations/001_baseline.sql` in a **new numbering space** — or better, a
  `migrations/baseline/` directory selected when `schema_migrations` is empty. The runner in
  `db.py` already reads an ordered directory; this is a ~15-line change to choose which one.
- The baseline is `pg_dump --schema-only` of the kept tables, **including the 034/035/036/037
  triggers verbatim**. Those triggers are the product; a baseline that loses `calls_append_only`
  ships an append-only record that is not append-only.
- **Every migration must still insert its own `schema_migrations` row** (CLAUDE.md §9). The
  baseline inserts all of 1..37 so an existing database is never re-migrated.
- **The owner's database is untouched either way.** Nothing is dropped. Every table that is
  provenance for a sealed call — `claims`, `claim_outcomes`, `signal_clusters`,
  `insider_transactions` — stays exactly as it is, because `seed-house-records` read them and the
  473 calls it wrote are sealed forever. Deleting their provenance would make the house record
  unauditable by us, which is the one thing we ask no one else to accept.

**Verification before shipping the baseline:** migrate an empty database from the baseline, then
from the 37 files, and diff `pg_dump --schema-only` of both. They must be identical.

---

## D. The house records, as a static verifiable export

The 473 sealed house calls live only in the owner's database. They are the project's best asset
precisely because the record is bad, and the first thing a visitor should be able to check.

### D.1 The redistribution question, answered

**All 473 house calls store zero prices.** Measured: `entry_price`, `exit_price`,
`benchmark_entry`, `benchmark_exit` are NULL on every one — `claim_outcomes` stored the excess
return and the entry day, never the component prices. Across the whole `calls` table, **0 of 474**
rows carry a price.

So a house export contains only: the ten sealed fields, `prev_hash`, `content_hash`, the verdict,
the excess return (a derived percentage) and two session dates. **No third-party price data. It is
redistributable.** See section J for why that is not luck but a constraint to design around.

### D.2 The export

```
export/
  convergence-v3.json      # {handle, display_name, is_house, fields[], genesis, links[]}
  convergence-v4.json
  MANIFEST.json            # sha256 of each file, the chain head of each, the export timestamp
  verify.mjs               # runs anywhere node runs; no dependencies, no network
  README.md
```

`links[]` is exactly what `GET /api/receipts/{handle}/chain` already returns — the sealed fields
rendered by `chain.rendered_fields`, plus `prev_hash` and `content_hash`. The export is therefore
`curl` plus a file write, and the format is already pinned by `tests/verify_js_check.mjs`.

`verify.mjs` should be **`tradeos/receipts/verify.js` itself**, not a copy. It already exports
`framePayload` and `verifyChain`, it already runs under node, and a second implementation of a
frozen wire format is the one thing this project has been most careful to avoid.

Add `cli export-house-records --out export/` and a CI job that runs `node export/verify.mjs` on
every push, so a broken export cannot be published.

### D.3 The one thing the export must say

The house records were **imported from an already-scored ledger and sealed together on 2026-09-02,
after their outcomes were known** — unlike every call published through the product, which is
sealed at publication. `receipts/page.sealing_line()` already says this on the record page and the
export's README must say it too. Publishing "sealed before the outcome was known" over these 473
would be the exact overclaim the product exists not to make.

And the numbers, unflattering, in the export's own README: **43.2% of 412 resolved, z = −2.76,
expectancy −1.18% with a 95% interval of [−2.93%, +0.57%] that spans zero.** Never presented as a
positive result.

---

## E. `docs/research/insider_buying.md`

Built from `docs/analysis/signal_edge.md` and `signal_edge_v5.md`, both of which stay in the repo
as the working record. The new document is the publishable form.

**Frame, in this order:**

1. **What was tested.** A pure Form 4 open-market-purchase signal: clusters of independent insider
   buys on one issuer inside a short window, scored as excess return against SPY.
2. **The window.** July 2024 to August 2026. Two years and one month.
3. **The method.** 60,708 open-market purchases → 251,688 gate clusters → 25,504 published →
   457 episodes after 14-day de-duplication, across 359 distinct issuers. Point-in-time throughout:
   `knowable_time`, never the filing date.
4. **The result.** **−3.40% mean excess versus SPY at 90 days, 95% interval [−5.40%, −1.40%],
   n=442. −7.21% at 180 days, [−10.45%, −3.96%], n=352. Hit rate 34.9% at 180 days, 5.65 standard
   errors below a coin flip.** The signal does not merely fail to predict; over this window it
   predicted the wrong way.
5. **The one positive cut, and why it should not be believed.** Opportunistic-voices-only:
   +3.61% at 30 days, +4.26% at 90. Neither interval excludes zero, n=31, and it is **one of 59
   tests run**. Reporting it as a finding would be the multiple-comparisons error this document
   exists to avoid.
6. **Why this may differ from the literature.** Lakonishok–Lee, Jeng–Metrick–Zeckhauser and
   Cohen–Malloy–Pomorski cover decades. This is **25 months**, one regime, one clustering rule, one
   benchmark, one liquidity profile. It is also worth stating that the Cohen–Malloy–Pomorski
   routine/opportunistic split could not be applied here in any meaningful way: **of 60,708
   purchases, 27 classify as routine, and none of the 27 reaches a published cluster.** Running the
   whole computation with routine insiders counted as voices produces a byte-identical set of 457
   episodes.

   **It must not claim that insider buying does not work in general.** The honest claim is: *this
   construction, over this window, measured this.*
7. **Reproduction.** `git checkout research_platform`, then the exact commands, then
   `scripts/analysis/compute_v5.py`, and the check that the answer matches: definition
   `convergence_insider-v2`, module hash `ea6b6a98227b95b4`. Note that this needs the SEC backfill
   (~76 hours of Form 4 at the measured 35 min/week) or a restore of the owner's `raw_filings`.

---

## F. The public files

**`README.md`, in this order and no other:**

1. **One sentence.** "A public, permanent record of market calls: publish a dated call before the
   outcome is known, and anyone can check it was never edited."
2. **A screenshot of `/r/{handle}`** at 375px, showing the sealing line, the counts with the miss
   count larger than the hit count, and the Verify control.
3. **Sixty-second quickstart** — section H is the tested version of this.
4. **What a caller does.** Claim a handle → publish a symbol, direction, 7/30/90-day horizon and a
   reason → it seals → it resolves itself → share the link.
5. **What a visitor can verify.** Press one button; their own browser downloads every sealed call
   and recomputes every SHA-256 on their device. Say the measured number: **323 links in 9 ms.**
   And mention the demonstration: the page will break its own record in front of you so you can
   watch the check say no.
6. **What it does NOT guarantee**, in the same words the page uses, from
   `record.methodology()["chain"]["does_not_prove"]`:

   > The chain does not prove that WE have not rewritten it. We hold every field, so this operator
   > could edit a call and recompute the whole chain after it. Making that impossible needs an
   > anchor outside our control, publishing the chain head daily somewhere we cannot revise, and
   > that is not built yet. This is not a blockchain and we do not call it one.

   Plus the sample gate (no rate below 25 resolved), the 2% noise floor, and the IEX thin-name
   caveat: on the least liquid symbols the two feeds measured disagreed by 2.86%, **larger than the
   noise floor**, and a verdict is sealed and never revised.
7. **A link to the research** (section E), stated as what it is: our own signal, measured, negative.

**Also:** `LICENSE` (MIT), `SECURITY.md` (how to report, what is in scope, the known gaps in
`docs/known_gaps.md` §1–5), `CONTRIBUTING.md` (`make test` + `make test-js` + `make lint`, the
frozen-wire-format rule, the "never quote a rate without its interval" rule), and a plain statement
— in the README, the footer and `SECURITY.md` — that **nothing here is investment advice**. The
string already exists as `RECEIPTS_DISCLAIMER` and should be read from there, not retyped.

One small thing the public page currently gets wrong: **`/favicon.ico` 404s** on every visit
(observed in the browser network log). Add one.

---

## G. Naming

Three names today: the page and card say **Rhumb**, the Python package is **tradeos**, the feature
is **Receipts**.

**Recommendation: call the public project `Receipts`.** It is what the thing is, it is what the
README's first sentence says, and it is the only one of the three that a stranger can guess the
meaning of. "Rhumb" is a good product name with no equity behind it yet; keeping it would mean
explaining it. Use `Receipts` as the repository and project name, and keep `BRAND_NAME` configurable
so a self-hoster can put their own name on their own board — which is already how the display name
works.

**The cost of renaming the Python package, measured, so the decision is informed:**

- `tradeos` appears in the package path, 37 migration files' comments, `docker-compose.yml`,
  `Dockerfile`, `Makefile`, `pyproject.toml`, every test import, and the Postgres role/database
  names.
- Mechanically: ~**1,100 occurrences across ~150 files**, plus a database role rename and a
  `pgdata` volume that was initialised with `POSTGRES_USER=tradeos`.
- The real risk is not the rename, it is that **`schema_migrations` and the append-only triggers
  are matched by name**, and a half-finished rename against a live database is how a sealed table
  loses its trigger.

**Do not rename the package.** CLAUDE.md already forbids renaming Python modules or database tables
for branding, and that rule was written for exactly this moment. The public name lives in
`config.brand_name()` and `frontend/src/brand.js`; the package stays `tradeos`, and the README says
in one line why.

---

## H. The ten-minute test

Every step a stranger takes, in order. Times are measured where the command has been run.

| # | Step | Time | Status |
|---|---|---|---|
| 1 | `git clone` | 20 s | ok |
| 2 | Get a free Alpaca key at `app.alpaca.markets/signup` — email, password, confirm | ~3 min | ok, no card |
| 3 | `./scripts/setup.sh` — writes `.env` with a generated DB password | 1 s | ok, tested |
| 4 | Edit `.env`: paste `ALPACA_API_KEY_ID`, `ALPACA_API_SECRET_KEY`, set `SEC_USER_AGENT` | ~1 min | **FAILURE — see below** |
| 5 | `docker compose up -d --build` | ~2 min first build | ok |
| 6 | `cli migrate` | 3 s | ok |
| 7 | `cli ingest-prices --universe --limit 400 --start <1y ago>` | **19 s measured** | ok |
| 8 | `cli seed-admin` / register a caller in the UI, claim a handle | ~1 min | ok |
| 9 | Publish a call on AAPL | ~30 s | **ok, proven on a fresh database** |
| 10 | Open `/r/<handle>`, press Verify | 1 s | ok |

**Total: about eight minutes.** Inside the bar, with two failures to fix first:

- **FAILURE 1 (step 4): `.env.example` demands `SEC_USER_AGENT` under "required", for data the
  product no longer fetches.** Checked, and it is *not* a hard startup failure — the app imports
  and serves 149 routes with it empty, because `config.sec_user_agent()` is called only inside the
  SEC command bodies and the scheduler's SEC job. What actually happens is softer and still wrong:
  the template tells a stranger it is required, `cli preflight` fails on it, and `docker-compose.yml`
  interpolates `${SEC_USER_AGENT}` with no default so every compose command warns. With SEC
  ingestion dropped (section B) the only remaining consumer is `ingestion/finra.py`, which is also
  dropped. **Fix: remove the variable, the config accessor, the preflight check and both compose
  lines.** A stranger should not be asked for a fair-access contact address for an API this product
  never calls.
- **FAILURE 2 (step 7): the universe command is undocumented and the flag names are not guessable.**
  `--universe --limit 400 --start <date>` appears in no README. **Fix: `scripts/setup.sh` prints
  the exact line, and the README quickstart carries it.** Better: a `cli quickstart` that runs
  migrate + a 400-symbol universe load + prints the publish URL.
- **Watch item:** the full 13,170-symbol universe takes **12,395 s** (measured, under concurrent
  load). `--limit 400` at 19 s is the right quickstart default, with the full load documented as an
  overnight job.
- **Watch item:** `onboarding.py` shows a first-run Radar setup card. The Radar is being deleted.
  Drop the card or it configures a surface that no longer exists.

---

## I. Before and after

| | Before (`research_platform`) | After (`main`, planned) |
|---|---:|---:|
| Python modules | 98 | 21 |
| Python lines (`tradeos/`) | 23,632 | ~5,500 |
| `app.py` lines / routes | 3,841 / 146 | ~700 / 33 (split into `routes/`) |
| Frontend files / lines | 40 / 9,309 | ~15 / ~2,400 |
| Frontend bundle (gzipped) | 124 KB JS + 25 KB CSS | ~45 KB JS + ~12 KB CSS |
| Migrations | 37 | 1 baseline (+37 kept for existing installs) |
| Tables on a fresh install | 64 | ~14 |
| Tests | 990 | ~450 |
| External sources needed | 12 | **1** (Alpaca) |
| Keys needed to run | `SEC_USER_AGENT` + 6 optional | **2** (`ALPACA_API_KEY_ID`, `_SECRET_KEY`) |

The public record page itself does not change: 12.8 KB over the wire, FCP 620 ms, LCP 727 ms,
CLS 0.00 at 375px on Slow 4G with 4× CPU throttling.

---

## J. Alpaca display terms — **this blocks showing raw prices**

**Source: Alpaca support, "Can I redistribute Alpaca API data via my platform?", dated November
2022** (`https://alpaca.markets/support/redistribute-alpaca-api`). Quoted verbatim, in full:

> "Unfortunately, you cannot redistribute Alpaca API data."

There is no personal/commercial distinction, no exception for display, and no qualification of any
kind. Alpaca's Terms and Conditions additionally incorporate the NASDAQ OMX Global Subscriber
Agreement and the Agreement for Market Data Display Services by reference, both of which carry
their own display-service restrictions.

**Plainly: no, it does not permit this.** Publishing entry and exit prices obtained from an Alpaca
key on a public page that anyone can read is redistribution on the ordinary meaning of the word,
and the one sentence Alpaca publishes on the subject does not carve out an exception this product
could rely on.

**What is exposed today: nothing.** `GET /api/calls/{id}` is public and returns the four price
columns, but all 474 sealed calls have them NULL, so the live surface leaks no price data. **The
moment a call resolves through the current scorer, `scoring._write` stores all four and the public
page would begin displaying them.** `@a-real-stranger`'s open call is the first that will do this.

**Plan: the public surfaces show excess return and dates, never raw prices.**

1. Drop `entry_price`, `exit_price`, `benchmark_entry`, `benchmark_exit`, `subject_return` and
   `benchmark_return` from the **public** payloads: `receipts/calls._SUMMARY_FIELDS` and the
   `/api/calls/{id}` response. Keep `excess_return`, `entry_session`, `exit_session`,
   `verdict`, `verdict_note`.
2. Keep storing them. They are the audit trail, they are sealed by migration 035, and a caller
   must be able to see the arithmetic on **their own** call. Gate the full proof panel behind
   "this is your call" or an operator session.
3. `calldetail.jsx`'s proof panel becomes, for a visitor: the two sessions, the excess return, the
   noise floor, the benchmark symbol and the rule — which is enough to check the verdict follows
   from the number, without republishing anyone's price feed.
4. **This makes the house records the model rather than the exception.** They already show exactly
   this shape, because their prices were never stored. The public page has been rendering the
   compliant version all along.
5. Say it on the methodology page: prices come from a vendor whose terms do not permit
   redistribution, so the site publishes the measurement and not the prices.

A self-hoster using their own key is in the same position, which is why this belongs in the product
rather than in a note to the owner.

---

## K. The history rewrite — specified, NOT executed

**Updated 2026-09-23, after sections A, B and C were executed.** Still not executed: no history has
been rewritten, no repository created, no visibility changed. The repository is private.

**THIS SECTION NAMES NO SENSITIVE STRING.** Every literal to be found and replaced lives in

```
~/receipts_release/expressions.txt        (mode 600, outside the repository, never committed)
```

in `git filter-repo --replace-text` syntax, one `literal==>replacement` per line. That file is the
input to K.2 and it is the only place the strings appear. Writing them here would put a copy of
each secret into the history being rewritten, in the document explaining how to remove it — the
fifth copy, created by the cleanup. It also means this section can be read by anyone.

### K.0 What HEAD now contains, measured

The sweep the readiness gate runs, over every tracked file at HEAD:

| what | hits at HEAD |
|---|---:|
| the owner's email address | **0** |
| the GDELT operator's email address | **0** |
| the personal path | **0** |
| the previous demo password | **0** |
| the development database password | **1** |

The single remaining hit is a **negative assertion** in `tests/test_sources.py`: it reads
`docker-compose.yml` and asserts that a connection string carrying the old default password is
**not** in it. The literal is the thing being forbidden, so the guard cannot be written without it,
and removing the literal would remove the check that keeps the default from coming back. It is
listed in `expressions.txt` anyway, because a rewrite that replaces it leaves the assertion reading
`assert "<replacement>" not in compose`, which still passes and still means the same thing.

The other four are zero **at HEAD** and non-zero **in history**, which is the entire reason this
section exists. `git log --all -p` still carries them.

### K.1 Paths to remove from every commit

```
docs/TRADEOS_HANDOVER.md
docs/research/2026-09-14/            (entire directory, including .work/ and the .docx/.pdf files)
docs/TRADEOS_INVENTORY.md
```

`docs/archive/` is **kept** — its documents are honest engineering history, and the audit found
nothing in them beyond the personal path, which K.2 replaces.

**Note added 2026-09-23:** `docs/research/2026-09-14/` also has uncommitted working-tree changes
parked in `git stash@{0}` from the start of this task. A stash is a ref, so `filter-repo` would
see it in the source repository — but K.6 operates on a `--no-local` CLONE, and `git clone` does
not carry stashes. Confirm with `git stash list` in the clone: it must print nothing.

### K.2 Strings to replace in every commit

Run `git filter-repo --replace-text ~/receipts_release/expressions.txt`. Do **not** use
`filter-branch`.

The file covers, in this order: two email addresses, the personal path in two forms (the full
repository path first, then the home directory, because filter-repo applies replacements in file
order and the longer match must win), the previous demo password, and two forms of the development
database password. Seven expressions.

### K.3 Unreachable objects

Three existed locally before this task: an abandoned 2026-09-02 draft commit and two stashes. One
more stash was created at the start of this task (K.1). **`git filter-repo` operates on refs and
`git clone --no-local` copies only reachable objects**, so none of them is carried into the new
repository. Confirm after cloning the rewritten repo:

```bash
git fsck --unreachable --no-reflogs        # must print nothing
git stash list                             # must print nothing
```

### K.4 Proof that nothing sealed depends on a git SHA or on a rewritten file

Answered by construction rather than by inspection, because this is the question that decides
whether the rewrite is safe.

1. **The chain hashes only ten database columns.** `chain.SEALED_FIELDS` is `caller_id, seq,
   symbol, direction, horizon_days, confidence, thesis, benchmark_symbol, published_at,
   knowable_time`. Every one is a value in the `calls` table. **No git SHA, no file path, no file
   content, no source hash is an input.** `content_hash = sha256(prev_hash + payload)`, and nothing
   else.
2. **The files being rewritten are documentation and one test fixture.** `docs/**` and
   `tests/test_gdelt.py`. None is read by `chain.py`, `calls.py` or `scoring.py`. *(The other file
   named in the previous version of this section, `ingestion/finra.py`, was deleted outright in
   section B.)*
3. **The `module_code_hash` guard was on the signal plane, and the signal plane is gone.**
   `signals/definitions.py` hashed `signals/convergence.py`'s source to decide whether to register
   a new version. It read that one module's bytes — not a git object, not any file in K.1 or K.2.
   Nothing in `receipts/` called it, and section B deleted it.
4. **The empirical proof, run before and after on the same database:**

   ```
   cli verify-chain convergence-v3    # 323 links, head c9f480e0a79a28c7
   cli verify-chain convergence-v4    # 150 links, head 24df0daed4f23ccd
   cli verify-chain a-real-stranger   #   1 link,  head 79de970e41a46b35
   make test-js                       # the wire format, from JavaScript, plus export/check.mjs
   ```

   These three heads were recorded on 2026-09-22 and **re-verified unchanged after every commit in
   sections A, B and C** — after 68 modules were deleted, after the Ledger was split, after the
   migration baseline was introduced. They are database facts and the rewrite does not touch the
   database, so they must be byte-identical afterwards. If any head moves, something other than
   the rewrite has happened.

5. **New in this task: the export is a second, offline proof.** `export/` holds both house chains
   and `check.mjs`, which recomputes them with no server and no database. It is committed, so a
   rewritten repository carries it, and `node export/check.mjs` on a fresh clone of the rewritten
   repo must print the same two heads as line 4. That check depends on no git object and no
   running instance, which makes it the strongest available evidence that the rewrite changed
   nothing about the record.

### K.5 Verification on the rewritten repository, before anything is pushed

All three must pass.

```bash
# 1. secret scan over the full rewritten history, all refs
docker run --rm -v "$PWD:/repo" -w /repo zricethezav/gitleaks:latest \
  git --log-opts="--all --full-history" --redact --no-banner
#    -> "no leaks found", and the commit count must equal (commits - merges)

# 2. the sensitive-string sweep, over every blob in every commit, reading the patterns from the
#    file rather than from this document
git log --all --full-history -p --format="COMMIT %H" > /tmp/hist.txt
cut -d'=' -f1 ~/receipts_release/expressions.txt | grep -v '^#' | grep . \
  | while read -r s; do printf '%s: ' "$s"; grep -c -F -- "$s" /tmp/hist.txt; done
#    -> every count 0, EXCEPT the development database password, which survives as the negative
#       assertion described in K.0 — and only in its replaced form

# 3. the paths removed by K.1 appear in no commit
git log --all --full-history --pretty=format: --name-only \
  | sort -u | grep -E 'TRADEOS_HANDOVER|docs/research/2026-09-14|TRADEOS_INVENTORY'
#    -> must be empty
```

Then a functional check, because a rewrite that passes every scan and does not run is still a
failure. This is the ten-minute test again, on the rewritten clone:

```bash
./scripts/setup.sh                 # then paste an Alpaca key pair into .env
make quickstart                    # measured 84s on a clean clone
make test && make test-js && make lint
node export/check.mjs
```

### K.6 Pushing into the new repository

The owner creates an **empty** repository — no README, no LICENSE, no .gitignore, or the first push
will not be a fast-forward.

```bash
git clone --no-local /path/to/tradeos /tmp/receipts-public   # a copy; the original is untouched
cd /tmp/receipts-public
git remote remove origin                                     # so nothing can push to the old remote
# ... run filter-repo per K.1 and K.2, then K.5 ...
git remote add origin git@github.com:<owner>/receipts.git
git push -u origin main
```

`--no-local` forces a real object copy rather than hardlinks, so `filter-repo` in the clone can
never touch the original's object store. Verify before pushing:
`git -C /path/to/tradeos log --oneline -1` must still be the original HEAD.

**The `research_platform` tag is the decision point, and it now matters more than it did.**
`docs/research/insider_buying.md` tells a reader to `git checkout research_platform` and reproduce
the result from there. If the tag is not published, that document describes a reproduction nobody
can perform, which is the exact failure this project argues against.

The tag contains the whole research plane, which is fine, and every file K.1 removes, which is not.
**Recommendation: rewrite the tag with the same expressions and publish it**, then re-run K.5
against the tag before pushing it. If it is kept private instead, `insider_buying.md`'s
reproduction section has to say so plainly rather than give commands that cannot be run.

## What is decided, and what is not

**Decided and done:** the security fixes at HEAD, the credential rotation, the universe rebuild,
Tiingo's removal, the `research_platform` tag.

**Decided, not done:** everything in A–I and K. This document is the specification.

**Not decided — the owner's calls:**

1. Whether to publish the `research_platform` tag or keep it private (K.6).
2. Whether the public name is `Receipts` or `Rhumb` (G).
3. Whether the full proof panel is gated to the caller, or the price columns are simply dropped
   from the public payload (J.2).
4. What to do with the 34,847 legacy Tiingo price rows. **Recommendation: keep them, unused.**
   They are the only independent measurement of the Alpaca feed this project has, they are what
   `docs/analysis/alpaca_vs_tiingo.md` was computed from, and deleting them would make that
   measurement unreproducible. They are not redistributed, not displayed and not read by any kept
   code path. If they must go, export the 1,324 day-pair comparison first.
