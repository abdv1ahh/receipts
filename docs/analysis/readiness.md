# Readiness report — 2026-09-09

**Diagnostic only. Nothing in this repository or database was changed.** No migration was run, no
worker was started, every database statement was a `SELECT`/`COUNT`, and the working tree is clean
(`git status --porcelain` → 0 files). The only writes anywhere were the container lifecycle
(`docker compose up -d db api`) and this file.

Measured by: bringing the stack up cold after ~7 days idle, probing every credential live from
**inside the `api` container**, querying the database read-only, and running the two gates.

**Branch note.** The task named `main`; the checked-out branch is **`receipts`**, 9 commits ahead
of `main` and unmerged (`main` is 0 commits ahead). Everything below describes `receipts` at
`9c6aafa`. This matters for anything that assumes `main` is current — the Receipts product, which
`CLAUDE.md` calls "the product", exists only on this branch.

---

## Verdict

| # | Area | Verdict |
|---|---|---|
| 1 | Stack bring-up | ✅ **Clean.** Both containers up in 3.94 s, no errors in either log |
| 2 | Credentials | ⚠️ **4 of 5 live.** SEC, Tiingo, OpenFIGI, Gemini all 200. OpenAI slot **HTTP 410, dead** |
| 3 | Database | ✅ **Intact.** 64 tables, 1,828,960 rows, 7.91 GB, migrations through 035 |
| 4 | Price coverage | ⚠️ **4 sessions behind.** 500 symbols; **0** have a bar at the latest session; SPY is stale |
| 5 | Tests | ✅ **834 passed, 0 failed, 1.59 s** |
| 6 | Lint | ✅ **All checks passed** (ruff 0.16.5) |
| 7 | Backups | 🔴 **Broken.** Failing 11 of the last 12 nights; **the Receipts tables have never been backed up** |

**The one thing to fix before anything else is item 7.** Everything else is either working or is a
known, documented, recoverable staleness. Item 7 is silent, ongoing data loss exposure on the
tables the product is built around.

---

## 1. Stack bring-up

Docker Desktop was **not running** when this session started — the daemon socket
(`unix://~/.docker/run/docker.sock`) did not exist. It was launched manually; the
daemon became available 12 s later. This is not incidental, it is the root cause of item 7.

```
$ docker compose up -d db api
```

| Container | Image | Result | Time |
|---|---|---|---|
| `tradeos-db-1` | `postgres:16` | ✅ started, healthy | PostgreSQL accepting connections **0.17 s** after container start; compose marked it healthy at **~3.6 s** (the healthcheck polls every 3 s, so this is the poll interval, not startup cost) |
| `tradeos-api-1` | `tradeos-api` | ✅ started, serving | recreated and started at **+3.67 s**, gated on the db healthcheck |
| **whole command** | | ✅ | **3.94 s** |
| `tradeos-worker-1` | | ⛔ **not started, as instructed** | still `Exited (137) 6 days ago` |

Measured separately with a forced cold recreate: **`/healthz` returned 200 in 0.55 s** from
container start.

Neither log contains an error:

```
api: Started server process [1] / Waiting for application startup. /
     Application startup complete. / Uvicorn running on http://0.0.0.0:8000
db:  database system was shut down at 2026-09-02 22:31:12 UTC
     database system is ready to accept connections
```

The api image runs `uvicorn` directly — there is no startup hook and no entrypoint migration
(`grep on_event|lifespan|startup|migrate tradeos/app.py` → no matches), so bringing the api up
cannot have applied a migration. `make test` and `make lint` both use `docker compose run --rm` on
the `api` service only; neither started the worker. Confirmed after every step:
`tradeos-worker-1 :: Exited (137) 6 days ago`, unchanged throughout.

---

## 2. Credentials

`.env` holds **10 variables, all present and all non-empty.** Probes were run **inside the `api`
container**, not on the host, which additionally proves each key actually reaches the running
process — the failure mode `CLAUDE.md` §0i warns about, where a key in `.env` alone is silently
absent from the container while host-side checks report "connected". All 10 arrived.

No key value is printed anywhere below; query strings are stripped from all captured output.

