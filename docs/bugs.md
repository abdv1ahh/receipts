# docs/bugs.md — catalogue of defects found in Phase 0

Found 2026-07-25 by reading the code, running the paths directly inside the container, and
clicking through all twelve surfaces in a headless browser at 1440×900 while authenticated
as `demo@tradeos.app`.

**No JavaScript console errors were produced on any surface.** The reported "instability and
visual glitches" are not crashes; they are data-quality problems, layout problems, and one
architectural gap (no error boundaries) that would turn any future failure into a blank page.

Severity: **S1** breaks a headline feature · **S2** materially wrong or misleading ·
**S3** degrades quality or trust · **S4** cosmetic / hygiene.

Status: `open` unless noted.

---

## S1 — breaks a headline feature

### B-01 · The journal chart coach discards a correct AI reading and then lies about why
**Reported as:** "uploaded screenshots are never actually seen by the model; it responds as
though no image arrived."

**Actually happening:** the model sees the image and reads it correctly. The output is then
thrown away by a guard, and the fallback text claims no vision model is connected.

**Reproduction (verified end to end):**
1. Trade 21 (user 20) has a stored screenshot. `chart_analyses` records
   `model_id = template, used_template = true`.
2. Running `llm.vision(...)` on those exact bytes returns a complete, accurate JSON chart
   read: `pattern: "breakout"`, correct structure prose, four coaching observations,
   `symbol: "NVDA"`, `entry: 120`, `stop: 110`, `target: 145`.
3. `vision._guarded(out)` returns `False`. Field-by-field: `pattern` passes, `structure`
   passes, `psychology` passes, all four observations pass — **`risk_reward` fails.**
4. The failing text is: *"…the reward is the distance from the entry price to the target
   price."* `explain/guards.py` line 20 bans the literal token `target\s?price` as
   recommendation vocabulary.
5. `_guarded` is all-or-nothing, so one tripped field discards the whole analysis.
6. `_fallback()` then renders: *"AI chart reading isn't available (no vision model
   connected)."* Which is false. A model was connected, was called, and answered.

**Root cause:** two independent defects that compound.
- `intelligence/vision.py` `INSTRUCTION` explicitly asks the model to *"comment factually on
  the risk/reward structure"* given entry/stop/target levels, while `directive_guard` bans
  the phrase any model will naturally use to do that. The prompt and the guard contradict
  each other.
- The fallback message is written as though the only possible cause is a missing provider,
  so a guard trip is reported to the user as a missing integration. This violates the
  honesty rule directly.

**Fix (Phase 1):** narrow the guard so `target price` is only directive in an imperative
context (`price target of $X`, `raise the price target`) and not when describing a level the
user themselves recorded; make `_guarded` field-level (drop the offending field, keep the
rest) rather than all-or-nothing; and make `_fallback` state the real reason — "no provider",
"quota exhausted / cooling", "guard tripped on field X". Add a test with a real fixture image
and a test asserting the guard permits descriptive risk/reward prose.

---

### B-02 · The attention board is dominated by companies whose names are common English words
**Severity S1** (it is the entire content of the Social surface).

**Observed:** the top of the 96-hour board reads `BALL` (7,547 mentions, 5.48× baseline),
`POOL` (4.96×), `PAG`, `DOV`, `FIX`, `NOW`, `CRM`. Wikipedia pageviews for the articles
behind the words *Ball*, *Pool*, *Dover*, *Fix* are being attributed to those tickers.

**Cause:** `wiki_titles` maps tickers to Wikipedia article titles by company-name match with
no disambiguation check and no popularity sanity check. A company literally named "Ball
Corporation" resolves to an article that a very large number of people read for reasons that
have nothing to do with the company.

**Consequence:** the ranked board is mostly noise, which makes the whole surface look broken
even though every number displayed is technically real. It also poisons `social.attention_
universe()`, which feeds the analyst's catalyst matching.

