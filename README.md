# Rhumb

A world-event interpretation engine that happens to be very good at explaining market
consequences. It answers one question continuously: *something just happened in the world, so
what does it mean for me specifically?*

Three commitments make that defensible:

- **Causal chains, not headlines.** Every item carries the event, the mechanism by which it
  propagates, what it touches, historical episodes that rhymed with it, and a confidence level.
- **A public track record.** Every interpretation is timestamped when made, then scored against
  what actually happened. The misses are shown, not buried.
- **Personal relevance.** The same event reads differently from Sharjah than from São Paulo.

Currently a working SEC/news intelligence platform being rebuilt around those three ideas. The
full brief is `docs/tradeoss_veryimportant_prompt.md`; the plan is `docs/plan.md`; where the work
stands is `docs/state.md`. **If you are an agent working on this repository, read `CLAUDE.md`
first.**

`TradeOSS` remains the internal codename — the Python package, the Docker services and the
database are named for it and are not renamed for branding. The display name is one config value
(`BRAND_NAME`).

---

## Run it

Prerequisites: Docker with Compose.

```bash
cp .env.example .env      # set SEC_USER_AGENT at minimum; every other key is optional
docker compose up -d --build
```

That starts Postgres, the API on <http://localhost:8000>, and the scheduler worker. Then load a
demo dataset:

```bash
make demo                 # quick data window: ingests, resolves, computes signals, backtests
docker compose exec api python -m tradeos.cli seed-admin --email you@example.com
```

`make backfill-full` is the overnight 24-month calibration backfill; do it before publishing any
track record.

### Development

```bash
make dev                  # Python reloads in place; tests/ mounted; serves frontend/dist
make web                  # rebuild the UI (~0.3s) — no image rebuild needed
make test                 # 213 tests, fully offline, under a second
make lint                 # ruff
```

Without `make dev`, the frontend bundle is baked into the image at build time, so a UI change
needs `docker compose up -d --build`. This is the single biggest time sink in this repo.

---

## Configuration

Every variable is documented in `.env.example` with a link to where each free key is obtained.
Only `SEC_USER_AGENT` is required — the SEC's fair-access policy requires a contact address, and
the app refuses to start without one.

`python -m tradeos.cli preflight` checks production readiness. The **Integrations** page in the
app (`/integrations`) shows every external source, whether it is connected, what it powers, when
it last succeeded and the last error — you should never have to guess why a panel is empty.

### The language model

`EXPLAIN_PROVIDER` is a comma-separated fallback chain, so one provider going down does not
silence every AI surface:

```
EXPLAIN_PROVIDER=gemini,openai
```

`gemini` is Google AI Studio's free tier. `openai` is any OpenAI-compatible `/chat/completions`
endpoint — OpenRouter and Groq both have free tiers. `template` means no model at all, and every
caller falls back to deterministic output rather than failing.

Two model roles are configurable per provider: a small fast model for classification and
extraction, and the strongest available for reasoning about mechanisms.

---

## What is in here

```
tradeos/            the Python package — see CLAUDE.md for the full directory map
  app.py            FastAPI, 99 routes
  llm.py            one transport for every model call: provider chain + circuit breakers
  sources.py        the source registry that backs /api/integrations and every degradation gate
  scheduler.py      the background worker: job registry, restart-safe cursors, error isolation
  ingestion/        one module per external source; nothing else calls an external API
  migrations/       ordered .sql, run by db.py. Never edit an applied migration.
frontend/src/       React + Vite. No router library, no state library, no CSS framework.
tests/              pytest, offline, fixture-driven
docs/               audit, bugs, dead_code, plan, state, progress/, decision-log, threat-models
```

---

## Point-in-time discipline (the one thing to internalize)

Every filing-derived row carries two times: `event_time` (when it happened) and `knowable_time`
(when it became public). All signal computation and every backtest query through `knowable_time`
only. This is what makes look-ahead leakage structurally impossible rather than merely avoided,
and it is what will make the accuracy ledger worth believing. **Do not break it.**

---

## Honesty rules this codebase enforces

These are not aspirational; they are why several things are built the way they are.

- **Never fabricate.** No placeholder numbers styled to look real. If a source is unavailable the
  interface says so and says what to do about it.
- **Degrade, never block.** A missing key renders a gate explaining what the source would add and
  linking to where the free key is obtained, while everything else keeps working.
- **Say the real reason.** When AI output is unavailable, the user is told whether it was a
  missing key, a quota trip, or a guard — never a generic "not connected". A wrong explanation is
  worse than none.
- **Every fact carries provenance.** Source, retrieval timestamp, link.
- **Describe, never advise.** Model prose passes an advice guard before display; anything that
  fails is withheld and named.

---

## Security posture

- Invite-gated registration; argon2id passwords; SHA-256-hashed session tokens in
  HttpOnly/SameSite cookies; per-IP and per-account login rate limits; TOTP for admins.
- The free tier's data delay is a server-side `WHERE` clause — no request parameter reaches
  fresher data.
- CSP without `unsafe-inline` for scripts, `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy`,
  CSRF origin checks, a request id on every response, uniform error shape, non-root container.
- Uploads are re-encoded through Pillow (strips EXIF, neutralises polyglots), stored under opaque
  names, served through an authenticated route.
- Runbooks in `docs/runbooks/`; threat models in `docs/threat-models/`.

Phase 9 of the plan is a full adversarial security pass, including prompt-injection defences for
ingested text and a git-history secret scan. Until then, treat the posture above as *present but
unverified by an adversarial review*.

### Deployment notes

- Set `COOKIE_SECURE=true` behind TLS; enables Secure cookies and HSTS.
- **Egress allowlist**: restrict production ingestion to exactly `sec.gov`, `openfigi.com`,
  `finra.org`, `api.tiingo.com`, `hn.algolia.com`, `en.wikipedia.org`, `wikimedia.org`,
  `api.coingecko.com`, `oauth.reddit.com`, and your LLM provider host — at the network layer, so
  a compromised container cannot reach anything else.
- Back up Postgres daily and **test the restore**. Pin the base image by digest.
