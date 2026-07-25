# Phase 1 — repair · progress report

Date: 2026-07-25 · Branch: `phase/1-repair` · 5 commits · 222 tests pass · 0 lint errors

---

## The three things you reported, and what was actually wrong

### 1. "Uploaded screenshots are never seen by the model"

The model saw them the whole time. Three defects hid that, and the third is why you believed
the image never arrived.

- `directive_guard` banned the phrase **"target price"** as recommendation vocabulary — while
  the vision prompt explicitly instructs the model to *"comment factually on the risk/reward
  structure"* given entry/stop/target levels. The prompt and the guard contradicted each other.
- One tripped field discarded the **entire** chart read. Four good fields were thrown away
  because a fifth said "the distance from the entry price to the target price".
- The fallback then printed *"AI chart reading isn't available (no vision model connected)"* —
  regardless of cause. That sentence was false, and it is what you were reading.

Fixed: the guard now fires on *issuance* (`price target of $190`, `raised its price target`) and
not on *description*; guarding is per field, so offending prose is withheld and named in
`withheld` while the rest survives; and `llm.complete()` returns `(text, reason)` so the fallback
states the real cause — a quota trip reads as a quota trip.

**Verified live** against your real trade-21 screenshot: `source: ai`,
`model: gemini-flash-latest`, `withheld: []`, with an accurate read of the price structure.

### 2. Reddit blocked with a bare key request

The Reddit OAuth2 implementation was already correct (client credentials, descriptive user agent,
host allowlist, polite rate limiting). What was missing was the path forward. There is now a
shared `<SourceGate>` used everywhere a source is missing: it states what the source would add,
links directly to where the free key is obtained, names the exact environment variables, and lets
everything else keep working. Reddit's entry says plainly that there is **no useful keyless
mode** — Reddit blocks the public JSON endpoints from datacenter addresses — rather than quietly
returning nothing.

### 3. The X panel showing `N/A`

`N/A` is gone. X and StockTwits render as *"no free access"* with the reason stated: X's free tier
does not permit reading timelines, paid tiers start well beyond free-tier scope, and scraping breaks
their terms and breaks constantly — so it is not shipped. The panel says which networks it does
cover. The `SocialSource` shape is now the source registry (`tradeos/sources.py`), so X drops in
the moment access exists.

---

## The finding that outranked all three

**Your only language-model provider was being switched off in five days.** GitHub Models returns
`Sunset: Thu, 30 Jul 2026` in its own response headers. On that date the Morning Brief, news
analysis, the assistant, the journal coach and all chart reading would have silently fallen back
to templates.

`llm.py` is now a provider **chain** (`EXPLAIN_PROVIDER=gemini,openai`) with per-provider circuit
breakers, so one backend dying no longer silences every AI surface. Switched to Gemini's free
tier, which is verified working on your existing key.

Two Gemini-specific bugs surfaced while verifying, both of which would have bitten you regardless:

- The hardcoded `thinkingConfig` returns **400 on every model newer than 2.5**, which had quietly
  pinned the app to legacy models. Removed.
- `maxOutputTokens` counts **hidden reasoning**. Measured: `gemini-flash-latest` spent 769–1360
  tokens thinking about one chart, so a caller asking for 800 received 24 tokens of prose and
  truncated JSON — which the caller then blamed on its own parsing. Callers now budget the visible
  answer and `THINKING_HEADROOM` pays for the reasoning; a truncated reply is reported, not
  returned.

**On your question about cost:** your Gemini key is on the **free tier** — the 429 body names
`generate_content_free_tier_input_token_count` explicitly. Nothing is being charged. Two model ids
matter: `gemini-2.0-flash` has a zero free-tier allowance and `gemini-2.5-*` are closed to new
keys; `gemini-flash-latest` (reasoning) and `gemini-flash-lite-latest` (extraction) both work and
are now the defaults.

---

## Where my Phase 0 audit was wrong

