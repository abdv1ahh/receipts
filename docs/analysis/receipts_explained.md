# What Receipts is — for someone who has forgotten building it

**Written 2026-09-11.** Describes branch `receipts` at `9c6aafa`, **9 commits ahead of `main`,
unmerged**. Everything here was read out of the code and verified against the live database this
morning. Where a claim could be tested, it was tested — the integrity guarantees below are not
quoted from comments, they were provoked and observed.

If you read one paragraph, read this one:

> Receipts is a **public scoreboard for market predictions**. Someone says "NVDA goes up over the
> next 30 days" *before* it happens. That statement goes into a database table that **physically
> cannot be edited or deleted afterwards** — not by them, not by the app, not by you at 2am in
> `psql`. When the 30 days are up, the system looks up the real prices, compares the move against
> the S&P 500, and records whether they were right. Anyone can press **Verify chain** and watch
> every hash recompute in front of them. The first two records on the board are **ours**, and they
> are bad: **43.2% right — worse than a coin flip.** That is deliberate.

---

## 1. The nine commits

All nine landed on **2026-09-02**. This was built, reviewed and corrected in one day.

| # | Commit | Date | In plain English |
|---|---|---|---|
| 1 | `cb354e3` | 2026-09-02 | Laid the foundation — repaired the broken backup script, added missing sources to the registry, then created the three tables and the hash-chain code |
| 2 | `919237a` | 2026-09-02 | Added the web API, the background job that scores calls when their window closes, and imported our own engine's 473 historical calls as the first two records |
| 3 | `76f26a9` | 2026-09-02 | Built the five screens people actually look at, and rewired the sidebar so Receipts is the first thing you see |
| 4 | `88a3a8d` | 2026-09-02 | Ran a security review and a simplification pass over all of the above, and fixed what they found |
| 5 | `cdce648` | 2026-09-02 | Rewrote the docs to describe what had actually shipped rather than what was planned |
| 6 | `eb5de7b` | 2026-09-02 | Fixed an honesty bug — the Ledger was publishing one subsystem's accuracy under a heading implying it belonged to another. Also wrote the demo runbook |
| 7 | `acc2311` | 2026-09-02 | **The critical one.** A code review found the database sealed the *verdict* but not the *nine numbers the verdict is computed from*, so `UPDATE calls SET excess_return = 0.42` worked and every hash still verified. Migration 035 closed it. Also stopped the system permanently branding a call "unscoreable" merely because our price feed was running late |
| 8 | `e3ac441` | 2026-09-02 | Recorded migration 035 in `CLAUDE.md` and corrected the note it replaced |
| 9 | `9c6aafa` | 2026-09-02 | Fixed a test that silently did nothing because it tried to clean up inside an already-failed transaction |

**Notice the shape.** Commits 1–3 build it. Commits 4–9 are all *someone checking it and finding it
wrong*. Commit 7 caught a hole that would have quietly voided the entire value proposition.

---

## 2. The three tables, column by column

From `tradeos/migrations/034_receipts.sql`, amended by `035_receipts_seal_the_measurement.sql`.

### `callers` — who is making predictions

A **caller is a named record-holder, not a user account.** That distinction is load-bearing: a
record must not die when someone deletes their login.

| Column | What it holds |
|---|---|
| `id` | auto-number |
| `user_id` | the login this belongs to — **nullable**, `ON DELETE SET NULL`. Our two algorithm callers have no login at all, and a human closing their account must not drag a published record out with them |
| `handle` | the URL name, unique — `convergence-v3` → `/r/convergence-v3` |
| `display_name` | the name shown on the page |
| `bio` | free text |
| `kind` | `'human'` or `'algorithm'`. Not decoration — a reader is entitled to know whether they are reading a person's judgement or a scoring function's output |
| `is_house` | true if it is one of ours |
| `audience_url` | where their audience already lives |
| `verified_at` | when we confirmed they control that audience |
| `verification_method` | `public_post`, `meta_tag`, `wallet_signature`, or `house` |
| `verification_evidence_url` | the link they offered as proof |
| `jurisdiction_attested` | they confirm their own regulatory status is their own responsibility. A caller **cannot be created without it** — it is a column, not a paragraph in a terms page |
| `created_at` | timestamp |

Migration 035 added `callers_one_per_user_idx`, a **partial unique index on `user_id`**, because two
fast clicks could previously create two caller rows for one person and the app would then pick
whichever one the planner returned.

### `calls` — the predictions

