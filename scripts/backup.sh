#!/usr/bin/env bash
# Database backup for Receipts.
#
# WHY THIS EXISTS: the dataset is 759,698 insider transactions, 135,925 stake events and 24,982
# institutional holdings, built over hours of rate-limited SEC backfill that cannot be rerun
# quickly — SEC fair-access throttling is the constraint, not disk. Losing it does not cost a
# restore, it costs days. It also holds the Ledger and, since migration 034, the `calls` table:
# a per-caller SHA256 hash chain whose entire value is that it is continuous and unedited. A
# restored gap in that chain is not an inconvenience, it is the failure of the thing being sold.
#
# Deliberately a shell script and a schedule entry rather than a backup service: it is `pg_dump`
# with retention, it has to work on whatever free tier this ends up on, and anything cleverer is
# something else to operate.
#
#   ./scripts/backup.sh                      # dump to ~/.local/share/receipts/backups
#   BACKUP_DIR=/mnt/vol ./scripts/backup.sh  # somewhere that survives a redeploy
#   ./scripts/backup.sh --verify             # dump, then prove it restores
#
# ---------------------------------------------------------------------------------------------
# TRANSPORT: THE HOST FIRST, DOCKER ONLY AS A NAMED FALLBACK.
#
# This script used to run `docker compose exec db pg_dump`, which put THREE things between us and
# a backup: the `docker` binary being on PATH, the Docker daemon being alive, and compose being
# able to resolve the project. Measured 2026-09-09: eleven of the previous twelve nightly runs
# failed, every one of them at `dial unix .../docker.sock: no such file or directory`.
#
# So the primary path is now a plain TCP connection from the host to the mapped Postgres port. No
# daemon API, no compose project, nothing to resolve — and it keeps working unchanged the day this
# database moves to a managed host, which is where it is going.
#
# BE PRECISE ABOUT WHAT THAT FIXES, because overstating it would be its own bug. Postgres itself
# still runs inside Docker today. If the daemon is down at 03:15 there is no server listening on
# 5432 either, and this script fails — just with an honest "could not connect" instead of a
# confusing Docker socket error. Removing the Docker CLI from the path buys robustness and
# portability. IT DOES NOT FIX THE NIGHTLY FAILURE. That needs Docker Desktop to be running when
# the job fires; see docs/analysis/ for the exact settings, and `preflight` below, which refuses
# to be quiet about it.
#
# The container fallback exists because a host `pg_dump` is not installed on this machine yet and
# a backup tonight beats a perfect backup next week. It is chosen ONLY when no host client is
# found, and it announces itself on every single run — a fallback nobody can see is an outage with
# good manners, which this codebase has already paid for once (CLAUDE.md §0).
#
# ---------------------------------------------------------------------------------------------
# SCHEDULING. On Linux, cron (daily, 03:15), with output kept so a silent failure is not silent:
#   15 3 * * * cd /srv/receipts && ./scripts/backup.sh >> /var/log/receipts-backup.log 2>&1
#
# On macOS use launchd, NOT cron: cron skips a scheduled run entirely if the machine is asleep at
# the time, so on a laptop the line above silently never fires. launchd's StartCalendarInterval
# runs it on the next wake instead. See ~/Library/LaunchAgents/app.rhumb.backup.plist.
#
# MEASURED, 2026-09-09: the database is 7.91 GB across 64 tables, of which raw_filings is 6.94 GB.
# A -Fc dump is 4.80 GB and takes about nine and a half minutes, so the default 14-day retention
# needs 67 GB. Size the volume for that, or lower KEEP_DAYS; do NOT "fix" it by excluding
# raw_filings, which is the part that costs ~76 hours of throttled refetch to rebuild.
#
# Be precise about what "irreplaceable" means here, because it decides what to protect first.
# raw_filings is 88% of the bytes but it is public and permanent — SEC EDGAR still has it, and
# losing it costs time, not data. The ~18 MB that is genuinely unrecoverable is the user accounts,
# trades, the journal, the whole claims/claim_outcomes Ledger, the RSS/GDELT/Bluesky event history
# which those feeds do not serve retrospectively, and `calls`, which by design has no second copy
# anywhere. A dump on the same disk as the database protects against a dropped table, not against
# losing the drive; an offsite copy of that 18 MB is cheap and matters more than the other 7.9 GB.

