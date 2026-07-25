# docs/state.md — where the work stands

Updated: 2026-07-25, end of Phase 4 (core).
Read this after `CLAUDE.md` and before `docs/plan.md` at the start of every session.

---

## Current phase

**Phases 0–3 complete. Phase 4 core complete.** Branch `phase/3-claims`.
**Phase 5 (the globe) is next.** Reports for every phase are in `docs/progress/`.

Outstanding inside Phase 4: saved filter sets, in-place threading of developing stories, and
subscribable alerts. The Radar surface itself, its relevance ranking, its filters and the
dashboard tile are done.

---

## Finished

**Phase 0 — audit.** `CLAUDE.md`, `docs/audit.md`, `docs/bugs.md` (21 defects),
`docs/dead_code.md`, `docs/plan.md`, `docs/progress/phase_0.md`.

**Phase 1 — repair.** Full report in `docs/progress/phase_1.md`. Headlines:

- Journal chart coach fixed and verified live against the real stored screenshot.
- LLM transport rebuilt as a provider chain; switched off GitHub Models before its 30 July
  shutdown; Gemini free tier confirmed working.
- Attention board's real bug found and fixed (my Phase 0 root cause was wrong — see below).
- Routing, error boundaries, source gates, integration status page, honest data age.
- Ruff + CI + 222 tests, zero lint errors.
- A vulnerability in my own new endpoint found by `/security-review` and fixed.

**Phase 2 — the ingestion spine.** Full report in `docs/progress/phase_2.md`. Headlines:

- Migration 024: `events`, `event_clusters`, `watchlist_accounts`, `source_calls`.
- `spine.py` — normalise, cluster (trigram, not embeddings), score novelty and velocity.
- GDELT wired as the global backbone; existing news adapted in rather than duplicated.
- Influence watchlist as first-class editable data with an admin API.
- 268 tests. Three bugs found by real data, plus an authorization bug I introduced and caught.

## Half finished

**GDELT has never been observed ingesting.** The adapter is built, its parsing is covered by
offline tests against real captured payloads, and its 429 backoff is verified — but my own
unpaced probing throttled this IP for the rest of the phase, so no article has landed in
`events` yet. The hourly scheduler job will confirm it once the limit clears; check
`/api/integrations` or `SELECT count(*) FROM events WHERE source='gdelt'`.

**Phase 3 + 4 core.** Full report in `docs/progress/phase_3_4.md`. Headlines:

- Migration 025: `claims`, `claim_outcomes`, `country_exposure`, `user_profiles`.
- `claims.py` — the impact engine. Rejects any "mechanism" that names a direction without a
  channel, and writes NOTHING rather than falling back to a template.
- `ledger.py` — outcome measurement vs SPY with a noise floor; `unscoreable` counted, not dropped.
- `relevance.py` — personal ranking, no model involved.
- Radar and Ledger surfaces; Radar is now where a signed-in reader lands.

## Next three tasks

1. Open `phase/5-globe`, plan mode first. `react-globe.gl`, lazy-loaded, country selection
   setting the app-wide geographic frame (the `user_profiles.country` written by
   `PUT /api/profile/frame` already IS that frame — the globe replaces the control, not the
   concept).
2. Finish Phase 4's remainder: saved filter sets, in-place threading, subscribable alerts.
3. Run `/security-review` on the Phase 2–4 diff. It found a real vulnerability on Phase 1 and has
   not been run since.

Carried over, not blocking: confirm GDELT ingests once its rate limit clears, and add Bluesky as
a real `SocialSource`.

## Open questions waiting on the owner

