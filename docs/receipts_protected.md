# Receipts — what must survive the deletion

**Written 2026-09-13.** Every list here is generated, not recalled: the dependency section comes
from an **AST import graph** that parses every module in the package (so a lazy import inside a
function is found and a name in a comment is not), and the collision claims were verified by
breaking a module and observing the failure.

**Read §3 first if you are about to delete something.** It contains a correction to
`docs/analysis/receipts_explained.md`.

---

## 1. Everything that belongs to Receipts

### Source — backend (8 modules, 1,417 lines)

```
tradeos/receipts/__init__.py
tradeos/receipts/chain.py          the hash chain. Pure: no DB, no clock, no randomness
tradeos/receipts/calls.py          publishing, validation, scoreability, sealing
tradeos/receipts/scoring.py        resolution against EOD prices, benchmarked to SPY
tradeos/receipts/record.py         counts, intervals, calibration, the board
tradeos/receipts/verification.py   proving a caller controls their audience
tradeos/receipts/context.py        freezing what the system showed at publish time
tradeos/receipts/seed.py           importing the two house records
```

### Source — frontend (6 surfaces)

```
frontend/src/board.jsx         the landing route
frontend/src/record.jsx        one caller's full record + Verify chain
frontend/src/publish.jsx       the publish form
frontend/src/calldetail.jsx    one call, with the proof panel
frontend/src/methodology.jsx   how scoring works, and what the chain does NOT prove
frontend/src/receiptsui.jsx    shared components for the five above
```

`frontend/src/App.jsx` carries the nav group `{ label: "Receipts", items: ["board", "publish",
"record", "methodology"] }` and the `ROUTES` entries. **Removing a route from `ROUTES` without
removing the links to it turns every link into a silent redirect to the Board** — `CLAUDE.md` §0v,
and there is a test guarding it.

### Routes — 13, all in `tradeos/app.py`

| Route | Public? |
|---|---|
| `POST /api/callers` | auth |
| `GET /api/callers/me` | auth |
| `POST /api/callers/verify/start` | auth |
| `POST /api/callers/verify/confirm` | auth |
| `GET /api/admin/callers/pending` | admin |
| `POST /api/admin/callers/{verification_id}/verify` | admin |
| `POST /api/calls` | auth (own rate-limit bucket) |
| `GET /api/calls/scoreability` | **public** |
| `GET /api/calls/{call_id}` | **public** |
| `GET /api/receipts/methodology` | **public** |
| `GET /api/receipts/{handle}` | **public** |
| `GET /api/receipts/{handle}/verify` | **public** |
| `GET /api/board` | **public** |
| `GET /api/card/receipt/{handle}.svg` | **public** |
| `GET /r/{handle}` | **public**, server-rendered with OG tags |

Also in `app.py`: `_PUBLIC_PREFIXES` must keep `/api/receipts`, `/api/board`, `/r/`,
`/api/card/receipt/`, `/api/calls/`; and `_PUBLISH_PATHS` must keep `/api/calls`.

> `GET /api/receipts/methodology` is registered **before** `GET /api/receipts/{handle}`. Reordering
> them makes `methodology` match as a handle. The order is load-bearing.

### Database — 3 tables, plus the objects that make them mean anything

| Object | Kind | Why it matters |
|---|---|---|
| `callers` | table | 2 rows |
| `calls` | table | **473 rows — the hash chain. No second copy exists anywhere, by design.** |
| `caller_verifications` | table | 0 rows |
| `calls_append_only()` | function | refuses DELETE, refuses edits to sealed columns, refuses edits to a resolved call's figures |
| `calls_append_only_trg` | trigger | `BEFORE UPDATE OR DELETE ON calls` — **this is the product, not a safeguard around it** |
| `calls_due_idx` | index | the resolver's work queue |
| `callers_one_per_user_idx` | unique index | partial, added by 035 |
| `caller_verifications_caller_idx` | index | |

Also: `calls.caller_id` is a plain FK with no `ON DELETE`, so Postgres already refuses to delete any
caller who has published. That is deliberate — do not "tidy" it by adding `ON DELETE CASCADE`.

