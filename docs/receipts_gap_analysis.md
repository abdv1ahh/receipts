# Receipts — the gap between what is built and a caller who can use it alone

**Written 2026-09-15.** Every number here was measured against the running stack this morning
(`docker compose ps`: api, db, worker all up) or read out of the code at `main` `1bad9f4`. Nothing
is quoted from an earlier document without being re-checked, and §5 contains a **correction to
`docs/receipts_protected.md`** found by measurement.

**Target user, as decided: the CALLER.** Someone who already publishes market opinions in public —
a fintwit account, a Discord room owner, a newsletter writer, a trading educator — and who needs a
track record nobody can accuse them of faking. The checker is not the customer; the checker arrives
because the caller shares a page.

**Read §4 and §6 if you read nothing else.** §1–§3 are the inventory those two rest on.

---

## Section 0: the branch push

`signal/pure-insider-v5` is pushed and preserved:

```
 * [new branch]      signal/pure-insider-v5 -> signal/pure-insider-v5
branch 'signal/pure-insider-v5' set up to track 'origin/signal/pure-insider-v5'.
```

Note for the record: `git log main..signal/pure-insider-v5` is **empty** — the branch was already
merged into `main` at `1bad9f4 Merge the pure-insider signal measurement into main`. The ref now
exists on origin as a permanent pointer at `a6ebfd3`. The negative result is kept. Nothing was
deleted.

---

# SECTION 1: WHAT EXISTS

## 1.1 Every Receipts route

15 routes. The app holds **140** routes in total (`grep -c '^@app\.\(get\|post\|put\|delete\|patch\)' tradeos/app.py`);
these are the ones that belong to this product. All live in `tradeos/app.py` lines 3083–3460.

| # | Method | Path | Line | Auth | What it does | Called by a frontend? |
|---|---|---|---|---|---|---|
| 1 | POST | `/api/callers` | 3144 | session | Claim a handle. Validates against `_HANDLE_RE` (2–30 chars, `[a-z0-9][a-z0-9-]*`), refuses 22 `_RESERVED_HANDLES`, refuses without `jurisdiction_attested`, refuses a non-`https://` audience URL, refuses a second caller per user | ✅ `api.js:194 claimHandle` → `publish.jsx` `ClaimHandle` |
| 2 | GET | `/api/callers/me` | 3194 | session | The signed-in user's caller row + their summary + the disclaimer | ✅ `api.js:189 fetchMyCaller` → `publish.jsx`, `record.jsx` `MyRecord` |
| 3 | POST | `/api/callers/verify/start` | 3209 | session | Issues a one-time code (`receipts-verify-` + 8 chars, 40 bits), supersedes any pending request | ✅ `api.js:196 verifyStart` → `publish.jsx` `Verify` |
| 4 | POST | `/api/callers/verify/confirm` | 3227 | session | Stores the evidence URL (https only, **never fetched** — SSRF), moves it into the review queue | ✅ `api.js:197 verifyConfirm` → `publish.jsx` `Verify` |
| 5 | GET | `/api/admin/callers/pending` | 3245 | admin | The reviewer queue: everything pending with an evidence URL | ❌ **NOTHING CALLS THIS** |
| 6 | POST | `/api/admin/callers/{verification_id}/verify` | 3254 | admin | Approve or reject; approving stamps `callers.verified_at` | ❌ **NOTHING CALLS THIS** |
| 7 | POST | `/api/calls` | 3266 | session + `publish` rate bucket (20/hour) | Seal a call into the chain. Returns the sealed row **including its hashes** | ✅ `api.js:195 publishCall` → `publish.jsx` `Form` |
| 8 | GET | `/api/calls/scoreability?symbol=` | 3290 | session | Live "can this be scored" as the symbol is typed | ✅ `api.js:191 fetchScoreability` → `publish.jsx` |
| 9 | GET | `/api/calls/{call_id}` | 3302 | **public** | One call with the full proof panel + `context_snapshot` + caller identity | ✅ `api.js:188 fetchCall` → `calldetail.jsx` |
| 10 | GET | `/api/receipts/methodology` | 3323 | **public** | Scoring rules as data (never hardcoded in a surface) + `scoreable_universe` | ✅ `api.js:187` → `methodology.jsx` |
| 11 | GET | `/api/receipts/{handle}` | 3332 | **public** | One caller's whole record: summary, misses-first, calibration, every call (summary fields), chain head | ✅ `api.js:185 fetchRecord` → `record.jsx` |
| 12 | GET | `/api/receipts/{handle}/verify` | 3364 | **public** | Recomputes every hash live and returns `intact`, `links`, `head`, and the `does_not_prove` caveat | ✅ `api.js:186 verifyChain` → `receiptsui.jsx` `ChainStrip` |
| 13 | GET | `/api/board` | 3379 | **public** | Every caller ranked, plus the pooled house figure and the ranking note | ✅ `api.js:184 fetchBoard` → `board.jsx` |
| 14 | GET | `/api/card/receipt/{handle}.svg` | 3394 | **public** | 1200×630 SVG share card, `Cache-Control: public, max-age=300` | ⚠️ referenced only by the server-rendered `/r/{handle}` page — no React file fetches it |
| 15 | GET | `/r/{handle}` | 3414 | **public** | Server-rendered share page with OG tags | ⚠️ not a React route; it links *into* `/record?handle=` |

**Route ordering is load-bearing.** `/api/receipts/methodology` (3323) is registered **before**
`/api/receipts/{handle}` (3332). Swapping them makes `methodology` match as a handle and a caller
holding it could never have their record served. Guarded by `_RESERVED_HANDLES`.

Middleware wiring in `tradeos/app.py:370–381`:

```python
_PUBLIC_PREFIXES = ("/api/public/", "/api/ledger", "/api/receipts", "/api/board", "/r/",
                    "/api/card/receipt/", "/api/calls/")
_PUBLISH_PATHS = ("/api/calls",)
```

`_limit_bucket` returns `"publish"` only for `POST /api/calls` and `"public"` for the rest.
`/api/calls` (POST, no trailing slash) does not match the `/api/calls/` public prefix, so a
publish cannot be billed to the public bucket. Limits: `public` 120/60s, `publish` **20/3600s**
(`tradeos/ratelimit.py:37,49`) — chosen because a sealed row is permanent damage, not load.

## 1.2 Every table, with live row counts

Measured 2026-09-15 from `pg_stat_user_tables`. **64 tables.** The three that are Receipts:

| Table | Rows | Note |
|---|---:|---|
| **`calls`** | **473** | The chain. No second copy exists anywhere, by design |
| **`callers`** | **2** | Both `is_house`, both `kind='algorithm'`, both `user_id IS NULL` |
| **`caller_verifications`** | **0** | The verification flow has never been used |

Plus the objects that make them mean anything: `calls_append_only()` + `calls_append_only_trg`
(BEFORE UPDATE OR DELETE), `calls_due_idx`, `callers_one_per_user_idx` (partial unique on `user_id`),
`caller_verifications_caller_idx`. Migrations `034_receipts.sql` and
`035_receipts_seal_the_measurement.sql`, both applied, `schema_migrations` at **35**.

The remaining 61 tables, for the deletion decision in §5:

```
alert_prefs 1            api_keys 2               audit_log 60            auth_tokens 5
billing_events 0         chart_analyses 1         claim_outcomes 908      claims 774
content_reports 0        country_exposure 10      daily_briefs 5          email_outbox 0
entities 23535           event_clusters 6083      events 7161             explanation_cache 5
feature_flags 6          feed_health 17           follows 7               fund_holdings 24982
ingest_rejects 4024      insider_transactions 759423   invites 21         job_runs 3096
journal_reports 1        library_entries 20       login_attempts 176      market_events 4349
news_analysis 685        news_item_entities 1691  news_items 4632         notifications 16
oauth_identities 0       oauth_states 0           portfolio_positions 42  portfolios 4
prices_eod 2237206       radar_filters 0          raw_filings 531897      schema_migrations 35
security_map 13170       sentiment_observations 4977   sessions 87        short_interest 34402
signal_clusters 17669    signal_definitions 6     signal_outcomes 631     source_calls 201
stake_events 135925      subscriptions 1          trade_analyses 5        trade_comments 0
trade_context 8          trade_reactions 1        trades 8                user_follows 0
user_profiles 1          users 6                  watchlist_accounts 24   watchlists 6
wiki_titles 564
```

