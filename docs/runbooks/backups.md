# Runbook — backups, and how to stop them depending on the laptop

**Written 2026-09-11.** Read this if a backup failed, or before trusting one.

Backups live in **`/path/to/receipts/backups/`**. To open that in Finder: **⇧⌘G**, paste the
path. The log is `backups/backup.log`.

---

## What was wrong, and what is actually fixed

Part 0 measured that **eleven of the previous twelve nightly runs failed**, every one at
`dial unix ~/.docker/run/docker.sock: no such file or directory`. The launchd agent
fired correctly every night. The script ran. Docker Desktop was not running, so there was nothing to
dump.

**Be precise about what the script rewrite fixes, because it is easy to overstate.**

`backup.sh` no longer goes through `docker compose exec`. Its primary path is a plain TCP connection
to the mapped Postgres port, which removes three failure points: the `docker` binary being on PATH,
the daemon being alive, and compose resolving the project. That is real robustness, and it means the
script keeps working unchanged the day this database moves to a managed host.

**It does not, on its own, fix the 03:15 failure.** Postgres still runs *inside* Docker. If the
daemon is down at 03:15 there is no server listening on 5432 either — the script now fails with an
honest "could not connect" instead of a confusing Docker socket error, but it still fails. **The
nightly failure is fixed by the steps in §3, not by the script.**

---

## 1. What the script now guarantees

| Guard | What it catches |
|---|---|
| Host TCP transport (primary) | removes the Docker CLI and daemon from the backup path |
| Explicit `DUMP_STATUS` capture | `set -e` can no longer abort past the checks |
| `trap cleanup EXIT/INT/TERM/HUP` | the size check runs on **every** exit path, not just the happy one |
| **Write to `.partial`, rename only on success** | a SIGKILL or power cut cannot leave a file that looks like a backup. `mv` within a directory is atomic, so a `rhumb-*.dump` never exists unverified |
| `MIN_PCT=95` vs the previous **good** dump | truncation. The reference skips implausible files, so a 0-byte leftover cannot collapse the floor to `ABS_FLOOR` |
| `MIN_TABLES=64` on the TOC | a dump taken *before a migration*. This is the check that would have caught the 2026-09-02 backup that predated migration 034 by 1m57s |
| On any failure | delete the file, loud line to the log, **exit non-zero** |

**`MIN_TABLES` is not a truncation check and must never be mistaken for one.** A 90%-truncated
archive lists every table and exits 0 — that is exactly what the 4.31 GB file of 2026-08-28 did for
twelve days. Only `MIN_PCT` catches truncation. The two checks answer different questions.

**Raise `MIN_TABLES` whenever a migration adds a table.** It is `64` today.

---

## 2. Test results, 2026-09-11

| Test | Result |
|---|---|
| Normal run, database up | ✅ exit 0 · 4,797,232,407 bytes · 64 tables · promoted · no `.partial` left |
| **db container stopped** | ✅ exit **1** · loud failure · **no file left behind** |
| **Docker Desktop stopped entirely** | ✅ exit **1** · loud failure · **no file left behind** |
| SIGKILL mid-dump *(the 2026-08-28 case)* | ✅ exit 137 · only a `.partial` remained, never a `rhumb-*.dump` · swept by the next run |

---

## 3. Making this stop depending on the laptop — exact steps

Do **A** and **B**. **C** is the permanent fix and is worth doing when there is time.

### A. Make Docker Desktop start by itself, and keep the Mac awake for the job

1. Open **Docker Desktop**.
2. Click the **gear icon** (Settings), top right.
3. Choose **General** in the left sidebar.
4. Tick **“Start Docker Desktop when you sign in”**.
5. Click **Apply & restart**.

That covers a reboot. It does **not** cover the Mac being asleep at 03:15, so also schedule a wake:

```bash
sudo pmset repeat wakeorpoweron MTWRFSU 03:10:00
```

Check it took:

```bash
pmset -g sched
```

To undo later: `sudo pmset repeat cancel`.

> The Mac must also be **logged in**. A LaunchAgent does not run at the login window — if the Mac
> reboots and nobody logs in, no backup runs, whatever else is configured.

### B. Point launchd at the wrapper instead of the script

`scripts/backup-scheduled.sh` starts Docker Desktop, **waits for the daemon** (up to 300s), brings up
only the `db` container — never the worker — waits for it to report healthy, then hands over to
`backup.sh`. All the laptop-specific ugliness lives there so `backup.sh` stays free of Docker.

