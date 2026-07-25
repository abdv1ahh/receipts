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
| Frontend | React + Vite, **no router, no state library, no CSS framework** | 18.3.1 / 5.4.21 |
| Node (build) | node / npm | 24.18 / 11.16 |

There is **no ORM** (raw SQL through psycopg), **no migration framework** (ordered `.sql`
files run by `tradeos/db.py`), and **no dependency injection / event bus / state machine**.
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
docker compose run --rm -T -v "$PWD/tests:/app/tests" api python -m pytest tests/ -q
```

**189 tests, ~0.5s, fully offline (no network).** The `-v` mount is required: the Dockerfile
deliberately does not copy `tests/` into the image, so `make test` and the README's
`python -m pytest tests/ -q` both fail with "file or directory not found". Fixing that
mismatch is a Phase 1 cleanup item.

### Frontend

```bash
cd frontend && npm ci && npm run build   # ~0.4s; emits frontend/dist
```

**The served bundle is baked into the image at build time** (`Dockerfile` stage 1 copies
`/web/dist` to `/app/tradeos/static`). Editing `frontend/src/*` and reloading the browser
changes nothing. You must `docker compose up -d --build` to see a frontend change. There is
no hot-reload wired to the container. `frontend/dist/` and `tradeos/static/` are gitignored.

### Data / operations CLI

```bash
docker compose exec -T api python -m tradeos.cli <command>
```

Commands: `migrate`, `sync-tickers`, `resolve-entities`, `resolve-cusips`,
`signals-register`, `compute-signals`, `ingest-prices`, `ingest-short-interest`,
`ingest-sentiment`, `ingest-news`, `analyze-news`, `ingest-calendar`, `scheduler`,
`run-backtest`, `calibration`, `sync-library`, `generate-alerts`, `seed-admin`, `seed-demo`,
`create-invites`, `status`, `preflight`.

`status` prints per-feed freshness. `preflight` checks production config — note it currently
reports a false failure for `EXPLAIN_PROVIDER=openai` (stale validator; see `docs/bugs.md`).

`make demo` rebuilds a full demo dataset from scratch (minutes). `make backfill-full` is the
overnight calibration backfill. `make test` is **broken** — use the command above.

### Database

```bash
docker compose exec -T db psql -U tradeos -d tradeos -c '\dt'    # 48 tables
docker compose exec -T db psql -U tradeos -d tradeos             # interactive
```

---

## Directory map

```
tradeos/                  the Python package (all backend code)
  app.py                  FastAPI app: 98 routes, 2200 lines. The one big file.
  db.py                   psycopg connect() + ordered .sql migration runner
  config.py               env accessors; raises ConfigError rather than defaulting secrets
  llm.py                  ONE transport for every model call (gemini | openai-compatible)
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

1. **Frontend changes need a Docker rebuild.** (See above. This is the number one time sink.)
2. **`make test` and the README test command are broken.** Use the mount form above.
3. **GitHub Models is being retired 2026-07-30.** `EXPLAIN_PROVIDER=openai` currently points
   at `https://models.github.ai/inference`, which returns `Sunset: Thu, 30 Jul 2026` headers.
   All AI prose, the Morning Brief, news analysis and chart reads die that day unless the
   provider moves. `gemini-flash-latest` is verified working on the existing key.
4. **`gemini-2.5-flash` 404s** ("no longer available to new users") and `gemini-2.0-flash`
   is over quota on this key. Use `gemini-flash-latest`.
5. **`llm.py` has a process-global cooldown.** One 429 silences *every* model caller for 120
   seconds. When debugging model output, a `None` may mean "cooling", not "no provider".
6. **`directive_guard` bans the phrase `target price`** while the vision prompt asks the
   model to discuss entry/stop/target levels. Any prose field tripping the guard discards
   the *entire* analysis. This is the root cause of "the AI never sees my screenshot".
7. **The app has no router.** Navigation is `useState` in `App.jsx`; there are no URLs, no
   deep links, no browser back. Phase 4 and Phase 7 both need this fixed.
8. **A single failed fetch sets a global `err`** in `App.jsx` and renders a red bar over
   every page. There are no error boundaries.
9. **Postgres, not SQLite.** The product brief suggests SQLite; the app already has 23
   migrations, 48 tables and 664k insider transactions in Postgres. Do not migrate.
10. **Migrations are never edited once applied.** Add `024_*.sql` and move forward.

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
| LLM | `OPENAI_*` or `GEMINI_API_KEY` | All AI prose | connected, **sunsetting** |

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