**`users` holds 6 rows, 4 of which are test accounts.** `invites`: 18 unused of 21. That is the
entire user base.

Price coverage, which every verdict depends on: `prices_eod` **2,237,206 rows / 2,018 distinct
symbols**, newest close **2026-09-14**, SPY newest **2026-09-14**, and only **68 of 2,018** symbols
sit more than 5 sessions behind SPY. The price feed is currently healthy.

## 1.3 Every source file, with line counts

**Backend — Receipts proper: 8 files, 1,417 lines.**

| File | Lines | Job |
|---|---:|---|
| `tradeos/receipts/__init__.py` | 14 | |
| `tradeos/receipts/chain.py` | 150 | The hash chain. Pure — no DB, no clock, no randomness |
| `tradeos/receipts/calls.py` | 328 | Validation, scoreability, sealing, reading |
| `tradeos/receipts/scoring.py` | 225 | Resolution against EOD prices, benchmarked to SPY |
| `tradeos/receipts/record.py` | 355 | Counts, intervals, calibration, the board, methodology |
| `tradeos/receipts/verification.py` | 146 | Proving a caller controls their audience |
| `tradeos/receipts/context.py` | 61 | Freezing what the system showed at publish time |
| `tradeos/receipts/seed.py` | 166 | Importing the two house records |

**Frontend — 6 files, 1,391 lines.**

| File | Lines |
|---|---:|
| `frontend/src/board.jsx` | 138 |
| `frontend/src/record.jsx` | 300 |
| `frontend/src/publish.jsx` | 361 |
| `frontend/src/calldetail.jsx` | 187 |
| `frontend/src/methodology.jsx` | 125 |
| `frontend/src/receiptsui.jsx` | 280 |

**Direct dependencies Receipts cannot run without.**

| File | Lines | What Receipts takes from it |
|---|---:|---|
| `tradeos/ledger.py` | 414 | `price_series`, `verdict_for`, `NOISE_FLOOR`, `mean_ci`, `proportion_z`, `sample_needed`, `CONFIDENCE_BUCKETS` |
| `tradeos/backtest/engine.py` | 128 | `Series`, `entry_day_after`, `exit_day_for`, `excess_return`, `wilson_interval` |
| `tradeos/journal_context.py` | 363 | `ranked_for`, `summarize` — two functions only |
| `tradeos/presentation.py` | 284 | `receipt_card_svg`, `_xml_escape` (route-layer only) |
| `tradeos/relevance.py` | 335 | transitive, via `journal_context` |
| `tradeos/geography.py` | 189 | transitive, via `relevance`. Imports nothing internal |
| `tradeos/trades.py` | 281 | transitive only — **no Receipts code path calls it** (§5) |
| `tradeos/llm.py` | 302 | transitive only — **no Receipts code path calls it** (§5) |
| `tradeos/app.py` | 3,525 | the 15 routes |

Whole `tradeos` package: **21,733 lines of Python.** Receipts is 1,417 of them — **6.5%**.

## 1.4 Every test file, with counts

`make test` measured this morning: **874 passed, 1 warning, 3.75s.** (`CLAUDE.md` still says 834 —
it has not been reconciled since the v5 measurement work landed. That is a doc drift, not a
failure.)

| File | Tests | Covers |
|---|---:|---|
| `tests/test_receipts.py` | 34 | Integrity against a live database: the trigger, scoreability, entry/exit, the noise floor, the 035 seal |
| `tests/test_receipts_api.py` | 24 | The routes |
| `tests/test_receipts_chain.py` | 18 | The chain, including the frozen wire format |
| `tests/test_navigation.py` | 7 | That no surface is unreachable |
| **Total** | **83** | |

`ruff check` is clean.

## 1.5 The append-only guarantee — provoked, not quoted

Run inside `BEGIN … ROLLBACK` against the live database this morning, against call id 95:

| Statement | Database response |
|---|---|
| `DELETE FROM calls WHERE id=95` | ❌ `calls rows are append only and cannot be deleted` |
| `UPDATE calls SET thesis='edited'` | ❌ `sealed columns on calls are immutable` |
| `UPDATE calls SET verdict='hit'` | ❌ `a resolved call is immutable, including the figures it was scored on` |
| `UPDATE calls SET excess_return=0.42` | ❌ `a resolved call is immutable, including the figures it was scored on` |
| `UPDATE calls SET context_snapshot='{}'` | ❌ `sealed columns on calls are immutable` |

473 rows before, 473 after. **The product's central claim is real and it is enforced in Postgres,
not in Python**, so it binds `psql`, a future admin tool, and anyone with the database password.

## 1.6 The complete flow: a caller registers and makes a call

Every step, in order, with the function that runs it.

**Stage A — getting an account. This is where it stops today.**

