#!/usr/bin/env bash
# Paced price top-up for Rhumb, sized to the FREE Tiingo tier.
#
# WHY THIS EXISTS: `ingest-prices` fetches as fast as it can, and free Tiingo does not allow that.
# Measured 2026-08-24 on this key: the 429s begin at roughly **57 unique symbols in an hour**, and
# `TiingoClient` retries a 429 exactly once after 30s before rejecting the symbol. So a single
# unpaced pass over 400+ symbols does not fetch 400 symbols — it fetches about 50 and then burns
# the rest of the run on 429s, spending quota to store nothing. This loop keeps each pass under
# the ceiling and waits out the window.
#
# It is resumable by construction: `--only-stale` re-derives the work list from the database on
# every pass, so a symbol that succeeded drops out and an interrupted run is restarted by simply
# running it again. Nothing is checkpointed because nothing needs to be.
#
#   ./scripts/topup-prices.sh                 # bring every stale symbol current
#   BATCH=30 PAUSE=3600 ./scripts/topup-prices.sh
#   START=2026-07-20 ./scripts/topup-prices.sh   # how far back each fetch reaches
#
# Roughly 45 symbols/hour, so ~9 hours for a 400-symbol backlog. Run it detached and read the log:
#   nohup ./scripts/topup-prices.sh >> /tmp/rhumb-topup.log 2>&1 &
#
set -euo pipefail

BATCH="${BATCH:-45}"          # under the measured ~57/hour ceiling, with headroom
PAUSE="${PAUSE:-3600}"        # the rate-limit window
START="${START:-2026-07-20}"  # overlap the existing tail; the upsert makes re-fetch harmless
MAX_PASSES="${MAX_PASSES:-40}"

# The running api container has its code baked in, so a CLI flag added since the last image build
# is not there. In production that is what you want. Under `make dev`, override with the mounted
# form so the loop runs the working tree:
#   CLI="docker compose run --rm -T -v $PWD/tradeos:/app/tradeos api python -m tradeos.cli"
CLI="${CLI:-docker compose exec -T api python -m tradeos.cli}"

remaining() {
  docker compose exec -T db psql -U tradeos -d tradeos -t -A -c \
    "SELECT count(*) FROM (SELECT symbol, max(day) d FROM prices_eod GROUP BY 1) s
      WHERE d < (SELECT max(day) FROM prices_eod)"
}

for pass in $(seq 1 "$MAX_PASSES"); do
  left="$(remaining)"
  if [ "$left" -eq 0 ]; then
    echo "$(date -u +%FT%TZ) all symbols current; done"
    exit 0
  fi
  echo "$(date -u +%FT%TZ) pass $pass: $left stale, fetching up to $BATCH"
  # A failing pass must not kill the loop — one bad symbol is a reject, not a reason to stop.
  $CLI ingest-prices --only-stale --limit "$BATCH" --start "$START" || \
    echo "$(date -u +%FT%TZ) pass $pass failed; continuing"
  left="$(remaining)"
  [ "$left" -eq 0 ] && { echo "$(date -u +%FT%TZ) all symbols current; done"; exit 0; }
  echo "$(date -u +%FT%TZ) $left still stale; sleeping ${PAUSE}s for the rate-limit window"
  sleep "$PAUSE"
done

echo "$(date -u +%FT%TZ) stopped after $MAX_PASSES passes with $(remaining) still stale"
