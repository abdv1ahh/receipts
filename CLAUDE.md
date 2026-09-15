# CLAUDE.md — operating manual for this repository

Read this first, every session. Then read `docs/state.md` (where the work stands) and
`docs/plan.md` (where it is going).

Every command below has been run and verified. If you find one that does not work, fix it
here in the same change that discovers it — a wrong command in this file is worse than no
command.

---

## What this is

**Internal codename: TradeOSS. Display name: Rhumb** (`BRAND_NAME`). A world-event interpretation
engine that explains market consequences. The product brief is
`docs/tradeoss_veryimportant_prompt.md` — the source of truth for scope. **All ten phases (0–9) are done.**
`docs/state.md` has the resume instructions and what remains; `docs/progress/phase_9.md`
§"What is NOT fixed" is the honest security list.**

**RECEIPTS is now the product** (`tradeos/receipts/`, migration 034, added 2026-09-02). A public,
permanent, chained record of market calls: a caller publishes a dated directional call BEFORE the
outcome is known, it is sealed into a per-caller SHA256 hash chain, and a database trigger refuses
every delete and every update to a sealed column. It resolves automatically against Tiingo prices,
benchmarked to SPY, with a 2% noise floor and a 25 call sample gate. Anyone can hit **Verify chain**
and watch every hash recompute. Surfaces: `/board` (the landing route) `/record` `/publish`
`/call` `/methodology`, plus the public share page `/r/{handle}` and card
`/api/card/receipt/{handle}.svg`.

**The first two records on the board are OURS** — `@convergence-v3` (323 calls) and
`@convergence-v4` (150), imported from the signal plane's own resolved claims by
`cli seed-house-records`. Pooled they read **43.2% of 412**, below a coin flip, with an expectancy
interval that spans zero. That is the point and it must never be presented as a positive result.

The rest still stands behind it: a claim engine (`claims.py`), the self-scoring Ledger
(`ledger.py`), an event spine (`spine.py`), personal relevance (`relevance.py`), world context
frozen at trade time (`journal_context.py`), and the research surfaces `/home` `/ledger` `/events`
`/crypto` `/news` `/journal` `/watchlist` `/integrations` `/assistant` `/search`.

`/radar` `/globe` `/exposure` `/library` `/community` are **off the navigation rail** but still in
`ROUTES` — they are empty or thin, and a rail that leads a reader to an empty page has spent the
one thing this product is selling. They stay addressable because other surfaces link to them.

**`/` is the marketing site for anyone signed out** (307 to `/site/`, decided on the presence of
the session cookie so no database round trip is needed). The app's own landing page was deleted: it
still pitched the pre-rebrand product and nothing linked to it. Signing out returns you to `/site/`.

The display name is a config value, not a hardcoded string (see `docs/plan.md` §rebrand).
Never rename Python modules, database tables, or the `tradeos` package for branding. It has exactly
two homes — `config.brand_name()` in Python and `frontend/src/brand.js` in React — and **neither is
optional**: for eight phases the rebrand reached only the nav bar while fourteen strings across nine
files still read "TradeOSS" to the reader. If you are typing the product's name in a string, stop.

---

## Stack (verified versions)

| Layer | What | Version |
|---|---|---|
| Runtime | Python | 3.12.13 |
| API | FastAPI + Starlette, served by uvicorn | 0.139.2 / 1.3.1 |
| DB driver | psycopg (v3, binary) | 3.2.9 |
| Database | PostgreSQL (Docker `postgres:16`) | 16.14 |
| HTTP client | httpx | 0.28.1 |
| Images | Pillow | 12.3.0 |
| XML | defusedxml | 0.7.1 |
| Auth | argon2-cffi, pyotp (TOTP for admins) | 23.1.0 / 2.9.0 |
| Tests | pytest | 9.0.3 |
| Frontend | React + Vite. Routing is ~40 lines over the History API in `shell.jsx`; no state library, no CSS framework | 18.3.1 / 5.4.21 |
| Node (build) | node / npm | 24.18 / 11.16 |

Ruff is the linter (not the formatter — see the note in `pyproject.toml`). There is **no ORM**
(raw SQL through psycopg), **no migration framework** (ordered `.sql` files run by
`tradeos/db.py`), and **no dependency injection / event bus / state machine**.
Keep it that way. `requirements.txt` is 10 lines. Adding to it is a decision, not a reflex.

---

## Commands

All of these are run from the repository root.

### Run the app

```bash
docker compose up -d --build          # api :8000, postgres :5432, worker (scheduler)
docker compose logs -f api            # follow API logs
docker compose logs -f worker         # follow scheduler logs
docker compose down                   # stop
```

The app is at <http://localhost:8000>. Demo login: `demo@tradeos.app` / `<generated at seed time>`
(tier `pro`, no MFA, populated with trades and portfolios).

### Tests

```bash
make test     # 904 tests, ~3.6s. Offline except the DB-backed authz and Receipts integrity tests
make lint     # ruff; zero errors is the standard
make dev      # reload-in-place stack; then `make web` for a UI change
make fix      # ruff --fix
```

