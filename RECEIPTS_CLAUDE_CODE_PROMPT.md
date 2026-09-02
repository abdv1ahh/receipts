# BUILD BRIEF: RECEIPTS

Paste this whole file into Claude Code as the opening message, from the repository root at `/path/to/receipts` on branch `main`.

---

## 0. READ THIS BEFORE YOU TOUCH ANYTHING

You are working in an existing, healthy, 35,000 line codebase. It has 720 passing tests, it is lint clean, and it has a detailed operating manual at `CLAUDE.md`. **Read `CLAUDE.md` first, in full, before writing a single line.** Then read `docs/state.md` and `docs/decision-log.md`. Everything below assumes you have.

You are adding a new product surface called **Receipts** on top of what exists. You are not rewriting the app. You are not refactoring. You are not "cleaning up" anything you were not asked to touch. Every existing test must still pass when you are done.

**Hard rules, in priority order:**

1. **Never fabricate data.** Not a price, not a track record, not a caller, not a number in a UI mock. This codebase has an explicit anti fabrication discipline enforced by `explain/guards.py` and by tests. If a surface has no data, it renders an honest empty state that says why. If you are tempted to seed a plausible looking demo user with plausible looking wins, stop. That single act destroys the entire product thesis.
2. **Append only means append only.** The integrity guarantees in this feature are the product. Do not add an update path, a delete path, an admin override, or a soft delete to sealed data. Not "just for testing."
3. **Follow the existing conventions.** Raw SQL through `psycopg.sql` composition, never f strings (ruff `S608` is enabled). Migrations are ordered `.sql` files that insert their own `schema_migrations` row. No ORM. No new frameworks. No react router, no state library, no CSS framework.
4. **Tests are not optional.** Every new module gets tests in `tests/`. The suite must finish green. Run `make test` before you report done.
5. **Free tiers only.** No paid API, no paid service, no new paid dependency.
6. **When blocked, stop and report.** Do not invent a workaround that quietly weakens a guarantee. Say what is blocking and what you would need.

**Writing style for all user facing copy:** do not use dashes of any kind. No hyphens, no en dashes, no em dashes, in any string a user will read. Rewrite around them with commas, conjunctions, or separate sentences. This applies to UI labels, empty states, error messages, tooltips, and the marketing site. It does not apply to code identifiers, file paths, URLs, or SQL.

---

## 1. WHAT WE ARE BUILDING AND WHY

### The product

**Receipts** is a public, permanent, cryptographically chained record of market calls.

A caller claims a handle, verifies control of the place their audience already lives, and then publishes dated directional calls through the system **before the outcome is known**. Every call is sealed at write time into a per caller SHA256 hash chain and written to a table whose trigger refuses deletes and refuses updates to sealed columns. After the stated horizon elapses, the call resolves automatically against Tiingo end of day prices, benchmarked against SPY, with an explicit noise floor. The public record page shows the entire history with misses above hits, confidence intervals beside every rate, and an honest sample size gate.

The caller cannot edit a call, cannot delete a loser, cannot reorder history, and cannot backdate. Anyone can hit **Verify chain** and watch the system recompute every hash in sequence.

### Why it works

The buyer is the person whose income depends on being believed: newsletter operators, signal group operators, independent research writers. Verification is a sales asset for them, not a cost. The reader side is free forever because it is the distribution.

### The thing that makes the demo land

The first record on the board belongs to **our own signal engine**. It made 473 resolved calls, hit 43.2 percent, which is below a coin flip, has an expectancy confidence interval that spans zero, and would need 1,268 resolved calls to detect a one percent edge while holding 412. We publish it anyway, prominently, as caller number one. That is the proof the scoring is not rigged in the operator's favour, and it is the emotional centre of the pitch.

**Under no circumstances present that 43.2 percent as a positive result.** It is below chance. The honesty is the point.

---

## 2. PHASE 0: REPAIR. DO THIS FIRST, IT TAKES MINUTES

Nothing below works until these four are done. Do them in order and confirm each.

### 0.1 Fix the backup script, because it is silently broken

`scripts/backup.sh` sets `set -euo pipefail`. The shell creates the output file for the `>` redirect **before** running `docker compose exec ... pg_dump`. When the Docker daemon is down that command exits non zero, `set -e` aborts the script immediately, and it never reaches the `SIZE=$(wc -c ...)` check, never reaches `rm -f "$OUT"`, and never prints the failure message. A zero byte file is left on disk looking like a backup. Three of the last four nightly runs produced zero bytes and a fourth truncated at 2.9 GB.