set -uo pipefail        # deliberately NOT -e; see THE GUARD below

# DEFAULTS OUTSIDE THE CLONE, and that is a correctness change rather than tidiness.
#
# It used to default to `./backups`, i.e. inside the working tree. Measured on the author's machine
# on 2026-09-23: 18 dumps, 81 GB, sitting in the repository directory. Nothing was ever committed —
# `.gitignore` has carried `backups/` from the start — but "the dump is safe because git ignores
# it" is not the property anybody wanted. A dump inside the clone is deleted by a fresh clone, is
# copied by a `cp -r` of the project, is scanned by every tool pointed at the repo, and on a laptop
# it is the thing that fills the disk while looking like source code.
#
# `$XDG_DATA_HOME` (or ~/.local/share) is where a per-user data store belongs on Linux and is
# harmless on macOS. A production host should set BACKUP_DIR to a volume that survives a redeploy,
# which is what the usage line above says.
#
# NOTHING IS MIGRATED. An existing ./backups keeps every dump in it; this only changes where the
# NEXT one is written. Moving somebody's 81 GB as a side effect of a default change would be the
# worse mistake.
BACKUP_DIR="${BACKUP_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/receipts/backups}"
KEEP_DAYS="${KEEP_DAYS:-14}"
DB_SERVICE="${DB_SERVICE:-db}"
DB_HOST="${PGHOST:-127.0.0.1}"
DB_PORT="${PGPORT:-5432}"
DB_USER="${POSTGRES_USER:-tradeos}"
DB_NAME="${POSTGRES_DB:-tradeos}"
# Local development credentials, already in plain text in docker-compose.yml. A managed host
# supplies its own, and this default is then never used.
export PGPASSWORD="${POSTGRES_PASSWORD:-tradeos}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
# THE PREFIX CHANGED AND THE MATCH DID NOT. New dumps are written as `receipts-*`; every read
# below globs BOTH, because 18 dumps on this machine are named `rhumb-*` and a retention sweep
# that stops seeing them would keep them forever while reporting success, and a restore that
# stops seeing them would report "no backup found" next to 81 GB of backups.
OUT="${BACKUP_DIR}/receipts-${STAMP}.dump"
# THE DUMP IS WRITTEN UNDER A NAME THAT IS NOT A BACKUP, and only renamed once every check has
# passed. This is the one guard a trap cannot provide: a trap handles SIGTERM, SIGINT and SIGHUP,
# but SIGKILL and a power cut cannot be caught by anything, and bash defers even a catchable
# signal until the foreground command returns. So the 9-minute window during which a laptop can
# sleep, be force-quit or lose power is a window in which a half-written multi-gigabyte file
# exists on disk. Under `rhumb-*.dump` that file is indistinguishable from a backup — that is
# precisely the 4.31 GB artifact of 2026-08-28, which sat in this directory for twelve days and
# passed `pg_restore -l` with all 61 tables. Under `.partial` it can never be mistaken for one,
# is never picked as the size reference, and is swept on the next run. `mv` within one directory
# is atomic, so the final name appears only on a dump that has been proven good.
STAGE="${OUT}.partial"

mkdir -p "$BACKUP_DIR"

# ---------------------------------------------------------------------------------------------
# THE FLOORS. Three of them, because each catches something the others cannot.
#
#   ABS_FLOOR   catches the empty file. It has to stay small enough that a legitimately tiny dump
#               of a fresh or demo-seeded database still passes, so ON ITS OWN IT IS NEARLY
#               USELESS: it would happily accept a multi-gigabyte dump truncated at 40%.
#   MIN_PCT     catches THAT, and it is the only check that can. Measured against the most recent
#               dump that is itself plausible. A new dump smaller than MIN_PCT of it is a
#               truncation, not a backup.
#   MIN_TABLES  catches a dump that is complete and current-looking but STRUCTURALLY BEHIND. On
#               2026-09-02 a good 4.80 GB dump was written 1m57s before migration 034 created
#               callers/calls/caller_verifications, so for a week the newest backup was a
#               perfectly valid archive of a database without the product in it. Size cannot see
#               that; a table count can.
#
# 95 rather than a rounder 80, and the number is measured rather than picked. Consecutive good
# dumps grow by well under 0.1% a day (4,794,949,429 -> 4,797,232,406 over twenty days), so this
# database has never shrunk between runs and 95% leaves fifty times the observed day-to-day
# movement as headroom. The truncated run of 2026-08-28 came in at 4,309,987,328, which is 89.9%
# of the dump before it: an 80% floor would have waved it through, which is the whole failure this
# is here to stop. If a deliberate shrink ever happens, a bulk delete or a dropped table, set
# MIN_PCT for that one run rather than lowering it permanently.
#
# With no prior dump there is nothing to compare against and the floor falls back to ABS_FLOOR.
ABS_FLOOR="${ABS_FLOOR:-100000}"
MIN_PCT="${MIN_PCT:-95}"
MIN_TABLES="${MIN_TABLES:-64}"