`tests/` is deliberately not copied into the production image, so the suite runs against a mount.
`make test` does that for you.

### Frontend

```bash
make dev      # once: starts the reload-in-place stack
make web      # after every APP UI edit (~0.3s) — this is what makes the change visible
make site     # same, for the marketing site at /site (needs `cd site && npm install` once)
```

**In production the bundle is baked into the image at build time** (`Dockerfile` stage 1 copies
`/web/dist` to `/app/tradeos/static`), so without `make dev` a UI change needs a full
`docker compose up -d --build`. `docker-compose.dev.yml` mounts `frontend/dist` over that path
instead, which is why `make web` alone is enough. `frontend/dist/` and `tradeos/static/` are
gitignored.

### Data / operations CLI

```bash
docker compose exec -T api python -m tradeos.cli <command>
```

All 44, checked against `--help` rather than remembered:

`migrate`, `preflight`, `status` · **SEC ingestion** `ingest-form4`, `ingest-13dg`, `ingest-13f`
`backfill-form4`, `backfill-13dg`, `backfill-13f` (`--from`/`--to` over a date range; weekends skipped, holidays 404 and
are logged past) · **resolution** `sync-tickers`, `resolve-entities`, `resolve-cusips` ·
**signals** `signals-register`, `compute-signals`, `run-backtest`, `calibration` ·
**prices** `ingest-prices` (Alpaca, THE price path — batched, 500 symbols is 5 requests;
`ingest-prices-alpaca` is kept as an alias), `ingest-prices-tiingo` (the fallback, one symbol per
request, cannot finish a full pass), `compare-prices` ·
**other ingestion** `ingest-short-interest`, `ingest-sentiment`, `ingest-news`,
`analyze-news`, `ingest-calendar`, `ingest-bluesky` · **spine and claims** `spine`, `reprocess`, `interpret`,
`measure-claims`, `ledger`, `import-signals` · **seeds** `seed-admin`, `seed-demo`,
`seed-watchlist`, `seed-exposure`, `sync-library`, `create-invites` ·
**receipts** `seed-house-records`, `resolve-calls`, `verify-chain <handle>` ·
**operations** `scheduler`, `generate-alerts`, `capture-context`, `check-source`.

`check-source <key>` makes a REAL call to one source and says whether it worked, which is the
question `status` (what has been ingested) and `preflight` (what is configured) both leave
unanswered right after someone pastes a key in.

`status` prints per-feed freshness. `preflight` checks production config, including every link in
the `EXPLAIN_PROVIDER` chain.

`make demo` rebuilds a full demo dataset from scratch (minutes). `make backfill-full` is the
overnight calibration backfill.

### Database

```bash
docker compose exec -T db psql -U tradeos -d tradeos -c '\dt'    # 64 tables
docker compose exec -T db psql -U tradeos -d tradeos             # interactive
```

---

## Directory map

```
tradeos/                  the Python package (all backend code)
  app.py                  FastAPI app: 141 routes, ~3510 lines. The one big file.
  db.py                   psycopg connect() + ordered .sql migration runner
  config.py               env accessors; raises ConfigError rather than defaulting secrets
  llm.py                  ONE transport for every model call: provider CHAIN + per-provider
                          circuit breakers + FAST/DEEP model roles
  sources.py              the source registry: every external source, its state, what it powers,
                          where its free key comes from. Backs /api/integrations and every gate.
  authn.py  apikeys.py    sessions (argon2, TOTP for admin), API keys
  flags.py                DB-backed feature flags actually enforced on the request path
  scheduler.py            the background worker: JOBS registry + due-check + job_runs
  ingestion/              one module per external source (see "Sources" below)
  intelligence/           analyst.py (news "why it matters"), vision.py (chart reads)
  explain/                guarded prose for the Signal plane: base, gemini, template, guards
  signals/                convergence scoring + versioned signal definitions
  resolution/             ticker / CUSIP / entity resolution (OpenFIGI, SEC)
  backtest/               outcome measurement for signal clusters
  spine.py                normalise -> cluster -> score. The substrate everything hangs off.
  claims.py               the impact engine. Mechanism rule + the prompt-injection boundary.
  ledger.py               outcome measurement vs SPY; the self-scoring record.
  relevance.py            personal ranking + the reader frame + country exposure data. No model.
  public_site.py          the ONLY unauthenticated surface: what a stranger or a crawler can read.
  onboarding.py           first-run frame capture. Gates nothing — a skip costs the reader nothing.
  mail.py                 the ONE outbound-email path. Refuses to send unconfigured, never half-sends.
  ratelimit.py            sliding-window limits on the public + model paths. IN-PROCESS; see docstring.
  radar.py                saved filter sets, threading, subscribable alerts. The SSRF defence lives here.
  oauth.py                Sign in with Google. Built, config-gated, NEVER RUN against Google.
  journal_context.py      the Radar frozen at trade time; the coach's process patterns. No model.
  geography.py            places events by what a claim AFFECTS, not who published it.
  exposure.py             what holdings are exposed to (replaced the position tracker).
  crypto_intel.py         positioning readings, each with an invalidation condition.
  assistant_tools.py      six READ-ONLY tools; a security boundary, not a convenience layer.
  smartmoney_claims.py    convergence signals expressed as scoreable claims.
  watchlist_accounts.py   the consequential-accounts influence list.
  receipts/               THE PRODUCT. chain.py (pure, the wire format) calls.py scoring.py
                          record.py verification.py seed.py context.py
  migrations/             001..036 ordered .sql; NEVER edit an applied migration, and every
                          file MUST insert its own schema_migrations row
  (surface modules)       dashboard, brief, news, social, sentiment, crypto, events,
                          trades, insights, portfolio, community, alerts, admin,
                          billing, search, library, presentation, assistant
shared/tokens.css         measurements both front ends agree on. Colour is deliberately NOT shared.
site/                     the marketing site: a sibling Vite project, served at /site. See its README.
frontend/src/             React, one .jsx per surface, imported by App.jsx
  shell.jsx               routing, ErrorBoundary, LoadError/EmptyState, SourceGate
  radar.jsx ledger.jsx    the two flagship surfaces
  globe.jsx globe3d.jsx   globe3d is lazy-loaded ONLY; never import it statically
tests/                    pytest; offline, fixture-driven (tests/fixtures/)
docs/                     audit, bugs, dead_code, known_gaps, plan, state, progress/, decision-log,
                          threat-models/, runbooks/
content/                  seed content for the learning library
deploy/                   Caddyfile for the production compose file
```

