# docs/plan.md — the build plan, adapted to what is actually here

Derived from `docs/tradeoss_veryimportant_prompt.md` and revised against the Phase 0 audit.
Where the brief and the codebase disagree, this file says so explicitly rather than quietly
working around it. Read with `docs/audit.md`, `docs/bugs.md` and `docs/dead_code.md`.

---

## Where the brief was right, and it matters

Four judgements in the brief survive contact with the code and should be held to:

1. **Reposition around causal chains, a public ledger, and personal relevance.** The app
   already has the honesty culture this needs (it publishes a `−24.1%` excess return without
   burying it). The missing piece is genuinely missing: nothing here explains *mechanism*.
2. **Adapters for volatile sources.** Justified upfront, for the stated reason. The directory
   structure already assumes it; only the interface is missing.
3. **Degrade, never block.** This is already the house style everywhere except Reddit, which
   is the one place it broke.
4. **X is not reachable on free tiers.** Confirmed. Do not build it, do not scrape it.

---

## Where the brief needs revision

Six places where following the brief literally would make the product worse. Each states the
alternative and the reason.

### 1. Do not move to SQLite — keep PostgreSQL

The brief (§8) says "SQLite is entirely sufficient and needs no hosting". That was written
without knowledge of the existing data layer. The app runs PostgreSQL 16 with 23 migrations,
48 tables, and **664,923 insider transactions, 51,099 stake events and 24,982 institutional
holdings** already loaded — a dataset that took hours of rate-limited SEC backfill to build.

Beyond the migration cost, Postgres gives the next three phases things SQLite does not:
`pg_trgm` for near-duplicate clustering without an embedding model, `tsvector` full-text
search, real `jsonb` indexing for `raw_payload` queries, `interval` arithmetic for horizon
sweeps, and concurrent access from the API and worker containers.

**Decision: PostgreSQL stays.** Deployment (Phase 8) uses a free-tier managed Postgres or a
persistent volume, documented in `docs/deploy.md`.

### 2. The background service already exists — extend it, do not build a second one

The brief (§8) asks for "a proper background service, not fetch calls inside components".
That service is `tradeos/scheduler.py`: a job registry, per-job intervals, a restart-safe
cursor via `job_runs`, and per-job error isolation. Nine jobs run on it today. No component
in this codebase calls an external API.

**Decision: Phase 2 adds jobs and a normalisation step to the existing scheduler.** New
requirements it does need: per-source quota accounting, per-source TTL policy, and a
`reprocess` command.

### 3. Clustering starts deterministic, not with embeddings

The brief (§8) says "embed titles and bodies, group by similarity". Embeddings need an
inference provider, and the only configured provider is being switched off in five days
(B-04). Making the ingestion spine depend on inference would make deduplication fail whenever
quota does.

**Decision: cluster with `pg_trgm` trigram similarity plus shared-entity and time-window
constraints first — deterministic, free, testable offline against fixtures, and it degrades
to "no cluster" rather than "no ingestion". Add an embedding pass behind the model adapter as
a refinement once a provider is settled.** The brief's own principle applies: prefer the
boring solution; a lookup beats a clever algorithm.

### 4. Routing must land in Phase 1, not Phase 7

The app has no router at all (B-16). The brief only implies URLs when it reaches the
marketing site, but Phase 4 requires "saved filter sets" and Phase 3 requires opening a
specific claim — both meaningless without addressable state. Retrofitting routing across
twelve surfaces after they have been rebuilt costs several times what it costs now.

**Decision: add routing in Phase 1** (React Router, or ~60 lines over the History API given
this app has no other routing needs — decide at implementation, defaulting to the smaller
option per §5 of the brief).

### 5. Fix the development loop before building on it

Every frontend change currently requires `docker compose up -d --build` because the bundle is
baked into the image. Nine phases of UI work at that latency is an unforced tax.

