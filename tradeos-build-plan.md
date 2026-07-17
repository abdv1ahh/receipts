# TradeOS Build Plan: Slices 2 through 6

This document is the complete execution brief for everything after Slice 1. It assumes
the Slice 1 codebase is present and its tests pass: the point-in-time Postgres schema,
the EDGAR client, the Form 4 pipeline, the CLI, and the feed health API. Work through
the slices strictly in order. Every slice ends with something the founder can run and
see working. Do not begin a slice until the previous slice's acceptance criteria all pass.

---

## Part 0: Global rules that govern every slice

These are permanent, inherited from the founding brief, and non-negotiable.

**Honesty rules.**
1. Never fabricate, embellish, or simulate signal data. Every number a user sees derives
   from a real ingested record or a real computation over real records. Test fixtures are
   clearly fictional (TESTFIXTURE CORP style) and never enter the runtime database.
2. Every derived fact carries `event_time` (when it happened in the world) and
   `knowable_time` (when it became publicly knowable). All signal computation and all
   backtests query through `knowable_time` only. No exceptions, ever.
3. Staleness is displayed, never hidden. A 13F figure must visually declare its quarterly
   delay everywhere it appears.
4. All performance figures are labeled "Backtested" in the UI itself, adjacent to the
   number, not in a footer. There is no live track record yet; do not imply one.
5. Amendments (4/A, SC 13D/A, 13F-HR/A) never overwrite. They insert as new rows linked
   to the parent accession, and current-state views reconstruct belief at a point in time.
6. If a feed degrades, it degrades loudly: quarantine it out of signal computation,
   surface it on the dashboard status strip, log it. A missing feed shown honestly is
   safe; a broken feed shown confidently is fatal.

**Engineering rules.**
7. Simplicity mandate: smallest amount of code that fully and correctly solves the
   problem. Add an abstraction only when two real call sites need it today. After every
   piece of work ask what can be deleted while everything still works and stays safe,
   then delete it.
8. Tests written alongside code. Signal computations get characterization tests so a
   definition can never silently change meaning. Every new pipeline gets parser tests
   against fixtures plus validation tests plus an idempotency property (re-running is a
   no-op, enforced by DB constraints).
9. Every new feature gets a threat model in `docs/threat-models/` written before the
   code, naming attacker, method, and the design property that removes the attack.
10. Every consequential decision goes into `docs/decision-log.md` with reasoning and the
    strongest counterargument. Number entries sequentially (next is 16).
11. No secret ever appears in code, in the frontend bundle, in the repo, or in logs.
    Environment variables only, `.env` gitignored, and add a pre-commit secret scan
    (gitleaks or equivalent) in this phase of work.
12. All EDGAR fetching goes through the existing `EdgarClient`: allowlisted hosts,
    HTTPS only, throttled, declared User-Agent, checksummed.
13. Migrations are additive SQL files in `tradeos/migrations/` numbered sequentially,
    applied by the existing runner. Never edit an applied migration.

**Legal guardrails for the demo (posture until counsel exists).**
14. The product describes what smart-money sources are doing. It never tells a user what
    to buy, never says "buy/sell/should", never personalizes a recommendation. UI copy
    and LLM explanation prompts must both enforce this.
15. Invite-gated access, no payments, no public marketing pages with performance claims.
16. Congressional and short-interest sources are modular inputs (Decision 11):
    convergence must compute correctly with either or both disabled via config flag.
17. Persistent product-wide disclaimer component: "TradeOS is an analytics and education
    platform. Nothing here is investment advice. Signals describe disclosed activity by
    third parties, with delays as labeled." Rendered on every signal surface.

**Pause points requiring the founder.** Stop and ask, with exact instructions, when you
reach: (a) the Gemini API key in Slice 5, (b) the SEC_USER_AGENT contact address if not
already set, (c) any deployment credentials in Slice 6. Nothing else should block on him.

---

## Part 1: Slice 2 — Institutional pipelines and entity resolution

Goal: TradeOS recognizes that a 13D, a 13F position, and an insider buy all refer to the
same company, and the founder can browse real institutional activity.

### 1.1 Migration 002: entities and institutional tables

