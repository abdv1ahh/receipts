# --- stage 1: build the React dashboard ---
FROM node:24-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# --- stage 2: the API image, serving the built bundle from tradeos/static ---
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY tradeos ./tradeos
COPY content ./content
COPY --from=web /web/dist ./tradeos/static
# run as a non-root user (production additionally pins the base image by digest)
RUN useradd --create-home --uid 10001 appuser && mkdir -p /app/uploads && chown -R appuser:appuser /app
USER appuser
EXPOSE 8000
CMD ["uvicorn", "tradeos.app:app", "--host", "0.0.0.0", "--port", "8000"]