log()  { echo "[backup] $*"; }
loud() { echo "[backup] FAILED: $*" >&2; }

# ---------------------------------------------------------------------------------------------
# THE GUARD. Everything that must happen on a bad dump happens in a trap, so it happens on EVERY
# bad dump — including the ones where nothing gets a chance to run a check.
#
# This is the lesson of 2026-08-28. That run was killed mid-dump (laptop asleep, ~9 minutes in).
# `set -e` had already aborted past the size check on other nights, but this was worse: no handler
# ran at all, so a 4.31 GB truncated file was left on disk with NO failure line in the log, and it
# sat there for twelve days looking exactly like a backup. `pg_restore -l` even listed all 61 of
# its tables and exited 0, because the custom-format TOC is at the head of the file.
#
# So the file is deleted on EVERY exit path unless KEEP is explicitly set to 1 at the very end,
# after every check has passed. Not "deleted if we notice a problem" — kept only if we prove
# there isn't one. A kill, a hangup, an unset variable, a `return` nobody expected: all of them
# now end with no file and a loud line, which is the only safe default for a thing whose failure
# mode is looking healthy.
KEEP=0
cleanup() {
  local rc=$?
  if [ "$KEEP" != "1" ]; then
    local size="unknown"
    [ -e "$STAGE" ] && size="$(wc -c < "$STAGE" 2>/dev/null | tr -d ' ')"
    rm -f "$STAGE"
    loud "no usable dump was produced (exit ${rc}); removed ${STAGE} (${size} bytes). Nothing was kept."
  fi
}
trap cleanup EXIT
trap 'loud "interrupted by a signal"; exit 130' INT TERM HUP

# Anything left by a run that was SIGKILLed or lost power. Matched on the suffix this
# script alone writes, so it can never remove a real backup.
for stale in "${BACKUP_DIR}"/receipts-*.dump.partial "${BACKUP_DIR}"/rhumb-*.dump.partial; do
  [ -e "$stale" ] || continue
  log "sweeping abandoned partial from an earlier run: ${stale} ($(wc -c < "$stale" | tr -d " ") bytes)"
  rm -f "$stale"
done

