# TRADEOS_AUDIT.md — a read-only forensic audit of the repository at `/path/to/receipts`

Compiled 2026-08-21 by walking the entire directory tree, reading every configuration file, every
migration, every Python module, every React component, every stylesheet, every test and every
document in `docs/`, and by cross-referencing the code against the project's own claims about
itself. Nothing was edited, created, deleted or executed that changes state. The one exception is
this file.

**One limitation, stated up front because it affects section 7.** The Docker daemon is not running
on this machine — `docker ps` fails with `dial unix ~/.docker/run/docker.sock: connect:
no such file or directory` — and there is no local PostgreSQL server outside Docker. I therefore
could not execute a single read-only query against the database. Every table, column, type,
nullability, default, index, constraint and relation described in section 7 is read from the
migration DDL, which is authoritative for the schema. **Row counts are not.** Where I give a row
count it is quoted from the project's own written record (`docs/state.md`, `docs/progress/`,
`scripts/backup.sh`) with the source named, and it should be treated as a measurement someone else
made on a date I can see rather than as something I verified. That distinction is made every time
a number appears.

---

## 1. What this product actually is

Read only the README and you are told this is "a world-event interpretation engine that happens to
be very good at explaining market consequences", answering the question *something just happened in
the world, so what does it mean for me specifically?* Read the code and that is broadly true, but it
is only about half of what is actually running, and the half the marketing describes is the younger,
thinner half.

What exists in the repository is two distinct products fused into one deployable, sharing a
database, an authentication layer, a scheduler and a React shell, but built years apart in
intellectual terms and measured by two completely separate track records.

The **older product** — the one with all the data behind it — is a US-equity smart-money
disclosure engine. It ingests SEC EDGAR filings directly from the source: Form 4 insider
transactions, Schedule 13D and 13G large-stake and activist filings, Form 13F quarterly
institutional holdings, and 8-K material-event filings. It resolves every filer and issuer to a
canonical entity by CIK, maps issuers to tickers through the SEC's own `company_tickers.json` and
13F CUSIPs through OpenFIGI, and then computes a "convergence" signal: a score that fires when many
*independent* smart-money voices cluster on one issuer inside a rolling 90-day window. The scoring
lives in `tradeos/signals/convergence.py` and is deliberately hash-locked — the module's own sha256
is stored in the database alongside the signal definition, and `compute-signals` refuses to run if
the two disagree, which forces a version bump and a changelog before the signal can silently change
meaning. That signal is then backtested against SPY at 30, 90 and 180 days by
`tradeos/backtest/engine.py` and `tradeos/backtest/run.py`, with entry defined as the close of the
first trading day strictly *after* the signal's `as_of`, so look-ahead leakage is structurally
impossible rather than merely avoided.

The **newer product** — the one the README, the marketing site and the display name "Rhumb"
describe — is a world-event interpretation engine. It ingests global news (GDELT, eleven RSS feeds
spanning five countries, Bluesky posts from a curated list of consequential institutional accounts),
normalises every arrival into a single `events` row through `tradeos/spine.py`, clusters
near-duplicate reports of the same happening using PostgreSQL trigram similarity plus a
shared-proper-noun corroborator, scores each cluster for novelty and amplification, and then feeds
the highest-novelty clusters to a language model with a very carefully constructed prompt
(`tradeos/claims.py`). The model's job is to produce a **claim**: a causal mechanism in prose, a
list of affected assets/sectors/currencies/regions/commodities each with a direction and magnitude,
a horizon, a numeric confidence between 0 and 1, historical analogs, and a step-by-step reasoning
trace. Every claim is timestamped the moment it is made and is later scored against what actually
happened by `tradeos/ledger.py`, which measures excess return versus SPY and writes a verdict of
hit, miss, inconclusive or unscoreable.

The thing that makes the two halves one product is the **Ledger**. Both planes write claims into
the same `claims` table and are scored by the same machinery. `tradeos/smartmoney_claims.py` exists
precisely to convert historical convergence signals into scoreable claims so the older plane's
long history gets measured by the newer plane's honesty apparatus.

**Who it serves.** On the evidence of the code: a self-directed retail or semi-professional trader
who wants situational awareness rather than trade calls, and who is not American — the
personalisation machinery is built around the premise that the same event reads differently from
Sharjah than from São Paulo, and the ten hand-curated countries in `tradeos/relevance.py` are
United Arab Emirates, Saudi Arabia, United States, United Kingdom, India, China, Brazil, Japan,
Germany and Singapore, weighted, as the module's own comment says, "toward the places this
product's early users actually are". The Gulf is listed first.
Free-tier data is delayed 48 hours by a server-side `WHERE` clause; paid tiers
see it live; there is an API key tier for programmatic access.

**The problem it solves, honestly stated.** Not "find me alpha". The product's own defensible claim
is narrower and better: financial news tells you *what* happened and leaves you to guess the
consequence; this system commits, in writing, before the outcome exists, to a specific causal
mechanism, a specific set of affected assets, a specific direction and a specific horizon — and
then publishes whether it was right, misses first. That is a falsifiability product. It is not
selling accuracy; it is selling a scoreable record. The marketing site's H2 is "Every call is
scored, including the bad ones."

**The uncomfortable fact the code is honest about, and which any reader of this report needs
immediately.** According to `docs/progress/cross_check.md`, which records measurements taken
directly against the database on 2026-07-26 and later, **every single one of the resolved calls in
the Ledger belongs to the older smart-money signal, not to the interpretation engine the product
sells.** The interpretation engine had 80 open claims and zero resolved. The signal plane's record
at the last recorded measurement was 412 resolved calls at a 43.2% hit rate with a mean excess
return of −1.18% per call and a 95% confidence interval of [−2.93%, +0.57%] which spans zero. The
project's own conclusion, which is correct: the directional hit rate is genuinely below chance at
z = −2.76, but the return is *not* distinguishable from zero because the wins are larger than the
losses, so on this sample no edge is demonstrated in either direction. It would take roughly 1,270
resolved calls at the measured dispersion to detect a 1% per-call edge. There are 412.

So: the product that is being sold has no track record yet, and the product that has a track record
has not been shown to work. The code says this out loud in `ledger.summary()`, which returns
`open_by_origin` specifically so no surface can pool the two planes, and there is a test asserting
they are never pooled. That is unusually honest engineering. It is also the single most important
fact about the state of this business.

---

## 2. The complete tech stack, with exact versions

There is no `package.json` at the repository root. This is a Python repository with two sibling Vite
front ends, not a JavaScript monorepo, and that was a deliberate decision recorded in `docs/plan.md`
§6.

**Runtime and language.** Python, pinned to 3.12 in the production image (`FROM python:3.12-slim`
in `Dockerfile`) and targeted as `py312` by Ruff in `pyproject.toml`. The local development
virtualenv at `.venv/` is Python **3.13**, which is a mismatch worth knowing about — the container
and the local venv are not the same interpreter. Every module opens with `from __future__ import
annotations` and uses modern `X | None` union syntax.

**API framework.** FastAPI **0.139.2** on Starlette **1.3.1**, served by uvicorn **0.35.0**. In
development uvicorn runs with `--reload`; in production `docker-compose.prod.yml` runs it with
`--proxy-headers --forwarded-allow-ips "*" --workers 2`. Pydantic **2.13.4** with pydantic-core
**2.46.4** arrives as a FastAPI dependency and is used directly for the ~25 request-body models
declared at the top of `tradeos/app.py`.

**Database and driver.** PostgreSQL 16 via the official `postgres:16` Docker image. The driver is
psycopg **3.2.9** with the binary extra (`psycopg[binary]`). There is **no ORM**. Every query is raw
SQL with `%s` parameter binding, and where SQL genuinely has to be *composed* — a column list, an
optional WHERE, a table name from an allowlist — it is built with `psycopg.sql.Identifier`,
`psycopg.sql.Placeholder` and `psycopg.sql.SQL`, never an f-string. There is **no migration
framework**: `tradeos/db.py` is a 41-line module that globs `tradeos/migrations/*.sql`, sorts them,
skips any version already present in `schema_migrations`, and executes the rest.

**HTTP client.** httpx **0.28.1**, used by every ingestion adapter and by `tradeos/llm.py`.

**Images.** Pillow. Here there is a genuine version discrepancy: `requirements.txt` pins
`Pillow==12.3.0`, `CLAUDE.md` claims 10.4.0, and the installed local virtualenv contains
`pillow-10.4.0.dist-info`. The correct value is almost certainly **12.3.0** — `docs/progress/phase_9.md`
documents the upgrade from 10.4.0 to 12.3.0 in detail, including the two specific CVEs in the PSD
decoder (PYSEC-2026-2249, an out-of-bounds write, and PYSEC-2026-2252, a memory-corruption path)
that motivated it. `CLAUDE.md` and the local venv are both stale.

**XML.** defusedxml **0.7.1**, used for every XML parse (Form 4 ownership documents, 13F information
tables, RSS/Atom feeds) so that XXE and entity-expansion attacks are closed by construction.

**Authentication.** argon2-cffi **23.1.0** (argon2id, library defaults) for password hashing, and
pyotp **2.9.0** for TOTP, which is mandatory for the admin tier. Session tokens are 32 bytes of
`secrets.token_urlsafe`, stored only as a SHA-256 hash in the `sessions` table, delivered in an
HttpOnly, SameSite=Lax cookie named `tos_session`, `Secure` when `COOKIE_SECURE=true`.

**Tests.** pytest **9.0.3**. Also present in the venv as transitive dependencies: pluggy 1.6.0,
iniconfig 2.3.0, packaging 26.2, anyio 4.14.2, h11 0.16.0, httpcore 1.0.9, certifi 2026.7.22, idna
3.18, click 8.4.2, cffi 2.1.0, pycparser 3.0, typing_extensions 4.16.0, typing_inspection 0.4.2,
annotated_types 0.7.0, annotated_doc 0.0.4, pygments 2.20.0.

**Linting.** Ruff (version 0.16.0 by the cache directory name), configured in `pyproject.toml` with
rule sets F (pyflakes), E and W (pycodestyle), I (import sorting), UP (pyupgrade), B (bugbear), S
(bandit) and C4 (comprehensions), line length 108. E501, S101 and B008 are globally ignored, with
reasons given. S608 — SQL built by string concatenation — is explicitly **on** as of Phase 9 and is
suppressed only inside `tests/*`, because `tests/test_slice2.py` builds a regex asserting that every
migration registers its own version and Ruff cannot distinguish an assertion about SQL from SQL.
`ruff format` is deliberately **not** adopted, with a written justification: checked against the
tree on 2026-07-25, it de-indented continuation strings and stripped the aligned trailing comments
this codebase uses in roughly 89 files.

**Frontend framework.** React **18.3.1** with react-dom **18.3.1**, built by Vite **5.4.21** with
`@vitejs/plugin-react` **4.3.3** and Node **24** (the Dockerfile uses `node:24-slim`; CI uses
node-version "24"). Both front ends declare `"type": "module"`.

**Styling approach.** Plain CSS in a single stylesheet per front end, with CSS custom properties as
design tokens. There is **no CSS framework**, no Tailwind, no CSS-in-JS, no CSS modules. The app's
stylesheet `frontend/src/styles.css` is 1,759 lines; the site's `site/src/styles.css` is 492 lines.
Both `@import "../../shared/tokens.css"` as their first line, which holds the measurements the two
front ends agree on. Colour is deliberately *not* shared.

**UI library.** None. There is no component library, no Radix, no shadcn, no MUI. Every component in
`frontend/src/components.jsx` and the surface files is hand-written. Icons are hand-drawn inline SVG
in `frontend/src/icons.jsx`.

**State management.** None. No Redux, no Zustand, no Jotai, no React Query, no SWR. State is
`useState` and `useEffect` in `frontend/src/App.jsx`, which holds roughly twenty pieces of state and
passes callbacks down as props.

**Routing.** Hand-rolled. `frontend/src/shell.jsx` exports a `useRoute()` hook that is about forty
lines over the browser History API: it reads `window.location.pathname` and the query string, listens
for `popstate`, and exposes `go(path, query)` (pushState) and `replace(path, query)` (replaceState).
There is no react-router. The decision is recorded in the file's own comment: "this app needs a path,
a query string, and a back button, and that is ~40 lines over the History API."

**Data fetching.** Bare `fetch` wrapped in `frontend/src/api.js`, which exports about 100 named
functions. There is no caching layer, no request deduplication, no stale-while-revalidate. Every
surface fetches in a `useEffect` on mount.

**3D.** `react-globe.gl` **2.38.0** and `three` **0.185.1**, used only by
`frontend/src/globe3d.jsx`, which is **lazy-loaded** via `React.lazy` from `frontend/src/globe.jsx`
and gated behind a WebGL capability check. The built chunk is 2,075,064 bytes — larger than the
entire rest of the app bundle, which is why it must never be imported statically.

**Fonts.** The app uses system font stacks only (`ui-monospace, "SF Mono", …` and `"Inter",
-apple-system, …`), so it makes no font request. The marketing site self-hosts three fonts via
fontsource: `@fontsource/instrument-serif` **5.3.0** (display, single weight),
`@fontsource-variable/inter` **5.3.0** (body), and `@fontsource/ibm-plex-mono` **5.3.0** (every
figure, timestamp and source). Self-hosting is deliberate — no external font request, so first paint
never waits on a third party and no visitor's IP reaches one.

**Hosting target.** Self-hosted Docker Compose on a small Linux VPS. `docker-compose.prod.yml`
defines four services: `db` (postgres:16, no published ports, reachable only on the internal compose
network), `api` (built from the Dockerfile, no published ports), `worker` (the same image running
`python -m tradeos.cli scheduler`), and `caddy` (caddy:2, the only service binding 80 and 443).
`deploy/Caddyfile` terminates TLS with automatic Let's Encrypt provisioning for `$DOMAIN`, proxies
to `api:8000`, strips the `Server` header, enables gzip and zstd, and caps request bodies at 9MB to
sit just above the API's own 8MB upload limit. `DEPLOY.md` at the root is the 120-line runbook;
`docs/deploy.md` is a longer 201-line reference. Neither has ever been executed against a real host,
which `docs/state.md` states plainly.

**Optional and conditional dependencies.** `sentry-sdk` is imported inside a `try` block in
`tradeos/app.py` only when `SENTRY_DSN` is set, and logs a warning if the DSN is set but the SDK is
absent. `stripe` is imported lazily inside `tradeos/billing.py` functions and
`billing.provider_configured()` returns False unless both `STRIPE_SECRET_KEY` is set **and** the SDK
imports. Neither is in `requirements.txt`, which is ten lines long and, as `CLAUDE.md` puts it,
"adding to it is a decision, not a reflex."

---

## 3. The full directory tree, file by file

### Repository root

`.dockerignore` — nine lines excluding `**/node_modules`, `frontend/dist`, `.venv`,
`**/__pycache__`, `**/*.pyc`, `.git`, `.env`, `.DS_Store` and `tradeos/static` from the Docker build
context.

`.env` — the live local environment file, gitignored. I enumerated its variable names without
printing any value. It sets `SEC_USER_AGENT`, `TIINGO_API_KEY`, `GEMINI_API_KEY`, `GEMINI_MODEL`,
`GEMINI_MODEL_FAST`, `EXPLAIN_PROVIDER`, `OPENAI_BASE_URL`, `OPENAI_API_KEY` and `OPENAI_MODEL`.
All nine carry non-empty values. `EXPLAIN_PROVIDER` is thirteen characters, consistent with
`gemini,openai`. Notably **absent** from the live `.env`: every SMTP variable, both Google OAuth
variables, `REDDIT_CLIENT_ID`/`REDDIT_CLIENT_SECRET`, `YOUTUBE_API_KEY`, `OPENFIGI_API_KEY`,
`PUBLIC_BASE_URL`, `BRAND_NAME`, `COOKIE_SECURE` and every Stripe variable. Those all fall back to
their defaults, which is why email cannot send, Google sign-in cannot run, Reddit is dark and
billing is in free-launch mode.

`.env.example` — 90 lines, the documented template, organised into required / language model / data
sources / Google sign-in / outbound email / runtime / seeding / billing. Every entry carries a
comment naming where the free key is obtained. This file was previously missing ten variables the
code reads (bug B-07) and has since been corrected.

`.env.production.example` — 52 lines, the production template. Requires `DOMAIN`,
`POSTGRES_PASSWORD` (with `:?` so compose refuses to start without it), `POSTGRES_USER`,
`POSTGRES_DB` and `SEC_USER_AGENT`. Defaults `EXPLAIN_PROVIDER=template`. Its OpenAI section
recommends GitHub Models at `https://models.github.ai/inference` — which, per bug B-04, was
scheduled for sunset on 2026-07-30. Today's date is 2026-08-21, so **that recommendation is now
dead advice**.

`.gitignore` — 31 lines. Ignores `.env` and `.env.*` with negations for the two `.example` files;
`__pycache__/`, `*.py[cod]`, `.pytest_cache/`, `.venv/`, `venv/`; `node_modules/`, `frontend/dist/`,
`tradeos/static/`, `site/dist/`, `tradeos/site_static/`; `.DS_Store`, `*.swp`, `.idea/`, `.vscode/`;
`*.log`, `.gstack/`; and `backups/`.

`.pre-commit-config.yaml` — nineteen lines wiring exactly one hook: gitleaks v8.21.2, the
secret-scanning tripwire.

`CLAUDE.md` — 22,531 bytes, the operating manual for AI agents working on the repository. It carries
the stack table, the command list, the directory map, the conventions, the gotchas (numbered oddly
as 0, 0a, 0a0, 0a2, 0a3, 0b2, 0c, 0d, 0e, then 1 through 12), the external-source table, and the
definition of done. It is the single densest document in the repository and it is largely accurate,
with the exceptions catalogued in section 18 below.

`DEPLOY.md` — 120 lines, the copy-paste production runbook: install Docker, clone, configure
`.env.production`, bring up `docker-compose.prod.yml`, run migrations, seed an admin. Still titled
"Deploying TradeOSS to production" using the internal codename rather than the display name.

`docker-compose.yml` — the default local stack. Three services: `db` (postgres:16 with a
`pg_isready` healthcheck, publishing 5432 to the host, with a `pgdata` volume, using the dev
credentials `tradeos`/`tradeos` which the file itself flags as local-only), `api` (built from the
Dockerfile, publishing 8000, mounting an `uploads` volume at `/app/uploads`, waiting on the db
healthcheck) and `worker` (the same image running the scheduler).

`docker-compose.dev.yml` — a 28-line override. Replaces the api command with uvicorn `--reload`,
bind-mounts `./tradeos` for live source, `./tests` (deliberately not in the image), `./frontend/dist`
read-only over `/app/tradeos/static` and `./site/dist` read-only over `/app/tradeos/site_static`, and
sets `DEV_ORIGINS=http://localhost:5173,http://localhost:5174` so the Vite dev servers pass the CSRF
origin check.

`docker-compose.prod.yml` — 66 lines, the four-service production stack described above.

`Dockerfile` — 31 lines, two stages. Stage one (`node:24-slim`, named `web`) works in
`/src/frontend`, copies the two package files, runs `npm ci`, copies `shared/` to `/src/shared` and
then `frontend/`, and runs `npm run build`. The layout deliberately mirrors the repository rather
than flattening, because `styles.css` imports `../../shared/tokens.css` and a flattened layout
resolves that outside the build context — a bug that made the production image unbuildable for two
phases while `make dev` kept working, found in Phase 9. Stage two (`python:3.12-slim`) upgrades pip,
installs requirements, copies `tradeos` and `content`, copies the built bundle from stage one to
`./tradeos/static`, creates a non-root user `appuser` with uid 10001, chowns `/app`, switches to that
user, exposes 8000 and runs uvicorn. `tests/` is deliberately **not** copied.

`FREE-AI.md` — 71 lines explaining how to light up live AI for free. Option A is GitHub Models,
which is sunset. Options for Groq and OpenRouter follow.

`GO-LIVE.md` — 140 lines, and **the most stale document in the repository**. It describes merging
"PR #1 on branch `game-changer`" and links to `https://github.com/DoubleX11/tradeos/pull/1`, an
organisation that is not the current remote (`https://github.com/abdv1ahh/tradeos.git`). It predates
the entire ten-phase rebuild.

`Makefile` — 77 lines, phony targets `demo`, `backfill-full`, `test`, `dev`, `web`, `site`, `lint`,
`fix`, `up`, `down`, `logs`. `demo` runs a fifteen-command sequence building a full demo dataset from
scratch over a few-week data window. `backfill-full` runs `backfill-13dg` and `backfill-form4` over
2024-07-01→2026-07-14 plus `resolve-entities`. `test` runs pytest in a throwaway container with
`tests/` and `tradeos/` bind-mounted, which is required because the image does not contain them.
`lint` and `fix` install ruff into a root-user throwaway container and run it over `tradeos tests`.

`pyproject.toml` — 45 lines, Ruff configuration only. No build system, no project metadata, no
dependency declarations. The package is not installable; it is run as `python -m tradeos.cli` and
`uvicorn tradeos.app:app` from the working directory.

`README.md` — 155 lines, the public-facing description. Accurate about philosophy, stale on two
numbers: it says "213 tests" and "app.py FastAPI, 99 routes". The real figures are 637 collected
tests and 127 routes.

`requirements.txt` — ten lines, pinned exactly: fastapi 0.139.2, starlette 1.3.1, uvicorn 0.35.0,
httpx 0.28.1, psycopg[binary] 3.2.9, defusedxml 0.7.1, argon2-cffi 23.1.0, pyotp 2.9.0, Pillow
12.3.0, pytest 9.0.3.

### `.github/`

`.github/workflows/ci.yml` — the only file. Two jobs on every push to any branch and on every pull
request. Job `test`: checkout with `fetch-depth: 0` (gitleaks needs history), set up Python 3.12
with pip cache, `pip install -r requirements.txt ruff`, run `ruff check tradeos tests`, run
`python -m pytest tests/ -q`, then `gitleaks/gitleaks-action@v2` over the full history. Job `web`:
checkout, set up Node 24 with npm cache keyed on `frontend/package-lock.json`, `npm ci`, `npm run
build`. **The marketing site under `site/` is not built by CI**, which is a gap — a syntax error in
`site/src/` would not be caught.

### `.gstack/`

A tooling scratch directory, gitignored. Three files: `browse-audit.jsonl` (622KB of headless-browser
audit records from a QA session on 2026-07-27), `browse-network.log` (150KB of network traces from the
same session), and `claude-available.json` (184 bytes recording that the `claude` CLI is available at
`~/.npm-global/bin/claude`). None of this is product code.

### `.pytest_cache/` and `.ruff_cache/`

Tool caches, gitignored. `.pytest_cache/` contains `.gitignore`, `CACHEDIR.TAG`, `README.md` and
`v/cache/lastfailed` plus `v/cache/nodeids`. The cached data is **stale**: it records 191 node ids
and two failures in `tests/test_previews.py`, a file that no longer exists. `.ruff_cache/` contains
`.gitignore`, `CACHEDIR.TAG` and a `0.16.0/` directory holding ten binary cache files named by hash.

### `.venv/`

A Python 3.13 virtualenv, 71MB, gitignored. Contains `bin/`, `include/python3.13/` and
`lib/python3.13/site-packages/` with the installed distributions listed in section 2. Not product
code; noted because it exists and because its Pillow version disagrees with `requirements.txt`.

### `.git/`

8.3MB of git internals. Not read.

### `content/`

One subdirectory, `content/library/`, containing one file, `entries.json`. This is the seed content
for the educational library: **twenty entries**, each with a slug, a kind (`concept` or
`investor_profile`), a title, markdown body, a list of sources with URLs and a `basis` field, a list
of linked source classes, and `review_status: draft`. The fourteen concepts are
`insider-cluster-buys`, `activist-13d-stakes`, `passive-13g-stakes`, `reading-13f-staleness`,
`short-interest-mechanics`, `why-convergence-beats-single-signals`, `base-rates-and-calibration`,
`survivorship-and-lookahead`, `position-sizing-basics`, `risk-management-basics`,
`reading-an-sec-filing`, `congressional-disclosure-limits`, `options-flow-basics` and
`market-structure-basics`. The six investor profiles are `profile-warren-buffett`,
`profile-peter-lynch`, `profile-carl-icahn`, `profile-michael-burry`, `profile-benjamin-graham` and
`profile-joel-greenblatt`. Every entry is still marked `draft`, meaning none has passed the founder
review gate described in `docs/review-queue.md`, yet `/api/library` serves them all with a note
saying they are "original drafts pending founder review".

### `deploy/`

One file, `deploy/Caddyfile`, ten lines. Described in section 2.

### `scripts/`

One file, `scripts/backup.sh`, an executable bash script. It is worth describing in full because it
is the single most operationally important file in the repository and it is not being run. It runs
`pg_dump -Fc` (custom format, compressed, restorable table-by-table) through
`docker compose exec -T db`, writes to `${BACKUP_DIR:-./backups}/rhumb-<UTC timestamp>.dump`,
**refuses to call the result a backup if it is under 100,000 bytes**, prunes files older than
`${KEEP_DAYS:-14}` matching only its own naming pattern, and with `--verify` restores the dump into a
scratch database, counts `insider_transactions`, drops the scratch database and fails if the count is
zero. Its header comment records measurements: the database is 5.2 GB of which `raw_filings` is
4.7 GB, a gzipped dump is about 2 GB, and fourteen days of retention needs roughly 30 GB. It also
records the reason the data matters: 664,923 insider transactions, 51,099 stake events and 24,982
institutional holdings built over hours of rate-limited SEC backfill that cannot be re-run quickly.
The cron line is written in the comments and, per `docs/state.md` and `docs/progress/phase_9.md`,
**nobody has installed it**.

### `shared/`

One file, `shared/tokens.css`, 71 lines. The measurements both front ends agree on: two font stacks
(`--mono`, `--sans`), a nine-step type scale from `--fs-xs: 11px` to `--fs-4xl: 44px`, an eight-step
4/8/12/16/24/32/48/64px spacing scale `--s1`…`--s8`, four radii, and five motion tokens (two easing
curves and three durations). It also carries one centralised accessibility rule: a
`prefers-reduced-motion: reduce` block that collapses animation and transition durations to 0.001ms
rather than setting `animation: none`, with a written reason — `none` can strand an element at frame
zero of an entrance animation and therefore make it invisible, whereas collapsing the duration runs
the animation to its final state instantly. Colour is deliberately excluded, with a paragraph
explaining why: the app is a dark instrument you sit in front of for an hour, the site is a chart you
read for ninety seconds, and each defines its own palette *after* importing this file so a later
addition here can never silently repaint a surface designed around a different one.

### `tradeos/` — the Python package

This is all backend code. Fifty-eight entries at the top level.

