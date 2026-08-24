# docs/audit.md — Phase 0 audit

Written 2026-07-25. Method: full read of the 196 tracked files (24k LOC), live probing of the
running stack (Docker compose: api + postgres + worker), authenticated click-through of all
twelve app surfaces in a headless browser, direct execution of the model and ingestion paths
inside the container, and inspection of the live database.

**Bottom line:** the foundation is better than the owner believes. The ingestion layer, the
scheduler, the point-in-time discipline, the guard architecture and the honesty conventions
are genuinely good and should be extended, not replaced. What is broken is narrower and more
specific than "a lot of glitches" — and the single most consequential finding has nothing to
do with the reported bugs.

---

## 0. The finding that outranks everything else

**The only configured language-model provider is being shut down in five days.**

`EXPLAIN_PROVIDER=openai` points at `https://models.github.ai/inference` (GitHub Models).
Every response from it carries:

```
Deprecation: @1777939200
Sunset: Thu, 30 Jul 2026 00:00:00 GMT
Link: <https://github.blog/changelog/2026-07-01-github-models-is-being-fully-retired-on-july-30-2026/>
```

Today is 2026-07-25. On 30 July the Morning Brief's executive summary, News Intelligence
"why it matters", the attention "why", the AI assistant, the journal coach prose and all
chart reading stop working and silently fall back to templates.

Everything in Phases 3–7 of the brief — the impact engine, mechanisms, analogs, the
assistant's reasoning — depends on inference. **This must be resolved before Phase 3.**

Verified alternative on the existing key: `gemini-flash-latest` returns 200 and reads a chart
image correctly. `gemini-2.5-flash` returns 404 ("no longer available to new users") and
`gemini-2.0-flash` returns 429 (free-tier token quota exhausted) — so the model id matters.

See `docs/plan.md` §"What I need from you" for the decision requested.

---

## 1. Stack and how it is built

| Concern | Reality |
|---|---|
| Language / runtime | Python 3.12.13 |
| Web framework | FastAPI 0.139.2 on Starlette 1.3.1, uvicorn 0.35 |
| Database | PostgreSQL 16.14 in Docker, volume `pgdata` |
| DB access | psycopg 3.2.9, **raw parameterised SQL, no ORM** |
| Migrations | 23 ordered `.sql` files run by a 40-line runner in `tradeos/db.py` |
| Frontend | React 18.3.1 + Vite 5.4.21. No router, no state library, no CSS framework, no component library. Two runtime dependencies total. |
| Build/serve | Two-stage Dockerfile: node builds `frontend/` → `dist` is copied to `tradeos/static` → uvicorn serves it. Non-root user (uid 10001). |
| Background work | A third container running `python -m tradeos.cli scheduler` |
| Tests | pytest, **189 tests, 0.43s, entirely offline** |
| Lint / format | **None configured.** Only a gitleaks pre-commit hook. |
| CI | **None.** No `.github/workflows`. |

Total: 95 Python files, 21 JSX, 23 SQL migrations, ~24k lines tracked.

### How the app is served

`Dockerfile` stage 1 (`node:24-slim`) runs `npm ci && npm run build`; stage 2
(`python:3.12-slim`) copies the built assets to `tradeos/static`. **Consequence: there is no
frontend hot reload.** Any UI change requires `docker compose up -d --build`. This is the
single biggest friction in the development loop and is worth fixing early (a dev compose
override running `vite dev` with a proxy to the API).

---

## 2. State, persistence, and the data model

There is no client-side state management beyond React `useState` in `App.jsx`. There is no
server-side session state beyond a `sessions` table. Everything durable is in Postgres.

48 tables. The meaningful clusters:

**Signal plane (the original product).** `entities`, `security_map`, `raw_filings`,
`stake_events`, `insider_transactions`, `fund_holdings`, `short_interest`, `signal_clusters`,
`signal_definitions`, `signal_outcomes`, `prices_eod`. Real volume: **664,923 insider
transactions, 51,099 13D/G events, 24,982 13F holdings**, 149 live convergence clusters.
This is a substantial, real dataset that took hours of backfill to build. It is an asset.