Fix it so the size check and cleanup run **even when pg_dump fails**. Capture the exit status explicitly rather than letting `set -e` abort, then branch. Also raise the floor: the current 100 KB floor would pass a multi gigabyte truncated dump. Make the floor a percentage of the previous successful dump, defaulting to the existing floor when there is no prior dump.

Then run `bash scripts/backup.sh --verify` and confirm it produces a real file and a real verification.

Context for why this matters: of roughly 7.9 GB, only about 18 MB is genuinely irreplaceable, and that 18 MB is the users, the trades, the journal, the whole claims and claim_outcomes ledger, and the RSS and Bluesky event history that those feeds do not serve retrospectively. The rest is `raw_filings`, which is public and permanent at SEC EDGAR.

### 0.2 Revive the model provider chain, at zero cost

`EXPLAIN_PROVIDER=gemini,openai`. The `openai` slot points at GitHub Models, which returns **HTTP 410 `github_models_retirement_brownout`**. The chain has had no working fallback for five weeks, which is why the claim engine produced 142 claims in six days and then one in the following thirty four days.

`llm.py` already supports any OpenAI compatible endpoint and `tests/test_llm.py` already exercises Groq and OpenRouter base URLs. Repoint the slot at Groq's free tier:

```
OPENAI_BASE_URL=https://api.groq.com/openai/v1
OPENAI_API_KEY=<groq key, free, no credit card>
OPENAI_MODEL=<a currently available Groq model>
```

**Critical gotcha:** `docker-compose.yml` enumerates every environment variable explicitly as `FOO: ${FOO:-}`. A key in `.env` alone does not reach the container. Add the variables in **both** `.env` and `docker-compose.yml`.

Then add the missing registry entries. `tradeos/sources.py:CATALOG` is missing six services this codebase actually talks to: **Binance, FINRA, Stripe, Sentry, and both LLM providers**. That is why the Integrations page, whose entire purpose is so the owner never has to guess why a panel is empty, structurally cannot report the model chain outage. Add all six. The repo's own rule in `CLAUDE.md` says adding an ingestion module is not done until it has a CATALOG entry, so this is fixing an existing violation.

Verify with `python -m tradeos.cli check-source` for each and confirm `/api/integrations` now reports the LLM chain.

### 0.3 Bring the stack up and refresh prices

The Docker daemon stopped on this machine at 2026-08-29 06:04 UTC and every scheduled job stopped with it.

```
docker compose up -d db api worker
```

Then start the price top up and leave it running in the background for the rest of the session:

```
bash scripts/topup-prices.sh --only-stale
```

SPY is the benchmark for every score in this product and its newest bar is 2026-08-21. The Tiingo free tier paces at roughly 45 to 57 unique symbols per hour, so prioritise SPY first, then the symbols used in the demo. Report how far it got.

### 0.4 Confirm the baseline before you build

```
make test
make lint
```

Both must be green before Phase 1. If `make lint` reports `UP038` findings, note that this is a ruff version artefact rather than a code regression (CI installs an unpinned ruff and UP038 has moved between releases). Pin the ruff version in `.github/workflows/ci.yml` while you are there.

---

## 3. PHASE 1: THE DATA MODEL

Create `migrations/034_receipts.sql`. It must insert its own `schema_migrations` row, matching the convention of the existing 33 files.

### 3.1 Tables