`tradeos/__init__.py` — empty, zero bytes. Marks the package.

`tradeos/app.py` — 3,115 lines, the FastAPI application and by a wide margin the largest file in
the repository. It declares roughly 25 Pydantic request models, the security middleware, the image
upload/storage helpers, and **127 routes**. `CLAUDE.md` says "the one big file" and instructs that
it be split by surface when a phase touches it rather than as a standalone refactor. Detailed in
section 6.

`tradeos/admin.py` — 233 lines. The admin control plane: moderation queue over `content_reports`,
user listing and search with LIKE wildcards escaped, tier changes limited to free/retail/pro (admin
is refused here — it requires a TOTP secret and is provisioned only via the CLI), ban/unban, and an
audit tail reader. Pure validation helpers (`validate_tier_change`, `can_ban`, `resolution_ok`) come
first so they are unit-testable offline. Deliberate safety choices: you cannot change your own tier
or ban yourself, and admins cannot be banned or retiered from the console.

`tradeos/alerts.py` — 218 lines. The reach-out layer. Pure decision functions
(`high_conviction_notifications`, `followed_symbol_notifications`, `actor_notifications`) turn
already-gathered facts into notification records each carrying a stable `dedup_key`, so the DB
driver inserts exactly-once via `ON CONFLICT (user_id, dedup_key) DO NOTHING`. Delivery is
tier-aware: a free user's alerts respect the same 48-hour delay as the feed, so alerts cannot be
used to exfiltrate fresh paid signals. Email is queued into `email_outbox` and marked sent only when
a real provider delivers.

`tradeos/apikeys.py` — 91 lines. Pro-tier API keys: generated with a prefix, stored only as a
sha256 hash, shown to the user exactly once, revocable, with a per-key `canary` seed. Every `/api/v1`
response carries `meta.trace = sha256(canary:day)` so a resold dataset is traceable to the leaking
key without ever polluting the data itself with a fabricated row.

`tradeos/assistant.py` — 395 lines. The AI market assistant. Pure intent classification
(`classify`), candidate ticker extraction (`candidate_symbols`), and a deterministic grounded answer
builder (`build_answer`) come first; then DB retrieval scoped to the requesting user and tier; then
a guarded orchestrator. It has two model paths: a **tool-using** path where the model is asked to
plan which of six read-only lookups to call and then answers from what came back, and a fallback
**rephrase** path. The numbers guard is deliberately relaxed on the tool path, with a written
reason: the model is quoting figures out of this system's own stores which it was just handed, so
the relevant risk is advice language rather than invented measurements.

`tradeos/assistant_tools.py` — 213 lines. Six read-only tools the assistant can call:
`search_events`, `search_claims`, `track_record`, `country_exposure`, `smart_money`,
`data_coverage`. This is a security boundary, not a convenience layer, and the module docstring
states three properties that hold by construction: read-only (no write tool and no generic
"run this query" escape hatch), always parameterised (the model picks a tool and fills clamped
blanks; it never composes a query), and no URL fetching (no tool takes a URL or reaches the
network, so an injected "fetch this address" has nothing to call). `call()` filters the argument
dict against the function's own signature before invoking it.

`tradeos/authn.py` — 407 lines. Authentication end to end. Detailed in section 8.

`tradeos/billing.py` — 182 lines. Plans, entitlements, Stripe Checkout, webhooks, test mode.
Detailed in section 11.

