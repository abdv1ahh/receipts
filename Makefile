# TradeOSS — one-command demo build and common tasks.
# Prereqs: Docker with Compose; a .env with SEC_USER_AGENT (and optional TIINGO_API_KEY,
# GEMINI_API_KEY for prices + LLM explanations).

X = docker compose exec -T api python -m tradeos.cli

.PHONY: demo test dev web site lint fix up down logs seed backfill-full

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

# tests/ is deliberately NOT copied into the image (test files have no business in a production
# artifact), so the suite runs against a mount. `make test` used to fail with "file or directory
# not found" because it omitted this.
test:
	docker compose run --rm -T \
	  -v "$(CURDIR)/tests:/app/tests" -v "$(CURDIR)/tradeos:/app/tradeos" \
	  -v "$(CURDIR)/frontend/src:/app/frontend/src:ro" \
	  api python -m pytest tests/ -q

# Development stack: Python reloads in place, tests/ is mounted, and the locally built frontend is
# served, so a UI change needs only `make web` instead of a full image rebuild.
dev:
	docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build

web:
	cd frontend && npm run build

# The marketing site (Phase 7). A sibling Vite project; same 0.3s loop as `web` under `make dev`,
# served at /site. First run needs `cd site && npm install`.
site:
	cd site && npm run build

# Ruff is the linter. It is deliberately NOT the formatter here — see the note in pyproject.toml.
lint:
	docker compose run --rm -T --user root -v "$(CURDIR):/src" -w /src \
	  api sh -c "pip install --quiet --root-user-action=ignore 'ruff==0.16.5' && python -m ruff check tradeos tests"

fix:
	docker compose run --rm -T --user root -v "$(CURDIR):/src" -w /src \
	  api sh -c "pip install --quiet --root-user-action=ignore 'ruff==0.16.5' && python -m ruff check --fix tradeos tests"

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f api
