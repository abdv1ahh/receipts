# Release readiness — what was done, what was found, what is left

Written 2026-09-23, after executing sections A, B, C, E, F, G, H and J of `docs/release_plan.md`.
Eleven commits on `receipts-caller-path`, `e5aafbe..ca32c5e`, pushed to the private remote.

The repository is still **private**. No history has been rewritten, no repository created, no
visibility changed. Section K is specified and not executed.

Every number here was measured on this machine today, not estimated. Where the plan and reality
disagreed, reality is recorded and the plan is quoted.

---

## Job 1 — the starting state

| check | result |
|---|---|
| Repository private | ✓ `abdv1ahh/tradeos`, `PRIVATE` |
| `research_platform` → `845d689` | ✓ annotated tag `05065ec`, peels to `845d689` |
| Tag pushed | ✓ present on `origin` |
| Full suite | ✓ 990 passed, 2 skipped |
| `make test-js` / `make lint` | ✓ both clean |
| Three chains | ✓ v3 323 / `c9f480e0a79a28c7`, v4 150 / `24df0daed4f23ccd`, a-real-stranger 1 / `79de970e41a46b35` |
| **Working tree clean** | **✗ — 4 modified, 1 untracked** |

The tree was not clean: five files of week-old `.docx` rendering work under
`docs/research/2026-09-14/`, a directory §K.1 removes from every commit. Reported and stashed on the
owner's instruction as `stash@{0}`; nothing was discarded. §K.3 now notes that a `git clone` does
not carry stashes, so it cannot reach the rewritten repository.

---

## Job 2 — no raw prices on any screen

**Every place a vendor price reached a screen, and what it is now:**

| # | site | reach | what leaked | now |
|---|---|---|---|---|
| 1 | `GET /api/calls/{id}` → `calls._row()` | **public** | `entry_price`, `exit_price`, `benchmark_entry`, `benchmark_exit`, `subject_return`, `benchmark_return` | not SELECTed at all |
| 2 | `calldetail.jsx` proof panel | **public page** | rendered all six | sessions + excess + noise floor |
| 3 | `GET /api/calls/preview` | signed in | `last_close`, `benchmark_last_close`, live from `prices_eod` | `last_session` dates only |
| 4 | `publish.jsx` commitment panel | signed in | "last close we hold", "SPY at that close" | "our data runs through \<date\>" |
| 5 | `GET /api/asset/{symbol}` | **public** | 130 raw daily closes | days only (route later deleted) |

**Checked and cleared:** `receipts/page.py`, `card.py` (PNG and SVG), `record.py`,
`verification.py`, `/api/receipts/{handle}/chain` (no price is a sealed field), `/api/board`,
`/api/receipts/{handle}` (`_SUMMARY_FIELDS` already excluded them), `/api/card/{symbol}.svg`,
`/s/{symbol}`.

**Not vendor data:** `/api/trades/*` and `/api/community/feed` carried `entry_price` — numbers a
user typed into their own journal. Both surfaces were deleted in Job 3 regardless.
`/api/portfolios/{pid}` returned `prices_eod`-derived figures for a user's own paper positions; it
was listed rather than patched, because it was in the deletion set.

**The enforcement is the SELECT, not a filter.** `calls._LIST_COLUMNS` does not load the six
columns. A filter at the route has the same hole one route later, and the leak this closes was
never a field anybody chose to print — `/api/calls/{id}` returned the whole row and the prices came
with it, invisibly, NULL on all 474 sealed rows, waiting for the first resolution to start
publishing them.

**The columns are kept.** They are the audit trail, migration 035 seals them, and a verdict nobody
can see the components of is a verdict the operator cannot answer a challenge to.
`test_the_stored_arithmetic_reconciles` checks them in the database;
`test_the_components_that_arithmetic_used_never_reach_the_payload` checks they never leave it.

