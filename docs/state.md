# docs/state.md — where the work stands

Updated: 2026-07-26, **Phase 6 complete**.
**Read this after `CLAUDE.md` and before `docs/plan.md` at the start of every session.**

---

## Resume in one minute

```bash
cd /path/to/receipts
git checkout phase/6-sections          # all work lives here; not yet merged to main
make dev                               # reload-in-place stack on :8000
make test                              # 486 pass, ~0.5s, offline
make lint                              # ruff, zero errors is the standard
```

Demo login `demo@tradeos.app` / `<generated at seed time>`. Surfaces: `/radar` `/globe` `/ledger`
`/exposure` `/crypto` `/news` `/brief` `/events` `/integrations` `/journal`.

**Verified state at handoff:** 486 tests pass · 0 lint errors · 0 console errors on eleven surfaces
checked in a headless browser · 601 events · 556 clusters · 357 claims · 323 scored outcomes ·
migrations through 028 · 57 tables.

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
| **7 — Marketing site** | **not started — next** |
| 8 — Accounts, limits, deployment | not started |
| 9 — Security | not started |

Every phase has a report in `docs/progress/`.

---

## NEXT STEPS, in the order I would do them

### 1. Phase 7 — the marketing site

`site/` as a **sibling Vite project** to `frontend/`, sharing `shared/tokens.css`. Not npm
workspaces — decided in `docs/plan.md` §6 and the reason still holds.

Hero is the live product. Then the daily real-event walkthrough, then **the public Ledger**, which
is now genuinely persuasive because it reads *41% of 282, with the misses shown*. Then the
personalisation globe demo, then FAQ with `FAQPage` structured data.

**Design direction is specified and non-obvious** — re-read `docs/tradeoss_veryimportant_prompt.md`
§13 before designing. It explicitly rules out the current defaults (cream + serif + terracotta;
near-black + one acid accent; broadsheet grid) and asks for a cartographic/instrumental vocabulary.
Present the token system for review **before** building.

### 2. Phase 8 — accounts, limits, deployment

Email + OAuth, sub-minute onboarding capturing country/currency/watchlist (the `user_profiles`
table and `PUT /api/profile/frame` already exist — onboarding just has to fill them), server-side
tier gating, and `docs/deploy.md`.

### 3. Phase 9 — security

Threat model first. `/security-review` has already run twice this project and found a **real
vulnerability each time**, so budget for findings rather than a clean pass. Known work:
- Re-enable the `S608` ruff rule and replace f-string SQL with `psycopg.sql` composition
  (`pyproject.toml` documents exactly why it is off and what the invariant is).
- gitleaks over full history — wired into CI, never run locally.
- Adversarial authorization tests across every per-user object.

### 4. Carried over, not blocking anything

- **Phase 4 remainder**: saved filter sets, in-place threading of developing stories, subscribable
  alerts.
- **GDELT has never been observed ingesting.** Adapter built, parsing covered by offline tests
  against real captured payloads, 429 backoff verified. My own unpaced probing throttled the IP;
  it now backs off six hours. Check `SELECT count(*) FROM events WHERE source='gdelt'`.
- **Bluesky** as a real `SocialSource` — the interface exists, the implementation does not.
- **`/simplify` and `/code-review` have never been run** on any phase diff.
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
    was written into the GDELT adapter and then violated twice — once in the news adapter, once
    when trying to use geography to corroborate cross-outlet clustering. The single most repeated
    mistake in this project.

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
