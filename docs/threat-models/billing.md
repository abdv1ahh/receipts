# Threat model — billing, entitlements, Pro API keys (Slice D)

Scope: migration 012 (`subscriptions`, `billing_events`, `api_keys`), `tradeos/billing.py`,
`tradeos/apikeys.py`, and the `/api/billing/*`, `/api/keys*`, `/api/v1/*` endpoints. This is the
surface that sits directly on money, so PCI scope, entitlement bypass, and data exfiltration are the
defining threats.

## Assets
- **Payment credentials** — must never touch TradeOS (PCI scope = zero).
- **Entitlements** — a free user must not reach a paid capability by editing a request.
- **The paid dataset** — the commercial attack is scraping the signals and reselling them.
- **Billing integrity** — every state change must be authentic and auditable.

## Attacks and the design that stops them
1. **Card data on our servers (PCI).** Never happens: upgrades use **hosted Stripe Checkout**; the
   server only ever sees a subscription id and status via webhook. No card field is accepted anywhere.
2. **Forged billing state / replayed webhooks.** Webhooks are verified with
   `stripe.Webhook.construct_event` (HMAC signature) and are **idempotent** — the Stripe event id is a
   unique key in `billing_events`, so a replay is a no-op. Every plan change is written to the append-only
   `audit_log`.
3. **Free-upgrade hole via test activation.** `test-activate` exists only for the demo and refuses the
   moment `provider_configured()` is true (a real Stripe key is set). In production the only path to a
   paid tier is a completed Checkout + verified webhook.
4. **Entitlement bypass by parameter tampering.** Entitlements derive from `users.tier` server-side
   (the same field as the delay paywall, #36), never from a client flag. Write limits (follows,
   portfolios) are checked in the POST handlers. A free user editing any request still hits the cap.
5. **Signal exfiltration through the API (the defining commercial attack).** API keys are **scoped,
   rotatable, and stored only as a sha256 hash** (raw shown once). Each key carries a **canary**; every
   `/api/v1` response includes `meta.trace = sha256(canary:day)`, so a resold dump is traceable to the
   leaking key. Per-key **rate limiting** caps bulk scraping, and API access is a Pro-only entitlement.
   The v1 view respects the tier's effective as_of, so a key cannot reach fresher data than its tier.
6. **IDOR on keys / subscriptions.** Key list/revoke and subscription reads are scoped to the session
   `user_id`; a key id from another account revokes nothing. Raw keys are never returned after creation.
7. **Injection via the webhook body.** The body is parsed only by the Stripe SDK after signature
   verification; unverified bodies are rejected before any processing.

## Residual / deferred (named, not silently assumed)
- A **shared/edge rate limiter** replaces the in-memory per-key limiter (does not span processes).
- **Anomaly detection** on API access patterns, key scope granularity beyond `read`, and usage metering
  land with the commercial API rollout.
- Going live requires a Stripe account, `stripe` pinned in requirements, and the four `STRIPE_*` env
  values (see `.env.example`); a webhook endpoint secret must be configured before enabling live keys.