`tradeos/app.py` is the only file that has grown past comfortable size. Split it by surface
when a phase touches it, not as a standalone refactor.

---

## Conventions this repo actually follows

- **Module docstring first.** Every module opens with a paragraph saying what it is *for*
  and, often, which decision or milestone produced it. Match this.
- **Comments explain why, not what.** Especially why an obvious approach was rejected.
- `from __future__ import annotations` at the top of every module; modern `X | None` types.
- **Raw SQL, always parameterised** (`%s` placeholders). Where SQL has to be *composed* — a column
  list, an optional WHERE, a table name from an allowlist — use `psycopg.sql`
  (`Identifier`/`Placeholder`/`SQL`), never an f-string. Ruff's `S608` enforces this; it was
  suppressed for eight phases and re-enabled in Phase 9.
- **Point-in-time discipline.** Anything derived from filings uses `knowable_time`, never
  the filing date, so backtests cannot see the future. Do not break this.
- **Honest degradation over fabrication.** When a source is missing, the API returns a state
  (`connected` / `needs_key` / `unavailable`) and the UI says so. There is no fixture data
  presented as live anywhere, and there must never be.
- **Guarded model output.** Model prose passes `explain/guards.py` before display. On a guard
  trip the caller falls back to a deterministic template. **The fallback message must state
  the real reason** — see the vision bug in `docs/bugs.md` for why this matters.
- Frontend: functional components, hooks only, `fetch` through `frontend/src/api.js`, plain
  CSS in `styles.css` with CSS custom properties for the design tokens.
- Naming: snake_case Python, camelCase JS, kebab-case CLI commands, `_leading_underscore`
  for module-private helpers.

---

## Gotchas that will cost you an hour

The full list, with the reasoning, is in `docs/state.md` §"Things learned". The ones that bite
fastest:

0z5. **A CALL IS SEALED `unscoreable` IF AND ONLY IF WE HOLD NO PRICE SERIES FOR ITS SYMBOL.**
   Nothing else may seal — and in particular no gap in OUR BENCHMARK, ever. `excess_return`
   returned `no_entry_price` both when the SUBJECT had no session after the call and when SPY was
   missing that one session, and `resolve_call` guarded only `horizon_open_or_delisted`, so the
   merged answer fell through to `_write(..., "unscoreable")`. Measured 2026-09-15 by the Part A
   proof run: **one missing SPY session** permanently sealed a healthy MSFT call, with the note
   *"our price feed for MSFT ends before this call was published"* while MSFT's series ran ten days
   past it. Backfilling the SPY row did not help; the trigger refuses to change a resolved call,
   which is the product working as designed on a verdict that should never have been written.
   `excess_return` now returns **four** reasons — two the subject's, two ours
   (`no_benchmark_entry_price`, `no_benchmark_exit_price`) — and `resolve_due` **refuses the whole
   batch** when `benchmark_health` finds a hole or a short tail in SPY. Note a hole exactly AT the
   exit session is absorbed rather than failed (`exit_day_for` rolls to the next session), which is
   why the batch-level refusal exists as well as the per-call reason. Open calls now carry
   `open_reason_code` (migration 036).