```sql
CREATE TABLE callers (
    id                        BIGSERIAL PRIMARY KEY,
    user_id                   BIGINT REFERENCES users(id) ON DELETE SET NULL,
    handle                    TEXT NOT NULL UNIQUE,
    display_name              TEXT NOT NULL,
    bio                       TEXT,
    kind                      TEXT NOT NULL DEFAULT 'human'
                                  CHECK (kind IN ('human', 'algorithm')),
    is_house                  BOOLEAN NOT NULL DEFAULT FALSE,
    audience_url              TEXT,
    verified_at               TIMESTAMPTZ,
    verification_method       TEXT CHECK (verification_method IN
                                  ('public_post', 'meta_tag', 'wallet_signature', 'house')),
    verification_evidence_url TEXT,
    jurisdiction_attested     BOOLEAN NOT NULL DEFAULT FALSE,
    created_at                TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE calls (
    id                BIGSERIAL PRIMARY KEY,
    caller_id         BIGINT NOT NULL REFERENCES callers(id),
    seq               INTEGER NOT NULL,
    symbol            TEXT NOT NULL,
    direction         TEXT NOT NULL CHECK (direction IN ('up', 'down')),
    horizon_days      INTEGER NOT NULL CHECK (horizon_days IN (7, 30, 90)),
    confidence        TEXT NOT NULL CHECK (confidence IN ('low', 'medium', 'high')),
    thesis            TEXT NOT NULL,
    benchmark_symbol  TEXT NOT NULL DEFAULT 'SPY',
    published_at      TIMESTAMPTZ NOT NULL,
    knowable_time     TIMESTAMPTZ NOT NULL,
    prev_hash         TEXT NOT NULL,
    content_hash      TEXT NOT NULL,
    entry_session     DATE,
    exit_session      DATE,
    entry_price       NUMERIC,
    exit_price        NUMERIC,
    benchmark_entry   NUMERIC,
    benchmark_exit    NUMERIC,
    subject_return    NUMERIC,
    benchmark_return  NUMERIC,
    excess_return     NUMERIC,
    verdict           TEXT CHECK (verdict IN ('hit', 'miss', 'inconclusive', 'unscoreable')),
    verdict_note      TEXT,
    resolved_at       TIMESTAMPTZ,
    context_snapshot  JSONB,
    UNIQUE (caller_id, seq),
    UNIQUE (content_hash)
);

CREATE INDEX calls_caller_seq_idx ON calls (caller_id, seq);
CREATE INDEX calls_due_idx ON calls (verdict, published_at) WHERE verdict IS NULL;

CREATE TABLE caller_verifications (
    id           BIGSERIAL PRIMARY KEY,
    caller_id    BIGINT NOT NULL REFERENCES callers(id) ON DELETE CASCADE,
    code         TEXT NOT NULL,
    method       TEXT NOT NULL,
    evidence_url TEXT,
    status       TEXT NOT NULL DEFAULT 'pending'
                     CHECK (status IN ('pending', 'confirmed', 'rejected')),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at  TIMESTAMPTZ
);
```

### 3.2 The append only trigger, which is the product

This is the single most important object in the migration. Sealed columns are immutable and rows cannot be deleted. Only the resolution columns may ever be written after insert.

```sql
CREATE OR REPLACE FUNCTION calls_append_only() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'calls rows are append only and cannot be deleted';
    END IF;

    IF OLD.caller_id     IS DISTINCT FROM NEW.caller_id
    OR OLD.seq           IS DISTINCT FROM NEW.seq
    OR OLD.symbol        IS DISTINCT FROM NEW.symbol
    OR OLD.direction     IS DISTINCT FROM NEW.direction
    OR OLD.horizon_days  IS DISTINCT FROM NEW.horizon_days
    OR OLD.confidence    IS DISTINCT FROM NEW.confidence
    OR OLD.thesis        IS DISTINCT FROM NEW.thesis
    OR OLD.published_at  IS DISTINCT FROM NEW.published_at
    OR OLD.knowable_time IS DISTINCT FROM NEW.knowable_time
    OR OLD.prev_hash     IS DISTINCT FROM NEW.prev_hash
    OR OLD.content_hash  IS DISTINCT FROM NEW.content_hash
    OR OLD.benchmark_symbol IS DISTINCT FROM NEW.benchmark_symbol THEN
        RAISE EXCEPTION 'sealed columns on calls are immutable';
    END IF;

    IF OLD.verdict IS NOT NULL AND OLD.verdict IS DISTINCT FROM NEW.verdict THEN
        RAISE EXCEPTION 'a resolved verdict cannot be changed';
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER calls_append_only_trg
    BEFORE UPDATE OR DELETE ON calls
    FOR EACH ROW EXECUTE FUNCTION calls_append_only();
```

Write a test that proves all three refusals fire: a delete, a sealed column update, and a verdict rewrite. That test is the evidence behind the product's central claim, so make it explicit and name it clearly.

---

## 4. PHASE 2: BACKEND MODULES

Create the package `tradeos/receipts/` with four modules. Keep each one small and pure where possible, matching the style of `backtest/engine.py`.

### 4.1 `tradeos/receipts/chain.py`

The hash chain. No database access in the pure functions.

```
GENESIS_HASH = "0" * 64

canonical_payload(call: dict) -> str
    Deterministic serialisation of the sealed fields only, in a fixed order,
    with timestamps in UTC ISO 8601 to the microsecond and numerics as strings.
    Field order must never change. Document it in the module docstring.

content_hash(payload: str, prev_hash: str) -> str
    sha256 of (prev_hash + payload), hex digest.

seal(call: dict, prev_hash: str) -> tuple[str, str]
    Returns (canonical_payload, content_hash).

verify_chain(calls: list[dict]) -> dict
    Walks calls in seq order, recomputes every hash, and returns
    {"intact": bool, "links": int, "broken_at_seq": int | None, "expected": str, "found": str}
```

