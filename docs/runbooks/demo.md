# Running the demo from cold

Written 2026-09-02, after the Receipts build. Every command here was run on this machine in that
session. If one of them does not work, fix it here in the same change that discovers it.

---

## The short version

```bash
cd /path/to/tradeos
docker compose up -d db api worker          # or `make dev` while iterating on the UI
open http://localhost:8000/board
```

Sign in as `demo@tradeos.app`, with the password `cli seed-demo` printed when you ran it.
It is generated per instance and shown once; re-run against an empty database to get a new one.

**How long before the demo to start the worker: fifteen minutes.** Not because Receipts needs it —
the Board, the records, the chain verification and the share pages are pure reads of data that is
already sealed, and they are correct one second after the API starts. Fifteen minutes is for the
RESEARCH surfaces standing behind Receipts:

| job | interval | what goes stale without it |
|---|---:|---|
| `crypto_structure` | 240 s | the Crypto positioning read, which caches for 300 s |
| `news_rss` | 1800 s | the News feed's freshness line |
| `spine_news` | 1800 s | new events reaching the spine |
| `warm_brief` | 3600 s | the Morning Brief is computed on first open instead of instantly |
| `resolve_calls` | 21600 s | nothing visible in a demo; horizons are 7 days at the shortest |

One pass of `crypto_structure` and one of `news_rss` is what fifteen minutes buys. Longer does not
help; the shortest horizon in this product is a week.

---

## The order to show it in

1. **`/board`.** Two records, both ours, both labelled. Say out loud that the first thing on the
   board is our own engine and that it is below a coin flip. That is the pitch.
2. **`/record?handle=convergence-v3`.** Scroll to the chain strip and press **Verify chain**. It
   walks all 323 links and takes about a second. Then read the caveat underneath it: the chain is
   tamper evident against the caller and not against us, and this is not a blockchain.
3. **Any miss.** They are above the breakdowns, which is the whole argument. Click one to open the
   proof panel and show that the arithmetic is checkable by hand.
4. **`/publish`.** Claim a handle live and publish a call. The consent panel says in plain language
   that it cannot be edited or deleted. The receipt shows the sequence number, the content hash and
   the hash it chains from.
5. **`/record`** immediately after. The new record is real, it has one call, and it shows **Low N**
   with counts and no percentage. That is the sample gate demonstrating itself on live data, which
   the two house records cannot do because both sit above 25.
6. **`/methodology`.** Every rule on it is read from the code that applies it.

---

## Proving the integrity claim, live, if someone asks

Break the chain and fix it in front of them. This is the only operation in the product that needs
the trigger switched off, and that is exactly the operator hole the methodology page discloses.

```bash
# Break it.
docker compose exec -T db psql -U tradeos -d tradeos <<'SQL'
ALTER TABLE calls DISABLE TRIGGER calls_append_only_trg;
UPDATE calls SET content_hash = 'deadbeef' || substring(content_hash from 9)
 WHERE caller_id = (SELECT id FROM callers WHERE handle = 'convergence-v3') AND seq = 100;
ALTER TABLE calls ENABLE TRIGGER calls_append_only_trg;
SQL

# Press Verify chain: it reports broken at seq 100. Then put it back:
docker compose exec -T db psql -U tradeos -d tradeos -tAc \
  "SELECT content_hash FROM calls WHERE caller_id=(SELECT id FROM callers WHERE handle='convergence-v3') AND seq=100"
```

Save the original hash before breaking it, or reseed. There is no undo, which is the point.

To show the refusals directly instead:

```bash
docker compose exec -T db psql -U tradeos -d tradeos -c \
  "DELETE FROM calls WHERE id = (SELECT id FROM calls LIMIT 1)"
# ERROR:  calls rows are append only and cannot be deleted
```

---

## If the database is empty

```bash
docker compose exec -T api python -m tradeos.cli migrate
docker compose exec -T api python -m tradeos.cli seed-demo
docker compose exec -T api python -m tradeos.cli seed-house-records
docker compose exec -T api python -m tradeos.cli verify-chain convergence-v3
```

`seed-house-records` imports our own signal engine's resolved claims and invents nothing. It
refuses to run twice: an append-only record is never imported again.

---

## If prices are stale

SPY is the benchmark for every score in this product, so it goes first. `--only-stale` selects
relative to the freshest close in the table, which means it selects NOTHING when every symbol is
equally behind — fetch SPY by name to move the frontier before the selector can work.

```bash
docker compose exec -T api python -m tradeos.cli ingest-prices --symbols SPY --start 2026-08-15
nohup bash scripts/topup-prices.sh >> /tmp/rhumb-topup.log 2>&1 &
```

Free Tiingo paces at roughly 45 to 57 unique symbols an hour, so a 500 symbol backlog is most of a
day. It is resumable by construction: the work list is re-derived from the database on every pass.

---

## What to say if someone asks about the AI surfaces

Be straight about it. `EXPLAIN_PROVIDER=gemini,openai`. Gemini works but sits at the edge of its
free daily allowance, and the second link points at GitHub Models, which has been answering
**HTTP 410 `github_models_retirement_brownout`** since it was retired. When both are unavailable
every AI surface falls back to its deterministic template and says so; the impact engine writes
nothing at all rather than fabricating a claim.

`/integrations` reports this now, per link, which it could not do before — the model chain was not
in the source registry at all. `docs/state.md` has the three environment variables that fix it.
