# Phase 9 — security · progress report

Date: 2026-07-26 · Branch: `phase/6-sections` · 544 tests pass · 0 lint errors

The phase that closes the build. The brief says to approach it as an adversary would rather than as
a checklist, and to **report honestly at the end, including what could not be fixed**. That list is
at the bottom and it is not short.

---

## The one that mattered

**Pillow 10.4.0 carried six advisories, and Pillow is where a stranger's bytes meet a parser.**

`_store_image` accepts an upload and calls `Image.open`, which sniffs the format from the bytes.
Two of the six were memory-safety bugs in the **PSD decoder** — an out-of-bounds write
(PYSEC-2026-2249) and a memory-corruption path (PYSEC-2026-2252) — both reachable by uploading a
crafted PSD to a trade. Nothing in the product wants PSD. Nothing asked for it either; the decoder
was reachable simply because no one had said which formats were wanted.

Two fixes, because the upgrade alone only closes the bugs that are already public:

1. **Pillow 10.4.0 → 12.3.0.**
2. **`_store_image` refuses any format outside {PNG, JPEG, WebP, GIF}**, checked against the header
   *before* anything calls a decoder — `verify()` and `convert()` both decode, so checking
   afterwards would mean the vulnerable path had already run. The PSD, FITS, PCF and BDF decoders
   are now unreachable from an upload regardless of what is found in them next.

Verified: a PNG is accepted, a PPM is refused by format, malformed bytes raise and the route
returns a clean 400 rather than a 500.

---

## SQL: from safe-by-review to safe-by-construction

`S608` (SQL built by string concatenation) had been suppressed since Phase 1, with a note saying
all sites interpolated only module constants, generated placeholders, or a table name from a
hardcoded allowlist. That note was accurate. It is also exactly the kind of guarantee that decays,
because it holds by *having been read once*.

**All 25 sites now compose with `psycopg.sql`** — `Identifier`, `Placeholder`, `SQL` — and the rule
is back on. The next f-string SQL in this repository is a lint failure rather than a discussion.

Two were more than mechanical:

- `admin.resolve` chose a table name from a two-value allowlist **eight lines above** the
  interpolation. Never injectable; but the check and the use being that far apart is precisely
  where this class of bug lives, and `Identifier()` makes the guarantee survive someone moving the
  check.
- `authn._create_session` built a session lifetime as `interval '{SESSION_HOURS} hours'`. Now
  `make_interval(hours => %s)` with a bound parameter. A session lifetime is not somewhere to leave
  a string-built query.

Tests cannot catch a broken query here, so every rewritten path was exercised against the live
database: trades list and detail, the Ledger's four breakdowns, the brief upsert, ticker search,
the community feed, the assistant's library lookup, admin user search, and both branches of the
news adapter — the one query I did break mid-edit, and which two greens and a passing suite would
not have revealed.

One suppression remains, scoped to `tests/*`: `test_slice2.py` builds a **regex** asserting every
migration registers its own version, and ruff cannot tell an assertion about SQL from SQL.

---

## Authorization, tested adversarially rather than structurally

The suite had authorization tests, and all of them checked the *shape* of the code — that a route
mentions `user_id`, that `_require_admin` is branched on correctly. Useful, and not adversarial.
The two disagree exactly when it matters: when a guard exists, looks right, and is bypassable.

`tests/test_authz_adversarial.py` creates two real accounts, gives one of them private objects
through the real API, and has the other try to read them. **17 attempts, all refused**: the trade,
its world context, its AI analysis, its chart image, editing it, deleting it, the similar-trade
cohort, the portfolio, deleting the portfolio, the watchlist, the journal report, the performance
summary, every one of those anonymously, five admin routes, the four public endpoints, and a forged
session cookie.

These are **the only tests in the suite that touch a database.** The rest is pure and offline and
that is worth protecting, so the file skips cleanly when no database is reachable and removes every
row it creates.

Two things it taught immediately:

- One assertion failed on `DELETE /api/portfolios/{id}`, which answers `{"removed": false}` with a
  200. The route was correct — nothing was deleted, and that response is identical to what a
  nonexistent id returns, which is the right amount to tell a stranger. **My test was checking the
  message instead of the effect.** It now asserts the object survived, which is strictly stronger.