### Migrations

```
tradeos/migrations/034_receipts.sql                      creates all three tables + the trigger
tradeos/migrations/035_receipts_seal_the_measurement.sql seals the ARITHMETIC and adds the
                                                          one-caller-per-user index
```

**Both are applied.** Never edit an applied migration.

### Tests — 4 files, 108 tests

```
tests/test_receipts.py        integrity against a live database
tests/test_receipts_api.py    the routes
tests/test_receipts_chain.py  the chain, including the frozen wire format
tests/test_navigation.py      that no surface is unreachable
```

### CLI and scheduler

```
cli seed-house-records        import the two house records (idempotent by refusal)
cli resolve-calls             score calls whose horizon has closed
cli verify-chain <handle>     recompute a caller's whole chain
scheduler JOBS: ("resolve_calls", 21600, _job_resolve_calls)
```

---

## 2. What Receipts depends on, and which of it is on the deletion list

Produced by AST import graph, transitive closure from the 8 `tradeos.receipts.*` modules.

### Direct dependencies (imported by a Receipts module itself)

| Module | Used for | On the deletion list? |
|---|---|---|
| `tradeos.ledger` | `price_series`, `verdict_for`, the interval maths | 🔴 **NAMED FOR DELETION — COLLISION** |
| `tradeos.backtest.engine` | `excess_return`, `entry_day_after`, `exit_day_for`, `wilson_interval`, `Series` | 🔴 **NAMED FOR DELETION — COLLISION** |
| `tradeos.journal_context` | `ranked_for`, `summarize` (the frozen context) | not named, but see §3 |

### Transitive dependencies (pulled in at import time by the above)

```
tradeos.config
tradeos.explain              ← via journal_context -> trades
tradeos.explain.gemini       ← via journal_context -> trades
tradeos.explain.guards       ← via journal_context -> trades
tradeos.geography            ← via journal_context -> relevance
tradeos.llm                  ← via journal_context -> trades
tradeos.relevance            ← via journal_context
tradeos.trades               ← via journal_context
```

### Route-layer dependency — invisible to a package import graph

| Module | Used by | On the deletion list? |
|---|---|---|
| `tradeos.presentation` | `presentation.receipt_card_svg()` backs `GET /api/card/receipt/{handle}.svg` | 🔴 **NAMED FOR DELETION — COLLISION** |

`tradeos/receipts/` never imports `presentation`, so the package graph shows nothing. The **route**
does. Deleting `presentation.py` removes the share card without touching a single file under
`tradeos/receipts/`.

### Modules that import Receipts

```
tradeos.app         the 13 routes
tradeos.cli         the 3 commands
tradeos.scheduler   the resolve_calls job
```

### The collision list, in one place

| Module | Status | What breaks |
|---|---|---|
| **`tradeos/ledger.py`** | 🔴 DIRECT | `record.py`, `scoring.py`, `seed.py` fail to import. Scoring and every published statistic stop. |
| **`tradeos/backtest/engine.py`** | 🔴 DIRECT | `record.py`, `scoring.py` fail to import. No excess return, no interval, no calibration. |
| **`tradeos/presentation.py`** | 🔴 ROUTE | `GET /api/card/receipt/{handle}.svg` 500s. The share card is the part of the product that travels furthest. |
| **`tradeos/llm.py`, `tradeos/explain/`** | 🟠 IMPORT-TIME ONLY | `receipts/context.py` fails to import. **Nothing functional is lost** — see §3. |
| **`tradeos/signals/`** | 🟢 NOT A DEPENDENCY | Nothing. Not in the graph, not referenced. Safe to delete as far as Receipts is concerned. |

> `signals/` is safe **for Receipts**. It is not safe for the board's *content*: the 473 calls were
> imported from `claims`/`claim_outcomes`, which the signal plane produced. The existing calls are
> sealed and independent of it, but re-running `seed-house-records` on a fresh database would need
> those rows to still exist.

---

## 3. Does Receipts depend on `llm.py`, `claims.py`, `spine.py`, `explain/`, `intelligence/`?

**One line per module, as asked:**