**Fix (Phase 1/2):** require the Wikipedia title to be disambiguated to the company (title
containing `(company)`, or the article's Wikidata entity typed as a business), compare
pageviews against the article's own long-run baseline rather than a global one, and drop any
symbol whose resolved title is a common noun. Log rejections to `ingest_rejects`.

---

### B-03 · Reddit blocks with a bare key request and no path forward
**Reported by the owner.** Confirmed: `config.reddit_configured()` returns false with no
key, `social_reddit.ingest()` is a silent no-op, and the UI renders a `Reddit · add key`
chip whose only affordance is a `title` tooltip reading "add a free key to connect". There
is no link to Reddit's app-registration page, no statement of what Reddit would add, and no
reduced-capability mode.

**Fix (Phase 1):** the shared graceful-degradation component required by the brief §4 —
explains what the source unlocks, links directly to where the free key is obtained, shows
the two steps, and keeps the panel working on whatever sources are live. Plus a real Reddit
OAuth2 client-credentials implementation with a descriptive user agent.

---

### B-04 · Only configured LLM provider is retired on 2026-07-30
**Severity S1**, five days of runway at time of writing. Full detail in `docs/audit.md` §0.
`https://models.github.ai/inference` returns `Sunset: Thu, 30 Jul 2026`. Every AI surface
degrades to templates that day. `gemini-flash-latest` is verified working as a replacement.
Needs an owner decision (see `docs/plan.md`).

---

## S2 — materially wrong or misleading

### B-05 · `cli preflight` rejects the provider the app is configured with
```
✗ EXPLAIN_PROVIDER 'openai' is invalid (template|gemini|anthropic).
preflight: 1 problem(s), 2 warning(s) — NOT ready.
```
`llm.py` implements `template`, `gemini` and `openai`. It does **not** implement `anthropic`.
The validator is stale in both directions: it rejects a valid provider and advertises one
that does not exist. A confidently wrong check is worse than no check — an operator running
preflight before deploying is told the working config is broken.

### B-06 · `make test` and the README test command both fail
```
$ docker compose run --rm -T api python -m pytest tests/ -q
ERROR: file or directory not found: tests/
```
The Dockerfile never copies `tests/` into the image. The suite runs fine when the directory
is mounted (`-v "$PWD/tests:/app/tests"` → 189 passed in 0.43s). `README.md` line 40 also
claims "13 tests"; there are 189.

### B-07 · `.env.example` is missing ten variables the code reads
Missing: `OPENAI_BASE_URL`, `OPENAI_API_KEY`, `OPENAI_MODEL`, `SENTRY_DSN`,
`OPENFIGI_API_KEY`, `TRADEOS_ADMIN_PASSWORD`, `TRADEOS_DEMO_EMAIL`, `TRADEOS_DEMO_PASSWORD`,
`UPLOADS_DIR`, `DATABASE_URL`. A new operator following `.env.example` cannot configure the
LLM provider the app actually uses.

### B-08 · Dashboard and Smart Money are three days stale while the UI says "live"
`/api/dashboard` returns `as_of: 2026-07-22T15:31`, and the header renders `● live` because
`delayed_hours == 0` for a pro tier. The `delayed_hours` field describes the *tier's* feed
delay, not the *data's* actual age. On 2026-07-25 the user is told "live" about a
three-day-old signal snapshot.

**Cause:** the signal-plane jobs (`compute-signals`, EDGAR backfills) are not in the
scheduler's `JOBS` registry — they are manual CLI operations. Only the news/attention/
calendar jobs run continuously.

**Fix:** display real data age (`as_of` → "3 days old"), and add signal recomputation to the
scheduler.

### B-09 · A single failed request paints an error bar over every surface
`App.jsx` holds one `err` string set by four different top-level fetches
(`fetchFeeds`, `fetchCalibration`, `fetchDefinitions`, `fetchClusters`). Any one failing
renders `error: <raw JS Error string>` above whatever page the user is on, permanently, with
no dismiss and no retry. The message is a developer string (`Error: /api/feeds -> 500`), not
an explanation.

### B-10 · No error boundaries anywhere
There is not a single `componentDidCatch` / error boundary in the app. A render-time
exception in any panel unmounts the entire React tree and leaves a blank page. Required by
the brief §Phase 1.

---

## S3 — degrades quality or trust

### B-11 · The Calendar is a ~10,000-pixel flat list
Ten days of earnings and macro releases rendered as one continuous scroll grouped by day
heading. No month view, no week view, no day view, no filtering by importance or relevance,
no way to see the shape of a week. The underlying data is good (consensus, previous, actual
where known). Owner's complaint confirmed. Phase 6.

### B-12 · Crypto interprets nothing
Confirmed as described: prices, 24h/7d moves, market cap, sparklines, gainers/losers,
search-trending. Every number free elsewhere. The page's own footer states which signals are
missing. Phase 6.

### B-13 · 20 of 20 attention rows read "attention only"; 15 of 20 flagged "single source"
A direct consequence of B-02 and B-03: with Reddit unkeyed, no source measures *mood*, and
with Wikipedia dominating, most names have exactly one source. The pulse tile reads
`— MOOD NOT MEASURED · CONNECT REDDIT` and the smart-money overlap count is `0`. Honest, but
the surface currently delivers close to zero signal.

### B-14 · 19,851 13F holdings have unresolved CUSIPs
`cli status` reports it. These holdings exist in the database but cannot be attributed to a
ticker, so they are invisible to every surface. Materially reduces Smart Money's institutional
coverage. Requires `resolve-cusips` runs (OpenFIGI, rate-limited) or an alternate mapping.

### B-15 · "On the radar" is a calendar preview, not a prioritised feed
Confirmed as reported. It renders `d.radar` — the next few scheduled events. No relevance
ranking, no live events, no consequence framing. To be replaced in Phase 4.

### B-16 · No routing: no deep links, no browser back, nothing indexable
`App.jsx` navigates by `useState`. The URL never changes. A user cannot bookmark the Journal,
share a link to a claim, or press back. Blocks Phase 4 (shareable filter sets) and Phase 7
(an indexable marketing site).

### B-17 · A 429 from one model call silences every model caller for 120 seconds
`llm.py` `_COOLDOWN_UNTIL` is a module-global. One quota trip on a background news-analysis
job makes the user's interactive chart read fall back to a template with no explanation. The
cooldown is a good idea; its blast radius is too wide and it is invisible to the user.

---

## S4 — hygiene

### B-18 · No linter and no formatter configured
Brief §5 asks for one of each running on commit. Only gitleaks is wired.

### B-19 · No CI
No `.github/workflows`. Nothing runs the 189 tests on push.

### B-20 · No request identifiers in logs
The middleware logs unhandled errors with method and path but no correlation id, so a failure
cannot be traced across the API and worker.

### B-21 · Five genuinely unused imports
`ingestion/news_sec.py:22 datetime` · `intelligence/vision.py:15 base64` ·
`news.py:12 math` · `news.py:17 config` · `signals/convergence.py:22 timezone`.
(An AST sweep also flags `from __future__ import annotations` in 55 files — false positive.)

---

## Fix order for Phase 1

1. B-04 (provider sunset — needs an owner decision first)
2. B-01 (journal vision guard + honest fallback)
3. B-03 (Reddit OAuth2 + the shared degradation component)
4. B-10, B-09 (error boundaries, then scoped error handling)
5. B-02 (Wikipedia entity resolution)
6. B-05, B-06, B-07 (broken commands and drifted config docs)
7. B-08 (honest data-age display)
8. B-16 (router — needed by Phases 4 and 7)
9. B-17 (per-caller cooldown, surfaced to the user)
10. B-18, B-19, B-20, B-21 (hygiene)

B-11, B-12, B-13, B-14, B-15 are Phase 4/6 rebuilds and are not Phase 1 work.
