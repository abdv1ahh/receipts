# Receipts — common tasks.
# Prereqs: Docker with Compose, and a .env carrying an Alpaca key pair. `./scripts/setup.sh`
# writes the .env; `make quickstart` does the rest.

X = docker compose exec -T api python -m tradeos.cli

.PHONY: quickstart test test-js dev web lint fix up down logs

# Everything a stranger needs on a fresh clone: migrate, then load enough recent price data to
# publish a call on.
#
# EVERY SYMBOL, A SHORT WINDOW — not a few symbols and a long one, and the difference is the whole
# point. The obvious first version was `--limit 400` over a year, which is quick and useless: the
# work list sorts by staleness and every symbol on a fresh database is equally stale, so it falls
# back to sorting by SYMBOL and the 400 are the alphabetical first 400 of 13,170. Measured on a
# clean clone: A, AA, AAA, AAAA, AAAC, AAAP, AAAU … and of the twelve names a person actually
# reaches for, TEN WERE ABSENT — MSFT, NVDA, TSLA, GOOGL, AMZN, META, QQQ, AMD, NFLX, JPM. A
# stranger's first call is on a company they have heard of, and it could not be published. That is
# the same defect as the old insider-signal universe wearing a different hat.
#
# A CALL DOES NOT NEED HISTORY. It is scored on the sessions AFTER it is published: entry is the
# close of the first session following publication, exit the close on or after the horizon. What a
# fresh install needs is that the symbol EXISTS in `prices_eod` with a recent session, and that SPY
# is current — so a month of closes over everything beats a year of closes over the alphabet.
#
# Measured on a clean clone: 13,170 symbols, 12,930 with data, ~176,000 rows, 132 batches, 65
# seconds for a 21-day window. `--universe` reads Alpaca's own asset endpoint and no research
# table, which is why it works on a database that has only ever run `migrate`.
quickstart:
	docker compose up -d --build
	$(X) migrate
	$(X) ingest-prices --universe --start $$(python3 -c "import datetime;print(datetime.date.today()-datetime.timedelta(days=30))")
	@echo ""
	@echo "Ready at http://localhost:8000 — register, claim a handle, publish a call."
	@echo "Every US-listed symbol Alpaca quotes is publishable; run the line below whenever you"
	@echo "want deeper history (about 3.5 hours for a full year, and nothing needs it to work):"
	@echo "  docker compose exec -T api python -m tradeos.cli ingest-prices --universe --start 2024-01-01"
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
	@# And the EXPORT, which is the same wire format checked with no server at all. A broken
	@# export is worse than no export: it is a file that claims to prove a record and does not.
	@test -f export/check.mjs && node export/check.mjs || echo "no export/ in this checkout; skipping"

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
