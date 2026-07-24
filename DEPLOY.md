# Deploying TradeOS to production

This takes you from the repo to a live, HTTPS, self-refreshing TradeOS on your own server. The stack is
four containers: **Postgres**, the **API**, the **scheduler worker** (keeps news/signals/attention/events
fresh), and **Caddy** (automatic Let's Encrypt HTTPS). The database is never exposed to the internet;
Caddy is the only thing the outside world talks to.

Everything below is copy-paste. Budget ~20 minutes.

---

## 0. What you need

- A small Linux server (Ubuntu 22.04+, **2 GB RAM minimum**, 4 GB comfortable) with a public IP.
- A **domain** you control (e.g. `tradeos.example.com`) — required for automatic HTTPS.
  (No domain yet? You can still test over plain HTTP with `DOMAIN=:80`, then add the domain later.)
- Ports **80** and **443** open to the internet (most clouds: open them in the firewall/security group).

## 1. Install Docker on the server

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker "$USER" && newgrp docker   # run docker without sudo
docker version                                     # sanity check
```

## 2. Get the code

```bash
git clone https://github.com/DoubleX11/tradeos.git && cd tradeos
git checkout game-changer                          # or main, once merged
```

## 3. Configure secrets

```bash
cp .env.production.example .env.production
nano .env.production
```
Set at least:
- `DOMAIN` — your domain (or `:80` for an HTTP-only test).
- `POSTGRES_PASSWORD` — a long random string: `openssl rand -base64 30`.
- `SEC_USER_AGENT` — `TradeOS you@yourdomain.com` (a real contact address; SEC policy).
- (recommended) `EXPLAIN_PROVIDER=gemini` + `GEMINI_API_KEY=...` to turn on live AI. Leave as
  `template` to run fully on the deterministic prose (no key needed).

`.env.production` is gitignored — it never gets committed.

## 4. Point DNS at the server

Create an **A record**: `tradeos.example.com → <your server IP>`. Wait for it to resolve
(`dig +short tradeos.example.com` should show your IP) before the next step, so Caddy can issue the cert.

## 5. Build and start

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build
```
Caddy will obtain a TLS certificate on first request (watch with `docker compose -f docker-compose.prod.yml logs -f caddy`).

## 6. Preflight, migrate, bootstrap data, seed

```bash
C="docker compose -f docker-compose.prod.yml --env-file .env.production"

$C run --rm api python -m tradeos.cli preflight        # verify config (fails loud if something's off)
$C run --rm api python -m tradeos.cli migrate          # create the schema

# One-time data bootstrap (the worker keeps it fresh afterward). Ticker universe first:
$C run --rm api python -m tradeos.cli sync-tickers
# Then let the scheduler fill the rest, or force a first pass now:
$C run --rm worker python -m tradeos.cli scheduler --once --force

# A ready-to-use demo account (optional) and your admin login:
$C run --rm api python -m tradeos.cli seed-demo
TRADEOS_ADMIN_PASSWORD='your-admin-pw' $C run --rm -e TRADEOS_ADMIN_PASSWORD api \
    python -m tradeos.cli seed-admin --email you@yourdomain.com
```

For the deep SEC signal history (insiders/activists/funds + calibration), run the backfill recipes in
`Makefile` (`ingest-*`, `compute-signals`, `ingest-prices`, `run-backtest`) — this is quota-paced and
can run over a day; the product is fully usable before it finishes.

## 7. Verify

```bash
curl -s https://tradeos.example.com/health          # {"ok":true}
docker compose -f docker-compose.prod.yml ps        # all four services "Up"; worker running
docker compose -f docker-compose.prod.yml logs --tail=20 worker
```
Open `https://tradeos.example.com` in a browser → the marketing landing; sign up → the Morning Brief.

---

## Operations

- **Logs:** `docker compose -f docker-compose.prod.yml logs -f api` (or `worker`, `caddy`).
- **Update to new code:**
  ```bash
  git pull
  docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build
  docker compose -f docker-compose.prod.yml --env-file .env.production run --rm api python -m tradeos.cli migrate
  ```
- **Back up the database:**
  ```bash
  docker compose -f docker-compose.prod.yml exec db pg_dump -U tradeos tradeos | gzip > backup-$(date +%F).sql.gz
  ```
- **Restore:** `gunzip -c backup.sql.gz | docker compose -f docker-compose.prod.yml exec -T db psql -U tradeos tradeos`

## Notes

- **AI:** with no key, every AI surface (brief summary, "why", chart read) falls back to deterministic
  prose — the product is complete without it. Set `EXPLAIN_PROVIDER=gemini` + `GEMINI_API_KEY` (a paid
  key avoids the free tier's ~5 req/min cap) to turn on the live AI everywhere.
- **Live social discussion:** Reddit's API is reachable from a normal server IP (unlike datacenter
  ranges) — add a free app's `REDDIT_CLIENT_ID`/`REDDIT_CLIENT_SECRET` to light it up.
- **Billing:** empty Stripe vars = free launch mode (payment UI visible, no charge). Fill them + add
  `stripe` to `requirements.txt` to take real payments.
- **Scaling:** the API is stateless — raise `--workers` or run multiple API replicas behind Caddy. Keep
  exactly **one** worker container (the scheduler must not double-run).