| Module | Answer |
|---|---|
| `tradeos/llm.py` | **YES — import-time only.** No Receipts code path calls it. |
| `tradeos/claims.py` | **NO.** Not in the graph at any depth. |
| `tradeos/spine.py` | **NO.** Not in the graph at any depth. |
| `tradeos/explain/` (and `guards.py`, `gemini.py`) | **YES — import-time only.** No Receipts code path calls them. |
| `tradeos/intelligence/` (and `analyst.py`, `vision.py`) | **NO.** Not in the graph at any depth. |

### ⚠️ Correction to `docs/analysis/receipts_explained.md`

That document says Receipts has "**zero dependency on the LLM**", based on
`grep -rn "llm\|gemini\|openai\|explain" tradeos/receipts/` returning one comment. **That grep was
right and the conclusion drawn from it was too strong.** It measured *direct* imports. The import
*graph* is what a deletion actually hits, and the graph says otherwise.

**The exact chain, and it is a single link:**

```
tradeos/receipts/context.py : line 21  from .. import journal_context   (module level)
tradeos/journal_context.py  : line 43  from . import relevance, trades  (module level)
tradeos/trades.py           : line 26  from . import config, llm
                              line 27  from .explain.guards import ...
```

**Verified empirically**, not inferred — with `tradeos.llm` removed from `sys.modules`:

```
ModuleNotFoundError: import of tradeos.llm halted; None in sys.modules
==> deleting llm.py breaks receipts.context
```

**But the functional claim still holds**, and this is the part that matters for judging risk.
Receipts calls exactly two functions from `journal_context` — `ranked_for()` and `summarize()` — and
an AST call-graph walk of both shows **neither reaches `trades.*` at all**. The *only* use of
`trades` anywhere in `journal_context` is one call, `trades.realized_pnl_pct`, at line 337 inside
`across_trades()`, which Receipts never invokes.

So both statements are true and they are not in tension:

- **Runtime:** revoke every model key and Receipts is unaffected. The board, the chains, scoring and
  verification all keep working. The original conclusion was right.
- **Import time:** delete `llm.py` or `explain/` and `receipts/context.py` raises on import, which
  takes `calls.py` with it, which takes publishing with it.

**The fix is one line and it is not done here** — this session was told not to refactor. Making
`journal_context`'s `trades` import lazy (move `import trades` inside `across_trades()`) severs the
whole chain to `llm` and `explain/`. Worth doing *before* the deletion rather than during it.

---

## 4. If you delete anyway — the order that keeps the chain alive

1. **Back up first.** The `calls` table has no second copy by design. `docs/runbooks/backups.md`.
2. **Never drop `calls`, `callers` or `caller_verifications`,** and never drop
   `calls_append_only_trg`. A record whose owner can quietly drop a loser is a marketing page.
3. **Before deleting `llm.py` or `explain/`:** make `journal_context`'s `trades` import lazy, then
   confirm `python -c "import tradeos.receipts.calls"` still succeeds.
4. **Before deleting `ledger.py` or `backtest/engine.py`:** these are real, used dependencies. Move
   the functions Receipts needs (`price_series`, `verdict_for`, `excess_return`, `entry_day_after`,
   `exit_day_for`, `wilson_interval`, `Series`) rather than reimplementing them — `record.py`'s
   docstring explains why a second Wilson interval is the fastest way to lose this product's only
   asset.
5. **Before deleting `presentation.py`:** `receipt_card_svg` has to go somewhere or the share card
   route dies.
6. **After any deletion:** `make test` (108 Receipts tests must pass), then
   `cli verify-chain convergence-v3` and `convergence-v4` — 323 and 150 links must come back intact.

## 5. The one-command health check

```bash
make test                                                            # 108 receipts tests
docker compose exec -T api python -m tradeos.cli verify-chain convergence-v3   # 323 links
docker compose exec -T api python -m tradeos.cli verify-chain convergence-v4   # 150 links
curl -s localhost:8000/api/board | head -c 200                        # the landing route
curl -s localhost:8000/api/card/receipt/convergence-v3.svg | head -c 80  # the route-layer dep
```