**One reason, in one place.** `receipts.record.NO_PRICES` and `RECOMPUTE_NOTE`, quoted by the
methodology page, the call detail, the server-rendered `/r/{handle}`, the publish screen and
`docs/known_gaps.md` §6. No surface writes its own.

**The guard.** `tests/test_price_redistribution.py` plants six-decimal prices on a resolved call and
a scratch symbol in `prices_eod`, renders **every route the app serves** — anonymous and signed in —
and fails on any planted value or price column name in the bytes. It failed on the parent commit
with 19 findings and passes now. A sweep rather than six assertions, because a test naming the six
fields it knows about would have passed throughout the leak.

**Item 6 — the @a-real-stranger ABT call: it has NOT resolved.** Call `4099`, ABT up 7 days,
published 2026-09-15. Its four price columns are NULL, as are all 474 rows in `calls` — nothing is
exposed. Both entry (2026-09-16) and exit (2026-09-22) sessions exist for ABT and SPY, so the next
scheduler pass will resolve it. It was not forced: a verdict is permanent and that is the owner's
call to make.

**And the reason it had not resolved is a defect found while auditing, which is the more serious
of the two findings.** `test_resolve_due_counts_no_ops_separately` called `scoring.resolve_due(conn)`
**unscoped**, against the live database, with `_series` monkeypatched to a fixture. It therefore
picked up every other open past-horizon call in the table — including that real, public ABT call —
and rewrote its public *"why is this still open"* sentence from prices that do not exist. On the
live board it read *"its newest close is 2026-08-14"* while ABT's actual series ran to 2026-09-22.

Nothing sealed was touched; `_stay_open` writes only disclosure columns. But the same batch reaches
`_write`, and under a fixture series spanning the horizon it would have sealed a **permanent
verdict on a stranger's public call from invented prices**. `resolve_due` now takes an optional
`caller_id`; production passes nothing and is unchanged; a second test asserts a scoped batch leaves
every other row's verdict and `open_checked_at` exactly as it found them.

---

## Job 3 — delete everything that is not Receipts

| | before (`research_platform`) | after | plan's target |
|---|---:|---:|---:|
| Python modules | 98 | **31** | 21 |
| Python lines (`tradeos/`) | 23,727 | **7,302** | ~5,500 |
| `app.py` lines / routes | 3,852 / 146 | **1,108 / 32** | ~700 / 33 |
| Frontend files / lines | 43 / 11,602 | **16 / 4,805** | ~15 / ~2,400 |
| Bundle, gzipped | 123.4 KB JS + 24.6 KB CSS | **62.0 KB JS + 24.6 KB CSS** | ~45 KB + ~12 KB |
| Migrations | 37 ordered | **1 baseline** (+37 kept) | 1 baseline |
| Tables on a fresh install | 64 | **19** | ~14 |
| Tests | 997 | **390** (+2 skipped) | ~450 |
| CLI commands | 44 | **12** | 11 |
| Scheduler jobs | 21 | **2** | 2 |
| Source catalog entries | 22 | **4** | — |
| Keys needed to run | `SEC_USER_AGENT` + 6 optional | **2** (one Alpaca pair) | 2 |
| Tracked files | 379 | **227** | — |

**Three targets missed, and why.** 31 modules not 21: the plan's count predated `stats.py` and
`prices.py` and omitted `apikeys`, `flags`, `mail`, `ratelimit`, `oauth`, `sources` and `scheduler`
from its tally. 19 tables not 14: authentication genuinely needs `auth_tokens`, `login_attempts`,
`audit_log`, `invites`, `subscriptions` and the two `oauth_*` tables. And **the CSS is unchanged at
24.6 KB gzipped** — `styles.css` still carries rules for 26 deleted surfaces. That is dead weight
rather than a defect, and pruning 137 KB of CSS by hand is a separate job with real regression risk.