```sql
-- canonical entities
CREATE TABLE entities (
    id          bigserial PRIMARY KEY,
    kind        text NOT NULL CHECK (kind IN ('issuer','institution','insider')),
    cik         text UNIQUE,          -- primary resolver for all EDGAR-known entities
    name        text NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);

-- issuer <-> ticker mapping with confidence and provenance
CREATE TABLE security_map (
    id          bigserial PRIMARY KEY,
    entity_id   bigint NOT NULL REFERENCES entities(id),
    symbol      text,
    cusip       text,                 -- stored when a filing provides it; never purchased
    figi        text,                 -- from OpenFIGI when resolvable
    source      text NOT NULL,        -- 'sec_company_tickers' | 'filing' | 'openfigi'
    confidence  real NOT NULL,        -- 1.0 exact CIK map, lower for name-joins
    valid_from  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (entity_id, symbol, cusip)
);

-- 13D/13G stake events
CREATE TABLE stake_events (
    id             bigserial PRIMARY KEY,
    accession_no   text NOT NULL REFERENCES raw_filings(accession_no),
    form_type      text NOT NULL,     -- 'SC 13D','SC 13G','SC 13D/A','SC 13G/A'
    amends_accession text,
    filer_entity   bigint NOT NULL REFERENCES entities(id),
    issuer_entity  bigint REFERENCES entities(id),   -- nullable if unresolved; display as unresolved
    issuer_name_raw text NOT NULL,
    percent_owned  numeric,           -- from the cover page when parseable
    event_time     date NOT NULL,     -- date of event requiring filing
    knowable_time  timestamptz NOT NULL,
    activist       boolean NOT NULL   -- true for 13D family
);

-- 13F quarterly holdings
CREATE TABLE fund_holdings (
    id             bigserial PRIMARY KEY,
    accession_no   text NOT NULL REFERENCES raw_filings(accession_no),
    filer_entity   bigint NOT NULL REFERENCES entities(id),
    period_end     date NOT NULL,     -- quarter end: this is the event_time of the snapshot
    knowable_time  timestamptz NOT NULL,  -- acceptance time, up to 45 days later; display this gap
    cusip          text NOT NULL,
    issuer_name_raw text NOT NULL,
    issuer_entity  bigint REFERENCES entities(id),
    value_usd      numeric,           -- 13F value field (thousands pre-2023-ish, dollars after; normalize, note in code)
    shares         numeric,
    share_type     text,              -- 'SH' or 'PRN'
    UNIQUE (accession_no, cusip, share_type)
);
CREATE INDEX idx_holdings_issuer_knowable ON fund_holdings (issuer_entity, knowable_time);
CREATE INDEX idx_stakes_issuer_knowable ON stake_events (issuer_entity, knowable_time);
```

Also add `insider_transactions.issuer_entity bigint` via `ALTER TABLE` and backfill it in
a resolution pass.

### 1.2 Resolution module (`tradeos/resolution/`)

- Ingest the SEC's own `company_tickers.json` (https://www.sec.gov/files/company_tickers.json)
  through EdgarClient into `entities` (kind issuer, keyed on CIK) and `security_map`
  (source `sec_company_tickers`, confidence 1.0). CLI: `python -m tradeos.cli sync-tickers`.
- CUSIP resolution for 13F: first try `security_map` by CUSIP (populated by prior filings
  and OpenFIGI results), then OpenFIGI's free mapping API (https://api.openfigi.com,
  batch POST, respect its unauthenticated rate limits with the same throttle pattern as
  EdgarClient; add `openfigi.com` to the allowlisted-hosts pattern via a second small
  client class, do not widen EdgarClient). Store results with source `openfigi` and
  confidence 0.9. Unresolved CUSIPs stay unresolved and display as such.
- Institutions and insiders resolve purely by CIK from filings (confidence 1.0).
- Rule: never guess. A record that cannot be resolved is stored with a null
  `issuer_entity` and excluded from convergence but visible in browse views flagged
  "unresolved security".

### 1.3 13D/13G pipeline (`tradeos/ingestion/schedule13.py`)

- Index: same daily master.idx already parsed; filter form types
  `{'SC 13D','SC 13G','SC 13D/A','SC 13G/A'}`.
- These filings are messier than Form 4: many are HTML/text, not structured XML. Parse
  strategy: extract subject company CIK and filer CIK from the SGML header of the full
  submission (SUBJECT COMPANY / FILED BY blocks give CIK, company name), take
  `event_time` from "Date of Event Which Requires Filing" when present in the header or
  document, fall back to filing date with a `parse_confidence` flag lowered. Attempt
  percent-owned from cover page regex ("Percent of class", item 13 patterns); store null
  when not confidently parsed. Never invent a percentage.
- Validation: percent between 0 and 100, event_time not in future, both CIKs present.
  Rejects go to `ingest_rejects` as in Slice 1.
- CLI: `ingest-13dg --date`, `backfill-13dg --from --to`.
- Threat model doc `docs/threat-models/schedule13.md`: same feed-spoofing/SSRF/XXE
  coverage as Form 4 plus the parse-error-presented-as-fact risk; mitigation is the
  confidence flag and the never-invent rule.

### 1.4 13F pipeline (`tradeos/ingestion/form13f.py`)

- Filter form types `{'13F-HR','13F-HR/A'}` from master.idx.
- Modern 13F filings contain a structured `informationTable` XML inside the submission
  (post-2013). Parse the info table entries: nameOfIssuer, cusip, value, sshPrnamt,
  sshPrnamtType. Use defusedxml. Pre-2013 filings are out of scope; log and skip.
- `event_time` = periodOfReport (quarter end). `knowable_time` = acceptance datetime.
  The gap between them is the headline staleness story; it must be queryable, so both
  are columns, no derivation in the app.
