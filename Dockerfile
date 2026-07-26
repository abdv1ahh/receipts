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
COPY requirements.txt .
# pip is upgraded first: the version bundled with the base image carries its own advisories, and
# although it only ever runs at build time (the container runs as a non-root user that never
# installs anything), leaving a known-vulnerable tool in the image makes every future audit noisy
# enough to stop being read.
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir -r requirements.txt
COPY tradeos ./tradeos
COPY content ./content
COPY --from=web /src/frontend/dist ./tradeos/static
# run as a non-root user (production additionally pins the base image by digest)
RUN useradd --create-home --uid 10001 appuser && mkdir -p /app/uploads && chown -R appuser:appuser /app
USER appuser
EXPOSE 8000
CMD ["uvicorn", "tradeos.app:app", "--host", "0.0.0.0", "--port", "8000"]
