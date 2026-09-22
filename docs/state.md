# docs/state.md — where the work stands

## Updated 2026-09-22: PART E — the public record page

Branch `receipts-caller-path`. **991 tests** plus `make test-js`, lint clean, checked in a real
browser at 375px with no console errors and no horizontal overflow.

**What changed.** `/r/{handle}` was a card image and an "open the full record" link into the app.
A stranger following a shared link therefore clicked twice to see anything they could judge, and
landed inside the research terminal — eleven nav items that 401 for them, a search field, an
upgrade button and a bell. It is now the record itself, server rendered by `receipts/page.py`, with
no app chrome and exactly one outbound link in the document (`/claim`). A test asserts both.

**Server rendered rather than the bundle, and the reason is measured.** The app ships 434KB of JS
and 137KB of CSS for eleven surfaces this visitor will never open. The page is one document with
its stylesheet inline. Measured on a throttled phone (Slow 4G, 4x CPU, 375px): **TTFB 19 ms, first
contentful paint 620 ms, LCP 747 ms, fully loaded 1.22 s, CLS 0.00** — against a two second budget.
The document is 11.2KB compressed (111KB raw).

**The Verify button now runs in the VISITOR'S browser.** `/api/receipts/{handle}/chain` hands over
the sealed fields rendered by `chain.rendered_fields` and states no verdict; `receipts/verify.js`
does the SHA-256 and the chain walk on their machine. `/api/receipts/{handle}/verify` still exists
and is still tested — it is simply no longer what the public page rests on, because a server
answering `intact: true` about its own record is the operator asking to be trusted. Measured:
**323 links recomputed in 10–11 ms** in the browser; click to answer 1.6 s on Slow 4G, most of it
the deliberate readable replay. The panel also offers "Now show me it failing", which changes one
character in the browser and reruns the same code so the check is visibly capable of saying no.
What this does NOT close is in `docs/known_gaps.md` §5, and the caveat prints under every result.

**Compression was added on that measurement** (`GZipMiddleware`, Starlette, no new dependency).
The chain payload for our own record is 350KB of mostly prose uncompressed and 23.7KB compressed;
before it, the flagship interaction spent 2.5 s of its 3.4 s transferring. Production already
compresses at the edge (`deploy/Caddyfile`), so this changes nothing there — it makes the measured
number the one every deployment gets, including a bare `docker compose up` with no proxy.

**What `/code-review high` found, and what changed.** Seven findings, six acted on:

1. **`--reload-include '*.js'` was a no-op** and the comment claiming it fixed the stale-verifier
   trap was worse than the trap. It needs `watchfiles`, which is not a dependency; uvicorn logs
   *"...have no effect unless watchfiles is installed"* and falls back to `StatReload`. Replaced
   with an mtime-keyed cache in `app.py:_verify_js()`, then proved by editing the file with no
   restart and watching the served bytes change. CLAUDE.md §0y3.
2. **The verify panel could hang with no message.** Only the fetch was inside the `try`, so a throw
   in the hashing, replay or render left `busy` true and the button disabled forever. Concretely
   reachable: `crypto.subtle` is undefined outside a secure context, so on a plain-http LAN address
   every hash throws. Whole run guarded with `finally`, plus an up-front secure-context check that
   says *"nothing is wrong with the record — open this page over https"*. CLAUDE.md §0y4.
3. **`make test-js` was not run by anything automatic** — CI's pytest job has no database, so every
   test that would reach the verifier skipped. Added to the `web` job, which already has node.
4. **`verify.js`'s header claimed the Python suite runs it.** It cannot. Corrected in both places
   it was stated.
5. **GZip re-compresses the share card PNG.** Measured: 0.8ms to save 5.7% on 58KB. Kept, with the
   number written down; `compresslevel` dropped from Starlette's 9 to 6 on the same measurement
   (the record page: 12,149 bytes in 0.4ms against 11,620 in 1.5ms).
6. **The replay counter could contradict the result**, stopping at "400 of 1000" one beat before
   "all 1000 recomputed". The bar is now driven by the run's totals, not by the display sample.