The table splits in two, and the split *is* the design.

**Part A — the commitment. Written once at publish. Never changeable.**

| Column | What it holds |
|---|---|
| `id` | auto-number |
| `caller_id` | who said it |
| `seq` | their 1st, 2nd, 3rd… call — position in *their* chain |
| `symbol` | the ticker |
| `direction` | `'up'` or `'down'` — nothing vaguer is accepted |
| `horizon_days` | `7`, `30` or `90`, **only those three**. Free-choice windows would make callers incomparable, and comparison is the point of a board |
| `confidence` | `'low'`, `'medium'`, `'high'` |
| `thesis` | their written reasoning |
| `benchmark_symbol` | what to measure against, default `'SPY'` |
| `published_at` | when they said it |
| `knowable_time` | the same instant, stored under the name the rest of the codebase uses for "the first moment this could have been acted on", so a call obeys the same point-in-time discipline as an SEC filing |
| `prev_hash` | fingerprint of their previous call |
| `content_hash` | this call's own fingerprint |
| `context_snapshot` | **what the system itself was showing about this symbol at that moment** — which interpretations were live, whether any pointed the other way. Frozen so it cannot be reconstructed flatteringly later |

**Part B — the measurement. Empty at publish. Written once by the scorer.**

`entry_session`, `exit_session` · `entry_price`, `exit_price` · `benchmark_entry`, `benchmark_exit`
· `subject_return`, `benchmark_return`, `excess_return` · `verdict` (`hit` / `miss` /
`inconclusive` / `unscoreable`) · `verdict_note` · `resolved_at`.

### `caller_verifications` — proving they are who they claim

| Column | What it holds |
|---|---|
| `id`, `caller_id` | which caller |
| `code` | a one-time code we issue |
| `method` | `public_post` or `meta_tag` |
| `evidence_url` | where they published the code |
| `status` | `pending` → `confirmed` or `rejected` |
| `created_at`, `resolved_at` | timestamps |

**What is being verified is narrower than it sounds.** Not *"who is this person"* — that would mean
holding passports. Only *"is whoever publishes here the same party who publishes at that
newsletter"*. They post our code somewhere only they can post, paste the URL back, a human looks.
Free, no third-party API.

Deliberately, **the server never fetches the evidence URL**. Doing so would turn the endpoint into a
request-forwarder aimed at any address a stranger names — server-side request forgery. If automated
fetching is ever added it must call the existing `radar.webhook_target_ok`, not grow a second copy.

### The trigger — verified live, not quoted

`calls_append_only_trg` lives in **Postgres, not Python**, so it binds every connection including a
future admin tool and including you in `psql`. I provoked all five guarantees inside a transaction
and rolled back:

| Attempt | Database response |
|---|---|
| `DELETE FROM calls …` | ❌ `calls rows are append only and cannot be deleted` |
| `UPDATE calls SET thesis='edited'` | ❌ `sealed columns on calls are immutable` |
| `UPDATE calls SET verdict='hit'` on a resolved miss | ❌ `a resolved call is immutable, including the figures it was scored on` |
| `UPDATE calls SET excess_return=0.42` on a resolved call | ❌ `a resolved call is immutable, including the figures it was scored on` |
| `DELETE FROM callers WHERE id=107` | ❌ foreign key `calls_caller_id_fkey` refuses it |

The fourth row is the one migration 035 added. Before it, that statement **succeeded** and every
hash still verified, because `excess_return` is not a sealed field.

MD5 across all 473 `content_hash` values was identical before and after: `9849b828…`. Nothing changed.

---

## 3. What it does, from a user's point of view

Backend: `tradeos/receipts/` — seven files, 1,417 lines.

| File | Job |
|---|---|
| `chain.py` | the hash chain. **Pure** — no database, no clock, no randomness, so a sceptic can reimplement it from published fields alone |
| `calls.py` | publishing: validate, decide whether it can ever be scored, seal, insert |
| `scoring.py` | resolving a call against real prices when its horizon closes |
| `record.py` | composing the public record: counts, intervals, calibration, the board |
| `verification.py` | proving a caller controls their audience |
| `context.py` | freezing what the system was showing at publish time — an **adapter** over `journal_context`, not a second implementation |
| `seed.py` | importing our own two records |

### The screens