**Decision: Phase 1 adds a `docker-compose.dev.yml` override running `vite dev` with a proxy
to the API.** Production stays exactly as it is.

### 6. The marketing site is a Vite workspace, not a monorepo migration

The brief (§13) says "a separate public application in the same repository as a monorepo
workspace". This is a Python repository with one Vite frontend, not a JS monorepo. Converting
to npm workspaces to host one extra site is more machinery than the problem needs.

**Decision: `frontend/` and `site/` as two sibling Vite projects sharing a
`shared/tokens.css`.** If a third surface ever appears, promote to workspaces then.

---

## Blocking decision needed now: the language model

This is the first thing to resolve because Phases 3–7 are inference-shaped and the current
provider dies on **2026-07-30**.

| Option | Cost | Vision | Notes |
|---|---|---|---|
| **Google Gemini free tier** | free | yes | `gemini-flash-latest` **verified working right now on your existing key**. `gemini-2.0-flash` is already over quota on it and `gemini-2.5-flash` 404s, so the model id matters. Generous limits; no card required. |
| **Groq free tier** | free | limited | Fastest inference available free. Vision support is model-dependent. Needs a new key. |
| **OpenRouter free models** | free | varies | Several free models behind one OpenAI-compatible endpoint — `llm.py` already speaks that protocol, so this is a two-variable change. Needs a new key. |
| **Ollama, local** | free | yes | Zero marginal cost, no quota, no vendor risk. Depends entirely on your machine's RAM/GPU, and cannot run on a free-tier deploy host. |

**Recommendation: Gemini as the primary (it already works, no new key needed), OpenRouter
configured as the fallback in the same adapter.** The brief's advice to use a small cheap
model for classification/extraction and the strongest available for mechanism reasoning maps
onto this cleanly.