0z4. **`scoreability`'s `days_behind` WAS `bench_last - sym_last`, so a lagging BENCHMARK produced a
   negative number and sailed through `> STALE_TOLERANCE_DAYS`.** Measured: `days_behind: -25,
   scoreable: true` with SPY twenty-five days stale. The gate could see a lagging symbol and was
   structurally blind to the far more dangerous case. It is now measured from `max(sym_last,
   bench_last)`, reports `benchmark_days_behind` separately against the tighter
   `BENCHMARK_TOLERANCE_DAYS = 3`, and **a lagging benchmark now BLOCKS the publish**
   (`blocks_publish`) rather than accepting a permanent commitment we cannot price. Related:
   `scoring._write` ignored `cur.rowcount` behind its `AND verdict IS NULL`, so it returned a
   fabricated verdict the row never received and `resolve_due` counted it into `job_runs.detail`;
   it now reports `no_op`. And `job_runs.status` gained **`warning`**: a job that had work and
   produced none of it on two consecutive runs is no longer recorded as `ok`
   (`scheduler.run_status`, `OUTPUT_KEYS`). `resolve_calls` stays at 21600s.

0z3. **`signal_clusters` HAS NO DEFINITION FILTER ANYWHERE, and v3/v4 miss each other by luck.**
   30 read sites across 12 live modules query it on `as_of` alone — `/api/clusters` is
   `WHERE c.as_of = %s` and nothing more. Measured 2026-09-15: **0** colliding (issuer, as_of)
   pairs today, because v3 was computed over 419 days and v4 over 77 **disjoint** ones. Compute a
   third definition over a range v3 already covers and every one of those 419 days collides: the
   Smart Money feed lists each issuer twice, `_cluster_detail` does `fetchone()` on two rows and
   silently picks one, and `compute_calibration` — which the PUBLIC methodology page reads — double
   counts. This is why `convergence_insider` is computed in memory to a JSON artifact instead of
   being stored (`scripts/analysis/compute_v5.py`). Storing a second definition over a shared range
   is a 12-module refactor, not a compute.

0z2. **A DEFINITION'S VERSION NUMBER IS GLOBAL TO THE TABLE, AND THE SCHEDULER STAMPS CLAIMS WITH
   IT.** `smartmoney_claims._definition_version()` read `SELECT max(version) FROM
   signal_definitions` with **no name filter**, and `scheduler` calls `build()` every cycle. So
   registering ANY definition numbered 5 — under any name — would have restamped new claims
   `convergence-v5` while v3 logic produced them, and those claims are exactly what
   `seed-house-records` imports into `calls`, where the append-only trigger seals them forever. A
   mislabelled claim is fixable; a mislabelled sealed call is not. Fixed by joining each cluster's
   own `definition_id` rather than guessing globally; two tests pin it. **Register a new signal
   under a new NAME** (versions then number from 1 per name) unless it really is a new version of
   the same signal.

0z1. **A RESOLVED CALL IS IMMUTABLE INCLUDING ITS ARITHMETIC** (migration 035). 034 sealed the
   commitment and refused to change a verdict, and said nothing about the nine columns the verdict
   is COMPUTED from: `UPDATE calls SET excess_return = 0.42 WHERE verdict = 'miss'` succeeded,
   every hash still verified because none of those are sealed fields, and the published expectancy,
   the interval and every proof panel had moved. The rule now is that a call is written once and
   scored once — before resolution only the resolution columns may be filled in, after resolution
   nothing may change — and `resolved_at` is the switch, so a verdict written without one is
   refused. `context_snapshot` is sealed too, which 034 claimed in a comment and did not enforce.
   Found by `/code-review`.

0z. **A VERDICT ON A CALL IS PERMANENT, so never seal an operational failure as one.** The
   `calls_append_only` trigger refuses to change a verdict once written — that is the product — and
   the consequence is that "unscoreable" cannot be taken back. A symbol whose price feed is merely
   BEHIND is perfectly scoreable and our data is late (the free Tiingo tier paces at ~45 to 57
   symbols/hour, so a top-up leaves most of the table days stale while it works). Sealing that case
   would be wrong an hour later and uncorrectable forever. `calls.scoreability` returns
   `permanent`, and only the permanent case — no price series at all — is sealed at publish.
   Everything else publishes OPEN with a visible warning. At the horizon, a MISSING EXIT PRICE
   ALWAYS LEAVES THE CALL OPEN. An earlier version let the benchmark settle it — SPY reaches the
   horizon, the symbol does not, therefore the symbol is dead — and `/code-review` showed that is
   wrong: a symbol lagging SPY is the ROUTINE state of this table, because SPY is fetched first on
   purpose. It would have sealed ordinary calls an hour before their prices arrived. A delisted
   symbol staying open forever is visible, honest and correctable; a wrong verdict is none of those.

0h2. **Alpaca's default feed is SIP, which this plan may not query — always send `feed=iex`.**
   The adapter documented IEX in its docstring, labelled every row it wrote
   `SOURCE = "alpaca:iex:adjusted"`, and then did not ask for it. Omitting the parameter failed
   both ways at once: any window reaching today came back `403 subscription does not permit
   querying recent SIP data`, which is EVERY scheduled top-up, and any older window came back 200
   carrying consolidated-tape bars that were stored under the IEX provenance string — so the
   quieter half of the bug was a row whose own label was false. A 403 that only appears once the
   window reaches today is invisible to a backfill and fatal to the scheduler.

