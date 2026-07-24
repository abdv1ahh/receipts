# TradeOSS — Go-Live Guide

Everything is built and on **PR #1** (branch `game-changer`). This is the copy-paste path from
"code on a branch" to "live product people can use, free." No Stripe needed yet — billing runs in a
free/test mode with the payment UI visible; you flip on real payments after launch (§5).

---

## 1. Merge PR #1

**GitHub UI (simplest):**
1. Open the PR: https://github.com/DoubleX11/tradeos/pull/1
2. Click **Merge pull request** → **Confirm merge**. (Use **Squash and merge** if you want one clean
   commit on `main`; a regular merge keeps the full slice-by-slice history.)
3. `main` now has the entire platform + redesign.

**Or from the terminal (GitHub CLI):**
```bash
gh pr merge 1 --squash --delete-branch   # or --merge to keep history
```

After merging, deploy from `main`:
```bash
git checkout main && git pull
```

---

## 2. Deploy

The whole app is one Docker Compose stack (API + Postgres). On the server:
```bash
docker compose up -d --build        # build image + start db + api
docker compose exec -T api python -m tradeos.cli migrate   # apply DB migrations (001–018)
```
App is served at `http://<host>:8000`. Behind TLS, set `COOKIE_SECURE=true` in the api environment.

`.env` must have `SEC_USER_AGENT="TradeOSS you@yourdomain.com"` (SEC fair-access requires a contact).
`TIINGO_API_KEY` (free tier) enables backtest prices; `GEMINI_API_KEY` + `EXPLAIN_PROVIDER=gemini`
enable the AI prose (guarded, with a deterministic fallback if unset).

---

## 3. Seed the accounts

**Demo login (for showing the product) — Pro, no MFA, pre-populated:**
```bash
docker compose exec api python -m tradeos.cli seed-demo
```
Logs in at `/` with:
- **email:** `demo@tradeos.app`
- **password:** `<generated at seed time>`

It's tier **pro** (all features, no charge) and comes with a handle, journal trades (some public), a
portfolio, and a watchlist so nothing looks empty. Override with `TRADEOS_DEMO_EMAIL` /
`TRADEOS_DEMO_PASSWORD` env vars before running if you want your own creds.

**Admin (moderation / flags / audit) — requires an authenticator app (TOTP):**
```bash
TRADEOS_ADMIN_PASSWORD='pick-a-strong-one' \
  docker compose exec api python -m tradeos.cli seed-admin --email you@yourdomain.com
```
It prints a TOTP secret + `otpauth://` URI — add it to Google Authenticator/1Password. Admin login
needs email + password + the 6-digit code (admins can't log in without MFA, by design).

**Invite codes (registration is invite-gated):**
```bash
docker compose exec api python -m tradeos.cli create-invites --n 20
```
Share a code so people can sign up. (Every referral link also opens signup + grants the inviter credit.)

---

## 4. Update all the data

Fresh filings → signals → calibration, plus attention + prices. Run this whole block (safe to re-run;
each day de-dupes). Replace the dates with "recent window up to today":
```bash
X="docker compose exec -T api python -m tradeos.cli"
$X sync-tickers
$X backfill-13dg  --from 2026-07-14 --to 2026-07-22
$X backfill-form4 --from 2026-07-14 --to 2026-07-22
$X resolve-entities
$X ingest-13f --date 2026-07-21 --limit 60
$X resolve-cusips --limit 700
$X ingest-short-interest --start 2026-07-01
$X compute-signals
$X ingest-prices --symbols-from-clusters --start 2026-01-01   # needs TIINGO_API_KEY
$X run-backtest
$X ingest-sentiment --source hn --limit 40                    # Hacker News, no key needed
$X sync-library
$X status                                                     # confirm freshest records advanced
```
For a **deep, publishable calibration sample** (hours; do once before a public launch):
`make backfill-full` (24-month backfill), then `compute-signals`, `ingest-prices`, `run-backtest`.

Keep it fresh on a schedule (cron / GitHub Action) — e.g. daily `backfill-*` for yesterday +
`compute-signals` + `run-backtest`, and `ingest-sentiment` a few times a day.

---

## 5. Billing: free now, real payments later

Right now the app is in **free launch mode**: while `STRIPE_SECRET_KEY` is unset, **every new signup
gets full Pro access at no charge**, and the pricing page still shows the plans + Upgrade button (labeled
"test mode · no real charge"). Nothing is gated. This is what you asked for.

When you're ready to charge (after launch), it becomes real with **no code change** — just set env:
```
STRIPE_SECRET_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_PRICE_RETAIL=price_...   # your $29 plan price id
STRIPE_PRICE_PRO=price_...      # your $99 plan price id
```
and add `stripe` to `requirements.txt`, then rebuild. The moment the key is present: new signups
default to the free tier again, the 48-hour delay + tier limits apply, and Upgrade routes to real
Stripe Checkout (card data never touches the server; webhooks are signature-verified + idempotent).

---

## 6. Optional — connect more (all free)

- **Reddit sentiment:** create a free "script" app at reddit.com/prefs/apps → set `REDDIT_CLIENT_ID`
  + `REDDIT_CLIENT_SECRET`. **YouTube:** a free Data API v3 key → `YOUTUBE_API_KEY`. Until set, those
  sources honestly read "not connected" (never faked). Hacker News works with no key.
- **Congress / short-interest** convergence inputs are env-gated (`ENABLE_CONGRESS`,
  `ENABLE_SHORT_INTEREST`) and off by default pending clean licensed sources.

---

## Quick reference

| Thing | Command |
|---|---|
| Deploy | `docker compose up -d --build` then `… cli migrate` |
| Demo login | `… cli seed-demo` → `demo@tradeos.app` / `<generated at seed time>` |
| Admin | `… cli seed-admin --email you@…` (prints TOTP) |
| Invites | `… cli create-invites --n 20` |
| Refresh data | the block in §4 |
| Go paid | set `STRIPE_*` env + add `stripe` to requirements + rebuild |