I need from you: confirmation to switch `EXPLAIN_PROVIDER` to `gemini`, and — if you want the
fallback — an OpenRouter free key (<https://openrouter.ai/keys>).

---

## The rebrand: domain reality

The brief asks for two or three names with rationale, checked for availability first. I
checked all five suggestions by DNS delegation:

**Every one of Meridian, Bellwether, Throughline, Consequence and Signalyard is taken on
.com, .io and .ai.** Meridian and Bellwether are additionally parked on Afternic (aftermarket
resale, so priced as premium). None is realistically obtainable on free tiers.

Working from the brief's own visual vocabulary instead — cartographic and instrumental —
three candidates that are both meaningful and appear unregistered:

| Name | Why it fits | Availability signal |
|---|---|---|
| **Rhumb** | A rhumb line is the constant-bearing course a navigator plots across a chart: not the shortest path, the *followable* one. That is precisely what a causal chain is — the traceable route from event to consequence. Short, unusual, ownable. | `rhumb.com` has no nameservers |
| **Portolan** | A portolan is the medieval chart that recorded not terrain but *bearings and connections between ports* — a map of relationships and routes rather than places. Trade corridors are literally the modern version. | `portolan.com` has no nameservers |
| **Bearing** | "A bearing" is a direction; "to have a bearing on" is to be *relevant to*. The double meaning is the whole product: direction plus personal relevance. Weakness: the bare word is generic and heavily used; `bearingline.com` is taken but `.io`/`.ai` are open. | `bearingline.io` / `.ai` open |

**My recommendation: Rhumb.** It carries the navigational metaphor without explaining itself,
it is one syllable, and it is not a word anyone else in this space is using.

Caveat stated plainly: absence of nameservers is a strong hint, not proof of availability, and
I have not checked trademark registers. Confirm with a registrar and a USPTO/EUIPO search
before committing. **Do not rename files or database tables** — the display name lands as a
single config value (`BRAND_NAME`) read once and threaded through the UI, as the brief
specifies.

---

## Phase plan

Each phase: branch `phase/N-name`, plan mode at the open, quality gates on the diff at the
close (`/simplify`, `/code-review`, `/security-review`), a report in `docs/progress/phase_N.md`,
a cleanup pass, then stop for approval.

### Phase 1 — Repair · branch `phase/1-repair`
Nothing new gets built on a broken base.
- Switch the model provider (B-04) and make `llm.py` fall back across providers rather than
  going silent.
- Fix the journal vision pipeline (B-01): narrow `directive_guard`, make `_guarded`
  field-level, make the fallback state the *real* reason. Test with a real fixture image.
- Reddit (B-03): OAuth2 client credentials, descriptive user agent, rate-limit respect; plus
  the shared `<SourceGate>` degradation component used everywhere a key is missing.
- `SocialSource` interface + honest panel labelling for the networks actually covered.
- Error boundaries per surface (B-10) and scoped, human-readable error states (B-09).
- Routing (B-16) and the dev compose override (revision §5).
- Wikipedia entity resolution (B-02) so the attention board stops ranking common nouns.
- Honest data-age display (B-08).
- Fix `preflight`, `make test`, the README, `.env.example` (B-05, B-06, B-07).
- Lint + format + CI (B-18, B-19); request ids in logs (B-20).
- Execute the safe deletions in `docs/dead_code.md` and answer the six ASK items.

**Done when:** every S1 and S2 bug is closed, the suite is green in CI, the app runs with no
console errors, and a frontend edit is visible without a Docker rebuild.

### Phase 2 — The ingestion spine · branch `phase/2-ingestion`
- Migration `024`: the `events` table (the brief's `Event`, with `geo[]`, `language`,
  `author`, `author_influence_score`, `novelty_score`, `amplification`, `raw_payload`), plus
  `event_sources`, `event_clusters`, `watchlist_accounts`.
- Source adapters formalised: `NewsSource`, `SocialSource`, `MarketSource`, `FilingSource`.
- **GDELT as the primary news backbone** (no key, global, machine-coded actors/locations/
  tone) alongside the existing RSS and SEC feeds. Bluesky for social. Wikipedia current
  events. Existing sources adapted onto `events` rather than replaced.
- Trigram clustering + novelty and velocity scoring (revision §3), stored velocity curve.
- Author-influence watchlist as first-class editable data with an admin surface.
- `reprocess` CLI command, admin-only, for rerunning the engine over stored payloads.
- Integration status page (brief §4) — one screen: every source, connected state, what it
  powers, quota headroom, last success, last error.

**Done when:** a story arriving from ten sources produces one canonical event with ten
attached sources, offline fixture tests cover every parser, and the status page explains any
`N/A` the owner ever sees again.

### Phase 3 — Impact engine, Ledger, relevance · branch `phase/3-claims`
- `claims`, `claim_outcomes`, `country_exposure` tables.
- Claim generation with a strict output schema, validated on return (this is also the
  prompt-injection boundary — see Phase 9). `mechanism` must be specific or the claim is
  rejected. `contradicts` computed by comparing live claims on overlapping assets.
- Outcome measurement job on the existing scheduler, reusing `prices_eod` and
  `backtest/engine.py` — the price-series machinery is already built and point-in-time
  correct. Light review queue for qualitative claims.
- The Ledger surface: hit rate by category, horizon, source and confidence bucket;
  calibration curve; **recent misses shown first, not buried.** Absorb the existing
  shadow-portfolio-vs-SPY track record into it.
- Personal relevance: profile (country, base currency, watchlist, sectors, risk appetite) and
  a scoring function over claim confidence × watchlist overlap × geographic exposure ×
  novelty. Seed reference data for country exports/imports, currency regime, index
  constituents, commodity dependence (World Bank, UN Comtrade — both free).

**Done when:** claims are being written, the first horizons have elapsed and been scored, and
the Ledger shows a real number including its misses.

### Phase 4 — Radar · branch `phase/4-radar`
Consequence-first ranked stream as the primary surface; filters across category, geography,
horizon, confidence floor and source type with saved sets; threading so a developing story
updates in place with visible interpretation history; throttled subscribable alerts by email
or webhook. Then "On the radar" on the dashboard becomes its compact view.

### Phase 5 — The globe · branch `phase/5-globe`
`react-globe.gl`, lazy-loaded below the fold, restrained base styling. Country selection sets
the geographic frame **application-wide** — that linkage is the point. Layers: event density,
trade corridors, currency pressure, commodity flows, and event propagation animated along the
corridors the mechanism actually implies. `prefers-reduced-motion` respected, 2D fallback,
and everything reachable through the globe also reachable without it.

### Phase 6 — Rework the existing sections · branch `phase/6-sections`
Morning Brief as daily distillation including yesterday's Ledger outcomes · Smart Money's
signals fed into the claim/Ledger machinery with the 13F reporting lag stated explicitly ·
News folded into the impact engine plus a source-comparison view · Crypto interpreting
instead of mirroring, with invalidation conditions · Calendar with real month/week/day views ·
Journal coach attached to world context at trade time · **Portfolio → Exposure** · AI
Assistant given read-only tools over the event, claim and Ledger stores.

### Phase 7 — Marketing site · branch `phase/7-site`
Live product as the hero. Daily real-event walkthrough. The public Ledger, unedited. A
personalisation globe demo. FAQ with `FAQPage` structured data. Cartographic/instrumental
design system presented for review *before* building. FCP under 1.5s, Lighthouse 90+.

### Phase 8 — Accounts, limits, deployment · branch `phase/8-accounts`
Email + OAuth, sub-minute onboarding capturing country/currency/watchlist, tier gating
scaffolded and **enforced server-side**, free-tier deployment documented end to end in
`docs/deploy.md`.

### Phase 9 — Security · branch `phase/9-security`
Threat model first. Secret history scan with gitleaks (not installed yet). Prompt injection
treated as the primary risk, since Phase 2 ingests arbitrary text and Phase 6 gives a model
tools. Then the classics, authorization tested adversarially with automated tests, data
protection for journals and holdings, rate and cost limits, supply chain, headers, uploads,
and the marketing site reviewed separately. Ends with an honest list of what remains open.

---

## Sequencing risks

- **Phase 3 cannot start until the model provider is settled.** It is the critical path.
- **Phase 2's value depends on B-02 being fixed** — a spine that ingests noise produces
  claims about noise.
- **The Ledger needs elapsed time.** Start writing claims in Phase 3 even before the surface
  is finished, so horizons are already resolving when Phase 7 wants to publish them. The
  `reprocess` command from Phase 2 is what bootstraps history rather than waiting months.
- **The globe is the most visible and least essential feature.** If a phase must be cut for
  time, Phase 5 is the one — but its country-selection linkage is load-bearing for relevance,
  so ship that linkage in Phase 3 as a plain country selector and let Phase 5 replace the
  control, not the concept.

---

## What I need from you

1. **The model provider decision** (above). Blocking for Phase 3.
2. **A name**, or approval to proceed on `Rhumb` while you verify trademark.
3. **API keys**, when you want the sources they unlock — all free, none urgent:
   - Reddit: <https://www.reddit.com/prefs/apps> (create a "script" app → client id + secret)
   - OpenRouter, if you want the LLM fallback: <https://openrouter.ai/keys>
   - ~~OpenFIGI, to resolve the 19,851 unmapped 13F holdings~~ — **done 2026-08-24**; 12,167
     linked, 7,684 remain and are mostly ETPs the SEC ticker file does not carry (B-14)
4. **Rulings on the six ASK items** in `docs/dead_code.md` (short interest, congress flag,
   Stripe price ids, share cards, `uploads/`, the misnamed test file).
5. **Confirmation that Portfolio may be replaced by Exposure** — it works and has a real
   track record inside it, so I want that on the record before removing the surface.
