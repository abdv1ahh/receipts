# CLAUDE.md — operating manual for this repository

Read this first, every session. Then read `docs/release_readiness.md` (where the work stands) and
`docs/known_gaps.md` (what is deliberately absent, and the sentence the product says about each).

Every command below has been run and verified. If you find one that does not work, fix it here in
the same change that discovers it — a wrong command in this file is worse than no command.

---

## What this is

**Receipts** (`BRAND_NAME`; the Python package is `tradeos` and stays that way). A public,
permanent, tamper-evident record of market calls. A caller publishes a dated directional call
BEFORE the outcome is known, it is sealed into a per-caller SHA256 hash chain, and a database
trigger refuses every delete and every update to a sealed column. It resolves automatically against
Alpaca prices, benchmarked to SPY, with a 2% noise floor and a 25-call sample gate. Anyone can hit
**Verify chain** and watch every hash recompute in their own browser.

Surfaces: `/board` (the landing route) `/publish` `/record` `/call` `/methodology`, plus
`/r/{handle}`.

**This is what is LEFT of a much larger system.** A world-event interpretation engine, an SEC
convergence signal, a trade journal, a news plane, a community and a marketing site were all
deleted on 2026-09-23 — 68 Python modules, 17,945 lines, 113 routes. All of it is runnable at the
tag **`research_platform`** (`845d689`), and `docs/release_plan.md` is the specification that was
executed. If you are looking for something that used to be here, it is at that tag, not gone.

**`/r/{handle}` is THE PUBLIC RECORD and it is server rendered, not the app bundle**
(`receipts/page.py`). It is where every shared link lands, so it is the one page written for
someone with no account: no sidebar, no search, no upgrade button, and exactly one outbound link in
the whole document — `/claim`. It carries the counts, the rate or the reason there is none, the
losses ahead of the breakdowns, every open call with the stored reason and the time we last looked,
and every call. **Its Verify button recomputes the chain in the VISITOR'S browser**
(`receipts/verify.js` over `/api/receipts/{handle}/chain`, which hands over the sealed fields and
states no verdict of its own — a server answering `intact: true` is the operator asking to be
trusted, on the page whose argument is that you need not). It also offers to break the record in
front of you, in your browser, so the check is visibly capable of saying no. A test asserts the
document holds no app chrome and exactly one internal link.

**The first two records on the board are OURS** — `@convergence-v3` (323 calls) and
`@convergence-v4` (150), imported from the retired signal plane's own resolved claims. Pooled they
read **43.2% of 412**, below a coin flip, with an expectancy interval that spans zero. That is the
point and it must never be presented as a positive result. **They are also a SEALED BACKTEST**:
imported already-scored and sealed together after their outcomes were known, unlike every call
published through the product. Four surfaces say so and none of them may stop.

---

## Stack (verified versions)

| Layer | What | Version |
|---|---|---|
| Runtime | Python | 3.12.13 |
| API | FastAPI + Starlette, served by uvicorn | 0.139.2 / 1.3.1 |
| DB driver | psycopg (v3, binary) | 3.2.9 |
| Database | PostgreSQL (Docker `postgres:16`) | 16.14 |
| HTTP client | httpx | 0.28.1 |
| Images | Pillow (the share card only) | 12.3.0 |
| Auth | argon2-cffi, pyotp (TOTP for admins) | 23.1.0 / 2.9.0 |
| Tests | pytest | 9.0.3 |
| Frontend | React + Vite. Routing is ~40 lines over the History API in `shell.jsx`; no state library, no CSS framework | 18.3.1 / 5.4.21 |
| Node (build) | node / npm | 24.18 / 11.16 |

Ruff is the linter (not the formatter — see the note in `pyproject.toml`). There is **no ORM**
(raw SQL through psycopg), **no migration framework** (ordered `.sql` files run by `tradeos/db.py`),
and **no dependency injection / event bus / state machine**. Keep it that way.
`requirements.txt` is 10 lines. Adding to it is a decision, not a reflex.

