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

It now has a claim engine (`claims.py`), a self-scoring Ledger (`ledger.py`, publishing 41% of 282
with the misses shown), an event spine (`spine.py`), personal relevance (`relevance.py`), world
context frozen at trade time (`journal_context.py`), and surfaces at `/radar` `/globe` `/ledger`
`/exposure` `/crypto` `/news` `/brief` `/events` `/journal` `/community` `/integrations`.

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
| Images | Pillow | 10.4.0 |
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
make test     # 631 tests, ~1s. Offline except 17 authz tests that need the local DB
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

All 39, checked against `--help` rather than remembered:

`migrate`, `preflight`, `status` · **SEC ingestion** `ingest-form4`, `ingest-13dg`, `ingest-13f`
`backfill-form4`, `backfill-13dg`, `backfill-13f` (`--from`/`--to` over a date range; weekends skipped, holidays 404 and
are logged past) · **resolution** `sync-tickers`, `resolve-entities`, `resolve-cusips` ·
**signals** `signals-register`, `compute-signals`, `run-backtest`, `calibration` ·
**other ingestion** `ingest-prices`, `ingest-short-interest`, `ingest-sentiment`, `ingest-news`,
`analyze-news`, `ingest-calendar`, `ingest-bluesky` · **spine and claims** `spine`, `reprocess`, `interpret`,
`measure-claims`, `ledger`, `import-signals` · **seeds** `seed-admin`, `seed-demo`,
`seed-watchlist`, `seed-exposure`, `sync-library`, `create-invites` ·
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
docker compose exec -T db psql -U tradeos -d tradeos -c '\dt'    # 61 tables
docker compose exec -T db psql -U tradeos -d tradeos             # interactive
```

---

## Directory map

```
tradeos/                  the Python package (all backend code)
  app.py                  FastAPI app: 127 routes, ~3070 lines. The one big file.
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
  migrations/             001..033 ordered .sql; NEVER edit an applied migration, and every
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
docs/                     audit, bugs, dead_code, plan, state, progress/, decision-log,
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

0. **`EXPLAIN_PROVIDER` is a comma-separated CHAIN, and only `llm.py` may parse it.** Production
   runs `gemini,openai`. Six call sites once gated their model call on
   `provider in ("gemini", "openai")` — False for the chain form — so every AI prose surface
   served its template for three phases while reporting the model had been tried (B-23). Gate on
   **`llm.wants_model(provider)`**; a test forbids the old pattern. More generally: the suite runs
   on `template` by design, so **verify a model change against a running instance**
   (`used_template: false`), never against the tests alone.

0a. **The Ledger's headline number was never the product's.** All 282 resolved calls are
   `convergence-v3`, the legacy smart-money signal; the impact engine has 80 open and **zero**
   resolved. The marketing site published the signal's 41% under the heading "the accuracy record"
   with an H2 reading "We are wrong most of the time", directly beneath a hero selling the engine.
   Two subsystems, one number, and the one on display had never measured the thing being sold.
   `ledger.summary()` now returns `open_by_origin` so any surface can say WHOSE record it is
   showing, and a test asserts the planes are never pooled. **Never quote a hit rate without
   saying which plane produced it.**

0a3. **A partial backfill looks exactly like a broken signal.** The publish gate is
   `min_source_classes: 2` + `min_voices: 3`, so a cluster needs at least two KINDS of filing.
   Backfilling Form 4 alone over June 2023 produced 79 candidates and **zero** clusters — not
   because anything was wrong, but because 13D/G history did not cover the same window. Always
   backfill both sources over the same range (`make backfill-full`), and read "N candidates, 0
   clusters" as "one source is missing" rather than as a failure. Measured cost: **35 minutes per
   week of Form 4**, so 2.5 years is ~76 hours.

0a2. **A point estimate without an interval invites a verdict the sample cannot support — in
   BOTH directions.** The signal plane reads 40.8% with +15.9% average on hits and −13.5% on
   misses, giving −1.52% expectancy. I reported that as "it does not work". It is not:
   the 95% interval on that mean is **[−3.80%, +0.76%] and spans zero**, so on 282 calls
   **no edge is demonstrated either way**. What IS significant is the FREQUENCY — 3.1 standard
   errors below a coin flip — but the wins are bigger than the losses, so the returns cancel.
   Those two statistics genuinely disagree and only one of them is conclusive.
   `ledger.mean_ci`, `proportion_z` and `sample_needed` are pure and tested; both Ledger surfaces
   publish the interval. **Never quote expectancy or a hit rate from this ledger without the
   interval beside it.** At the measured 18% dispersion it takes ~1,470 resolved calls to detect a
   1% per-call edge, and there are 282.

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

1. **Frontend changes need `make web`** (0.3s) under `make dev`, or a full image rebuild otherwise.
2. **`geo` on an event is where the OUTLET sits, not what the story is about.** The single most
   repeated mistake in this project — made three times.
3. **Gemini's `maxOutputTokens` counts hidden reasoning** (measured 769-1360 tokens for one chart).
   `THINKING_HEADROOM` in `llm.py` pays for it. Do not remove it. `thinkingConfig` 400s on every
   model newer than 2.5 — do not reintroduce it.
4. **Gemini quota is per model and has a real daily ceiling.** Use `gemini-flash-latest` (DEEP) and
   `gemini-flash-lite-latest` (FAST). `gemini-2.0-flash` has a zero free-tier allowance.
5. **httpx puts the full request URL, query string included, in exception messages.** Any API
   authenticated with `?key=` leaks its credential. `scheduler.redact()` strips them. Keep it.
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
| Tiingo | `TIINGO_API_KEY` | EOD prices | connected |
| Reddit | `REDDIT_CLIENT_ID` + `_SECRET` | Social sentiment | **not connected** |
| YouTube | `YOUTUBE_API_KEY` | Social sentiment | not connected |
| X / Twitter | — | — | **no free read tier; do not attempt — Bluesky covers the need** |
| LLM | `GEMINI_API_KEY` (+ optional `OPENAI_*`) | All AI prose | connected (Gemini free tier) |

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