**Intelligence plane (added later).** `news_items`, `news_item_entities`, `news_analysis`,
`daily_briefs`, `market_events`, `sentiment_observations`, `wiki_titles`, `chart_analyses`.

**Product plane.** `users`, `sessions`, `login_attempts`, `trades`, `trade_analyses`,
`trade_comments`, `trade_reactions`, `portfolios`, `portfolio_positions`, `watchlists`,
`follows`, `user_follows`, `notifications`, `alert_prefs`, `journal_reports`,
`library_entries`, `invites`, `subscriptions`, `billing_events`, `api_keys`,
`content_reports`, `audit_log`, `feature_flags`, `email_outbox`, `job_runs`, `feed_health`,
`ingest_rejects`, `explanation_cache`.

### The `news_items` table is already 70% of the brief's `Event`

```
brief's Event                 news_items today
─────────────────────────     ──────────────────────────────
id, source, source_url        id, source, external_id, url
published_at, ingested_at     published_at, knowable_time, created_at
title, body                   headline, summary
category                      category
entities[]                    news_item_entities (symbol-only, US equities)
raw_payload                   meta jsonb (partial)
─────────────────────────     ──────────────────────────────
missing: author, author_influence_score, language, geo[], novelty_score,
         amplification, full raw_payload
```

Phase 2 should generalise this into an `events` spine and adapt the existing sources onto it,
rather than starting a parallel table. Detail in `docs/plan.md`.

### Point-in-time discipline is real and load-bearing

Every filing-derived record carries `knowable_time` (when the information became public), and
every backtest query filters on it. This is the difference between a credible track record
and a fake one, and it is already correct. **Do not break it.** The Ledger in Phase 3 should
adopt the same convention.

---

## 3. External integrations — how they are actually wired

The adapter pattern the brief asks for **already exists in spirit**: `tradeos/ingestion/` has
one module per source, and no route handler or component calls an external API directly. What
is missing is the *interface* — the modules are shaped by each vendor rather than by what the
app needs. Formalising `SocialSource` / `NewsSource` / `MarketSource` / `FilingSource` is a
tightening of an existing pattern, not a new architecture.

| Module | Source | Key | Live status (verified) |
|---|---|---|---|
| `edgar_client.py` + `schedule13/form4/form13f/news_sec` | SEC EDGAR | `SEC_USER_AGENT` | connected, fresh to 2026-07-22 |
| `news_rss.py` | CNBC, Fed, SEC RSS | none | connected, fresh to 2026-07-25 01:39 |
| `calendar_nasdaq.py` | Nasdaq earnings + economic | none | connected, 8,033 + 134 records |
| `attention_wiki.py` | Wikipedia pageviews | none | connected — **but see bug B-02** |
| `sentiment_hn.py` | Hacker News | none | connected |
| `coingecko.py` | CoinGecko | none | connected |
| `prices.py` | Tiingo | `TIINGO_API_KEY` | connected |
| `finra.py` | FINRA short interest | none | ingested, flag-gated off |
| `social_reddit.py` | Reddit | `REDDIT_CLIENT_ID/SECRET` | **not connected** — silent no-op |
| `openfigi.py` | OpenFIGI | `OPENFIGI_API_KEY` | **connected** 2026-08-24; 69.2% of holdings resolved, rest are ETPs (B-14) |
| `llm.py` | GitHub Models / Gemini | `OPENAI_*` / `GEMINI_*` | connected, **sunsetting** |

Caching and quota discipline are partly present: per-item analysis is cached in
`news_analysis` and `explanation_cache`, briefs cached by inputs-hash in `daily_briefs`,
chart reads cached by image hash in `chart_analyses`, and `llm.py` has exponential backoff
plus a global cooldown. What is missing is a per-source TTL policy and any logging of quota
cost per call.

### Where secrets live

`.env` at the repo root, gitignored (`.env`, `.env.*` with `!.env.example` exceptions),
injected into containers by `docker-compose.yml`. **`.env` has never been committed** —
verified with `git log --all -- .env` (empty) and a regex sweep of all tracked files for
`sk-`/`ghp_`/`github_pat_`/`AIza` patterns (no hits). A proper gitleaks/trufflehog history
scan is Phase 9 work; neither tool is installed yet.