- A negative test suite's characteristic failure is being vacuously green, so the first test
  asserts the setup actually created something.

---

## Rate limiting and cost

`/api/public/*` and `/api/ledger` answer anyone, take no session, and run real queries. Nothing
bounded them. Neither did anything bound the model paths — and Gemini's free daily allowance is
shared by every user, so one script exhausting it silences every AI surface for everybody until
midnight UTC. That is a bill and a shared resource, not a denial-of-service worry.

`ratelimit.py`: a sliding window (not a fixed one — a fixed window lets a caller spend a full
allowance at the end of one and the start of the next, doubling the rate at the worst moment),
applied in middleware before any work is done. 120/min public, 20/5min model, 30/hour uploads.
Measured: exactly 120 requests succeed, the 121st returns 429 with a correct `Retry-After`, and
authenticated surfaces are untouched.

**It is in-process**, which is honest for one container and wrong for several, and it says so in
its own docstring, in the threat model and in `docs/deploy.md`. The alternative is Redis — an
eleventh line in `requirements.txt` and a second thing to operate, for a product that has not
launched. The login path is deliberately not here: it is limited against a database table, which
survives restarts and is shared across replicas, because credential stuffing is worth paying for.

---

## Secrets, dependencies, headers

**gitleaks over all 53 commits: no leaks found.** It had been wired into CI since Phase 1 and never
actually run. It has now.

**`pip-audit`, `npm audit` on both front ends: zero known vulnerabilities**, after the Pillow
upgrade and a `pip` upgrade in the Dockerfile (build-time only, but a known-vulnerable tool in the
image makes every future audit noisy enough to stop being read).

Headers were already right and were re-verified rather than re-implemented: CSP `default-src
'self'` with no `unsafe-eval` and no third-party origin, `X-Frame-Options: DENY`,
`frame-ancestors 'none'`, `nosniff`, `no-referrer`, HSTS behind `COOKIE_SECURE`. The marketing site
loads no external script, font or image, so no visitor's IP reaches a third party.

`docs/threat-models/public-surface.md` is new — the surface Phase 7 created, modelled properly.

---

## A deployment bug found by accident

`docker compose build` had been failing since Phase 7 and nobody knew, because `make dev` serves a
bundle built on the host. The Dockerfile flattened `frontend/` into the workdir, so
`@import "../../shared/tokens.css"` resolved outside the build context. **The production image had
been unbuildable for two phases while every local check stayed green.** Fixed by mirroring the repo
layout in the build stage.

---

## What is NOT fixed

The honest list, which the brief asks for explicitly.

1. **Google sign-in has never been exercised against Google.** Its validation logic is unit-tested
   — audience, issuer, expiry, `email_verified`, one-time state, no merge-on-email — but the live
   handshake has never run. Treat it as untested auth code. Email and password signup is unaffected.
2. **No email verification and no password reset.** A new account is usable immediately with an
   unverified address, and a forgotten password is unrecoverable. Both are real gaps for real
   users. Neither is in the brief's scope for any phase, which is why they are listed rather than
   quietly added.
3. **The rate limiter does not survive a restart or a second replica.** Above.
4. **`X-Forwarded-For` is trusted for client identity**, so the limiter is bypassable if the app is
   ever reachable other than through the reverse proxy. Not a confidentiality control, ranked
   accordingly, stated rather than assumed.
5. **No CORS policy.** Correct while both bundles are same-origin; needed, narrowly, the moment the
   marketing site gets its own domain. Writing a permissive one under deadline pressure is the
   predictable failure.
6. **No caching on the public endpoints.** Every request runs its queries.
7. **No backup schedule.** The dataset took hours of rate-limited SEC backfill to build.
8. **No penetration test.** Everything above is my own review of my own code. `/security-review`
   has found a real vulnerability twice on this project, both times in code I had just written and
   believed was correct; the base rate for "the author found everything" is not good.
9. **Dependencies are clean as of today only.** The audit is a snapshot. CI runs `gitleaks`; it
   does not yet run `pip-audit` or `npm audit` on a schedule.

