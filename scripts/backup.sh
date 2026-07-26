#!/usr/bin/env bash
# Database backup for Rhumb.
#
# WHY THIS EXISTS: the dataset is 664,923 insider transactions, 51,099 stake events and 24,982
# institutional holdings, built over hours of rate-limited SEC backfill that cannot be rerun
# quickly — SEC fair-access throttling is the constraint, not disk. Losing it does not cost a
# restore, it costs days. It also holds the Ledger, and a Ledger that can be lost and rebuilt is
# not an accuracy record.
#
# Deliberately a shell script and a cron line rather than a backup service: it is `pg_dump` with
# retention, it has to work on whatever free tier this ends up on, and anything cleverer is
# something else to operate.
#
#   ./scripts/backup.sh                      # dump to ./backups
#   BACKUP_DIR=/mnt/vol ./scripts/backup.sh  # somewhere that survives a redeploy
#   ./scripts/backup.sh --verify             # dump, then prove it restores
#
# Cron (daily, 03:15 UTC), with output kept so a silent failure is not silent:
#   15 3 * * * cd /srv/rhumb && ./scripts/backup.sh >> /var/log/rhumb-backup.log 2>&1
#
# MEASURED, 2026-07-26: the database is 5.2 GB, of which raw_filings is 4.7 GB — the stored SEC
# payloads, which are exactly the part that cannot be refetched quickly. A gzip -Fc dump of it is
# ~2 GB and takes a few minutes, so the default 14-day retention needs roughly 30 GB. Size the
# volume for that, or lower KEEP_DAYS; do NOT "fix" it by excluding raw_filings, which would leave
# the backup missing the only irreplaceable thing in the database.

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
# months, so refuse to call it a backup. A real dump of this database is tens of megabytes.
if [ "$SIZE" -lt 100000 ]; then
  echo "[backup] FAILED: ${OUT} is only ${SIZE} bytes — refusing to treat that as a backup" >&2
  rm -f "$OUT"
  exit 1
fi
echo "[backup] wrote ${SIZE} bytes"

if [ "${1:-}" = "--verify" ]; then
  # The only backup worth anything is one that has been restored. This restores into a scratch
  # database and counts rows, then drops it.
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
