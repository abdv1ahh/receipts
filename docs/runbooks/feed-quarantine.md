# Runbook: feed quarantine and restore

A feed that degrades must degrade loudly, not silently (honesty rule 6). This runbook covers
verifying a suspect feed and restoring it.

## Signals that a feed is degrading
- `feed_health.rejects_total` climbing for a source (visible on the dashboard status strip).
- A day that produced zero records when the market was open (an empty feed that looks healthy).
- Schema-drift errors in `ingest_rejects` after an upstream format change.
- A source's freshest `knowable_time` frozen while time moves on.

## Quarantine (stop trusting it)
1. Confirm the pattern in `ingest_rejects` and `feed_health` — read the actual reject reasons.
2. Stop scheduled ingestion for that source; the modular flags let a source be disabled without
   touching the others (congress / short-interest via `feature_flags`; a signal input via a
   definition version).
3. If the feed already fed the signal, exclude it from convergence (a definition version bump
   with a changelog) so no cluster rests on a compromised source. The point-in-time store means
   derived tables can be rebuilt from the append-only raw layer once the feed is trusted again.

## Verify
- Fetch a fresh sample manually through the same throttled/allowlisted client and compare to a
  known-good prior payload (the raw layer stores the sha256, so integrity is checkable).
- If it was a format change, fix the parser, add a fixture + parser test, and reprocess the raw
  payloads (no re-fetch needed — they are stored).
- If it was upstream corruption or a suspected poisoning attempt, keep it quarantined and note
  it in the decision log.

## Restore
1. Re-enable ingestion; watch `feed_health` reject counts return to baseline.
2. Re-run the affected day(s); idempotency makes this safe (re-ingestion is a no-op on
   already-stored records).
3. If a signal definition was changed to exclude the source, restore it with a new version +
   changelog once the feed is trusted, then recompute and re-backtest.
