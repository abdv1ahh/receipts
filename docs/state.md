# docs/state.md — where the work stands

Updated: 2026-07-25, end of Phase 2.
Read this after `CLAUDE.md` and before `docs/plan.md` at the start of every session.

---

## Current phase

**Phase 2 (the ingestion spine) — core complete.** Branch `phase/2-ingestion`, 3 commits.
**Phase 3 (impact engine + Ledger) is unblocked and is next.**

Phase 0 and Phase 1 are complete; their reports are in `docs/progress/`.

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

## Next three tasks

1. Open `phase/3-claims`, plan mode first.
2. Migration `025`: `claims`, `claim_outcomes`, `country_exposure`. Claim generation with a
   STRICT output schema validated on return — that validation is also the prompt-injection
   boundary, since Phase 2 now ingests arbitrary text from GDELT.
3. Outcome measurement on the existing scheduler, reusing `prices_eod` and `backtest/engine.py`
   — the price-series machinery is already built and point-in-time correct.

Carried over, not blocking: confirm GDELT ingests once its rate limit clears (the adapter is
built and covered, but a live ingest is unverified — see `docs/progress/phase_2.md`), and add
Bluesky as a real `SocialSource`.

## Open questions waiting on the owner

| # | Question | Blocks |
|---|---|---|
| 1 | Reddit free key (<https://www.reddit.com/prefs/apps>, type "script") | B-13 — the only source that measures mood |
| 2 | OpenFIGI free key (<https://www.openfigi.com/api>) | B-14 — 19,851 invisible 13F holdings |
| 3 | OpenRouter free key (<https://openrouter.ai/keys>), optional | Second link in the provider chain |
| 4 | The six ASK rulings in `docs/dead_code.md` | Cleanup only |

Nothing on this list blocks Phase 3.

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