| Credential | Present | Probe | Status | Result |
|---|---|---|---|---|
| `SEC_USER_AGENT` | ✅ | `GET https://www.sec.gov/files/company_tickers.json` | **200** | ✅ 10,415 tickers, 797,199 bytes (2,030 ms) |
| `TIINGO_API_KEY` | ✅ | `GET api.tiingo.com/tiingo/daily/spy`, `Authorization: Token …`, `follow_redirects=False` | **200** | ✅ `ticker=SPY startDate=1993-01-29 endDate=2026-09-08` (864 ms) |
| `OPENFIGI_API_KEY` | ✅ | `POST api.openfigi.com/v3/mapping`, `X-OPENFIGI-APIKEY`, **11 jobs** | **200** | ✅ 11 jobs accepted, 11 mapped (2,570 ms) |
| ↳ *control: same 11 jobs, no key* | — | same request, header omitted | **413** | ✅ `"Request may only contain 10 mapping jobs."` |
| `GEMINI_API_KEY` | ✅ | `GET generativelanguage.googleapis.com/v1beta/models` | **200** | ✅ 50 models; both configured models present (1,073 ms) |
| `OPENAI_BASE_URL` + `_API_KEY` + `_MODEL` | ✅ | `POST https://models.github.ai/inference/chat/completions` | 🔴 **410** | ❌ `github_models_retirement_brownout` (823 ms) |

**The OpenFIGI control probe is the point of the 11-job batch.** OpenFIGI's mapping endpoint
answers keyless callers, so a plain success proves nothing (`CLAUDE.md` §0j). Eleven jobs is one
over the keyless cap: the keyless control got **413**, the keyed request got **200**. The key is
therefore genuinely present, genuinely transmitted, and genuinely honoured — not merely
"the endpoint replied".

**Tiingo's own SPY series runs to 2026-09-08.** The source is current; our copy is not (see item 4).

**The model chain has no working fallback.** `EXPLAIN_PROVIDER=gemini,openai`. Gemini answers, but
it is the only link that does, and `docs/state.md` records it running at the edge of its free daily
quota. The `openai` slot points at GitHub Models, which is in retirement brownout and returns 410
on every request. This is exactly the state `docs/state.md` §"The one thing that is blocked"
described on 2026-09-02 — **unchanged, still true, and still the documented one-line fix** (three
env vars pointing at a free Groq key, in both `.env` *and* `docker-compose.yml`).

---

## 3. Database state

| Metric | Value |
|---|---|
| Tables (`public`, base tables) | **64** |
| Total rows, all 64 tables | **1,828,960** (exact `COUNT(*)`, 440 ms) |
| Database size | **7,910,743,063 bytes — 7.91 GB** (7,544 MiB) |
| Migrations applied | **35 of 35**, newest `035` applied 2026-09-02 08:32:14 UTC |

Size is concentrated almost entirely in one table:

| Table | Total size | % of DB |
|---|---:|---:|
| `raw_filings` | 6,935 MB | **91.9%** |
| `insider_transactions` | 414 MB | 5.5% |
| `stake_events` | 48 MB | 0.6% |
| `prices_eod` | 46 MB | 0.6% |
| `signal_clusters` | 31 MB | 0.4% |
| everything else (59 tables) | — | ~1.0% |

### The nine requested tables

| Table | Rows | Newest event/business date | Newest `knowable_time` |
|---|---:|---|---|
| `insider_transactions` | **759,698** | `event_time` 2026-07-21 | 2026-07-22 01:25:58 UTC |
| `stake_events` | **135,925** | `event_time` 2026-07-21 | 2026-07-22 01:58:00 UTC |
| `fund_holdings` | **24,982** | `period_end` 2026-06-30 | 2026-07-21 21:20:05 UTC |
| `prices_eod` | **249,462** | `day` 2026-09-02 | — |
| `signal_clusters` | **17,669** | `as_of` 2026-07-27 01:13:41 UTC | — |
| `signal_outcomes` | **620** | `entry_day` 2026-07-20 | `computed_at` 2026-07-27 11:28:40 UTC |
| `entities` | **23,533** | `created_at` 2026-07-27 11:22:16 UTC | — |
| `security_map` | **13,170** | `valid_from` 2026-08-24 02:21:59 UTC | — |
| `claims` | **616** | `created_at` 2026-08-24 23:31:03 UTC | `resolved_at` 2026-08-20 23:32:44 UTC |

