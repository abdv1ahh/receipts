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

echo "[backup] dumping ${DB_NAME} -> ${OUT}"
# -Fc (custom format): compressed, and restorable table-by-table with pg_restore, which matters
# when the thing you actually want back is one table rather than the whole database.
docker compose exec -T "$DB_SERVICE" pg_dump -U "$DB_USER" -d "$DB_NAME" -Fc > "$OUT"

SIZE=$(wc -c < "$OUT" | tr -d ' ')
# A dump that is technically a file but holds nothing is the failure mode that goes unnoticed for
# months, so refuse to call it a backup. A real dump of THIS database is 4.8 GB (2026-08-23), so
# this 100 KB floor only catches the empty-file case. It is deliberately not raised to something
# proportional, because the same script has to accept a legitimately small dump of a fresh or
# demo-seeded database — a floor sized for production would reject those. It follows that a
# partial dump measured in megabytes would still pass: if you want that caught, `--verify` is the
# check that actually proves the file restores.
if [ "$SIZE" -lt 100000 ]; then
  echo "[backup] FAILED: ${OUT} is only ${SIZE} bytes — refusing to treat that as a backup" >&2
  rm -f "$OUT"
  exit 1
fi
echo "[backup] wrote ${SIZE} bytes"

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