Tests must cover: a genesis link, a valid multi link chain, a chain with one tampered field, a chain with a removed link, and a chain with two links swapped. Each tampered case must report the correct `broken_at_seq`.

### 4.2 `tradeos/receipts/calls.py`

Publishing and scoreability. This module enforces the single most important design decision in the product: **a call that cannot be scored cannot be published in an ambiguous form.**

```
SCOREABLE_HORIZONS = (7, 30, 90)

scoreability(symbol: str, conn) -> dict
    Returns {"scoreable": bool, "reason": str}.
    A symbol is scoreable when prices_eod holds a usable series for it
    and for the benchmark. Not scoreable returns the honest reason,
    for example "no price series loaded for this symbol".

validate(spec: dict) -> list[str]
    Returns a list of human readable problems. Empty list means valid.
    Requires symbol, direction, horizon_days, confidence, and a thesis
    of at least 40 characters. Rejects anything else.

publish(caller_id: int, spec: dict, conn) -> dict
    Inside one transaction, with the caller row locked:
      1. validate
      2. read the caller's current max seq and its content_hash
      3. set published_at and knowable_time to the same now()
      4. seal via chain.seal
      5. insert
      6. capture the frozen context (see 4.5) and store it in context_snapshot
    Returns the created call.
    If the symbol is not scoreable, still publish it, but write
    verdict = 'unscoreable' and a verdict_note explaining why, immediately.
    Never silently reject. Never silently accept something unscoreable
    as if it were scoreable.

listing(caller_id: int, conn) -> list[dict]
```

### 4.3 `tradeos/receipts/scoring.py`

Resolution. Reuse the existing statistics rather than rewriting them.

```
NOISE_FLOOR = 0.02

entry_exit_sessions(published_at, horizon_days, symbol, conn) -> tuple[date, date] | None
    Entry is the close of the first trading session strictly after published_at.
    Use backtest.engine.entry_day_after. Never the session in progress.
    Exit is the close of the session at or after entry plus horizon_days
    trading sessions.

verdict_for(direction: str, excess: float) -> tuple[str, str]
    Excess inside plus or minus NOISE_FLOOR returns ('inconclusive', reason).
    Otherwise sign agreement with direction gives 'hit', disagreement 'miss'.
    Always return the human readable reason alongside.

resolve_call(call_id: int, conn) -> dict
    Computes entry, exit, subject return, benchmark return, excess return,
    the verdict and the note, and writes only the resolution columns.
    If the price series is incomplete, writes 'unscoreable' with the reason.

resolve_due(conn, limit: int = 100) -> dict
    Finds calls whose horizon has elapsed and whose verdict is NULL,
    resolves each, and returns counts by verdict.
```

Use `backtest.engine.excess_return` for the arithmetic. Do not write a second implementation of it.

### 4.4 `tradeos/receipts/record.py`

Composition of the public record. Every statistic here already exists in `ledger.py`. Import them, do not reimplement.

```
SAMPLE_GATE = 25

summary(caller_id: int, conn) -> dict
    {
      "counts": {"hit": n, "miss": n, "inconclusive": n, "unscoreable": n, "open": n},
      "resolved_scoreable": n,          # hit + miss only
      "hit_rate": float | None,          # None below SAMPLE_GATE
      "hit_rate_ci": [lo, hi] | None,    # ledger.py wilson / mean_ci
      "expectancy": float | None,
      "expectancy_ci": [lo, hi] | None,
      "z_vs_coinflip": float | None,     # ledger.proportion_z
      "sample_needed_1pct": int,         # ledger.sample_needed
      "gated": bool,                     # True below SAMPLE_GATE
      "gate_reason": str | None
    }

calibration(caller_id: int, conn) -> list[dict]
    Stated confidence bucket against observed hit rate, with counts and intervals.
    Use ledger.confidence_bucket.

recent_misses(caller_id: int, limit: int, conn) -> list[dict]

board(conn) -> list[dict]
    Every caller with their summary. Callers below SAMPLE_GATE appear
    with counts and a "Low N" label and are never assigned a rank.
```

**The gate is not decoration.** Below 25 resolved scoreable calls, `hit_rate` is `None` and the UI must render counts rather than a percentage. This matches the discipline already in `ledger.py` and in `ledger.jsx`, and it is the convention the category uses.

### 4.5 Wire the frozen context