0h3. **Alpaca spells a class or preferred share with a DOT, and one wrong symbol kills 100.**
   `GEF-B` is the SEC/Nasdaq spelling this database stores; Alpaca answers `400 invalid symbol`,
   and because the request is batched that 400 rejects the WHOLE batch — 99 healthy symbols lose
   their refresh for one bad name. `daily_batch` converts `-` to `.` on the wire and maps the
   response back, so nothing stored ever carries a dot. Note the reject row logs only `batch[:20]`
   while BATCH is 100, so the symbol that actually failed may not even appear in the log line.
   Delisted and OTC names are NOT this problem — they return 200 with no bars and count as
   `no_data`.

0y. **`receipts/chain.py`'s canonical payload is a WIRE FORMAT and its field order is frozen
   forever.** Adding a sealed field, reordering two, or changing how a timestamp renders would
   invalidate every chain ever published. A test pins the order. Note the fields are LENGTH
   PREFIXED rather than delimited: a caller writes their own thesis, and with a plain separator they
   could type the separator into it and make two different calls serialise identically — a
   collision they control, and so a forged link. Same lesson as the prompt fence in `claims.py`.

0x. **Probe each link of the model chain ALONE.** `llm.complete` falls through to the next
   provider on failure, so a probe using the configured chain answers for the fallback and reports
   OK for a dead key. That is exactly how the `openai` slot answered HTTP 410
   `github_models_retirement_brownout` for five weeks while every surface looked fine — Gemini was
   covering it. `check-source llm_gemini` and `check-source llm_openai` each force ONE provider.
   And a source not in `sources.CATALOG` is invisible to the operator no matter how badly it is
   failing: the whole chain was missing from the registry, which is why the integration page
   structurally could not report the outage.

0w. **A time window on a read is a preference, not a wall.** `/api/news` queried a fixed 72 hours
   and rendered completely empty whenever ingestion had been stopped longer than that, which on a
   laptop is any weekend — while holding 3,690 items. Widening the default only moves the cliff.
   `news.ranked_news_window` falls back to the most recent rows and SAYS SO, with the age of what
   you are looking at, and does not widen when a filter genuinely matches nothing.

0v. **A route taken off the sidebar must stay in `ROUTES`.** Radar, The World, Exposure, Library
   and Community are off the rail because they are empty. They are still addressable, because the
   Morning Brief and the Dashboard link to the Radar and four surfaces link to library entries;
   dropping them from `ROUTES` would turn every one of those links into a silent redirect to the
   Board. A door that opens onto the wrong room is worse than a door that is not advertised. The
   opposite failure also happened here and is guarded by a test: `portfolios.jsx` was imported and
   rendered but absent from `ROUTES`, so a whole paid feature was unreachable while the pricing
   page advertised it.

0. **`EXPLAIN_PROVIDER` is a comma-separated CHAIN, and only `llm.py` may parse it.** Production
   runs `gemini,openai`. Six call sites once gated their model call on
   `provider in ("gemini", "openai")` — False for the chain form — so every AI prose surface
   served its template for three phases while reporting the model had been tried (B-23). Gate on
   **`llm.wants_model(provider)`**; a test forbids the old pattern. More generally: the suite runs
   on `template` by design, so **verify a model change against a running instance**
   (`used_template: false`), never against the tests alone.

0a. **The Ledger's headline number was never the product's.** All 412 scoreable calls belong to the
   legacy smart-money signal; the impact engine has **9 open, 133 unscoreable and zero resolved**
   (2026-08-23). The marketing site published the signal's rate under the heading "the accuracy
   record" with an H2 reading "We are wrong most of the time", directly beneath a hero selling the
   engine. Two subsystems, one number, and the one on display had never measured the thing being
   sold. `ledger.summary()` now returns `open_by_origin` so any surface can say WHOSE record it is
   showing, and a test asserts the planes are never pooled. **Never quote a hit rate without
   saying which plane produced it.**

   The 412 do span two version rows — `convergence-v3` (115/282 = 40.8%) and `convergence-v4`
   (63/130 = 48.5%) — but **these are the same scoring logic**, so pooling them is legitimate and
   the 43.2% headline is honest. v4's `signal_definitions` changelog says so explicitly: "NO
   BEHAVIOURAL CHANGE", re-registering identical logic after a lint pass changed the module hash.
   That hash guard silently stopped `compute-signals` producing clusters from 2026-07-25 until it
   was re-registered, so **a frozen sample is a symptom worth checking** when the ledger stops
   growing. Do not present v3 and v4 to a reader as two signals.

0a0. **A commodity is a RELATIONSHIP, not a location — and conflating them killed
   personalisation.** `COMMODITY_COUNTRIES["oil"]` lists six producers, `places()` treated all six
   as where the event happened, and `geo_weight` returns 1.0 when your country is in that list. So
   a Gulf oil story scored identically for Saudi Arabia, the US, Russia, the UAE, Iraq and Brazil,
   and the marketing site's "pick a country" demo returned a byte-identical feed for Abu Dhabi and
   Sao Paulo. `geography.countries_with_reason` now labels each country `location` or `commodity`;
   `places()` takes only the former, and `commodity_weight` scores the latter by rank in the
   reader's own `key_exports`/`key_imports`. `countries_for` is unchanged — the globe legitimately
   wants every country a claim touches.