- A large filer's info table can be tens of thousands of rows; insert with
  `execute_values`-style batching, still under the (accession, cusip, share_type)
  uniqueness for idempotency.
- Backfill scope for the demo: the most recent 8 quarters of 13F, most recent 24 months
  of 13D/13G and Form 4 (extend Form 4 backfill accordingly). This is hours of polite
  throttled fetching; make backfill resumable (it already is via idempotency; also
  print progress).
- Threat model doc: staleness misread as freshness is this pipeline's defining risk;
  removed by the two-timestamp schema and by UI rules in Slice 3.

### 1.5 Browse API + minimal browse page

- `GET /api/activity?symbol=XYZ` returns the merged, knowable_time-ordered stream of
  insider transactions, stake events, and holdings changes for a resolved issuer, each
  item tagged with source class and its own staleness (now minus event_time, and
  knowable-lag = knowable_time minus event_time).
- Extend `/api/feeds` with the two new sources.
- A single server-rendered or minimal React page is acceptable here; the real frontend
  arrives in Slice 3. Purpose: the founder can type a ticker and see real merged
  activity.

### 1.6 Slice 2 acceptance criteria

- `sync-tickers` populates entities/security_map from the SEC file.
- One real day each of 13D/13G and 13F ingests cleanly; re-running is a no-op.
- A known issuer (pick any large cap) shows merged activity across all three sources
  under one entity id.
- Unresolved records appear flagged, never guessed.
- New parser/validation/idempotency tests pass offline against fixtures; full suite green.
- Decision log updated (value_usd normalization decision, backfill scope decision).

---

## Part 2: Slice 3 — Convergence signal v1 and the dashboard

Goal: live signal clusters on screen, computed from real filings, with the versioned
signal definition and the design language in place.

### 2.1 Migration 003: signal tables

```sql
CREATE TABLE signal_definitions (
    id          bigserial PRIMARY KEY,
    name        text NOT NULL,            -- 'convergence'
    version     integer NOT NULL,
    params      jsonb NOT NULL,           -- every constant below lives here, not in code
    code_hash   text NOT NULL,            -- sha256 of the computing module file
    changelog   text NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (name, version)
);

CREATE TABLE signal_clusters (
    id             bigserial PRIMARY KEY,
    definition_id  bigint NOT NULL REFERENCES signal_definitions(id),
    issuer_entity  bigint NOT NULL REFERENCES entities(id),
    as_of          timestamptz NOT NULL,   -- computation time; all inputs have knowable_time <= as_of
    score          numeric NOT NULL,
    confidence_bucket text NOT NULL CHECK (confidence_bucket IN ('low','medium','high')),
    voices         integer NOT NULL,       -- distinct independent filers contributing
    source_classes text[] NOT NULL,        -- e.g. {insider,activist}
    inputs         jsonb NOT NULL,         -- the exact contributing events: ids, weights, decayed values
    UNIQUE (definition_id, issuer_entity, as_of)
);
CREATE INDEX idx_clusters_asof ON signal_clusters (as_of DESC);
```

### 2.2 The signal definition, v1 (implement exactly; constants in params jsonb)

Module `tradeos/signals/convergence.py`. For each issuer with any activity, over a
rolling window ending at `as_of`:

- Window: 90 days on knowable_time.
- Event base weights by class: insider purchase (code P, acquired A) 1.0; insider sale
  0 contribution to bullish score in v1 (sales are context, shown but not scored;
  log this as a decision, counterargument noted: sales are informative); 13D new stake
  1.2; 13D/A increase 0.8; 13G 0.6; 13F new position or position increase quarter over
  quarter 0.4 (the low weight encodes its staleness).
- Magnitude scaling: insider events scale by log10(1 + trade value USD)/6 capped at 1.5
  (trade value = shares * price); 13D scales by percent_owned/10 capped at 1.5 when
  percent known, else 1.0; 13F scales by log10(1 + value_usd)/8 capped at 1.2.
- Freshness decay: exponential on (as_of - knowable_time) with half-lives per class:
  insider 14 days, 13D/13G 30 days, 13F 60 days.
- Independence collapse: group events by filer entity. Each filer contributes
  max(one voice): its single highest decayed-weighted event counts fully, its additional
  events add at 25 percent. An institution's 13D and 13F on the same issuer are one
  voice (same filer CIK family). Distinct insiders at one issuer are distinct voices
  (the classic cluster-buy is genuine reinforcement).
- Score = sum of voice contributions.
- Publish gate: at least 2 distinct source classes AND at least 3 distinct voices AND
  issuer passes the liquidity floor. Liquidity floor for the demo: issuer must be
  present in the SEC company_tickers file with an exchange listing, and (once Slice 4
  price data exists, tighten to) 90-day median dollar volume above 2,000,000 USD;
  until price data exists use the exchange-listing check and log the interim state.
  Below the floor a cluster is computed but stored with confidence bucket forced 'low'
  and excluded from the default dashboard feed (visible only via explicit screener
  filter with a manipulation-risk warning). After Slice 4, sub-floor clusters do not
  publish at all.