Both `event_time` and `knowable_time` are reported for the SEC tables because they mean different
things and the point-in-time discipline depends on the difference.

**Every SEC-derived table stopped on 2026-07-21/22.** That is expected — those tables only move
during a backfill, and none has run. `security_map` (2026-08-24) and `claims` (2026-08-24) are the
newest-touched tables; nothing anywhere has moved since **2026-09-02**, the day the worker last ran.

The Receipts chains still verify. Read-only via the public endpoint:

| Handle | Links | Checked | Intact |
|---|---:|---:|---|
| `convergence-v3` | 323 | 323 | ✅ `intact: true` |
| `convergence-v4` | 150 | 150 | ✅ `intact: true` |

---

## 4. Price coverage

| Metric | Value |
|---|---|
| Distinct symbols in `prices_eod` | **500** |
| Total bars | 249,462 |
| Oldest bar | 2021-06-01 |
| Newest bar, any symbol | **2026-09-02** |
| Symbols with a bar at the latest *real* session (2026-09-08) | **0** |

### Newest bar date per symbol

Grouped losslessly — every one of the 500 symbols is in exactly one row:

| Newest bar | Day | Symbols |
|---|---|---:|
| 2026-09-02 | Wed | 39 |
| 2026-09-01 | Tue | **379** |
| 2026-08-27 | Thu | 1 |
| 2026-08-26 | Wed | 2 |
| 2026-08-21 | Fri | **74** |
| 2026-08-11 | Tue | 1 |
| 2026-08-07 | Fri | 1 |
| 2026-07-24 | Fri | 1 |
| 2026-07-22 | Wed | 2 |

### Freshness — two different answers, and the difference is the finding

**Against the table's own calendar** (its 10 most recent distinct `day` values, cutoff 2026-08-20):
**495 of 500 (99.0%) fresh, 5 stale.** This is the flattering number and it is misleading, because
the table's own calendar is itself four sessions behind reality.

**Against the real trading calendar** — the last 10 NYSE sessions ending at Tiingo's own latest SPY
close, 2026-09-08, excluding Labor Day 2026-09-07 — cutoff **2026-08-25**:

| Measure | Symbols |
|---|---:|
| With a bar in the last 10 real sessions | **421** |
| Outside that window | **79** |
| **At the latest real session (2026-09-08)** | **0** |

Sessions missing entirely:

| Session | Symbols with a bar |
|---|---:|
| 2026-09-08 Tue | **0** |
| 2026-09-04 Fri | **0** |
| 2026-09-03 Thu | **0** |
| 2026-09-02 Wed | 39 |
| 2026-09-01 Tue | 418 |
| 2026-08-31 Mon | 418 |

**The feed stopped mid-pass, not at a boundary.** The 39 symbols that reached 2026-09-02 are a
contiguous alphabetical block ending at `PEB-PH` (`LWAY MAIA MBC … PCTTW PEB PEB-PH`), and the 79
stalest are the alphabetical tail (`PFX … YEXT`). That is the signature of a paced
`ingest-prices --only-stale` run walking the symbol table and being cut off — consistent with the
free-tier ceiling described in `CLAUDE.md` §0h (~57 unique symbols/hour) and with the worker having
been stopped on 2026-09-02.

**SPY — the benchmark — is the stalest of the current leaders**: 1,320 bars, newest **2026-09-01**,
a day behind the 39 symbols that reached 09-02. Per `CLAUDE.md` §0h a stale SPY makes every other
symbol unscoreable, and per §0z a missing exit price correctly leaves a call **open** rather than
sealing a wrong verdict. So this is degradation, not corruption — but it does mean call resolution
is currently stalled by design, and **SPY is what to fetch first** on any top-up.

The 79 symbols outside the real 10-session window:

