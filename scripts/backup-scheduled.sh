#!/usr/bin/env bash
# The wrapper launchd should call, instead of calling backup.sh directly.
#
# WHY THIS IS A SEPARATE FILE. `backup.sh` deliberately knows nothing about Docker: it connects to
# a Postgres port, and that is all it should ever do, because the day this database moves to a
# managed host the backup must keep working with no edit. But TODAY Postgres runs inside Docker on
# a laptop, and the laptop is the problem — measured 2026-09-09, eleven of the previous twelve
# nightly runs failed with `dial unix .../docker.sock: no such file or directory`, because Docker
# Desktop is a GUI application that does not start itself and nothing was starting it at 03:15.
#
# Environment-wrangling belongs in the scheduler's wrapper, not in the backup. So this file holds
# every piece of laptop-specific ugliness and `backup.sh` holds none of it. When Postgres stops
# living in Docker, delete this file and point launchd back at backup.sh.
#
# INSTALL: point ~/Library/LaunchAgents/app.rhumb.backup.plist at this script instead of
# backup.sh, then `launchctl unload` and `launchctl load` it. Exact commands in
# docs/runbooks/backups.md.

set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

WAIT_SECONDS="${DOCKER_WAIT_SECONDS:-300}"
log() { echo "[scheduled] $(date '+%Y-%m-%d %H:%M:%S') $*"; }

log "nightly backup starting"

if ! command -v docker >/dev/null 2>&1; then
  echo "[scheduled] FAILED: no docker binary on PATH (launchd starts jobs without /usr/local/bin;" >&2
  echo "[scheduled]         the plist must set PATH explicitly)" >&2
  exit 1
fi

# Start Docker Desktop if it is not already up, then WAIT for the daemon rather than assuming.
# `open -a Docker` returns immediately; the daemon takes tens of seconds, and the old failure was
# essentially a race nobody was waiting on.
if ! docker info >/dev/null 2>&1; then
  log "Docker daemon is down; starting Docker Desktop and waiting up to ${WAIT_SECONDS}s"
  open -a Docker 2>/dev/null || { echo "[scheduled] FAILED: could not launch Docker Desktop" >&2; exit 1; }
  waited=0
  until docker info >/dev/null 2>&1; do
    sleep 5; waited=$((waited + 5))
    if [ "$waited" -ge "$WAIT_SECONDS" ]; then
      echo "[scheduled] FAILED: Docker daemon did not come up within ${WAIT_SECONDS}s" >&2
      exit 1
    fi
  done
  log "Docker daemon ready after ${waited}s"
else
  log "Docker daemon already running"
fi

# The database container specifically. Starting it is safe and idempotent; note this brings up ONLY
# db, never the worker, so a backup never quietly starts ingestion.
if ! docker compose ps --status running --services 2>/dev/null | grep -qx db; then
  log "db container is not running; starting it"
  docker compose up -d db >/dev/null 2>&1
fi

waited=0
until [ "$(docker inspect tradeos-db-1 --format '{{.State.Health.Status}}' 2>/dev/null)" = "healthy" ]; do
  sleep 3; waited=$((waited + 3))
  if [ "$waited" -ge 120 ]; then
    echo "[scheduled] FAILED: db container did not become healthy within 120s" >&2
    exit 1
  fi
done
log "db healthy; handing over to backup.sh"

exec ./scripts/backup.sh "$@"