`tradeos/brief.py` — 278 lines. The Morning Brief composer. Assembles the smart-money digest, the
impact-ranked news ("what changed overnight"), an AI executive summary, the accountability section
(yesterday's Ledger outcomes) and the live claims currently on the hook, cached per (user, day) by
an inputs-hash in `daily_briefs`.

`tradeos/claims.py` — 427 lines. The impact engine. Detailed in sections 6 and 10.

`tradeos/cli.py` — 841 lines. The operations command line, `python -m tradeos.cli <command>`.
Detailed in section 9.

`tradeos/community.py` — 267 lines. The social graph: handle validation
(`^[a-z0-9_]{3,20}$` with reserved words blocked), public feed, follows between traders, reactions
(like/save), comments, report-and-auto-hide moderation at three distinct unresolved reports, and a
trader leaderboard ranked by honest win rate above a sample floor (`LEADERBOARD_MIN_CLOSED`) —
never by a raw return figure, which the module comment explains would invite fabrication and
pumping.

`tradeos/config.py` — 76 lines. Environment accessors that raise `ConfigError` rather than
defaulting a secret. `database_url()` refuses an unset `DATABASE_URL`; `sec_user_agent()` refuses a
User-Agent without an `@` in it, because the SEC's fair-access policy requires a contact address.
Also `short_interest_enabled()`, `reddit_configured()`, `reddit_client_id()`,
`reddit_client_secret()`, `youtube_configured()`, `tiingo_configured()`, `openfigi_configured()`
and `brand_name()`.

`tradeos/crypto.py` — 76 lines. CoinGecko market data with a 60-second in-process cache and honest
risk labels: `high_volatility` at |24h| ≥ 20%, `microcap` under $100M, `thin_volume`.

`tradeos/crypto_intel.py` — 216 lines. The interpreted crypto surface that replaced the price
mirror. Reads Binance public derivatives — funding rate, funding history, open interest, global
long/short account ratio — into falsifiable positioning readings, plus stablecoin supply as a
liquidity proxy. **Every reading carries an invalidation condition**, which the module docstring
argues is what separates analysis from a horoscope. Returns `None` rather than a manufactured
reading when inputs are too thin.

`tradeos/dashboard.py` — 231 lines. The dashboard composer. Its centrepiece is `_market_pulse`, a
transparent flow-and-positioning read: the score starts neutral at 50 and each real signal nudges
it, and every nudge that fires becomes a human-readable driver so the number is explainable rather
than a black box. The inputs are insider buy/sell breadth over the trailing 30 days, convergence
breadth by bucket, attention, news load and the nearest high-importance macro event. The module
comment is explicit that it measures flow and positioning rather than claiming to read a crowd mood
it cannot see.

`tradeos/db.py` — 41 lines. `connect()` and the ordered migration runner.

`tradeos/events.py` — 99 lines. The forward-calendar read/enrich layer. Macro events get a
deterministic educational read from a curated `MACRO_INTEL` table; company earnings get cross-plane
enrichment flagging whether the name also shows a smart-money signal or an attention spike.

`tradeos/exposure.py` — 130 lines. The surface that replaced the position tracker. Pure functions:
`concentration`, `claims_touching`, `geographic_reach`, `corridor_dependence`,
`upcoming_intersections`, `summarise`. The docstring makes the product argument explicitly: a broker
already shows what you own and what it is worth, better and with real prices; what no broker shows
is which live events reach you, through which holding, and by what mechanism.

`tradeos/flags.py` — 118 lines. Five DB-backed feature flags actually enforced on the request path:
`ai_assistant`, `ai_trade_analysis`, `registration`, `community_writes`, `crypto`. A three-second TTL
cache keeps it off the hot path. `set_flag` rejects unknown names so the console cannot create
phantom flags. `effective_provider(conn, flag)` returns `"template"` when a flag is off, which is
how the AI kill-switches force the deterministic path with no model call.

`tradeos/geography.py` — 189 lines. Places events by what a claim *affects* rather than who
published it. Three lookup tables — `REGIONS` (19 named regions to ISO code lists, with `global` and
`worldwide` deliberately mapping to the empty list), `CURRENCY_COUNTRIES` (20 currencies) and
`COMMODITY_COUNTRIES` (fourteen commodities to producer lists). `countries_for` returns every
country a claim touches; `countries_with_reason` labels each one `location` or `commodity`, which is
the distinction that fixed the personalisation bug; `commodities_in` normalises a claim's commodity
values to the table's vocabulary; `corridors` builds weighted trade corridors from the country
exposure rows; `coverage` states honestly how much of the world the map can speak about.

`tradeos/insights.py` — 356 lines. Advanced journal intelligence: a similar-trade finder using an
outcome-blind similarity over asset class, direction, strategy tokens (Jaccard), reward:risk band
and timeframe; a scenario simulator that is pure arithmetic with no probabilities; and an auto
journal report aggregating performance, recurring habits and — since Phase 6 — the behavioural
patterns read from world context. All three are object-scoped to the requesting user.

`tradeos/journal_context.py` — 363 lines. Freezes the Radar at the moment a trade is logged.
Detailed in sections 4 and 10.

`tradeos/ledger.py` — 378 lines. Outcome measurement and the self-scoring record. Detailed in
section 10.

`tradeos/library.py` — 42 lines. Loads `content/library/entries.json` into `library_entries`.

`tradeos/llm.py` — 293 lines. The single transport for every model call. Detailed in section 9.

`tradeos/mail.py` — 118 lines. The one outbound-email path. Refuses to send when unconfigured; the
`MAIL_DEV_ECHO=true` escape hatch writes the link to the server log and is treated by `preflight` as
a production **problem**, not a warning, because it is a real capability leak to anyone who can read
logs. Plain text only, on purpose — an HTML mail is a rendering surface and the two messages this
product sends are a sentence and a link. `send()` reports only whether delivery succeeded; the token
never returns through the API.

`tradeos/news.py` — 148 lines. Deterministic impact scoring (`intrinsic_impact` as a pure function
of category, smart-money overlap and whether the item is directly about the company or merely
mentions it), read-time ranking with a 36-hour half-life so recency tapers importance without
rewriting it, and the honest per-source status map.

`tradeos/oauth.py` — 250 lines. Sign in with Google. Built, config-gated, and — per its own
docstring, `sources.py`, `docs/state.md` and `docs/progress/phase_9.md` — **never once exercised
against Google**. Detailed in section 8.

`tradeos/onboarding.py` — 146 lines. First-run frame capture: country, base currency, starting
watchlist. Gates nothing; a skip costs the reader nothing but the personalised ordering, which the
Radar already says out loud. Two timestamps rather than a boolean (`onboarded_at`, `snoozed_until`)
because "skippable but gently persistent" is a behaviour a boolean cannot express.

`tradeos/portfolio.py` — 128 lines. Paper portfolios tracked against SPY from real `prices_eod` over
the actual holding window. A name that cannot be priced is reported `priced: False` and **excluded
from the averages**, never filled with a guess.

`tradeos/presentation.py` — 193 lines. Display-only transforms: `smart_money_score` maps the
unbounded raw convergence score to 0–100 pinned to the real calibrated bucket edges (raw 3 → 50, raw
6 → 75, asymptotic toward 100); `cluster_story` builds the plain-language "who is piling in" from a
cluster's contributions and a voice→name map; `score_card_svg` renders a 1200×630 shareable card as
a pure string with no image dependency and a non-removable honesty footer, with every value
XML-escaped.

`tradeos/public_site.py` — 164 lines. The only unauthenticated surface. Its docstring states two
rules the rest of the API may relax: no user-scoped data ever (nothing here accepts a session, reads
`users`, `trades`, `watchlists` or `user_profiles`, or takes an identifier that could address a
person), and nothing may be cherry-picked to flatter (the walkthrough rotates deterministically by
`today.toordinal() % pool` over the real store, and the settled example alongside it is drawn
newest-first, not best-first).

`tradeos/radar.py` — 431 lines. Saved filter sets, threading and subscribable alerts, plus the SSRF
defence. Detailed in sections 6, 11 and 18.

`tradeos/ratelimit.py` — 102 lines. Sliding-window limits on the public and model paths. Its
docstring is unusually candid: "This is an in-process limiter, and that is a real limitation, stated
rather than buried. It is a dict in one worker. It resets on restart, and with more than one API
replica each replica gets its own allowance."

`tradeos/relevance.py` — 335 lines. Personal ranking, the reader frame, and the ten-country exposure
reference data. No model. Detailed in sections 10 and 11.

`tradeos/scheduler.py` — 284 lines. The background worker. Detailed in section 9.

`tradeos/search.py` — 61 lines. Unified search across issuers, institutions, insiders, the library
and public traders. Read-only, public handles only (never emails or user ids), LIKE wildcards escaped
by `clean_query`.

`tradeos/sentiment.py` — 263 lines. Attention and sentiment scoring. `attention_score` is a velocity
against the symbol's own baseline; `blend_sentiment` is mention-weighted and returns `None` when no
connected source measures mood; `manipulation_flag` labels `single_source` and `bot_heavy` rather
than hiding them; `score_symbol` takes at most one *current* observation per source (via
`DISTINCT ON`) after a bug where summing repeated snapshots turned 312 daily Wikipedia views into
"7,547 mentions"; `_group` groups by company rather than ticker so Alphabet does not appear twice
with its attention split.

`tradeos/smartmoney_claims.py` — 158 lines. Converts historical convergence clusters into scoreable
claims so the signal plane's long history is measured by the same Ledger. Its docstring confronts the
backdating question head-on: these claims carry the cluster's `as_of`, not the import moment, and the
justification is that `signal_clusters` was computed under strict point-in-time discipline so the
system really did make that call then, and the outcomes were measured against prices strictly after
entry.

`tradeos/social.py` — 61 lines. The attention read/enrich layer: connects an attention spike to a
likely news catalyst, deterministically on the board (so the endpoint stays instant) and
model-capable on the per-symbol deep dive.

`tradeos/sources.py` — 273 lines. The source registry of record. Sixteen catalog entries with a key,
label, kind, what it powers, its state, the env variables it needs, a signup URL, an explanatory
note, the `feed_health` rows it writes and the scheduler jobs that drive it. `health(conn,
detailed)` joins the catalog to reality, and `detailed` (admins only) is the only way to see raw
error text, because that text is `str(exc)` of an arbitrary ingestion failure and an httpx error
embeds the full request URL including its query string.

`tradeos/spine.py` — 440 lines. Normalise, cluster, score. Detailed in section 10.

`tradeos/trades.py` — 281 lines. The trade journal's pure math and analysis. `reward_risk` returns
`None` rather than a misleading ratio when a leg is on the wrong side; `realized_pnl_pct` returns a
**fraction** (0.1 means +10%), which is the unit convention that caused a real display bug;
`analyze_trade` produces observations, risk flags and context; `summarize_performance` reports counts
below a ten-closed-trade floor and only then a win rate, expectancy and per-strategy breakdown
(itself floored at eight).

`tradeos/watchlist_accounts.py` — 180 lines. The consequential-accounts influence list. Its `SEED`
contains **24 accounts**: five `rss` (US Federal Reserve at influence 1.0, European Central Bank
0.95, Bank of England 0.85, Bank of Japan 0.85, US SEC 0.8), three `official` (OPEC 0.9, IMF 0.75,
World Trade Organization 0.7), and sixteen `bluesky` — Reuters 0.85, Associated Press 0.85, Peterson
Institute 0.7, The New York Times 0.65, The Washington Post 0.65, Al Jazeera English 0.65, Council on
Foreign Relations 0.6, FRANCE 24 0.55, Chatham House 0.55, Brookings Institution 0.55, Politico 0.55,
Axios 0.5, MarketWatch 0.5, Business Insider 0.45, Semafor 0.45, ProPublica 0.45. Every Bluesky
handle was resolved against the live `app.bsky.actor.getProfile` on 2026-07-26 before seeding; a
handle that could not be verified was left out rather than seeded hopefully. `influence` is
documented everywhere as a **stated editorial weight, not a measurement of reach**.

#### `tradeos/backtest/`

`__init__.py` (8 lines, a docstring stating that look-ahead is structurally impossible),
`engine.py` (113 lines of pure math — the `Series` dataclass, `excess_return`, `entry_day_after`,
`group_episodes` with a 14-day gap rule, `wilson_interval`, `bucket_calibration`, and the constants
`HORIZONS = (30, 90, 180)`, `EPISODE_GAP_DAYS = 14`, `MIN_EPISODES = 30`), and `run.py` (210 lines
of DB drivers — `load_series`, `symbols_for_clusters`, `symbols_for_clusters_missing`,
`symbols_for_clusters_missing_history`, `run_backtest`, `compute_calibration`).

#### `tradeos/explain/`

`__init__.py` (7 lines), `base.py` (151 lines — the cache→provider→guards→template orchestration and
`extract_tickers`), `gemini.py` (139 lines — five prompt builders: `generate`,
`generate_trade_prose`, `generate_journal_report`, `answer_question`, `extract_tickers`; the module
keeps the name its callers import even though the transport is now provider-agnostic),
`guards.py` (115 lines — `directive_guard`, `numbers_guard`, `allowed_numbers`,
`base_rate_integrity_guard`), and `template.py` (85 lines — the deterministic always-available
prose).

#### `tradeos/ingestion/`

Twenty-one files. `__init__.py` is empty. `attention_wiki.py` (130 lines) resolves a company to its
canonical Wikipedia article and reads daily pageviews from the Wikimedia REST API, caching resolved
titles and honest misses in `wiki_titles`. `calendar_nasdaq.py` (185 lines) reads Nasdaq's public
JSON earnings and economic calendars, requiring a browser User-Agent because Nasdaq fingerprints
non-browser clients. `coingecko.py` (44 lines) makes exactly two fixed queries and is never an open
proxy. `common.py` (39 lines) holds `reject()` and `update_health()`, the loud-degradation helpers.
`derivatives.py` (145 lines) reads four Binance public endpoints with a 300-second cache;
`funding_trend` and `annualised` are pure. `edgar_client.py` (75 lines) is the throttled,
host-allowlisted, sha256-checksumming SEC client. `finra.py` (121 lines) ingests consolidated short
interest. `form13f.py` (213 lines) parses 13F-HR information tables, normalising `value` to whole
USD keyed on the SEC's 2023-01-03 rule change and aggregating per (cusip, share_type) within a
filing. `form4.py` (217 lines) parses the daily master index and ownershipDocument XML, with
`validate_transaction` enforcing `MAX_PRICE` and `MAX_SHARES` sanity bounds and sending failures to
`ingest_rejects`. `gdelt.py` (202 lines) is the global news backbone with a six-second minimum
interval and a six-hour persistent backoff after any 429. `news_adapter.py` (103 lines) projects
`news_items` into `events`, one-directionally. `news_rss.py` (282 lines) fetches eleven allowlisted
feeds and tags tickers only on unambiguous evidence. `news_sec.py` (213 lines) ingests 8-K material
events, reading the machine-structured SGML header for facts and the standardised Item codes for
"what happened" from a fixed table. `prices.py` (115 lines) is the Tiingo EOD client, storing the
split/dividend-adjusted series as `source = 'tiingo:adjusted'`. `runner.py` (116 lines) orchestrates
one day of Form 4 ingestion. `schedule13.py` (189 lines) parses 13D/G from the SGML header only,
storing `percent_owned` as NULL rather than scraping an ambiguous HTML cover page, and normalising
the legacy `SC 13D` spelling to the modern `SCHEDULE 13D`. `sentiment_hn.py` (99 lines) counts
exact-phrase Hacker News mentions via Algolia with `advancedSyntax` enabled. `sgml.py` (98 lines) is
the shared EDGAR submission-header parser. `social_bluesky.py` (202 lines) reads the curated account
list keylessly. `social_reddit.py` (138 lines) is a client-credentials OAuth adapter that is a
complete no-op until credentials exist.

#### `tradeos/intelligence/`

`__init__.py` (12 lines describing the two-plane split), `analyst.py` (282 lines — the news "why it
matters" with a third guard, `citation_guard`, that blocks the model smuggling in a different
company via a cashtag or exchange-qualified mention), and `vision.py` (154 lines — chart reads with
**field-level** guarding, so one tripped sentence drops that field rather than discarding four good
ones).

#### `tradeos/migrations/`

Thirty-three ordered `.sql` files, `001_init.sql` through `033_drop_congress_flag.sql`. Every one
inserts its own `schema_migrations` row; the runner does not. Detailed in section 7.

#### `tradeos/resolution/`

`__init__.py` (4 lines), `entities.py` (42 lines — `get_or_create_entity` keyed on CIK and
`backfill_insider_entities`), `openfigi.py` (133 lines — the CUSIP→ticker client, unauthenticated at
a low rate limit, refusing to guess), and `tickers.py` (50 lines — `sync_tickers` ingesting the SEC's
own `company_tickers.json` at confidence 1.0).

#### `tradeos/signals/`

`__init__.py` (5 lines), `convergence.py` (284 lines — the hash-locked scorer), and `definitions.py`
(134 lines — the registry and the hash-guarded compute driver).

#### `tradeos/static/` and `tradeos/site_static/`

Both exist as directories and both are **empty** and gitignored. In production the Dockerfile copies
the built app bundle into `tradeos/static`; under `make dev` the compose override bind-mounts
`frontend/dist` and `site/dist` over them.

### `frontend/`

`index.html` (16 lines — the pre-boot title "Rhumb — world events, and what they mean for you" and
meta description, with a comment noting that this is what a shared link shows because `App.jsx` sets
`document.title` only after first paint), `package.json`, `package-lock.json`, `vite.config.js`
(base `/`, dev proxy `/api` → `localhost:8000`, outDir `dist`), `node_modules/` (176MB, 83 top-level
packages installed for four declared dependencies plus two dev dependencies — the transitive weight
is almost entirely `react-globe.gl`'s d3 and three.js graph), `dist/` (2.5MB of built output:
`index.html`, `assets/index-D-tI4mZV.js` at 388,717 bytes, `assets/index-Cs78syNh.css` at 108,636
bytes, and `assets/globe3d-DzD--yO8.js` at 2,075,064 bytes, built 2026-07-26), and `src/` with 37
files.

The `frontend/src/` files, all of them: `account.jsx` (169 lines — email verification and password
reset screens plus `ForgotPassword`), `admin.jsx` (250 lines — the five-tab admin console),
`alerts.jsx` (127 lines — notifications and alert preferences), `api.js` (166 lines — every network
call), `App.jsx` (381 lines — the shell, nav, command palette and the surface switch),
`assistant.jsx` (115 lines — the chat surface), `brand.js` (13 lines — `export const BRAND =
"Rhumb"` and a long comment about why it exists), `brief.jsx` (219 lines — the Morning Brief),
`calendar.jsx` (221 lines — month/week/day calendar views), `community.jsx` (354 lines — feed,
leaderboard, profile editor, trader pages), `components.jsx` (377 lines — shared display
components), `coverage.jsx` (81 lines — the source-comparison tab inside News), `crypto.jsx` (220
lines — positioning, sparklines, mini-boards), `dashboard.jsx` (351 lines — market pulse and five
sections), `discover.jsx` (47 lines — search results), `events.jsx` (101 lines — the flat event
list), `exposure.jsx` (200 lines — five exposure panels), `format.js` (32 lines — `pct`, `cls`,
`money`, `ago`), `globe.jsx` (265 lines — WebGL detection, flat map, country panel), `globe3d.jsx`
(123 lines — the lazy 3D globe), `icons.jsx` (42 lines — inline SVG icons), `integrations.jsx` (144
lines — the source status page), `journal.jsx` (723 lines — the largest frontend file, with capture
zone, trade form, coach strip, analysis, similar trades, world context, chart analysis, performance
and simulator), `ledger.jsx` (217 lines — headline, misses, breakdowns, calibration), `main.jsx` (10
lines — the React root), `news.jsx` (219 lines — hero, pulse, category filters, dedup grouping),
`onboarding.jsx` (105 lines — the first-run card), `portfolios.jsx` (209 lines — health, allocation,
track record, positions), `pricing.jsx` (124 lines — plans, referral card, API keys), `radar.jsx`
(240 lines — the flagship claim feed), `radarfilters.jsx` (220 lines — saved filters and thread
history), `shell.jsx` (171 lines — routing, error boundary, load/empty states, source gate),
`smartmoney.jsx` (397 lines — the convergence feed and issuer detail), `social.jsx` (211 lines — the
attention board), `styles.css` (1,759 lines), `views.jsx` (493 lines — asset, screener, watchlist,
auth panel, library, profile), and `world-110m.geo.json` (vendored Natural Earth 110m country
geometry, public domain, stripped to `iso` + `name` + coordinates and rounded to two decimal places,
reducing 488KB to 163KB; it reports as zero lines because it is one long line).

### `site/`

`index.html` (33 lines — canonical URL `https://rhumb.app/`, OpenGraph and Twitter card metadata,
an inline `html { background: #05090c }` rule so the first frame is never a white flash, and a
substantial `<noscript>` block that explains the product in prose and links to `/api/ledger` as
JSON), `package.json`, `package-lock.json`, `README.md` (a genuinely excellent 80-line design
rationale), `vite.config.js` (base `/site/`, dev port 5174, a manual-chunks rule splitting vendor
from app because "the site is read top-to-bottom in one sitting"), `node_modules/` (44MB),
`dist/` (716KB — `index.html`, `assets/index-ys1lS28X.js` at 28,749 bytes, `assets/vendor-C5x2k6wl.js`
at 141,671 bytes, `assets/index-Dtl_qZfv.css` at 14,392 bytes, `assets/vendor-B7lHLIuf.css` at 6,863
bytes, and 30 font files across four families and six subsets, built 2026-07-27), and `src/` with
ten files.

`site/src/api.js` (17 lines — four public GET-only calls, all resolving to `null` on failure rather
than throwing, with `credentials: "omit"`), `App.jsx` (106 lines — the page, nav, five bands,
footer, and JSON-LD structured data generated from the same `FAQS` array the accordion renders so
the markup cannot drift from the visible answer), `bearing.jsx` (71 lines — a live compass bearing
in the nav sweeping N 000° → NNE 060°, the one effect that cannot be pure CSS because text content
is not animatable from a scroll timeline), `graticule.jsx` (54 lines — the deep hero layer, meridians
fanned from a vanishing point above the frame so it reads as a projection rather than graph paper),
`hooks.js` (62 lines — `useLoad` with three explicit states, `useReveal` over IntersectionObserver,
`useScrollDriver`, `useProgress`), `main.jsx` (19 lines — the React root plus four font imports),
`rose.jsx` (81 lines — the signature 32-point portolan wind rose with line weight varying by wind
order), `scroll.js` (104 lines — one listener, one rAF, transforms only, with native
`animation-timeline` detection), `sections.jsx` (536 lines — `Hero`, `Walkthrough`, `Ledger`,
`Personalisation`, `FAQS`, `Close`, `Faq`), `styles.css` (492 lines), and `worldmap.jsx` (84 lines —
an SVG equirectangular plate with ten marked stations rather than a spinning globe, argued as both
lighter and more honest because exactly ten countries have hand-checked exposure figures).

### `tests/`

`__init__.py`, `conftest.py`, a `fixtures/` directory and 47 `test_*.py` files. Detailed in
section 15.

### `docs/`

Seventeen top-level markdown files plus three subdirectories. `audit.md` (324 lines — the Phase 0
audit), `bugs.md` (316 lines — the defect catalogue, B-01 through B-23), `dead_code.md` (142 lines),
`decision-log.md` (58 lines — a table of 51 numbered decisions with reasoning and the strongest
counterargument for each), `demo-script.md` (61 lines), `deploy.md` (201 lines),
`plan.md` (278 lines — where the brief was right, where it needed revision, the language-model
decision, the rebrand, and the ten-phase plan with branch names), `review-queue.md` (43 lines — the
founder review gate for library content), `security-audit.md` (76 lines), `staff-trading-policy.md`
(32 lines), `state.md` (294 lines — the resume document), `tradeoss_veryimportant_prompt.md` (478
lines — the product brief and source of truth for scope), and a `.DS_Store`.
`docs/progress/` holds `cross_check.md` (578 lines, the single most valuable document in the
repository), `phase_0.md`, `phase_1.md`, `phase_2.md`, `phase_3_4.md`, `phase_4_remainder.md`,
`phase_6.md`, `phase_7.md`, `phase_8.md` and `phase_9.md` — note there is **no `phase_5.md`**, the
globe phase has no progress report. `docs/runbooks/` holds `feed-quarantine.md`, `keys.md` and
`leaked-secret.md`. `docs/threat-models/` holds twenty files: `admin.md`, `alerts.md`,
`assistant.md`, `auth.md`, `backtest.md`, `billing.md`, `community.md`, `convergence.md`,
`crypto.md`, `explanation.md`, `form13f.md`, `form4.md`, `insights.md`, `portfolios.md`,
`public-surface.md`, `schedule13.md`, `screenshot.md`, `search.md`, `sentiment.md`,
`shortinterest.md` and `trades.md`.

---

## 4. Every page and route in the application

The app is a single-page React application. `frontend/src/shell.jsx` gives it real URLs over the
History API, and `tradeos/app.py` serves it through a custom `_SpaFiles` StaticFiles subclass that
catches Starlette's 404 `HTTPException` and returns `index.html` instead — but only for a plain miss
on a path that neither starts with `api/` nor ends in something with a file extension, so a bad
method or a genuinely missing asset still 404s rather than silently returning HTML.

**`/`** is not a page. It is a decision. If the request carries a `tos_session` cookie the server
returns the app's `index.html`; otherwise it issues a 307 redirect to `/site/`. The test is cookie
*presence*, not validity, and the comment explains why: deciding a redirect does not need a database
round trip, and the only case it gets wrong — an expired cookie — lands on the app, which asks the
reader to sign in, which is the right destination anyway. This route is registered conditionally,
only when both `tradeos/site_static/index.html` and `tradeos/static/index.html` exist. If the app
bundle is missing entirely, a fallback `/` returns a small HTML page saying the dashboard bundle is
not built.

**`/site/`** is the marketing site, a completely separate Vite bundle mounted before the app's
catch-all. It renders five bands in order. **Hero** pulls `/api/public/live?limit=5` and shows the
freshest event-derived interpretations, each with its mechanism, affected assets and confidence,
behind the wind rose and graticule. **Walkthrough** pulls `/api/public/walkthrough` and walks one
real interpretation end to end, rotating deterministically by day. **Ledger** pulls `/api/ledger`
and — since the accuracy-honesty pass — separates the two planes so they cannot be confused: the
impact engine's block says plainly that N interpretations are open, none has resolved and there is
nothing to show yet, while the signal plane's block publishes its full record including expectancy
and the confidence interval. **Personalisation** pulls `/api/public/frame?country=XX` and lets a
visitor click one of ten marked countries on an SVG plate to see the same day re-ranked. **FAQ**
renders seven questions from the `FAQS` array. **Close** is the call to action. Nav links go to
`#how`, `#ledger`, `#you`, `#faq`; "Start free" goes to `/auth`; the footer's "Open the app" goes to
`/radar` rather than `/` specifically because `/` would loop a signed-out visitor straight back. It
is finished and polished.

Inside the app, `frontend/src/App.jsx` declares `ROUTES` as the union of the twenty nav labels plus
`auth`, `pricing`, `notifications`, `search`, `asset`, `profile`, `library-entry`, `admin`,
`trader`, `verify` and `reset`. An unrecognised path falls back to **`/radar`**.

**`/radar`** — the flagship and the default landing surface. Renders `frontend/src/radar.jsx`, which
calls `fetchClaims({hours, limit})` → `GET /api/claims` and `fetchCountries()` →
`GET /api/countries`. Each claim card leads with the mechanism rather than the headline, shows the
affected assets with direction chips, the horizon, the confidence as a percentage, a "why shown"
sentence explaining its rank, any contradicting claims, and — where a cluster has been re-read — a
`ThreadHistory` panel showing the earlier readings and a plain-English diff of what changed. A
`FramePicker` lets the reader set their country inline, which `PUT /api/profile/frame` persists.
`SavedFilters` from `radarfilters.jsx` sits alongside, backed by four routes under
`/api/radar/filters`. **Finished.**

**`/globe`** ("The World") — `frontend/src/globe.jsx` calls `fetchGlobe()` → `GET /api/globe`. It
performs a real WebGL capability probe by creating a canvas and requesting a context; on success it
lazy-loads `globe3d.jsx`, on failure it renders `FlatMap`, an SVG equirectangular projection.
Clicking a country — including one with no events, which was the fix that made "is this country
quiet?" answerable — opens `CountryPanel` showing that country's exposure row and the claims placed
there, with a button to adopt it as your frame. **Finished, with a stated caveat**: verified on
desktop WebGL only, never on a real low-power mobile device.

**`/ledger`** — `frontend/src/ledger.jsx` calls `fetchLedger()` → `GET /api/ledger`. Four
components: `Headline` (the overall hit rate with its z-score, expectancy with its 95% interval and
significance flag, and the sample needed to detect a 1% edge), `Misses` (the recent misses, first on
the page by design), `Breakdown` (by category, horizon, source and origin, each flagged
`sufficient` or not), and `Calibration` (stated confidence versus observed rate, bucketed). This is
the moral centre of the product. **Finished.**

**`/dashboard`** — `frontend/src/dashboard.jsx` calls `fetchDashboard()` → `GET /api/dashboard`. A
`MarketPulse` tile with its drivers always shown, then five sections: Opportunities, What Matters,
Smart Money, Live Radar and Upcoming Radar. **Finished.**

**`/brief`** (Morning Brief) — `frontend/src/brief.jsx` calls `fetchBrief()` → `GET /api/brief` and
`fetchJobs()` → `GET /api/jobs`. Opens with `HeldToAccount` (yesterday's Ledger outcomes) before
telling you anything new, then the executive summary, what changed overnight, the smart-money
digest, your names, what is coming, and `OnTheHook` (the claims currently live). **Finished.**

**`/news`** — `frontend/src/news.jsx` calls `fetchNews({symbol, category, hours, limit})` →
`GET /api/news`. Two tabs: the impact-ranked feed with a hero story, category filters and same-ticker
dedup grouping showing "+N related"; and a Coverage tab rendering `coverage.jsx`, which calls
`fetchNewsCoverage(hours)` → `GET /api/news/coverage` and shows how differently outlets in different
countries frame the same event, plus where coverage is unusually thin. **Finished.**

**`/events`** (Calendar) — `frontend/src/calendar.jsx` calls `fetchEvents(days)` → `GET /api/events`
and offers month, week and day views with an importance filter. This replaced what bug B-11 called
"a ~10,000-pixel flat list". **Finished.** Note that `frontend/src/events.jsx` still exists and
exports `EventsView`, the old flat list — it is imported by `App.jsx` but the `events` route renders
`CalendarView` instead, so `EventsView` is **unreachable dead code** (see section 17).

**`/home`** (Smart Money) — `frontend/src/smartmoney.jsx` calls `fetchHome(minConfidence)` →
`GET /api/home` and `fetchLeaderboards()` → `GET /api/leaderboards`. A plain-language feed of
convergences with the Smart Money Score, the story of who is piling in, backtested rate labels and
freshness. Clicking through opens `IssuerDetail`, which shows the AI "why it matters" from
`GET /api/clusters/{id}/explanation`, a price sparkline from `GET /api/asset/{symbol}`, this
issuer's own backtested stats, and the raw filings behind one expand. **Finished.**

**`/trending`** (Social) — `frontend/src/social.jsx` calls `fetchTrending(hours)` →
`GET /api/trending`. The attention board with honest source status, manipulation badges, a
cross-plane smart-money flag, and a `Voices` strip naming the networks the product reads for
consequential accounts. **Finished, but thin by dependency**: with Reddit unkeyed no connected
source measures mood, so most rows read "attention only" (bug B-13).

**`/crypto`** — `frontend/src/crypto.jsx` calls `fetchCryptoStructure()` →
`GET /api/crypto/structure`, `fetchCryptoMarkets(limit)` and `fetchCryptoTrending()`. The
`Positioning` tab is the interpreted surface (funding, open interest, crowding, liquidity, each with
an invalidation condition); the market table and trending strip remain. **Finished.**

**`/journal`** — `frontend/src/journal.jsx`, 723 lines and the most feature-dense surface. It calls
fourteen distinct endpoints. A `CaptureZone` accepts a dropped or pasted screenshot and calls
`extractTickers(file)` → `POST /api/extract-tickers` to prefill the form, or
`analyzeChartImage(file)` → `POST /api/analyze-chart`. `TradeForm` creates and updates trades.
`CoachStrip` reads `fetchJournalReport()`. Each trade detail offers `AnalysisPanel`
(`GET /api/trades/{id}/analysis`), `SimilarTrades` (`GET /api/trades/{id}/similar`), `WorldContext`
(`GET /api/trades/{id}/context`) and `ChartAnalysisPanel` (`GET /api/trades/{id}/chart-analysis`).
There are `PerformancePanel` and `SimulatorPanel` tabs. **Finished.**

**`/exposure`** — `frontend/src/exposure.jsx` calls `fetchExposure()` → `GET /api/exposure`. Five
panels: Summary, TouchingClaims, Reach, Corridors, Concentration. **Finished, and tier-gated** —
free accounts get a `locked: true` response that says in words what the surface would show.

**`/watchlist`** — `WatchlistView` in `frontend/src/views.jsx` calls `fetchWatchlist()` →
`GET /api/watchlist`, plus add/remove. Each name gets a scorecard with smart-money conviction, public
attention, the latest impactful news, the next earnings date and a transparent conviction blend.
Also hosts `ScreenshotImport` and `WatchChartAnalyzer`. **Finished.**

**`/community`** — `frontend/src/community.jsx` calls `fetchCommunityFeed(scope, beforeId)`,
`fetchTraderLeaderboard()`, `fetchProfile(handle)` and the reaction/comment/follow endpoints. Public
and Following feeds, a win-rate leaderboard that shows nobody at all below the sample floor, and a
profile editor. Individual traders are addressable at **`/trader?handle=x`**. **Finished** — it was
rebuilt in the cross-check pass after its only entry point had been deleted as dead code.

**`/alerts`** — `frontend/src/alerts.jsx` calls `fetchAlertPrefs()`, `saveAlertPrefs(prefs)` and
`fetchFollows()`/`removeFollow(id)`. **Finished.** **`/notifications`** renders `NotificationsView`
from the same file against `GET /api/notifications` and `POST /api/notifications/read`.

**`/assistant`** — `frontend/src/assistant.jsx` calls `askAssistant(message)` →
`POST /api/assistant`. A chat transcript with citations. **Finished.**

**`/screener`** — `Screener` in `views.jsx` calls `fetchScreener(minC, sourceClass)`. A filter over
`/api/clusters`. **Finished but minimal.**

**`/library`** and **`/library-entry?slug=…`** — `LibraryView` and `LibraryEntry` in `views.jsx`.
**Finished as a reader; the content is all `draft`.**

**`/integrations`** — `frontend/src/integrations.jsx` calls `fetchIntegrations()` →
`GET /api/integrations`. Every source with its state, what it powers, last success, and the free-key
signup path. **Finished.**

**`/methodology`** — `Methodology` in `components.jsx`, fed by `/api/calibration` and
`/api/definitions` fetched once in `App.jsx`. **Finished.**

**`/asset?symbol=X`** — `AssetView` in `views.jsx` calls `fetchAsset`, `fetchActivity` and
`fetchExplanation`. **`/profile?kind=…&id=…`** — `ProfileView` calls `fetchInstitution` or
`fetchInsider`. **`/search?q=…`** — `SearchView` in `discover.jsx` calls `fetchSearch(q)`. All
**finished**.

**`/auth`** — `AuthPanel` in `views.jsx`. Login, register with an invite or referral code, TOTP
field, a Google button, and `ForgotPassword`. **Finished except the Google button, which has never
been exercised against Google.** **`/verify`** and **`/reset`** render `VerifyView` and `ResetView`
from `account.jsx`, reading the token from the URL **fragment** (never the query string, so it
cannot reach an access log) and listening for `hashchange` so a second link clicked while the page
is open is honoured. **Finished, but non-functional in practice because SMTP is unconfigured.**

**`/pricing`** — `frontend/src/pricing.jsx` calls `fetchPlans()`, `checkout(plan)`,
`testActivate(plan)`, `cancelSub()`, `fetchReferral()` and the API-key endpoints. **Finished, in
test mode.**

**`/admin`** — `frontend/src/admin.jsx`, five tabs (Overview, Moderation, Users, Flags, Audit)
across eight admin endpoints. Only rendered when `user.tier === "admin"`. **Finished.**

**`/s/{symbol}`** — a server-rendered HTML link-preview page with OpenGraph tags pointing at
`/api/card/{symbol}.svg`. Not part of the SPA. **Finished.**

**`/portfolios` — the one broken route.** `App.jsx` imports `PortfoliosView` and contains a
`view === "portfolios"` branch, but `"portfolios"` appears in neither `NAV_LABELS` nor `ROUTES`.
Navigating to `/portfolios` therefore falls through to `/radar`, nothing calls `go("portfolios")`,
and the branch is unreachable. `frontend/src/portfolios.jsx` — 209 lines with health score,
allocation, track record and a positions table — is dead in the UI while its six backend routes
remain live and its `portfolios`/`portfolio_positions` tables still feed the Exposure surface's
holdings query.

---

## 5. Every reusable component

There is no component library and no props-typing system — no TypeScript, no PropTypes. Props are
plain destructured objects and their shapes are only discoverable by reading the call sites, which
is what I did.

The genuinely shared primitives live in **`frontend/src/shell.jsx`**. `useRoute()` takes no
arguments and returns `{path, query, go, replace}`; it is used only by `App.jsx`. `ErrorBoundary` is
the sole class component in the codebase, taking `surface` (a string used in the console message)
and `children`; `App.jsx` wraps the entire surface switch in one, **keyed by `view`**, so a throw
inside a surface shows a contained failure panel with the chrome intact and switching surfaces
resets it. `LoadError` takes `what` (a noun phrase completing "Couldn't load …") and an optional
`onRetry` callback; it is used by `brief.jsx`, `dashboard.jsx`, `events.jsx`, `news.jsx` and
`social.jsx`. `EmptyState` takes `title`, `children` and an optional `action` node, and is used
across most surfaces. `SourceGate` takes `gate` (the object `sources.gate(key)` returns from the
server, carrying `key`, `label`, `state`, `powers`, `note`, `signup_url` and `env`) and an optional
`compact` boolean; it renders nothing at all when the source is connected, an inline chip when
compact, and a full explanatory card otherwise, with numbered steps and a link to where the free key
is obtained. It is used by `social.jsx` and `integrations.jsx`.

**`frontend/src/icons.jsx`** exports one component, `Icon`, taking `name`, `size` (default 18) and
`style`. It is imported by `App.jsx`, `shell.jsx` and most surfaces. The icon set covers `radar`,
`layers`, `target`, `grid`, `sparkles`, `news`, `calendar`, `signal`, `trending`, `crypto`,
`journal`, `briefcase`, `star`, `users`, `bell`, `compass`, `filter`, `book`, `plug`, `shield`,
`search`, `menu`, `logout`, `chevron` and `alert`.

**`frontend/src/format.js`** exports four pure display formatters and exists specifically because
duplication caused a real bug. `pct(v)` converts a **fraction** to a signed percentage (0.1 →
"+10.0%"); `cls(v)` returns the CSS class colouring a signed number, with zero being neither green
nor red; `money(v)` renders a locale-grouped price at most 2dp and never scientific; `ago(iso,
empty)` renders coarse relative time with a caller-chosen empty string because a feed item says
nothing while a source-health row says "never". They are used by `journal.jsx`, `portfolios.jsx` and
`community.jsx`. The file's comment records why: `pct` existed as near-identical copies in three
surfaces and the fourth copy, in the community feed, omitted the ×100, so a +10% trade was published
to other people's screens as "+0.1%".

**`frontend/src/components.jsx`** is the older shared-component file and it is half dead. Nine
exports. `Freshness({iso, quarterly})` renders a relative-age chip and is used by `smartmoney.jsx`
and `views.jsx`. `Bucket({bucket})` renders a low/medium/high pill and is used only by
`portfolios.jsx` — which is itself unreachable, so `Bucket` is transitively dead.
`Backtested({cal})` renders a backtested-rate label or "insufficient sample" and is used by
`smartmoney.jsx` and `views.jsx`. `Disclaimer()` takes no props and is used five times in
`views.jsx`. `Methodology({calibration, definitions, onBack})` is used by `App.jsx`. The remaining
four — **`Classes({classes})`, `StatusStrip({feeds})`, `ClusterTable({clusters, onSelect, pulseKey,
calibration, horizon})` and `ClusterDetail({detail, onBack, calibration, horizon, explanation,
onOpenLibrary})`** — have **no importer anywhere in the tree**. They are superseded by the
equivalents inside `smartmoney.jsx` and are dead code not recorded in `docs/dead_code.md`.

**`frontend/src/radarfilters.jsx`** exports two components consumed by `radar.jsx`.
`SavedFilters({claims, activeSpec, onApply})` manages the whole saved-filter lifecycle — listing,
editing five dimensions through `SpecEditor`, previewing the match count live while editing, saving,
deleting, and toggling a subscription with a channel and throttle. `ThreadHistory({claim})` renders
the earlier readings of a developing story with the plain-English diff. Its two private helpers are
`Chip({on, onClick, children})` and `SpecEditor({spec, setSpec, categories, geos, sources})`.

**`frontend/src/coverage.jsx`** exports `CoverageView()`, taking no props, imported by `news.jsx`
and rendered when the News surface's tab is `coverage`.

**`frontend/src/globe3d.jsx`** exports a **default** component `Globe3D({countries, corridors,
centroids, selected, onSelect})`, imported *only* through `React.lazy` in `globe.jsx`. Importing it
statically anywhere would pull two megabytes into the main bundle.

Every other `.jsx` file exports one or two page-level views plus private helpers scoped to that
file. Those private helpers are not reusable components and are not shared; naming them all would be
accurate but misleading about their nature, so they are named instead in the per-file inventory in
section 3 and the page inventory in section 4. On the marketing site, `Rose({cx, cy, r})`,
`Graticule()`, `Bearing()` and `WorldMap({countries, selected, onSelect})` are the reusable pieces;
`Section({id, children, className})`, `Tag({a})` and `ClaimRow({c})` are private to `sections.jsx`.

---

## 6. Every API route, method, path, inputs, outputs, auth and side effects

All 127 routes live in `tradeos/app.py`. There are no server actions and no separate router files.
Authentication is by the `tos_session` cookie, read through FastAPI's `Cookie(None)` and resolved by
`authn.session_user`. A route that needs a user but has none either sets `response.status_code = 401`
and returns an error dict, or returns `{"authenticated": false}` — the two conventions coexist,
which is a minor inconsistency. Admin routes call `_require_admin`, which **returns the user object
on success and `None` on failure**, setting 401 or 403 as a side effect; every call site branches on
`if not _require_admin(...)`, and `tests/test_sources.py` asserts that shape is never inverted,
because getting it backwards once served the admin watchlist to anonymous callers.

**Global middleware.** One `@app.middleware("http")` function named `harden` runs before every
route. On any POST/PUT/DELETE/PATCH it refuses a cross-origin request whose `Origin` netloc does not
match `Host` and is not in `DEV_ORIGINS` — a CSRF belt-and-braces alongside SameSite=Lax. It then
applies rate limiting *before any work is done*, bucketing by path prefix: `public` for
`/api/public/` and `/api/ledger` at 120 per 60 seconds, `model` for `/api/assistant`,
`/api/analyze-chart` and `/api/extract-tickers` at 20 per 300 seconds, `auth_token` for
`/api/auth/verify/` and `/api/auth/reset/` at 10 per 900 seconds, and `upload` for any path ending
`/image` or `/chart-analysis` at 30 per 3600 seconds. It generates an eight-byte hex request id,
never derived from user input, and stamps it on `request.state` and on the response as
`X-Request-Id`. It catches every unhandled exception, logs it with the request id, and returns a
uniform `{"error": "internal error", "request_id": …}` with status 500 — never a stack trace. Then
it sets `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`,
and a CSP of `default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src
'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'`. When
`COOKIE_SECURE` is true it adds HSTS with a one-year max-age and `includeSubDomains`.

**Health.** `GET /health` returns `{"ok": true}`, unauthenticated, no side effects, used by the
container healthcheck.

**Authentication.** `POST /api/auth/register` takes `{email, password, invite_code}`, checks the
`registration` feature flag, and on success sets the session cookie and returns the user; side
effects are a `users` row, a consumed `invites` row or a referral link, a `sessions` row, an
`audit_log` row, a possible 14-day trial subscription, and a possible tier upgrade to `pro` under
free-launch mode. `POST /api/auth/login` takes `{email, password, totp_code?}` and returns 401 with
a deliberately uniform "invalid credentials" for a wrong email, a wrong password or a missing TOTP
code; it writes two `login_attempts` rows before checking anything. `POST /api/auth/logout` deletes
the session row and clears the cookie. `GET /api/auth/me` returns the current user or null.
`POST /api/auth/verify/request` and `POST /api/auth/reset/request` both take `{email}` and both
return an **identical** `{"sent": true, "message": …}` regardless of whether the address exists,
with every piece of work — lookup, token issuance, SMTP send — deferred to a FastAPI
`BackgroundTask` so the response *time* cannot answer the question the wording refuses to.
`POST /api/auth/verify/confirm` takes `{token}`; `POST /api/auth/reset/confirm` takes `{token,
password}` and, on success, deletes **every** session for that user including the caller's.
`GET /api/auth/google/start` returns a 302 to Google or a 503 with `{"error", "configured"}`;
`GET /api/auth/google/callback` consumes the one-time state, exchanges the code, validates the ID
token claims and links or creates an account, redirecting to `/auth?auth_error=<code>` on any
failure — a short code, never a message, because arbitrary text on the real login page is a phishing
surface and `str(exc)` in a URL bar leaks internals.

**Onboarding and profile.** `GET /api/onboarding` returns the older activation checklist (follows,
portfolios, alerts configured). `GET /api/profile/onboarding` returns whether this reader is due to
be asked plus the selectable countries; `POST /api/profile/onboarding` takes `{country?,
base_currency?, symbols[]}` and writes `user_profiles` plus watchlist rows;
`POST /api/profile/onboarding/skip` sets `snoozed_until`. `PUT /api/profile/frame` takes
`{country?, base_currency?, sectors[], risk_appetite?}` and rejects a country with no
`country_exposure` row. `PATCH /api/profile` takes `{handle?, bio?}` and sets the public identity.
`GET /api/referral` returns the reusable referral code and the count of people who joined through
it.

**Honesty and public surface.** `GET /api/feeds` returns per-source freshness plus three global
counts, unauthenticated. `GET /api/ledger` returns the whole accuracy record and the recent misses,
unauthenticated and deliberately never tier-gated — "an accuracy record behind a paywall is not an
accuracy record". `GET /api/public/walkthrough`, `GET /api/public/frame?country&limit` and
`GET /api/public/live?limit` are the three marketing-site endpoints, all delegating to
`public_site.py`, all unauthenticated, all read-only, none accepting an identifier that could
address a person. `GET /api/integrations` **requires a session** and returns raw operator detail —
last error text and per-feed row counts — only to admins.

**Claims and relevance.** `GET /api/claims?hours&limit` clamps hours to 1–720 and limit to 1–100,
resolves the reader's frame, scores every claim for relevance server-side (so the ranking cannot be
gamed from the client), attaches a `why_shown` sentence, sorts, threads by cluster, and returns the
list with `personalised`, `profile` and a standing disclaimer. `GET /api/countries` lists the
personalisable countries. `GET /api/globe` returns countries lit by claim placement, corridors,
exposure rows and an honest coverage note. `GET /api/exposure` is tier-gated: without the
entitlement it returns `{locked: true, what, upgrade}` rather than an empty page.

**Saved filters.** `GET /api/radar/filters` lists them with `min_throttle_mins` and `max_filters`.
`POST /api/radar/filters` takes `{name, spec, subscribed, channel?, webhook_url?, throttle_mins}`,
normalises the spec into a fixed five-key shape, enforces a maximum of 20 per user, floors the
throttle at 60 minutes, and — if the channel is `webhook` — runs the full SSRF check.
`DELETE /api/radar/filters/{fid}` is scoped to the owner. `POST /api/radar/filters/preview` returns
how many recent claims a spec would have caught, so a filter matching nothing is visible while
editing rather than after a week of silence.

**Signal plane.** `GET /api/activity?symbol&limit` merges insider transactions, stake events, fund
holdings and short interest for one issuer, every row carrying `event_time`, `knowable_time`,
`staleness_days` and `knowable_lag_days`. `GET /api/clusters?as_of&min_confidence&source_class`
resolves the tier's effective `as_of` server-side. `GET /api/clusters/{issuer_id}` returns full
detail and, when an admin reads a not-yet-public cluster, writes a `prepub_access` audit row — the
staff-trading seed. `GET /api/clusters/{issuer_id}/explanation?horizon&provider` returns guarded
prose. `GET /api/calibration`, `GET /api/definitions`, `GET /api/home`, `GET /api/leaderboards`,
`GET /api/asset/{symbol}`, `GET /api/institution/{entity_id}`, `GET /api/insider/{owner_cik}` and
`GET /api/track-record` are all read-only.

**Composed surfaces.** `GET /api/brief`, `GET /api/dashboard`, `GET /api/events?days`,
`GET /api/jobs`, `GET /api/news`, `GET /api/news/coverage`, `GET /api/news/{news_id}`,
`GET /api/trending?hours`, `GET /api/sentiment/{symbol}`, `GET /api/search?q`,
`GET /api/crypto/markets`, `GET /api/crypto/structure`, `GET /api/crypto/trending`,
`GET /api/library`, `GET /api/library/{slug}`, `GET /api/leaderboard/traders`.

**Trade journal.** `POST /api/trades` enforces the tier's `max_trades` cap before inserting, and
**after committing** attempts `journal_context.capture` inside its own `try` so a journal entry the
trader just wrote can never be lost because the spine was empty or slow. `GET /api/trades` returns
your own journal when authenticated or a profile's public trades when `user_id` is given.
`GET /api/trades/{tid}` returns `{found: false}` for a private trade you do not own — never
revealing its existence. `PATCH /api/trades/{tid}` re-sanitises every field and **deletes the cached
analysis** because the inputs changed. `DELETE /api/trades/{tid}` also unlinks the stored image.
`GET /api/trades/{tid}/analysis` is visible to viewers of a public trade;
`GET /api/trades/{tid}/context` is **owner-only and strictly stricter**, because the snapshot is
ranked by the owner's personal relevance and therefore leaks their country, currency and watchlist —
publishing a trade is not consent to publish the frame you read the world through.
`GET /api/trades/{tid}/chart-analysis?refresh` is owner-only and cached by image hash.
`GET /api/trades/{tid}/similar` is owner-only. `POST /api/trades/{tid}/image` and
`GET /api/trades/{tid}/image` handle upload and authenticated serving.
`POST /api/analyze-chart`, `GET /api/performance`, `POST /api/simulate`, `GET /api/journal/report`
and `POST /api/extract-tickers` complete the set.

**Community.** `GET /api/u/{handle}`, `POST /api/users/follow`, `DELETE
/api/users/follow/{handle}`, `GET /api/community/feed`, `POST /api/trades/{tid}/react`,
`DELETE /api/trades/{tid}/react/{kind}`, `GET /api/trades/{tid}/comments`,
`POST /api/trades/{tid}/comments`, `DELETE /api/comments/{cid}`, `POST /api/report`. Every write
passes through `_community_open`, which returns 403 when the `community_writes` flag is off.

**Watchlist, follows, notifications, alerts, portfolios.** `GET/POST/DELETE /api/watchlist` (the
POST validates the symbol against `^[A-Z0-9.\-]+$` capped at 12 characters);
`GET/POST /api/follows` and `DELETE /api/follows/{follow_id}`; `GET /api/notifications` and
`POST /api/notifications/read`; `GET/PUT /api/alert-prefs`; `POST /api/portfolios`,
`GET /api/portfolios`, `GET /api/portfolios/{pid}`, `POST /api/portfolios/{pid}/positions`,
`DELETE /api/portfolios/{pid}` and `DELETE /api/portfolios/{pid}/positions/{pos_id}`. Every one is
scoped to the session's `user_id` **inside the SQL WHERE clause**, not filtered afterwards.

**Billing and API keys.** `GET /api/billing/plans`, `POST /api/billing/checkout`,
`POST /api/billing/test-activate` (which refuses once a real provider is configured, so it can never
be a free-upgrade hole in production), `POST /api/billing/cancel`, and `POST /api/billing/webhook` —
the only route called by a machine rather than the browser, verifying the Stripe signature and
deduplicating on the Stripe event id. `POST /api/keys`, `GET /api/keys`, `DELETE /api/keys/{key_id}`.

**The Pro data API.** `GET /api/v1/clusters?min_confidence&limit` is the only route authenticated by
`Authorization: Bearer <key>` rather than a cookie. It verifies the hashed key, requires the `pro`
or `admin` tier, applies a per-key rate limit, respects the tier's effective `as_of`, and attaches
`meta.trace` — the per-key, per-day canary — plus a licence note.

**Admin.** `GET /api/admin/overview`, `GET /api/admin/moderation`,
`POST /api/admin/moderation/resolve`, `GET /api/admin/users`, `POST /api/admin/users/{uid}/tier`,
`POST /api/admin/users/{uid}/ban`, `GET /api/admin/flags`, `POST /api/admin/flags/{name}`,
`GET /api/admin/watchlist-accounts`, `POST /api/admin/watchlist-accounts` and
`GET /api/admin/audit`. Every mutation writes an `audit_log` row, so an admin action is itself an
auditable record, and `audit_log` carries a trigger forbidding UPDATE and DELETE.

**Sharing.** `GET /api/card/{symbol}.svg` renders a 1200×630 SVG from the **free-tier delayed view**
specifically so a public artifact cannot leak a fresh paid signal. `GET /s/{symbol}` is a
server-rendered HTML preview page.

Three routes have no frontend caller by design: `/health` (the container healthcheck),
`/api/card/{symbol}.svg` (fetched by link-preview crawlers) and `/api/billing/webhook` (called by
Stripe).

---

## 7. The database in complete detail

**Which database.** PostgreSQL 16.x, the official `postgres:16` image. Three extensions are created:
`citext` (migration 009, for case-insensitive email and handle), `pg_trgm` (migration 024, for
trigram similarity in clustering) and the implicit `plpgsql` used by the immutability trigger.

**Which client.** psycopg 3.2.9 with the binary extra. No ORM. `tradeos/db.py` exposes exactly one
connection function, `connect()`, which calls `psycopg.connect(database_url())`. There is **no
connection pool** — every request opens and closes a connection via `with db.connect() as conn`.
That is a real scalability limitation and it is not documented anywhere in the repository.

**How the connection is configured.** Entirely from `DATABASE_URL`. `config.database_url()` raises
`ConfigError` if it is unset. In `docker-compose.yml` it is
`postgresql://tradeos:${POSTGRES_PASSWORD}@db:5432/tradeos` for both api and worker; in
`docker-compose.prod.yml` it is interpolated from `POSTGRES_USER`, `POSTGRES_PASSWORD` and
`POSTGRES_DB`, with compose refusing to start if `POSTGRES_PASSWORD` is unset.

**The migration mechanism.** `run_migrations(conn)` reads `applied_versions(conn)` — which first
checks `to_regclass('schema_migrations')` and returns an empty set if the table does not exist —
then globs `MIGRATIONS_DIR.glob("*.sql")`, sorts by filename, extracts the leading integer with
`re.match(r"(\d+)_", …)`, skips anything already applied, executes the file's whole text in one
cursor and commits per file. **The runner does not record the version.** Every migration file must
insert its own `schema_migrations` row as its last statement, and all 33 do. `tests/test_slice2.py`
enforces this with a regex.

**The count.** Thirty-three migrations create **61 tables**. That matches `CLAUDE.md`.

### Table by table

**`schema_migrations`** (001) — `version integer PRIMARY KEY`, `applied_at timestamptz NOT NULL
DEFAULT now()`.

**`raw_filings`** (001) — the immutable raw layer. `id bigserial PK`, `source text NOT NULL`,
`accession_no text NOT NULL UNIQUE` (the idempotency key that makes re-ingestion a no-op),
`source_url text NOT NULL`, `sha256 char(64) NOT NULL`, `fetched_at timestamptz NOT NULL DEFAULT
now()`, `accepted_at timestamptz NOT NULL` (the knowable_time, from the EDGAR header in US/Eastern),
`payload bytea NOT NULL` (the full original document). A `BEFORE UPDATE OR DELETE … FOR EACH ROW`
trigger named `raw_filings_immutable` executes `forbid_mutation()`, a plpgsql function that raises
an exception. Append-only is enforced by the database, not by convention. Per `scripts/backup.sh`
this table is 4.7 GB of a 5.2 GB database.

**`insider_transactions`** (001, altered by 002) — `id bigserial PK`, `accession_no text NOT NULL
REFERENCES raw_filings(accession_no)`, `seq integer NOT NULL`, `form_type text NOT NULL`,
`amends_accession text` (nullable), `issuer_cik text NOT NULL`, `issuer_name text NOT NULL`, `symbol
text` (nullable), `owner_cik text NOT NULL`, `owner_name text NOT NULL`, `is_director boolean NOT
NULL DEFAULT false`, `is_officer boolean NOT NULL DEFAULT false`, `officer_title text`,
`security_title text NOT NULL`, `transaction_code text NOT NULL`, `event_time date NOT NULL`,
`knowable_time timestamptz NOT NULL`, `shares numeric`, `price_per_share numeric`,
`acquired_disposed char(1) NOT NULL`, `shares_after numeric`, `direct_indirect char(1)`, plus
`issuer_entity bigint REFERENCES entities(id)` added in 002. `UNIQUE (accession_no, seq,
owner_cik)`. Indexes on `(symbol, knowable_time)`, `(issuer_cik, knowable_time)` and
`(issuer_entity, knowable_time)`. `scripts/backup.sh` records 664,923 rows; `docs/state.md` agrees.

**`ingest_rejects`** (001) — `id bigserial PK`, `source text NOT NULL`, `accession_no text`, `reason
text NOT NULL`, `created_at timestamptz NOT NULL DEFAULT now()`. The loud-degradation layer.

**`feed_health`** (001) — `source text PRIMARY KEY`, `last_success_at timestamptz`,
`last_record_knowable timestamptz`, `records_total bigint NOT NULL DEFAULT 0`, `rejects_total bigint
NOT NULL DEFAULT 0`, `note text`.

**`entities`** (002) — `id bigserial PK`, `kind text NOT NULL CHECK (kind IN
('issuer','institution','insider'))`, `cik text UNIQUE`, `name text NOT NULL`, `created_at
timestamptz NOT NULL DEFAULT now()`. One CIK maps to exactly one entity even when it plays two
roles, because it is the same real-world party.

**`security_map`** (002) — `id bigserial PK`, `entity_id bigint NOT NULL REFERENCES entities(id)`,
`symbol text`, `cusip text`, `figi text`, `source text NOT NULL` (`sec_company_tickers` | `filing` |
`openfigi`), `confidence real NOT NULL`, `valid_from timestamptz NOT NULL DEFAULT now()`, `UNIQUE
(entity_id, symbol, cusip)`. Plus a **partial** unique index `uq_security_map_symbol_nocusip ON
(entity_id, symbol) WHERE cusip IS NULL` — necessary because NULLs are distinct under a plain
UNIQUE, so re-running `sync-tickers` would otherwise duplicate. Partial indexes on `cusip` and
`symbol` where each is not null.

**`stake_events`** (002) — `id bigserial PK`, `accession_no text NOT NULL REFERENCES
raw_filings(accession_no)`, `form_type text NOT NULL`, `amends_accession text`, `file_number text`
(the SEC 005-xxxxx amendment-series key), `filer_entity bigint NOT NULL REFERENCES entities(id)`,
`issuer_entity bigint REFERENCES entities(id)` (nullable — an unresolved issuer is displayed as
unresolved rather than guessed), `issuer_name_raw text NOT NULL`, `percent_owned numeric` (**always
NULL** by decision #19, because it would have to be scraped from an ambiguous HTML cover page),
`event_time date NOT NULL`, `knowable_time timestamptz NOT NULL`, `parse_confidence text NOT NULL`
(`header_period` | `filing_date_fallback`), `activist boolean NOT NULL`. `UNIQUE (accession_no,
filer_entity, issuer_name_raw)`. Indexes on `(issuer_entity, knowable_time)` and `(file_number)`.
Recorded at 51,099 rows in `scripts/backup.sh`, later grown — `docs/progress/cross_check.md` records
31,698 stake events in 2022 and 30,048 in 2023 added by a later backfill.

**`fund_holdings`** (002) — `id bigserial PK`, `accession_no text NOT NULL REFERENCES
raw_filings(accession_no)`, `filer_entity bigint NOT NULL REFERENCES entities(id)`, `period_end date
NOT NULL`, `knowable_time timestamptz NOT NULL` (up to 45 days later — the gap *is* the story),
`cusip text NOT NULL`, `issuer_name_raw text NOT NULL`, `issuer_entity bigint REFERENCES
entities(id)`, `value_usd numeric`, `shares numeric`, `share_type text`. `UNIQUE (accession_no,
cusip, share_type)`. Recorded at 24,982 rows, of which `docs/bugs.md` B-14 says **19,851 have
unresolved CUSIPs** and are therefore invisible to every surface.

**`signal_definitions`** (003) — `id bigserial PK`, `name text NOT NULL`, `version integer NOT
NULL`, `params jsonb NOT NULL`, `code_hash text NOT NULL`, `changelog text NOT NULL`, `created_at
timestamptz NOT NULL DEFAULT now()`, `UNIQUE (name, version)`.

**`signal_clusters`** (003) — `id bigserial PK`, `definition_id bigint NOT NULL REFERENCES
signal_definitions(id)`, `issuer_entity bigint NOT NULL REFERENCES entities(id)`, `as_of timestamptz
NOT NULL`, `score numeric NOT NULL`, `confidence_bucket text NOT NULL CHECK (… IN
('low','medium','high'))`, `voices integer NOT NULL`, `source_classes text[] NOT NULL`, `inputs
jsonb NOT NULL` (the exact contributing events with ids, weights, decayed values and floor status),
`UNIQUE (definition_id, issuer_entity, as_of)`. Indexes on `(as_of DESC)` and `(issuer_entity, as_of
DESC)`. `docs/progress/cross_check.md` records 17,145 clusters collapsing to 583 distinct episodes,
later grown.

**`prices_eod`** (004) — `symbol text NOT NULL`, `day date NOT NULL`, `open/high/low numeric`,
`close numeric NOT NULL`, `volume numeric`, `source text NOT NULL`, `PRIMARY KEY (symbol, day)`,
index on `(symbol, day)`.

**`signal_outcomes`** (004) — `cluster_id bigint PRIMARY KEY REFERENCES signal_clusters(id)`,
`entry_day date NOT NULL`, `excess_30/excess_90/excess_180 numeric` (all nullable — NULL until the
horizon closes or prices exist), `computed_at timestamptz NOT NULL DEFAULT now()`.

**`explanation_cache`** (005) — `cluster_id bigint NOT NULL REFERENCES signal_clusters(id)`,
`provider text NOT NULL`, `definition_version integer NOT NULL`, `prose text NOT NULL`, `model_id
text NOT NULL`, `used_template boolean NOT NULL DEFAULT false`, `created_at timestamptz NOT NULL
DEFAULT now()`, `PRIMARY KEY (cluster_id, provider)`.

**`short_interest`** (006) — `id bigserial PK`, `symbol text NOT NULL`, `issuer_entity bigint
REFERENCES entities(id)`, `settlement_date date NOT NULL`, `knowable_time timestamptz NOT NULL`,
`current_short/previous_short/change_short/avg_daily_volume/days_to_cover numeric`, `source text NOT
NULL`, `UNIQUE (symbol, settlement_date)`, index on `(issuer_entity, knowable_time)`. **Fed but
never read** — deliberately parked, see section 17.

**`library_entries`** (007) — `id bigserial PK`, `slug text UNIQUE NOT NULL`, `kind text NOT NULL
CHECK (kind IN ('concept','investor_profile'))`, `title text NOT NULL`, `body_md text NOT NULL`,
`sources jsonb NOT NULL`, `linked_source_classes text[] NOT NULL DEFAULT '{}'`, `review_status text
NOT NULL DEFAULT 'draft'`, `created_at timestamptz NOT NULL DEFAULT now()`, GIN index on
`linked_source_classes`. Seeded with the 20 entries from `content/library/entries.json`.

**`watchlists`** (008, re-keyed by 026) — originally `user_key text NOT NULL DEFAULT 'demo'`, which
was bug B-22: every account shared one list and any caller could address another by changing a query
parameter. Migration 026 adds `user_id bigint REFERENCES users(id) ON DELETE CASCADE`, migrates rows
whose key was already a user id or a resolvable email, assigns the shared `'demo'` pile to the
seeded demo account, makes `user_key` nullable and drops its default, drops the old unique
constraint and creates `watchlists_owner_symbol_idx ON (user_id, symbol)` plus
`watchlists_owner_idx ON (user_id)`. **`user_key` still exists**, kept for one release so a rollback
does not lose the mapping; no later migration drops it, so it is still there.

**`users`** (009, altered by 013, 016, 017, 031) — `id bigserial PK`, `email citext UNIQUE NOT
NULL`, `password_hash text NOT NULL` (argon2id), `tier text NOT NULL DEFAULT 'free' CHECK (tier IN
('free','retail','pro','admin'))`, `totp_secret text` (required for admin, optional otherwise),
`created_at timestamptz NOT NULL DEFAULT now()`, `referral_code text UNIQUE` (013), `referred_by
bigint REFERENCES users(id)` (013), `handle citext UNIQUE` (016, NULL until claimed), `bio text`
(016), `banned boolean NOT NULL DEFAULT false` (017), `email_verified_at timestamptz` (031, NULL for
every account predating that migration because "claiming they were verified would be a lie written
by a migration").

**`sessions`** (009) — `id bigserial PK`, `user_id bigint NOT NULL REFERENCES users(id)`,
`token_hash char(64) NOT NULL UNIQUE`, `created_at timestamptz NOT NULL DEFAULT now()`, `expires_at
timestamptz NOT NULL`, `ip text`, `ua text`, index on `token_hash`. The raw token is never stored.

**`invites`** (009) — `code text PRIMARY KEY`, `created_by bigint REFERENCES users(id)`, `used_by
bigint REFERENCES users(id)`, `used_at timestamptz`, `created_at timestamptz NOT NULL DEFAULT
now()`.

**`audit_log`** (009) — `id bigserial PK`, `actor text`, `action text NOT NULL`, `object text`, `at
timestamptz NOT NULL DEFAULT now()`, `detail jsonb`. Carries the same `forbid_mutation()` trigger as
`raw_filings`; it is append-only at the database level.

**`login_attempts`** (009) — `id bigserial PK`, `key text NOT NULL` (an IP or an email), `at
timestamptz NOT NULL DEFAULT now()`, index on `(key, at)`. **This table is never pruned** — see
section 18.

**`feature_flags`** (009, row deleted by 033) — `name text PRIMARY KEY`, `enabled boolean NOT NULL
DEFAULT true`, `blocked_countries text[] NOT NULL DEFAULT '{}'`. Seeded with `congress` (false),
`short_interest` (false), `signals` (true) and `previews` (true). Migration 033 deletes the
`congress` row. **`blocked_countries` is declared and never read by any code**, and `signals` and
`previews` are inert historical rows that no code consults.

**`follows`** (010) — `id bigserial PK`, `user_id bigint NOT NULL REFERENCES users(id) ON DELETE
CASCADE`, `kind text NOT NULL CHECK (kind IN ('symbol','insider','filer'))`, `ref text NOT NULL`,
`label text`, `created_at timestamptz NOT NULL DEFAULT now()`, `UNIQUE (user_id, kind, ref)`, index
on `user_id`.

**`alert_prefs`** (010) — `user_id bigint PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE`,
`new_high_conviction boolean NOT NULL DEFAULT true`, `followed_activity boolean NOT NULL DEFAULT
true`, `min_score int NOT NULL DEFAULT 75 CHECK (min_score BETWEEN 0 AND 100)`, `email_enabled
boolean NOT NULL DEFAULT false`, `updated_at timestamptz NOT NULL DEFAULT now()`.

**`notifications`** (010) — `id bigserial PK`, `user_id bigint NOT NULL REFERENCES users(id) ON
DELETE CASCADE`, `kind text NOT NULL`, `title text NOT NULL`, `body text NOT NULL`, `symbol text`,
`entity_id bigint` (**not** a foreign key), `dedup_key text NOT NULL`, `created_at timestamptz NOT
NULL DEFAULT now()`, `read_at timestamptz`, `UNIQUE (user_id, dedup_key)`, index on `(user_id,
created_at DESC)`.

**`email_outbox`** (010) — `id bigserial PK`, `user_id bigint NOT NULL REFERENCES users(id) ON
DELETE CASCADE`, `to_email text NOT NULL`, `subject text NOT NULL`, `body text NOT NULL`, `status
text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','sent','failed','skipped'))`, `provider
text`, `created_at timestamptz NOT NULL DEFAULT now()`, `sent_at timestamptz`, index on `(status,
created_at)`.

**`portfolios`** (011) — `id bigserial PK`, `user_id bigint NOT NULL REFERENCES users(id) ON DELETE
CASCADE`, `name text NOT NULL`, `kind text NOT NULL DEFAULT 'manual' CHECK (kind IN
('manual','shadow_bucket'))`, `spec jsonb NOT NULL DEFAULT '{}'`, `created_at timestamptz NOT NULL
DEFAULT now()`, index on `user_id`.

**`portfolio_positions`** (011) — `id bigserial PK`, `portfolio_id bigint NOT NULL REFERENCES
portfolios(id) ON DELETE CASCADE`, `symbol text NOT NULL`, `entity_id bigint` (not a foreign key),
`opened_on date NOT NULL`, `note text`, `created_at timestamptz NOT NULL DEFAULT now()`, `UNIQUE
(portfolio_id, symbol)`, index on `portfolio_id`.

**`subscriptions`** (012) — `user_id bigint PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE`,
`plan text NOT NULL DEFAULT 'free' CHECK (plan IN ('free','retail','pro'))`, `status text NOT NULL
DEFAULT 'active' CHECK (status IN ('active','past_due','canceled','trialing'))`, `provider text`,
`provider_customer_id text`, `provider_subscription_id text`, `current_period_end timestamptz`,
`updated_at`/`created_at timestamptz NOT NULL DEFAULT now()`.

**`billing_events`** (012) — `id bigserial PK`, `user_id bigint REFERENCES users(id) ON DELETE SET
NULL`, `provider text NOT NULL`, `event_type text NOT NULL`, `provider_event_id text UNIQUE` (the
webhook idempotency key), `payload jsonb`, `at timestamptz NOT NULL DEFAULT now()`.

**`api_keys`** (012) — `id bigserial PK`, `user_id bigint NOT NULL REFERENCES users(id) ON DELETE
CASCADE`, `name text`, `prefix text NOT NULL`, `key_hash char(64) NOT NULL UNIQUE`, `scopes text[]
NOT NULL DEFAULT '{read}'`, `canary text NOT NULL`, `last_used_at timestamptz`, `created_at
timestamptz NOT NULL DEFAULT now()`, `revoked_at timestamptz`, index on `user_id`.

**`trades`** (014, altered by 016) — `id bigserial PK`, `user_id bigint NOT NULL REFERENCES
users(id) ON DELETE CASCADE`, `symbol text` (nullable — not every idea is a resolvable ticker),
`entity_id bigint`, `asset_class text NOT NULL DEFAULT 'equity' CHECK (… IN
('equity','crypto','forex','option','future','other'))`, `direction text NOT NULL DEFAULT 'long'
CHECK (… IN ('long','short'))`, `status text NOT NULL DEFAULT 'planned' CHECK (… IN
('planned','open','closed'))`, `entry_price/exit_price/stop_price/target_price/size double
precision`, `size_unit text NOT NULL DEFAULT 'shares' CHECK (… IN
('shares','contracts','usd','units','lots'))`, `timeframe text`, `strategy text`, `reason_entry
text`, `reason_exit text`, `confidence smallint CHECK (confidence BETWEEN 1 AND 5)`,
`expected_outcome text`, `opened_on date`, `closed_on date`, `image_path text` (an opaque key, never
a user filename), `is_public boolean NOT NULL DEFAULT false`, `created_at`/`updated_at timestamptz
NOT NULL DEFAULT now()`, plus `hidden boolean NOT NULL DEFAULT false` (016). Indexes on `(user_id,
created_at DESC)`, a **partial** index on `(created_at DESC) WHERE is_public`, and `(symbol)`.

**`trade_analyses`** (014) — `trade_id bigint PRIMARY KEY REFERENCES trades(id) ON DELETE CASCADE`,
`input_hash text NOT NULL`, `provider text NOT NULL`, `model_id text NOT NULL`, `used_template
boolean NOT NULL DEFAULT true`, `content jsonb NOT NULL`, `created_at timestamptz NOT NULL DEFAULT
now()`.

**`sentiment_observations`** (015) — `id bigserial PK`, `source text NOT NULL`, `symbol text NOT
NULL`, `entity_id bigint REFERENCES entities(id)`, `window_end timestamptz NOT NULL`, `window_hours
integer NOT NULL`, `mentions integer NOT NULL`, `baseline real` (NULL = no history), `sentiment
real` (NULL when the source has no sentiment — Wikipedia and HN both write NULL, honestly),
`bots_filtered integer NOT NULL DEFAULT 0`, `knowable_time timestamptz NOT NULL`, `meta jsonb NOT
NULL DEFAULT '{}'`, `created_at timestamptz NOT NULL DEFAULT now()`, `UNIQUE (source, symbol,
window_end)`, indexes on `(window_end DESC)` and `(symbol, window_end DESC)`.

**`user_follows`** (016) — `follower_id bigint NOT NULL REFERENCES users(id) ON DELETE CASCADE`,
`followee_id bigint NOT NULL REFERENCES users(id) ON DELETE CASCADE`, `created_at timestamptz NOT
NULL DEFAULT now()`, `PRIMARY KEY (follower_id, followee_id)`, `CHECK (follower_id <> followee_id)`,
index on `followee_id`.

**`trade_reactions`** (016) — `id bigserial PK`, `trade_id bigint NOT NULL REFERENCES trades(id) ON
DELETE CASCADE`, `user_id bigint NOT NULL REFERENCES users(id) ON DELETE CASCADE`, `kind text NOT
NULL CHECK (kind IN ('like','save'))`, `created_at timestamptz NOT NULL DEFAULT now()`, `UNIQUE
(trade_id, user_id, kind)`, index on `(trade_id, kind)` and a partial index on `(user_id) WHERE kind
= 'save'`.

**`trade_comments`** (016) — `id bigserial PK`, `trade_id bigint NOT NULL REFERENCES trades(id) ON
DELETE CASCADE`, `user_id bigint NOT NULL REFERENCES users(id) ON DELETE CASCADE`, `body text NOT
NULL`, `hidden boolean NOT NULL DEFAULT false`, `created_at timestamptz NOT NULL DEFAULT now()`,
index on `(trade_id, created_at)`.

**`content_reports`** (016, altered by 017) — `id bigserial PK`, `reporter_id bigint NOT NULL
REFERENCES users(id) ON DELETE CASCADE`, `target_type text NOT NULL CHECK (target_type IN
('trade','comment'))`, `target_id bigint NOT NULL` (**deliberately not a foreign key**, because it
addresses two different tables), `reason text`, `created_at timestamptz NOT NULL DEFAULT now()`,
`UNIQUE (reporter_id, target_type, target_id)`, plus `resolved_at timestamptz`, `resolved_by text`
and `resolution text` from 017. Indexes on `(target_type, target_id)` and a partial
`idx_reports_open ON (target_type, target_id) WHERE resolved_at IS NULL`, because both the
moderation queue and the auto-hide counter look only at open reports.

**`journal_reports`** (018) — `user_id bigint PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE`,
`input_hash char(64) NOT NULL`, `provider text NOT NULL`, `model_id text NOT NULL`, `used_template
boolean NOT NULL`, `content jsonb NOT NULL`, `created_at timestamptz NOT NULL DEFAULT now()`.

**`news_items`** (019) — `id bigserial PK`, `source text NOT NULL`, `external_id text NOT NULL`,
`url text NOT NULL`, `headline text NOT NULL`, `summary text` (source description only — article
bodies are never republished), `category text`, `published_at timestamptz`, `knowable_time
timestamptz NOT NULL`, `meta jsonb NOT NULL DEFAULT '{}'`, `created_at timestamptz NOT NULL DEFAULT
now()`, `UNIQUE (source, external_id)`, indexes on `(knowable_time DESC)` and `(category)`.

**`news_item_entities`** (019) — `news_id bigint NOT NULL REFERENCES news_items(id) ON DELETE
CASCADE`, `entity_id bigint`, `symbol text NOT NULL`, `relation text NOT NULL DEFAULT 'primary'`,
`PRIMARY KEY (news_id, symbol)`, index on `symbol`.

**`news_analysis`** (019) — `news_id bigint PRIMARY KEY REFERENCES news_items(id) ON DELETE
CASCADE`, `impact_score int NOT NULL` (deterministic, 0–100), `category text`, `why_it_matters text
NOT NULL`, `confidence text NOT NULL`, `sources jsonb NOT NULL DEFAULT '[]'`, `provider text NOT
NULL`, `model_id text NOT NULL`, `used_template boolean NOT NULL`, `created_at timestamptz NOT NULL
DEFAULT now()`, index on `(impact_score DESC)`.

**`daily_briefs`** (019) — `id bigserial PK`, `user_id bigint REFERENCES users(id) ON DELETE
CASCADE` (NULL = the shared market brief), `brief_date date NOT NULL`, `scope text NOT NULL DEFAULT
'market'`, `input_hash char(64) NOT NULL`, `provider text NOT NULL`, `model_id text NOT NULL`,
`used_template boolean NOT NULL`, `content jsonb NOT NULL`, `created_at timestamptz NOT NULL DEFAULT
now()`. Two **partial** unique indexes rather than one plain one, because NULLs are distinct:
`daily_briefs_market_uniq ON (brief_date, scope) WHERE user_id IS NULL` and
`daily_briefs_personal_uniq ON (user_id, brief_date, scope) WHERE user_id IS NOT NULL`.

**`wiki_titles`** (020) — `symbol text PRIMARY KEY`, `entity_id bigint`, `title text` (NULL when
unresolved), `resolved_ok boolean NOT NULL DEFAULT false`, `resolved_at timestamptz NOT NULL DEFAULT
now()`. An honest miss is cached so pageviews are never fetched for a fabricated title.

**`job_runs`** (021) — `id bigserial PK`, `job text NOT NULL`, `started_at timestamptz NOT NULL
DEFAULT now()`, `finished_at timestamptz`, `status text` (`ok` | `error`), `detail jsonb`,
`duration_ms integer`, index on `(job, started_at DESC)`. **Never pruned.**

**`market_events`** (022) — `id bigserial PK`, `kind text NOT NULL`, `scope text NOT NULL`, `title
text NOT NULL`, `event_date date NOT NULL`, `event_time text` (a label like `pre-market`, not a
timestamp), `importance text NOT NULL DEFAULT 'medium'`, `symbol text`, `entity_id bigint`, `country
text`, `source text NOT NULL`, `external_id text NOT NULL`, `meta jsonb NOT NULL DEFAULT '{}'`,
`created_at timestamptz NOT NULL DEFAULT now()`, `UNIQUE (source, external_id)`, indexes on
`(event_date, importance)` and `(symbol)`.

**`chart_analyses`** (023) — `trade_id bigint PRIMARY KEY REFERENCES trades(id) ON DELETE CASCADE`,
`image_hash char(64) NOT NULL`, `analysis jsonb NOT NULL`, `model_id text NOT NULL`, `used_template
boolean NOT NULL`, `created_at timestamptz NOT NULL DEFAULT now()`.

**`events`** (024) — the spine. `id bigserial PK`, `source text NOT NULL`, `external_id text NOT
NULL`, `source_url text NOT NULL`, `author text` (NULL for wire copy), `author_influence real`
(0..1, NULL when unknown), `published_at timestamptz`, `knowable_time timestamptz NOT NULL` (**the**
time column), `ingested_at timestamptz NOT NULL DEFAULT now()`, `title text NOT NULL`, `body text`,
`language text`, `entities jsonb NOT NULL DEFAULT '[]'`, `geo text[] NOT NULL DEFAULT '{}'`,
`category text`, `novelty_score real`, `amplification real`, `raw_payload jsonb NOT NULL DEFAULT
'{}'` (always kept, so the engine can be re-run over history), `cluster_id bigint` with the foreign
key added after `event_clusters` exists, `UNIQUE (source, external_id)`. Six indexes: `(knowable_time
DESC)`, `(category, knowable_time DESC)`, `(cluster_id)`, GIN on `geo`, GIN on `entities` with
`jsonb_path_ops`, and **GIN on `title` with `gin_trgm_ops`** — which is the index that
`spine.find_cluster` cannot actually use, for the reason set out in section 18.

**`event_clusters`** (024) — `id bigserial PK`, `canonical_event bigint REFERENCES events(id) ON
DELETE SET NULL`, `title text NOT NULL`, `category text`, `geo text[] NOT NULL DEFAULT '{}'`,
`first_seen timestamptz NOT NULL`, `last_seen timestamptz NOT NULL`, `source_count int NOT NULL
DEFAULT 1` (**distinct** sources — corroboration, not volume), `event_count int NOT NULL DEFAULT 1`,
`novelty_score real`, `amplification real`, `velocity_curve jsonb NOT NULL DEFAULT '[]'`,
`updated_at timestamptz NOT NULL DEFAULT now()`. Indexes on `(last_seen DESC)`, `(category,
last_seen DESC)` and GIN on `geo`.

**`watchlist_accounts`** (024) — `id bigserial PK`, `platform text NOT NULL`, `handle text NOT
NULL`, `display_name text NOT NULL`, `role text`, `domain text`, `country text`, `influence real NOT
NULL DEFAULT 0.5`, `feed_url text`, `active boolean NOT NULL DEFAULT true`, `note text`, `created_at
timestamptz NOT NULL DEFAULT now()`, `UNIQUE (platform, handle)`, index on `(active, domain)`.

**`source_calls`** (024) — `id bigserial PK`, `source text NOT NULL`, `at timestamptz NOT NULL
DEFAULT now()`, `endpoint text` (**path only, never the query string, because that is where
credentials travel**), `status int`, `duration_ms int`, `units int NOT NULL DEFAULT 1`, `ok boolean
NOT NULL DEFAULT true`, index on `(source, at DESC)`. Also doubles as the persistent GDELT backoff
clock, so a container restart cannot reset the penalty.

**`claims`** (025, altered by 027 and 032) — the heart. `id bigserial PK`, `event_id bigint
REFERENCES events(id) ON DELETE CASCADE` (**NULL for signal-plane claims**, which is exactly how
`ledger.summary` splits the two planes), `cluster_id bigint REFERENCES event_clusters(id) ON DELETE
SET NULL`, `created_at timestamptz NOT NULL DEFAULT now()`, `model_version text NOT NULL`,
`mechanism text NOT NULL`, `affected jsonb NOT NULL DEFAULT '[]'`, `horizon text NOT NULL`,
`horizon_days int NOT NULL`, `confidence real NOT NULL CHECK (confidence >= 0 AND confidence <= 1)`,
`analogs jsonb NOT NULL DEFAULT '[]'`, `contradicts bigint[] NOT NULL DEFAULT '{}'`,
`reasoning_trace jsonb NOT NULL DEFAULT '[]'`, `resolved_at timestamptz`, `status text NOT NULL
DEFAULT 'open' CHECK (status IN ('open','resolved','unscoreable'))`, plus `source_ref text` (027,
with a partial unique index where not null) and `supersedes bigint REFERENCES claims(id) ON DELETE
SET NULL` (032, with a partial index where not null). Five other indexes: `(created_at DESC)`,
`(event_id)`, `(cluster_id)`, `(status, created_at DESC)` and GIN on `affected` with
`jsonb_path_ops`.

**`claim_outcomes`** (025) — `id bigserial PK`, `claim_id bigint NOT NULL REFERENCES claims(id) ON
DELETE CASCADE`, `subject text NOT NULL`, `predicted text NOT NULL`, `magnitude text`, `measured_at
timestamptz NOT NULL DEFAULT now()`, `entry_day date`, `exit_day date`, `actual_return real`,
`excess_return real`, `verdict text NOT NULL CHECK (verdict IN
('hit','miss','inconclusive','unscoreable'))`, `note text`, `UNIQUE (claim_id, subject)`, index on
`verdict`. **One row per (claim, affected asset)** — a claim naming three assets is scored three
times, because getting one right and two wrong is not "right".

**`country_exposure`** (025) — `country text PRIMARY KEY` (ISO alpha-2), `name text NOT NULL`,
`currency text NOT NULL`, `currency_regime text`, `pegged_to text`, `main_index text`,
`export_partners text[] NOT NULL DEFAULT '{}'`, `import_partners text[] NOT NULL DEFAULT '{}'`,
`key_exports text[] NOT NULL DEFAULT '{}'`, `key_imports text[] NOT NULL DEFAULT '{}'`,
`commodity_exposure jsonb NOT NULL DEFAULT '{}'`, `source text`, `updated_at timestamptz NOT NULL
DEFAULT now()`. **Ten rows**, seeded from `relevance.COUNTRIES`: AE, SA, US, GB, IN, CN, BR, JP, DE,
SG. Every row cites a source (a central bank plus UN Comtrade or the national statistics office).

**`user_profiles`** (025, altered by 029) — `user_id bigint PRIMARY KEY REFERENCES users(id) ON
DELETE CASCADE`, `country text REFERENCES country_exposure(country)`, `base_currency text`, `sectors
text[] NOT NULL DEFAULT '{}'`, `risk_appetite text`, `updated_at timestamptz NOT NULL DEFAULT
now()`, plus `onboarded_at timestamptz` and `snoozed_until timestamptz` (029, with existing profiles
carrying a country backfilled as already onboarded).

**`trade_context`** (028) — `trade_id bigint PRIMARY KEY REFERENCES trades(id) ON DELETE CASCADE`,
`captured_at timestamptz NOT NULL DEFAULT now()`, `as_of timestamptz NOT NULL`, `basis text NOT NULL
DEFAULT 'live' CHECK (basis IN ('live','reconstructed'))`, `claim_ids bigint[] NOT NULL DEFAULT
'{}'`, `n_live int NOT NULL DEFAULT 0`, `n_on_symbol int NOT NULL DEFAULT 0`, `alignment text CHECK
(alignment IN ('with','against','mixed','none'))`, `mean_novelty real`, `snapshot jsonb NOT NULL
DEFAULT '{}'`, index on `alignment`. Written **once**, at trade creation, and never updated when the
trade is edited — the whole point, because a later edit could otherwise drift the record toward
whatever the trader now believes was happening.

**`oauth_identities`** (030) — `id bigserial PK`, `provider text NOT NULL`, `subject text NOT NULL`,
`user_id bigint NOT NULL REFERENCES users(id) ON DELETE CASCADE`, `email text` (stored only as a
record of what the provider asserted; **never** the lookup key), `linked_at timestamptz NOT NULL
DEFAULT now()`, `last_login timestamptz`, `UNIQUE (provider, subject)`, index on `user_id`.
`user_id` is deliberately not unique, so one user may hold several identities.

**`oauth_states`** (030) — `state text PRIMARY KEY`, `provider text NOT NULL`, `created_at
timestamptz NOT NULL DEFAULT now()`, `redirect_to text`. Server-side rather than a signed cookie,
because it has to be *consumed*: a state that can be replayed is not CSRF protection.

**`auth_tokens`** (031) — `id bigserial PK`, `user_id bigint NOT NULL REFERENCES users(id) ON DELETE
CASCADE`, `purpose text NOT NULL CHECK (purpose IN ('verify_email','reset_password'))`, `token_hash
char(64) NOT NULL UNIQUE`, `created_at timestamptz NOT NULL DEFAULT now()`, `expires_at timestamptz
NOT NULL`, `used_at timestamptz`, indexes on `(user_id, purpose)` and `(expires_at)`. The row is
kept rather than deleted on redemption so a second attempt can be told "already used" instead of
"invalid".

**`radar_filters`** (032) — `id bigserial PK`, `user_id bigint NOT NULL REFERENCES users(id) ON
DELETE CASCADE`, `name text NOT NULL`, `spec jsonb NOT NULL DEFAULT '{}'`, `subscribed boolean NOT
NULL DEFAULT false`, `channel text CHECK (channel IN ('email','webhook'))`, `webhook_url text`,
`throttle_mins int NOT NULL DEFAULT 360 CHECK (throttle_mins >= 60)`, `last_claim_id bigint` (a
high-water mark, deliberately an id and not a timestamp so a retry, a restart or a clock change
cannot resend), `last_sent_at timestamptz`, `created_at`/`updated_at timestamptz NOT NULL DEFAULT
now()`, `UNIQUE (user_id, name)`, partial index `ON (subscribed, last_sent_at) WHERE subscribed`.

**Enums.** There are no PostgreSQL `ENUM` types anywhere. Every enumerated value is a `text` column
with a `CHECK` constraint, which is a deliberate and sensible choice — adding a value is a migration
either way, but a `CHECK` does not require `ALTER TYPE`.

**Migrations in chronological order**, with what each does: 001 the honesty architecture (raw layer,
insider transactions, rejects, feed health, the immutability trigger); 002 entity resolution and the
institutional pipelines; 003 versioned signals and computed clusters; 004 prices and backtest
outcomes; 005 the explanation cache; 006 FINRA short interest; 007 the intelligence library; 008
watchlists (keyed by a free-text `user_key`); 009 authentication, sessions, invites, the append-only
audit log, login attempts and feature flags; 010 follows, alert preferences, notifications and the
email outbox; 011 paper portfolios; 012 subscriptions, billing events and API keys; 013 the referral
loop; 014 the trade journal and its analysis cache; 015 sentiment observations; 016 the community
and social graph; 017 the admin dashboard (ban plus non-destructive report resolution); 018 the
journal-report cache; 019 news intelligence and the Morning Brief; 020 the Wikipedia title cache;
021 the scheduler job-run log; 022 the forward market calendar; 023 the chart-analysis cache; 024
the event spine, clusters, the consequential-accounts watchlist and the source-call ledger; 025
claims, claim outcomes, country exposure and user profiles; 026 giving the watchlist a real owner
(fixing B-22); 027 moving the signal-plane provenance marker out of prose and into a `source_ref`
column, with a data migration extracting the markers already written into `mechanism`; 028 the
frozen world context at trade time; 029 onboarding state; 030 OAuth identities and states; 031 the
single-use auth tokens and `email_verified_at`; 032 claim threading (`supersedes`) and saved filter
sets; 033 deleting the `congress` feature-flag row for a source that was never built.

**Seed data.** There is no SQL-level seed data beyond the four `feature_flags` rows in migration
009. Everything else is seeded by CLI commands: `sync-library` loads the twenty library entries from
`content/library/entries.json`; `seed-exposure` loads the ten `country_exposure` rows from
`relevance.COUNTRIES`; `seed-watchlist` loads the 24 accounts from `watchlist_accounts.SEED`;
`seed-admin` creates an admin with a TOTP secret; `seed-demo` builds the populated demo account;
`create-invites` mints single-use codes; `signals-register` writes the first signal definition.

**Actual row counts.** I could not run a query. The numbers recorded by the project itself, with the
document and date attached: 664,923 insider transactions, 51,099 stake events and 24,982
institutional holdings (`scripts/backup.sh` header, undated but consistent with 2026-07-26); a 5.2
GB database of which `raw_filings` is 4.7 GB (same); 17,145 signal clusters collapsing to 583
episodes, 271 distinct tickers of which 268 have price history (`docs/progress/cross_check.md`,
2026-07-26); 19,851 fund holdings with unresolved CUSIPs (`docs/bugs.md` B-14); ~350 Bluesky events
on the first pass and 22 GDELT events as of 2026-07-26 (`docs/state.md`); 821 event clusters in the
matching window (`docs/progress/cross_check.md`); 412 resolved Ledger calls and 80 open impact-engine
claims (`docs/progress/cross_check.md`, the most recent measurement in the repository); 61 tables,
of which a verified dump restored 60 plus 501 TOC entries (`docs/progress/phase_9.md`). **What is
actually sitting in the database, in one sentence:** two years of real SEC filings, roughly seventeen
thousand computed signal snapshots, a few thousand news and world-event rows, a small number of
model-written claims, a demo user account with trades and portfolios, and 4.7 GB of raw filing
payloads that exist so every derived table can be rebuilt from source.

---

## 8. Auth and the user model, end to end

**Signup.** `POST /api/auth/register` is invite-gated. The flow in `authn.register` is: reject a
password shorter than ten characters or present in a hardcoded set of 29 common passwords (the set
is a small stand-in for a top-100k breached list, checked locally so a password is never sent
anywhere); lowercase and strip the email; insert a `users` row with an argon2id hash, catching
`UniqueViolation` and converting it to "email already registered"; try to consume a single-use
`invites` row by setting `used_by` and `used_at` where `code = ? AND used_by IS NULL`; if that
matched exactly zero rows, look the code up as another user's reusable `referral_code`, and if that
also fails, roll back and raise "invalid or already-used invite code"; create a session. A referred
signup then gets a 14-day `trialing` Pro subscription. Separately, **while `STRIPE_SECRET_KEY` is
unset, every non-referred signup is upgraded to `pro` at no charge** — the free-launch mode — and
this auto-reverts to the normal free default the moment the key is set, so switching on paid billing
needs no code change. The registration route also consults the `registration` feature flag first and
returns 403 when it is off.

**Login.** `authn.login` reads two `login_attempts` rows before touching the user table — one keyed
on IP, one on email — and refuses with "too many attempts" at ten attempts in fifteen minutes on
either key. It then fetches the user and verifies the password with argon2. A wrong email, a wrong
password, an admin without a configured TOTP secret, and a wrong or missing TOTP code all produce
the **identical** `AuthError("invalid credentials")`, so the response never distinguishes which
field failed. A banned account is the one exception: it gets "this account has been suspended", but
only after a correct password, which is the right trade — you have already proved you own it.

**Sessions.** `_create_session` mints `secrets.token_urlsafe(32)`, stores only
`hashlib.sha256(token).hexdigest()` in `sessions`, and sets `expires_at` with `now() +
make_interval(hours => %s)` bound as a parameter. `SESSION_HOURS = 24`. The cookie is `tos_session`,
HttpOnly, SameSite=Lax, path `/`, `max_age` 86400, and `Secure` when `COOKIE_SECURE=true`.
`session_user` joins `sessions` to `users` where the hash matches, `expires_at > now()` and `NOT
u.banned` — so banning is enforced on every request, not merely at login. There is **no session
rotation on privilege change** despite decision #35 saying there is; the code does not rotate.
**Expired sessions are never deleted** by any code path; the table grows.

**Trials expire lazily.** `session_user` calls `_expire_trial_if_lapsed` for any user on `retail` or
`pro`: if a `trialing` subscription has a `current_period_end` in the past, the user is downgraded to
`free` and the subscription is marked `canceled`, on read, with no cron required.

**Tokens.** `issue_token(conn, user_id, purpose, ttl_hours)` first invalidates any unused token of
the same purpose (so a second "reset my password" click does not leave the first link live), then
inserts a hashed token. `consume_token` redeems with a single `UPDATE … WHERE token_hash = ? AND
purpose = ? AND used_at IS NULL AND expires_at > now() RETURNING user_id`. The single-use guarantee
is that WHERE clause plus the RETURNING: two concurrent redemptions cannot both match. Verification
tokens live 24 hours, reset tokens one hour, and there is a per-address limit of five token requests
per hour. `complete_password_reset` refuses a weak password **before** spending the token, sets the
new hash, **deletes every session for that user**, and marks the email verified because a reset
proves control of the mailbox.

**Roles and permissions.** There are exactly four tiers on `users.tier`: `free`, `retail`, `pro`,
`admin`. There is no separate role table and no permission matrix. Two things derive from the tier.
First, `authn.delay_hours(tier)` returns 0 for retail/pro/admin and `FREE_DELAY_HOURS = 48`
otherwise, and `_effective_as_of` applies that as a **server-side SQL predicate**
(`WHERE as_of <= now() - make_interval(hours => %s)`), so no request parameter — not `as_of`, not an
id — can reach fresher data. Second, `billing.ENTITLEMENTS` maps each tier to seven capabilities:
`live_signals`, `max_follows`, `max_portfolios`, `max_trades`, `realtime_alerts`, `api` and
`exposure`. Free gets 5 follows, 1 portfolio, 50 trades, no realtime alerts, no API and no Exposure
surface. Retail gets 1,000/50/5,000 with alerts and Exposure but no API. Pro and admin get
100,000/1,000/100,000 with everything. **Two things are deliberately never gated at any tier**: the
Ledger and the marketing site's public endpoints, because "an accuracy record behind a paywall is
not an accuracy record."

**Admin.** Admin is a tier, not a flag, and it is gated behind TOTP at login — `authn.login` refuses
an admin whose `totp_secret` is NULL. It cannot be granted from the web: `admin.set_tier` restricts
targets to free/retail/pro and `TIER_TARGETS` does not include admin, so admin is provisioned only
by `cli seed-admin`, which prompts for a password and prints a TOTP secret. You cannot change your
own tier or ban yourself, and admins cannot be banned or retiered from the console.

**Protected routes.** There is no route-level decorator or dependency for authentication. Every
handler that needs a user calls `authn.session_user(conn, tos_session)` itself and branches. This is
repetitive but it has one real advantage the codebase exploits: authorization is expressed
**inside the SQL**, as `WHERE user_id = %s`, rather than as a filter applied to already-fetched
rows. `tests/test_authz_adversarial.py` verifies this adversarially rather than structurally: it
creates two real accounts through the real API, gives one of them private objects, and has the other
try seventeen different reads and writes — the trade, its world context, its AI analysis, its chart
image, editing it, deleting it, the similar-trade cohort, the portfolio, deleting the portfolio, the
watchlist, the journal report, the performance summary, all of those anonymously, five admin routes,
the four public endpoints and a forged session cookie. All seventeen are refused. These are the only
tests in the suite that touch a database, they skip cleanly when none is reachable, and they clean
up every row they create.

**Google OAuth.** `tradeos/oauth.py` implements the authorization-code flow with five properties it
documents explicitly: the `state` is one-time and server-side, consumed by deleting the row and
checking `rowcount`, because a signed cookie can be replayed and a row cannot be deleted twice;
identity is the provider's `sub`, never the email, because an address is mutable and a corporate
mailbox handed to a new employee would otherwise inherit the old employee's account; the email is
stored only as a record of what the provider asserted; `link_or_create` **refuses** when the email
belongs to a local password account with no existing link, rather than silently merging; and
`decode_id_token` reads the JWT claims **without verifying the signature**, which is acceptable only
because the token was just received over TLS directly from Google's token endpoint in a
server-to-server exchange authenticated with the client secret, never from the browser.
`validate_claims` checks issuer against a fixed set, audience against the client id, expiry with a
clock-skew allowance, and `email_verified`. **None of this has ever been run against Google.** The
docstring says so, `sources.py` says so, `docs/state.md` says so and `docs/progress/phase_9.md` lists
it first among what is not fixed. Treat it as untested auth code.

---

## 9. Every third-party service, API, SDK, webhook, cron job, queue, websocket and external feed

**There are no websockets and no message queue.** `email_outbox` is a table used as an outbox, not a
broker. There is no Celery, no RQ, no Kafka, no Redis. The only background execution is the
scheduler process.

**SEC EDGAR** — free, keyless, requires only `SEC_USER_AGENT` with a contact address. Wired through
`tradeos/ingestion/edgar_client.py`, which enforces an `ALLOWED_HOSTS` allowlist, HTTPS only, a hard
minimum interval well under the SEC's fair-access ceiling, exponential backoff on 429 and 5xx, and a
sha256 checksum of every response before storage. Consumed by `ingestion/runner.py` (Form 4),
`ingestion/schedule13.py` (13D/G), `ingestion/form13f.py` (13F), `ingestion/news_sec.py` (8-K) and
`resolution/tickers.py` (`company_tickers.json`). Powers the entire signal plane and the news
plane's primary-source half.

**GDELT DOC 2.0** — free, keyless, at `api.gdeltproject.org`. `tradeos/ingestion/gdelt.py` runs five
fixed topic queries (monetary_policy, conflict, supply_chain, energy, trade_policy) at a six-second
minimum interval, records every call in `source_calls`, and on a 429 stops the whole pass and backs
off for six hours, with the clock persisted in the database so a restart cannot reset it. The module
records a measured finding and a deliberate refusal: GDELT's throttle is keyed on the **User-Agent**,
not the IP, so rotating the UA would restore access, and the project deliberately does not, because
that is evasion of a rate limit on a free service. `tests/test_gdelt.py` asserts the module still
explains why.

**Public RSS/Atom** — eleven feeds, free and keyless, host-allowlisted in
`tradeos/ingestion/news_rss.py`: `federalreserve.gov` press releases, `sec.gov` press releases, three
CNBC feeds (Markets, Top News, International), two BBC feeds (Business, World), Guardian Business,
Al Jazeera, South China Morning Post Business, and the European Central Bank. Five countries — US,
GB, QA, HK and the EU — which the code notes is not decoration: the source-comparison view needs
outlets that can genuinely disagree, and two CNBC feeds agreeing is not two perspectives. The file
also records feeds that were tried and rejected: Reuters, DW, Nikkei and Arab News, as unreachable,
empty or 403.

**Bluesky** — free, keyless, `public.api.bsky.app`. `tradeos/ingestion/social_bluesky.py` reads a
**curated account list** rather than searching the network, because `app.bsky.feed.searchPosts`
returns 403 without authentication as of 2026-07-26 while `getAuthorFeed` and `getProfile` remain
keyless. Reposts are skipped, because an account amplifying someone else is not that account
speaking. `geo` is left empty on purpose, and a test enforces that on this source specifically.

**Nasdaq calendar** — free, keyless. `tradeos/ingestion/calendar_nasdaq.py` reads the earnings and
economic JSON endpoints, requiring a browser User-Agent because Nasdaq fingerprints non-browser
clients, and keeps only US market-moving macro events plus earnings for names already tracked.

**Wikipedia and Wikimedia** — free, keyless, two allowlisted hosts. `en.wikipedia.org` for search
(resolving a company to its canonical article, cached in `wiki_titles` including honest misses) and
`wikimedia.org` for the daily pageviews REST API. Measures attention, not mood, so it writes
`sentiment` as NULL.

**Hacker News via Algolia** — free, keyless, `hn.algolia.com`. `tradeos/ingestion/sentiment_hn.py`
counts exact-phrase mentions with `advancedSyntax=true`, which is the fix for bug B-02 where the
default fuzzy OR search made Algolia assert that Hacker News discusses a packaging company more than
it discusses Nvidia.

**CoinGecko** — free tier, keyless, `api.coingecko.com`. Two fixed queries only, never an open
proxy, behind a 60-second cache.

**Binance public derivatives** — free, keyless, `fapi.binance.com`. Four endpoints per tracked
symbol: `premiumIndex`, `fundingRate`, `openInterest` and `globalLongShortAccountRatio`. Cached for
300 seconds and kept warm by a scheduler job every 240 seconds specifically so the Crypto page never
pays for ~7 seconds of paced requests on a page load.

**Tiingo** — free tier, **needs `TIINGO_API_KEY`** (which is set in the live `.env`).
`tradeos/ingestion/prices.py` fetches the split/dividend-adjusted daily series and records
`source = 'tiingo:adjusted'`. This is how claim outcomes get scored, so it is load-bearing.

**OpenFIGI** — works keyless at a low rate limit, `OPENFIGI_API_KEY` raises it. **Not set.** This is
why 19,851 fund holdings have unresolved CUSIPs and are invisible to every surface.

**Reddit** — needs `REDDIT_CLIENT_ID` and `REDDIT_CLIENT_SECRET`. **Not set**, so
`social_reddit.ingest` is an honest no-op returning zero. The adapter uses the client-credentials
OAuth path at `oauth.reddit.com` rather than the public `.json` endpoints, because Reddit
Cloudflare-blocks those from datacenter addresses. This is the only connected-capable source that
would measure *mood* rather than attention.

**YouTube Data API** — needs `YOUTUBE_API_KEY`. **Not set.** There is no ingestion module for it at
all; it exists in `sources.py` and `config.py` as a declared-but-unbuilt source.

**X / Twitter** — permanently unavailable. `sources.py` carries a long entry explaining that the
free tier does not permit reading timelines, the paid tiers start well beyond free-tier scope, and
scraping breaks their terms and breaks constantly. The entry stays visible on the integration page
so the gap is stated rather than quietly dropped, and it now names Bluesky as what covers the need.

**StockTwits** — listed as `unavailable`: no free read tier, left disconnected rather than faked.

**The language model** — Google AI Studio (Gemini) and any OpenAI-compatible `/chat/completions`
endpoint, both wired through the single transport `tradeos/llm.py`. `EXPLAIN_PROVIDER` is a
comma-separated **chain** tried in order; the live `.env` runs `gemini,openai`. Two model roles are
configurable per provider: FAST for classification and extraction, DEEP for reasoning about
mechanism. Each provider has its own circuit breaker — a 429 or 503 after three attempts with
exponential backoff trips a 120-second cooldown on **that provider only**, and the chain falls
through to the next. Failures never raise; `complete()` returns `(None, reason)` where `reason` is
plain language, so a caller can tell the user whether it was a missing key, a quota trip, a safety
refusal or a truncation. Three domain-specific details are baked in with measurements attached:
`THINKING_HEADROOM = 2048` because Gemini's `maxOutputTokens` counts hidden reasoning against the
same budget (measured 769–1360 thinking tokens for one chart image); `thinkingConfig` is never sent
because every model newer than 2.5 rejects it with a 400; and the defaults are
`gemini-flash-latest` and `gemini-flash-lite-latest` because `gemini-2.0-flash` has a zero
free-tier allowance and the `gemini-2.5-*` models are closed to new keys. The Gemini URL is checked
against a hostname allowlist and the OpenAI base URL is required to be `https`.

**Stripe** — optional. `billing.provider_configured()` returns True only when `STRIPE_SECRET_KEY` is
set **and** the `stripe` SDK imports; the SDK is not in `requirements.txt`. Card data never touches
these servers: `create_checkout` builds a hosted Stripe Checkout session. **The webhook** is
`POST /api/billing/webhook`, verified with `stripe.Webhook.construct_event` against
`STRIPE_WEBHOOK_SECRET`, deduplicated on `provider_event_id`, and handling three event types:
`checkout.session.completed` (upgrade), `customer.subscription.deleted` and
`customer.subscription.paused` (downgrade to free). **Currently in test mode**, which means the
pricing UI is visible, `test-activate` self-serves an upgrade with no charge, and that route
disables itself the instant a real provider is configured.

**SMTP** — `tradeos/mail.py`. **Not configured.** Verification and reset emails cannot send.

**Sentry** — optional, activated only when `SENTRY_DSN` is set and the SDK is importable, with
`traces_sample_rate=0.0`. Not in requirements.

**Cron jobs.** There is exactly one intended cron line and it is **not installed**: the daily 03:15
UTC backup in `scripts/backup.sh`'s header comment. Everything else runs inside the scheduler
process, `python -m tradeos.cli scheduler`, which is `tradeos/scheduler.py`'s `run_forever` looping
on a 60-second tick, opening a fresh database connection each tick (resilient to blips), and running
every job whose interval has elapsed since its last **successful** run recorded in `job_runs` — so
the schedule survives a restart. Each job runs inside `run_job`, which records the attempt whether
it succeeds or fails, rolls back on exception, and passes the message through `redact()` first,
which strips every query string so an API key passed as a URL parameter cannot reach the database or
the logs. **The eighteen jobs, with intervals**: `news_rss` every 1800s, `news_sec` every 21600s,
`analyze_news` every 3600s, `sentiment_hn` every 21600s, `attention_wiki` every 86400s,
`social_reddit` every 3600s (a no-op until configured), `social_bluesky` every 3600s,
`earnings_cal` every 43200s, `economic_cal` every 43200s, `warm_brief` every 3600s, `gdelt` every
3600s, `spine_news` every 1800s, `interpret` every 3600s, `reinterpret` every 7200s, `radar_alerts`
every 900s, `measure_claims` every 21600s, and `crypto_structure` every 240s (just inside the
300-second cache TTL). **What is conspicuously absent**: the signal-plane jobs. `compute-signals`
and the EDGAR backfills are manual CLI operations, which is the root cause of bug B-08 — the
dashboard showed a three-day-old signal snapshot while the header said "live".

**The operations CLI** — `python -m tradeos.cli`, 39 commands. SEC ingestion: `ingest-form4`,
`ingest-13dg`, `ingest-13f` and the three `backfill-*` twins taking `--from`/`--to`. Resolution:
`sync-tickers`, `resolve-entities`, `resolve-cusips`. Signals: `signals-register`, `compute-signals`,
`run-backtest`, `calibration`. Other ingestion: `ingest-prices`, `ingest-short-interest`,
`ingest-sentiment`, `ingest-news`, `analyze-news`, `ingest-calendar`, `ingest-bluesky`. Spine and
claims: `spine`, `reprocess`, `interpret`, `measure-claims`, `ledger`, `import-signals`. Seeds:
`seed-admin`, `seed-demo`, `seed-watchlist`, `seed-exposure`, `sync-library`, `create-invites`.
Operations: `migrate`, `preflight`, `status`, `scheduler`, `generate-alerts`, `capture-context`,
`check-source`. The last one is the most useful and the newest: it makes a **real** call to one
source and reports plainly whether it worked, which is the question that `status` (what has been
ingested) and `preflight` (what is configured) both leave unanswered right after someone pastes a
key in. It never echoes the credential. `cli.py` also pins the `httpx` and `httpcore` loggers to
WARNING, because `logging.basicConfig(level=INFO)` plus httpx's habit of logging the full request
URL put a Tiingo token in plain text on a terminal during a manual backfill.

---

## 10. All trading, market and financial logic

**Point-in-time discipline is the load-bearing invariant.** Every filing-derived row carries two
times: `event_time` (when it happened) and `knowable_time` (when it became public, taken from the
EDGAR submission header's `ACCEPTANCE-DATETIME` in US/Eastern). Every signal computation and every
backtest query filters on `knowable_time` only. For 13F the gap is up to 45 days and, as migration
002 puts it, "the gap IS the story". `README.md` says of this: "Do not break it."

**The convergence signal** (`tradeos/signals/convergence.py`, currently definition v4 after a
no-behaviour-change re-registration). It fires when many *independent* smart-money voices cluster on
one issuer inside a rolling **90-day window**. Every constant lives in `DEFAULT_PARAMS`, which is
stored in the database alongside a sha256 of the module. Base weights: an open-market insider
purchase (transaction code `P`, acquired `A`) scores **1.0**; an insider **sale scores 0.0** and is
kept as context only, by decision #21, because sales are noisy — tax, diversification, 10b5-1 — and
would flood the bullish signal an attacker could hide in; a new activist stake (`SCHEDULE 13D`)
scores 1.2; an activist amendment 0.8; a passive >5% stake (13G) 0.6; a 13F holding 0.4 but **only**
when it is a genuine quarter-over-quarter new or increased position, which requires a prior quarter
to establish and is dormant otherwise (decision #22).

Magnitude scaling is explicit: for an insider purchase, `min(1.5, log10(1 + trade_value_usd) / 6.0)`;
for a stake, `min(1.5, percent_owned / 10.0)` — which in practice always returns 1.0 because
`percent_owned` is always NULL; for a 13F holding, `min(1.2, log10(1 + value_usd) / 8.0)`. An
unknown magnitude is neutral at 1.0, never amplified and never zeroed.

Freshness decay is exponential with per-class half-lives: **14 days** for insider events, **30 days**
for stakes, **60 days** for holdings, applied as `0.5 ** (age_days / half_life)`.

**Independence collapse** is the anti-echo mechanism and the most interesting piece of the formula:
events are grouped by `voice_key` (`insider:<cik>` or `filer:<entity_id>`), and each voice
contributes its **strongest** event at full weight plus **25%** of every additional event it filed.
A single actor filing twenty times cannot manufacture a score.

The **publish gate** requires at least **three distinct voices** across at least **two different
source classes**. This is the constraint that makes a partial backfill look identical to a broken
signal: backfilling Form 4 alone over June 2023 produced 79 candidates and zero clusters, not
because anything was wrong but because 13D/G history did not cover the same window.

The **liquidity floor** (decision #38, v3) is a 90-day median dollar volume above **$2,000,000**,
computed point-in-time from `prices_eod` on or before `as_of`. No price history means below the
floor. A sub-floor issuer does **not publish at all**, superseding the earlier interim floor of mere
exchange listing. The reasoning is measured: the illiquid micro-caps were the performance drag
(liquid names 44% hit and +0.8% mean excess versus illiquid 38% and −2.0%), so the honest fix was to
filter rather than to re-cut thresholds to fit a small band.

Bucket thresholds: raw score below 3.0 is `low`, 3.0 to 6.0 inclusive is `medium`, above 6.0 is
`high`. `presentation.smart_money_score` re-expresses that as 0–100 pinned to the same edges — raw 3
maps to 50, raw 6 maps to 75, and above that it approaches 100 asymptotically. That transform is
**display only** and lives in a different module specifically so `convergence.py` stays hash-locked.

**The backtest** (`tradeos/backtest/engine.py`). Entry is the close of the first trading day
**strictly after** the cluster's `as_of`; exit is the close of the first trading day on or after
entry plus the horizon in calendar days. Horizons are 30, 90 and 180 days. The metric is excess
return versus **SPY** over the same window, and a hit is a positive excess. Consecutive daily
clusters on one issuer with no gap greater than **14 days** collapse into one **episode**, entered
once at its earliest day (decision #26) — without that, daily recomputation would count one ongoing
situation dozens of times and inflate both n and the hit rate. A bucket reports "insufficient
sample" below **30 resolved episodes** and never a bare rate. `wilson_interval` gives a 95% Wilson
score interval, chosen because it is honest for small n.

**The Ledger** (`tradeos/ledger.py`) applies the same discipline to claims. `NOISE_FLOOR = 0.02`: a
claim that said "up" and produced +0.3% excess is recorded as **inconclusive**, not a hit, because it
did not move enough to be evidence either way. A claim about a currency or a region has no price
series and is recorded as **unscoreable** rather than quietly dropped, because silently excluding
those would let the hit rate be computed over a self-selected sample. Only `kind == "asset"`
subjects are priced. `verdict_for` is pure. `measure_claim` is idempotent — re-running replaces the
rows — and refuses to score a claim whose horizon has not elapsed.

Three statistical functions were added after the marketing site published a point estimate with no
interval and invited the wrong conclusion. `mean_ci(values, z=1.96)` returns the mean with a
confidence interval and a `significant` flag that is **False whenever the interval spans zero**.
`proportion_z(successes, n, p0=0.5)` reports how many standard errors a hit rate sits from a coin
flip. `sample_needed(sd, edge, z=1.96)` returns how many resolved calls it would take to detect a
given per-call edge at the measured dispersion — the number that turns "not enough data" from an
excuse into a plan. All three are pure and unit-tested offline.

**The assumptions baked in, stated plainly.** Excess versus SPY only — no sector adjustment, which
decision #12 defers to v2 on the grounds that sector models add researcher degrees of freedom before
launch. Close-to-close only — no intraday, no slippage, no commission, no borrow cost for the short
side, all disclosed on the methodology page. Adjusted prices, so splits and dividends are handled.
The 14-day episode gap and the $2M liquidity floor are judgment parameters, disclosed and tunable.
The 2% noise floor is a judgment parameter. The confidence buckets `(0, 0.4)`, `(0.4, 0.7)`,
`(0.7, 1.0]` for claims are a judgment parameter. Prices come from a free Tiingo tier and are
labelled demo-grade on the methodology page.

**Refresh intervals.** News every 30 minutes, 8-K every 6 hours, GDELT and Bluesky hourly, Wikipedia
daily, HN every 6 hours, calendars twice daily, crypto structure every 4 minutes, claim measurement
every 6 hours, interpretation hourly, re-interpretation every 2 hours, subscription delivery every
15 minutes. **Signal computation and EDGAR backfill: manual only.**

**The impact engine's economics** (`tradeos/claims.py`). `interpret_recent` is bounded to 8 clusters
per run above a 0.4 novelty floor within a 6-hour window, ordered by novelty descending;
`reinterpret_developing` is bounded harder, to 3 or 4, and only fires when a cluster has gained at
least one new source since its last reading. The reason is economic: inference is the scarcest
resource, and a revision costs the same quota as a new claim while there are always more new events
than developing ones. The prompt reads the **whole cluster**, not the single canonical event,
because a measured RSS summary averages 125 characters and an 8-K description 66 — asking a model
for a specific causal mechanism from a headline and one sentence is asking it to invent one.

**The mechanism validator** is the most important piece of financial-logic validation in the
codebase. `mechanism_is_specific` requires at least 80 characters, rejects prose matching
`^(this|it|that) (is|will be|should be|looks) (bullish|bearish|positive|negative|good|bad)`, and
requires at least one of 27 causal markers (`because`, `which`, `forces`, `tightens`, `passes
through`, `knock-on`, `in turn`, `exposed to`, and so on). Its docstring states the stakes: "A
product whose 'mechanism' field says 'this is bullish for oil' is a headline aggregator wearing a
costume." A claim naming more than six affected items is truncated, because "a claim naming
everything commits to nothing."

**The impact engine has no template fallback, deliberately.** Every other AI path in this codebase
degrades to deterministic output. This one writes nothing at all on failure, because a fabricated
claim inside a ledger built to measure honesty would poison the only thing that makes the product
defensible.

**Contradiction linking.** After a claim is written, `link_contradictions` finds live claims from
the last seven days pointing the **opposite** way on the same named subject and records the
disagreement in both directions. Two live interpretations disagreeing, with the reader able to read
both, is more honest than smoothing them into one confident narrative.

**Personal relevance** (`tradeos/relevance.py`) is a weighted sum of seven parts summing to 1.0:
confidence 0.20, watchlist overlap 0.22, geography 0.20, commodity centrality 0.14, currency 0.08,
novelty 0.10 and authority 0.06. Authority is deliberately smallest — who said something is evidence
about it, not a substitute for what it says — and a claim with no named author scores the neutral
0.5 rather than being penalised for lacking a byline. `geo_weight` gives 1.0 for your own country,
0.75 decaying by 0.07 per rank for a trade partner (ranked **within each list separately**, because
concatenating exports and imports once offset every import partner by the length of the export list
and scored a country's largest supplier as if it were its sixth-largest customer), 0.4 for an
unplaced event with no profile, and 0.3 otherwise. `currency_weight` gives 1.0 for your own currency
and **0.9 for a currency yours is pegged to**, which is the second-order link a US-centric feed
silently drops. `commodity_weight` scores by position in the reader's own `key_exports` and
`key_imports`, with producing beating buying (base 1.0 versus 0.85) and rank decaying 0.18 per
position to a floor of 0.25 — so crude oil, the UAE's first export and Brazil's third behind
soybeans and iron ore, correctly weighs more in one than the other.

**The Journal's world context** (`tradeos/journal_context.py`) is the most conceptually original
piece of financial logic here. At the moment a trade is logged it freezes the Radar as it stood —
which interpretations were live, ranked by that reader's own relevance, and whether any of them named
the same instrument pointing which way (`alignment` is `with`, `against`, `mixed` or `none`). That
turns the coach from an outcome scorer into a **process** observer: it can say "eleven of your
entries were made while a live interpretation on that name pointed the other way" long before enough
closed trades exist to say anything about whether the trader is any good. Three lines it holds: the
snapshot is written once and never rewritten (`ON CONFLICT DO NOTHING`, not `DO UPDATE`); the system
is **not** the benchmark, so every pattern mentioning disagreement carries the Ledger's own real hit
rate beside it; and patterns are stated only above a sample floor of five, phrased as observations
with their sample size attached, never as verdicts, with `tone` never negative.

**Crypto positioning** (`tradeos/crypto_intel.py`) reads funding rate, funding trend, open interest
and the global long/short account ratio into a falsifiable reading, with thresholds `LEANING_PCT`,
`CROWDED_PCT`, `EXTREME_PCT`, `CROWDED_LONG_SHARE` and `CROWDED_SHORT_SHARE`. Funding is reported
**annualised**, because 0.01% per eight-hour period sounds like nothing and is about 11% a year to
hold the position. Every reading carries an invalidation condition, and `read_positioning` returns
`None` rather than manufacturing one when the inputs are too thin.

---

## 11. All business logic and rules

**Pricing.** Three plans in `billing.PLANS`: Free at $0 mapping to tier `free`; **Trader** at $29
mapping to tier `retail` with price id from `STRIPE_PRICE_RETAIL`; **Pro** at $99 mapping to tier
`pro` with price id from `STRIPE_PRICE_PRO`. The currency is never stated in code; the frontend
renders a bare number.

**The current commercial mode is "free launch".** Because `STRIPE_SECRET_KEY` is unset,
`provider_configured()` is False, which has three simultaneous effects: `create_checkout` returns
`{"mode": "test", "plan": …}` instead of a Stripe URL; `test_activate` is **enabled**, so any
logged-in user can self-serve an upgrade to any tier with no charge; and `authn.register` upgrades
every non-referred new signup straight to `pro`. So today, in practice, **everyone is Pro and nobody
pays**, while the pricing page remains visible. All three revert automatically the moment the key is
set — a genuinely elegant piece of design, and also a real hole if the app were exposed publicly in
this state, because `test-activate` is a free-upgrade endpoint.

**Usage limits, enforced server-side in the write path.** Free: 5 follows, 1 portfolio, 50 journal
trades. Retail: 1,000 follows, 50 portfolios, 5,000 trades. Pro and admin: 100,000 follows, 1,000
portfolios, 100,000 trades. Each is checked with a `SELECT count(*)` before the insert, and exceeding
it returns 403 with a plain message and `{"upgrade": true}`.

**Feature gating.** `live_signals` is not a boolean check anywhere — it is realised as the 48-hour
delay applied as a SQL predicate. `realtime_alerts` gates the alert engine's tier awareness. `api`
gates key creation and the `/api/v1` endpoint. `exposure` is the one gate checked in a **read** path
rather than a write path, because Exposure is a view rather than a thing you accumulate; a free user
gets `{locked: true, what: "…", upgrade: true}` explaining in words what the surface would show,
which the code justifies as "a locked feature that does not explain itself is indistinguishable from
a broken one."

**Referrals.** Every user gets a reusable `referral_code` on demand. Signing up with someone's
referral code is accepted as a valid invite, links `referred_by`, and grants the **new** user a
14-day Pro trial that expires lazily on read. The referrer gets nothing except a count.

**Saved filters.** Maximum 20 per user. Throttle floored at 60 minutes and defaulting to 360.
Subscriptions are off by default, because a saved filter is a view and turning a view into email is
a separate decision the user makes deliberately. A batch that matched nothing is **not sent** — an
alert saying "no news" is exactly the noise the throttle exists to prevent — but the high-water mark
still advances so the next run does not re-examine the same claims. If a send **fails**, the mark
does not advance, so a transient outage retries next tick; `last_sent_at` moves either way, which is
what stops it becoming a hot loop.

**The SSRF rule for webhooks** is worth stating as business logic because it is the sharpest thing
in the file. The user supplies a URL and the server fetches it. `radar.webhook_target_ok` requires
`https` (http would also send the payload in the clear), requires a hostname, refuses a port in
{22, 23, 25, 445, 3306, 5432, 6379, 9200, 11211, 27017}, resolves the name with
`socket.getaddrinfo`, and refuses if **any** resolved address is private, loopback, link-local,
reserved, multicast or unspecified — every address, not just the first, because a name resolving to
one public and one private address would otherwise pass and then connect wherever the client picked.
It is re-checked **at send time**, not only at save time, because DNS can change in between, which is
a rebinding attack. Redirects are refused for the same reason: a 302 to 169.254.169.254 would walk
straight past the check that just passed.

**Content moderation.** A trade or comment is auto-hidden at `community.REPORTS_TO_HIDE` distinct
**unresolved** reports; a dismissal resets the counter, because migration 017 made resolution
non-destructive. One report per user per target. Handles must match `^[a-z0-9_]{3,20}$` and are
checked against a reserved list to prevent staff impersonation. A comment is deletable by its
author, the trade owner or an admin.

**The leaderboard rule.** `community.trader_leaderboard` ranks by **honest win rate over public
closed trades** above `LEADERBOARD_MIN_CLOSED`, never by a raw return figure, and shows **nobody at
all** below the floor rather than ranking someone on four trades. Both rules are printed on the
surface. The reasoning is anti-abuse: a return leaderboard invites fabrication and pumping.

**Small-sample honesty, applied uniformly.** Personal performance reports counts only below ten
closed trades and a per-strategy rate only above eight. The Ledger reports `sufficient: false` below
twenty scoreable outcomes. Backtest buckets read "insufficient sample" below thirty episodes.
Behavioural patterns need five trades with context, and a cohort contrast needs five closed trades
**per side**. Every one of these floors is a named constant.

**The advice line, enforced mechanically.** `explain/guards.py` contains two guards every piece of
model prose must clear. `directive_guard` is a regular expression banning second-person imperatives
("you should/could/ought/might want/need/must"), first-person recommendations ("I/we/they/analysts
recommend/suggest/advise"), rating vocabulary ("strong buy", "overweight", "outperform"), issuance
of a price target ("price target of $190", "raised its price target") — but **not** mere reference to
a target price, a narrowing that was required because the chart coach's prompt asks the model to
discuss risk/reward against the user's own recorded levels and the original rule made it discard
correct readings and then blame a missing provider. `numbers_guard` requires every numeric token in
the output to trace to a value in the input payload, with formatting tolerance for integers, one and
two decimal places and percent forms of a fraction, plus a pass for anything matching a plausible
year. `base_rate_integrity_guard` additionally requires any stated hit-rate percentage to match the
backtest record exactly, and forbids stating one at all when the sample is insufficient.
`intelligence/analyst.py` adds `citation_guard`, blocking the model from smuggling in a different
company via a cashtag or exchange-qualified mention. A guard trip discards the model output and
renders the deterministic template — except in `vision.py`, where guarding is **field-level** so one
tripped sentence drops that field rather than four good ones.

**Data licensing posture.** Only primary sources, no aggregators (decision #5). Article bodies are
never republished — only a headline, a short source-provided summary, the link, the source and the
time. FINRA short interest is stored as derived changes, never a raw-file mirror. Stooq was rejected
outright (decision #27) because its free CSV endpoint sits behind a JavaScript proof-of-work
anti-bot challenge and fetching it would require circumventing that.

**The staff-trading seed.** When an admin reads a cluster that is not yet public to the free tier,
`authn.audit` writes a `prepub_access` row naming the symbol and the `as_of`. `docs/staff-trading-policy.md`
is the accompanying document.

---

## 12. The design system

There are two deliberately different visual languages sharing one set of measurements.

**Shared: `shared/tokens.css`.** Two font stacks. A nine-step type scale — 11, 12.5, 13.5, 15, 18,
22, 27, 34 and 44 pixels — with fixed pixel values rather than rems, so it does not respond to the
browser's root font size. An eight-step spacing scale on a 4/8 base: 4, 8, 12, 16, 24, 32, 48, 64.
Four radii: 8, 12, 16 and 22. Motion: two easing curves, `cubic-bezier(0.22, 0.68, 0.15, 1)` for
general transitions and `cubic-bezier(0.16, 1, 0.3, 1)` for entrances, and three durations of
0.16s, 0.28s and 0.5s. And one centralised reduced-motion rule that collapses durations to 0.001ms
rather than disabling animations, so an element is never stranded invisible at frame zero.

**The app: "Midnight Terminal, alive".** A cool blue-violet near-black rather than a flat terminal
grey, built as seven layered surfaces from `--bg: #05060c` through `--bg-2`, `--panel`, `--panel-2`,
`--card`, `--card-2` to `--elev: #191d2b`, with two border weights and a `--hairline` of
`rgba(255,255,255,0.06)`. Text is `#eaecf4`, muted `#8b93ab`, faint `#7b83a0`. The single accent is
indigo `#6e8cff` with a violet companion `#a98bff`, and cyan `#52dcff` is **reserved for "live" data
pulses only**. Semantic colours are green `#2fe3a0`, amber `#ffc25c` and red `#ff6b81`, each with a
14%-alpha soft variant. Four gradients are defined. Elevation is soft, wide, negative-spread shadows
rather than hard drop shadows, plus a `--glow` and a `--ring` for focus.

The contrast work is documented in the token itself, which is unusual and good: `--faint` measures
5.4:1 on `--bg`, 5.1:1 on `--panel` and 4.7:1 on `--card`, all clearing the 4.5:1 AA floor, with the
one exception being 4.47:1 on `--elev`, the transient row-hover background only — and the comment
explains that it was not raised further because the next step up collides with `--muted` and
collapses the type hierarchy, trading a real distinction for a rounding difference in a hover state.
That trade-off is written down rather than left to be rediscovered.

Layout is a fixed 244px sidebar plus a 62px glassy top bar over a fluid main column. The sidebar
groups navigation into four labelled sections — Overview, Intelligence, Your desk, People — plus a
collapsible "More" and a conditional Admin section, with the active item marked by a gradient
background and a 3px gradient bar bleeding off its left edge. There is a ⌘K/Ctrl-K command palette
with keyboard navigation, grouped results and a footer hint bar. There is a slow "aurora" — two
blurred radial gradients drifting on a 26-second alternating animation behind everything, fixed and
pointer-transparent so it costs nothing in interaction, and disabled entirely under reduced motion.
Focus rings, selection colour and scrollbars are all styled globally.

Responsiveness is handled by a marked block at the **end** of `styles.css` labelled "NARROW SCREENS
— must stay LAST". The reason is written into the file: a media query adds no specificity, so a
narrow-screen rule placed earlier loses to a base rule further down on source order alone — a trap
the project fell into once. Below 720px the search field is replaced by a search **button** rather
than hidden, because there is no ⌘K on a phone and hiding the field outright would remove search
entirely. Two systemic fixes appear throughout: every grid and flex track that needs to shrink is
written `minmax(0, 1fr)` rather than `1fr`, because a bare `1fr` is `min-width: auto` and refuses to
shrink below its content; and `.content` sets `overflow-wrap: anywhere`, chosen over `break-word`
because only `anywhere` also shrinks the container's min-content, which is the half that actually
stops the overflow. That rule exists because one ingested news item whose title was a raw
`drive.google.com` link widened its container past the viewport — ingested text is arbitrary by
definition, so it is handled at the root rather than by guessing which card can receive a URL.
`docs/progress/cross_check.md` records the verification: 21 surfaces at 375, 768 and 1280 pixels,
zero horizontal overflow.

**The marketing site: a nautical chart.** Its palette is derived from the product's own subject
matter and its own name, and the reasoning is written at the top of `site/src/styles.css` and again
in `site/README.md`. Three defaults are ruled out **by name** — cream with a serif display and a
terracotta accent, near-black with one acid accent, and the broadsheet grid of hairline rules — on
the grounds that they show up regardless of subject. The field is deep ocean ink `#05090c` with a
green undertone, described as chart paper under a night light rather than a terminal. Text is warm
chart buff `#e9e3d6`, never pure white, with `--paper-dim` and `--paper-faint` at a measured 5.0:1.
The accent pair is taken from **real Admiralty chart printing**: magenta `#e8368f`, the overprint
colour used on nautical charts for lights, radio beacons and traffic separation schemes, and
verdigris `#45b5a0`, the patina of oxidised marine instruments and the shallow-water tint. They are
mapped to opposite ends of one idea and that mapping holds across the entire page — **magenta for
what the system claims, verdigris for what actually happened** — so the colour carries information
rather than decorating. Misses get their own colour, `--miss: #d9634a`, because they are shown first
on purpose and deserve a real colour rather than an alarm one.

Type on the site is three self-hosted families: Instrument Serif at one weight for display, used
only at section heads with tightened tracking at display sizes; Inter Variable for body; and IBM Plex
Mono with tabular figures for **every** figure, ticker, timestamp and source, because a number set
in the body face reads as prose while the same number in mono reads as a measurement. Headings use
`clamp()` — h1 from 3rem to 6.5rem, h2 from 2.1 to 3.6, h3 from 1.3 to 1.75. Body text is capped at
a 68-character measure. The gutter is `clamp(20px, 5vw, 72px)` and the content width 1180px.

**The signature element** is `site/src/rose.jsx`: a 32-point portolan wind rose whose rhumb lines
run out past every edge of the hero. A rhumb line is a real navigational object — a course that
crosses every meridian at a constant angle — and it is literally what the product is named after.
Line weight and opacity vary by wind order (principal 0.9/0.5, half 0.55/0.3, quarter 0.35/0.17),
because reproducing that hierarchy is what separates a wind rose from a bicycle wheel. It is inline
SVG, a few hundred bytes of geometry, scaling to any viewport with no second asset request.
Everything else on the page is deliberately quiet, on the stated principle that boldness spent in
more than one place is noise.

**Animation** is the most technically considered part of the design. The brief offered GSAP
ScrollTrigger with Lenis, or Framer Motion, and then set a first-contentful-paint target of 1.5s two
paragraphs later; the site takes neither, and `site/src/scroll.js` explains why in full. Where the
browser supports `animation-timeline: view()` the entire parallax runs on the compositor as pure CSS
and never touches the main thread; everywhere else, **one** passive listener writes two custom
properties on `<html>` once per frame and the same CSS reads them — one listener for the page, not
one per element. Everything animated is transform or opacity only. Scroll reveals are twenty lines
of IntersectionObserver with `once: true`, because re-animating on the way back up is what makes
scroll effects read as cheap. Smooth-scroll hijacking is deliberately **not** done, on the grounds
that it takes scrolling away from the operating system, breaks trackpad and keyboard feel, and
fights assistive tooling. Three depth layers move in the hero — the graticule furthest back, the rose
mid, the content in front — and a live compass bearing in the nav sweeps N 000° to NNE 060°, driven
by the same page progress as the rose and verified in a browser to agree with it to within 0.05°.
Every animation rule sits inside `prefers-reduced-motion: no-preference`, verified structurally
rather than by eye, which matters because scroll-driven animations ignore the duration override in
`shared/tokens.css` and would otherwise have survived it.

**Overall visual character.** The app reads as a calm dark instrument — layered near-blacks, one
confident indigo, generous spacing, tabular figures everywhere, restraint in colour. The site reads
as a night-lit nautical chart — deep ink, warm paper, two uncommon accents carrying meaning, one
large serif, and one bold drawn object. Neither looks like a default SaaS template, and both are
argued for in writing rather than asserted.

---

## 13. Every dependency, what it is used for, and what is unused

**Python, all ten lines of `requirements.txt`, every one genuinely used.** `fastapi==0.139.2` is the
app framework, imported in `tradeos/app.py` for the app object, `Request`, `Response`, `Cookie`,
`BackgroundTasks` and the response classes. `starlette==1.3.1` is pinned explicitly rather than left
to FastAPI's resolver, and is imported directly for `StarletteHTTPException` in the SPA fallback and
for `StaticFiles`. `uvicorn==0.35.0` is the ASGI server, invoked from the Dockerfile CMD and the
compose commands, never imported. `httpx==0.28.1` is every outbound HTTP call — `llm.py` and all
eleven ingestion adapters. `psycopg[binary]==3.2.9` is the database driver, imported in `db.py`,
`authn.py`, and everywhere `psycopg.sql` or `psycopg.types.json.Json` is needed.
`defusedxml==0.7.1` provides `fromstring` for Form 4 ownership documents, 13F information tables and
RSS/Atom feeds. `argon2-cffi==23.1.0` provides `PasswordHasher` and `VerifyMismatchError` in
`authn.py`. `pyotp==2.9.0` provides `TOTP` and `random_base32` for admin MFA.
`Pillow==12.3.0` is imported **lazily inside `_store_image`** in `app.py` and inside
`intelligence/vision.py`, for upload re-encoding. `pytest==9.0.3` runs the suite. **Nothing in
`requirements.txt` is unused.** `docs/dead_code.md` verified this independently and called it
"unusually clean and worth preserving."

**Two optional Python packages are referenced but not declared.** `sentry_sdk` is imported inside a
`try` in `app.py` guarded on `SENTRY_DSN`, and logs a warning if the DSN is set but the package is
missing. `stripe` is imported lazily inside four `billing.py` functions, and
`provider_configured()` returns False if the import fails. Both are deliberate: neither adds a hard
dependency to the demo image. Whether that is the right call for `stripe` is arguable — a production
deployment that sets `STRIPE_SECRET_KEY` without also installing the SDK will silently stay in test
mode with no error, and `_ops_config()` will report `stripe.enabled: false`, which is technically
honest but could be misread as "the key is wrong".

**Frontend — `frontend/package.json`, four runtime and two dev dependencies.** `react@18.3.1` and
`react-dom@18.3.1` are used everywhere. `react-globe.gl@^2.38.0` (resolved 2.38.0) is imported by
exactly one file, `frontend/src/globe3d.jsx`, which is itself only reachable through `React.lazy`.
`three@^0.185.1` (resolved 0.185.1) is imported by that same file for exactly one symbol,
`MeshPhongMaterial`. It is declared as a **direct** dependency rather than relied on as
react-globe.gl's peer, and the reason is recorded in `docs/progress/cross_check.md`: the
`globeMaterial` prop takes a `THREE.Material` **instance**, and passing a plain `{ color }` object
is silently ignored, which is part of why the globe rendered as an invisible black sphere. Dev
dependencies `@vitejs/plugin-react@4.3.3` and `vite@5.4.21` are the build. **Nothing is unused.**
Note the cost profile: four declared dependencies pull 83 top-level packages into
`frontend/node_modules` (176MB), essentially all of it the d3 and three.js graph behind
react-globe.gl, and the resulting `globe3d` chunk is 2,075,064 bytes — larger than the rest of the
app bundle combined. The lazy-load boundary is therefore not a nicety; it is the only thing keeping
first paint reasonable.

**Marketing site — `site/package.json`, five runtime and two dev dependencies.** `react@18.3.1` and
`react-dom@18.3.1`; `@fontsource/instrument-serif@5.3.0`, `@fontsource-variable/inter@5.3.0` and
`@fontsource/ibm-plex-mono@5.3.0`, all three imported in `site/src/main.jsx` and all three used in
`styles.css`. Dev: `@vitejs/plugin-react@4.3.3` and `vite@5.4.21`. **Nothing is unused.** The site's
README lists what was deliberately *not* taken and why: no GSAP, no Lenis, no Framer Motion — a
marketing page whose first paint waits on an animation library fails the performance target set two
paragraphs later in the same brief — and no `react-globe.gl`, replaced by an 84-line SVG plate that
is both lighter and, as the README argues, more honest, because exactly ten countries have
hand-checked exposure figures and a globe you can spin implies you can pick any of them.

**One installed-but-stale artefact.** The local `.venv/` contains `pillow-10.4.0.dist-info` while
`requirements.txt` pins 12.3.0. The virtualenv has not been re-synced since the Phase 9 security
upgrade. This has no effect on the container, which installs from `requirements.txt`, but it means
any test run from the local venv exercises the version with the two known PSD-decoder CVEs.

**One dependency that is not a package.** `frontend/src/world-110m.geo.json` is vendored Natural
Earth 110m country geometry, public domain, stripped to `iso` + `name` + coordinates and rounded to
two decimal places to bring 488KB down to 163KB. It rides inside the lazy globe chunk.

---

## 14. Build, deployment, environment and infrastructure

**Local development.** `make dev` brings up `docker-compose.yml` plus `docker-compose.dev.yml`.
Python reloads in place because `./tradeos` is bind-mounted and uvicorn runs `--reload`. `./tests` is
mounted because it is deliberately not in the image. `./frontend/dist` and `./site/dist` are mounted
read-only over `tradeos/static` and `tradeos/site_static`, shadowing whatever the image baked in, so
a UI change needs only `make web` (about 0.3 seconds) rather than a full image rebuild.
`DEV_ORIGINS` is set so the Vite dev servers on 5173 and 5174 pass the CSRF origin check. Without
`make dev`, the bundle is baked in at build time and any UI change costs a full
`docker compose up -d --build`, which `README.md` calls "the single biggest time sink in this repo".

**Testing.** `make test` runs `docker compose run --rm -T` with `tests/` and `tradeos/` bind-mounted
and `python -m pytest tests/ -q`. The mount is required, not optional — bug B-06 was exactly this,
`ERROR: file or directory not found: tests/`, because the Dockerfile never copies them. The fix was
to mount rather than to copy, on the stated principle that test files have no business in a
production artifact.

**Linting.** `make lint` and `make fix` run a throwaway root-user container that pip-installs ruff
and runs it over `tradeos tests`. Ruff is not in `requirements.txt` and is not in the image.

**Building the front ends.** `make web` runs `npm run build` in `frontend/`; `make site` does the
same in `site/`. Both need `npm install` once. The site's Vite config splits vendor from app into
two chunks and no more, because "the site is read top-to-bottom in one sitting; splitting it into a
dozen chunks would trade a smaller first parse for a stack of round trips."

**The production image.** Two stages, described in section 3. Notable properties: pip is upgraded
before installing requirements (build-time only, but a known-vulnerable tool in the image makes
every future audit noisy enough to stop being read); the app runs as a non-root user with uid 10001;
`tests/` is excluded; and the stage-one workdir mirrors the repository layout rather than
flattening, because flattening breaks the `../../shared/tokens.css` import — a bug that made the
production image **unbuildable for two full phases** while every local check stayed green, found by
accident in Phase 9.

**Production topology.** `docker-compose.prod.yml`: `db` with `restart: always`, a healthcheck and
**no published ports**; `api` with `restart: always`, two uvicorn workers, `--proxy-headers
--forwarded-allow-ips "*"`, `COOKIE_SECURE: "true"` hardcoded, and **no published ports**; `worker`
running the scheduler; and `caddy` binding 80 and 443 as the only internet-facing service. Four
named volumes: `pgdata`, `uploads`, `caddy_data`, `caddy_config`. Caddy provisions and renews a
Let's Encrypt certificate automatically for `$DOMAIN`, and `DOMAIN=:80` is documented as the
no-domain plain-HTTP escape hatch. Note the interaction between `--forwarded-allow-ips "*"` and
`ratelimit.client_key`, which reads `X-Forwarded-For`: that is only trustworthy while the app is
reachable *exclusively* through Caddy, which is how the compose file is written, and Phase 9 lists
it as a known gap rather than assuming it.

**Environment variables, every one, with what it is for.** Required: `SEC_USER_AGENT` (a contact
address the SEC's fair-access policy demands; the app refuses to start without an `@` in it) and
`DATABASE_URL` (the Postgres DSN; `ConfigError` if unset). Language model: `EXPLAIN_PROVIDER` (a
comma-separated fallback chain of `gemini`, `openai` and `template`), `GEMINI_API_KEY`,
`GEMINI_MODEL`, `GEMINI_MODEL_FAST`, `OPENAI_BASE_URL`, `OPENAI_API_KEY`, `OPENAI_MODEL`,
`OPENAI_MODEL_FAST`. Data sources: `TIINGO_API_KEY` (end-of-day prices, which is how claim outcomes
get scored), `REDDIT_CLIENT_ID` and `REDDIT_CLIENT_SECRET` (discussion volume and sentiment),
`YOUTUBE_API_KEY` (declared, no ingestion module), `OPENFIGI_API_KEY` (CUSIP→ticker; works keyless
at a low rate limit). Sign-in: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`. Email: `SMTP_HOST`,
`SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `MAIL_FROM`, and `MAIL_DEV_ECHO` (development only —
writes unsendable links to the server log, which preflight treats as a production **problem**).
Runtime: `PUBLIC_BASE_URL` (used to build the OAuth redirect URI, so it must match what Google has
registered), `BRAND_NAME` (the display name, defaulting to "Rhumb"), `COOKIE_SECURE` (Secure cookies
plus HSTS), `UPLOADS_DIR`, `DEV_ORIGINS`, `SENTRY_DSN`, and the undocumented `ENABLE_SHORT_INTEREST`
(read by `config.short_interest_enabled()`, deliberately parked). Seeding: `TRADEOS_ADMIN_PASSWORD`,
`TRADEOS_DEMO_EMAIL`, `TRADEOS_DEMO_PASSWORD`. Billing: `STRIPE_SECRET_KEY`,
`STRIPE_WEBHOOK_SECRET`, `STRIPE_PRICE_RETAIL`, `STRIPE_PRICE_PRO`. Production database:
`POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `DOMAIN`.

**Configuration validation.** `cli preflight` checks production readiness and, per `README.md`,
"checks every link in the `EXPLAIN_PROVIDER` chain". It once rejected `openai` — a provider the app
was actually running on — while advertising `anthropic`, which was never implemented; that was bug
B-05, "the most dangerous category of stale code: a check that is confidently wrong", and it has
been fixed.

**CI.** Described in section 3. Two jobs. **Gaps**: the marketing site is never built by CI; there
is no `pip-audit` or `npm audit` on a schedule (Phase 9 lists this explicitly — "dependencies are
clean as of today only. The audit is a snapshot"); and there is no deployment step, so CI is a
verification gate rather than a pipeline.

**Secret scanning.** gitleaks runs both as a pre-commit hook and as a CI job over full history. It
had been wired since Phase 1 and, per `docs/progress/phase_9.md`, was **never actually run** until
Phase 9, at which point it found no leaks across all 53 commits.

**Backups.** `scripts/backup.sh` exists, works, and is not scheduled.

**Uploads.** Written to `UPLOADS_DIR` (`/app/uploads`), backed by a named Docker volume so they
survive image rebuilds. Each file is stored under a 32-hex-character opaque key with a `.png`
extension, matched by the regex `[0-9a-f]{32}\.png` before any path is constructed — which is what
makes path traversal impossible. Served only through the authenticated `GET /api/trades/{tid}/image`
route with `Cache-Control: private, max-age=3600` and `X-Content-Type-Options: nosniff`, never
through a static mount.

---

## 15. Tests

There are **47 test files** containing **562 `def test_` functions**, plus 16 `@pytest.mark.parametrize`
decorators that expand into additional cases, which reconciles with the 637 figure quoted in
`docs/state.md`. `README.md`'s "213 tests" is stale by a factor of three.

The suite's defining property is that it is **offline and fixture-driven**. `tests/conftest.py` is
twelve lines and contains one autouse fixture that forces `EXPLAIN_PROVIDER=template` and deletes
`OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_MODEL` and `GEMINI_API_KEY` from the environment for
**every** test, so the developer's live `.env` can never leak into a test run and no test can hit the
network. Tests that exercise a provider set it explicitly *and* mock the transport.

`tests/fixtures/` holds six files: `chart_nvda.png` (a real 5,294-byte chart screenshot used by the
vision tests), `form4_submission.txt` and `master_sample.idx` (a real Form 4 full-text submission and
a daily master index), `form13f_submission.txt` and `master_13_sample.idx`, and
`schedule13d_submission.txt`.

**What the tests cover, by count.** The largest files are `test_accounts.py` (43 — registration,
login, sessions, tokens, tiers, entitlements), `test_relevance.py` (39 — every weight function and
the explain sentence), `test_journal_context.py` (29 — ticker extraction from claim values,
alignment, cohorts, behavioural patterns), `test_radar.py` (25 — spec normalisation, matching,
threading, the diff, and the full SSRF matrix), `test_claims.py` (21 — validation, the fence, the
mechanism validator, injection resistance), `test_spine.py` (21 — normalisation, classification,
distinctive words, novelty, amplification, trend), `test_ledger.py` (19 — verdicts, the noise floor,
`mean_ci`, `proportion_z`, `sample_needed`), `test_slice2.py` (19 — including the regex asserting
every migration registers its own version), `test_geography.py` (18), `test_llm.py` (18 — chain
parsing, circuit breakers, and specifically that `wants_model` accepts the chain form),
`test_authz_adversarial.py` (17), `test_crypto_intel.py` (16), `test_bluesky.py` (15 — against a real
captured payload), `test_sentiment.py` (15), `test_form4.py` (14), `test_gdelt.py` (14),
`test_insights.py` (14), `test_vision.py` (14), `test_trades.py` (13), `test_exposure.py` (12),
`test_assistant.py` (11), `test_news.py` (11), `test_signals.py` (10), `test_smartmoney_claims.py`
(10), `test_sources.py` (10), `test_assistant_tools.py` (9), `test_dashboard.py` (9),
`test_public_site.py` (9), `test_presentation.py` (8), `test_explain.py` (7),
`test_intelligence.py` (7), `test_social.py` (7), `test_backtest.py` (6), `test_billing.py` (6),
`test_admin.py` (5), `test_alerts.py` (5), `test_events.py` (5), `test_auth.py` (4),
`test_crypto.py` (4), `test_hn_query.py` (4), `test_community.py` (3), `test_library.py` (3),
`test_explain_gemini.py` (2), `test_scheduler.py` (2), `test_screenshot.py` (2),
`test_shortinterest.py` (2) and `test_search.py` (1).

**What is unusual and worth noting about several of them.** `test_authz_adversarial.py` is the only
file that touches a database; it skips cleanly when none is reachable and removes every row it
creates, and its first test asserts the setup actually created something, because "a negative test
suite's characteristic failure is being vacuously green." `test_llm.py` contains a **static scan**
asserting that no branch anywhere in the package gates a model call on a bare provider name, which
is a structural regression test for bug B-23. `test_sources.py` similarly asserts every
`_require_admin` call site uses a safe branching shape. `test_gdelt.py` asserts the module still
explains why the User-Agent is not rotated. `test_bluesky.py` asserts `geo` is left empty on that
source specifically, because conflating outlet location with event location is the most repeated
mistake in the project. `test_claims.py` asserts the prompt returns no literal attack strings,
because Azure's content filter classifies text quoting prompt-injection examples as a jailbreak.
`test_ledger.py` asserts the two planes are never pooled into one hit rate.

**What is not covered.** There is no frontend test of any kind — no Vitest, no Jest, no Testing
Library, no Playwright, no Cypress. There is no browser automation in CI. There is no load test. The
17 authz tests are the only integration tests; everything else is a unit test over pure functions or
mocked transports. And, as `docs/progress/cross_check.md` puts it in its own summary: "598 tests
passed, lint was clean, and six things were broken in the reader's face. Every finding below was
invisible to the suite." The failures that mattered most — an invisible black sphere, sideways
scrolling on every page at 375px, an unreachable marketing site, a rebrand that reached only the nav
bar — were not test-shaped, and the document's closing section names the four gates that would have
caught them: check a running instance at 375px, check WebGL surfaces in a **headed** browser,
grep the built bundle for the old brand name before calling a rebrand done, and treat a new
ingestion module as unfinished until it has a `sources.py` entry.

---

## 16. Git state

**Current branch: `main`**, tracking `origin/main`, and **exactly level with it** — not ahead, not
behind. `git status --porcelain` returns nothing: the working tree is **completely clean**. There
are no staged changes, no unstaged changes, no untracked files and **no stashes**. There are no tags.

**All branches.** Local: `game-changer` (at `de56ad0`, "Phase 0: audit before anything else", ahead
of `origin/game-changer` by 2), `main` (at `3136622`), `phase/1-repair` (at `2870f29`, "Phase 1:
finish reconciling CLAUDE.md"), `phase/2-ingestion` (at `e2d5ac5`), `phase/3-claims` (at `dd4fc01`),
`phase/5-globe` (at `db8d0e5`) and `phase/6-sections` (at `8c582a7`). Note there is **no
`phase/4-radar`**, **no `phase/7-site`**, **no `phase/8-accounts`** and **no `phase/9-security`**
branch, despite `docs/plan.md` naming all of them — those phases were evidently developed on
`phase/6-sections`, which is consistent with the commit history. Remote: `origin/HEAD` → `origin/main`,
`origin/game-changer` (at `8465dc7`), `origin/main` and `origin/phase/6-sections`. The remote is
`https://github.com/abdv1ahh/tradeos.git` for both fetch and push. Every local phase branch except
`phase/6-sections` has already been merged into `main` and exists only as a historical marker.

**The last twenty-five commits, newest first, with dates.** `3136622` 2026-07-27 15:30 "Two more
blockers: the benchmark had no history, and httpx prints API keys". `492f860` 2026-07-27 05:36 "Fix
the authz test teardown leaking accounts into the database". `d8e9c7b` 2026-07-27 05:32 "Docs:
record the commodity/location distinction and the test count". `1177def` 2026-07-27 05:29 "Fix
personalisation: a commodity is a relationship, not a location". `0c35229` 2026-07-27 00:25 "Docs:
the branch is merged and pushed; correct the test count". `367142e` 2026-07-27 00:24 "Merge
origin/main: reconcile the GitHub PR merges with four days of local work". `8c582a7` 2026-07-26
23:45 "Correct the backfill cost by 4x, and record why a partial one looks broken". `2baf8e6`
2026-07-26 23:19 "Unblock the signal's history: three silent failures in the chain". `7ec439b`
2026-07-26 22:17 "Find the bug that was capping the signal's history at two years". `34d9412`
2026-07-26 21:38 "Fix heading order and contrast, both front ends". `d4eed04` 2026-07-26 21:27 "Stop
the site publishing one subsystem's failure as the product's record". `b394413` 2026-07-26 20:50
"Size the scheduled Bluesky pass, and write up why it barely helped". `52cc389` 2026-07-26 20:35
"Rebuild the community surface, close the audit rulings, run the gates". `ffba39e` 2026-07-26 18:52
"Cross-check: fix what was broken in the reader's face". `d1de6e7` 2026-07-26 15:39 "Cross-check:
correct the table count after migration 032". `8deebe2` 2026-07-26 15:35 "Phase 4 remainder:
threading, saved filter sets, and subscribable alerts". `375e7d5` 2026-07-26 15:14 "Close three of
Phase 9's open gaps, and cross-check every claim in the docs". `1002187` 2026-07-26 06:09 "Phase 9:
security, and the list of what it did not fix". `bb24770` 2026-07-26 05:32 "Phase 8: accounts,
limits, and a deployment document that admits what it hasn't done". `1da2f34` 2026-07-26 04:59
"Phase 7: the marketing site, and the personalisation bug it exposed". `b92e09b` 2026-07-26 04:22
"Phase 6: the Journal learns what the trader was looking at". `6c9fa94` 2026-07-25 20:16 "Phase 6
handoff: complete resume state". `b6685b8` 2026-07-25 18:13 "Phase 6: News folds into the spine,
with a real source-comparison view". `74fbc45` 2026-07-25 16:28 "Phase 6: the Morning Brief holds
the system to account". `d5c847c` 2026-07-25 16:14 "Phase 6: Smart Money signals become scoreable
claims, and the Ledger gets real numbers".

Every commit is authored by Abdullah Hasan. Every message is a sentence describing the *effect* of
the change rather than the change itself, which is a genuinely good habit and makes the log readable
as a narrative.

**Where the work stopped.** The last commit is 2026-07-27 at 15:30 +0400. Today is 2026-08-21 —
roughly **three and a half weeks of no activity**. Nothing was left half-finished in the working
tree: the tree is clean and pushed. The stopping point is therefore not a mid-edit interruption but
a deliberate pause, and the commit that ends it is a bug-fix commit closing out two silent blockers
in the signal-history chain. `docs/state.md`'s "Resume in one minute" section is written for exactly
this situation and is still accurate apart from the numbers noted in section 18.

---

## 17. Every TODO, FIXME, commented-out block, dead file, duplicate implementation and abandoned experiment

**There is not a single `TODO`, `FIXME`, `XXX` or `HACK` comment anywhere in the codebase.** I swept
`tradeos/`, `frontend/src/`, `site/src/`, `tests/` and `shared/` and the only matches were the
substring "todo" inside the local variable `todo` in `intelligence/analyst.py:275` and the word
"Hacker" in "Hacker News". For a codebase of roughly 24,000 lines of Python and 11,000 lines of
JavaScript and CSS, that is remarkable, and it reflects a discipline visible everywhere: rather than
leaving a marker, the project writes the reasoning into a comment or files it in `docs/bugs.md`,
`docs/dead_code.md` or `docs/state.md`.

**There are no commented-out code blocks.** Every comment I read explains *why* — usually why an
obvious alternative was rejected — rather than preserving disabled code.

**Confirmed dead code — frontend.**

`frontend/src/components.jsx` exports four components with **no importer anywhere**:
`ClusterTable`, `ClusterDetail`, `StatusStrip` and `Classes`. They are superseded by equivalents
inside `smartmoney.jsx`. They are not recorded in `docs/dead_code.md`, so this is a **new finding**.
Roughly 200 of that file's 377 lines are unreachable.

`frontend/src/portfolios.jsx` (209 lines) exports `PortfoliosView`, which `App.jsx` imports and
renders under `view === "portfolios"` — but `"portfolios"` is in neither `NAV_LABELS` nor `ROUTES`,
nothing calls `go("portfolios")`, and an unrecognised path falls back to `radar`. The branch is
therefore **unreachable**, and with it the private helpers `HealthCard`, `Allocation`, `TrackRecord`
and `PositionsTable`. This transitively kills `Bucket` in `components.jsx`, whose only importer is
this file. Also a **new finding**. Note this is the "Portfolio → Exposure" decision recorded in
`docs/state.md` executed only halfway: the replacement shipped, the nav entry was removed, and the
old surface was left wired but unreachable rather than deleted.

`frontend/src/events.jsx` (101 lines) exports `EventsView`, imported by `App.jsx` — but the `events`
route renders `CalendarView` from `calendar.jsx` instead. `EventsView` is the pre-rebuild flat list
that bug B-11 called "a ~10,000-pixel flat list". Its private helpers `CrossPlane`, `EventRow` and
`SourceStrip` go with it. Also a **new finding**.

Note that `frontend/src/coverage.jsx` is **not** dead — it is imported by `news.jsx` and rendered as
the Coverage tab — and `frontend/src/globe3d.jsx` is **not** dead, it is lazy-loaded by `globe.jsx`.
`frontend/src/radarfilters.jsx` is used by `radar.jsx`. `ForgotPassword` in `account.jsx` is used by
`views.jsx`.

**Confirmed dead code — backend.** None. `docs/dead_code.md` records an AST sweep finding every
non-`__init__.py` module under `tradeos/` is imported by at least one other module or test, and my
own reading agrees. The five unused imports it listed (`datetime` in `news_sec.py`, `base64` in
`vision.py`, `math` and `config` in `news.py`, `timezone` in `convergence.py`) have all been
removed — and the removal of that last one had a consequence nobody expected, described below.

**Files that were dead and have since been deleted**, per `docs/dead_code.md` and verified absent
from the tree: `frontend/src/home.jsx` (208 lines, superseded by `smartmoney.jsx`),
`frontend/src/scanner.jsx` (94 lines, superseded by `social.jsx`), `LandingView` and `ExploreView`
(removed from `discover.jsx` in the cross-check pass), `fetchCommunityFeed`'s orphaned caller, 14
lines of orphaned landing CSS, `trading_intelligence .md` (19KB at the root, note the space in the
filename), a root `.DS_Store`, `tradeos-build-plan.md`, `tradeos-feature-spec-5.5.md` and an
`uploads/` directory.

**Deliberately parked, not dead.** `tradeos/ingestion/finra.py`, the `short_interest` table and the
`ENABLE_SHORT_INTEREST` environment variable form a complete ingestion path with **no consumer**.
Nothing reads `short_interest` into the convergence score. This was an explicit owner ruling on
2026-07-26 recorded three times — in `config.short_interest_enabled()`'s docstring, in
`docs/dead_code.md` A-01 and in `docs/decision-log.md` #31 — and the docstring says so directly: "A
future cleanup pass will find an ingestion path with no consumer and be tempted; this is the note
saying it was already considered and kept."

**Declared but never built.** `YOUTUBE_API_KEY` and `config.youtube_configured()` exist, YouTube has
a `sources.py` catalog entry, and there is **no ingestion module for it at all**. The
`feature_flags.blocked_countries` column exists and no code reads it — the geofence hook from
decision #37 was schema'd and never wired. The `signals` and `previews` feature-flag rows are inert.
`watchlists.user_key` survives as a nullable legacy column that migration 026 said a later migration
would drop, and no later migration does.

**Duplicate implementations, all deliberate and all documented.** There are **three** near-identical
ticker-from-prose regexes: `ingestion/news_rss.py`, `intelligence/analyst.py` and
`journal_context.py`. The third one's comment explains why they are not consolidated — the first two
parse free-running headline prose and require an exchange qualifier like "(NASDAQ: AMC)", while the
third parses one short structured field where a bare parenthetical is the common form, so a shared
helper would have to be the union and would loosen both — and then names the trigger: "If a fourth
appears, that is the signal to unify all four rather than add to the pile." There are also two
`Sparkline` components, one in `views.jsx` and one in `smartmoney.jsx`, which is genuine
undocumented duplication. And the `pct` formatter was duplicated across four surfaces until the
fourth copy dropped the ×100 and published a +10% trade as "+0.1%"; that one is now consolidated in
`format.js`.

**Abandoned experiments.** Congressional trading disclosure: decision #29 records the
reconnaissance — the Senate eFD portal returns 403 to programmatic clients and House PTR transaction
detail lives in scanned PDFs — and the feature flag was seeded, gated nothing for eight phases, and
was finally deleted by migration 033 with `ENABLE_CONGRESS` removed from `config.py` in the same
change. Stooq as a price source: decision #27 records that its free CSV endpoint sits behind a
JavaScript proof-of-work anti-bot challenge and that fetching it was refused on supply-chain grounds,
superseding decision #15. Embeddings for clustering: `docs/plan.md` §3 records the decision to start
deterministic, and `spine.py` explains that a spine which stops ingesting when model quota runs out
is a worse spine. GSAP, Lenis and Framer Motion on the marketing site: offered by the brief, rejected
in writing, replaced by native scroll timelines.

**Three "silent failure" bugs found by trying to grow the sample**, recorded in
`docs/progress/cross_check.md`, all of which are instructive about how this codebase fails. First,
`schedule13.FORM_TYPES` contained only the modern spelling `SCHEDULE 13D` while EDGAR indexes before
the SEC's 2024 modernisation say `SC 13D` — so **fourteen years of filings were skipped with no
error**, every backfill logging "0 Schedule 13D/G filings in index" and exiting zero. Second, the
Phase 1 lint pass removed an unused `timezone` import from `convergence.py`, which changed the
module's sha256, which made the hash guard refuse to run `compute-signals` from 2026-07-25 onward —
the guard was right to fire and nothing surfaced that it had. Third, the v3 liquidity floor needed
90 days of price history and `prices_eod` began at 2024-04-01, so every historical `as_of` failed
the floor and published nothing. Two more followed: the benchmark itself had no history (SPY prices
began 2026-01-02 while cluster tickers reached back to 2021-06-01, so all 297 historical outcomes
were written with a NULL return and were silently unscoreable), and pulling that SPY history by hand
put a Tiingo token in plain text on stdout because httpx logs every request at INFO with the full
URL and `cli.py` enabled INFO globally.

---

## 18. Known bugs, broken flows, and what currently crashes or silently fails

I have separated what the project already knows from what I found.

**Known and documented as still open.**

*Google sign-in has never been run against Google.* The parsing, validation and linking logic is
unit-tested against captured-shape payloads; the live handshake has never executed because no
credentials were available. It is untested auth code. The button exists on the login screen. If
`GOOGLE_CLIENT_ID` is unset, `/api/auth/google/start` returns a 503 with a clear reason rather than
half-working.

*SMTP is unconfigured, so email verification and password reset cannot send.* The machinery is
built, tested and reachable from the login screen; `mail.send` refuses to send rather than
half-sending, which is the correct failure. But a user who forgets their password today has no path
back except an operator editing the database. `docs/state.md` calls this "the real blocker before
other people use this."

*The rate limiter is in-process.* It resets on restart and multiplies by the replica count. Stated in
its own docstring, in the threat model and in `docs/deploy.md`.

*`X-Forwarded-For` is trusted for client identity.* Only safe while the app is reachable exclusively
through Caddy.

*No CORS policy.* Correct while both bundles are same-origin; needed narrowly the moment the site
gets its own domain.

*No caching on the public endpoints.* Every request runs its queries.

*No backup schedule.* The script works; nobody has installed the cron line.

*No penetration test.* `/security-review` has only ever seen diffs, never the code predating the
current branch. `/code-review` has **never been run on any diff**.

*Dependencies are clean as of one snapshot only.* CI runs gitleaks but not `pip-audit` or
`npm audit`.

*Cluster matching does not scale.* `spine.find_cluster` computes `similarity(c.title, …)` against
every cluster in a 36-hour window — 821 of them at the time of measurement — for every event, with
no usable index. Measured at 186 seconds for 381 events and 165 seconds for 183, so the cost tracks
the **cluster corpus**, not the batch, and shrinking the fetch window barely helped. It is
comfortably inside its hourly interval today and will get slower as the corpus grows. The fix is
known and deliberately not done in passing: a GIN trigram index only helps the `%` operator, which
takes its threshold from the `pg_trgm.similarity_threshold` session GUC rather than from the query,
so doing it right means `title % $1 AND similarity(...) >= $2` with the GUC set at or below
`WEAK_SIMILARITY` — and doing it wrong silently stops matching things in the one piece of logic the
whole product is built on.

*The confidence buckets look mis-specified.* At 90 days the "high" bucket runs −25.8% against
"medium" at +9.5%, an inversion — but n = 8 in that bucket, so it is recorded as a suspected defect
rather than refitted on eight observations.

*Bluesky addresses accounts by handle, not DID*, so a renamed account fails and is logged by name.

*The 3D globe is verified on desktop WebGL only*, never on a real low-power mobile device.

*`author_influence` is used but thinly.* It reaches `relevance.score` weighted at 0.06.

**Found in this audit and not previously recorded.**

*The `/portfolios` route is unreachable.* Described in sections 4 and 17. Nothing crashes; the
surface is simply inaccessible while its backend routes remain live and its tables still feed
Exposure's holdings query. A user who created a portfolio before the nav entry was removed can no
longer see it, though its positions still count toward their Exposure.

*`EventsView` is unreachable*, superseded by `CalendarView` at the same route.

*Four exports in `components.jsx` are unreachable.*

*`sessions` rows are never deleted.* No code path removes expired sessions and there is no cleanup
job. The table grows monotonically with every login. Same for `login_attempts` — `_rate_limited`
counts rows inside a fifteen-minute window but nothing ever deletes older ones — and for `job_runs`,
which gains eighteen rows per hour, or roughly 158,000 per year, with no pruning. None of these
breaks anything today; all three will need a retention job.

*There is no database connection pool.* Every request calls `psycopg.connect()` and closes it. At
two uvicorn workers on a small VPS this is fine; it is a hard ceiling on concurrency and it is
documented nowhere.

*`docs/state.md` and `CLAUDE.md` publish a Ledger figure that the same repository has already
superseded.* Both say "41% of 282". `docs/progress/cross_check.md` records the post-backfill
measurement as **43.2% of 412** with expectancy −1.18% and an interval of [−2.93%, +0.57%]. The
docs disagree with each other by a full backfill.

*`CLAUDE.md` says Pillow 10.4.0*; `requirements.txt` says 12.3.0 and Phase 9 documents the upgrade.

*`README.md` says 213 tests and 99 routes*; the real figures are 637 and 127.

*`docs/dead_code.md` says "All 23 applied"* for migrations; there are 33.

*`GO-LIVE.md` points at the wrong GitHub organisation* (`DoubleX11` rather than `abdv1ahh`) and
describes merging a pull request from an era three rebuilds ago.

*`FREE-AI.md` and `.env.production.example` both recommend GitHub Models*, whose sunset date of
2026-07-30 has passed. Anyone following either document today configures a dead endpoint. The chain
would fall through to Gemini if configured, so the failure is graceful, but the advice is wrong.

*The local `.venv` carries Pillow 10.4.0*, the version with the two known PSD CVEs.

*`test-activate` is a live free-upgrade endpoint* while Stripe is unconfigured. It requires
authentication, and free-launch mode already grants Pro to every signup, so it grants nothing extra
today — but it is a route that upgrades an account for free and it is reachable.

*The `.pytest_cache` is stale*, recording 191 node ids and two failures in a file that no longer
exists.

*The marketing site is not built in CI*, so a syntax error in `site/src/` would not be caught.

**What actually crashes.** Nothing that I can find. The failure design here is unusually thorough:
one `ErrorBoundary` per surface keyed by view so a render throw is contained; `LoadError` and
`EmptyState` for honest data states; `SourceGate` for a missing key; every ingestion adapter catching
per-feed and per-account so one failure never sinks a pass; `run_job` rolling back and recording
every failure; `llm.complete` never raising; and one middleware catching every unhandled exception
and returning a uniform error with a request id. The historical crash — a missing `Icon` import
that passed 435 tests and threw `ReferenceError` on the page — is exactly the class the boundaries
now contain.

**What silently fails, which is the more interesting category and the one this codebase has been
burned by repeatedly.** A model call that falls through to a template while reporting the model was
tried (bug B-23, fixed by `llm.wants_model`, with a static test preventing recurrence). A source
that no-ops because it is unkeyed but still records `status: ok` in `job_runs` (handled —
`sources.health` deliberately does not count that as a successful fetch). A backfill that produces
"N candidates, 0 clusters" because only one of the two required source classes has history —
indistinguishable from a broken signal from the outside, which is why `make backfill-full` exists. A
migration that forgets its own `schema_migrations` row and silently re-runs. A hash guard refusing
to compute signals with nobody able to see that it was refusing. All five are now either fixed with
a test or written into `CLAUDE.md` as a gotcha.

---

## 19. Honest feature-by-feature completion assessment

Percentages are my judgement of how much of what the feature promises is actually delivered
end to end, with the reasoning stated.

**Works end to end.**

*SEC ingestion pipeline (Form 4, 13D/G, 13F, 8-K)* — **95%**. Throttled, allowlisted, checksummed,
idempotent, point-in-time correct, with loud rejects and per-feed health. The missing 5% is
operational: the backfills are manual, and Form 4 history is measured at 35 minutes per week
ingested, so 2.5 years is roughly 76 hours.

*Entity and ticker resolution* — **80%**. CIK resolution is exact and complete; the SEC's own
ticker file gives confidence-1.0 mapping. CUSIP resolution is the gap: 19,851 holdings unresolved
because `OPENFIGI_API_KEY` is unset.

*The convergence signal and its hash lock* — **100% as engineering**. Versioned, parameterised,
independence-collapsed, gated, liquidity-floored, refusing to run on a hash mismatch. **As a
product it is unproven** — see the Ledger below.

*The backtest and calibration* — **95%**. Pure, tested, look-ahead-proof, episode-deduplicated,
Wilson-intervalled, with "insufficient sample" below thirty episodes. Constrained by sample, not
correctness.

*The event spine* — **90%**. Normalisation, clustering with a documented weak-similarity band and a
proper-noun corroborator, novelty and amplification with a stored velocity curve, category
re-derivation from members. The missing 10% is the clustering scalability problem.

*The Ledger* — **100% as machinery, and it is the best thing in the repository.** Excess vs SPY, a
2% noise floor, unscoreable as a first-class verdict, misses exposed deliberately, calibration
buckets, confidence intervals, a z-score against a coin flip, and a sample-needed calculation. The
two planes cannot be pooled and a test enforces it.

*Authentication and sessions* — **90%**. argon2id, invite gating, hashed tokens, dual-key rate
limiting, TOTP for admin, lazy trial expiry, single-use expiring hashed reset tokens, uniform
responses, an enumeration-safe request path with the timing side channel closed, a reset that signs
out everywhere, and seventeen adversarial authorization tests. The missing 10% is Google OAuth
untested and no session cleanup.

*The Radar* — **95%**. Relevance-ranked, server-side scored, explained per item, threaded with a
plain-English diff, filterable and subscribable.

*The Ledger surface, the Morning Brief, News with source comparison, Exposure, the Calendar, the
Assistant, Integrations, Community, Admin* — all **90–95%**, all wired to real data with real
loading, empty and error states.

*The Journal* — **95%**, and the most feature-dense surface: screenshot capture with ticker
extraction, AI chart reads with field-level guarding, a coach that reasons about **process** rather
than outcome, similar-trade cohorts, a deterministic simulator and a cached report.

*The marketing site* — **95%**. Live data through four public endpoints, no fixtures anywhere, real
loading/empty/unreachable states as three different sentences, structured data generated from the
same array the page renders, self-hosted fonts, native scroll-driven animation, verified contrast
and heading order.

*The guard system* — **100%**. Three guards plus a fourth on the news plane, with a deterministic
fallback everywhere except the impact engine, where writing nothing is the deliberate choice.

*The source registry and honest degradation* — **100%**.

**Half built.**

*The impact engine* — **70%**. The pipeline works: it produces claims with real mechanisms, they are
validated, contradictions are linked, threading re-reads developing stories, and outcomes are
measured. What is missing is **time**: 80 open claims and zero resolved means the product's central
promise has produced no evidence yet. It is not broken; it is young.

*Personalisation* — **75%**. The scoring is sophisticated and correct after the commodity/location
fix. The constraint is coverage: **ten countries** have exposure data, and a reader outside them
gets a global frame. That is honest and it is also a small world.

*Alerts and subscriptions* — **70%**. In-app notifications work. Webhook delivery works with a
genuinely good SSRF defence. **Email delivery cannot send.**

*Billing* — **60%**. Plans, entitlements, limits, checkout, webhook handling, cancellation and API
keys are all written and structurally sound. None of it has processed a real payment, the SDK is not
installed, and the system is deliberately in free-launch mode.

*Social and attention* — **50%**. Wikipedia and Hacker News work and measure attention.
**No connected source measures mood**, so most rows read "attention only" and the pulse tile says
"MOOD NOT MEASURED · CONNECT REDDIT". Honest, and thin.

*Crypto* — **80%**. Positioning, funding, open interest, crowding and liquidity all work with
invalidation conditions. Deferred: on-chain data and whale flows.

*The globe* — **85%**. Renders on desktop WebGL with real geometry and 62 sourced corridors, with a
flat-map fallback. Unverified on mobile.

*The library* — **60%**. Twenty entries with sources, wired into cluster detail. All twenty are
still `review_status: draft`.

**Stubbed, mocked or hardcoded.** Very little, and that is the point. There is **no fixture data
presented as live anywhere** — the honesty rule is enforced structurally, and the searches I ran for
placeholder, mock and hardcoded data found only input `placeholder` attributes and
`psycopg.sql.Placeholder`. The genuinely hardcoded things are all reference data that ought to be
hardcoded and are documented as editorial: the ten countries in `relevance.COUNTRIES`, the region,
currency and commodity tables in `geography.py`, the 24 seeded accounts and their influence weights,
the `MACRO_INTEL` knowledge base, the 34-name megacap map, and the 29 common passwords standing in
for a breached-password list. The one thing that is a genuine placeholder is that
breached-password set, which is explicitly labelled "a small demo stand-in for a top-100k breached
list (a drop-in replacement in prod)".

**Empty scaffolding.** YouTube — a config accessor, a catalog entry, no module.
`feature_flags.blocked_countries` — a column no code reads. The `signals` and `previews` flag rows.
`watchlists.user_key` — a legacy column a migration promised to drop and never did.
`stake_events.percent_owned` — a column that is always NULL by design.

**Overall.** My honest number for the whole system is **80% of a working product and 25% of a proven
one**. The engineering is close to done. The evidence is not.

---

## 20. What is genuinely valuable and reusable if the product were repositioned

If you kept nothing but the code and pointed it at a different problem, here is what would survive.

**The single most valuable asset is the honesty apparatus, and it is portable to almost anything.**
`ledger.py` plus `claim_outcomes` plus the three statistical functions form a general-purpose
**prediction scoring system**: something commits to a direction on a named subject over a stated
horizon with a stated confidence, and later gets marked against what happened, with excess return
over a benchmark, a noise floor so a non-move is not counted as a win, `unscoreable` as a first-class
verdict so the sample cannot be self-selected, calibration buckets asking whether "70%" lands near
70%, a confidence interval, a z-score against chance, and a sample-size calculation. Point that at
sports, at elections, at weather, at supply-chain ETAs, at sales forecasts, at anything with a
falsifiable claim and a measurable outcome, and it works unchanged. Nobody builds this because it is
the part that makes you look bad. Having built it is a genuine moat.

**Second: `explain/guards.py` and the guarded-model pattern around it.** A numbers guard requiring
every numeric token in model output to trace to the input payload, a directive guard banning advice
vocabulary, a citation guard banning tickers the source did not mention, a base-rate integrity guard
requiring any stated rate to match the record exactly — plus the architectural rule that a guard trip
falls back to deterministic output and **the fallback message must state the real reason**. That is a
reusable compliance layer for any regulated or high-stakes domain: medical, legal, insurance,
HR. The vision module's field-level guarding is a refinement most implementations of this pattern
never reach.

**Third: `llm.py`.** A 293-line provider-chain transport with per-provider circuit breakers, two
model roles, plain-language failure reasons instead of exceptions, host allowlisting, and three
hard-won operational details — the thinking-token headroom, the `thinkingConfig` incompatibility and
the free-tier model-id constraints — each with a measurement attached. It is a drop-in for any
project and better than most of what people write for themselves.

**Fourth: `spine.py`.** A deterministic news-clustering engine that does not need an inference
provider: trigram similarity with a documented strong and weak band, a shared-proper-noun
corroborator whose thresholds were calibrated against real measured headline pairs, an entity-overlap
requirement that stops templated SEC headlines merging eight different companies into one story,
novelty as a function of corroboration and repetition rather than recency, and amplification from a
stored velocity curve so the interface can say "accelerating" or "fading" rather than showing a
number that hides direction. That is reusable for any deduplication problem over a stream of text —
support tickets, incident reports, job postings, product reviews. Its one known weakness, the
unindexed similarity scan, is a known problem with a known fix.

**Fifth: the SEC ingestion pipeline.** `edgar_client.py`, `sgml.py`, `form4.py`, `schedule13.py`,
`form13f.py`, `news_sec.py` and `runner.py` are a genuinely careful EDGAR reader: throttled,
allowlisted, checksummed, idempotent on accession number, header-only parsing so no fact is a guess,
loud rejects, and the legacy-versus-modern form-type normalisation that took fourteen years of
missing filings to discover. Anyone building anything on EDGAR would be years ahead starting from
this.

**Sixth: the point-in-time architecture itself.** The `event_time`/`knowable_time` pair on every
derived row, the append-only raw layer enforced by a database trigger, the derived tables rebuildable
from stored payloads, and the discipline that every backtest query filters on `knowable_time`. That
is the correct shape for **any** system that will later be asked "would you have known this then?" —
credit models, fraud detection, risk scoring, medical prediction. Retrofitting it is close to
impossible, which is exactly why decision #4 insisted on it from day one.

**Seventh: `ratelimit.py`, `radar.webhook_target_ok`, `assistant_tools.py` and `claims.fence`.**
Four small, self-contained security components: a correct sliding-window limiter that explains its
own limitations, an SSRF defence that resolves and checks **every** address and re-checks at send
time and refuses redirects, a read-only tool registry with no generic query escape hatch, and a
prompt fence using a per-request nonce rather than fixed markers — the last because `str.replace`
cannot sanitise a delimiter, a lesson learned the hard way. All four are directly liftable.

**Eighth, and underrated: the writing.** The module docstrings, the decision log's 51 entries each
carrying its strongest counterargument, the threat models, the bug catalogue that records a wrong
root cause rather than quietly deleting it, and `docs/progress/cross_check.md`, which opens by
saying "598 tests passed, lint was clean, and six things were broken in the reader's face." Whether
this is repositioned or handed to a new team, that record is worth more than most of the code,
because it explains *why* every non-obvious decision is the way it is.

**Ninth: the marketing site**, as a design artefact. Two hundred lines of React and 492 of CSS
producing a page with FCP measured at 24ms, no external requests, native scroll-driven animation,
verified contrast, and a palette argued from the subject matter rather than picked. The specifics are
nautical and would not survive a pivot, but the *method* and the performance discipline would.

**What is throwaway.**

The **convergence signal itself**, as a product. Not the machinery around it — the machinery is
excellent — but the specific weighting scheme. On 412 resolved calls it shows a directional hit rate
significantly below chance and a return indistinguishable from zero. It might work with more sample
and it might not. Anyone repositioning should treat it as a hypothesis, not an asset, and
`docs/progress/cross_check.md` says as much: continuing to surface it as a signal to act on "is a
product decision worth making deliberately."

The **community and social layer** — profiles, follows, reactions, comments, the leaderboard, the
moderation queue — is competent and generic. It has already been deleted once for lack of an entry
point and rebuilt on an owner ruling. It carries an ongoing moderation burden, adds tables and
attack surface, and is not differentiated. In a repositioning it is the first thing to cut.

**Billing** is standard Stripe integration. Well done, entirely replaceable.

**Paper portfolios** are already half-dead — the route is unreachable — and the decision to replace
them with Exposure was correct. The remaining code is not worth carrying.

The **crypto surface** is genuinely good work but sits oddly beside everything else, is entirely
dependent on Binance's public endpoints continuing to be public, and shares almost nothing with the
rest of the system.

The **library** is twenty draft entries of general trading education, replaceable in a weekend.

`GO-LIVE.md`, `FREE-AI.md` and the phase progress reports are historical. `DEPLOY.md` and
`docs/deploy.md` overlap substantially and one should absorb the other.

The **4.7 GB of `raw_filings`** is only valuable if you stay on SEC data. It is also the only thing
in the database that cannot be quickly refetched, which is why the unscheduled backup is the single
most urgent operational item in this report.

**In one sentence:** what is worth keeping is the *epistemics* — the point-in-time discipline, the
guard system, the Ledger, the deterministic clustering, the honest-degradation pattern and the
written record of why — and what is throwaway is the *domain-specific product decisions* layered on
top, including the signal the older half of the product was built to sell.

---

*End of report. Compiled by reading, not by running. No file in this repository was modified except
this one.*