---

## Commands

All of these are run from the repository root.

### Run the app

```bash
./scripts/setup.sh                    # first run: writes .env with a generated DB password
# paste an Alpaca key pair into .env  (free, no card: app.alpaca.markets/signup)
make quickstart                       # build + migrate + a month of closes for every symbol (~84s)

docker compose up -d --build          # api :8000, postgres :5432, worker (scheduler)
docker compose logs -f api
docker compose down
```

The app is at <http://localhost:8000>. `docker-compose.yml` has **no default database password**
and the stack refuses to start without one.

`cli seed-demo` creates an account and a handle with **no calls**, and GENERATES its password,
printing it once. It seeds nothing to publish on purpose: inventing calls would put fabricated
entries into a permanent sealed public record. It also refuses to run when `COOKIE_SECURE=true`
unless given `--i-know`.

### Tests

```bash
make test     # 390 passed, 2 skipped. Offline: no Alpaca key, no network, no live prices
make test-js  # the cross-language guard on the sealed wire format, PLUS export/check.mjs. HOST
make lint     # ruff; zero errors is the standard
make dev      # reload-in-place stack; then `make web` for a UI change
make fix      # ruff --fix
```

`tests/` is deliberately not copied into the production image, so the suite runs against a mount.
`make test` does that for you.

**THE SAME NUMBER IN ALL THREE SETUPS, AND THE SETUP IS PART OF THE NUMBER.** Measured 2026-09-24:

| database | `make test` |
|---|---|
| fresh clone — `setup.sh`, `make quickstart` (baseline, 19 tables) | **390 passed, 2 skipped** |
| operator shape — the 37 ordered migrations (64 tables) | **390 passed, 2 skipped** |
| this machine's live instance | **390 passed, 2 skipped** |

It did not use to be one number. The suite scored 390 on a database with the 37 ordered migrations
and **363 passed, 27 failed, 6 errors** on a fresh clone, and a release report claimed the first
figure for the second setup — a number quoted without its setup is how that happens. Three causes,
all now fixed: a teardown fixture deleted from `user_profiles`, a table the baseline never creates;
`seed-house-records` read the deleted signal plane's tables and sealed nothing; and eight scoring
tests built their fixtures out of whatever `prices_eod` happened to hold, so they needed an Alpaca
key and a year of history to pass.

**The scoring tests use `tests/fixtures/prices_synthetic.json` and never read `prices_eod`.** It is
generated by a closed form recorded inside the file, and its dates are absolute and in the past —
a fixture anchored to `today` is a fixture that starts failing on a date nobody chose. It is not
vendor data, so gotcha 1 does not reach it. The `synthetic_market` fixture in `tests/conftest.py`
is the only way into it.

**The two skips are environment-conditional and both name a guard that does run:** `node` is absent
inside the API image (`make test-js` covers it on the host), and `docker-compose.yml` is not
mounted into the container (the host reads it from a checkout). Anything else that skips is a bug.

**`make test-js` is not optional and `make test` cannot replace it.** `chain.py` and
`receipts/verify.js` must produce byte-identical payloads forever, because the public record page
lets a visitor recompute the chain in their own browser — a JS framing that disagrees by one byte
reports every intact record as broken. `make test` runs inside the API image, which carries no
node; the host that has node has no Python dependencies. Both sides check one committed fixture
(`tests/fixtures/receipt_chain.json`, five links including an empty thesis, a four-byte emoji, and
a thesis that spells out a field header to try to smuggle structure past the framing).
**Run both after touching either side.**

### Frontend

```bash
make dev      # once: starts the reload-in-place stack
make web      # after every UI edit (~0.3s) — this is what makes the change visible
```

**In production the bundle is baked into the image at build time**, so without `make dev` a UI
change needs a full `docker compose up -d --build`. `frontend/dist/` and `tradeos/static/` are
gitignored.

### Data / operations CLI