- Confidence buckets by score thresholds in params (initial: low < 3, medium 3 to 6,
  high > 6). These are placeholders until Slice 4 calibrates them; the UI must label
  buckets "Backtested calibration pending" until Slice 4 replaces the label.
- Computation is a CLI command `compute-signals --as-of <timestamp>` writing clusters
  for that as_of, plus a `--daily` mode for backfill of daily as_of points (needed by
  Slice 4). Deterministic: same inputs, same output; add a characterization test with
  a frozen fixture dataset asserting exact scores.

On any change to constants or logic: new row in signal_definitions with version bump,
changelog text, new code_hash. The compute command refuses to run if the module hash
does not match the latest definition row (this is the "signals never silently change
meaning" guarantee, mechanically enforced).

### 2.3 Signals API

- `GET /api/clusters?as_of=latest&min_confidence=medium` — dashboard feed, ordered by
  score, each cluster carrying: issuer, symbol, score, bucket, voices, source classes,
  per-input staleness summary (freshest and stalest contributing event), and the
  definition version.
- `GET /api/clusters/{issuer_id}` — full cluster detail with every contributing event.
- `GET /api/definitions` — public methodology: all versions, params, changelogs. The
  methodology being public is product, not documentation.

### 2.4 The frontend (React, Vite, single-page)

Read `/mnt/skills/public/frontend-design/SKILL.md` before building if available in the
environment; otherwise follow this section.

Design language, binding:
- Professional terminal feel: dark theme default, dense tabular data, a monospaced
  numerals font for figures, high information density, fast first paint. Numbers load
  fast or the product is dead: skeleton rows, no spinners longer than 300ms.
- Motion budget spent on exactly two things: a freshness pulse (a value that just
  updated gets a brief subtle highlight decay) and cluster state change (new cluster
  slides in once). Restrained parallax ONLY on the landing hero and deep-dive page
  headers: translation capped at ~6px, disabled entirely under
  `prefers-reduced-motion`. No motion inside data tables. No decorative animation.
- Staleness is a first-class visual system: every data point renders with a freshness
  chip (e.g. "2d ago" green, "3w ago" amber, "Quarterly, as of Mar 31" grey). A 13F
  figure must look categorically different from a fresh Form 4. Build one
  `<Freshness>` component and use it everywhere; never render a signal number without it.
- The disclaimer component (rule 17) on every signal surface.
- Pages this slice: Dashboard (cluster feed + feed-health status strip showing the
  /api/feeds data, including reject counts, because honesty is the brand), and a
  minimal cluster detail view.

### 2.5 Slice 3 acceptance criteria

- `compute-signals` produces clusters from the real backfilled data; at least some
  real multi-class clusters exist (with 24 months of Form 4 + 13D/G and 8 quarters of
  13F, they will).
- Characterization test locks scores on a fixture dataset; changing a constant without
  a version bump makes the compute command refuse to run.
- Dashboard renders real clusters with freshness chips, status strip, disclaimer,
  reduced-motion respected.
- Definition endpoint shows v1 with full params.
- Founder can run `docker compose up`, compute, and see the dashboard.

---

## Part 3: Slice 4 — Backtest, prices, calibration

Goal: every signal bucket displays its own backtested hit rate, honestly labeled, with
the methodology one click away. This slice is the heart of the pitch.

### 3.1 Price data (Decision 15 in the log)

- Source: Stooq free end-of-day files (daily OHLCV, US symbols as `aapl.us` style).
  Terms permit this demo-scale analytical use; label "demo-grade price data" on the
  methodology page; a licensed EOD feed is the first post-funding purchase. If Stooq
  is unreachable or terms have changed at implementation time, STOP and present the
  founder the alternatives with their terms; do not silently substitute a scraped source.
- Migration 004: `prices_eod (symbol text, day date, open numeric, high numeric,
  low numeric, close numeric, volume numeric, source text, PRIMARY KEY (symbol, day))`.
- Ingest only symbols that appear in resolved clusters plus SPY (benchmark). CLI
  `ingest-prices --symbols-from-clusters`. Validate: positive prices, high >= low,
  no future dates; rejects logged.
- Prices are not adjusted for splits/dividends in Stooq's raw files in all cases;
  use their adjusted series where available and record which series was used per
  symbol in a `source` note. State this limitation on the methodology page. Never
  hide a data limitation.

### 3.2 Backtest engine (`tradeos/backtest/`)

- Replay: for each historical day D in the backfilled range, clusters as computed with
  `as_of = D` (from the `--daily` compute backfill) represent exactly what was knowable
  on D. Forward returns: excess return of the issuer's symbol vs SPY over 30, 90, 180
  calendar days from the first trading day after D (entry at that day's close;
  document this convention). A "hit" = positive excess return over the horizon.
- Outcomes table:
```sql
CREATE TABLE signal_outcomes (
    cluster_id  bigint PRIMARY KEY REFERENCES signal_clusters(id),
    entry_day   date NOT NULL,
    excess_30   numeric, excess_90 numeric, excess_180 numeric,  -- null until horizon complete
    computed_at timestamptz NOT NULL DEFAULT now()
);
```
- Deduplication for honesty: consecutive daily clusters on the same issuer are the same
  underlying episode. Define an episode as issuer clusters with no gap > 14 days;
  backtest statistics count each episode once, entering at its first day. Report both
  episode count and raw cluster count.
- Calibration output per confidence bucket per horizon: hit rate, mean and median
  excess return, episode count, and a simple binomial 95 percent interval on the hit
  rate. If a bucket has fewer than 30 episodes, the UI shows "insufficient sample"
  instead of a percentage. Never display a rate on a tiny sample.
- Survivorship honesty: the symbol universe comes from filings (companies that existed
  and filed), which limits survivorship bias but delisted symbols may lack price data.
  Count and display the coverage: "N episodes excluded for missing price history."
  Excluding silently is forbidden; the exclusion count is part of the methodology page.
- Characterization test: frozen mini-universe fixture (a handful of fictional symbols
  with synthetic price paths clearly labeled as test fixtures) asserting exact hit-rate
  outputs. Look-ahead test: assert the engine raises if asked to use any record with
  knowable_time > as_of (write this test by attempting to smuggle one in).

### 3.3 Product surfaces

- Every cluster in the dashboard and detail views now renders its bucket's backtested
  hit rate and sample size beside the confidence bucket, with the literal label
  "Backtested" as part of the component, plus the horizon selector (30/90/180).
- Methodology page (public within the app): full signal definition params, backtest
  conventions, price-data grade, exclusion counts, calibration table per bucket, and
  the pre-commitment sentence: "Live track record accrues from launch; the live
  calibration curve replaces this backtest at 200 resolved signals per type."
- Recalibrate bucket thresholds once against backtest results if the initial
  placeholders are clearly wrong; that is a v2 of the signal definition with a
  changelog entry, done once, before the demo, and disclosed.

### 3.4 Slice 4 acceptance criteria

- Prices ingested for all cluster symbols + SPY with validation.
- Daily as_of compute backfilled across the data range; episodes derived; outcomes
  computed for all completed horizons.
- Look-ahead test passes (engine structurally refuses future knowledge).
- Dashboard shows hit rates with "Backtested" labels and sample sizes; methodology
  page complete with exclusion counts.
- Decision log updated (entry conventions, episode definition, any threshold
  recalibration as signal v2).

---

## Part 4: Slice 5 — Modular inputs, explanations, deep dives, previews

### 4.1 Congressional trading pipeline (modular input A)

- Config flag `ENABLE_CONGRESS=true/false`; convergence must compute correctly either way
  (Decision 11: the EIGA commercial-use question means counsel may order this pulled).
- Sources: House and Senate financial disclosure portals (periodic transaction reports).
  Senate PTRs are frequently structured web tables; House PTRs are often scanned PDFs.
  Demo scope: ingest the structured/parseable subset only; every record carries
  `parse_confidence`; low-confidence parses never feed convergence, only the browsable
  record; display coverage statistics ("structured filings only") rather than implying
  completeness. Amounts are disclosed as ranges; store range bounds, never a midpoint
  presented as a value.
- New source class weight in signal params (signal v2 or v3 with changelog): base 0.5,
  half-life 30 days, magnitude scale by log of range midpoint used ONLY for scaling,
  never displayed as the amount.
- Threat model doc: parse error presented as fact; disclosure gaming (members file at
  the 45-day limit); both mitigated by confidence flags and by displaying the filing
  lag on every record.

### 4.2 Short interest pipeline (modular input B)

- Config flag `ENABLE_SHORT_INTEREST`. FINRA publishes consolidated short interest
  twice monthly. Ingest the published files via a small dedicated client (allowlist
  finra.org hosts), schema-validate, store with event_time = settlement date and
  knowable_time = publication date. Display derived changes (short interest ratio
  change) rather than republishing raw files wholesale (licensing posture per the
  decision log). In convergence v-next: short-interest DECREASE on a name with other
  bullish classes contributes 0.3 weight; increase contributes context display only.
- If FINRA's current terms at implementation time require registration or explicitly
  forbid this use even at demo scale, STOP, present the founder the terms and options,
  and proceed with the flag off.

### 4.3 Explanation layer (PAUSE POINT: Gemini key)

- Interface `tradeos/explain/base.py`: `explain(cluster: ClusterDetail) -> Explanation`
  where Explanation carries prose plus the model/template identifier for display.
- Three implementations selected by env var `EXPLAIN_PROVIDER=template|gemini|anthropic`:
  - `template.py`: deterministic prose assembled from the cluster's real fields. This
    is the always-available path and the default when no key is set.
  - `gemini.py`: calls the Gemini API (founder's key via `GEMINI_API_KEY`). Prompt: the
    computed values only, instruction to explain what the disclosed activity shows, to
    attribute every fact to its source class and staleness, to use probability-framed
    language, and to never use directive language (buy, sell, should, recommend) and
    never introduce numbers not present in the payload.
  - `anthropic.py`: same contract, slot open, activates when `ANTHROPIC_API_KEY` exists.
- Numbers guard, enforced in code after any LLM call: extract all numeric tokens from
  the output; any number absent from the input payload (allow formatting variants:
  thousands separators, rounding to the payload's own displayed precision, percents)
  discards the response and renders the template instead, logging the event. Also a
  directive-language guard: reject outputs containing buy/sell/should-style directives.
- Explanations are cached per (cluster id, definition version, provider) so a model
  outage or key exhaustion never blanks the dashboard.
- When you reach this section: pause and give the founder exact steps to create the
  key in Google AI Studio and set `GEMINI_API_KEY` in `.env`, then continue. Build and
  test the template path first so the pause never blocks the slice.

### 4.4 Deep-dive and profile pages

- Asset deep dive `/asset/:symbol`: cluster history, the full merged activity stream
  (Slice 2 API) with freshness chips, contributing filers, explanation panel, price
  chart with cluster markers (only where price data exists), backtested stats for this
  name's episodes if >= 5, else "insufficient sample".
- Smart-money profile `/institution/:id` and `/insider/:id`: positioning over time
  purely from public filings, with every figure carrying its knowable_time lag.
- Screener `/screener`: filter clusters by source class, confidence, staleness,
  liquidity floor status (sub-floor visible only here, wrapped in the manipulation-risk
  warning).

### 4.5 Preview surfaces (Decision 8, binding rules)

- Routes `/preview/options` and `/preview/crypto`, linked from the dashboard nav under
  a "Roadmap" section.
- Data: static fixture JSON files living in the frontend bundle only
  (`frontend/src/previews/fixtures/`), obviously illustrative tickers and wallets.
  These files NEVER touch the backend or database. No API serves them.
- Every preview screen: persistent top banner "PREVIEW — illustrative design, not live
  data. Options and on-chain feeds arrive post-funding.", a diagonal watermark across
  chart areas, and a visually distinct style token (e.g. a hatched background tint) so
  a screenshot can never be mistaken for the live product.
- Content: the options surface shows the designed experience for unusual-activity/flow
  clusters; the crypto surface shows whale-cohort convergence design. Design them
  properly; they carry the investor vision. But the honesty chrome is non-removable:
  build the banner/watermark into the preview layout component, not per page.

### 4.6 Intelligence library (small and deep, per Decision in Phase 0)

- Purpose: the layer that teaches while the signals inform, and the strongest
  regulatory anchor on the education side of the line.
- Content model: markdown files in `content/library/`, each with frontmatter
  (title, tags, sources array with URLs, concepts array). Twenty entries for the
  demo: roughly twelve investor/framework profiles built strictly from public
  domain material, published shareholder letters, interviews, and regulatory
  filings, and eight curriculum entries (position sizing, insider signal research
  basics, 13F mechanics and their delay, activist campaigns, market structure,
  risk management, derivatives basics, reading a filing).
- Sourcing rules, binding: every entry lists its sources; original synthesis in
  the platform's own words; never reproduce copyrighted books or paywalled
  research; quotations minimal and attributed. If a planned entry cannot be
  sourced cleanly, write a different entry instead.
- Wiring: each source class and common cluster pattern maps to concept tags; the
  cluster detail page and explanation panel render "Understand this pattern"
  links into the library. The template explainer includes the links too, so the
  teaching layer never depends on an LLM.
- Route `/library` with an index and entry pages; same freshness/disclaimer chrome.
- Writing the twenty entries is real work: generate drafts flagged for founder
  review in `docs/review-queue.md`, since published educational content carries
  the brand's credibility.

### 4.7 Slice 5 acceptance criteria

- Congress and short-interest flags toggle cleanly; convergence identical with both off.
- Template explanations render for every cluster with zero keys configured; Gemini path
  works once the key is provided; numbers guard and directive guard have tests (feed a
  mocked LLM response containing an invented number / the word "buy" and assert the
  template fallback).
- Deep dive, profiles, screener render from real data.
- Previews carry banner + watermark, contain no backend calls (assert with a test that
  the preview routes make no /api requests).
- Library renders twenty entries, each with listed sources; cluster details link into
  relevant concepts; drafts queued for founder review.

---

## Part 5: Slice 6 — Auth, entitlements, hardening, demo readiness

### 5.1 Auth (demo-grade but real)

- Migration: `users (id, email citext unique, password_hash text, tier text NOT NULL
  DEFAULT 'free' CHECK (tier IN ('free','retail','pro','admin')), totp_secret text,
  created_at)`, `sessions (id, user_id, token_hash, created_at, expires_at, ip, ua)`,
  `invites (code, created_by, used_by, used_at)`, `audit_log (id, actor, action,
  object, at timestamptz, detail jsonb)` append-only with the same immutability trigger
  as raw_filings.
- argon2id password hashing; breached-password check via a local top-100k list at demo
  scale (no external call leaking credentials); session cookie HttpOnly + Secure +
  SameSite=Lax, 24h expiry with rotation on privilege change; login rate limit
  (per-IP and per-account, simple Postgres counter is fine at demo scale); registration
  requires a valid unused invite code; TOTP required for the admin tier; new-session
  email can be stubbed to log output for the demo (no email provider yet) and logged
  as such.
- Every privileged action (invite creation, tier change) writes to audit_log.

### 5.2 Entitlements and the free-tier delay

- Tier resolved server-side from the session on every request. The free-tier delay is
  a WHERE clause in the cluster queries: `knowable_time <= now() - interval '48 hours'`
  applied when tier = free, inside the query layer, with a test asserting a free
  session cannot retrieve a fresh cluster by any parameter manipulation. Object-level
  checks on watchlists (if watchlists are built this slice, keep them minimal: a table
  and add/remove; they are demo garnish, cut first under time pressure).
- Free tier sees the full methodology page always (verifiability is the funnel).

### 5.3 Hardening checklist (do all)

- Security headers middleware: CSP (no inline scripts; Vite build accordingly),
  X-Content-Type-Options, X-Frame-Options DENY, Referrer-Policy, HSTS behind TLS.
- CSRF: SameSite=Lax plus origin-check middleware on state-changing routes.
- Strict input validation via Pydantic models on every endpoint; uniform error shape;
  no stack traces to clients.
- Rate limiting on all API routes (generous) and auth routes (tight).
- Dependency audit: `pip audit` and `npm audit` clean or exceptions documented;
  lockfiles committed; gitleaks pre-commit hook installed and a full-history scan run
  once (treat any finding as an incident: rotate, document).
- Docker: non-root user in the image, pinned base image digest.
- Egress note in README deployment section: production ingestion runs with a network
  allowlist of exactly sec.gov, openfigi.com, finra.org, stooq.com, and the LLM
  provider; document how to set this on the chosen host.

### 5.4 Demo readiness

- Seed script: creates the admin (prompting for password at runtime, never hardcoded)
  and N invite codes.
- A `make demo` / `just demo` path: compose up, migrate, sync-tickers, backfill (with
  a documented smaller "quick demo" range for a fast rebuild), compute daily signals,
  ingest prices, run backtest, ready.
- Demo walkthrough doc `docs/demo-script.md`: the exact investor flow — open dashboard,
  pick a real cluster, click into the deep dive, verify one Form 4 against EDGAR live
  in front of them (the trust moment; include the EDGAR full-text search URL pattern
  for doing it), show the methodology and calibration page, show the previews last.
- Deployment: one small VPS or Railway-class PaaS, TLS via the platform or Caddy,
  Postgres backed up daily (document the restore command; an untested backup is not a
  backup). PAUSE for founder credentials at this point.
- Final pass, per the simplicity mandate: a deletion review across the whole codebase.

### 5.5 Slice 6 acceptance criteria

- Registration only via invite; free/retail tiers enforce the delay clause with a test
  proving the bypass attempt fails server-side.
- Admin requires TOTP; audit log receives privileged actions and refuses UPDATE/DELETE.
- Headers, CSRF, rate limits verified (add a small test hitting each).
- Full test suite green; `make demo` produces a working system from scratch; demo
  script written; decision log and threat models current.

---

## Part 6: Standing instructions for the whole build

- Work one slice at a time. Open each slice by writing its threat model docs and any
  new decision-log entries, then migrations, then code with tests, then UI.
- After each slice, print for the founder: what to run, what he should see, what
  decisions were logged, and anything needed from him.
- If anything in this plan turns out technically impossible, legally risky, or
  contradicted by reality at implementation time (a changed API, changed terms of use,
  a dead endpoint), STOP on that item, say so plainly, propose the closest working
  alternative, and log it. Never quietly ship a weaker interpretation, never present
  stubbed logic as finished work, and never let fabricated data touch the runtime
  database.
- The bar, always: a skeptical trader checks one signal against EDGAR and finds it
  accurate and honestly labeled. Every line of code either serves that moment or is
  a candidate for deletion.

---

## Part 7: Completeness addendum

This part closes gaps found in an audit of this plan against the founding brief and
the Phase 0 and Phase 1 commitments. Everything here is binding. It adds four small
work items, flags one scope decision, and makes every deliberate deferral explicit so
absence is always a decision, never an omission. Log the decisions below as entries
16 through 19 in the decision log when you begin Slice 2.

### 7.1 Intelligence library, demo scope (build in Slice 5)

Phase 0 committed a small, deep library at launch; it belongs in the demo because it
is the education half of the regulatory posture. Scope: 12 to 20 entries, two kinds.

- Migration (with Slice 5's other work):
```sql
CREATE TABLE library_entries (
    id        bigserial PRIMARY KEY,
    slug      text UNIQUE NOT NULL,
    kind      text NOT NULL CHECK (kind IN ('concept','investor_profile')),
    title     text NOT NULL,
    body_md   text NOT NULL,
    sources   jsonb NOT NULL,        -- [{title, url, basis: 'public_domain'|'public_filing'|'published_interview'}]
    linked_source_classes text[] NOT NULL DEFAULT '{}',
    created_at timestamptz NOT NULL DEFAULT now()
);
```
- Content rules, absolute: every entry is original prose written in the platform's own
  words; every factual claim traceable to a listed public source; no reproduction of
  copyrighted books, letters, or paywalled research; direct quotation at most a short
  attributed phrase, and prefer none. Investor profiles state documented, publicly
  sourced philosophy and track record only, no invented views.
- Priority entries: concepts first (insider cluster buys and their research history,
  activist 13D stakes, 13F staleness and how to read quarterly snapshots, position
  sizing basics, why convergence beats single signals, base rates and calibration,
  survivorship and look-ahead bias, short interest mechanics, congressional disclosure
  mechanics and their limits). Profiles second, only where public material is deep.
- Wiring: cluster detail and deep-dive pages render "Understand this pattern" links by
  matching `linked_source_classes` to the cluster's classes. Library index page at
  `/learn`. This is the "teaches in the same moment it informs" requirement.

### 7.2 Geofence and feature-flag hook (build in Slice 6, ~1 hour)

Phase 0 committed that the geofence switch exists from the start because it is cheap
now and a fortune retrofitted. Demo scope: a `feature_flags` table (name, enabled
boolean, blocked_countries text[]) plus one gate function used by the API layer, with
the request country taken from a proxy header when present (document
`CF-IPCountry`/`X-Country` style) and an env default of unrestricted for local runs.
Demo default: everything enabled everywhere, invite gating is the real control. The
point is that the day a lawyer says "not feature X in jurisdiction Y," it is a row
update, not a rebuild. Wire the congress and short-interest flags (4.1, 4.2) through
this same table instead of bare env vars.

### 7.3 Alerts, demo scope (Slice 6, cut first under time pressure)

The full tunable alerting system from the brief (delivery channels, per-signal tuning)
is post-demo. Demo scope, small and honest: watchlists (add/remove symbols) plus an
in-app indicator, "N new clusters on your watchlist since your last visit," computed
server-side with the tier delay clause applied. No email or push infrastructure. If
Slice 6 runs long, this section is the designated cut, stated here so cutting it is
pre-approved and logged rather than silent.

### 7.4 Operational honesty items (Slice 6)

- Error tracking: support a Sentry-compatible DSN via env var, active only when set.
- Incident runbook: write `docs/runbooks/leaked-secret.md` (rotate the credential,
  invalidate sessions if auth-adjacent, run a full-history gitleaks scan, record the
  incident in the decision log) and `docs/runbooks/feed-quarantine.md` (how a
  quarantined feed is verified and restored). Short, real, rehearsable.
- Pre-publication access logging: any admin-tier API read of clusters newer than the
  free-tier delay window writes an `audit_log` row with action `prepub_access`. This
  is the seed of the staff-trading answer regulators will one day ask for. Also add
  `docs/staff-trading-policy.md` as a one-page template for signature at
  incorporation (no personal trading on pre-publication clusters, blackout until a
  cluster is public to free tier, all staff access logged).

### 7.5 Backfill scope, flagged scope decision (log as entry 16)

Phase 1 named a ten-year backfill target; this plan's Slice 2 specifies 24 months of
Form 4 and 13D/G plus 8 quarters of 13F. That narrowing is deliberate for the
three-week demo window given polite throttled fetching, and the calibration page must
therefore state its actual sample window. The ten-year backfill happens post-demo as
a batch job over EDGAR's quarterly full-index archives, and must complete before any
public launch so published calibration rests on the deep sample. Counterargument to
the narrowing: investors may ask why the sample is short; the methodology page's
honesty about it is the answer.

### 7.6 Deferred registry (explicit, with return points)

Deferred to post-funding, pre-first-paid-user: professional tier API with scoped,
rotatable, hashed API keys; canary records for dataset traceability; payments and
billing (webhook signature verification, audit-logged billing state); licensed EOD
price feed replacing demo-grade prices; licensed options flow.

Deferred to pre-public-launch: external penetration test with findings fixed;
ten-year backfill (7.5); incident response rehearsal; new-device email alerts on a
real email provider; production egress allowlisting verified on the host.

Deferred to the crypto expansion: on-chain pipelines, TimescaleDB migration,
streaming infrastructure, wallet cohort independence analysis, Shariah screening
overlay evaluation, meme-coin trend detection with liquidity floors and mandatory
corroboration.

Deferred to post-launch: bug bounty, SOC 2 path, live calibration curve replacing
the backtest at the pre-committed 200 resolved signals per type, sector-adjusted
benchmarks (signal v2 era), paper-trading sandbox, theme and narrative pages,
broker API integrations, full tunable alerting with delivery channels, Form 144,
CFTC Commitments of Traders, non-US insider disclosure regimes.

Nothing in this registry may be quietly promoted into the demo build; each returns
via a decision-log entry when its phase arrives.
