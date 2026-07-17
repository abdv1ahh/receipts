# TradeOS — Slice 1: skeleton + Form 4 pipeline

Real ingestion of real SEC Form 4 filings into a point-in-time Postgres store,
with an API exposing feed freshness. No fabricated data anywhere; test fixtures
are clearly fictional and never enter the database.

## Run it (10 minutes)

Prerequisites: Docker with Compose, or Python 3.12 + a local Postgres.

```bash
cp .env.example .env
# edit .env: set SEC_USER_AGENT to "TradeOS your@email.com" (SEC requires a contact)

docker compose up -d          # starts Postgres + API on :8000
```

Apply migrations and ingest one real day of filings (run inside the api container
or locally with the venv, DATABASE_URL pointing at localhost):

```bash
docker compose exec api python -m tradeos.cli migrate
docker compose exec api python -m tradeos.cli ingest-form4 --date 2026-07-10 --limit 25
docker compose exec api python -m tradeos.cli status
```

Then open http://localhost:8000/api/feeds — you are looking at the seed of the
product's honesty surface: real record counts, real freshness, real reject counts.

Backfill a range (respects EDGAR throttling; a full day is a few minutes):

```bash
docker compose exec api python -m tradeos.cli backfill-form4 --from 2026-06-01 --to 2026-07-14
```

## Run the tests

```bash
pip install -r requirements.txt
python -m pytest tests/ -q      # 13 tests, all offline, no network needed
```

## Local (no Docker)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export DATABASE_URL=postgresql://tradeos:${POSTGRES_PASSWORD}@localhost:5432/tradeos
export SEC_USER_AGENT="TradeOS your@email.com"
python -m tradeos.cli migrate
python -m tradeos.cli ingest-form4 --date 2026-07-10 --limit 25
uvicorn tradeos.app:app --reload
```

## What is in here

- `tradeos/ingestion/edgar_client.py` — throttled, allowlisted, checksummed EDGAR fetcher
- `tradeos/ingestion/form4.py` — index/submission/XML parsing + validation (XXE-safe)
- `tradeos/ingestion/runner.py` — idempotent day-level ingestion with loud rejects
- `tradeos/migrations/001_init.sql` — append-only raw layer (trigger-enforced), PIT derived table
- `docs/decision-log.md` — every consequential decision, veto by number
- `docs/threat-models/form4.md` — written before the pipeline, per the mandate

## Point-in-time discipline (the one thing to internalize)

Every insider transaction row carries two times: `event_time` (when the insider
traded) and `knowable_time` (when the filing became public at the SEC). All signal
computation and every backtest queries through `knowable_time` only. This is what
makes look-ahead leakage structurally impossible rather than merely avoided.

## Full demo (all slices)

```bash
make demo    # builds + loads a quick data window, computes signals, backtests, seeds invites
docker compose exec api python -m tradeos.cli seed-admin --email you@example.com   # prompts for password
```

Then open http://localhost:8000. See `docs/demo-script.md` for the investor walkthrough and
`docs/decision-log.md` for every consequential decision (37 entries).

## Auth, entitlements, security (Slice 6)

- Invite-gated registration; argon2id passwords; SHA-256-hashed session tokens in
  HttpOnly/SameSite=Lax cookies; per-IP+per-account login rate limits; TOTP required for admin.
- The free tier sees signals on a **48-hour delay enforced as a server-side WHERE clause** — no
  request parameter can reach fresher data (the anti-exfiltration floor).
- Security headers (CSP, X-Frame-Options DENY, X-Content-Type-Options, Referrer-Policy), CSRF
  origin checks, uniform error shape, and a non-root container image.
- Runbooks in `docs/runbooks/`; staff-trading policy template in `docs/staff-trading-policy.md`.

### Deployment notes (production)

- Set `COOKIE_SECURE=true` behind TLS (Caddy/Railway/host TLS); enables Secure cookies + HSTS.
- **Egress allowlist**: production ingestion should be restricted to exactly `sec.gov`,
  `openfigi.com`, `finra.org`, `api.tiingo.com`, and the LLM provider host
  (`generativelanguage.googleapis.com`) — set this on the host/network layer so a compromised
  container cannot reach anything else.
- Back up Postgres daily and **test the restore** (an untested backup is not a backup). Pin the
  base image by digest.
