# Getting the free keys

Four keys were requested on 2026-07-26: Reddit, SMTP, OpenFIGI and Google OAuth. All four are free.
Each section below is the exact click path, the exact `.env` lines, and the command that proves it
worked — because "did that actually work?" is the question `status` and `preflight` both leave
unanswered, and the answer used to be "wait and see if a panel fills in".

Everything goes in **`.env` at the repository root** (already gitignored — never commit it). After
editing, restart and verify:

```bash
docker compose up -d          # picks up the new environment
docker compose exec -T api python -m tradeos.cli check-source <name>
```

`check-source` makes a real call. It prints `OK` with what came back, `NOT CONFIGURED` with the
variables still missing, or `FAILED` with the reason. It never prints the credential itself.

---

## 1. Reddit — 3 minutes

The only connected source that measures **mood** rather than attention. Everything else on the
attention board counts how much a name is discussed; Reddit is the one that can tell you whether the
discussion is bullish or bearish.

1. Go to <https://www.reddit.com/prefs/apps> (log in first).
2. Click **create another app...** at the bottom.
3. Fill in:
   - **name**: anything, e.g. `rhumb`
   - **type**: select **script** — this matters. The other types use a different OAuth flow that
     this app does not implement.
   - **redirect uri**: `http://localhost:8000`
     This app never uses it — `client_credentials` has no redirect step — but Reddit's form will
     not submit without one.
4. Click **create app**.
5. Two strings you need, and the first one is easy to miss:
   - **client id** — the short unlabelled string directly **under the app name**, near the words
     "personal use script". It is *not* the app name.
   - **secret** — the field explicitly labelled `secret`.

```dotenv
REDDIT_CLIENT_ID=your_client_id_here
REDDIT_CLIENT_SECRET=your_secret_here
```

```bash
docker compose exec -T api python -m tradeos.cli check-source reddit
# OK — authenticated and read 1 post(s) from r/stocks
```

Then backfill some history: `docker compose exec -T api python -m tradeos.cli ingest-sentiment --source reddit`

---

## 2. SMTP — the one real blocker before other people use this

Without it, password resets and alert digests are **queued and never sent**. The app refuses to
half-send rather than silently dropping a reset link, which is the right failure — but it means a
user who forgets their password today cannot recover the account.

Any SMTP provider works. Two transactional emails is inside every free tier.
<https://resend.com> is the least friction (free tier, no card).

1. Sign up, verify your email.
2. Create an API key.
3. Either use the provider's SMTP bridge, or your own mailbox's SMTP settings.

```dotenv
SMTP_HOST=smtp.resend.com
SMTP_PORT=587
SMTP_USER=resend
SMTP_PASSWORD=your_api_key_here
MAIL_FROM=noreply@yourdomain.com
```

`MAIL_FROM` must be an address the provider will let you send as — with Resend that means a domain
you have verified with them, otherwise every send is rejected at the door.

```bash
docker compose exec -T api python -m tradeos.cli preflight     # reports SMTP as configured
```

Then test the whole path for real: use "forgot your password?" on the login screen and confirm the
mail arrives. Nothing short of a delivered message proves this one.

---

## 3. OpenFIGI — unlocks 19,851 hidden holdings

13F filings identify holdings by **CUSIP**, not by ticker. Without a mapping those rows exist in
the database and appear nowhere, because the product will not display a holding it cannot name.
That is currently 19,851 institutional holdings.

1. Go to <https://www.openfigi.com/api>.
2. Click **Get API Key** and sign up (free, no card).
3. Copy the key from your account page.

```dotenv
OPENFIGI_API_KEY=your_key_here
```

It works keyless at a low rate limit too — the key mainly raises the ceiling, so the backfill
finishes in a reasonable time rather than over days.

```bash
docker compose exec -T api python -m tradeos.cli resolve-cusips --limit 2000
docker compose exec -T api python -m tradeos.cli status        # the unresolved count should fall
```

---

## 4. Google OAuth — built, never once run against Google

"Sign in with Google" is fully implemented, its validation logic is tested, and **the handshake has
never been executed**. Until it is, it is untested authentication code. Email and password signup is
unaffected either way.

1. Go to <https://console.cloud.google.com/apis/credentials>.
2. Create a project if you have none.
3. **Configure the OAuth consent screen** first (External is fine). Add yourself as a test user.
4. **Create credentials → OAuth client ID → Web application**.
5. Under **Authorised redirect URIs** add exactly:
   - `http://localhost:8000/api/auth/google/callback` for local testing
   - and the same path on your real domain once deployed
   A mismatch here is the single most common failure, and Google's error names it plainly.
6. Copy the client ID and client secret.

```dotenv
GOOGLE_CLIENT_ID=xxxxx.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your_secret_here
```

There is no offline check for this one — the only proof is completing the flow:

```bash
docker compose up -d
# then open http://localhost:8000/auth and use the Google button end to end
```

Confirm it lands you signed in, and confirm signing out and back in still works. Report anything
that does not, because this path has never had a real user through it.

---

## After all four

```bash
docker compose exec -T api python -m tradeos.cli preflight
```

`preflight` is the production gate: it checks every required variable and every link in the
`EXPLAIN_PROVIDER` chain. The integration page at `/integrations` shows the same registry joined to
real feed health, so a source that is connected but not actually flowing still reads as a gap there
rather than a green tick.