**§A.4's app.py split was not done.** The plan proposed `tradeos/routes/receipts.py`. `app.py` came
out at 1,108 lines, which is under the size the split was meant to solve, so splitting it would
have been motion rather than work.

**One commit per area was not possible, and the reason is worth recording.** The first attempt
followed §B's order and does not work: `assistant.py` imports `trades`, `test_claims.py` imports
`explain.guards`, and `test_accounts.py` tests billing and onboarding and oauth in one file. Any
single-subsystem commit leaves the suite red. The subsystems are entangled through their tests and
cannot be severed one at a time, so the deletion is one commit whose message is organised by §B's
seven rows. "Run the full suite after each" was kept; the shape of the log was not.

**Every cut was bounded by the AST.** `cli.py` was broken twice in a previous session by deletions
that began on the right line and ended inside the next command's flags — which argparse accepts
silently. A definition ends where the next top-level statement begins, and the tool used refuses to
write a file that will not parse. `tests/test_cli_commands.py` now walks the built parser and
asserts exactly the expected commands are registered, that every one has an `fn` (`set_defaults` is
a separate statement from `add_parser`, so a cut between them leaves a command that parses and then
crashes), and that every one answers `--help`. It caught `export-records` the moment it was added.

**Nothing was dropped from the owner's database and NO PRODUCTION MIGRATION WAS APPLIED.** None was
needed: `db.run_migrations` gives an empty `schema_migrations` the baseline and everything else the
37 ordered files, and the owner's database has all 37 applied. It still holds 64 tables and 474
calls. The migration equivalence was proved on two **scratch** databases, created and dropped.

**Two things the baseline almost shipped broken.** `pg_dump -t table` emits `CREATE TRIGGER` and
**not** the function it calls: the raw dump contained three triggers and zero functions, and
Postgres accepts that until the first UPDATE — an append-only record whose append-only trigger does
not exist. And pg_dump's preamble sets `search_path` to `''`, so the closing
`INSERT INTO schema_migrations` resolved to nothing and the file failed at its last statement after
creating all 19 tables. Both found by running it. `tests/test_migrations.py` now migrates two
scratch databases and asserts the baselined one reports versions 1..37, carries all three trigger
functions, and **refuses** a verdict change, an `excess_return` change, a thesis change and a delete
on a sealed call.

**The schema diff is scoped to the 19 kept tables, and the scope is a correction to the plan.** §C
says to diff the two databases whole and expect them identical. They are 19 tables against 64, by
design. What must match is every table Receipts touches — measured at **739 lines of DDL each, byte
for byte**.

**Backups: 18 dumps, 81 GB, none deleted.** `scripts/backup.sh` defaulted to `./backups`, inside the
working tree. It now defaults to `$XDG_DATA_HOME/receipts/backups`. Nothing is migrated and no dump
is removed — the existing 81 GB stays exactly where it is; only the next one is written elsewhere.
Both the retention sweep and the restore path glob the old `rhumb-*` prefix as well as the new
`receipts-*`, so a name change cannot orphan 81 GB of backups.

**And the suite went green by not running.** `test_receipts_api.py` still imported `presentation`
after it was deleted, and its `try/except _IMPORTS_OK = False` guard turned 38 assertions covering
the public HTTP boundary into skips while the run said *"354 passed"*.
`tests/test_suite_integrity.py` closes it: where the database IS reachable, no module may report
that flag false, and it re-runs the guarded block to name the failure rather than leaving a flag.

---

## Job 4 — the public files

**The name is Receipts** on the public page, the share card, every page title and the README.
`tradeos` remains the package, the tables and the container names: renaming them would mean
renaming tables, and `schema_migrations` and the append-only triggers are matched **by name**.

**README.md** — one sentence, screenshots at 375px and 1280px captured from the running instance
(no prices, no personal data, the miss count larger than the hit count), a quickstart, what a caller
does, what a visitor can verify, what it does not guarantee in the page's own words, the house
record stated as bad and as a sealed backtest, an Engineering section, and the research link.

