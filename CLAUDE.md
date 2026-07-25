# CLAUDE.md — operating manual for this repository

Read this first, every session. Then read `docs/state.md` (where the work stands) and
`docs/plan.md` (where it is going).

Every command below has been run and verified. If you find one that does not work, fix it
here in the same change that discovers it — a wrong command in this file is worse than no
command.

---

## What this is

**Internal codename: TradeOSS.** A world-event interpretation engine that explains market
consequences. Currently a working SEC/news intelligence app; being rebuilt around causal
claims, a public accuracy ledger, and personal (country-level) relevance. The product brief
is `docs/tradeoss_veryimportant_prompt.md` — it is the source of truth for scope.

The display name is a config value, not a hardcoded string (see `docs/plan.md` §rebrand).
Never rename Python modules, database tables, or the `tradeos` package for branding.

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
make test     # 222 tests, ~0.3s, fully offline (no network)
make lint     # ruff; zero errors is the standard
make dev      # reload-in-place stack; then `make web` for a UI change
```

`tests/` is deliberately not copied into the production image, so the suite runs against a mount.
`make test` does that for you.

### Frontend

```bash
make dev      # once: starts the reload-in-place stack
make web      # after every UI edit (~0.3s) — this is what makes the change visible
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

Commands: `migrate`, `sync-tickers`, `resolve-entities`, `resolve-cusips`,
`signals-register`, `compute-signals`, `ingest-prices`, `ingest-short-interest`,
`ingest-sentiment`, `ingest-news`, `analyze-news`, `ingest-calendar`, `scheduler`,
`run-backtest`, `calibration`, `sync-library`, `generate-alerts`, `seed-admin`, `seed-demo`,
`create-invites`, `status`, `preflight`.

`status` prints per-feed freshness. `preflight` checks production config, including every link in
the `EXPLAIN_PROVIDER` chain.

`make demo` rebuilds a full demo dataset from scratch (minutes). `make backfill-full` is the
overnight calibration backfill.

### Database

```bash
docker compose exec -T db psql -U tradeos -d tradeos -c '\dt'    # 48 tables
docker compose exec -T db psql -U tradeos -d tradeos             # interactive
```

---

## Directory map

```
tradeos/                  the Python package (all backend code)
  app.py                  FastAPI app: 99 routes, ~2250 lines. The one big file.
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
  migrations/             001..023 ordered .sql; NEVER edit an applied migration
  (surface modules)       dashboard, brief, news, social, sentiment, crypto, events,
                          trades, insights, portfolio, community, alerts, admin,
                          billing, search, library, presentation, assistant
frontend/src/             React, one .jsx per surface, imported by App.jsx
  shell.jsx               routing, ErrorBoundary, LoadError/EmptyState, SourceGate
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
- **Raw SQL, always parameterised** (`%s` placeholders, never f-strings into queries).
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

1. **Frontend changes need a rebuild.** Under `make dev` that is `make web` (~0.3s). Without
   it, a full `docker compose up -d --build`. The bundle is baked into the image.
2. **Gemini's `maxOutputTokens` counts hidden reasoning.** Measured 769–1360 thinking tokens for
   one chart image, so a caller asking for 800 gets truncated JSON that looks like a parse bug.
   `THINKING_HEADROOM` in `llm.py` pays for it — do not remove it.
3. **`thinkingConfig` returns 400 on every Gemini model newer than 2.5.** Sending it had pinned
   the app to legacy models. Do not reintroduce it.
4. **Gemini quota is per model.** `gemini-2.0-flash` has a zero free-tier allowance and
   `gemini-2.5-*` are closed to new keys. Use `gemini-flash-latest` (DEEP) and
   `gemini-flash-lite-latest` (FAST). The model id is load-bearing.
5. **`EXPLAIN_PROVIDER` is a chain**, comma-separated, tried in order. Circuit breakers are per
   provider. A `None` from `llm.text()` may mean "every provider is cooling" — use
   `llm.complete()` when you need the reason to show a user.
6. **httpx puts the full request URL, query string included, in exception messages.** Any API
   authenticated with `?key=` leaks its credential through an unhandled error.
   `scheduler.redact()` strips query strings before anything is stored or logged. Keep it.
7. **Postgres, not SQLite.** The product brief suggests SQLite; the app already has 23
   migrations, 48 tables and 664k insider transactions in Postgres. Do not migrate.
8. **Migrations are never edited once applied.** Add `024_*.sql` and move forward.
9. **Never call an external API from a route handler or a component** — it goes in
   `tradeos/ingestion/` and gets an entry in `tradeos/sources.py`, or the integration status page
   silently stops telling the truth.
10. **A source that no-ops because it is unkeyed still records `status: ok`** in `job_runs`.
    `sources.health()` deliberately does not count that as a successful fetch.

---

## External sources (all free tier)

| Source | Key needed | Powers | State |
|---|---|---|---|
| SEC EDGAR (13D/G, 13F, Form 4, 8-K) | `SEC_USER_AGENT` only | Smart Money, news | connected |
| RSS (CNBC, Fed, SEC) | none | News Intelligence | connected |
| Nasdaq calendar | none | Calendar | connected |
| Wikipedia pageviews | none | Attention | connected (noisy — see bugs) |
| Hacker News | none | Attention | connected |
| CoinGecko | none | Crypto | connected |
| Tiingo | `TIINGO_API_KEY` | EOD prices | connected |
| Reddit | `REDDIT_CLIENT_ID` + `_SECRET` | Social sentiment | **not connected** |
| YouTube | `YOUTUBE_API_KEY` | Social sentiment | not connected |
| X / Twitter | — | — | **no free read tier; do not attempt** |
| LLM | `GEMINI_API_KEY` (+ optional `OPENAI_*`) | All AI prose | connected (Gemini free tier) |

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