`.env.example` has drifted: it is **missing** `OPENAI_BASE_URL`, `OPENAI_API_KEY`,
`OPENAI_MODEL`, `SENTRY_DSN`, `OPENFIGI_API_KEY`, `TRADEOS_ADMIN_PASSWORD`,
`TRADEOS_DEMO_EMAIL`, `TRADEOS_DEMO_PASSWORD`, `UPLOADS_DIR`, `DATABASE_URL`.

---

## 4. The background worker

`tradeos/scheduler.py` is 188 lines and is **the strongest piece of infrastructure in the
repo**. It has exactly what Phase 2 asks for:

- a registry of `(name, interval_seconds, fn)` jobs;
- a due-check driven by the last *successful* run recorded in `job_runs`, so restarts neither
  refetch nor lose ground (this is the "persist a cursor per source" requirement, already
  done);
- per-job error isolation — a failure is recorded in `job_runs` with status `error` and never
  stops sibling jobs;
- a `/api/jobs` endpoint exposing last run, status and duration per job.

Nine jobs run today at intervals from 30 minutes (RSS) to 24 hours (Wikipedia). All nine were
`status: ok` at audit time.

**Phase 2 should add jobs and a normalisation step to this scheduler. Building a second
worker would be a mistake.**

---

## 5. Surface-by-surface assessment

Blunt, as requested.

### Keep and extend

**Smart Money** — the best thing in the product. Real SEC data at real volume, a versioned
signal definition, convergence scoring, a backtest that publishes unflattering numbers
(`38% hit rate (n=138)` on the low bucket, `−24.1%` 90-day excess on high). The owner is
right that this is potentially game-changing, and it is closer to done than anything else.
Phase 6's job is to feed its signals into the claim/Ledger machinery, not to rebuild it.

**The scheduler and ingestion layer** — see §4. Extend.

**Morning Brief** — real structure (`what_changed`, `whats_coming`, cached by inputs-hash,
personalised by followed symbols). Its weakness is that the prose is a paragraph of "several
companies reported earnings" rather than analysis. That is a content problem, fixable by
giving it better inputs (claims), not a rewrite.

**News Intelligence** — deterministic impact score plus cited, guarded interpretation, with
`knowable_time` on every item. This is the correct shape for the claim structure. Fold in.

**Dashboard** — well built. Market Pulse shows its own drivers with polarity, honest about
what it measures ("flow & positioning", not "the market"). Extend rather than rewrite; the
one weak tile is "On the radar" (see below).

**Portfolio** — the owner says it adds nothing. That is half right. As a *position tracker*
it is a commodity and should go. But it also contains a **live public track record of
shadowing each conviction bucket against SPY, published even when unflattering** — which is
an early, working version of exactly what Phase 3's Ledger needs. Salvage that mechanism when
Portfolio becomes Exposure.

### Rework

**Social & Attention** — the concept is right (velocity vs each name's own baseline, honest
manipulation flags, transparent source states). The execution was undermined by a data bug
that put `BALL`, `POOL`, `PAG`, `DOV`, `FIX` at the top of the board.

> **Correction (Phase 1).** This section originally attributed that to Wikipedia title
> resolution matching common nouns. That was wrong — the titles resolve correctly. The real
> causes were a fuzzy Hacker News search query and a double-counting error in the board's
> scoring. Both are fixed and measured; see `docs/bugs.md` B-02 for the full trace.

The remaining honest weakness is thinness: with Reddit unkeyed, no connected source measures
*mood*, so every row reads "attention only". That is now stated with a route to fixing it
rather than a bare "n/a".

**Crypto** — the owner is exactly right: a data mirror. Price, 24h, 7d, market cap, sparkline,
gainers/losers, trending. All real, all available free elsewhere, zero interpretation. The
page's own footer admits it: "On-chain flows, whale activity, funding & open interest,
liquidations, and ETF flows need specialized data feeds that aren't connected yet." Rebuild
around interpretation.