```
BBBY GAMB MNTSW PFX PFXNZ PICS PLNT PLSE PODD POOL PPHC PRTA PSNY PSNYW QTRX QTTB RACC RAIN RAINW
REA RLYB ROCK RPAY RVSB RYAN SAGU SATA SATL SATLW SDEV SDHC SHAK SIMA SIMAU SIMAW SKIN SKYH SLMT
SRZN SRZNW SSP STI STRC STRD STRF STRK STRR STRRP STRZ STTK SWIM TKO TLSI TLSIW TMCI TNXP TPG TPGXL
TWFG TXO UA UAA UCAR USAR UUU UUUU VECA VIDA VITL VRDN VVV VVX WGS WGSWW WOK WRAP WW XPOF YEXT
```

Four of these look genuinely dead rather than merely behind — `WGSWW` and `GAMB` (2026-07-22),
`BBBY` (2026-07-24), `SRZNW` (2026-08-07), `MNTSW` (2026-08-11) — but that was not investigated,
because distinguishing "delisted" from "lagging" is exactly the judgement §0z says must not be made
casually.

---

## 5. Tests

```
$ make test
834 passed, 1 warning in 1.59s
```

| Metric | Value |
|---|---|
| Passed | **834** |
| Failed | **0** |
| Errors / skipped | **0** |
| Duration | **1.59 s** (pytest); 2.87 s wall including container creation |

Matches the 834 recorded in `CLAUDE.md` exactly — no test has been lost or silently skipped.

One warning, non-blocking:

```
StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated;
install `httpx2` instead.   (fastapi/testclient.py:1)
```

**Caveat on what this proves.** Per `CLAUDE.md` §0, the suite runs on the `template` provider by
design, so a green suite says nothing about whether the model path works. The live probes in item 2
are the answer to that question, and they say Gemini works and the fallback does not.

---

## 6. Lint

```
$ make lint      # docker compose run … ruff==0.16.5 → python -m ruff check tradeos tests
All checks passed!
```

**Zero findings**, which is the repository's stated standard. Ruff is pinned at 0.16.5 by the
`lint` target and runs against `tradeos` and `tests`, exactly as specified.

---

## 7. Backups — 🔴 the finding

`backups/` holds **13 `.dump` files and one log, 44 GB total.** Disk is not the constraint: 597 GB
free.

| File | Bytes | Modified (local, UTC+04) | Assessment |
|---|---:|---|---|
| `backup.log` | 4,427 | 2026-09-09 03:26 | the agent **is** still firing |
| `rhumb-20260820T232305Z.dump` | 4,794,949,429 | 2026-08-21 03:32 | ✅ good |
| `rhumb-20260823T165503Z.dump` | 4,795,314,311 | 2026-08-23 21:04 | ✅ good |
| `rhumb-20260823T215359Z.dump` | 4,795,396,757 | 2026-08-24 02:04 | ✅ good |
| `rhumb-20260824T214538Z.dump` | 4,795,921,759 | 2026-08-25 04:06 | ✅ good |
| `rhumb-20260825T220005Z.dump` | 4,796,001,577 | 2026-08-26 09:23 | ✅ good |
| `rhumb-20260826T215811Z.dump` | 4,796,173,163 | 2026-08-27 03:55 | ✅ good |
| `rhumb-20260827T214708Z.dump` | 4,796,390,494 | 2026-08-28 13:27 | ✅ good |
| `rhumb-20260828T215039Z.dump` | **4,309,987,328** | 2026-08-29 14:20 | 🔴 **truncated — 89.9% of its predecessor** |
| `rhumb-20260829T214709Z.dump` | **0** | 2026-08-30 01:47 | 🔴 empty |
| `rhumb-20260830T214505Z.dump` | **0** | 2026-08-31 01:45 | 🔴 empty |
| `rhumb-20260831T215157Z.dump` | **0** | 2026-09-01 01:51 | 🔴 empty |
| `rhumb-20260901T214505Z.dump` | 4,796,633,340 | 2026-09-02 01:54 | ✅ good |
| `rhumb-20260902T023149Z.dump` | 4,796,684,947 | 2026-09-02 06:41 | ✅ good — **and it is the newest** |

### 7a. The newest usable backup is 7 days old, and 11 of the last 12 nights failed

From `backups/backup.log`, every run since:

| Night | Outcome |
|---|---|
| 2026-08-28 | 🔴 killed mid-dump — **no completion line at all**, left a 4.31 GB truncated file |
| 2026-08-29 / 30 / 31 | 🔴 `failed to connect to the docker API` — left 0-byte files, **printed no failure line** |
| 2026-09-01 | ✅ wrote 4,796,633,340 bytes |
| 2026-09-02 (02:31) | ✅ wrote 4,796,684,947 bytes |
| 2026-09-02 (21:55) | 🔴 `FAILED: pg_dump exited 255 and left 4336484352 bytes` |
| 2026-09-03 → 09-08 | 🔴 all six: `failed to connect to the docker API` → `FAILED: pg_dump exited 1 and left 0 bytes` |

### 7b. Root cause: Docker Desktop is not running at 03:15

The launchd agent is **installed, loaded and firing correctly**:

```
$ launchctl list | grep rhumb
-    1    app.rhumb.backup          # loaded; last exit status 1
```

`~/Library/LaunchAgents/app.rhumb.backup.plist` fires at 03:15 daily, sets `PATH` explicitly to
reach the Docker CLI, and appends to `backups/backup.log`. All of that works — the log's newest
entry is `2026-09-09 03:26`, this morning.

**What fails is one layer below.** The plist fixed `PATH` so the `docker` *binary* is found; it
cannot make the Docker *daemon* exist. Docker Desktop is a GUI application that does not start
itself, and it was confirmed not running at the start of this session. So the script finds
`docker`, runs it, and gets `dial unix ~/.docker/run/docker.sock: connect: no such file
or directory`.

The earlier fix documented in `scripts/backup.sh` — the comment reading *"Three of the last four
nightly runs ended that way"* — addressed the **symptom** (zero-byte files left silently on disk)
and it works: runs from 2026-09-03 onward correctly print `[backup] FAILED …` and `rm -f` the
artifact. It did not, and could not, address the **cause**. The script is now failing loudly and
correctly every single night, and nothing is reading the log.

### 7c. The truncated dump is invisible to a TOC check

`rhumb-20260828T215039Z.dump` is 4.31 GB against ~4.80 GB for its neighbours. Verified read-only in
a throwaway container:

```
$ docker run --rm -v .../backups:/b:ro postgres:16 pg_restore -l /b/rhumb-20260828T215039Z.dump
exit=0    TABLE DATA entries: 61
```

**It lists all 61 tables and exits 0** — identical to a good dump. The custom-format TOC sits at the
head of the file, so truncation at 90% is undetectable this way. This matters because
`scripts/backup.sh`'s own `--verify` comment proposes exactly that check
(`pg_restore --list | grep -c 'TABLE DATA'`) as the way to widen verification. **It would wave this
file through.** The only control that actually catches it is the `MIN_PCT=95` size floor — and that
floor never executed, because the process was killed before reaching it.

The three 0-byte files are correctly detected as garbage (`pg_restore -l` → `input file is too
short (read 0, expected 5)`), but they remain on disk; retention only removes files older than 14
days, so they will sit there until 2026-09-13.

### 7d. 🔴 The Receipts tables have never been backed up, at all

The newest backup contains **61 tables**. The live database has **64**. The three missing ones:

```
callers
calls
caller_verifications
```

These are the Receipts tables — `CLAUDE.md`'s "**RECEIPTS is now the product**".

The timing is the whole story:

| Event | Timestamp (UTC) |
|---|---|
| Newest backup written | **2026-09-02 02:31:49** |
| Migration `034` created the Receipts tables | **2026-09-02 02:33:46** |

**The last good backup was taken 1 minute 57 seconds before the product's tables existed**, and
every attempt since has failed. There is no backup, anywhere, that contains a single row of
`calls`.

Current exposure, measured:

| Table | Rows |
|---|---:|
| `callers` | 2 (`@convergence-v3`, `@convergence-v4` — both `kind = algorithm`) |
| `calls` | 473 |
| `caller_verifications` | 0 |

**Today the practical loss is small**: all 473 calls are the house records, seeded from
`claim_outcomes` by `cli seed-house-records`, and `claim_outcomes` *is* in the backup — so they are
regenerable. There are zero human callers.