```bash
docker compose exec -T api python -m tradeos.cli <command>
```

All 12, checked against `--help` rather than remembered, and pinned by `tests/test_cli_commands.py`:

`migrate` · `ingest-prices` (alias `ingest-prices-alpaca`) · `check-source` · `scheduler` ·
`seed-admin` `seed-demo` `seed-house-records` `create-invites` · `resolve-calls` `verify-chain`
`export-records` · `status` `preflight`.

`ingest-prices --universe` builds the ticker list from **Alpaca's own asset endpoint** and reads no
research table — 13,170 tradable non-OTC US symbols. `--only-stale` is the scheduler's top-up
selector and puts SPY first, because a stale benchmark blocks everything.

`check-source alpaca` makes a REAL call and says whether the credential works, which is the
question `status` (what has been ingested) and `preflight` (what is configured) both leave
unanswered right after someone pastes a key in.

`export-records` writes every sealed chain to a directory that verifies with **no server and no
database** — `node export/check.mjs`. A record that can only be checked while its author keeps a
server running is a record with an expiry date.

### Database

```bash
docker compose exec -T db psql -U tradeos -d tradeos -c '\dt'    # 19 tables on a fresh install
docker compose exec -T db psql -U tradeos -d tradeos             # interactive
```

---

## Directory map

```
tradeos/                  the Python package (all backend code) — 31 modules, 7,300 lines
  app.py                  FastAPI app: 32 routes, ~1,100 lines
  db.py                   psycopg connect() + the migration runner, WHICH CHOOSES between
                          migrations/ (37 ordered files, for a database with history) and
                          migrations/baseline/ (one file, for an empty one)
  config.py               env accessors; raises ConfigError rather than defaulting secrets
  stats.py                mean_ci, proportion_z, sample_needed, confidence_bucket. Pure.
  prices.py               price_series, verdict_for, UNSCOREABLE_REASONS. The only path a price
                          takes to the scorer, and the one definition of "does that count as a hit"
  sources.py              the source registry — 4 entries. Backs every gate
  authn.py  apikeys.py    sessions (argon2, TOTP for admin), API keys
  flags.py                DB-backed feature flags enforced on the request path
  ratelimit.py            sliding-window limits on the public + publish paths. IN-PROCESS
  scheduler.py            the worker: 2 jobs (ingest_prices, resolve_calls) + the zero-output alarm
  mail.py                 the ONE outbound-email path. Refuses to send unconfigured
  oauth.py                Sign in with Google. Built, config-gated, NEVER RUN against Google
  backtest/engine.py      Series, entry_day_after, exit_day_for, excess_return, wilson_interval
  ingestion/              prices_alpaca.py (THE price path + the work-list order), common.py
  receipts/               THE PRODUCT. chain.py (pure, the wire format) calls.py scoring.py
                          record.py verification.py seed.py context.py card.py universe.py
                          page.py   the server-rendered public record at /r/{handle}. No bundle
                          verify.js the visitor's own check, run in THEIR browser. Served as a
                                    file at /receipt-verify.js, because script-src 'self' refuses
                                    an inline script silently
  migrations/             001..037 ordered .sql, plus baseline/001_baseline.sql. NEVER edit an
                          applied migration, and every file MUST insert its own
                          schema_migrations row
export/                   the house chains + check.mjs, verifiable offline. `make test-js` runs it
frontend/src/             React, 16 files. App.jsx is 174 lines and four rail items
tests/                    pytest; offline, fixture-driven
docs/                     release_plan, release_readiness, known_gaps, research/, analysis/,
                          runbooks/, threat-models/, archive/
```

---

## Conventions this repo actually follows

- **Module docstring first**, saying what the module is *for* and often which decision produced it.
- **Comments explain why, not what.** Especially why an obvious approach was rejected. A rule
  without its measurement gets "simplified" away inside a year.
- `from __future__ import annotations`; modern `X | None` types.
- **Raw SQL, always parameterised.** Where SQL has to be *composed*, use `psycopg.sql`, never an
  f-string. Ruff's `S608` enforces it.