0a3. **A partial backfill looks exactly like a broken signal.** The publish gate is
   `min_source_classes: 2` + `min_voices: 3`, so a cluster needs at least two KINDS of filing.
   Backfilling Form 4 alone over June 2023 produced 79 candidates and **zero** clusters — not
   because anything was wrong, but because 13D/G history did not cover the same window. Always
   backfill both sources over the same range (`make backfill-full`), and read "N candidates, 0
   clusters" as "one source is missing" rather than as a failure. Measured cost: **35 minutes per
   week of Form 4**, so 2.5 years is ~76 hours.

0a2. **A point estimate without an interval invites a verdict the sample cannot support — in
   BOTH directions.** The signal plane reads 43.2% with +14.29% average on hits and −12.95% on
   misses, giving −1.18% expectancy. I reported that as "it does not work". It is not:
   the 95% interval on that mean is **[−2.93%, +0.57%] and spans zero**, so on 412 calls
   **no edge is demonstrated either way**. What IS significant is the FREQUENCY — 2.76 standard
   errors below a coin flip — but the wins are bigger than the losses, so the returns cancel.
   Those two statistics genuinely disagree and only one of them is conclusive.
   `ledger.mean_ci`, `proportion_z` and `sample_needed` are pure and tested; both Ledger surfaces
   publish the interval. **Never quote expectancy or a hit rate from this ledger without the
   interval beside it.** At the measured 18.17% dispersion it takes **1,268** resolved calls to
   detect a 1% per-call edge, and there are 412. All figures measured 2026-08-23 — note the
   sample grew from 282 and the conclusion did not change, which is itself the point.

0b2. **A formatter duplicated across files WILL drift, and the drift is silent.** `pct` lived as
   near-identical copies in three surfaces; the fourth copy omitted the ×100 and published a +10%
   trade to other readers as "+0.1%". `trades.realized_pnl_pct` returns a FRACTION (0.1 == +10%).
   Shared display formatters now live in `frontend/src/format.js` — use them rather than writing a
   fourth `pct`.

0c. **A media query adds NO specificity, so mobile overrides must sit at the END of `styles.css`.**
   A `@media (max-width: 720px) { .bt { white-space: normal } }` placed at line 190 loses to the
   base `.bt { white-space: nowrap }` at line 227 — same specificity, later wins. Same trap with
   compound classes: `.menu-btn { display: none }` lost to `.icon-btn { display: grid }` declared
   after it, which is why a hamburger sat in the desktop top bar. There is a marked
   "NARROW SCREENS — must stay LAST" block at the bottom of the file; put narrow-screen rules
   there, and use a compound selector (`.icon-btn.menu-btn`) when the element carries both classes.

0d. **A grid or flex track written `1fr` is `min-width: auto` and will not shrink below its
   content.** Every horizontal-overflow bug found in this codebase was this or an unbreakable
   string: write `minmax(0, 1fr)`. Ingested text also contains bare URLs, which is why `.content`
   sets `overflow-wrap: anywhere` — `anywhere` rather than `break-word` because only `anywhere`
   also shrinks the container's min-content, which is the half that stops the overflow.
   **Check a UI change at 375px, not just at your window width.**

0e. **react-globe.gl draws NOTHING by default.** With no `globeImageUrl` its own docs say the globe
   "is represented as a black sphere", and a black sphere on this near-black page is invisible —
   which is what "the globe doesn't load" meant. Land comes from vendored Natural Earth 110m
   geometry (`frontend/src/world-110m.geo.json`) passed as `hexPolygonsData`. Note that
   `globeMaterial` takes a THREE.Material INSTANCE; a plain `{ color }` object is silently ignored,
   and `globeMaterial()` is NOT a method on the React ref (only `pointOfView`, `controls`, `scene`,
   `camera`, `renderer` and the utilities are).

0f. **A word-bounded cue cannot match its own plural, and the cue table is full of them.**
   `\btariff\b` does not match "tariffs" — the trailing `\b` wants a non-word character and `s` is
   one. Inside `other` there were 37 events containing "tariffs" and **zero** containing "tariff",
   because any singular was caught and never got there. `spine._cue_pattern` now expands each cue
   to its inflected forms, every word of a phrase (the plural of "ban on" is "bans on"), so write
   the cue once in whichever number reads best. Do **not** patch a single word by listing both
   forms — that was done once for "port"/"ports" and hid the general bug for eight phases.
   `_NO_INFLECTION` is the escape hatch for a genuinely ambiguous cue and every entry needs a
   measurement: "strikes" is military 33 times to 2 in this corpus.

0f2. **The cue table's ORDER is behaviour, and it is sorted by specificity, not importance.**
   First match wins. `trade_policy` sat ninth behind `conflict` ("war" is inside "trade war") and
   `regulation` ("sanction"), so the two categories most likely to hold a tariff story both won
   first — 21 events, every one a tariff story, filed as conflict/regulation/election. Order is
   now: unambiguous vocabularies first (`protocol_upgrade`, `monetary_policy`, `trade_policy`),
   metaphor-prone ones last (`technology` stays bottom — "ai" is two letters, "chip" is a snack).
   Five tests pin the constraints. Demoting `conflict` further was measured and rejected: 35 more
   moves, zero additional trade_policy.