**Calendar** — renders as a single flat scroll roughly 10,000 pixels tall listing every
earnings release for ten days. The data is good (8,033 earnings + 134 macro events, with
consensus and previous values). It needs to become a calendar.

**"On the radar"** — not static filler, but not a prioritised live feed either: it is the next
few scheduled calendar entries. Correct call to rebuild it as the Radar's compact view.

**AI Assistant** — a chat box with a grounded system prompt. It reads the user's journal,
watchlist and positions, which is more than "generic", but it has no tools, cannot query the
event store, and cannot cite a specific stored event. Phase 6 rebuild is justified.

**Journal** — the structure is strong (drop/paste capture, auto-detect prefill, coach strip,
performance, simulator, similar-trade finder). The screenshot pipeline is broken in a specific
and fixable way (bug B-01). Fix the guard, then connect the coach to world context.

### Delete

`frontend/src/home.jsx` and `frontend/src/scanner.jsx` — superseded, nothing imports them.
See `docs/dead_code.md`.

---

## 6. Cross-cutting weaknesses

**No routing.** Navigation is `useState` in `App.jsx`. No URLs, no deep links, no browser
back button, nothing indexable. Phase 4 (shareable Radar filter sets), Phase 7 (an indexable
marketing site) and ordinary usability all need this. Adding a router is a Phase 1–2 item,
not a Phase 7 one.

**No error boundaries.** `App.jsx` holds a single `err` string; any failed fetch renders a
red bar above every surface. One failing panel can blank a page. Phase 1 requirement.

**No lint, no formatter, no CI.** Section 5 of the brief asks for one of each, running on
commit. Today there is only a gitleaks hook.

**Documentation has drifted.** `README.md` claims "13 tests" (there are 189) and gives a test
command that fails. `make test` fails. `cli preflight` rejects the provider the app is
actually configured with and offers `anthropic`, which `llm.py` does not implement.

**`tradeos/app.py` is 2,219 lines and 98 routes.** Not yet unmanageable, but it is the only
file that has outgrown its shape. Split by surface opportunistically.

**Observability is partial.** Structured `job_runs` records exist and the middleware logs
unhandled errors without leaking stack traces to clients. There are no request identifiers,
so a failure cannot be traced end to end.

---

## 7. What is genuinely good and worth protecting

Listing these so future phases do not casually break them:

1. **Honest degradation is already a house style.** Sources report `connected` / `needs_key` /
   `unavailable` and the UI renders that state. No fixture data is dressed as live anywhere I
   looked.
2. **Guarded model output with deterministic fallback.** Every model call is wrapped by
   `explain/guards.py` and falls back to a template. The architecture is right; one guard rule
   is wrong (B-01).
3. **Point-in-time correctness** on every filing-derived record.
4. **Published unflattering numbers.** The track record shows `−24.1%` and `38%` without
   burying them. This is the culture the Ledger needs.
5. **Security basics are present**: argon2 password hashing, TOTP for admins, HttpOnly +
   SameSite session cookies, a CSP without `unsafe-inline` for scripts, `X-Frame-Options:
   DENY`, `nosniff`, cross-origin POST refusal, per-route rate limiting, uploads re-encoded
   through Pillow (strips EXIF, neutralises polyglots) and stored under opaque
   `secrets.token_hex(16)` names behind an authenticated route, and owner-only scoping on
   journal reads. Phase 9 will verify all of this adversarially rather than take it on trust.
6. **The test suite is fast and offline** (0.43s, fixture-driven), which makes it cheap to
   keep green.

---

## 8. Numbers, for reference

| Metric | Value |
|---|---|
| Tracked files / lines | 196 / 24,156 |
| Python files / JSX files / migrations | 95 / 21 / 23 |
| API routes | 98 (3 with no frontend caller, all legitimate) |
| Database tables | 48 |
| Tests | 189 passing, 0.43s |
| Insider transactions / 13D-G events / 13F holdings | 664,923 / 51,099 / 24,982 |
| Live convergence clusters | 149 (3 high-conviction) |
| News items ingested | ~350 across 6 feeds |
| Console errors across 12 surfaces | 0 |
| Runtime dependencies (Python / JS) | 10 / 2 |