| # | Question | Blocks |
|---|---|---|
| 1 | Reddit free key (<https://www.reddit.com/prefs/apps>, type "script") | B-13 — the only source that measures mood |
| 2 | OpenFIGI free key (<https://www.openfigi.com/api>) | B-14 — 19,851 invisible 13F holdings |
| 3 | OpenRouter free key (<https://openrouter.ai/keys>), optional | Second link in the provider chain |
| 4 | The six ASK rulings in `docs/dead_code.md` | Cleanup only |

Nothing on this list blocks Phase 5.

## Decisions already taken

- **Display name: Rhumb.** `BRAND_NAME` config value; `TradeOSS` stays the internal codename and
  nothing is renamed for branding.
- **Portfolio → Exposure** approved, salvaging its shadow-vs-SPY track record into the Phase 3
  Ledger rather than deleting it with the surface.
- **Provider: Gemini free tier**, chain-configured so a second provider can be added without code.

---

## Things learned that are not obvious from the code

1. **The "AI never sees my screenshot" bug was not a transport bug.** `directive_guard` banned
   "target price" — which the prompt itself asks the model to discuss — and one tripped field
   discarded the whole read. The fallback then blamed a missing provider. Fixed; see B-01.

2. **My Phase 0 root cause for the attention board was wrong.** I blamed Wikipedia title
   resolution; the titles are correct. The real causes were a fuzzy Algolia query on Hacker News
   and a double-counting error in the board's own scoring. `docs/audit.md` and `docs/bugs.md`
   carry the correction. Treat this as a reminder to measure before concluding.

3. **Gemini's `maxOutputTokens` counts hidden reasoning.** Measured 769–1360 thinking tokens for
   one chart image, so a caller asking for 800 gets truncated JSON. `THINKING_HEADROOM` in
   `llm.py` pays for it. Do not remove it.

4. **`thinkingConfig` 400s on every Gemini model newer than 2.5.** Sending it had pinned the app
   to legacy models. Do not reintroduce it.

5. **Gemini quota is per model.** `gemini-2.0-flash` has a zero free-tier allowance and
   `gemini-2.5-*` are closed to new keys. `gemini-flash-latest` and `gemini-flash-lite-latest`
   work. The model id is load-bearing, not cosmetic.

6. **httpx puts the full request URL, query string included, in its exception messages.** Any
   API authenticated with `?key=` leaks its credential through an unhandled error. `scheduler.redact()`
   strips query strings before anything is stored or logged. Keep that invariant.

7. **Frontend changes need `make web`** (0.3s) when running `make dev`, or a full
   `docker compose up -d --build` otherwise. The bundle is baked into the image.

8. **The scheduler is genuinely good** — restart-safe cursors via `job_runs`, per-job error
   isolation. Phase 2 extends it; do not build a second worker.

9. **Portfolio hides a working Ledger.** Its shadow-vs-SPY track record publishes `−24.1%` and
   `38%` without burying them. Salvage that mechanism in Phase 3.

10. **All five brand names in the brief are taken** on .com/.io/.ai. Settled on Rhumb.

11. The data is real and substantial: 664,923 insider transactions, 51,099 stake events, 24,982
    institutional holdings, 149 live convergence clusters. Weigh that in any rewrite-vs-extend call.

12. **A source that no-ops because it is unkeyed still records `status: ok`** in `job_runs`.
    `sources.health()` deliberately does not count that as a successful fetch, or the page would
    report Reddit as working when it has never run.

13. **GDELT rate-limits for over an hour after a burst.** Three unpaced probe requests throttled
    this IP for the rest of the phase. `gdelt.MIN_INTERVAL_S` is 6 seconds and a 429 ends the
    whole pass — do not "optimise" either.

14. **SEC filing headlines are templated**, so trigram similarity matches the template rather
    than the story. Cluster matching requires shared entities when both sides name any. Removing
    that check re-merges eight companies into one "story".

15. **`_require_admin` returns the USER on success and None on failure.** Branch on
    `if not _require_admin(...)`. Getting it backwards serves admin data to everyone, silently.
    `tests/test_sources.py` asserts every call site uses a safe shape.

16. **Clusters re-derive their category from members.** Without that, improving the classifier
    and reprocessing creates duplicate clusters instead of correcting existing ones.

17. **Azure's content filter classifies text that QUOTES prompt-injection examples as a jailbreak**
    and 400s the whole request. Our own defence made the provider unusable. Describe the rule in
    the abstract; `tests/test_claims.py` asserts no attack strings return.

18. **The impact engine has NO template fallback, on purpose.** Every other AI path in this
    codebase degrades to deterministic output. This one writes nothing, because a fabricated claim
    inside a ledger built to measure honesty would poison the only thing that makes it defensible.

19. **`= ANY(%s::record[])` fails** — psycopg cannot bind an anonymous composite type. Use two
    parallel arrays with `unnest(%s::text[], %s::text[])`.

20. **Every migration file must INSERT its own version row** into `schema_migrations`; the runner
    does not. A file that forgets re-runs and fails with "relation already exists".
    `tests/test_slice2.py` guards this.

21. **Gemini's free tier has a real daily ceiling.** Claim generation is the heaviest consumer.
    A second provider in the chain is the fix, not more retries.