**I need to correct the record.** I attributed the Social board being topped by `BALL`, `POOL`,
`DOV`, `FIX` to Wikipedia title resolution matching common English nouns. That was wrong. The
titles resolve correctly — `BALL → "Ball Corporation"`, not `"Ball"` — and the Wikipedia numbers
were sane throughout (`BALL: 312 views, 1.01× baseline`).

The two real causes, both measured:

1. **Hacker News counted fuzzy matches.** The query sent a bare company name to Algolia, whose
   default search is an OR match, so `"BALL Corp"` matched every post containing "ball" or "corp".
   Measured over the same window: `BALL Corp` → **6,757 hits**, `NVIDIA CORP` → **5,303**. The
   code was asserting that Hacker News discusses a packaging company more than it discusses Nvidia.
2. **The board summed snapshots and mismatched its own ratio.** Every observation in the window
   was added up — but each source writes a *snapshot* of the same measure on every run, so 312
   daily pageviews became "7,547 mentions". Worse, velocity divided a total that *included*
   baseline-less sources by a total that *excluded* them, which alone turned a 1.01× name into
   5.48×.

Fixed: exact quoted phrase with `advancedSyntax`, legal suffixes stripped so `NVIDIA CORP`
searches `"NVIDIA"`, and the suffix deliberately **kept** for names that are ordinary English
words. One current reading per `(symbol, source)`. Velocity as a mention-weighted mean over only
the sources that have a baseline. Poisoned observations deleted and re-ingested.

| | Before | After |
|---|---|---|
| Top of board | BALL 5.48×, POOL 4.96× | NWBO 2.78×, AIDX 2.33×, GCBC 2.05× |
| HN mentions | BALL 6,757 · NVIDIA 5,303 | NVIDIA 14,272 · Salesforce 1,418 · UNP 37 · BALL 0 |

`docs/audit.md` and `docs/bugs.md` carry the correction inline, because a confidently wrong root
cause left in a bug file is exactly the kind of thing that misleads the next reader.

---

## Everything else that changed

**Routing.** The app had none — navigation was `useState`, so nothing had a URL: no deep links, no
back button, nothing indexable. `useRoute()` puts the surface in the path (about 40 lines over the
History API; react-router is more machinery than this app needs), and the static mount falls back
to `index.html` so a refresh survives. This was scheduled for Phase 7 in the brief; it had to move
here because Phases 3 and 4 both need addressable state.

**Failure containment.** Every surface is wrapped in an `ErrorBoundary`, so one throwing panel no
longer blanks the app. The global error bar that painted a raw JS `Error` string over every page
is gone, replaced by scoped, human-readable states with a retry.

**Integration status page** (`/integrations`). Every external source, its state, what it powers,
where its free key comes from, when it last succeeded, whether it is failing. Backed by one
registry so it cannot drift from what the app is actually doing. 7 connected, 3 need a free key,
2 have no free path.

**Honest data age.** The dashboard said "live" whenever your tier had no feed delay — while the
signal snapshot was three days old. It now reports the real age and only claims "live" under two
hours.

**Tooling.** Ruff as the linter with zero errors left behind, and CI running tests + lint + a
full-history gitleaks scan. There was no CI at all before. Real defects the linter found: a broken
type annotation in `backtest/run.py`, a silently swallowed Stripe cancellation failure in
`billing.py`, a lost exception chain in `authn.py`, two XXE tests that asserted
`raises(Exception)` (which passes when the parser fails for the *wrong* reason), and an untested
OHLC sanity check.

**Ruff is deliberately not the formatter.** Checked against the tree: it de-indents continuation
strings away from the key they belong to and strips the aligned trailing comments this codebase
uses consistently across ~89 files. That is a large mechanical diff that makes the code harder to
read. The reason is recorded in `pyproject.toml` so it stays a decision rather than drift.

**Development loop.** `make dev` reloads Python in place and serves the locally built frontend, so
a UI change costs a 0.3-second `make web` instead of a full image rebuild.

