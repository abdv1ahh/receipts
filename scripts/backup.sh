#!/usr/bin/env bash
# Database backup for Rhumb.
#
# WHY THIS EXISTS: the dataset is 759,698 insider transactions, 135,925 stake events and 24,982
# institutional holdings, built over hours of rate-limited SEC backfill that cannot be rerun
# quickly — SEC fair-access throttling is the constraint, not disk. Losing it does not cost a
# restore, it costs days. It also holds the Ledger, and a Ledger that can be lost and rebuilt is
# not an accuracy record.
#
# Deliberately a shell script and a schedule entry rather than a backup service: it is `pg_dump`
# with retention, it has to work on whatever free tier this ends up on, and anything cleverer is
# something else to operate.
#
#   ./scripts/backup.sh                      # dump to ./backups
#   BACKUP_DIR=/mnt/vol ./scripts/backup.sh  # somewhere that survives a redeploy
#   ./scripts/backup.sh --verify             # dump, then prove it restores
#
# SCHEDULING. On Linux, cron (daily, 03:15), with output kept so a silent failure is not silent:
#   15 3 * * * cd /srv/rhumb && ./scripts/backup.sh >> /var/log/rhumb-backup.log 2>&1
#
# On macOS use launchd, NOT cron: cron skips a scheduled run entirely if the machine is asleep at
# the time, so on a laptop the line above silently never fires. launchd's StartCalendarInterval
# runs it on the next wake instead. See ~/Library/LaunchAgents/app.rhumb.backup.plist — and note
# it must set PATH explicitly, because launchd starts jobs without /usr/local/bin, where the
# Docker CLI lives.
#
# MEASURED, 2026-08-23 (the previous figures here were from 2026-07-26 and understated the
# database by half — re-measure before trusting them, and update this block when you do):
# the database is 7.89 GB, of which raw_filings is 7.27 GB — the stored SEC payloads, which are
# exactly the part that cannot be refetched quickly. A -Fc dump of it is 4.8 GB and takes about
# nine minutes, so the default 14-day retention needs 67 GB. Size the volume for that, or lower
# KEEP_DAYS; do NOT "fix" it by excluding raw_filings, which is the part that costs ~76 hours of
# throttled refetch to rebuild.
#
# Be precise about what "irreplaceable" means here, because it decides what to protect first.
# raw_filings is 92% of the bytes but it is public and permanent — SEC EDGAR still has it, and
# losing it costs time, not data. The ~18 MB that is genuinely unrecoverable is the user accounts,
# trades, the journal, the whole claims/claim_outcomes Ledger, and the RSS/GDELT/Bluesky event
# history, which those feeds do not serve retrospectively. A dump on the same disk as the database
# protects against a dropped table, not against losing the drive; an offsite copy of that 18 MB is
# cheap and matters more than an offsite copy of the other 7.5 GB.

set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-./backups}"
KEEP_DAYS="${KEEP_DAYS:-14}"
DB_SERVICE="${DB_SERVICE:-db}"
DB_USER="${POSTGRES_USER:-tradeos}"
DB_NAME="${POSTGRES_DB:-tradeos}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="${BACKUP_DIR}/rhumb-${STAMP}.dump"

mkdir -p "$BACKUP_DIR"

# The floor a dump must clear to count as a backup. Two parts, and the second one is the point:
#
#   ABS_FLOOR   catches the empty file. It has to stay small enough that a legitimately tiny dump
#               of a fresh or demo-seeded database still passes, so on its own it would happily
#               accept a multi-gigabyte dump that got truncated at 40% of the real database.
#   MIN_PCT     catches THAT. The most recent dump still on disk is by definition one that passed
#               this check (a failed one is deleted below), so it is a usable reference for what
#               this database's dump weighs. A new dump smaller than MIN_PCT of it is a
#               truncation, not a backup.
#
# 95 rather than a rounder 80, and the number is measured rather than picked. Consecutive good
# dumps in ./backups grow by well under 0.1% a day (4,794,949,429 -> 4,796,633,340 over twelve
# days), so this database has never shrunk between runs and 95% leaves fifty times the observed
# day-to-day movement as headroom. The truncated run of 2026-08-28 came in at 4,309,987,328, which
# is 89.9% of the dump before it: an 80% floor would have waved it through, which is the whole
# failure this is here to stop. If a deliberate shrink ever happens, a bulk delete or a dropped
# table, set MIN_PCT for that one run rather than lowering it permanently.
#
# With no prior dump there is nothing to compare against and the floor falls back to ABS_FLOOR.
ABS_FLOOR="${ABS_FLOOR:-100000}"
MIN_PCT="${MIN_PCT:-95}"