Edit the plist:

```bash
open -e ~/Library/LaunchAgents/app.rhumb.backup.plist
```

Change this:

```xml
    <key>ProgramArguments</key>
    <array>
        <string>/path/to/receipts/scripts/backup.sh</string>
    </array>
```

to this:

```xml
    <key>ProgramArguments</key>
    <array>
        <string>/path/to/receipts/scripts/backup-scheduled.sh</string>
    </array>
```

Save, then reload — **both commands, in this order**:

```bash
launchctl unload ~/Library/LaunchAgents/app.rhumb.backup.plist
launchctl load   ~/Library/LaunchAgents/app.rhumb.backup.plist
```

Verify it is loaded:

```bash
launchctl list | grep rhumb
```

Second column is the **last exit status**. `0` is good; anything else means the last run failed.

Force one run now, without waiting for 03:15:

```bash
launchctl start app.rhumb.backup
tail -f /path/to/receipts/backups/backup.log
```

### C. The permanent fix — install a host `pg_dump`

Today there is **no `pg_dump` on this Mac** (no Homebrew, no libpq, no Postgres.app), so the script
announces `DOCKER FALLBACK` on every run and uses the container. The host TCP path is proven working
— a direct SCRAM-authenticated query over `127.0.0.1:5432` returned `473` from `calls` with no Docker
involved — **only the binary is missing.**

Easiest route without Homebrew:

1. Download **Postgres.app** from <https://postgresapp.com>.
2. Drag it to **Applications**. Do not open it — the app's server is not wanted, only its tools.
3. Confirm the script finds it (it already searches `/Applications/Postgres.app/Contents/Versions/*/bin`):

```bash
./scripts/backup.sh 2>&1 | head -3
```

The first line should change from `transport: DOCKER FALLBACK` to
`transport: HOST pg_dump -> 127.0.0.1:5432 (no Docker in this path)`.

Or with Homebrew, if it ever gets installed:

```bash
brew install libpq
```

A newer client dumping an older server is supported, so any recent version is fine.

---

## 4. Two things still outstanding

**The backups sit on the same disk as the database.** That protects against a dropped table or a bad
migration. It does **not** protect against losing the drive. Of the 7.91 GB, only about **18 MB** is
genuinely irreplaceable — user accounts, trades, the journal, the whole `claims`/`claim_outcomes`
Ledger, the RSS/GDELT/Bluesky event history those feeds do not serve retrospectively, and **`calls`,
which by design has no second copy anywhere**. `raw_filings` is 88% of the bytes and is refetchable
from SEC EDGAR, at roughly 76 throttled hours. An offsite copy of the 18 MB is cheap and matters far
more than an offsite copy of the other 7.9 GB.

**Two dead files from before the rewrite are still in `backups/`** and will age out on their own:

| File | Why it is bad | Ages out |
|---|---|---|
| `rhumb-20260828T215039Z.dump` | **truncated** — 4,309,987,328 bytes, 89.9% of its predecessor. Passes `pg_restore -l` with all 61 tables | 2026-09-12 |
| `rhumb-20260829…`, `…0830…`, `…0831…` | **0 bytes** each | 2026-09-13 to 15 |

They are harmless where they are: `prior_size` skips anything below `ABS_FLOOR`, so the empty ones
cannot become the size reference. Deleting them early is safe if the clutter is annoying.

---

## 5. Commands

```bash
./scripts/backup.sh                      # dump to ./backups
./scripts/backup.sh --verify             # dump, then restore into a scratch DB and count rows
BACKUP_DIR=/Volumes/ext ./scripts/backup.sh    # somewhere that survives losing this disk
KEEP_DAYS=30 ./scripts/backup.sh         # keep longer (needs ~4.8 GB per day)
MIN_TABLES=65 ./scripts/backup.sh        # after a migration adds a table

launchctl list | grep rhumb              # second column is the last exit status
launchctl start app.rhumb.backup         # run the nightly job right now
tail -50 backups/backup.log              # what happened last night
```

Restoring one table out of a dump:

```bash
docker compose exec -T db createdb -U tradeos scratch
docker run --rm -i --network container:tradeos-db-1 \
  -v /path/to/receipts/backups:/b:ro postgres:16 \
  pg_restore -h 127.0.0.1 -U tradeos -d scratch --no-owner -t calls /b/<dumpfile>
docker compose exec -T db psql -U tradeos -d scratch -c 'SELECT count(*) FROM calls'
docker compose exec -T db dropdb -U tradeos scratch
```