**That is exactly why this is urgent rather than already-catastrophic.** The window is open and it
closes the moment a human publishes. A published call is sealed into an append-only SHA256 chain
whose whole product promise is that it cannot be rewritten or reconstructed; there is no second
copy anywhere, by design. Restoring the newest dump today would silently roll the database back to
a state where the product does not exist.

---

## Findings, ranked

| # | Severity | Finding |
|---|---|---|
| **F-1** | 🔴 **Critical** | No backup contains the Receipts tables. Newest dump predates migration 034 by 1 m 57 s; every run since has failed. A restore today would delete the product |
| **F-2** | 🔴 **Critical** | Backups have failed 11 of the last 12 nights. Cause: Docker Desktop is not running when launchd fires at 03:15. The agent, the `PATH` fix and the failure reporting all work — the daemon simply is not there |
| **F-3** | 🟠 **High** | A truncated 4.31 GB dump (2026-08-28) sits on disk and passes `pg_restore -l` with all 61 tables. The TOC check `backup.sh` proposes for wider verification cannot detect it; only the `MIN_PCT` size floor can, and that run never reached it |
| **F-4** | 🟠 **High** | The model chain has no fallback. `openai` slot → HTTP 410 `github_models_retirement_brownout`. Gemini is the single point of failure and is at its free-tier ceiling. Unchanged since 2026-09-02; fix is documented in `docs/state.md` |
| **F-5** | 🟡 **Medium** | Prices are 4 real sessions behind (newest bar 2026-09-02 vs Tiingo's own 2026-09-08); **0 of 500** symbols at the latest session; the feed stopped mid-alphabet at `PEB-PH`. SPY, the benchmark, is at 2026-09-01 — staler than the 39 leaders, so call resolution is stalled |
| **F-6** | 🟡 **Medium** | Three 0-byte `.dump` files remain in `backups/`; retention will not remove them until 2026-09-13 |
| **F-7** | 🔵 **Info** | HEAD is `receipts`, not `main` — 9 commits ahead, unmerged. The Receipts product does not exist on `main` |
| **F-8** | 🔵 **Info** | All SEC tables frozen at 2026-07-21/22; nothing in the database has moved since 2026-09-02. Expected with the worker stopped, but it means every "as of" figure in `docs/state.md` should be re-measured before use |

### Nothing was fixed

Per the brief, every finding above is recorded and left alone. F-1/F-2 are one command away from
being addressed and are the obvious first action of any follow-up.

---

## Appendix — what was and was not verified

**Verified live:** container start and health; five credentials from inside the container (plus one
deliberate negative control); 64 tables and every requested row count and date by direct `SELECT`;
price coverage against both the table's calendar and the real NYSE calendar; both Receipts hash
chains (323/323 and 150/150 links intact); 834 tests; ruff; every backup file's size, mtime and
restorable-TOC status; the launchd agent's load state and last exit status; the table-list diff
between the newest backup and the live database.

**Not verified, and why:**

- **No backup was actually restored.** `pg_restore -l` reads the TOC only. Given F-3 — a truncated
  file passes that check — *the newest dump's TOC being readable is not proof it restores.* A full
  `--verify` restore into a scratch database is the only real proof, and it writes, so it was out
  of scope here.
- **No browser check.** `CLAUDE.md` §12 warns that tests and lint both pass while a page throws.
  Only `/healthz` and one read-only API endpoint were exercised; no surface was rendered.
- **Whether the 5 oldest-stale symbols are delisted or merely lagging.** Distinguishing those is
  precisely the call §0z says must not be made casually, and it needs a live per-symbol fetch.
- **`used_template: false` on a real model surface.** The Gemini key lists models; that is not the
  same as a surface returning model prose. Per §0 that must be checked against a running instance
  before trusting the model path.

## Appendix — commands run

```bash
docker compose up -d db api                      # worker deliberately omitted
docker compose exec -T api python - < probe.py   # live credential probes, inside the container
docker compose exec -T db psql -U tradeos -d tradeos -X -q   # SELECT / COUNT only
make test                                        # docker compose run --rm api python -m pytest tests/ -q
make lint                                        # docker compose run --rm api ruff check tradeos tests
docker run --rm -v ./backups:/b:ro postgres:16 pg_restore -l /b/<dump>   # read-only, throwaway
launchctl list | grep rhumb
```
