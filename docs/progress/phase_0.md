# Phase 0 — audit · progress report

Date: 2026-07-25 · Branch: `game-changer` · No feature code written, as specified.

---

## What changed

Six documents, no code:

| File | What it is |
|---|---|
| `CLAUDE.md` | Operating manual. Stack with verified versions, every command run and confirmed, directory map, the conventions this repo actually follows, and eleven gotchas that each cost an hour to find. |
| `docs/audit.md` | The real stack, state management, persistence, integration wiring, secrets, build/serve, data models, and a blunt surface-by-surface keep/rework/delete assessment. |
| `docs/bugs.md` | 21 defects, severity-ranked, with reproduction steps and root cause. |
| `docs/dead_code.md` | 6 safe deletions, 5 stale things needing correction, 6 items I will not touch without a ruling, plus a list of what I checked and found clean. |
| `docs/plan.md` | Phase-by-phase plan, six places the brief needs revision with reasons, the blocking model-provider decision, and the rebrand with real domain checks. |
| `docs/state.md` | Session handoff: what is done, what is next, what is blocked, and twelve non-obvious things learned. |

## Method

Read all 196 tracked files. Ran the stack (api + postgres + worker). Logged in as
`demo@tradeos.app` in a headless browser at 1440×900 and clicked through all twelve surfaces,
capturing console output, network failures and screenshots for each. Executed the vision,
LLM, Reddit and scheduler code paths directly inside the container. Queried the live database.
AST-swept every Python module for unused imports, cross-referenced every JSX export against
its importers, matched all 98 API routes against frontend call sites, and diffed environment
variables read in code against `.env.example`.

---

## The three findings that matter most

**1. The only configured language-model provider is retired in five days.**
`EXPLAIN_PROVIDER=openai` points at GitHub Models, whose responses carry
`Sunset: Thu, 30 Jul 2026`. On that date the Morning Brief summary, news "why it matters",
the assistant, the journal coach and all chart reading fall back to templates. Phases 3–7 are
entirely inference-shaped. This is the critical path and it needs a decision from you.
`gemini-flash-latest` is verified working on your existing key.

**2. The journal screenshot bug is the opposite of what it looks like.**
The model *does* receive the image and *does* read it correctly — I ran it on your stored
trade-21 screenshot and got back a complete, accurate chart read (`pattern: breakout`,
`symbol: NVDA`, `entry: 120`, `stop: 110`, `target: 145`). The output is then discarded
because `directive_guard` bans the phrase `target price`, which the prompt itself instructs
the model to discuss. One tripped field kills the whole analysis, and the fallback then tells
you "no vision model connected" — which is false, and is why you believed the image never
arrived. Two small fixes, both in Phase 1.

**3. The foundation is better than you think, and one surface is better than you think.**
The scheduler, the ingestion layer, the point-in-time discipline and the honesty conventions
are good and should be extended rather than replaced. Specifically: **Portfolio is not
worthless.** Buried in it is a live public track record of shadowing each conviction bucket
against SPY, published including a `−24.1%` and a `38% hit rate` without burying them. That
is an early working version of the Ledger from Phase 3. Scrap the position-tracker framing,
keep that mechanism.

---

## Assessment, blunt

**Keep and extend:** Smart Money (the strongest asset — real SEC data at real volume, a
versioned signal, a backtest that publishes its misses), the scheduler and ingestion layer,
Morning Brief, News Intelligence, Dashboard.

**Rework:** Social (concept right, data poisoned — the board's top names are BALL, POOL, DOV,
FIX, because Wikipedia pageviews for the common English words are attributed to the tickers),
Crypto (you are right, it is a data mirror and interprets nothing), Calendar (a 10,000-pixel
flat list), the AI Assistant (grounded but tool-less), "On the radar" (a calendar preview, not
a live prioritised feed).

**Delete:** `frontend/src/home.jsx` and `frontend/src/scanner.jsx` — superseded, nothing
imports them.

---

## What I could not do, and why

- **No gitleaks/trufflehog history scan.** Neither tool is installed. I did verify by other
  means that `.env` has never been committed (`git log --all -- .env` is empty) and that no
  tracked file contains an `sk-`/`ghp_`/`github_pat_`/`AIza` pattern. A real history scan is
  Phase 9 work and I will install the tool then.
- **No trademark search** for the rebrand candidates. I checked domain delegation by DNS,
  which is a strong hint but not proof of availability, and I have said so in `docs/plan.md`
  rather than presenting it as certainty.
- **No responsive-breakpoint audit.** I checked 1440×900 only. Layout behaviour at mobile and
  tablet widths is unverified and I have not claimed otherwise.
- **The quality gates (`/simplify`, `/code-review`, `/security-review`) were not run.** They
  operate on a diff, and this phase produced no code diff. They start at Phase 1.

---

## What I need from you

1. **The model provider decision.** Recommendation: switch `EXPLAIN_PROVIDER` to `gemini`
   (works today, no new key needed), optionally with an OpenRouter free key as fallback.
   Blocking for Phase 3, and time-critical regardless.

2. **A display name.** All five candidates in the brief — Meridian, Bellwether, Throughline,
   Consequence, Signalyard — are taken on .com, .io and .ai; two are parked on an aftermarket
   reseller and priced accordingly. My recommendation from the brief's own cartographic
   vocabulary is **Rhumb** (a rhumb line is the constant-bearing course a navigator plots — the
   followable route, which is exactly what a causal chain is). `rhumb.com` shows no
   nameservers. Alternatives `Portolan` and `Bearing` are in `docs/plan.md` with reasoning.

3. **Free API keys, when convenient** (none urgent, all free): Reddit
   (<https://www.reddit.com/prefs/apps>), OpenRouter (<https://openrouter.ai/keys>), OpenFIGI
   (<https://www.openfigi.com/api>, to resolve 19,851 currently-invisible 13F holdings).

4. **Six rulings** on things I suspect are dead but will not remove on my own judgement —
   listed as ASK items in `docs/dead_code.md`: the parked short-interest pipeline, the
   `ENABLE_CONGRESS` flag for a source that was never built, two Stripe price-id variables no
   Python file reads, the unreachable social share cards, the stray `uploads/` directory, and
   a misnamed test file.

5. **Confirmation that Portfolio may become Exposure.** It works and contains the track-record
   mechanism described above, so I want your explicit go-ahead before removing the surface.

---

## Revisions I am proposing to the brief

Six, each argued in full in `docs/plan.md`. In short: keep PostgreSQL rather than moving to
SQLite (664k rows of backfilled SEC data already there); extend the existing scheduler rather
than build a second worker (it already does restart-safe cursors); cluster with trigram
similarity before embeddings (so deduplication does not fail when model quota does); add
routing in Phase 1 rather than Phase 7 (Phases 3 and 4 both need addressable state); fix the
frontend dev loop in Phase 1 (every UI change currently needs a Docker rebuild); and ship the
marketing site as a sibling Vite project rather than converting to a JS monorepo.

---

**Status: Phase 0 complete. Stopping for approval as instructed.**