**LICENSE** (MIT), **SECURITY.md**, **CONTRIBUTING.md**, and the "nothing here is investment advice"
statement in the README footer, the LICENSE, SECURITY.md and CONTRIBUTING.md.

**docs/research/insider_buying.md** — what was tested, the window (2024-07-02 to 2026-08-12), the
method, the result (−3.40% at 90 days, [−5.40%, −1.40%], n=442), the one positive cut and three
independent reasons not to believe it, six reasons it may differ from decades of published
literature, and the commands to reproduce it from the tag — **including the module hash
`ea6b6a98227b95b4`**, because different scoring source means the numbers do not apply. It states
plainly that it does not claim insider buying fails in general.

**The export.** `cli export-records` writes both house chains plus `check.mjs` plus
`receipts/verify.js` **itself, copied verbatim** — not a port, because a frozen wire format with two
implementations already needs a cross-language test and a third would be a liability. `MANIFEST.json`
carries the sha256 of every file including the verifier. `make test-js` runs it, so a broken export
cannot be committed:

```
ok    convergence-v3: 323 links in 8 ms, head c9f480e0a79a28c7  [SEALED BACKTEST - see README]
ok    convergence-v4: 150 links in 3 ms, head 24df0daed4f23ccd  [SEALED BACKTEST - see README]
ok    and it says no when it should: the stored hash does not match the call's own contents at call #1
```

That third line is the checker tampering with one byte of its own input and confirming it notices.

**The 473 house calls are labelled a sealed backtest in four places**: the export's README,
`MANIFEST.json`'s per-file `sealed_after_the_outcome_was_known`, `check.mjs`'s own output, and the
project README.

**Every claim checked against the code, not remembered**: ten sealed fields in the frozen order,
`FRAMING` read from `chain.py`, noise floor `0.02`, sample gate `25`, horizons `(7, 30, 90)`,
`requirements.txt` ten lines, zero inline scripts and exactly one internal link on `/r/{handle}`,
961 day-pairs and 0.391% and the 2.86% thin-name tail, 13,170 symbols. And the house numbers read
live from `/api/board`: 43.2% of 412, expectancy −1.18%, interval [−2.93%, +0.57%], z = −2.76,
1,268 calls needed to detect a 1% edge.

**One thing not done.** §A.3 lists `admin.jsx` as kept, "verification queue only". There was no
verification queue in the frontend — `admin.jsx` was the moderation, users, flags and audit
dashboard, and its five routes went with the community plane. The two verification routes are kept,
admin-only and tested; nothing calls them. That is `docs/known_gaps.md` §2, which already recorded
it, and it stays a documented gap rather than a rail item leading to an empty page.

---

## Job 5 — the ten-minute test

**2.7 minutes** from `git clone` to a published call, on the clean re-run. Full transcript below.

```
1. git clone                                                    instant
   [local only: ports 8001/5433, project receipts-tenmin, because this machine
    already runs the owner's instance on 8000/5432. A stranger needs neither.]
2. ./scripts/setup.sh                                           instant
   -> "Wrote .env with a generated database password (not shown)."
3. paste the Alpaca key pair into .env                          instant
   [a stranger also spends ~3 min at app.alpaca.markets/signup — free, no card]
4. make quickstart                                              84s
   -> 13,170 symbols, 12,933 with data, 265,451 rows, 132 batches, 0 rejected
   -> migrations applied: the BASELINE (19 tables on the fresh database)
5. register -> claim a handle -> publish a call, in the browser 11s
   -> @clean-run, NVDA up 30 days medium, sealed
   -> content hash c82901dffc24d2b9df4685a40abd05a901466bb9a26d16ff1ede9fcc26a4088b
   -> console: no errors, no warnings
```

Verified on the fresh instance afterwards: 19 tables, the public payload carries no price field,
the chain has 1 link and 10 sealed fields, `/r/clean-run` returns 200 and reads correctly for a
caller below the sample gate.