1. Visitor lands on `/auth` (the marketing site's "Start free" CTA, `site/src/sections.jsx:16`).
2. `frontend/src/views.jsx:342–372` renders the auth form. In register mode it shows **three**
   fields: email, password, and `"invite or referral code"`.
3. `api.js authRegister` → `POST /api/auth/register` (`tradeos/app.py:443`).
4. `flags.enabled(conn, "registration")` gate.
5. `authn.register` (`tradeos/authn.py:147`):
   - `is_weak_password` check
   - `INSERT INTO users` (unique email)
   - `UPDATE invites SET used_by=… WHERE code=%s AND used_by IS NULL`
   - **if `rowcount != 1`**, fall back to `SELECT id FROM users WHERE referral_code = %s`
   - **if neither matches → `conn.rollback()` and `raise AuthError("invalid or already-used invite code")`**
   - `_create_session`, then `launch_free` grants tier `pro` because `STRIPE_SECRET_KEY` is unset
6. `_set_session_cookie(response, token)` — cookie `tos_session`.

**Step 5 is a wall.** There is no path to an account without either an operator running
`cli create-invites` or an existing user handing over their referral code.

**Stage B — claiming a handle.**

7. Caller navigates to `/publish`. `App.jsx` renders `PublishView` (`publish.jsx:318`).
8. `PublishView` → `fetchMyCaller()` → `GET /api/callers/me` → `_caller_for_user(conn, user["id"])`.
9. No caller row → `publish.jsx:20 ClaimHandle` renders: handle, display name, audience URL, bio,
   and a **jurisdiction attestation checkbox that is not pre-checked**.
10. `claimHandle()` → `POST /api/callers` (`app.py:3144`) → validates `_HANDLE_RE`,
    `_RESERVED_HANDLES`, `jurisdiction_attested`, the https-only audience URL, one-caller-per-user,
    handle uniqueness → `INSERT INTO callers`.

**Stage C — publishing a call.**

11. `publish.jsx Form` renders: symbol, direction (up/down), horizon (7/30/90), confidence
    (low/medium/high), thesis (≥40 chars with a live counter).
12. As the symbol is typed: `fetchScoreability(symbol)` → `GET /api/calls/scoreability` →
    `receipts.calls.scoreability()` (`calls.py:105`) → `_last_close()` for both the symbol and SPY
    → returns one of four states, each with a sentence: no symbol / no benchmark prices / no series
    for this symbol (**permanent**) / more than `STALE_TOLERANCE_DAYS=5` behind (**operational**) /
    scoreable. Rendered as a green, amber or red strip.
13. The consent panel states, in five bullets: sealed on submit, cannot be edited, cannot be
    deleted, horizon/direction/thesis fixed, scored against SPY whichever way it goes.
14. `publishCall()` → `POST /api/calls` (`app.py:3266`). Rate-limited to 20/hour.
15. `receipts.calls.publish()` (`calls.py:172`), one transaction:
    - `validate(spec)` returns **all** problems at once, not the first
    - `normalise(spec)`
    - `SELECT id, user_id FROM callers WHERE id=%s FOR UPDATE` — the lock that makes `seq` safe
      against a double-click fork
    - `head(conn, caller_id)` → `(last_seq, prev_hash)`, or `(0, GENESIS_HASH)` for a first call
    - `chain.seal(sealed, prev_hash)` → `canonical_payload` (10 fields,
      `name:byte-length:value`, newline-joined, order frozen forever) then
      `sha256(prev_hash + payload)`
    - `scoreability()` again — **only `permanent` seals `unscoreable` at publish**; an operational
      gap publishes OPEN with the warning
    - `context.capture()` → `journal_context.ranked_for` + `summarize`, wrapped in a bare `except`
      that falls back to `context.empty(now, reason)` so a Radar failure can never block a publish
    - `INSERT INTO calls (…16 columns…) RETURNING id`
    - `conn.commit()`
16. The response carries `content_hash`, `prev_hash` and `canonical_payload` — the receipt is
    returned to the caller, not just "saved".

**Stage D — resolution.**

17. `scheduler.JOBS` entry `("resolve_calls", 21600, _job_resolve_calls)` — every 6 hours.
18. `scoring.resolve_due(conn, limit=100)` (`scoring.py:197`): loads SPY once, then
    `SELECT id FROM calls WHERE verdict IS NULL AND published_at::date + horizon_days <= now()`.
19. Per call, `scoring.resolve_call()`: `ledger.price_series` for both legs →
    `backtest.engine.excess_return` → **if the exit price is missing the call stays OPEN, never
    `unscoreable`** → `entry_day_after` (strictly after publication) → `exit_day_for` →
    `ledger.verdict_for` with the ±2% floor → `_write()`, which touches **only** the 12 resolution
    columns and carries `WHERE id=%s AND verdict IS NULL`.
20. `job_runs.detail` receives counts **by verdict**, not a bare success.

## 1.7 The complete flow: a stranger views a caller's record

**Path A — from a shared link.**

1. `GET /r/{handle}` (`app.py:3414`), no session.
2. `receipts_record.caller(handle, conn)` (case-insensitive on `handle`). Unknown handle → a
   styled "No record here" page linking to `/board`. **200, not 404.**
3. `receipts_record.summary(caller["id"], conn)`.
4. Server renders HTML with `og:title`, `og:description`, `og:image`,
   `twitter:card=summary_large_image`, every value through `presentation._xml_escape`.
   The description branches on the gate: below 25 resolved it prints counts and
   *"A rate is not shown below 25 resolved calls"*; above it prints
   *"40.8% right on 282 resolved calls, measured against SPY."*
5. The body is the card image, a link to `/record?handle=…`, the summary line, and the disclaimer.

**Path B — inside the app.**

6. `GET /record?handle=convergence-v3` → the SPA catch-all (`_SpaFiles`) serves `index.html`.
7. `App.jsx:173` reads `handle` out of `window.location.search` on first load, so a shared link
   works cold.
8. `RecordView` → `fetchRecord(handle)` → `GET /api/receipts/{handle}` — **public, no session**.
9. The page renders in this order, and the order is the argument (`record.jsx:1–13`):
   who this is and whether verified → **the chain with the Verify button** → counts and intervals →
   **the misses, above every breakdown** → calibration → every call, newest first.
10. `httpsOnly()` re-checks `audience_url` and `verification_evidence_url` client-side before either
    reaches an `href`, because React escapes an attribute value but does not restrict its scheme.

## 1.8 The scoring, exactly

**Trigger.** `scheduler` job `resolve_calls`, every 21,600s (6h). Also `cli resolve-calls` by hand.
The work queue is `calls_due_idx`.

**Where the prices come from.** `ledger.price_series(conn, symbol)` reads `prices_eod`
(2,237,206 rows, 2,018 symbols). Alpaca IEX is the price path; Tiingo is the fallback.

**The SPY benchmark.** `backtest.engine.excess_return(sym, spy, as_of, horizon_days)` returns
`subject_return − benchmark_return` over the identical window. SPY is loaded **once** per batch in
`resolve_due` and passed into every `resolve_call`, so 100 calls cost one benchmark load.
`benchmark_symbol` is a sealed column defaulting to `'SPY'`; nothing in the UI can change it.

**Entry.** `entry_day_after(sym, published_at.date())` — the first session **strictly after**
publication. Never the session in progress: by the time a call is published at 3pm most of that
day's close has already happened.

**Exit.** `exit_day_for(sym, entry, horizon_days)` — the first session on or after `entry +
horizon_days` calendar days. The benchmark gets its own `exit_day_for(spy, entry, horizon_days)`,
so a symbol that does not trade on the exact day does not silently borrow SPY's date.

**The 2% noise floor.** `scoring.NOISE_FLOOR = ledger.NOISE_FLOOR` — bound, not a second constant.
`ledger.verdict_for(direction, excess)`:

- `|excess| < 2%` → **`inconclusive`**, and it stays in the counts rather than leaving the denominator.
  **Corrected 2026-09-15:** this document previously stated the test as `≤`. The code is
  `abs(excess) < NOISE_FLOOR`, strictly — measured, then pinned by
  `test_the_noise_floor_is_strict_so_exactly_two_percent_is_a_hit`. Exactly `+2.000000%`
  resolves **hit**, not inconclusive: a move that reaches the floor has cleared it
- past the floor in the called direction → **`hit`**
- past the floor against it → **`miss`**
- no usable series → **`unscoreable`**

`scoring.verdict_for` wraps it to guarantee a reason sentence on **every** verdict including hits
and misses, because a record page shows one call alone with no number beside it.

**What happens at 7, 30 and 90 days.** Nothing different. The horizon is the only input that
changes; the same entry rule, the same benchmark, the same floor. The three windows exist so
callers are comparable — `SCOREABLE_HORIZONS = (7, 30, 90)`, enforced in `validate()` and in the
migration's CHECK constraint. Free-choice windows would make a board meaningless.

**The honest failure mode.** If `excess_return` returns `None` with reason
`horizon_open_or_delisted`, **the call stays open forever rather than being sealed**. An earlier
version let SPY settle it — SPY reaches the horizon, the symbol has not, therefore the symbol is
dead — and that is wrong, because a symbol lagging SPY is the routine state of this table. A
delisted symbol staying open is visible, honest and correctable; a wrong verdict is none of those.

## 1.9 The hash chain, exactly

**What is hashed.** Ten fields, in an order frozen forever (`chain.SEALED_FIELDS`):

```
caller_id, seq, symbol, direction, horizon_days, confidence,
thesis, benchmark_symbol, published_at, knowable_time
```

Each rendered as `name:byte-length:value`, joined with newlines. **Length-prefixed, not
delimited** — a thesis is free text the caller writes, and with a plain separator they could type
the separator into their own thesis and make two different calls serialise identically: a collision
they control, therefore a forged link. Timestamps render as UTC ISO-8601 to the microsecond with an
explicit `Z`, so a server in Dubai and one in UTC produce identical bytes. `Decimal` is normalised
so `30` and `30.00` cannot be two payloads. A `bool` raises. A `None` raises.

```
content_hash = sha256(prev_hash + canonical_payload)
```

`prev_hash` goes **first and inside** the hashed input. First call chains from
`GENESIS_HASH = "0" * 64`, which makes *"this is the first thing they ever published"* checkable
rather than asserted. Each caller has **their own** chain — 323 links and 150 links, not one of 473.

**How verification works.** `chain.verify_chain(calls)` sorts by `seq` (the ordering is part of
what is checked, so it is not trusted to arrive right) and walks:

1. `call["seq"] != i` → break: *"the sequence has a gap or a duplicate, so a call is missing"*.
   Without this check, deleting a call and renumbering nothing would leave every remaining hash
   self-consistent — and deletion is precisely what this exists to catch.
2. `call["prev_hash"] != prev` → break: *"this call does not chain from the one before it"*.
3. `sha256(prev + payload) != call["content_hash"]` → break: *"the stored hash does not match the
   call's own contents"*.

It returns **`broken_at_seq` for the FIRST failing link only.** Once a link breaks, every later
link was computed over a wrong `prev_hash` and would report broken too, burying the actual edit
under its own consequences.

`calls.for_chain()` is a separate query from `calls.listing()` on purpose: verification reads the
sealed fields and nothing else, so a bug in the display layer cannot make a broken chain look intact.

**What a user actually sees when they press Verify.** `receiptsui.jsx:145 ChainStrip`:

1. Resting state: the link count, the label *"sealed calls, each carrying the hash of the one
   before it"*, the short head hash, and a **Verify chain** button.
2. On click: `GET /api/receipts/{handle}/verify`.
3. The links are then **walked visibly** — `checking link N of 323` with a progress bar, 28 ticks
   at 26ms each, roughly 0.7 seconds. Deliberate: *"an instant green tick reads like a decoration
   rather than like work."*
4. Intact → **"Intact. All 323 links recompute."** plus *"every link recomputes from the published
   fields"*, in the one strongest accent in the palette, spent here and nowhere else.
5. Broken → **"Broken at call N."** plus the specific reason.
6. Network failure → **"The check could not be run. That is a problem reaching us, not a finding
   about the record."** with a retry. A 429 on a page that has just been shared widely is a real
   possibility, and this used to hang on "checking link 0" forever.
7. Underneath, always: the `does_not_prove` caveat, verbatim from `record.methodology()`.

**Verified live this morning:**

```
convergence-v3  intact: true  links: 323  head c9f480e0a79a28c73f149eec3c083a0d436169812471c7b5c4d94f613b6ef5f1
```

**What it does not prove, and the product says so in these words:** *"The chain does not prove that
WE have not rewritten it. We hold every field, so this operator could edit a call and recompute the
whole chain after it. Making that impossible needs an anchor outside our control, publishing the
chain head daily somewhere we cannot revise, and that is not built yet. This is not a blockchain and
we do not call it one."*

---

# SECTION 2: WHAT A CALLER CAN AND CANNOT DO TODAY

| Capability | Status |
|---|---|
| Sign up as a caller without an administrator | ❌ **DOES NOT EXIST** |
| Make a call through a UI rather than CLI or SQL | ✅ **WORKS** |
| Make a call from a phone | ⚠️ **PARTIALLY WORKS** |
| See their own record | ✅ **WORKS** |
| Share a public link to their record | ⚠️ **PARTIALLY WORKS — the preview is broken** |
| Get notified when a call resolves | ❌ **DOES NOT EXIST** |
| Correct a genuine mistake | ❌ **DOES NOT EXIST, and by design cannot** |

### Sign up as a caller without an administrator — ❌ DOES NOT EXIST

`authn.register` (`tradeos/authn.py:160–169`) requires an invite code that matches either an unused
row in `invites` or another user's `referral_code`. Neither matches → `AuthError("invalid or
already-used invite code")`. The auth form (`views.jsx:367`) renders the field as required in
register mode. There are 18 unused invites and 6 users, 4 of them test accounts.

Compounding it: **SMTP is not configured.** `cli preflight` this morning:

> `⚠ SMTP_HOST/MAIL_FROM are empty — email verification and password reset cannot send, so a
> forgotten password is unrecoverable.`

So even if the invite wall came down, a caller who forgets their password is locked out of their
own record permanently. (The *record* survives — `callers.user_id` is nullable with
`ON DELETE SET NULL`, which was the right call — but they can never publish to it again.)

### Make a call through a user interface — ✅ WORKS

End to end, and it is the best-built part of the product. `publish.jsx` handles signed-out (an
EmptyState with a Sign in button, not a crash), no-caller (the claim form), live scoreability as
the symbol is typed, all validation problems at once rather than one per submit, a `finally` on the
busy flag so a rejected fetch cannot leave the button reading "claiming…" forever, and a consent
panel in plain language before the irreversible click. The receipt with its hashes comes back and is
shown.

### Make a call from a phone — ⚠️ PARTIALLY WORKS

Mobile CSS genuinely exists. `frontend/src/styles.css` carries a marked
`NARROW SCREENS — must stay LAST` block of 145 lines, and Receipts is properly represented in it:

```css
.bd-row { grid-template-columns: 34px minmax(0, 1fr); grid-template-areas: … }
.rc-counts { grid-template-columns: repeat(3, minmax(0, 1fr)); }   /* then 2 at the narrowest */
.rc-page, .bd-page, .pb-page, .cd-page, .mt-page { padding: var(--s4) 0 var(--s7); }
.rc-call-row { grid-template-columns: 58px 46px minmax(0, 1fr) 74px; }
.pb-receipt-grid b, .cd-field b, .rc-chain-head, .mt-fields { overflow-wrap: anywhere; }
```

`minmax(0, 1fr)` is used throughout and hashes get `overflow-wrap: anywhere` — both of the
overflow traps this codebase has learned about are handled.

**What makes it "partially":** the phone experience is the *whole app shell* — a sidebar carrying
three nav groups plus a "More" menu of seven more surfaces, a top bar with a search field, an
"Ask AI" button and an "Upgrade" button. For a caller whose entire job is *publish a call, look at
my record*, that is a research terminal with a publish form inside it. Nothing is broken; the
information architecture is simply not the target user's. **I have not verified this on a real
375px viewport in a browser** — the CSS reads correctly and the rules are in the right place, but
`CLAUDE.md` §12 exists precisely because reading is not checking.

### See their own record — ✅ WORKS

`record.jsx MyRecord` → `GET /api/callers/me` → renders `RecordView` for their handle. The rail
item "My record" navigates to `/record` with no handle and resolves to their own; the highlight
logic deliberately does not light up when they are reading somebody else's record.

### Share a public link to their record — ⚠️ PARTIALLY WORKS

The link works. **The preview does not.** Two independent defects, both in
`tradeos/app.py:3445–3450`:

```python
card = e(f"/api/card/receipt/{caller['handle']}.svg")
...
<meta property="og:image" content="{card}">
```

1. **It is a relative URL.** The Open Graph protocol requires an absolute URL for `og:image`.
   Facebook, X, LinkedIn, Slack and Discord will not resolve `/api/card/...` against the page.
   There is no base-URL config anywhere in the repo to build one from — I grepped `config.py`,
   `app.py` and `docker-compose.yml` for `BASE_URL` / `SITE_URL` / `PUBLIC_URL` and found nothing
   but `OPENAI_BASE_URL` and a per-request `request.base_url` used only by Stripe checkout.
2. **It is an SVG.** No major social platform renders SVG as a link-preview image. X's card spec
   accepts JPG, PNG, WEBP and GIF. Facebook's OG image scraper does not accept SVG either.

So the single mechanism by which "checkers arrive for free when callers share their page" is
supposed to work — a caller posts their link and a card appears in the feed — produces a bare text
link today. `/s/{symbol}` (`app.py:3057`) has the identical bug, so this is one pattern copied, not
a one-off slip.

Also currently true on this instance: `tradeos/site_static/index.html` **does not exist in the
running container**, so the `/` → `/site/` 307 redirect handler is never registered and the
`/site` mount never happens. Measured: `GET /` returns **200 serving the app bundle**, and
`GET /site/` also returns **200 serving the app bundle** via the SPA catch-all. Logging out runs
`window.location.assign("/site/")` (`App.jsx:264`) and lands the user back in the app.

### Get notified when a call resolves — ❌ DOES NOT EXIST

`grep -rn 'notif' tradeos/receipts/ tradeos/scheduler.py` returns **nothing**. The `notifications`
table exists with 16 rows and `alerts.py:164` knows how to write one, but no Receipts code path
touches it. A caller publishes a 90-day call and the only way to learn the outcome is to open the
page and look.

### Correct a genuine mistake — ❌ DOES NOT EXIST, and cannot

There is no retract, amend, annotate or withdraw anywhere: not a route, not a column, not a button.
`grep -rn 'retract\|correction\|amend\|withdraw'` across `tradeos/receipts/`, `publish.jsx`,
`record.jsx` and both migrations returns only two **comments** explaining why a correction to the
*scorer* must be disclosed rather than applied.

**What happens if they try**, measured this morning: the database refuses, with the messages in
§1.5. A caller who types `AAPL` when they meant `AAPD` has published a permanent, public, sealed,
chained call on a company they never meant to name, and it will be scored and will sit on their
record forever.

That the seal is right does not make the absence of *any* correction affordance right. The seal
says "you cannot rewrite history." It does not have to say "you cannot say, in public and
permanently, that call 14 was a typo." An **append-only annotation** — a new row in a new table
that never touches `calls` and never enters the hash — would preserve every integrity property and
close this. It is not built and, as far as I can find, has not been considered.

---

# SECTION 3: WHAT A VISITOR SEES

### Is there a public page per caller, and at what URL — ✅ TWO of them

| URL | What it is |
|---|---|
| `/r/{handle}` | Server-rendered share page. No JS, no bundle, OG tags |
| `/record?handle={handle}` | The full React record page with Verify chain |

Both public. `/board` lists every caller. The API underneath is
`GET /api/receipts/{handle}`, also public.

### Does it work signed out — ✅ YES, measured

```
200  /r/convergence-v3
200  /api/receipts/convergence-v3
200  /api/receipts/convergence-v3/verify
200  /api/board
200  /api/card/receipt/convergence-v3.svg
200  /api/receipts/methodology
200  /record?handle=convergence-v3
200  /board
401  /api/callers/me
401  /api/calls/scoreability?symbol=AAPL
```

Exactly the right split: reading a record needs no account, publishing does.

**But the signed-out React experience is wrong.** `App.jsx` has no auth gate around the shell. A
stranger at `/board` gets the full sidebar — Receipts, Research (Home, Ledger, Events, Crypto, News,
Journal, Watchlist), System (Integrations, Assistant, Search) and a "More" menu of seven more —
plus a search field, an "Ask AI" button and an "Upgrade" button. The board renders correctly; every
other rail item leads to a surface whose API returns 401. The one thing this product sells is that
a reader can check a caller without taking anything on trust, and the first thing it shows them is
a terminal they cannot use.

### Does it have OG tags and a share image — ⚠️ TAGS YES, IMAGE BROKEN

Live output of `GET /r/convergence-v3`:

```html
<title>Convergence v3 · the record · Rhumb</title>
<meta property="og:title" content="Convergence v3 · the record · Rhumb">
<meta property="og:description" content="40.8% right on 282 resolved calls, measured against SPY.">
<meta property="og:image" content="/api/card/receipt/convergence-v3.svg">
<meta name="twitter:card" content="summary_large_image">
```

The tags are present, correctly escaped, and the description is honest and gate-aware. The image is
a **relative URL to an SVG**, and neither of those works in a social preview — see §2. The card
itself is real and good: 1200×630, 3,819 bytes, brand mark, a `✓ verified` badge, and it is
forbidden by its own contract from printing a rate on a gated record.

Missing beyond that: no `og:url`, no `og:type`, no `og:site_name`, no `twitter:site`, no
`<link rel="canonical">`. None of those are fatal; the image is.

### Is there any way to browse or compare callers — ⚠️ ONE FIXED VIEW

`/board` (`board.jsx`) is it. It renders every caller in one table — rank, name, counts, hit rate
with its Wilson interval, average excess with "interval spans zero" when it does. Gated callers are
listed **below** the ranked ones under "Below the sample gate", with a neutral `Low N` chip and
**no rank**, because a rank implies a comparison the sample cannot support.

Live board:

```
convergence-v4  rank 1  48.46%  n=130  expectancy -0.441%  CI [-2.979%, +2.098%]
convergence-v3  rank 2  40.78%  n=282  expectancy -1.521%  CI [-3.803%, +0.761%]
HOUSE (pooled)          43.20%  n=412  expectancy -1.180%  CI [-2.934%, +0.574%]  z = -2.76
```

There is **no** filtering, sorting, search, horizon split, symbol split, time-period split, or
head-to-head comparison. With 2 callers that is correct. With 50 it is unusable, and with 2 real
human callers it is already thin.

### Verify the chain from the browser — ✅ WORKS, and it is the best thing here

Described in full in §1.9. The short version of what the user sees: a **Verify chain** button → a
visible walk through all 323 links at roughly 0.7 seconds → **"Intact. All 323 links recompute."**
→ and directly beneath it, unprompted, the paragraph explaining that this does *not* prove the
operator has not rewritten it. A product that shows you its own strongest caveat at the exact
moment you are most impressed is doing something rare, and it should not be diluted.

---

# SECTION 4: THE GAPS

Ordered by how much each blocks the path: **a caller signs up → makes a call from their phone →
shares a page they are proud of.**

---

### GAP 1 — There is no open signup. 🔴 TOTAL BLOCKER
**Blocks: everything.**

`authn.register` requires an invite or referral code. No caller can reach step one without you.

**Files:** `tradeos/authn.py:147–187` · `tradeos/app.py:443–457` · `frontend/src/views.jsx:342–372` ·
`tradeos/flags.py` (the `registration` flag already exists as the kill switch) · `tests/test_authn.py`

**The work is not the `if`.** Removing the invite check is twenty minutes. Opening registration on
a product whose core table is append-only and public means: mandatory email verification before
publishing (otherwise `throwaway@…` seals permanent rows on a public board), a signup rate limit
(there is no `_AUTH_TOKEN_PATHS` bucket covering `/api/auth/register`), and a decision on whether
an unverified caller appears on `/board` at all.

**Estimate: 1.5 days**, and it depends on GAP 2.

---

### GAP 2 — Email cannot be sent. 🔴 TOTAL BLOCKER
**Blocks: signup recovery, verification, and every notification.**

`cli preflight`: *"SMTP_HOST/MAIL_FROM are empty."* `mail.py` refuses to send unconfigured and never
half-sends, which is the right behaviour — but the consequence is that a caller who forgets their
password can never publish to their own record again.

**Files:** `.env` · `docker-compose.yml` (both `api` and `worker` — `CLAUDE.md` §0i: the base
compose file enumerates every variable explicitly, so a key in `.env` alone does not reach the
container) · no code change in `tradeos/mail.py`

**Estimate: 2–3 hours**, config and a live send test. A free tier (Resend, Postmark, SES) covers it.

---

### GAP 3 — The share card cannot render in a social feed. 🔴 CRITICAL
**Blocks: the entire distribution loop, which is the strategy.**

Relative URL **and** SVG. Either alone breaks the preview; both are present. A caller posts their
link and their audience sees a bare URL. "Checkers arrive for free when callers share their page"
is currently false.

**Files:**
- `tradeos/config.py` — add `public_base_url()` (raise or fall back explicitly; never silently emit
  a relative URL)
- `docker-compose.yml` — the new variable, in **both** services
- `tradeos/presentation.py:233` — `receipt_card_svg` stays; add a PNG renderer beside it
- `tradeos/app.py:3394` — add `GET /api/card/receipt/{handle}.png`
- `tradeos/app.py:3445–3450` — absolute `og:image` pointing at the `.png`; add `og:url`, `og:type`,
  `og:site_name`
- `tradeos/app.py:3052–3070` — `/s/{symbol}` has the identical bug; fix it in the same change
- `Dockerfile` — **a font.** Measured: the container has **zero** TrueType fonts
  (`glob('/usr/share/fonts/**/*.ttf')` → `[]`), so `PIL.ImageFont.truetype` fails. Either
  `apt-get install fonts-dejavu-core` or vendor one `.ttf`. Pillow 12.3.0 is already in
  `requirements.txt` — **no new dependency is needed**, which matters given the 10-line rule.
- `tests/test_receipts_api.py` — assert the og:image is absolute and is not `.svg`

**Estimate: 1.5 days.** Most of it is drawing the card in Pillow primitives rather than SVG text,
and confirming it against a real card validator.

---

### GAP 4 — `/` and `/site/` both serve the app bundle. 🟠 HIGH
**Blocks: a stranger's first second.**

`tradeos/site_static/index.html` is absent from the running image, so the redirect handler at
`app.py:3491` is never registered and the `/site` mount never happens. Measured: `GET /` → 200 app
bundle; `GET /site/` → 200 app bundle. Sign-out lands back in the app.

**This gap resolves itself if the marketing site is deleted (§5) — but only if `/` is repointed to
`/board` in the same change.** Otherwise deleting `site/` leaves a signed-out stranger on a
research terminal.

**Files:** `Dockerfile` (if keeping) · `tradeos/app.py:3488–3497` (repoint `/` if deleting) ·
`frontend/src/App.jsx:264,278` (two `window.location.assign("/site/")` calls)

**Estimate: 3 hours** either way.

---

### GAP 5 — Signed-out visitors get the whole app shell. 🟠 HIGH
**Blocks: the shared page being one a caller is proud of.**

No auth gate around the sidebar. A stranger following a caller's link sees eleven nav items that
401.

**Files:** `frontend/src/App.jsx:275–305` (gate `SIDEBAR` / `MORE` / the top bar on `user`) ·
`frontend/src/styles.css` (a signed-out chrome) · `tests/test_navigation.py`

**Estimate: 4–6 hours.**

---

### GAP 6 — Verification cannot be completed. 🟠 HIGH
**Blocks: the `✓ verified` badge, which is what separates a claimed handle from a proved one.**

`GET /api/admin/callers/pending` and `POST /api/admin/callers/{id}/verify` exist, are tested, and
**nothing in the frontend calls either.** `frontend/src/admin.jsx` has no reference and
`frontend/src/api.js` has no wrapper. A caller starts verification, publishes the code, pastes the
URL, and it sits in `caller_verifications` until someone hand-runs an HTTP request. `pending` is
currently 0 rows because nobody has ever tried.

**Files:** `frontend/src/api.js` (two wrappers) · `frontend/src/admin.jsx` (a queue panel: handle,
code, method, evidence link, approve/reject) · `tests/test_receipts_api.py`

**Estimate: 4 hours.** Small, and it is the cheapest credibility win on this list.

---

### GAP 7 — No notification when a call resolves. 🟡 MEDIUM
**Blocks: the caller ever coming back.**

Zero code. The plumbing exists: `notifications` (16 rows), `alerts.py:164`, `alert_prefs`,
`email_outbox`.

**Files:** `tradeos/receipts/scoring.py` (`_write` is the single write path — the one place to hook)
· `tradeos/alerts.py` · `tradeos/scheduler.py:133 _job_resolve_calls` · `tradeos/mail.py` ·
`tests/test_receipts.py`

Careful: `_write` runs inside the resolve loop and must not let a mail failure abort a batch, and a
resolution must never be notified twice. Depends on GAP 2.

**Estimate: 1 day.**

---

### GAP 8 — No way to disclose a genuine mistake. 🟡 MEDIUM
**Blocks: a caller trusting the product enough to publish freely.**

A typo'd ticker is permanent, public and will be scored. The correct fix is **not** to weaken the
seal — it is an append-only annotation that never touches `calls` and never enters the hash, so
every integrity property survives and `verify_chain` is unaffected.

**Files:** `tradeos/migrations/036_call_annotations.sql` (new table, its own append-only trigger) ·
`tradeos/receipts/calls.py` (`annotate`, `annotations_for`) · `tradeos/app.py`
(`POST /api/calls/{id}/annotate`, own-caller only; include annotations in
`GET /api/calls/{call_id}`) · `frontend/src/calldetail.jsx`, `record.jsx` ·
`tradeos/receipts/record.py` (methodology text) · `tests/test_receipts.py`

The design question I cannot settle from the code: **does an annotation change the verdict?** It
must not. But then a caller can attach "typo" to any miss, and a record full of excused misses is
worth less than one without the feature. That is a product call, not an implementation detail.

**Estimate: 1.5 days**, plus the decision.

---

### GAP 9 — The board cannot be browsed. 🟡 MEDIUM
**Blocks: nothing today; blocks everything at 50 callers.**

One fixed ordering, no filter, no search, no head-to-head, no horizon or period split.

**Files:** `tradeos/receipts/record.py:board()` · `tradeos/app.py:3379` · `frontend/src/board.jsx`

The statistics are the hard part, not the UI: any filter creates a sub-sample, and every sub-sample
has to re-apply `SAMPLE_GATE` and the Wilson interval or the board starts publishing rates on
slices of eleven calls. `_compute` is already separated from the fetch for exactly this, so the
right shape is there.

**Estimate: 2 days.**

---

### GAP 10 — The publish path has never run in production. 🟡 MEDIUM
**Blocks: confidence, not the caller.**

All five `resolve_calls` job runs in `job_runs` report `{"due": 0, … "note": "no call had reached
its horizon."}`. Zero open calls. All 473 arrived pre-resolved from `seed-house-records`. **The
scorer has never scored a call that this product published.**

It is not untested — `tests/test_receipts.py` exercises publish→resolve end to end against a live
database, including the entry-session rule, the noise floor, and the stale-feed case. But a test
fixture is not a 90-day horizon crossing a real weekend with a real symbol.

**Files:** none. This is an operational task: publish a handful of real 7-day calls, wait a week,
watch `resolve_calls` pick them up.

**Estimate: 1 hour of work, 7 days of waiting.** Start it first, because the waiting is on the
critical path and nothing else is blocked by it.

---

### GAP 11 — Handle claiming is buried. 🟢 LOW

There is no `/claim` route. The only path is `/publish` → discover you have no caller → a form
appears. A caller arriving to set up a record must first go to the page for publishing one.

**Files:** `frontend/src/App.jsx` (`NAV_LABELS`, `ROUTES`) · `frontend/src/publish.jsx`
(extract `ClaimHandle`) · `tests/test_navigation.py`. **Estimate: 3 hours.**

---

### GAP 12 — One copy of the chain. 🔴 CRITICAL, and not on the caller's path

`calls` has no replica, no streaming copy, no external anchor. The single authoritative copy of 473
sealed rows is a Docker volume on one laptop. The trigger protects it from being *edited*. Nothing
protects it from the disk dying, and a restored-from-backup chain is not "as good as" the original —
a gap in it is the failure of the only thing the product sells.

`docs/runbooks/backups.md` exists. Automation does not.

**Files:** `docs/runbooks/backups.md` · `docker-compose.yml` or a cron job ·
`tradeos/cli.py` (a `verify-chain` gate in the backup path)

**Estimate: 4 hours** for automated `pg_dump` + off-machine copy + a restore drill.

---

## Summary

| Blocking the caller path | Days |
|---|---:|
| GAP 1 open signup | 1.5 |
| GAP 2 SMTP | 0.4 |
| GAP 3 share card | 1.5 |
| GAP 4 root route | 0.4 |
| GAP 5 signed-out chrome | 0.7 |
| GAP 6 verification UI | 0.5 |
| **Minimum to "sign up, publish from a phone, share a page you are proud of"** | **~5 days** |
| GAP 7 notifications | 1.0 |
| GAP 8 annotations | 1.5 |
| GAP 9 browse | 2.0 |
| GAP 11 claim route | 0.4 |
| GAP 12 backups (parallel, not on the path) | 0.5 |
| **Total** | **~10.5 days** |

---

# SECTION 5: THE COLLISION

## 5.1 The `llm` chain — confirmed, still true, verified empirically

```
tradeos/receipts/context.py : 21   from .. import journal_context          (module level)
tradeos/journal_context.py  : 43   from . import relevance, trades         (module level)
tradeos/trades.py           : 26   from . import config, llm
                              27   from .explain.guards import allowed_numbers, directive_guard, numbers_guard
                             237   from .explain import gemini             (function level)
```

Proved, not inferred — with `tradeos.llm` removed from `sys.modules`:

```
BREAKS: ModuleNotFoundError import of tradeos.llm halted; None in sys.modules
```

`receipts.calls` imports `context`, so deleting `llm.py` takes **publishing** with it.

Full transitive closure from the eight Receipts modules, by AST walk of the running package:

```
backtest, backtest.engine, config, explain, explain.guards,
geography, journal_context, ledger, llm, relevance, trades
```

**The functional claim still holds.** Receipts calls exactly two functions from `journal_context` —
`ranked_for()` and `summarize()` — and neither reaches `trades`. The only use of `trades` in that
module is `trades.realized_pnl_pct` at **line 337**, inside `across_trades()`, and `across_trades`
has exactly one caller in the entire repository: `tradeos/insights.py:316`. Receipts never touches it.

So both statements are true and not in tension: **at runtime**, revoke every model key and Receipts
is unaffected. **At import time**, delete `llm.py` and publishing stops.

## 5.2 The smallest change that severs it

**One line.** `tradeos/journal_context.py:43`:

```python
from . import relevance, trades
```

becomes

```python
from . import relevance
```

and `from . import trades` moves inside `across_trades()` at line 320, the only function that uses
it. `CLAUDE.md`'s "never call an external API from a route handler" rule is unaffected; this is a
lazy import of a sibling, which the codebase already does in `ledger.py:215`.

After that change the closure is:

```
backtest, backtest.engine, config, geography, journal_context, ledger, relevance
```

`llm`, `explain`, `explain.guards` and `trades` are gone from it. `geography` imports nothing
internal (stdlib only). `backtest.engine` imports nothing internal. `ledger` imports only
`backtest.engine`.

**Confirm with:** `python -c "import tradeos.receipts.calls"` after the edit, and `make test`.

## 5.3 ⚠️ CORRECTION to `docs/receipts_protected.md`

That document's §2 collision table says:

> | **`tradeos/signals/`** | 🟢 NOT A DEPENDENCY | Nothing. Not in the graph, not referenced.
> Safe to delete as far as Receipts is concerned. |

**That is wrong, and I verified it.** `tradeos/presentation.py:18`:

```python
from .signals.convergence import DEFAULT_PARAMS
_BUCKETS = DEFAULT_PARAMS["buckets"]
```

`presentation` backs `GET /api/card/receipt/{handle}.svg` (`app.py:3405`). Empirically, with
`tradeos.signals.convergence` removed from `sys.modules`:

```
BREAKS: ModuleNotFoundError import of tradeos.signals.convergence halted; None in sys.modules
```

**Deleting `signals/` breaks the Receipts share card.** The earlier document missed it for the same
structural reason it correctly flagged `presentation` itself: `tradeos/receipts/` never imports
`presentation`, so a package-level import graph rooted at `receipts` shows nothing. The dependency
runs through the **route**, and then one hop further than the previous analysis followed.

**The fix is trivial and it is the same fix the deletion already needs.** `_BUCKETS` is used only by
`smart_money_score` at `presentation.py:34–35`; `receipt_card_svg` (line 233) never touches it. Move
`receipt_card_svg` and `_xml_escape` into a new `tradeos/receipts/card.py` and the dependency on
both `presentation` and `signals` disappears in one move.

## 5.4 The full collision list, corrected

| Module | Status | What breaks | Sever it by |
|---|---|---|---|
| `tradeos/ledger.py` | 🔴 **REAL** | `record`, `scoring`, `seed` fail to import. No scoring, no statistic | **Move** `price_series`, `verdict_for`, `NOISE_FLOOR`, `mean_ci`, `proportion_z`, `sample_needed`, `CONFIDENCE_BUCKETS`. Never reimplement — a second Wilson interval is how this product loses its only asset |
| `tradeos/backtest/engine.py` | 🔴 **REAL** | `record`, `scoring` fail to import | **Move** `Series`, `entry_day_after`, `exit_day_for`, `excess_return`, `wilson_interval`. 128 lines, zero internal imports — the cleanest move on the list |
| `tradeos/presentation.py` | 🔴 **ROUTE** | `/api/card/receipt/{handle}.svg` 500s | Move `receipt_card_svg` + `_xml_escape` to `tradeos/receipts/card.py` |
| `tradeos/signals/` | 🔴 **ROUTE, one hop further** | Same route. **Correction to `receipts_protected.md`** | Solved by the `presentation` move above |
| `tradeos/llm.py`, `tradeos/explain/` | 🟠 **IMPORT-TIME ONLY** | `receipts/context.py` fails to import, taking `calls.py` and publishing with it | The one-line lazy import in `journal_context.py:43` |
| `tradeos/trades.py` | 🟠 **IMPORT-TIME ONLY** | Same | Same one line |
| `tradeos/journal_context.py`, `relevance.py`, `geography.py` | 🟢 **KEEP or retire deliberately** | See §5.5 | — |
| `tradeos/claims.py`, `spine.py`, `intelligence/` | 🟢 **NOT A DEPENDENCY** | Nothing. Not in the graph at any depth | — |

## 5.5 The honesty problem the deletion introduces

`receipts/context.py` freezes *"what the system itself was showing about this symbol at that
moment"*. Measured live this morning:

```python
context.capture(conn, None, "AAPL", "up", now())
→ {'basis': 'live', 'claim_ids': [411, 394, 384, 368, 358, 5, 424, 408], 'n_live': 9, …}
```

Nine claims — from a `claims` table whose newest row is **2026-08-24**, three weeks stale.

Delete the claim engine and `ranked_for` returns `[]`, so `summarize` produces `n_live: 0` with
`basis: "live"`. That asserts **"we looked and there was nothing live"** when the truth is
**"there is no engine any more."** `context.empty(as_of, why)` exists for exactly this distinction
and its own docstring makes the argument — but it is only reached from the `except` branch in
`calls.publish`, never from a deliberate "the engine is gone" branch.

This is a small change that must land **with** the deletion, not after it. Two honest options:

- **Retire the snapshot.** Stop capturing; store `context.empty(now, "the interpretation engine
  this recorded was retired on <date>")`. `context_snapshot` is sealed, so old snapshots keep
  meaning what they meant.
- **Keep `journal_context` + `relevance` + `geography`** (887 lines, no model, no external call)
  and keep capturing. Defensible only if something still writes `claims`.

Given the decision that the convergence signal is dead, **the first option is the honest one.**

## 5.6 Can the deletion proceed, and in what order

**Yes.** Every collision has a named, small fix and none requires redesigning Receipts.

Do these **before deleting anything**, each verifiable on its own:

1. **Back up `calls`.** 473 rows, one copy, `docs/runbooks/backups.md`. Then
   `cli verify-chain convergence-v3` (323) and `convergence-v4` (150) to prove the backup is of an
   intact chain.
2. **Sever the `llm` chain.** `journal_context.py:43`. Verify: `python -c "import
   tradeos.receipts.calls"`, then `make test`.
3. **Create `tradeos/receipts/card.py`.** Move `receipt_card_svg` + `_xml_escape`. Repoint
   `app.py:3405`. Verify: `curl -s localhost:8000/api/card/receipt/convergence-v3.svg | head -c 80`.
   This severs `presentation` **and** `signals` in one step.
4. **Create `tradeos/receipts/prices.py` and `tradeos/receipts/stats.py`.** Move the seven functions
   from `ledger` and the five from `backtest/engine`. **Move, do not reimplement.** Verify:
   `make test`, and re-read `record.py`'s docstring before touching a single interval.
5. **Decide the context question (§5.5) and implement it.**
6. **Confirm the closure is clean.** Re-run the AST walk; it should show only
   `config` + `receipts.*`.

Then delete, in this order — each step leaves a running app:

7. `tradeos/intelligence/` (`analyst.py`, `vision.py`) — not in the graph at any depth.
8. `tradeos/claims.py`, `tradeos/spine.py` — not in the graph. Note `seed.py` reads
   `claims`/`claim_outcomes` **tables**; it is idempotent-by-refusal and will never run again, but
   keep the tables until you are certain you will never rebuild a house record.
9. `tradeos/llm.py`, `tradeos/explain/` — safe after step 2.
10. `tradeos/trades.py`, `tradeos/journal_context.py`, `tradeos/relevance.py`,
    `tradeos/geography.py` — safe after steps 2 and 5. Check `insights.py:316` first.
11. `tradeos/signals/`, `tradeos/presentation.py` — safe after step 3.
12. `news.py`, `crypto.py`, `crypto_intel.py`, `community.py`, `sentiment.py` and their ingestion
    modules — not in the graph. Each also needs its routes, its `.jsx`, its `ROUTES` entry, its
    `sources.CATALOG` entry and its `scheduler.JOBS` entry removed in the same commit.
13. `site/` — **and repoint `/` to `/board` in the same commit** (GAP 4), or a signed-out stranger
    lands in a research terminal.

**After every step:** `make test` (83 Receipts tests must pass), then
`cli verify-chain convergence-v3` → 323 links, `convergence-v4` → 150 links, then
`curl -s localhost:8000/api/board`. If the link counts ever change, stop.

One structural warning: `tradeos/app.py` is 3,525 lines and 140 routes, and the deletion touches
most of it. `CLAUDE.md` says to split it by surface when a phase touches it. **This is that phase** —
`tradeos/routes/receipts.py` should be the file that survives.

---

# SECTION 6: MY HONEST READ

## How far is Receipts from something a real caller could use unassisted

**About five working days, and the five days are not the interesting part.**

The engineering that is hard is done and done well. The seal is real — I broke it five ways this
morning and Postgres refused every one. The chain verifies 323 links live. The statistics refuse to
publish a rate on a thin sample, publish the interval beside every number they do publish, lead
with the misses, and say in plain words what the chain does *not* prove. The publish form handles
signed-out, no-caller, live scoreability, all-errors-at-once and an irreversible click with a
consent panel written for a human. The mobile CSS is in the right block with `minmax(0, 1fr)` and
`overflow-wrap: anywhere`. 874 tests pass in 3.75 seconds and ruff is clean.

What is missing is almost entirely **the ordinary product plumbing around a well-built core**: a
signup that does not need you, an email server, an image format a social network will render, and a
signed-out page that does not look like someone else's terminal. None of it is hard. All of it is
between the caller and the door.

## The single biggest thing standing in the way

**A caller cannot get an account, and if they could, sharing their record would produce a bare link.**

I am naming two things because they are one failure: **the product has never had a user who was not
us, so nothing on the path from stranger to shared page has ever been walked.** Every defect in
§4's top three is of the same kind — invisible unless someone outside the building tries it.

Registration has required an invite since long before Receipts existed; it was correct for a private
research tool and was never revisited when the product became a public scoreboard. `og:image` points
at a relative SVG because `/s/{symbol}` did, and nobody pasted a link into Slack. `site_static` is
missing from the image because nobody signed out and looked. The admin verification queue has no UI
because nobody ever submitted evidence.

If I could fix one thing it would not be a file. It would be: **publish five real calls from a phone,
as a caller, through the front door, and share one in a group chat.** Every gap in §4 above GAP 7
would surface in twenty minutes.

## Is anything half-built the summary did not mention

Five things. In order of how much they matter.

**1. The admin verification queue has no interface.** Two routes, tested, and **nothing calls
either one** — no wrapper in `api.js`, no panel in `admin.jsx`. A caller can start verification and
submit evidence, and it lands in a table nobody can see from the product. `caller_verifications` has
0 rows so this has never been noticed. Both prior documents list these routes without saying they
are unreachable. This is the clearest half-built thing in the feature.

**2. The scorer has never scored a call this product published.** All five `resolve_calls` runs in
`job_runs` report `due: 0`. Zero open calls. All 473 were imported pre-resolved. It is thoroughly
tested against a live database — but the difference between a fixture and a real 90-day horizon
crossing a weekend with a real ticker is exactly the difference `CLAUDE.md` §12 exists to warn about.

**3. The context snapshot silently degrades.** `capture()` returns `n_live: 9` from claims three
weeks stale, labelled `basis: "live"`. `context.empty()` exists to say *"we looked and the engine
was silent"* and is only reachable from an exception handler. In a product whose entire pitch is
that its numbers mean exactly what they say, a snapshot asserting "live" over three-week-old rows is
the wrong kind of quiet. The deletion makes it worse, not better (§5.5).

**4. There is no correction affordance of any kind.** Not a weakened seal — the seal is right. But
there is no append-only annotation either, and a caller who fat-fingers a ticker has published a
permanent public call on a company they never meant to name. I could not find evidence this has
been considered; both prior documents discuss why the *scorer* cannot be corrected and neither
discusses the *caller's* typo.

**5. `wallet_signature` is in the migration's CHECK constraint and deliberately unimplemented.**
Documented as intentional in `verification.py`'s docstring — a column that will not need altering
later, not a hint that it is coming. I mention it only so nobody reads it as a to-do.

One more thing, smaller but worth a line: **`CLAUDE.md` says 834 tests and Pillow 10.4.0.** Measured:
**874 tests** and **Pillow 12.3.0**. Both drifted since the v5 work landed. The repo's own rule is to
fix a wrong command in the file that documents it, in the change that discovers it.

## If I had two weeks

I would not build any new capability. Every day goes into the path between a stranger and a shared
page, in the order that unblocks the next day.

**Day 1 — start the clock on the thing that cannot be rushed.**
Publish five real 7-day calls through the actual UI as a real caller. Configure SMTP (GAP 2, ~3h).
Automate the `calls` backup and do one restore drill (GAP 12, ~4h) — 473 sealed rows on one Docker
volume is not a risk to carry into a launch week.

**Days 2–3 — the front door.**
Open registration (GAP 1): drop the invite requirement behind the existing `registration` flag,
require email verification before the *first publish* rather than before login, add a signup rate
bucket. This is where to be careful: an append-only public table plus open signup is a spam surface
with no undo.

**Days 4–5 — the share loop.**
`public_base_url()`, a PNG card renderer in Pillow, a font in the image, `og:image` absolute and
`.png`, plus `og:url` / `og:type` / `og:site_name`. Fix `/s/{symbol}` in the same change. Validate
against a real card validator, not a unit test.

**Day 6 — the signed-out page.**
Gate the shell on `user` (GAP 5). Repoint `/` to `/board` (GAP 4). A stranger following a caller's
link should see the record and one honest invitation, not eleven doors that 401.

**Day 7 — verification, and the first check-in.**
Wire the admin queue into `admin.jsx` (GAP 6, ~4h). Then check the five calls from Day 1: the 7-day
horizons are closing and `resolve_calls` should be picking them up. **Watch the job run.** If
anything is wrong with the scorer in production, this is the day it shows, and there is a week left
to fix it.

**Day 8 — the collision prep, before it is urgent.**
The one-line lazy import in `journal_context.py:43`. `tradeos/receipts/card.py`.
`tradeos/receipts/prices.py` and `stats.py`. Six verifiable steps (§5.6 1–6), each leaving a running
app. Nothing is deleted yet. This is the day that makes the deletion boring instead of frightening.

**Days 9–10 — notifications.**
Resolution email + in-app notification (GAP 7). A caller publishes a 90-day call and hears nothing
for three months is a product with no second session. Hook `scoring._write`, which is the single
write path.

**Day 11 — annotations.**
Migration 036, append-only, never touching `calls`, never entering the hash (GAP 8). **Decide first
whether an annotation may change a verdict. It must not.**

**Day 12 — the deletion.**
Steps 7–13 of §5.6. `make test` + both `verify-chain` runs after every step. Split
`tradeos/routes/receipts.py` out of `app.py` while it is open.

**Day 13 — the board.**
Filtering and sorting (GAP 9), with `SAMPLE_GATE` and the Wilson interval re-applied to **every**
sub-sample. The moment a filter can produce a rate on eleven calls, the board has become the thing
it was built to replace.

**Day 14 — walk it as a stranger.**
Sign up with an address nobody here owns, on a phone, through the front door. Claim a handle.
Publish a call. Share it into a group chat and look at the preview. Press Verify. Every defect in
§4 above GAP 7 was findable this way and none of them was findable any other way.

**What I would deliberately not build:** more surfaces, any model feature, a mobile app, payments, or
anything that makes the board more impressive. The record is 43.2% of 412 with an interval that spans
zero, and that must stay exactly as unflattering as it is. The product's asset is that it is
checkable, and everything in these two weeks is in service of someone outside this building being
able to check it.

---

## Appendix: one-command health check

```bash
make test                                                                      # 874, incl. 83 receipts
docker compose exec -T api python -m tradeos.cli verify-chain convergence-v3   # 323 links
docker compose exec -T api python -m tradeos.cli verify-chain convergence-v4   # 150 links
curl -s localhost:8000/api/board | head -c 200                                 # the landing route
curl -s localhost:8000/api/card/receipt/convergence-v3.svg | head -c 80        # the route-layer dep
curl -s localhost:8000/r/convergence-v3 | grep og:image                        # GAP 3 — still relative + .svg?
```