0f3. **A category the cue table cannot PRODUCE is adapter-authoritative — never reclassify it.**
   GDELT's category is the topic of the query that found the article (284 events); `macro` comes
   from the ECB/Fed feeds (39) and `corporate` from 8-K item codes (26), and no cue spells either
   word. `reprocess --reclassify` used to `UPDATE ... SET category = classify(...)` unconditionally
   and would have replaced most of those 349 labels with `other`. Any reclassification pass must
   skip `source = 'gdelt'` and any category outside `_CATEGORY_CUES`.

0g. **`reject()` and `redact()` are one thing, and the reason is a leaked key.** httpx puts the
   full request URL in its exception message, five adapters hand raw exception text to
   `ingestion.common.reject`, and Tiingo used to authenticate with `?token=` — so 1,172 rows of
   `ingest_rejects` held the live API key in plain text for five weeks. Redaction happens INSIDE
   `reject`, not at the call sites, and `scheduler.redact` imports it rather than keeping a second
   copy. **Never store `str(exc)` from an HTTP client without it**, and never write a second
   redactor: the copy that drifts is the one that leaks.

0g2. **Authenticate with a HEADER, not a query parameter, and redaction stops being load-bearing.**
   B-30's first fix scrubbed the key out of the exception text on its way to the database; the key
   still went onto the wire in the URL, so `redact()` was the single control protecting it and it
   only covered the one path that runs through `reject()`. `TiingoClient` now sends
   `Authorization: Token <key>` — Tiingo accepts both forms, so it was free. Verified against live
   Tiingo with `redact` swapped for the identity function: a real 429 wrote a reject row carrying
   no credential, while the same request re-issued the old `?token=` way still leaked. When you add
   a source, **check whether it accepts a header before reaching for `?key=`**; `redact` is the net,
   not the wire. One consequence: `follow_redirects` must stay **False**, because a header is sent
   to whatever host a redirect lands on and `daily()`'s allowlist only checks the URL we build.

0h4. **Alpaca's cost scales with BARS, not symbols, and the "requests" counter counts neither.**
   The counter logged as `batches` counts symbol groups of 100; the real HTTP round trips are
   those TIMES the pagination factor, because a page caps at 10,000 bars. So "345 symbols, 4
   requests, 47 seconds" in §0h is ~39 actual fetches, and a deep backfill pays the factor in
   full: measured 2026-09-15, **1,664 symbols / ~1.85M rows / 17 batches / ~355 seconds**, which
   is 4.8x the symbols but 7.6x the time. Budget a backfill by ROWS (symbols x trading days), not
   by symbol count. Also: **26 stored symbols have zero Alpaca coverage** and are frozen at
   Tiingo's last day — warrants (`...W`/`WW`), preferreds, units, OTC foreign lines, B-class
   shares, bankruptcy `Q` tickers. IEX does not quote them. `--only-stale` re-selects them every
   run and can never fix them.

0h. **Prices come from ALPACA now; the Tiingo ceiling is why.** Free Tiingo is ~57 unique
   symbols/HOUR, ~500/month, and ONE symbol per request, so a 500-symbol top-up could never
   finish: it died mid-alphabet every time and price staleness became alphabetically biased while
   the table reported 99% fresh. Use `ingest-prices-alpaca --only-stale` — 461 symbols, 8,216
   rows, 5 requests, ~3 seconds, measured 2026-09-14. The `--only-stale` selector still matters
   and still puts SPY first, because a stale benchmark makes every other symbol unscoreable; what
   changed is that the pass now FINISHES. `ingest-prices` and `scripts/topup-prices.sh` are the
   Tiingo fallback and stay only until Alpaca has a track record.

0i. **A key in `.env` does NOT reach the container.** `docker-compose.yml` enumerates every
   variable explicitly (`FOO: ${FOO:-}`), so a key added to `.env` alone is silently absent from
   `api` and `worker` — `config.foo_configured()` reads the HOST's environment during tests and
   says "connected" while the running process has nothing. `OPENFIGI_API_KEY` was missing from
   the compose file entirely, which is a second reason 19,851 holdings stayed invisible. Add the
   variable in BOTH services, then `docker compose up -d api worker`. `docker-compose.prod.yml`
   uses `env_file:` and needs no such edit — only the base file enumerates.

0j. **A probe against an endpoint that also serves unauthenticated callers proves nothing.** This
   bit Tiingo (`/api/test` 200s for a garbage token) and OpenFIGI's mapping endpoint answers
   keyless requests too. The fix is to make the request one a keyless caller CANNOT make:
   measured 2026-08-24, OpenFIGI caps keyless at **10** mapping jobs and keyed at **100**, so
   `check-source openfigi` posts **eleven** and reads three distinct outcomes — 200 valid,
   401 invalid, **413 the key never arrived**. When adding a probe, ask what the unauthenticated
   response would be; if it is also success, the probe is decorative.

