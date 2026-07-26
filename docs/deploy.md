# docs/deploy.md — deploying Rhumb end to end

Written for someone who has never seen this repository. Every variable the code reads is listed
below with where to obtain it, and the list is checked against the source rather than remembered —
`python -m tradeos.cli preflight` is the authority and will refuse a configuration this document
gets wrong.

**Honest status:** the app has been run continuously in Docker on a developer machine. It has
**not** been deployed to any of the hosts named below, so the platform-specific steps are written
from each provider's documentation, not from having done it. Where that matters, it says so.

---

## What has to run

Three processes and a database. This is not a single-container app, and the reason matters:

| Piece | What it is | Why it cannot be merged |
|---|---|---|
| **api** | `uvicorn tradeos.app:app` | Serves the API, the app bundle and the marketing bundle |
| **worker** | `python -m tradeos.cli scheduler` | Ingestion, claim generation and Ledger scoring run on a timer. If this does not run, the product freezes at the last thing it ingested and quietly serves stale data |
| **db** | PostgreSQL 16 | See "Why not SQLite" below |

The worker is the piece most free tiers make awkward, because it is a long-running process rather
than a request handler. Budget the decision there, not on the API.

### Why not SQLite

The brief suggests SQLite, and `docs/plan.md` §1 overrides it. The short version: 664,923 insider
transactions, 51,099 stake events and 24,982 institutional holdings already exist, and the product
depends on `pg_trgm` for clustering, `tsvector` for search, `jsonb` indexing on raw payloads,
`interval` arithmetic for horizon sweeps, and concurrent access from two containers. Several of
those have no SQLite equivalent that would not require rewriting the feature.

---

## The fastest correct path

```bash
git clone <repo> && cd tradeos
cp .env.example .env          # then fill in SEC_USER_AGENT — the app refuses to start without it
docker compose up -d --build
docker compose exec -T api python -m tradeos.cli migrate
docker compose exec -T api python -m tradeos.cli preflight     # tells you what is missing
```

Then seed an admin and, optionally, a demo account:

```bash
docker compose exec api python -m tradeos.cli seed-admin --email you@example.com
docker compose exec -T api python -m tradeos.cli seed-demo
```

The marketing site is a separate bundle and is not built by the Docker image:

```bash
cd site && npm install && npm run build      # served at /site
```

---

## Every environment variable

`.env.example` is the machine-checkable copy; this table adds where each value comes from. Only
the first two are required — **everything else degrades honestly**, reporting itself as not
connected on `/integrations` rather than failing or fabricating.

### Required

| Variable | What it is | Where to get it |
|---|---|---|
| `SEC_USER_AGENT` | `Name you@example.com`. SEC fair-access policy requires a real contact address | Your own email. The app raises `ConfigError` on startup without it |
| `DATABASE_URL` | `postgresql://user:pass@host:5432/db` | Set for you by docker-compose; override only for a managed database |

### Language model — all AI prose degrades to deterministic text without these

| Variable | What it is | Where to get it |
|---|---|---|
| `EXPLAIN_PROVIDER` | A comma-separated **chain**, tried in order: `gemini,openai`. `template` means no model | — |
| `GEMINI_API_KEY` | Free tier, no card | <https://aistudio.google.com/apikey> |
| `GEMINI_MODEL` | `gemini-flash-latest`. **The id matters** — `gemini-2.0-flash` has a zero free-tier allowance and `gemini-2.5-*` are closed to new keys | — |
| `GEMINI_MODEL_FAST` | `gemini-flash-lite-latest`, for classification | — |
| `OPENAI_API_KEY` / `OPENAI_BASE_URL` / `OPENAI_MODEL` | Any OpenAI-compatible endpoint — Groq, OpenRouter, a local server | <https://openrouter.ai/keys> for a free one |

> **Verify this after deploying, not before.** The suite runs on `template` by design, so a dead
> model path passes every test silently — that exact failure shipped for three phases (B-23). Hit
> `/api/journal/report` on the running instance and confirm `used_template: false`.

### Data sources — each is optional and each says so when absent

| Variable | Powers | Where to get it |
|---|---|---|
| `TIINGO_API_KEY` | End-of-day prices — **this is how claim outcomes get scored**, so the Ledger stops advancing without it | <https://www.tiingo.com/account/api/token> |
| `REDDIT_CLIENT_ID` + `REDDIT_CLIENT_SECRET` | The only source that measures mood rather than attention | <https://www.reddit.com/prefs/apps>, type "script" |
| `YOUTUBE_API_KEY` | Video discussion volume | Google Cloud console, YouTube Data API |
| `OPENFIGI_API_KEY` | Maps 13F CUSIPs to tickers; 19,851 holdings are currently invisible without it | <https://www.openfigi.com/api> — works keyless at a lower rate |