7. **An unknown handle answered HTTP 200** while `/api/receipts/{handle}` answered 404 for the same
   input. Now 404 **with** the readable page: the status is for machines, the body is for people.

**Found separately, by probing edge cases the review did not reach:** `record._compute` returned
`expectancy_ci: [None, None]` for a caller past the gate whose resolved calls all carry a NULL
excess return. That crashed the public page with a TypeError and made the React surface print "this
sample does show an effect of not scored per call". It returns `None` now — one fix, both surfaces.

**Also guarded:** `make test` can never run the JavaScript half of the wire format, so `make
test-js` and a shared fixture exist — CLAUDE.md §0y2.

**Also:** `frontend/src/record.jsx` rendered open calls above the misses while its own comment said
the opposite. The losses now come first on both surfaces.

---

## Updated 2026-09-02: RECEIPTS SHIPPED, and it is now the product

Branch `receipts`, five commits, **818 tests**, lint clean, all 20 mechanical acceptance criteria
verified against the live system. `CLAUDE.md` §"What this is" is the short version; this section is
what a fresh session needs to know that is not in the code.

**What it is.** A public, permanent, chained record of market calls. A caller publishes a dated
directional call before the outcome is known; it is sealed into a per-caller SHA256 hash chain and
written to a table whose trigger refuses deletes and refuses updates to sealed columns. It resolves
automatically against Tiingo end-of-day prices, benchmarked to SPY, with a 2% noise floor. Below 25
resolved scoreable calls no hit rate is published at all.

**Verified against the live database, not asserted.** DELETE refused; every sealed column refused
on UPDATE; a resolved verdict refused on rewrite; the resolution columns still writable; a caller
who has published cannot be deleted. Corrupting one `content_hash` on `@convergence-v3` made
`/api/receipts/convergence-v3/verify` return `intact: false` at exactly `seq 100`, and restoring it
returned to intact over all 323 links.

**The house record is ours and it is unflattering, on purpose.** `seed-house-records` imported the
signal plane's own resolved claims — nothing invented, real `created_at` as `published_at`, real
verdicts from `claim_outcomes`, sealed in true chronological order:

| caller | calls | hit | miss | inconclusive | rate |
|---|---:|---:|---:|---:|---:|
| `@convergence-v3` | 323 | 115 | 167 | 41 | 40.8% of 282 |
| `@convergence-v4` | 150 | 63 | 67 | 20 | 48.5% of 130 |
| **pooled (the house figure)** | **473** | **178** | **234** | **61** | **43.2% of 412** |