| Route | What you see |
|---|---|
| **`/board`** | **The landing page.** Every public record, ranked. First thing anyone sees |
| `/record` | One caller's full record — every call, **misses first**, the interval, the calibration table, and the **Verify chain** button |
| `/publish` | The form for writing a new call. Tells you *before you commit* whether the symbol can be scored |
| `/call` | One call in detail with the full proof panel — entry price, exit price, SPY's move, the arithmetic |
| `/methodology` | How scoring works, including what the chain does **not** prove |
| **`/r/{handle}`** | The **public share page** — server-rendered with Open Graph tags so a link previews in a feed. No login |
| `/api/card/receipt/{handle}.svg` | An image of someone's record, for embedding |

Fifteen API endpoints back these. Three CLI commands were added: `seed-house-records`,
`resolve-calls`, `verify-chain`.

### Three rules that shape what a user actually experiences

**The sample gate.** Below **25** resolved scoreable calls, **no percentage is shown at all** — the
page shows counts and the words "Low N". A rate on nine calls is not a weaker version of a rate on
nine hundred, it is a different kind of statement. It is not a hiding place: a gated caller still
shows every call and every miss. Only the one derived number is withheld.

**The noise floor.** A call that said "up" and beat SPY by 0.4% predicted nothing. Anything inside
**±2%** resolves `inconclusive`, and inconclusive appears in the counts rather than quietly leaving
the denominator.

**Entry is the next session, never today's close.** A call published at 3pm cannot enter at that
day's close, because by 3pm most of that close has already happened.

And one that exists only because of commit 7: **a call our price feed is merely behind on publishes
OPEN with a visible warning, not `unscoreable`.** Since a verdict is permanent, branding a call
unscoreable at 10am because the feed was late could never be undone at 11am when it caught up. Only
a symbol with no price series at all is sealed unscoreable at publish.

---

## 4. The two hash chains

### What is chained

Each caller has **their own** chain. That is why there are two — 323 links and 150 links — not one
chain of 473.

Ten fields are serialised per call in a **frozen order**: `caller_id`, `seq`, `symbol`, `direction`,
`horizon_days`, `confidence`, `thesis`, `benchmark_symbol`, `published_at`, `knowable_time`. Then:

```
content_hash = sha256( prev_hash + payload )
```

The previous hash goes **first, inside the hashed input**, which is what makes every link depend on
every link before it. The first call chains from `GENESIS_HASH` — 64 zeros — which turns "this is
the first thing they ever published" into a checkable statement rather than an assertion.

Each field is written `name:byte-length:value`, **length-prefixed rather than delimited.** A thesis
is free text a caller writes; with a plain separator they could type the separator into their own
thesis and make two different calls serialise identically — a hash collision they control, therefore
a forged link. A length prefix removes the ambiguity instead of trying to escape it. (This codebase
already learned once that `str.replace` cannot sanitise a delimiter — see the prompt fence in
`claims.py`.)

**This payload is a wire format and its field order is frozen forever.** Adding a sealed field,
reordering two, or changing how a timestamp renders would invalidate every chain ever published.

### What it proves — and what it does not

**Against the caller: tamper-evident.** They can publish, and nothing else. They cannot edit, delete,
reorder or backdate. Any attempt breaks every hash from that point on, and `verify_chain` reports the
**first** broken link — the actual edit, not the hundred consequences downstream of it.

**Against us, the operator: it proves nothing.** We hold every field, so we could rewrite a call and
recompute the whole chain from there. Closing that needs an **external anchor** — publishing the
chain head daily somewhere we cannot revise. **That is not built.** The methodology page says so in
those words. It is not a blockchain and must never be described as one.

### What breaks it

Editing any sealed field · deleting a call · reordering two · a gap or duplicate in `seq` — checked
explicitly, because otherwise removing a call and renumbering nothing would leave the remaining
hashes self-consistent, and deletion is exactly what this exists to catch.

Verified live 2026-09-11: `convergence-v3` **323/323 intact**, head `c9f480e0a79a28c73f14…`;
`convergence-v4` **150/150 intact**, head `24df0daed4f23ccde198…`.

### Why "no second copy by design"

An ordinary database row can be restored from backup because a restored copy is *as good as* the
original. **A chain link is not.** Its value is the claim *"this exact text was committed to at this
exact instant, before the outcome was known, and has not moved since."* That rests on the record
being continuous and unbroken. A gap in it is not an inconvenience — it is the failure of the only
thing the product sells.

There is no replica, no streaming copy to another host, no external anchor. **The single
authoritative copy is the `calls` table on this laptop's Docker volume.** The trigger protects it
against being *edited*. Nothing protects it against the disk dying. That is why Part 0 ranked the
backup gap as critical, and why a backup was taken before this document was written.