### Sign in with Google — optional, and unverified

| Variable | Notes |
|---|---|
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | OAuth 2.0 Client ID, type "Web application", at <https://console.cloud.google.com/apis/credentials> |
| `PUBLIC_BASE_URL` | Scheme + host, no trailing slash. The redirect URI is `<PUBLIC_BASE_URL>/api/auth/google/callback` and must be registered **exactly** |

> The Google flow has **never been exercised against Google** — no credentials were available while
> it was built. Its validation logic is unit-tested; the live handshake is not. Email and password
> signup is unaffected. Whoever configures this first should treat it as untested code.

### Runtime

| Variable | Notes |
|---|---|
| `COOKIE_SECURE` | **`true` in production.** Session cookies then require HTTPS and HSTS is sent. Leaving it false over the public internet exposes sessions |
| `BRAND_NAME` | `Rhumb`. A config value so the display name changes without a refactor |
| `UPLOADS_DIR` | Where chart screenshots are written. **Needs a persistent volume** — a container filesystem loses them on redeploy |
| `DEV_ORIGINS` | Extra origins allowed to make state-changing requests. **Development only.** Leave empty in production |
| `SENTRY_DSN` | Optional error reporting |

### Billing and seeding

| Variable | Notes |
|---|---|
| `STRIPE_SECRET_KEY` / `STRIPE_WEBHOOK_SECRET` | **Empty means free-launch mode**: every signup gets Pro at no charge and the pricing page is labelled test mode. Setting the key switches real billing on with no code change — and switches free-launch off |
| `TRADEOS_ADMIN_PASSWORD`, `TRADEOS_DEMO_EMAIL`, `TRADEOS_DEMO_PASSWORD` | Read only by `seed-admin` / `seed-demo`. Not needed at runtime |

---

## Deploying on free tiers

### Database

A managed Postgres free tier (Neon, Supabase, Railway) is the least work. Take the connection
string into `DATABASE_URL` and run `migrate` once. **Check the provider's idle-suspend policy** —
several free tiers suspend after inactivity, and the worker waking a suspended database every few
minutes may or may not count as activity depending on the provider.

### API and worker

They share an image and differ only by command. Any host that runs a container works: Fly.io,
Railway, Render. On a platform that only offers request-scoped execution, the worker is the problem
— the scheduler is a loop, not a handler.

If the host cannot run a background process, the honest fallback is an external cron hitting the
CLI, accepting that per-source TTLs become approximate:

```bash
docker compose exec -T api python -m tradeos.cli spine       # ingest + cluster
docker compose exec -T api python -m tradeos.cli interpret   # generate claims
docker compose exec -T api python -m tradeos.cli measure-claims   # score elapsed horizons
```

### The two front ends

Both are static bundles. `frontend/` is baked into the API image at build time; `site/` is not, and
must be built separately (`make site`). On a static host, deploy `site/dist` to the apex domain and
point the app at a subdomain, which is the split the marketing site is designed for — it currently
mounts at `/site` on the API's own origin purely so both are verifiable locally.

Whichever split you choose, the site's `/api/public/*` calls must reach the API. Same origin needs
no configuration; a separate origin needs CORS, which **is not currently configured** — that is
real work, not a checkbox.

---

## Before you call it live

```bash
docker compose exec -T api python -m tradeos.cli preflight
docker compose exec -T api python -m tradeos.cli status      # per-feed freshness
```

`preflight` checks production configuration including every link in the `EXPLAIN_PROVIDER` chain.
Then, by hand, because these are the things that pass automated checks and still bite:

- [ ] `COOKIE_SECURE=true`, and the site actually reachable over HTTPS
- [ ] `DEV_ORIGINS` empty
- [ ] `UPLOADS_DIR` on a volume that survives a redeploy
- [ ] `/api/journal/report` returns `used_template: false` — see the warning above
- [ ] `/integrations` shows every source in the state you expect
- [ ] The worker is actually running: `job_runs` should have rows from the last hour
- [ ] A real signup, in a browser, end to end — including the onboarding card

---

## Known gaps

Recorded here rather than discovered later:

1. **No CORS configuration.** Fine while both bundles are same-origin; required the moment the
   marketing site moves to its own domain.
2. **No rate limiting on the public endpoints.** `/api/public/*` and `/api/ledger` are
   unauthenticated and uncached. Phase 9 territory.
3. **Google sign-in is untested against Google.** See above.
4. **Backups are not configured.** The dataset took hours of rate-limited SEC backfill to build and
   there is no dump schedule. Whatever host you choose, set one up before it matters.
5. **This document has not been executed against a real host.** It is derived from the running
   Docker setup and provider documentation. The first person to deploy should correct it in the
   same change that discovers a mistake — a wrong command here is worse than no command.