`journal_context.py` already freezes what the system was showing at the moment a trade was logged: live claims on that symbol, claims live generally, an alignment verdict, the mean novelty of the moment. It has `capture`, `for_trade` and `across_trades`, and it returned real data for demo trade 21.

Add a thin adapter so `calls.publish` captures the same snapshot for a call and stores it in `calls.context_snapshot`. Do not duplicate the logic. If the claim engine is producing nothing at the moment of capture, the snapshot must say so honestly rather than being empty.

### 4.6 `tradeos/receipts/verification.py`

Free, no external API, manually reviewable.

```
start(caller_id, method, conn) -> dict
    Issues a one time code of the form "receipts-verify-<8 random chars>"
    and returns instructions for the chosen method.

confirm(caller_id, evidence_url, conn) -> dict
    Records the evidence URL and moves the request to pending review.
    An admin route approves it. Do not fetch the URL automatically in
    this phase; a server side fetcher of a user supplied URL needs the
    same SSRF defence that radar.py already implements in
    webhook_target_ok, so if you do add fetching, reuse that function
    rather than writing a new one.
```

Methods to support: `public_post` (post the code in a public post or newsletter and paste the URL back) and `meta_tag` (put the code in a meta tag on your own site). Both are free and require no third party API. Leave `wallet_signature` declared in the CHECK constraint but unimplemented, and do not show it in the UI yet.

---

## 5. PHASE 3: API ROUTES

Add to `tradeos/app.py`, following the existing patterns exactly: Pydantic request models, `_require_admin` returning the user or `None`, rate limiting on public and model paths, and the `harden` middleware untouched.

| Method | Path | Auth | Returns |
|---|---|---|---|
| POST | `/api/callers` | user | Claim a handle. Enforces uniqueness and the jurisdiction attestation. |
| GET | `/api/callers/me` | user | The signed in user's caller row, or null. |
| POST | `/api/callers/verify/start` | user | Issues the verification code and instructions. |
| POST | `/api/callers/verify/confirm` | user | Submits the evidence URL. |
| POST | `/api/admin/callers/{id}/verify` | admin | Approves or rejects a verification. |
| POST | `/api/calls` | user | Publishes a call. Seals it. Returns the sealed row including its hash. |
| GET | `/api/calls/{id}` | public | One call with its full proof panel payload. |
| GET | `/api/receipts/{handle}` | public | The full record: summary, calibration, misses first, every call. |
| GET | `/api/receipts/{handle}/verify` | public | Recomputes the chain and returns the verify_chain result. |
| GET | `/api/board` | public | Every caller with their summary, gated callers labelled. |
| GET | `/api/receipts/methodology` | public | The scoring rules as structured data so the UI never hardcodes them. |
| GET | `/api/card/receipt/{handle}.svg` | public | Server rendered OG share card for a record. |
| GET | `/r/{handle}` | public | Server rendered share page with OG tags, same pattern as `/s/{symbol}`. |

Rate limit `POST /api/calls` and add `/api/receipts`, `/api/board` and `/r/` to `_PUBLIC_PREFIXES` in `ratelimit.py`.

The share card at `/api/card/receipt/{handle}.svg` should follow the existing `presentation.score_card_svg` pattern. Put the caller handle, the resolved counts, the hit rate with its interval when ungated, and the chain link count on it. If gated, put the counts and the words "Low N" rather than a rate. **Never render a rate on a card for a gated record.**

---

## 6. PHASE 4: SCHEDULER

Register one new job in `scheduler.py`'s `JOBS` registry, matching the existing structure:

```
resolve_calls   interval 21600 s (6 h)   calls receipts.scoring.resolve_due
```

The scheduler's existing per job error isolation and `job_runs` recording apply automatically. One important note the inventory raised: **a job that produces nothing is still recorded as a successful run**, which is how a month of zero claim production went unnoticed. Have `resolve_due` return counts by verdict in the detail blob so `job_runs.detail` shows what actually happened, and log explicitly when there was nothing due.

---

## 7. PHASE 5: FRONTEND

Five new surfaces in `frontend/src/`. Routing is about forty lines over the History API in `shell.jsx` via `useRoute`, with `ROUTES`, `NAV_LABELS` and `CMD_ITEMS`. Add every new route to **all three**, because the existing bug where `portfolios.jsx` is imported and rendered but absent from `ROUTES` is exactly how a whole feature became unreachable.

Reuse the shared primitives: `LoadError`, `EmptyState`, `SourceGate`, and one `ErrorBoundary` per surface keyed by view.

### 7.1 `record.jsx` : the public record page at `/r/{handle}`

This is the product. Give it the most care.

