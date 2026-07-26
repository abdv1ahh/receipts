# docs/dead_code.md — unused, stale, and orphaned, with a recommendation for each

Compiled 2026-07-25 by AST-walking every Python module for unused imports, cross-referencing
every JSX export against its importers, matching all 98 API routes against frontend call
sites, diffing environment variables read in code against `.env.example`, and reading every
markdown file at the repository root.

Legend: **DELETE** safe to remove now · **FIX** wrong, must be corrected not deleted ·
**ASK** cannot confirm without the owner.

---

## Safe deletions

### D-01 · `frontend/src/home.jsx` (208 lines) — **DELETE**
Exports `Home(...)`. Nothing imports it; `grep -rn 'from "./home' frontend/src/` returns
nothing. Superseded by `smartmoney.jsx` (`SmartMoneyView`), which `App.jsx` actually renders
for the `home` view. The stale filename is actively confusing: a reader looking for the
"home" surface finds a component nothing renders.

### D-02 · `frontend/src/scanner.jsx` (94 lines) — **DELETE**
Exports `ScannerView(...)`. No importers. Superseded by `social.jsx` (`SocialView`). The
matching CSS block `/* ---- Sentiment & Trend Scanner (Slice H) --- */` at
`frontend/src/styles.css:533` should be checked for orphaned rules when this goes.

### D-03 · Five unused imports — **DELETE**
| File | Line | Import |
|---|---|---|
| `tradeos/ingestion/news_sec.py` | 22 | `datetime` |
| `tradeos/intelligence/vision.py` | 15 | `base64` |
| `tradeos/news.py` | 12 | `math` |
| `tradeos/news.py` | 17 | `config` |
| `tradeos/signals/convergence.py` | 22 | `timezone` |

`from __future__ import annotations` appears "unused" in 55 modules; that is a false positive
of the AST sweep. Leave those alone.

### D-04 · `trading_intelligence .md` (19 KB, root, **note the space in the filename**) — **DELETE**
The original build brief for a previous generation of this project ("Build Brief for Claude
Fable 5"). Superseded in full by `docs/tradeoss_veryimportant_prompt.md`. The space in the
filename breaks tab completion and shell globs. Its historical value is already preserved in
git. Recommend deleting from the working tree; git keeps the archive.

### D-05 · `.DS_Store` at repository root — **DELETE**
Present in the working tree, correctly gitignored, but still on disk. Harmless, remove.

### D-06 · Two documents already deleted but not committed — **DELETE (commit the deletion)**
`git status` shows ` D tradeos-build-plan.md` and ` D tradeos-feature-spec-5.5.md` — removed
from the working tree, deletion unstaged. Nothing in the repo references either filename
(verified by grep across all `.md` and `.py`). Commit the deletions so the tree is clean.

---

## Stale — must be fixed, not deleted

### F-01 · `cli preflight` provider validation — **FIX**
Rejects `EXPLAIN_PROVIDER=openai` (which `llm.py` implements and the app is running on) and
offers `anthropic` (which `llm.py` does not implement). This is the most dangerous category
of stale code: a check that is confidently wrong. See `docs/bugs.md` B-05.

### F-02 · `README.md` line 40 — **FIX**
Documents `python -m pytest tests/ -q  # 13 tests, all offline`. The command fails inside the
container (tests are not copied into the image) and the count is wrong (189). See B-06.

### F-03 · `Makefile` target `test` — **FIX**
`docker compose run --rm -T api python -m pytest tests/ -q` fails for the same reason. Either
mount `tests/` in the target or add `COPY tests ./tests` to the Dockerfile. Mounting is
preferable — test files have no business in a production image.

### F-04 · `.env.example` drift — **FIX**
Missing ten variables the code reads: `OPENAI_BASE_URL`, `OPENAI_API_KEY`, `OPENAI_MODEL`,
`SENTRY_DSN`, `OPENFIGI_API_KEY`, `TRADEOS_ADMIN_PASSWORD`, `TRADEOS_DEMO_EMAIL`,
`TRADEOS_DEMO_PASSWORD`, `UPLOADS_DIR`, `DATABASE_URL`. Each entry should carry a comment
naming where the key is obtained (brief §9). Conversely `STRIPE_PRICE_RETAIL` /
`STRIPE_PRICE_PRO` appear only in `docker-compose.yml` and `.env.example`, never in Python —
see A-03.

### F-05 · Comment in `tradeos/flags.py:30` describes rows that still exist — **FIX**
The comment says "the dead seed rows in feature_flags (congress/short_interest/signals/
previews) are ignored here". They are indeed ignored by the console, but they are still in
the table (`congress=f`, `short_interest=f`, `signals=t`, `previews=t`). Either drop the rows
in a migration or reword the comment to say they are inert historical rows. A comment saying
something is "dead" while it sits live in the database will mislead the next reader.