**Deletions:** `home.jsx`, `scanner.jsx`, six orphaned CSS rules, `trading_intelligence .md`, a
stray empty `uploads/`, `.DS_Store`. `test_gemini.py` renamed to `test_explain_gemini.py`.

**Documentation reconciled:** README rewritten (it still described "Slice 1: skeleton + Form 4
pipeline" and a test command that fails), `.env.example` now lists all 20 variables the code reads
with a link to each free key — it was missing ten.

---

## Quality gates

`/security-review` on the phase diff **found a real vulnerability in my own work**, which is
fixed in commit `52b948f`:

> `/api/integrations` was unauthenticated and returned `last_error` verbatim — `str(exc)[:300]`
> of an arbitrary ingestion failure. httpx embeds the full request URL, **query string included**,
> in its exception messages, and Gemini authenticates with `?key=...`. One unhandled 4xx in a
> keyed job would have written a live credential into `job_runs` and served it to the open
> internet.

That path was saved today only because `llm.py` swallows provider exceptions rather than raising —
an incidental property of one function, not a boundary. Tiingo, FINRA and OpenFIGI are all already
in the codebase and not yet on the scheduler; adding one would have reintroduced it silently.

Fixed at both ends: `scheduler.redact()` strips every query string before a message is stored or
logged (the host survives, because that is the useful part), and the endpoint now requires a
session with the raw error text admin-only. Regression tests in `tests/test_sources.py`.

`/simplify` and `/code-review` were **not** run — the phase diff is large and I judged the
security gate the one that mattered most here. Flagging that as a gap rather than claiming it.

---

## Bug status

| Closed | Remaining |
|---|---|
| B-01 journal vision · B-02 attention board · B-03 Reddit path · B-04 provider sunset · B-05 preflight · B-06 `make test` · B-07 `.env.example` · B-08 data age · B-09 global error bar · B-10 error boundaries · B-16 routing · B-18 lint · B-19 CI · B-20 request ids · B-21 unused imports | B-11 Calendar (Phase 6) · B-12 Crypto (Phase 6) · B-13 no mood source (needs your Reddit key) · B-14 19,851 unresolved CUSIPs (needs OpenFIGI key) · B-15 On the Radar (Phase 4) · B-17 per-caller cooldown blast radius |

B-17 is partly addressed — the cooldown is now per provider rather than global, so one job's quota
trip no longer silences a different provider. It is still not surfaced to the user; that lands
with the Radar in Phase 4.

New, found during this phase: `GOOG` and `GOOGL` render as two board rows for one company. Share
classes should collapse. Carried to Phase 2 with entity resolution.

---

## What I could not do

- **`/simplify` and `/code-review` were not run on this diff.** Stated above.
- **Responsive breakpoints are still unverified.** I checked 1440×900 only, across all 14 routes.
- **No gitleaks history scan yet** — the tool is now wired into CI but has not run against the
  full history locally. Phase 9 owns this.
- **The six ASK items in `docs/dead_code.md` are untouched**, awaiting your ruling. You selected
  the Portfolio→Exposure approval but not the "clear them my way" option, so I left them alone.

---

## What I need from you

1. **Nothing is blocking Phase 2.** It can start immediately.
2. **A Reddit key** would close B-13 and give the Social surface the only source that measures
   *mood* rather than attention: <https://www.reddit.com/prefs/apps> → create an app of type
   "script" → client id + secret. Two minutes.
3. **An OpenFIGI key** would make 19,851 currently-invisible 13F holdings visible:
   <https://www.openfigi.com/api>.
4. **Optionally an OpenRouter key** (<https://openrouter.ai/keys>) as the second link in the
   provider chain. Gemini alone works; a second provider means a quota trip never silences the AI.
5. **The six `ASK` rulings** in `docs/dead_code.md`, whenever convenient.

---

**Status: Phase 1 complete.** Base is repaired. Phase 2 (the ingestion spine) is unblocked.
