# Receipts — common tasks.
# Prereqs: Docker with Compose, and a .env carrying an Alpaca key pair. `./scripts/setup.sh`
# writes the .env; `make quickstart` does the rest.

X = docker compose exec -T api python -m tradeos.cli

.PHONY: quickstart test test-js dev web lint fix up down logs

# Everything a stranger needs on a fresh clone: migrate, then load enough recent price history to
# publish a call on. 400 symbols over one year is ~19 seconds measured, which is the right size for
# a first run — the full 13,170-symbol universe takes about 3.5 hours and is documented in the
# README as an overnight job rather than put in anybody's way here.
#
# `--universe` reads Alpaca's own asset endpoint and no research table, which is why this works on
# a database that has only ever run `migrate`.
quickstart:
	docker compose up -d --build
	$(X) migrate
	$(X) ingest-prices --universe --limit 400 --start $$(python3 -c "import datetime;print(datetime.date.today()-datetime.timedelta(days=365))")
	@echo ""
	@echo "Ready at http://localhost:8000 — register, claim a handle, publish a call."
	@echo "Optional, to put our own 473-call record on your board:"
	@echo "  docker compose exec api python -m tradeos.cli seed-house-records"

# tests/ is deliberately NOT copied into the image (test files have no business in a production
# artifact), so the suite runs against a mount. `make test` used to fail with "file or directory
# not found" because it omitted this.
test:
	docker compose run --rm -T \
	  -v "$(CURDIR)/tests:/app/tests" -v "$(CURDIR)/tradeos:/app/tradeos" \
	  -v "$(CURDIR)/frontend/src:/app/frontend/src:ro" \
	  api python -m pytest tests/ -q

# The JavaScript half of the cross-language guard on the sealed wire format, run on the HOST.
#
# `chain.py` and `receipts/verify.js` must produce byte-identical payloads forever: the public
# record page lets a visitor recompute the chain in their own browser, and a JS framing that
# disagrees by one byte would report every intact record as broken. `make test` cannot check that —
# it runs inside the API image, which carries no node — so both sides check one committed fixture
# instead (tests/fixtures/receipt_chain.json). Node is already a prerequisite for `make web`.
test-js:
	node tests/verify_js_check.mjs

# Development stack: Python reloads in place, tests/ is mounted, and the locally built frontend is
# served, so a UI change needs only `make web` instead of a full image rebuild.
dev:
	docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build

web:
	cd frontend && npm run build

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