1. **Frontend changes need `make web`** (0.3s) under `make dev`, or a full image rebuild otherwise.
2. **`geo` on an event is where the OUTLET sits, not what the story is about.** The single most
   repeated mistake in this project — made three times.
3. **Gemini's `maxOutputTokens` counts hidden reasoning** (measured 769-1360 tokens for one chart).
   `THINKING_HEADROOM` in `llm.py` pays for it. Do not remove it. `thinkingConfig` 400s on every
   model newer than 2.5 — do not reintroduce it.
4. **Gemini quota is per model and has a real daily ceiling.** Use `gemini-flash-latest` (DEEP) and
   `gemini-flash-lite-latest` (FAST). `gemini-2.0-flash` has a zero free-tier allowance.
5. **httpx puts the full request URL, query string included, in exception messages.** Any API
   authenticated with `?key=` leaks its credential. `scheduler.redact()` strips them. Keep it —
   Gemini still authenticates that way. Tiingo no longer does; see 0g2.
6. **The prompt fence in `claims.py` uses a per-request nonce.** Do not "simplify" it to fixed
   markers — `str.replace` cannot sanitise a delimiter, it reassembles. Found by `/security-review`.
7. **Do not quote prompt-injection examples in a prompt.** Azure's content filter classifies that
   as a jailbreak and 400s the whole request.
8. **`_require_admin` returns the USER on success, None on failure.** Branch on `if not ...`.
9. **Every migration must INSERT its own `schema_migrations` row**; the runner does not.
10. **GDELT's throttle is keyed on the User-Agent.** Rotating it would work; we deliberately do not.
11. **Postgres, not SQLite** (contra the brief; reasoned in `docs/plan.md` §1).
12. **Run the browser check as well as the tests** — a missing import passed 435 tests and threw
    on the page.

## External sources (all free tier)

| Source | Key needed | Powers | State |
|---|---|---|---|
| SEC EDGAR (13D/G, 13F, Form 4, 8-K) | `SEC_USER_AGENT` only | Smart Money, news | connected |
| RSS (11 feeds, 5 countries) | none | News Intelligence, source comparison | connected |
| GDELT | none | worldwide event coverage on the Radar | connected |
| Bluesky | none | posts from consequential accounts → the Radar | connected |
| Nasdaq calendar | none | Calendar | connected |
| Wikipedia pageviews | none | Attention | connected (noisy — see bugs) |
| Hacker News | none | Attention | connected |
| CoinGecko | none | Crypto | connected |
| Alpaca Market Data | `ALPACA_API_KEY_ID` + `_SECRET_KEY` | EOD prices — **the price source**; batched, free IEX feed | connected |
| Tiingo | `TIINGO_API_KEY` | EOD prices — FALLBACK only | connected |
| OpenFIGI | `OPENFIGI_API_KEY` | 13F CUSIP → ticker; unmapped holdings are invisible | connected |
| Reddit | `REDDIT_CLIENT_ID` + `_SECRET` | Social sentiment | **not connected** |
| YouTube | `YOUTUBE_API_KEY` | Social sentiment | not connected |
| X / Twitter | — | — | **no free read tier; do not attempt — Bluesky covers the need** |
| Binance (public derivatives) | none | Crypto positioning: funding, open interest, crowding | connected |
| FINRA | none | short interest, ingested as context, CLI only and parked | connected |
| LLM link 1 — Gemini | `GEMINI_API_KEY` | All AI prose | connected, and **at the edge of its daily quota** |
| LLM link 2 — OpenAI-compatible | `OPENAI_BASE_URL` + `_API_KEY` + `_MODEL` | the fallback for all AI prose | **DEAD: GitHub Models answers HTTP 410. Needs a Groq key** |
| Stripe | `STRIPE_SECRET_KEY` + `_WEBHOOK_SECRET` | billing | not connected (free launch mode) |
| Sentry | `SENTRY_DSN` | error tracking | not connected |

`tradeos/sources.py` is the registry of record and the integration page reads it — a source missing
from it is invisible to the operator no matter how well it runs. GDELT was exactly that for three
phases. **Adding an ingestion module is not done until it has a CATALOG entry.**

Bluesky reads a CURATED ACCOUNT LIST (`watchlist_accounts`, `platform = 'bluesky'`), not the
network: `app.bsky.feed.searchPosts` returns 403 without authentication as of 2026-07-26, while
`getAuthorFeed` and `getProfile` are keyless. Do not rebuild this around search.

Every external call goes through a module in `tradeos/ingestion/`. **Never call an external
API from a route handler or a component.**

---

## Definition of done for any change

- Tests pass (command above), and new tests cover ingestion parsers, scoring, and every
  authorization boundary.
- The app runs with **no console errors** — check in a browser, do not assume.
- No fabricated data anywhere, including empty states and demo screens.
- Every displayed fact carries source + timestamp + link.
- Every new external source appears on the integration status page.
- Every new panel has real loading, empty, and error states.
- Documentation reconciled with reality in the same commit that changed the behaviour.
- Dead code removed and reported, not commented out.
- `/simplify`, `/code-review` and `/security-review` run on the diff, findings addressed or
  explained.