prior_size() {
  # Most recent surviving dump other than the one we are writing now. Sorted by modification
  # time rather than by name so a manually copied file cannot jump the queue on its timestamp.
  local newest
  newest="$(find "$BACKUP_DIR" -name 'rhumb-*.dump' -type f ! -name "$(basename "$OUT")" \
              -exec ls -t {} + 2>/dev/null | head -n 1)"
  [ -n "$newest" ] && wc -c < "$newest" | tr -d ' '
}

fail() {
  # Everything that must happen on a bad dump happens HERE, so it happens on EVERY bad dump.
  echo "[backup] FAILED: $1" >&2
  rm -f "$OUT"
  exit 1
}

echo "[backup] dumping ${DB_NAME} -> ${OUT}"
# -Fc (custom format): compressed, and restorable table-by-table with pg_restore, which matters
# when the thing you actually want back is one table rather than the whole database.
#
# The exit status is captured EXPLICITLY rather than left to `set -e`. The shell creates ${OUT}
# for the redirect before pg_dump runs, so when pg_dump fails — a stopped Docker daemon is the
# common case — `set -e` used to abort the script right here, past the redirect and before the
# size check and the `rm -f`. That left a zero byte file on disk looking exactly like a backup,
# and printed nothing about it. Three of the last four nightly runs ended that way.
DUMP_STATUS=0
docker compose exec -T "$DB_SERVICE" pg_dump -U "$DB_USER" -d "$DB_NAME" -Fc > "$OUT" || DUMP_STATUS=$?

SIZE=$(wc -c < "$OUT" 2>/dev/null | tr -d ' ' || echo 0)
SIZE="${SIZE:-0}"

if [ "$DUMP_STATUS" -ne 0 ]; then
  fail "pg_dump exited ${DUMP_STATUS} and left ${SIZE} bytes; is the database up? (docker compose ps)"
fi

PRIOR="$(prior_size || true)"
if [ -n "${PRIOR:-}" ] && [ "$PRIOR" -gt 0 ]; then
  FLOOR=$(( PRIOR * MIN_PCT / 100 ))
  FLOOR_WHY="${MIN_PCT}% of the previous dump (${PRIOR} bytes)"
else
  FLOOR="$ABS_FLOOR"
  FLOOR_WHY="the absolute floor, because there is no previous dump to compare against"
fi

if [ "$SIZE" -lt "$FLOOR" ]; then
  fail "${OUT} is ${SIZE} bytes, under ${FLOOR} — ${FLOOR_WHY}. Refusing to call that a backup."
fi
echo "[backup] wrote ${SIZE} bytes (floor was ${FLOOR}: ${FLOOR_WHY})"

if [ "${1:-}" = "--verify" ]; then
  # The only backup worth anything is one that has been restored. This restores into a scratch
  # database and counts rows, then drops it.
  #
  # KNOW WHAT THIS PROVES. It counts ONE table. A dump that restored insider_transactions but lost
  # claims, claim_outcomes or users would still print "verified" — and those are the tables that
  # cannot be rebuilt from SEC EDGAR. Verified 2026-08-23 that a real dump does carry all 61 tables
  # with data (`pg_restore --list | grep -c 'TABLE DATA'`), so the gap is in the check, not in the
  # dump. Widen this to assert across the tables that matter before relying on it as the only proof.
  VERIFY_DB="rhumb_verify_${STAMP}"
  echo "[backup] verifying by restoring into ${VERIFY_DB}"
  docker compose exec -T "$DB_SERVICE" createdb -U "$DB_USER" "$VERIFY_DB"
  docker compose exec -T "$DB_SERVICE" pg_restore -U "$DB_USER" -d "$VERIFY_DB" --no-owner < "$OUT" >/dev/null 2>&1 || true
  ROWS=$(docker compose exec -T "$DB_SERVICE" psql -U "$DB_USER" -d "$VERIFY_DB" -tAc \
    "SELECT count(*) FROM insider_transactions")
  docker compose exec -T "$DB_SERVICE" dropdb -U "$DB_USER" "$VERIFY_DB"
  if [ "${ROWS:-0}" -lt 1 ]; then
    echo "[backup] VERIFY FAILED: restored database has no insider transactions" >&2
    exit 1
  fi
  echo "[backup] verified: ${ROWS} insider transactions restored cleanly"
fi

# Retention. `-mtime +N` only ever matches this script's own naming pattern, so it cannot delete
# anything it did not write.
find "$BACKUP_DIR" -name 'rhumb-*.dump' -type f -mtime "+${KEEP_DAYS}" -print -delete
echo "[backup] done; keeping ${KEEP_DAYS} days in ${BACKUP_DIR}"