---

## Cannot confirm — asking before touching

### A-01 · `tradeos/ingestion/finra.py` + the `short_interest` table — **RESOLVED: KEEP, PARKED**
Owner ruling 2026-07-26: keep. Short interest stays ingested and stored against a future
convergence-score version bump (decision #31). It is **deliberately dormant, not debris** —
`config.short_interest_enabled()` is the switch and `ENABLE_SHORT_INTEREST` is false. Do not
"clean this up" in a later pass; this line is the record that it was considered and kept.

### A-02 · `ENABLE_CONGRESS` + `congress` flag row — **RESOLVED: REMOVED**
Owner ruling 2026-07-26: remove. `config.congress_enabled()` and the admin surface entry are gone,
and **migration 033** deletes the seed row. The flag gated a congressional-disclosure source that
was never built; the reasoning stays recorded in `docs/decision-log.md` (#29), which is where a
decision belongs. A live switch for a feature that does not exist only misleads.

### A-03 · Stripe price-id variables — **RESOLVED: THE AUDIT WAS WRONG, KEEP**
This entry claimed "no Python file reads either name". They are read, through an indirection the
original grep missed: `billing.PLANS` stores `price_id_env` and `billing.py:108` does
`os.environ.get(PLANS[plan]["price_id_env"])`. The variables are live configuration for real Stripe
checkout, not vestigial. **Nothing to remove.** Left as a warning that grepping for a literal name
misses config reached through a lookup table.

### A-04 · `tradeos/presentation.py` and `/api/card/{symbol}.svg` + `/s/{symbol}` — **RESOLVED: KEEP**
Keep, as recommended, and it is no longer unreachable: `/s/{symbol}` is a real link-preview page and
its outbound link was corrected on 2026-07-26 (it pointed at `/`, which now redirects a signed-out
visitor to the marketing site and would have dropped the symbol; it points at `/asset?symbol=` now).

### A-05 · `uploads/` at repository root — **RESOLVED: ALREADY GONE**
No such directory exists in the working tree. It was removed at some point after this audit was
compiled. Nothing to do.

### A-06 · `tests/test_gemini.py` — **RESOLVED: NO SUCH FILE, NO RENAME NEEDED**
The audit named a file that does not exist. The real file is `tests/test_explain_gemini.py`, and it
tests `tradeos/explain/gemini.py` — a real module, correctly named for what it covers. The unified
`llm.py` transport has its own `tests/test_llm.py`. There was never anything misleading here.

---

## Explicitly checked and found clean

Recording these so nobody re-audits them:

- **API routes.** All 98 checked against every frontend call site. Only three have no
  frontend caller — `GET /health` (container health check), `GET /api/card/{symbol}.svg`
  (see A-04) and `POST /api/billing/webhook` (called by Stripe, not the browser). No dead
  endpoints.
- **Python modules.** Every non-`__init__.py` module under `tradeos/` is imported by at least
  one other module or test. No orphans.
- **Migrations.** All 23 applied; `schema_migrations` matches the files on disk. No
  migrations for dropped tables.
- **Dependencies.** All ten Python requirements are imported somewhere
  (`fastapi`, `starlette`, `uvicorn`, `httpx`, `psycopg`, `defusedxml`, `argon2-cffi`,
  `pyotp`, `Pillow`, `pytest`). Both JS runtime dependencies (`react`, `react-dom`) are used.
  Nothing to prune — this is unusually clean and worth preserving.
- **Secrets in git history.** `git log --all -- .env` is empty and a regex sweep of all
  tracked files for `sk-*`, `ghp_*`, `github_pat_*`, `AIza*` finds nothing. A full
  gitleaks/trufflehog history scan is Phase 9 work; neither tool is installed yet.
