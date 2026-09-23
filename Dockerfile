# --- stage 1: build the React dashboard ---
# Layout mirrors the repo (/src/frontend, /src/shared) rather than flattening frontend/ to the
# workdir, because styles.css imports ../../shared/tokens.css — the measurements the app and the
# marketing site share. Flattened, that import resolves outside the build context and the image
# build fails while `make dev` keeps working, since dev serves a bundle built on the host. Phase 7
# introduced the import; Phase 9 found it, on the first full image build since.
FROM node:24-slim AS web
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY shared/ /src/shared/
COPY frontend/ ./
RUN npm run build

# --- stage 2: the API image, serving the built bundle from tradeos/static ---
FROM python:3.12-slim
WORKDIR /app
# TWO OS PACKAGES. The first is for the share card; the second is so the suite can check its own
# schema.
#
# `receipts/card.py` renders the Open Graph image with Pillow. Pillow 12 ships a scalable embedded
# face (Aileron), which is enough to draw a card -- but measured against a private-use codepoint to
# find its tofu signature, Aileron renders U+00E9 (e-acute) as a BOX, along with the em dash, the
# bullet, the check mark and every arrow. A caller whose name carries an accent would have seen
# tofu boxes where their own name should be, on the one asset this product asks them to post. That
# is precisely the failure that makes a distribution model not work.
#
# DejaVu is ~3MB and covers Latin-1, Latin Extended, Greek and Cyrillic, in three families, so the
# card also regains the serif/mono contrast its SVG twin gets from the browser.
# `--no-install-recommends` and the cache cleanup keep the layer to what was asked for. This is an
# OS package, not a Python dependency: `requirements.txt` is untouched and its ten-line rule is not
# in play.
#
# `postgresql-client` is here for `pg_dump`, and it is not a convenience. A fresh install takes
# `migrations/baseline/001_baseline.sql` and an existing one takes the 37 ordered files, and
# `tests/test_migrations.py` proves those two paths produce the same 19 tables by migrating two
# scratch databases and diffing their schemas. Without pg_dump in this image that test SKIPS, and
# a skipped equivalence check is how a fresh install and an upgraded one quietly stop being the
# same product. `scripts/backup.sh` also falls back to a container pg_dump when the host has none.
RUN apt-get update \
 && apt-get install --no-install-recommends -y fonts-dejavu-core postgresql-client \
 && apt-get clean \
 && find /var/lib/apt/lists -type f -delete
COPY requirements.txt .
# pip is upgraded first: the version bundled with the base image carries its own advisories, and
# although it only ever runs at build time (the container runs as a non-root user that never
# installs anything), leaving a known-vulnerable tool in the image makes every future audit noisy
# enough to stop being read.
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir -r requirements.txt
COPY tradeos ./tradeos
# The house records' committed export, 940K. It ships in the image because `cli
# seed-house-records` restores from it: `claims` is the retired signal plane's table, it is in the
# schema and it is empty everywhere but the operator's own database, so on every other install the
# export IS the record. Without this line the command finds nothing and a fresh board has no house
# record at all — which is how it behaved, silently, reporting success.
COPY export ./export
COPY --from=web /src/frontend/dist ./tradeos/static
# run as a non-root user (production additionally pins the base image by digest)
RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /app
USER appuser
EXPOSE 8000
CMD ["uvicorn", "tradeos.app:app", "--host", "0.0.0.0", "--port", "8000"]