z = −2.76, expectancy −1.18% with a 95% interval of [−2.93%, +0.57%] that spans zero, and 1,268
resolved calls needed to detect a 1% per-call edge against the 412 held. **Never present that as a
positive result.** `record.house_summary` pools the two versions and its docstring says why that is
legitimate (same scoring logic, v4's own changelog records "NO BEHAVIOURAL CHANGE").

**The gate is not demonstrated by the seed.** Both house records sit above 25 resolved calls, so
neither shows the Low N state. It appears the moment a human caller claims a handle, which is what
happens live in the demo. `/api/card/receipt/{handle}.svg` for a gated caller was verified to show
counts and the words Low N and no percentage at all.

### The one thing that is blocked

**The model chain has no working fallback.** `EXPLAIN_PROVIDER=gemini,openai`; the `openai` slot
points at GitHub Models, which answers **HTTP 410 `github_models_retirement_brownout`** on every
request. Gemini works but is at the edge of its free daily quota — it answered normally and then
429'd within the same minute during this session. Both links are now in `sources.CATALOG` with live
probes, so the integration page reports it instead of hiding it.

**To fix it, three environment variables in BOTH `.env` and `docker-compose.yml`** (the base compose
file enumerates every variable it passes; a key in `.env` alone does not reach the container):

```
OPENAI_BASE_URL=https://api.groq.com/openai/v1
OPENAI_API_KEY=<a free Groq key, no card, from https://console.groq.com/keys>
OPENAI_MODEL=<a currently available Groq model>
```

Then `docker compose up -d api worker` and confirm with `cli check-source llm_openai`.
No code change is needed: `llm._openai` already speaks to whatever `OPENAI_BASE_URL` names, and
`tests/test_llm.py` already exercises Groq and OpenRouter base URLs.

### Prior state

Updated: 2026-07-26. **All ten phases (0–9) are complete**, plus a cross-check pass the owner asked
for after reporting that "the website does not even load, the globe does not even load" and that
they could not find the marketing site. **That pass is written up in
`docs/progress/cross_check.md` — read it before trusting any "complete" above it**, because six of
the things it found were genuinely broken in the reader's face while every test passed.

**Read this after `CLAUDE.md` and before `docs/plan.md` at the start of every session.**

---

## Resume in one minute

```bash
cd /path/to/receipts
git checkout main                      # merged and pushed 2026-07-27 (367142e)
make dev                               # reload-in-place stack on :8000
make test                              # 637 pass, ~1s (17 need the local DB)
make lint                              # ruff, zero errors is the standard
```

Demo login `demo@tradeos.app` / `<generated at seed time>`. Surfaces: `/radar` `/globe` `/ledger`
`/exposure` `/crypto` `/news` `/brief` `/events` `/journal` `/community` `/integrations`.
`/` redirects a signed-out visitor to the marketing site at `/site/`.

**Verified state at handoff:** 637 tests pass · 0 lint errors · 0 console errors and **0 horizontal
overflow on all 21 app surfaces at 375 / 768 / 1280px**, plus the marketing site, checked in a real
browser · the 3D globe verified **rendering under actual WebGL** in headed Chromium, not merely
"no errors in headless" (headless has no GPU, which is exactly how the globe stayed broken) ·
migrations through **033** · 61 tables · the Ledger reads **43.2% of 412** (see §"Measured
figures" below — every row count in this document is dated, because undated ones went stale).

**The marketing site is at <http://localhost:8000/site/>, and `/` now redirects there** for anyone
signed out — it was previously reachable by no link from anywhere, which is why the owner could not
find it. `docs/deploy.md` is the deployment reference; `cli preflight` is its enforcer, and
`docs/progress/phase_9.md` §"What is NOT fixed" is the honest security list.

**Bluesky is live** — 16 curated consequential accounts, keyless, **2,147 events** ingested as of
2026-08-23 (55% of the whole spine, so half of what Radar ranks comes from one social source) and already
producing scored claims on the Radar. This is the brief's answer to X, which remains unavailable and
is now labelled as such *with the alternative named* rather than as a bare "unavailable".

**Model prose is genuinely on again.** It was not, silently, for the whole of Phases 3–6 — see
B-23 in `docs/bugs.md`. If you change anything in the model path, confirm a running instance
returns `used_template: false` rather than trusting the suite, which runs on `template` by design.

---

## Measured figures

**Every number here was measured against the live database on 2026-08-23. Quote them with that
date, and re-measure before quoting them anywhere a reader will act on them.** The previous set
sat undated in this file for four weeks while the database moved underneath it; two of the counts
had roughly doubled and the backup script was sizing a volume from figures that were half the
truth. Undated is how that happened, so the dates are not decoration.

| Figure | Value | Note |
|---|---:|---|
| Database on disk | **7.89 GB** (7,892,802,583 bytes) | 61 tables, migrations through 033 |
| `raw_filings` | **7.27 GB**, 531,898 rows | 92% of the database |
| `insider_transactions` | **759,698** | |
| `stake_events` | **135,925** | |
| `fund_holdings` | **24,982** | 17,298 resolved (69.2%, 77.1% by value); 7,684 unresolved — mostly ETPs the SEC ticker file does not carry. See B-14 |
| `events` | **3,879** | grows continuously while the worker runs |
| `claims` | **615** | 473 signal plane, 142 impact engine |
| `claim_outcomes` | **501+** | 178 hit · 234 miss · 61 inconclusive · 273 unscoreable |
| `country_exposure` | **10** | all populated and sourced |
| Ledger headline | **43.2% of 412** | z = −2.76; see §"What the product actually does now" |
| Impact engine | **9 open, 133 unscoreable, 0 resolved** | no accuracy figure exists for it |
| `pg_dump -Fc` output | **4.79 GB** | 14-day retention needs **67 GB** |

`events`, `news_items` and the `claim_*` tables move whenever the worker runs, so treat those four
as "as of", not as constants. The SEC tables only move during a backfill.

---

## Current position

| Phase | Status |
|---|---|
| 0 — Audit | complete |
| 1 — Repair | complete |
| 2 — Ingestion spine | complete |
| 3 — Impact engine + Ledger | complete |
| 4 — Radar | complete — threading, saved filters and alerts landed 2026-07-26 |
| 5 — Globe | complete |
| 6 — Rework sections | complete (all eight) |
| 7 — Marketing site | complete — `site/`, served at `/site` |
| 8 — Accounts, limits, deployment | complete (OAuth built but never run against Google) |
| 9 — Security | complete — see phase_9.md for what is NOT fixed |

**The ten-phase brief is finished.** What is left is listed below and in `docs/progress/phase_9.md`;
none of it is a phase.

Every phase has a report in `docs/progress/`.

---

## NEXT STEPS, in the order I would do them

### 1. Before real users

- ~~Email verification and password reset~~ **DONE 2026-07-26.** Hashed, single-use, expiring
  tokens; identical responses so the endpoints cannot be used to test whether an address has an
  account; the whole operation deferred off the request path so the response *time* cannot answer
  it either; the token in the URL **fragment**, never a query string, so it cannot reach an access
  log; a reset signs out every other session. Reachable from the login screen, and both screens
  driven end to end in a browser.
- ~~A backup schedule~~ **DONE 2026-08-23.** `scripts/backup.sh` exists, refuses to call a truncated
  dump a backup, prunes on retention, and `--verify` restores into a scratch database. It is now
  scheduled by a **launchd agent** (`~/Library/LaunchAgents/app.rhumb.backup.plist`, 03:15 daily),
  **not** by the cron line the script's header documents: macOS cron skips a run outright if the
  machine is asleep at the scheduled time, so on a laptop the cron entry would silently never have
  fired. launchd's `StartCalendarInterval` runs it on the next wake instead. The agent also sets
  `PATH` explicitly, because launchd starts jobs without `/usr/local/bin`, where the Docker CLI
  lives. On a Linux host the documented cron line is correct and should be used.
  **Still outstanding: the backups are on the same disk as the database**, so they protect against
  a bad migration or a dropped table but not against losing the drive. Only ~18 MB of the 7.89 GB
  is genuinely irreplaceable (everything else is refetchable from SEC EDGAR, at ~76 hours), so an
  offsite copy of that slice is cheap and is the obvious next step.
- **Exercise Google sign-in against Google.** Still untested auth code until someone does.
- **SMTP is not configured**, so verification and reset cannot actually send. The machinery is
  built and tested; it needs a provider (`SMTP_HOST`, `MAIL_FROM`) and `preflight` says so.
- ~~Run `/security-review`~~ **RUN 2026-07-26 on the cross-check diff**, and it earned its keep a
  third time: rendering `auth_error` (which nothing had ever read) let anyone put arbitrary
  official-looking text on the real login page, and `_fail(str(exc))` reflected internal
  exception detail through the URL bar. Both fixed — the handler now emits a CODE and the client
  renders only codes it recognises. **Still not run over the code that predates this branch.**

### 2. Deploy it

`docs/deploy.md` is written and has never been executed against a real host. First run should
correct it in the same change that discovers a mistake.

### 3. Carried over, not blocking anything

- ~~Phase 4 remainder~~ **DONE 2026-07-26.** Saved filter sets (five dimensions, previewed live
  while editing, addressable), in-place threading (a cluster that gains sources is re-read, and the
  card carries the earlier readings — *a superseded claim is still scored, so revising can never
  erase a miss*), and subscriptions by email or webhook with a hard throttle. The webhook is a
  user-supplied URL the server fetches, so `radar.webhook_target_ok` refuses non-https, private,
  loopback, link-local and metadata addresses on every resolved IP, re-checks at send time, and
  refuses redirects.
- ~~GDELT has never been observed ingesting.~~ **RESOLVED 2026-07-25** — it came back after the
  backoff elapsed and it has kept flowing — **284 events** as of 2026-08-23 (22 on 2026-07-26, up
  from 4 the day before), with gdelt-sourced claims on the Radar and in the marketing site's hero.
- ~~Bluesky as a real `SocialSource`~~ **DONE 2026-07-26.** 16 curated accounts, each verified
  against the live API before seeding, keyless, feeding the spine hourly. Note for anyone
  extending it: `searchPosts` 403s without auth, so network-wide search is not available.
- **`/code-review` has still never been run.** `/simplify` was run on the cross-check diff and
  found a real one: `pct` was duplicated across three surfaces and the fourth copy dropped the
  ×100, so the community feed published a +10% trade as "+0.1%". Formatters now live in
  `frontend/src/format.js`.

- **Google sign-in has never been exercised against Google** — no credentials. Validation logic is
  tested; the handshake is not.
- ~~`GOOG`/`GOOGL` render as two board rows~~ **FIXED 2026-07-26.** The attention board groups by
  company (entity), not ticker: mentions and baselines merge, sentiment merges mention-weighted,
  the displayed ticker is deterministic (shortest then alphabetical, so GOOG/FOX/BRK.A), the merge
  is disclosed rather than silent, and an unresolved ticker is never merged into anything.

---

## Open questions for the owner

| # | Question | Blocks |
|---|---|---|
| 1 | **OpenRouter free key** (<https://openrouter.ai/keys>) — offered, not yet provided | Nothing, but Gemini's daily allowance ran out twice in one session and it is the real throttle on claim generation |
| 2 | **Four keys the owner agreed to create 2026-07-26**: Reddit, SMTP, OpenFIGI, Google OAuth. Step-by-step in **`docs/runbooks/keys.md`**, each verifiable with `cli check-source`. | Reddit = mood; SMTP = password reset can actually send (the real blocker before other users); OpenFIGI = 19,851 invisible holdings; Google = untested auth code |

~~The six ASK rulings in `docs/dead_code.md`~~ **ALL RESOLVED 2026-07-26.** Short interest kept and
parked; ENABLE_CONGRESS removed (migration 033); the Stripe and `test_gemini.py` entries turned out
to be audit errors, not debris; `uploads/` was already gone. The community surface was rebuilt
rather than deleted, on the owner's ruling.

## Decisions already taken

- **Display name: Rhumb.** `BRAND_NAME` config value. `TradeOSS` stays the internal codename;
  nothing is renamed for branding.
- **Portfolio → Exposure**, approved, with the shadow-vs-SPY track record salvaged into the Ledger.
- **Provider: Gemini free tier**, chain-configured (`EXPLAIN_PROVIDER=gemini,openai`).
- **PostgreSQL, not SQLite** (contra the brief — reasoned in `docs/plan.md` §1).
- **Extend the existing scheduler**, never build a second worker.

---

## Things learned that are not obvious from the code

Ordered roughly by how much time they would cost to rediscover.

0. **A fallback indistinguishable from success is an outage with good manners.** Six call sites
   gated their model call on `provider in ("gemini", "openai")` — False for the chain form
   `gemini,openai` that production runs — so every AI prose surface served its deterministic
   template for three phases while reporting the model had been tried (B-23). Nothing crashed and
   no test failed: the suite runs on `template` by design, and a template *is* a legitimate
   output. Two lessons. First, wherever a path can degrade silently, something must assert which
   path actually ran — ask a running instance, not the suite. Second, a config value with a
   documented parser has exactly one place it may be parsed; `llm.wants_model()` now exists so the
   gate and the call cannot disagree about what is configured.

0b. **A module and a route handler can share a name, and Python will not warn you.** `def
   onboarding(...)` as a FastAPI handler shadowed the `onboarding` module the moment Phase 8
   imported one, turning every `onboarding.state(...)` into an AttributeError on a function. The
   identical mistake then happened in JavaScript, where `fetchOnboarding` already existed. Name
   handlers for what they DO, not for their route path — and note that no test caught either one;
   both surfaced within a minute of using the feature.

1. **The "AI never sees my screenshot" bug was not a transport bug.** `directive_guard` banned
   "target price" — which the prompt itself asks the model to discuss — and one tripped field
   discarded the whole read. The fallback then blamed a missing provider. (Same family as #0: the
   guard was right to fire and the *message* was the lie.)

2. **My Phase 0 root cause for the attention board was wrong.** I blamed Wikipedia title
   resolution; the titles are correct. The real causes were a fuzzy Algolia query and a
   double-counting error in the board's own scoring. Measure before concluding.

3. **`str.replace` cannot sanitise a delimiter.** Single pass, no re-scan, so a marker split around
   a nested copy of itself reassembles. The prompt fence uses a **per-request nonce** — do not
   "simplify" it back to fixed markers. Found by `/security-review` on my own code.

4. **Azure's content filter classifies text that QUOTES prompt-injection examples as a jailbreak**
   and 400s the request. Our own defence made the provider unusable. Describe the rule in the
   abstract; a test asserts no attack strings return.

5. **Gemini's `maxOutputTokens` counts hidden reasoning.** Measured 769–1360 thinking tokens for one
   chart, so a caller asking for 800 gets truncated JSON. `THINKING_HEADROOM` pays for it.

6. **`thinkingConfig` 400s on every Gemini model newer than 2.5.** Sending it pinned the app to
   legacy models. Do not reintroduce.

7. **Gemini quota is per model and has a real daily ceiling.** `gemini-2.0-flash` has a zero
   free-tier allowance; `gemini-2.5-*` are closed to new keys. Use `gemini-flash-latest` (DEEP) and
   `gemini-flash-lite-latest` (FAST).

8. **httpx puts the full request URL, query string included, in exception messages.** Any API
   authenticated with `?key=` leaks its credential through an unhandled error. `scheduler.redact()`
   strips query strings before anything is stored or logged. Keep the invariant.

9. **GDELT's throttle is keyed on the User-Agent, not the IP.** Rotating it *would* restore access;
   we deliberately do not, and `tests/test_gdelt.py` asserts the module still explains why.

10. **`geo` on an event is where the OUTLET sits, not what the story is about.** This distinction
    was written into the GDELT adapter and then violated three times — the news adapter, an attempt
    to use geography to corroborate cross-outlet clustering, and **relevance ranking itself**,
    found in Phase 7. The third was the worst: personal relevance scored on the publisher's
    country, so a reader in Tokyo and a reader in São Paulo were shown nearly the same order,
    differing only by a rounding of the same US-centric number. The entire personalisation promise
    was quietly not working, and it took building a page whose whole job is to *demonstrate* that
    promise to notice.

    **It is fixed at the root now**: `relevance.places()` derives the countries from what a claim
    AFFECTS via `geography.countries_for`, falling back to the outlet's `geo` only when nothing
    maps, so no caller has to remember the rule. Three tests hold it. If you add a fourth consumer
    of `geo`, this is still the mistake you are about to make.

11. **Cross-outlet clustering needs shared PROPER NOUNS**, not title similarity and not geography.
    Two reports of one event share who and where; two unrelated ones share topic vocabulary.

12. **SEC filing headlines are templated**, so trigram similarity matches the template rather than
    the story. Cluster matching requires shared entities when both sides name any.

13. **`_require_admin` returns the USER on success and None on failure.** Branch on
    `if not _require_admin(...)`. Getting it backwards serves admin data to everyone, silently.
    `tests/test_sources.py` asserts every call site uses a safe shape.

14. **A threshold that fires on everything is as useless as one that never fires.** The crypto
    positioning read was calibrated wrong in both directions against live data before it
    discriminated. Measure against real data before trusting a threshold.

15. **Every migration file must INSERT its own version row** into `schema_migrations`; the runner
    does not. A file that forgets re-runs and fails with "relation already exists".

16. **Frontend changes need `make web`** (0.3s) under `make dev`, or a full image rebuild otherwise.

17. **The browser check catches what tests do not.** A missing `Icon` import passed 435 tests and
    threw `ReferenceError` on the page. Run both gates.

18. **Clusters re-derive their category from members.** Without that, improving the classifier and
    reprocessing creates duplicate clusters instead of correcting existing ones.

19. **A source that no-ops because it is unkeyed still records `status: ok`** in `job_runs`.
    `sources.health()` deliberately does not count that as a successful fetch.

20. **The impact engine has NO template fallback, on purpose.** Every other AI path degrades to
    deterministic output. This one writes nothing, because a fabricated claim inside a ledger built
    to measure honesty would poison the only thing that makes it defensible.

21. **`= ANY(%s::record[])` fails** — psycopg cannot bind an anonymous composite type. Use two
    parallel arrays with `unnest(%s::text[], %s::text[])`.

22. The data is real and substantial: **759,698 insider transactions, 135,925 stake events, 24,982
    institutional holdings** (measured 2026-08-23). Weigh that in any rewrite-vs-extend call.
    See §"Measured figures" for the rest, and quote figures from there with their date.

---

## What the product actually does now

So a fresh session knows what it is resuming, not just where the files are.

**Radar** is the landing surface: interpretations ranked by personal relevance, leading with the
consequence rather than the headline, confidence always visible, disagreements surfaced.

**The Ledger** publishes **43.2% of 412 scoreable calls** (178 hit / 234 miss), misses first — and
**expectancy −1.18% per call with a 95% interval of [−2.93%, +0.57%], which spans zero**. On 412
calls the signal shows **no edge in either direction**; an earlier note here called it a failure,
which the sample does not support. The frequency IS below chance (z = −2.76) while the wins exceed
the losses, so returns cancel. At the measured 18.17% dispersion, detecting a 1% per-call edge would
take **1,268** resolved calls. All figures measured 2026-08-23; the earlier "41% of 282" was the
same ledger before the sample grew, and `docs/progress/cross_check.md` had already recorded 43.2%
of 412 on 2026-07-26 — this file simply never picked it up.

All 412 belong to the signal plane, split across two version rows: **`convergence-v3` (115/282 =
40.8%) and `convergence-v4` (63/130 = 48.5%)**. These are **the same scoring logic** — v4's own
`signal_definitions` changelog records "NO BEHAVIOURAL CHANGE", re-registering identical logic after
a Phase 1 lint pass changed the module hash and silently froze `compute-signals` from 2026-07-25.
**Pooling them into one 43.2% is therefore legitimate**, and the gap between the two is sample and
period, not model. Do not present them as two signals.

**The impact engine still has zero resolved calls and no accuracy figure**, and no surface may imply
otherwise. As of 2026-08-23 it holds **9 open and 133 unscoreable** claims — the unscoreable count
rose from 14 on 2026-08-21 when `measure_claims` ran, so of 142 model-written claims **133 could not
be scored at all**. That is a finding about the engine, not a gap in the ledger, and it is the
number to watch. `open_by_origin` exists so every surface can say whose record it is showing.

**The World** places events by what their claims *affect*, with 62 sourced trade corridors; 3D
lazy-loaded behind WebGL detection, flat map otherwise.

**Exposure** answers what a broker cannot: which live events reach your holdings, through which
name, by what mechanism.

**Crypto** reads positioning — funding, open interest, crowding — with an invalidation condition on
every reading.

**News** compares how outlets in different countries frame the same event, and flags thin coverage.

**Morning Brief** opens by scoring yesterday's calls before telling you anything new.

**The Assistant** has six read-only tools and answers "how often are you right?" by reading the
Ledger.

**The Journal** freezes the Radar at the moment a trade is logged — which interpretations were
live, and whether any named the same instrument pointing the other way. The coach reads that
across trades, so it can speak to *process* ("1 of 6 entries went against a live interpretation")
rather than only to outcome. Every disagreement it reports carries the Ledger's own 41% beside it,
because the system is not the benchmark.