- **Honest degradation over fabrication.** When a source is missing the API returns a state and the
  UI says so. There is no fixture data presented as live anywhere, and there must never be.
- Frontend: functional components, hooks only, `fetch` through `frontend/src/api.js`, plain CSS.
- Naming: snake_case Python, camelCase JS, kebab-case CLI commands, `_leading_underscore` for
  module-private helpers.

---

## Gotchas that will cost you an hour

The ones that bite fastest. Everything below was measured, not guessed.

1. **NO PRICE MAY APPEAR ON ANY SCREEN.** Alpaca's terms permit no redistribution and carry no
   exception for display. The four price columns and the two component returns are stored, sealed
   by migration 035, and **never SELECTed** — `calls._LIST_COLUMNS` does not load them, which is
   the enforcement. A filter at the route has the same hole one route later. What replaces them is
   the two session DATES, which are exact, are ours, and let anyone reproduce the excess return
   from any feed. `record.NO_PRICES` and `record.RECOMPUTE_NOTE` are the one place the reason is
   written; every surface reads them. `tests/test_price_redistribution.py` plants six-decimal
   prices and sweeps every route.

2. **A VERDICT ON A CALL IS PERMANENT, so never seal an operational failure as one.** A call is
   sealed `unscoreable` if and only if **no price series exists for its symbol**. Nothing else may
   seal, and in particular no gap in OUR BENCHMARK, ever — one missing SPY session once sealed a
   healthy MSFT call while blaming MSFT's feed, which ran ten days past it. A missing exit price
   always leaves the call OPEN with a stored reason; a lagging benchmark BLOCKS publishing.
   `resolve_due` refuses the whole batch on a benchmark fault rather than scoring the calls it
   happens not to touch.

3. **A RESOLVED CALL IS IMMUTABLE INCLUDING ITS ARITHMETIC** (migration 035). 034 sealed the
   verdict and said nothing about the nine columns it is computed from, so
   `UPDATE calls SET excess_return = 0.42 WHERE verdict = 'miss'` succeeded and every hash still
   verified. `resolved_at` is the switch. `context_snapshot` is sealed too.

4. **`resolve_due` IS A BATCH OVER THE WHOLE TABLE, and the suite runs against the live database.**
   A test called it unscoped with `_series` monkeypatched to a fixture, so it picked up a real
   stranger's public open call and rewrote that call's public "why is this still open" sentence
   from prices that do not exist. Under a fixture series spanning the horizon it would have sealed
   a permanent verdict on it. It takes `caller_id` now; tests pass their own scratch caller.

5. **THE WIRE FORMAT HAS TWO IMPLEMENTATIONS IN TWO LANGUAGES.** See `make test-js` above. The
   length prefix is in **bytes, not characters**, and the framing is length-prefixed rather than
   delimited *on purpose*: a caller writes their own thesis, and with a plain separator they could
   type the separator into it and make two different calls serialise identically. Field order is
   frozen forever; a test pins it.

6. **`script-src 'self'` means an inline `<script>` is refused with NOTHING in our logs.** That is
   why the verifier is a file. Related: **`--reload-include '*.js'` DOES NOT WORK HERE** — it needs
   `watchfiles`, which is not in `requirements.txt`, so uvicorn falls back to `StatReload`, which
   only `rglob`s `*.py`. `app.py:_verify_js()` caches on the file's **mtime** instead.

7. **WebCrypto is undefined outside a SECURE CONTEXT, and `localhost` hides it.** `crypto.subtle`
   exists on https and on localhost and nowhere else, so the verifier works perfectly in
   development and is dead on a plain-http LAN address — which is what a bare `docker compose up`
   with no proxy serves. `verify.js` checks and says which of the two things is wrong.