---

## 5. The data

Measured live, 2026-09-11:

| Caller | `caller_id` | kind | calls | hit | miss | inconclusive |
|---|---:|---|---:|---:|---:|---:|
| `@convergence-v3` | 107 | algorithm | **323** | 115 | 167 | 41 |
| `@convergence-v4` | 108 | algorithm | **150** | 63 | 67 | 20 |
| **total** | | | **473** | **178** | **234** | **61** |

**Human callers: 0.** `caller_verifications`: 0 rows. Everything on the board is ours.

Pooled, that is **43.2% right on the 412 that resolved hit-or-miss** — below a coin flip. The
expectancy interval spans zero, so on this sample **no edge is demonstrated in either direction**.
It would take 1,268 resolved calls to detect a 1%-per-call edge; there are 412.

### Where the 473 came from

**Nothing was invented.** `seed.py` reads the signal engine's own already-scored claims:

```sql
SELECT c.id, c.created_at, c.mechanism, c.confidence, c.horizon_days,
       o.subject, o.predicted, o.verdict, o.excess_return, o.entry_day, o.exit_day, o.note
  FROM claims c JOIN claim_outcomes o ON o.claim_id = c.id
 WHERE c.model_version = %s
 ORDER BY c.created_at, c.id
```

Real `created_at` becomes `published_at`. Real verdicts from `claim_outcomes`. Sealed in true
chronological order.

### Regenerable from `claim_outcomes`? — **Yes as a record. No as the same chain.**

I confirmed the source rows still exist and still match exactly:

| `claims.model_version` | resolved claims available | calls on the board |
|---|---:|---:|
| `convergence-v3` | **323** | 323 |
| `convergence-v4` | **150** | 150 |
| `gemini-flash-latest` | 273 | — not imported; that is the impact engine, which has no resolved calls |

So `cli seed-house-records` against a database holding `claims` and `claim_outcomes` would rebuild
both records with the same symbols, directions, verdicts, dates and counts. Ordering is
`(created_at, id)` — a deliberate total order, because many claims share a timestamp to the second
and a chain built on a non-deterministic order would verify today and fail after the next import.
The command is **idempotent by refusal**: a caller who already holds calls is skipped entirely,
because appending a second copy of 323 calls is precisely the quiet corruption this exists to prevent.

**But the hashes would differ, and here is the concrete reason.** `caller_id` is one of the ten
sealed fields. The two callers hold ids **107 and 108** — not 1 and 2, because the `bigserial`
sequence had already advanced. A regenerated pair would almost certainly get different ids, and all
473 `content_hash` values would change with them. The new chain would be internally valid and would
verify perfectly — but **any chain head published or screenshotted from today's data would no longer
match**. The record survives regeneration; its fingerprints do not.

That is the difference between "we can rebuild the numbers" and "we can prove we never touched
them", and the second is what the product sells.

---

## 6. Bolted-on feature, or separate product? — **A separate product sharing a house.**

**It is a separate product that lives in the same repository.** The evidence, not the impression:

- **It measures a different kind of thing.** Every other table records an *observation* — a filing
  arrived, a price moved, a model wrote a sentence. `calls` is the first table holding a *commitment*.
- **Its user is a different person.** The rest of TradeOS serves a trader reading their own feed.
  Receipts serves a **publisher** building public reputation and a **stranger** deciding whether to
  trust them. A `caller` is explicitly not a `user`.
- **Its surfaces are public.** `/board`, `/r/{handle}` and the SVG card need no login. The rest of
  the app is entirely behind auth.
- **It took the front door.** `/board` is the landing route; older surfaces moved into a "More" menu.

But it is **not standalone today.** It genuinely depends on `ledger.price_series` and
`backtest.engine` for arithmetic, `prices_eod` for prices, `journal_context` for frozen context, the
`users` table, the session/auth stack, the scheduler and the React shell.

Those dependencies are deliberate. `record.py` says reusing `ledger`'s statistics rather than
rewriting them "is not tidiness; this product's only asset is that its numbers are the same numbers
everywhere, and the fastest way to lose that is a second Wilson interval."

**Practical read: Receipts could be extracted, but only by taking the price pipeline and the scoring
maths with it.** The chain, the tables, the trigger and the surfaces are separable. The thing that
makes a verdict trustworthy is not.

---

## 7. Does it depend on the LLM claim engine? — **No. Completely independent.**