# ---------------------------------------------------------------------------------------------
# Locate a host pg_dump / pg_restore. `command -v` first, then the places macOS puts libpq without
# putting it on PATH, then Postgres.app.
find_pg() {
  local tool="$1" p
  if command -v "$tool" >/dev/null 2>&1; then command -v "$tool"; return 0; fi
  for p in /opt/homebrew/opt/libpq/bin /usr/local/opt/libpq/bin \
           /opt/homebrew/bin /usr/local/bin \
           /Applications/Postgres.app/Contents/Versions/*/bin; do
    [ -x "$p/$tool" ] && { echo "$p/$tool"; return 0; }
  done
  return 1
}

PG_DUMP="$(find_pg pg_dump || true)"
PG_RESTORE="$(find_pg pg_restore || true)"

if [ -n "$PG_DUMP" ]; then
  TRANSPORT="host"
  log "transport: HOST pg_dump -> ${DB_HOST}:${DB_PORT} (no Docker in this path)"
  log "           $($PG_DUMP --version 2>/dev/null || echo 'version unknown')"
else
  TRANSPORT="docker"
  log "transport: DOCKER FALLBACK — no host pg_dump found."
  log "           This run depends on the Docker daemon, which is what breaks the 03:15 job."
  log "           Install the client to remove that dependency; see docs/runbooks/."
fi

# ---------------------------------------------------------------------------------------------
log "dumping ${DB_NAME} -> ${OUT}  (transport: ${TRANSPORT})"

# The exit status is captured EXPLICITLY as well as being trapped. The shell creates ${OUT} for
# the redirect before pg_dump runs, so a failing pg_dump always leaves a file behind; the status
# is what says whether its contents mean anything.
#
# -Fc (custom format): compressed, and restorable table-by-table with pg_restore, which matters
# when the thing you actually want back is one table rather than the whole database.
DUMP_STATUS=0
if [ "$TRANSPORT" = "host" ]; then
  "$PG_DUMP" -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -Fc > "$STAGE" || DUMP_STATUS=$?
else
  docker compose exec -T "$DB_SERVICE" pg_dump -U "$DB_USER" -d "$DB_NAME" -Fc > "$STAGE" || DUMP_STATUS=$?
fi

SIZE=$(wc -c < "$STAGE" 2>/dev/null | tr -d ' ' || echo 0)
SIZE="${SIZE:-0}"

if [ "$DUMP_STATUS" -ne 0 ]; then
  loud "pg_dump exited ${DUMP_STATUS} and left ${SIZE} bytes (transport: ${TRANSPORT})."
  if [ "$TRANSPORT" = "host" ]; then
    loud "  could not reach ${DB_HOST}:${DB_PORT} — is the db container up? (docker compose ps db)"
  else
    loud "  is Docker running and is the db container up? (docker compose ps)"
  fi
  exit 1                      # the trap deletes the file
fi

# --------------------------------------------------- floor 1 + 2: absolute, then relative
# The reference is the newest dump that is ITSELF plausible, not merely the newest file. A failed
# dump is deleted below, but three zero-byte files from before this guard existed are still on
# disk, and if one of them were ever the newest the floor would collapse to ABS_FLOOR and a
# truncated 4.31 GB file would sail through. Skipping implausible files closes that.
prior_size() {
  local f n
  while IFS= read -r f; do
    [ "$f" = "$STAGE" ] && continue
    n="$(wc -c < "$f" 2>/dev/null | tr -d ' ')"
    if [ -n "$n" ] && [ "$n" -ge "$ABS_FLOOR" ]; then echo "$n"; return 0; fi
  done < <(find "$BACKUP_DIR" \( -name 'receipts-*.dump' -o -name 'rhumb-*.dump' \) -type f -exec ls -t {} + 2>/dev/null)
  return 1
}

PRIOR="$(prior_size || true)"
if [ -n "${PRIOR:-}" ] && [ "$PRIOR" -gt 0 ]; then
  FLOOR=$(( PRIOR * MIN_PCT / 100 ))
  FLOOR_WHY="${MIN_PCT}% of the previous good dump (${PRIOR} bytes)"
else
  FLOOR="$ABS_FLOOR"
  FLOOR_WHY="the absolute floor, because there is no previous dump to compare against"
fi

if [ "$SIZE" -lt "$FLOOR" ]; then
  loud "${STAGE} is ${SIZE} bytes, under ${FLOOR} — ${FLOOR_WHY}. Refusing to call that a backup."
  exit 1
fi

# --------------------------------------------------- floor 3: does it contain the whole schema
# Cheap: the custom-format TOC is at the head of the file, so this reads kilobytes, not gigabytes.
# It is NOT a truncation check and must never be mistaken for one — a 90%-truncated archive lists
# every table and exits 0. MIN_PCT above is the truncation check. This one answers a different
# question: is this a dump of the CURRENT schema, or of a database from before the last migration?
#
# Two traps here, both of which bit on the first run of this rewrite and are worth naming.
# `grep -c` EXITS 1 when it counts zero, so the idiomatic `grep -c ... || echo 0` prints "0"
# and then appends a second "0", and the `-lt` test below dies on "0\n0" with
# "integer expression expected" — leaving the ELSE branch to report the check as PASSED. A guard
# that cannot compute its number must never fall through to success, so the count is validated as
# a single integer and anything else is a failure, not a pass.
#
# And pg_restore needs a SEEKABLE file for the custom format, so piping the archive in on stdin
# yields nothing. The container path therefore bind-mounts the directory read-only rather than
# streaming, which also avoids pushing 4.8 GB through a pipe.
count_tables() {
  if [ -n "$PG_RESTORE" ]; then
    "$PG_RESTORE" --list "$STAGE" 2>/dev/null | grep -c 'TABLE DATA'
  elif command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    docker run --rm -v "$(cd "$(dirname "$STAGE")" && pwd):/b:ro" postgres:16 \
      pg_restore --list "/b/$(basename "$STAGE")" 2>/dev/null | grep -c 'TABLE DATA'
  else
    return 1
  fi
}

TABLES="$(count_tables | tr -d '[:space:]')" || TABLES=""

if [ -z "$TABLES" ]; then
  log "table-count check SKIPPED: no usable pg_restore on either path"
elif ! [ "$TABLES" -eq "$TABLES" ] 2>/dev/null; then
  loud "table-count check could not produce a number (got ${TABLES@Q}). Refusing to guess."
  exit 1
elif [ "$TABLES" -lt "$MIN_TABLES" ]; then
  loud "${STAGE} contains ${TABLES} tables, fewer than ${MIN_TABLES}. Either a migration has not been"
  loud "  applied to this database, or the dump is incomplete. Refusing to call that a backup."
  exit 1
else
  log "table-count check passed: ${TABLES} tables (floor ${MIN_TABLES})"
fi

log "wrote ${SIZE} bytes (floor was ${FLOOR}: ${FLOOR_WHY})"

# --------------------------------------------------- optional: prove it actually restores
if [ "${1:-}" = "--verify" ]; then
  # The only backup worth anything is one that has been restored. This restores into a scratch
  # database and counts rows, then drops it.
  #
  # KNOW WHAT THIS PROVES. It counts three tables, chosen because they are the ones that cannot be
  # rebuilt: insider_transactions is the bulk that costs ~76 hours to refetch, and callers/calls
  # are the hash chain, which cannot be refetched at all. A dump that restored insider_transactions
  # but lost calls used to still print "verified"; it no longer does.
  VERIFY_DB="rhumb_verify_${STAMP}"
  log "verifying by restoring into ${VERIFY_DB}"
  if [ -n "$PG_RESTORE" ]; then
    PSQL="$(find_pg psql || true)"
    "$(find_pg createdb)" -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" "$VERIFY_DB"
    "$PG_RESTORE" -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$VERIFY_DB" --no-owner < "$STAGE" >/dev/null 2>&1
    ROWS=$("$PSQL" -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$VERIFY_DB" -tAc \
      "SELECT (SELECT count(*) FROM insider_transactions)||'/'||(SELECT count(*) FROM calls)")
    "$(find_pg dropdb)" -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" "$VERIFY_DB"
  else
    docker compose exec -T "$DB_SERVICE" createdb -U "$DB_USER" "$VERIFY_DB"
    docker compose exec -T "$DB_SERVICE" pg_restore -U "$DB_USER" -d "$VERIFY_DB" --no-owner < "$STAGE" >/dev/null 2>&1
    ROWS=$(docker compose exec -T "$DB_SERVICE" psql -U "$DB_USER" -d "$VERIFY_DB" -tAc \
      "SELECT (SELECT count(*) FROM insider_transactions)||'/'||(SELECT count(*) FROM calls)")
    docker compose exec -T "$DB_SERVICE" dropdb -U "$DB_USER" "$VERIFY_DB"
  fi
  ROWS="$(echo "$ROWS" | tr -d '[:space:]')"
  INS="${ROWS%%/*}"; CALLS="${ROWS##*/}"
  if [ "${INS:-0}" -lt 1 ] || [ "${CALLS:-0}" -lt 1 ]; then
    loud "VERIFY FAILED: restored ${INS:-0} insider transactions and ${CALLS:-0} calls"
    exit 1
  fi
  log "verified: ${INS} insider transactions and ${CALLS} calls restored cleanly"
fi

# --------------------------------------------------- promote: it is a backup only from here
# Every check has passed, so the staging file earns the real name. Atomic within the directory,
# so at no instant does a `rhumb-*.dump` exist that has not been verified.
if ! mv "$STAGE" "$OUT"; then
  loud "could not rename ${STAGE} to ${OUT}"
  exit 1
fi
KEEP=1
log "promoted to ${OUT}"

# Retention. `-mtime +N` only ever matches this script's own naming pattern, so it cannot delete
# anything it did not write.
find "$BACKUP_DIR" \( -name 'receipts-*.dump' -o -name 'rhumb-*.dump' \) -type f -mtime "+${KEEP_DAYS}" -print -delete
log "done; keeping ${KEEP_DAYS} days in ${BACKUP_DIR}"
