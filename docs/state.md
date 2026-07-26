# docs/state.md — where the work stands

Updated: 2026-07-26, **Phases 6, 7 and 8 complete**.
**Read this after `CLAUDE.md` and before `docs/plan.md` at the start of every session.**

---

## Resume in one minute

```bash
cd /path/to/receipts
git checkout phase/6-sections          # all work lives here; not yet merged to main
make dev                               # reload-in-place stack on :8000
make test                              # 527 pass, ~0.5s, offline
make lint                              # ruff, zero errors is the standard
```

Demo login `demo@tradeos.app` / `<generated at seed time>`. Surfaces: `/radar` `/globe` `/ledger`
`/exposure` `/crypto` `/news` `/brief` `/events` `/integrations` `/journal`.

**Verified state at handoff:** 527 tests pass · 0 lint errors · 0 console errors on the app
surfaces and the marketing site, checked in a headless browser · migrations through 030 · 60
tables. The marketing site is at <http://localhost:8000/site/> after `cd site && npm install` then
`make site`. `docs/deploy.md` is the deployment reference; `cli preflight` is its enforcer.

**Model prose is genuinely on again.** It was not, silently, for the whole of Phases 3–6 — see
B-23 in `docs/bugs.md`. If you change anything in the model path, confirm a running instance
returns `used_template: false` rather than trusting the suite, which runs on `template` by design.

---

## Current position

| Phase | Status |
|---|---|
| 0 — Audit | complete |
| 1 — Repair | complete |
| 2 — Ingestion spine | complete |
| 3 — Impact engine + Ledger | complete |
| 4 — Radar | core complete (threading, saved filters, alerts outstanding) |
| 5 — Globe | complete |
| 6 — Rework sections | complete (all eight) |
| 7 — Marketing site | complete — `site/`, served at `/site` |
| 8 — Accounts, limits, deployment | complete (OAuth built but never run against Google) |
| **9 — Security** | **not started — next, and it closes the build** |

Every phase has a report in `docs/progress/`.

---

## NEXT STEPS, in the order I would do them

### 1. Phase 9 — security

Threat model first. `/security-review` has already run twice this project and found a **real
vulnerability each time**, so budget for findings rather than a clean pass. Known work:
- Re-enable the `S608` ruff rule and replace f-string SQL with `psycopg.sql` composition
  (`pyproject.toml` documents exactly why it is off and what the invariant is).
- gitleaks over full history — wired into CI, never run locally.
- Adversarial authorization tests across every per-user object.

### 2. Carried over, not blocking anything

- **Phase 4 remainder**: saved filter sets, in-place threading of developing stories, subscribable
  alerts.
- ~~GDELT has never been observed ingesting.~~ **RESOLVED 2026-07-25** — it came back after the
  backoff elapsed. 4 events in the store and gdelt-sourced claims are now on the Radar and in the
  site's hero. The count is small; watch whether it keeps flowing rather than assuming it will.
- **Bluesky** as a real `SocialSource` — the interface exists, the implementation does not.
- **`/code-review` has never been run** on any phase diff. `/simplify` and `/security-review` were
  run on the Phase 6 diff.
- **No email verification and no password reset.** A new account is usable immediately with an
  unverified address. Not in the brief's Phase 8 list, so recorded rather than silently added.
- **Google sign-in has never been exercised against Google** — no credentials. Validation logic is
  tested; the handshake is not.
- **`GOOG`/`GOOGL` render as two board rows** for one company; needs share-class collapsing.

---

## Open questions for the owner

| # | Question | Blocks |
|---|---|---|
| 1 | **OpenRouter free key** (<https://openrouter.ai/keys>) — offered, not yet provided | Nothing, but Gemini's daily allowance ran out twice in one session and it is the real throttle on claim generation |
| 2 | Reddit free key (<https://www.reddit.com/prefs/apps>, type "script") | The only source that measures *mood* rather than attention |
| 3 | OpenFIGI free key (<https://www.openfigi.com/api>) | 19,851 unmapped 13F holdings, invisible everywhere |
| 4 | The six ASK rulings in `docs/dead_code.md` | Cleanup only |

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

22. The data is real and substantial: 664,923 insider transactions, 51,099 stake events, 24,982
    institutional holdings. Weigh that in any rewrite-vs-extend call.

---

## What the product actually does now

So a fresh session knows what it is resuming, not just where the files are.

**Radar** is the landing surface: interpretations ranked by personal relevance, leading with the
consequence rather than the headline, confidence always visible, disagreements surfaced.

**The Ledger** publishes **41% of 282 resolved calls**, misses first, with calibration (said 38% →
landed 40%). Broken down by origin so the signal plane and the model are never pooled.

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