```
$ grep -rn "import llm\|from ..llm\|llm\.\|gemini\|openai\|explain\." tradeos/receipts/
  (zero matches)
```

**Not one reference.** No import of `llm`, no import of the `claims` module, no model call anywhere
in the package. Its entire import surface is `psycopg`, `hashlib`, `secrets`, `decimal`, `datetime`,
and four internal modules — `ledger`, `backtest.engine`, `journal_context` and its own siblings —
none of which call a model.

Everything Receipts does is deterministic: SHA-256, price arithmetic, a Wilson interval, a comparison
against SPY.

**This is the most valuable structural fact on the branch.** The known-broken thing in this
repository is the model chain: the `openai` slot has answered HTTP 410 since 2026-07-30 and Gemini is
a single point of failure at its free-tier ceiling. **None of that can touch Receipts.** If every
model key were revoked tomorrow, the board, the chains, the scoring and the verification would keep
working exactly as they do now.

The one place the planes touch is historical, not operational: `seed.py` read `claims` and
`claim_outcomes` **once**, as rows already sitting in tables. It called no model to do it, and it
will not run again — it refuses to re-import.

---

## 8. Is it safe to merge into `main` right now?

**Yes on all three questions**, with two things to decide first that are not merge blockers.

**Does it conflict?** No — and it cannot.

```
merge-base main receipts  =  cd834f2  =  git rev-parse main
git rev-list --count receipts..main  →  0
git merge-tree --write-tree main receipts  →  exit 0, no conflicts
```

`main` is a **direct ancestor** of `receipts`. Nothing has landed on `main` since the branch point.
The merge is a **fast-forward** — conflicts are not merely absent, they are impossible.

**Does it pass tests?** Yes, verified 2026-09-11:

| Gate | Result |
|---|---|
| Full suite | **834 passed, 0 failed**, 1.63 s |
| Receipts + navigation alone | **108 passed, 0 failed**, 0.83 s |
| `ruff check tradeos tests` | **All checks passed** |

**Does it change anything `main` already relies on?** Yes, in nine pre-existing modules. I read each
one; none is a silent behaviour change.

| Module | Change | Risk |
|---|---|---|
| `ledger.py` | `_series` renamed to `price_series`, made public so both planes load prices through one definition | **None.** Pure rename, all call sites updated |
| `news.py` | `ranked_news_window` added — falls back to most recent rows when a fixed window is empty, and says how old they are | **Improvement.** Fixes "empty over a weekend while holding 3,690 items" |
| `presentation.py` | new `receipt_card_svg`; existing `score_card_svg` takes `brand` as a parameter instead of a welded-in literal | **Low.** Additive plus a rebrand fix |
| `backtest/engine.py`, `ratelimit.py`, `llm.py`, `config.py` | additive only — `wilson_interval` export, a new rate-limit bucket, four `*_configured()` helpers | **None** |
| `billing.py`, `intelligence/analyst.py` | small edits from the review passes | **Low** |
| `app.py` | +422 lines: 15 routes, new public prefixes | **Additive** |
| `scheduler.py` | one new job, `_job_resolve_calls` | **Additive.** Only runs when the worker runs |

Migrations 034 and 035 create new tables and alter nothing existing.

### Two decisions to take around the merge

1. **034 and 035 are already applied here** (2026-09-02, 02:33 and 08:32 UTC). Merging changes no
   schema on this machine. But **any environment restoring a pre-2026-09-02 dump must run
   `cli migrate`**, because those dumps predate both migrations.
2. **The branch carries three large documents that may not belong in `main`** —
   `TRADEOS_AUDIT.md` (3,043 lines), `RECEIPTS_CLAUDE_CODE_PROMPT.md` (630) and
   `EXPOSURE_FEASIBILITY.md` (648): **4,321 of the branch's 10,544 added lines — 41%, none of it
   code.** Worth a decision before merging, not after. A judgement call for you, not a defect.

---

## The short version

Receipts is a public, permanent scoreboard for market predictions where the database itself refuses
to let anyone edit or delete a call once made, and anyone can recompute every hash to check. It is
**functionally complete, fully tested, lint-clean, and merges into `main` as a fast-forward with zero
conflicts.** It has **no dependency on the LLM**, which is the one broken subsystem in this
repository. Its two chains are intact, its 473 calls are real imports from the signal engine's own
scored history, and its headline number is **43.2% — deliberately unflattering, and it must never be
presented as a positive result.** The one thing genuinely at risk is the data: a sealed chain has
exactly one copy.