Layout, top to bottom:

1. **Header.** Display name, handle, verified badge with the method and the evidence link, audience link, and for the house records a clear label reading "This is our own signal engine."
2. **The chain strip.** Number of sealed calls, the current chain head hash truncated, and a **Verify chain** button. On click, call `/api/receipts/{handle}/verify` and animate through the links, then report intact with the link count, or report the exact `seq` where it broke. This is the moment the demo turns, so make it feel deliberate rather than instant.
3. **The record.** Counts for hit, miss, inconclusive, unscoreable and open, always all five, always visible. When ungated: the hit rate with its Wilson interval, expectancy with its interval, the z score against a coin flip, and `sample_needed` printed next to the sample actually held. When gated: counts only, a "Low N" chip, and the sentence explaining that a rate is not shown below 25 resolved calls.
4. **Recent misses, above the breakdowns.** This ordering is deliberate and it is already the convention in `ledger.jsx`. Do not move them below.
5. **Calibration.** Stated confidence against observed, per bucket, with counts.
6. **Every call**, newest first, each row linking to its detail page, each showing its verdict chip, its excess return, and its sealed timestamp.
7. **Footer.** The disclaimer block from section 9.

### 7.2 `publish.jsx` : the publish form

Five fields: symbol, direction, horizon, confidence, thesis. Live scoreability check on the symbol as it is typed, calling the API, showing either "scoreable against SPY" or the honest reason it is not. A visible pre submit panel stating in plain language: this call is sealed on submit, it cannot be edited, it cannot be deleted, and the horizon cannot be changed.

After submit, show the sealed receipt: the timestamp, the sequence number, the content hash, and the previous hash it chains from.

### 7.3 `board.jsx` : the public board

Every caller. Gated callers rendered with counts and a Low N chip, never with a rank or a rate. A prominent line at the top of the board stating that this is a measurement of past statements, that it is not investment advice, and that a high position is not a recommendation to follow anyone.

### 7.4 `calldetail.jsx` : one call, with proof

The call itself, then a **proof panel** showing: published at, knowable time, sequence, previous hash, content hash, entry session, exit session, entry price, exit price, benchmark entry, benchmark exit, subject return, benchmark return, excess return, the noise floor applied, and the verdict with its note. An investor should be able to check the arithmetic with a calculator. Below that, the frozen world context captured at publish time.

### 7.5 `methodology.jsx` : the rules

Rendered from `/api/receipts/methodology` so the rules can never drift from the code. Entry convention, exit convention, benchmark, noise floor, the four verdicts with what each means, the sample gate, the scoreable universe and its current size, and an explicit statement of what the hash chain does and does not prove.

**Be honest on that last point.** The chain is tamper evident against the caller. It is not tamper evident against the operator, who could recompute the whole chain. Say so on this page, and say that a daily public anchor of the chain head is the roadmap answer. Do not call it a blockchain. Understating this is more credible than dressing it up, and an investor who catches an overclaim will discount everything else.

---

## 8. PHASE 6: NAVIGATION AND DEMO SAFETY

The app currently opens on an empty Radar. That cannot happen during a pitch.

### 8.1 Restructure the sidebar

Receipts becomes the product. Everything else becomes supporting research.

```
RECEIPTS       The Board (default landing) | Publish a call | My record | Methodology
RESEARCH       Smart Money | Ledger | Calendar | Crypto | News | Journal | Watchlist
SYSTEM         Integrations | Assistant | Search
```

Change the default landing route from Radar to **The Board**.

### 8.2 Hide, do not delete

Remove from `NAV_LABELS`, `ROUTES` and `CMD_ITEMS`, leaving the code in place:

- **Radar, Exposure, Globe.** Empty until the claim engine has been producing for a while. They can come back once Phase 0.2 has been running for a day.
- **Library.** All 20 entries carry a `review_status: 'draft'` badge, and one teaches `congressional-disclosure-limits`, a feature removed in migration 033.
- **Community and the trader leaderboard.** One public trade, an empty leaderboard behind an honest ten closed trade gate.

### 8.3 Fix the two live embarrassments while you are here

- **The News default window.** `/api/news` queries the last 72 hours and the newest item is 2026-08-29, so it renders empty despite holding 3,690 items. Widen the default so it is never empty when data exists.
- **Shadow portfolios.** `pricing.jsx` line 33 still advertises "N shadow portfolios" as a paid entitlement and there is no route to the screen. Either add `portfolios` to `ROUTES`, `NAV_LABELS` and `CMD_ITEMS` under Research, or remove the line from the pricing page. Do not leave a paid feature advertised with the door bricked up.