8. **A FRESH DATABASE TAKES `migrations/baseline/`, an existing one takes the 37 ordered files.**
   The rule is whether `schema_migrations` is empty. Adding migration 38 means updating the
   baseline too; `tests/test_migrations.py` migrates two scratch databases and diffs them. Note
   `pg_dump -t table` emits CREATE TRIGGER and **not** the function it calls, and Postgres accepts
   that until the first UPDATE — which is how a baseline ships an append-only record that is not
   append-only.

9. **THE PRICE WORK LIST'S ORDER IS BEHAVIOUR.** `_STALENESS_ORDER` is oldest-data-first with an
   `md5(symbol)` tie-break, because an alphabetical selector made price staleness alphabetically
   biased while the table reported 99% fresh. On a FRESH database everything is equally stale, so
   it falls back to sorting by symbol — which is why the quickstart loads a short window over every
   symbol rather than a long window over 400 of them, and why ten household names were once absent.

10. **Alpaca's default feed is SIP, which this plan may not query — always send `feed=iex`.** And
    Alpaca spells a class share with a **DOT** (`GEF.B`, not `GEF-B`); one wrong symbol rejects the
    whole batch of 100, so `daily_batch` converts on the wire and maps back.

11. **A key in `.env` does NOT reach the container.** `docker-compose.yml` enumerates every
    variable explicitly, so a key added to `.env` alone is silently absent from `api` and `worker`.
    Add it in BOTH services, then `docker compose up -d api worker`.

12. **`reject()` and `redact()` are one thing, and the reason is a leaked key.** httpx puts the full
    request URL in its exception message. Redaction happens INSIDE `reject`, not at the call sites.
    Never store `str(exc)` from an HTTP client without it, and never write a second redactor.
    Better still: **authenticate with a HEADER**, and redaction stops being load-bearing.

13. **A grid or flex track written `1fr` is `min-width: auto`** and will not shrink below its
    content. Write `minmax(0, 1fr)`. **Check a UI change at 375px, not just at your window width.**
    And a media query adds NO specificity, so narrow-screen overrides must sit at the END of
    `styles.css`; there is a marked block there.

14. **`_require_admin` returns the USER on success, None on failure.** Branch on `if not ...`.

15. **Run the browser check as well as the tests** — a missing import has passed the whole suite
    and thrown on the page.

16. **The suite can go green by not running.** The DB-backed files open with
    `try: import ...; except Exception: _IMPORTS_OK = False` and skip the whole file. That cannot
    tell "no psycopg here" from "this file imports something deleted", and once hid 38 assertions
    on the public HTTP boundary behind a green "354 passed".
    `tests/test_suite_integrity.py` closes it.

---

## External sources

| Source | Key needed | Powers | State |
|---|---|---|---|
| Alpaca Market Data | `ALPACA_API_KEY_ID` + `_SECRET_KEY` | EOD prices — **the only external service this product needs** — and the ticker universe | connected |
| SMTP | `SMTP_HOST` + `MAIL_FROM` | email verification and password reset | not connected (see known_gaps §1) |
| Google OAuth | `GOOGLE_CLIENT_ID` + `_SECRET` | sign-in without a password | config-gated, never run live |
| Sentry | `SENTRY_DSN` | error tracking | not connected |

`tradeos/sources.py` is the registry of record — a source missing from it is invisible to the
operator no matter how badly it is failing, and a source LISTED but no longer talked to tells an
operator to paste a key for a surface that does not exist. A test asserts the catalog is exactly
these four.

Every external call goes through `tradeos/ingestion/`. **Never call an external API from a route
handler or a component.**

---

## Definition of done for any change

- `make test`, `make test-js` and `make lint` all pass.
- The app runs with **no console errors** — check in a browser, do not assume.
- **The three chains still verify with the same link counts and head hashes.**
- No fabricated data anywhere, including empty states.
- Every displayed fact carries source + timestamp + link.
- Every new panel has real loading, empty, and error states.
- Documentation reconciled with reality in the same commit that changed the behaviour.
- Dead code removed and reported, not commented out.