**Three things a stranger would have got stuck on, all fixed and re-run from a fresh clone:**

**1. The quickstart loaded the alphabet.** `--limit 400` over a year sorts by staleness, and on a
fresh database everything is equally stale, so it fell back to sorting by symbol: `A, AA, AAA,
AAAA, AAAC, AAAP, AAAU…`. Of twelve names a person actually reaches for, **ten were absent** —
MSFT, NVDA, TSLA, GOOGL, AMZN, META, QQQ, AMD, NFLX, JPM. A stranger's first call is on a company
they have heard of, and it could not be published. This is the old insider-signal universe defect
wearing a different hat.

The budget was not loosened, per the instruction. A call is scored on the sessions **after**
publication, so a fresh install needs the symbol to *exist* with a recent session, not a year of
history behind it. A month over everything replaced a year over 400: **13,170 symbols, 265,451
rows, 84 seconds**, and 13 of 14 household names scoreable afterwards. The fourteenth is `GEF-B`,
the documented class-share spelling case.

**2. The sign-in screen advertised a product that does not exist** — *"Free tier sees signals on a
48-hour delay; paid tiers see them live."* There are no tiers and no signals. It survived because
`views.jsx` was trimmed by lifting the `AuthPanel` whole, which preserves behaviour and does not
read copy.

**3. The browser tab read "Receipts · Receipts"** on every surface that is addressable but
deliberately off the rail — auth, claim, call, verify, reset — because `document.title` fell back
to the brand when `NAV_LABELS` had no entry.

**The test environment is gone**: containers, volumes, images and the clone all removed. The
owner's stack is untouched — three containers up, `tradeos_pgdata` and `tradeos_uploads` intact,
64 tables, 474 calls, three chains verifying.

---

## Final state

| | |
|---|---|
| Branch | `receipts-caller-path`, 11 commits, `e5aafbe..ca32c5e`, pushed |
| Repository | **private**, unchanged |
| `research_platform` | `845d689`, on `origin`, untouched |
| Working tree | clean |
| `make test` | **390 passed, 2 skipped** |
| `make lint` | **clean** |
| `make test-js` | **passes**, including `export/check.mjs` |
| Price guard | **4 passed** |
| Chains on the owner's instance | v3 323 / `c9f480e0a79a28c7` · v4 150 / `24df0daed4f23ccd` · a-real-stranger 1 / `79de970e41a46b35` — **byte-identical to Job 1** |
| Owner's database | 64 tables, 474 calls, nothing dropped, no migration applied |
| Backups | 18 dumps, 81 GB, none deleted |

**Sensitive-string sweep, every tracked file at HEAD:**

| string | hits |
|---|---:|
| the owner's email address | **0** |
| the GDELT operator's email address | **0** |
| the personal path | **0** |
| the previous demo password | **0** |

One related string remains and is not on that list: the development database password, once, in
`tests/test_sources.py` as a **negative assertion** — it reads `docker-compose.yml` and asserts a
connection string carrying the old default is *not* in it. The literal is the thing being
forbidden; removing it removes the check that keeps the default from coming back. It is in
`~/receipts_release/expressions.txt` anyway, and rewritten the assertion still passes and still
means the same thing.

**Still to do, and deliberately not done here:** section K, the history rewrite. It is specified in
`docs/release_plan.md` §K, it names no sensitive string, and its replacement expressions are in
`~/receipts_release/expressions.txt` (mode 600, outside the repository). The four strings above are
zero **at HEAD** and non-zero **in history**, which is the whole reason that section exists.

One decision is still the owner's and is called out in §K.6: whether to publish the
`research_platform` tag. `docs/research/insider_buying.md` tells a reader to check it out and
reproduce the result, so if the tag stays private that document has to say so plainly rather than
give commands nobody can run.

---

READY FOR PROMPT 2
