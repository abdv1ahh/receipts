# TradeOSS — one-command demo build and common tasks.
# Prereqs: Docker with Compose; a .env with SEC_USER_AGENT (and optional TIINGO_API_KEY,
# GEMINI_API_KEY for prices + LLM explanations).

X = docker compose exec -T api python -m tradeos.cli

.PHONY: demo test up down logs seed backfill-full

# Reproducible demo from scratch. Uses a QUICK data window (a few weeks) so it finishes in
# minutes; the full 24-month backfill (backfill-full) is a separate overnight job.
demo:
	docker compose up -d --build
	$(X) migrate
	$(X) sync-tickers
	$(X) backfill-13dg --from 2026-05-11 --to 2026-06-12
	$(X) backfill-form4 --from 2026-05-11 --to 2026-06-12
	$(X) resolve-entities
	$(X) ingest-13f --date 2026-07-14 --limit 60
	$(X) resolve-cusips --limit 700
	$(X) ingest-short-interest --start 2026-05-01
	$(X) signals-register --changelog "convergence v1 (initial)"
	$(X) compute-signals --daily --from 2026-05-11 --to 2026-06-12
	$(X) compute-signals
	$(X) ingest-prices --symbols-from-clusters --start 2026-01-01
	$(X) run-backtest
	$(X) sync-library
	$(X) create-invites --n 5
	@echo ""
	@echo "TradeOSS demo ready at http://localhost:8000"
	@echo "Next: create the admin (prompts for a password):"
	@echo "  docker compose exec api python -m tradeos.cli seed-admin --email you@example.com"

# The deep, publishable calibration sample (runs for hours; do before any public launch).
backfill-full:
	$(X) backfill-13dg --from 2024-07-01 --to 2026-07-14
	$(X) backfill-form4 --from 2024-07-01 --to 2026-07-14
	$(X) resolve-entities

test:
	docker compose run --rm -T api python -m pytest tests/ -q

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f api