### 8.4 Leave the staleness banner alone

`dashboard.jsx` computes the age of the signal snapshot and renders `data 37 days old` in a stale style. **Do not hide this.** It is the codebase being honest on purpose and it is on message for this product. The same applies to the Smart Money "as of 2026-07-27" line.

### 8.5 Update the pricing page

Three tiers, replacing the current Free / Trader / Pro framing:

- **Reader, free forever.** Every record page, the board, the methodology, chain verification.
- **Caller, $19 per month.** A verified record page, unlimited calls, the share card, the embed.
- **Desk, $99 per month.** Multiple handles, the API, exports.

Keep it in test mode. The Stripe code is complete and signature verified; the SDK is simply not installed.

---

## 9. PHASE 7: SEED, HONESTLY

This is where a careless build destroys the product. **Do not invent a caller. Do not invent a call. Do not invent a win.**

There is exactly one honest source of historical record in this database: the signal plane's own resolved claims. The `claims` table holds 473 resolved claims, all legacy signal plane, split by model as `convergence-v3` with 323 and `convergence-v4` with 150.

Write a CLI command `python -m tradeos.cli seed-house-records` that imports those two model families as **two algorithm callers**:

- `@convergence-v3`, kind `algorithm`, `is_house` true, 323 calls
- `@convergence-v4`, kind `algorithm`, `is_house` true, 150 calls

For each imported claim, preserve the real `created_at` as `published_at` and `knowable_time`, preserve the real verdict from `claim_outcomes`, and seal each into the chain in true chronological order. Nothing is invented; the chain is computed over facts already in the database.

This gives the board two real rows with different sample sizes, which demonstrates the gate visually: one certified above 25 resolved calls, one that may sit below it. Both real.

On both record pages, render a prominent, honest banner:

> This record belongs to our own signal engine. Across 412 calls that resolved as hit or miss it was right 43.2 percent of the time, which is below a coin flip. Its expectancy interval spans zero. We publish it because a scoreboard that only shows winners is not a scoreboard.

Any human caller starts at zero calls and the record page says so. During the demo, calls are published live.

---

## 10. DESIGN

Do not invent a new visual language. Read `frontend/src/styles.css`, `shared/tokens.css` and `site/src/sections.jsx` first and extend what is there.

The existing identity is nautical and cartographic: hand drawn SVG compass rose, graticule and bearing components, and three self hosted font families (Inter Variable, IBM Plex Mono, Instrument Serif). Keep it. It already reads as instrument rather than as hype, which is exactly right for a product about measurement.

Direction for the Receipts surfaces specifically:

- **Feel:** a registry or a certificate. Ledger book, not trading terminal. Generous whitespace, quiet rules, restraint.
- **Numbers:** IBM Plex Mono with tabular figures throughout, so columns align and nothing jitters on update.
- **Headlines:** Instrument Serif for record page headers and the caller name.
- **Colour discipline:** verdicts get muted, low saturation treatments. No neon green for hits. No alarm red for misses. A miss is a normal outcome and should look like one. Reserve the single strongest accent in the palette for the chain verification state, because that is the one moment that should feel like something happened.
- **Hierarchy on the record page:** the counts and the intervals are the largest text. The hit rate is not the hero. This is deliberate and it is the opposite of what every competitor does.
- **Empty states:** every one names what is missing and why, following the existing `EmptyState` and `SourceGate` convention where an empty panel always says which source is absent and links to where its free key comes from.
- **The gate:** a Low N chip should look like a neutral fact, not a warning.

If you want a reference for how a scored record reads, look at how `ledger.jsx` already lays out misses above breakdowns and refuses percentages on thin slices. Extend that language rather than replacing it.

---

## 11. LEGAL COPY, WHICH IS NOT OPTIONAL

Chairman of the Board Resolution No. (10/R.M) of 2025, effective 21 May 2025, regulates financial recommendations to a UAE audience and applies extraterritorially by audience location rather than by creator location. The Securities and Commodities Authority became the **Capital Market Authority** on 1 January 2026. Separately, if any caller is a US registered investment adviser, SEC Rule 206(4)-1 governs testimonials, endorsements and third party ratings, and a public scoreboard of named advisers edges toward a third party rating.

The product must therefore be, and must read as, a **measurement and analytics tool rather than an advisory service**.

Implement all of the following:

1. A persistent footer on every public surface: this platform measures publicly stated market calls. It is not investment advice, it is not a recommendation, and no position on the board is an endorsement of any person.
2. A line on every record page and every share card: past performance does not predict future results.
3. A line at the top of the board stating that ranking measures past statements only.
4. A required checkbox at caller signup where the caller attests that they are responsible for their own regulatory and registration status in their jurisdiction, stored as `callers.jurisdiction_attested`. Refuse to create a caller without it.
5. Nowhere in the product may a surface rank callers by expected future return, suggest following anyone, or imply that a high position predicts anything.

---

## 12. ACCEPTANCE CRITERIA

You are done when every one of these passes. Run them and paste the output.

**Integrity**
- [ ] `DELETE FROM calls WHERE id = <any>` raises an exception.
- [ ] `UPDATE calls SET thesis = 'x' WHERE id = <any>` raises an exception.
- [ ] `UPDATE calls SET published_at = now() WHERE id = <any>` raises an exception.
- [ ] Updating a resolved `verdict` raises an exception.
- [ ] `GET /api/receipts/convergence-v3/verify` returns `intact: true` with a link count of 323.
- [ ] Manually corrupting one `content_hash` in a scratch copy makes `verify` return `intact: false` with the correct `broken_at_seq`, and restoring it returns to intact.

**Scoring**
- [ ] A call published today enters at the **next** trading session close, never today's.
- [ ] A call whose excess return is inside plus or minus 2 percent resolves `inconclusive`, not `hit`.
- [ ] A call on a symbol absent from `prices_eod` publishes with `verdict = 'unscoreable'` and a readable reason, and the reason is visible in the UI.
- [ ] `/api/receipts/{handle}` returns `hit_rate: null` and `gated: true` for a caller below 25 resolved scoreable calls.
- [ ] The house record reports a hit rate of 0.432 over 412 resolved scoreable calls, an expectancy interval that spans zero, and `sample_needed_1pct` of 1,268.

**Surfaces**
- [ ] The app opens on The Board, not on Radar.
- [ ] Every new route appears in `ROUTES`, `NAV_LABELS` and `CMD_ITEMS`.
- [ ] Radar, Exposure, Globe, Library and Community are unreachable from navigation.
- [ ] No surface reachable from the sidebar renders an empty state on a fresh start.
- [ ] `/r/convergence-v3` returns 200 unauthenticated and carries OG tags.
- [ ] `/api/card/receipt/convergence-v3.svg` returns a valid SVG.
- [ ] A gated record's share card shows counts and Low N, never a percentage.
- [ ] The disclaimer footer appears on every public surface.

**Health**
- [ ] `make test` is green, with the new tests included and the original 720 still passing.
- [ ] `make lint` is clean.
- [ ] `bash scripts/backup.sh --verify` produces a real, verified dump.
- [ ] `/api/integrations` reports the LLM provider chain, Binance and FINRA.
- [ ] `python -m tradeos.cli check-source` passes for Tiingo and the LLM chain.
- [ ] `GET /api/jobs` shows `resolve_calls` registered.

---

## 13. EXPLICITLY OUT OF SCOPE

Do not build, do not stub, do not scaffold:

- Any X, Twitter, Reddit, YouTube, Telegram or Discord ingestion. There is no free compliant read path for the ones that matter and scraping is off limits.
- Any crypto, on chain, wallet, DEX, Solana or token feature. Wallet signature verification is declared in a CHECK constraint and left unimplemented on purpose.
- Live Stripe. Test mode only.
- Email of any kind. There is no SMTP and password reset is unrecoverable, which is why auth is not in the demo.
- Any social feed, comment thread, follow graph or reaction on Receipts surfaces.
- Broker integrations.
- Any change to `signals/convergence.py`, whose `module_code_hash` refuses to run on drift, or to the existing `claims`, `claim_outcomes` or `ledger` write paths. Read from them, never write.

---

## 14. HOW TO WORK AND HOW TO REPORT

Work in phase order. Phase 0 first, then 1 through 7. Commit at the end of each phase with a message naming the phase. Run `make test` at the end of every phase, not just at the end.

If something in this brief conflicts with what you find in the codebase, **the codebase wins**. Stop, say precisely what the conflict is, and propose the resolution rather than guessing.

If a phase turns out to be materially larger than described, say so before starting it, name what you would cut, and continue with the reduced scope rather than running long silently.

When you finish, report:

1. What was built, by phase.
2. Every acceptance criterion, with its actual result.
3. Anything you could not do and exactly what blocked it.
4. Anything you found in the codebase that contradicts this brief.
5. The exact commands to run the demo from cold, in order, including how long before the demo the worker should be started.
6. Anything a viewer could click that would embarrass, and what you did about it.