---

**Status: Phase 9 complete. All ten phases (0–9) are done.**

---

# Follow-up, same day: the gaps Phase 9 listed as not fixed

Three of the nine items above were closed after the report was written. The rest stand.

## Email verification and password reset (item 2) — done

The item most likely to hurt a real user first: an account was usable with an unverified address,
and a forgotten password was unrecoverable except by an operator editing the database.

Migration 031 (`auth_tokens`, `users.email_verified_at`), `tradeos/mail.py`, the token machinery in
`authn`, four routes, and two screens. Four properties, each with a test:

- **Hashed at rest, single-use, expiring.** Single use is enforced by the UPDATE itself —
  `used_at IS NULL` in the WHERE plus `RETURNING` — because a read-then-mark has a window where two
  concurrent redemptions both win, and for a reset token that is two people setting a password.
  Issuing a new token invalidates any unused one, so a second "reset my password" click does not
  leave the first link live.
- **The request routes cannot be used as a membership oracle.** Identical wording either way, one
  return statement, no branch on whether a token was issued.
- **A reset signs out every other session.** A reset is what someone does when they think the
  account is compromised; leaving the attacker's session alive makes it ceremonial.
- **A weak password is refused before the token is spent**, so one fat-fingered attempt does not
  burn the link.

Two things found by reviewing it as an attacker rather than as its author:

**The token was in the URL query string, and uvicorn logged it.** `GET /reset?token=…` in an access
log is a working password reset in a file that gets shipped to a log aggregator and kept for
ninety days. It is now in the URL **fragment**, which is never transmitted to the server, read by
the page and sent in a POST body — and scrubbed from the address bar once read.

**The response time answered the question the wording refused to.** Only a real address did any
work, so an existing account took 0.06s against 0.01s for a fake one — and that was *after* moving
the SMTP call to a background task. The whole operation now runs after the response: lookup, token,
send. Re-measured over five samples each: 0.012s vs 0.008s, which is noise.

A third came out of driving the flow twice in a browser rather than once: opening a second reset
link while the page is open is a fragment-only navigation, which does not reload the document, so
the screen kept the first token and rejected a link the user had just clicked. It listens for
`hashchange` now.

`ForgotPassword` also had to be wired into the login screen — the API existed and nothing pointed
at it, which would have made the whole feature invisible.

**Still open: SMTP is not configured**, so nothing can actually send. The machinery is built and
tested; it needs a provider, and `preflight` warns.

## Backups (item 7) — half done

`scripts/backup.sh`: `pg_dump -Fc`, a size floor so a truncated file is never mistaken for a
backup, retention that only matches its own filenames, and `--verify` restoring into a scratch
database. Measured on the real database: 5.2 GB, of which `raw_filings` is 4.7 GB — the SEC
payloads that cannot be refetched quickly — producing a ~2 GB dump, so 14 days of retention wants
about 30 GB. The dump was taken and its archive verified: 501 TOC entries, all 60 tables present.

**Nobody has installed the cron line.** A backup script that is never run is not a backup.

## GOOG/GOOGL (carried over since Phase 4) — fixed

The attention board keyed on ticker, so Alphabet appeared twice with its attention split between
the rows — and each half then measured against its own baseline, so a genuine spike could miss the
mention floor in both. It groups by company now: mentions and baselines add, sentiment merges
weighted by mentions, the displayed ticker is deterministic (shortest then alphabetical — "whichever
class has more mentions today" would let a row rename itself between refreshes), the merge is
disclosed rather than silent, and a ticker with no resolved entity is never merged into anything.

## Verified in the same pass

- **Migrations 001–031 apply cleanly to an EMPTY database** and re-run as a no-op. Never checked
  before; the whole schema had only ever been built incrementally.
- **The production image builds, serves, and runs as uid 10001.** `/health`, `/api/ledger` and `/`
  all answer from a container with no dev mounts.
- **All 37 CLI commands exist**; six (`ingest-form4`, `ingest-13dg`, `ingest-13f` and their
  `backfill-*` twins) were real but undocumented, and are now listed.
- Every count in `CLAUDE.md` and `docs/state.md` re-measured against the database and corrected.
