"""Billing, plans, and entitlements (Slice D).

Card data never touches these servers: real payment goes through Stripe Checkout (hosted) and
state changes arrive as signature-verified, idempotent webhooks. Until a Stripe key is configured
the module runs in TEST MODE — the upgrade flow works end to end with no charge and is labeled as
such, and the self-serve test activation is only reachable while unconfigured, never in production.

Entitlements are enforced off `users.tier` (the same field that drives the bypass-proof 48h delay),
so upgrading structurally unlocks live signals without any client flag.
"""
from __future__ import annotations

import logging
import os

import psycopg
from psycopg.types.json import Json

from . import authn

log = logging.getLogger("tradeos.billing")

# The tier KEYS are unchanged and must stay that way: `users.tier` holds them, ENTITLEMENTS is
# keyed on them, and the 48h delay is enforced off them. Only the display names, the prices and the
# copy move, because the product they describe moved. Renaming a tier key would silently re-tier
# every existing account.
#
# `blurb` is what each plan is FOR, in one line, because a price list of feature bullets does not
# tell a newsletter operator why they would pay us anything.
PLANS = {
    "free":   {"name": "Reader", "price": 0,  "tier": "free",
               "blurb": "Every record, the board, the methodology, and chain verification. Free "
                        "forever, and no account needed to read."},
    "retail": {"name": "Caller", "price": 19, "tier": "retail", "price_id_env": "STRIPE_PRICE_RETAIL",
               "blurb": "A verified record page of your own, unlimited calls, the share card and "
                        "the embed."},
    "pro":    {"name": "Desk",   "price": 99, "tier": "pro",    "price_id_env": "STRIPE_PRICE_PRO",
               "blurb": "Multiple handles, the data API, and exports."},
}

# Server-side entitlements per tier. live_signals maps to the 48h delay (decision #36); the limits
# are enforced in the write paths so a free user editing a request can never exceed them.
#
# `exposure` was added in Phase 8 to match the split the brief specifies — free gets the Radar with
# delayed data and limited alerts, paid gets live data, unlimited alerts, the full Exposure surface
# and API access. It is a boolean here and checked in the READ path, unlike the others which cap
# writes, because Exposure is a view rather than a thing you accumulate.
#
# What is deliberately NOT gated, at any tier: the Ledger and the marketing site's public
# endpoints. An accuracy record behind a paywall is not an accuracy record.
ENTITLEMENTS = {
    "free":   {"live_signals": False, "max_follows": 5,      "max_portfolios": 1,    "max_trades": 50,     "realtime_alerts": False, "api": False, "exposure": False},
    "retail": {"live_signals": True,  "max_follows": 1000,   "max_portfolios": 50,   "max_trades": 5000,   "realtime_alerts": True,  "api": False, "exposure": True},
    "pro":    {"live_signals": True,  "max_follows": 100000, "max_portfolios": 1000, "max_trades": 100000, "realtime_alerts": True,  "api": True,  "exposure": True},
    "admin":  {"live_signals": True,  "max_follows": 100000, "max_portfolios": 1000, "max_trades": 100000, "realtime_alerts": True,  "api": True,  "exposure": True},
}


def entitlements(tier: str | None) -> dict:
    return ENTITLEMENTS.get(tier or "free", ENTITLEMENTS["free"])


def provider_configured() -> bool:
    """True only when a real Stripe key is set AND the SDK is importable — otherwise TEST MODE."""
    if not os.environ.get("STRIPE_SECRET_KEY"):
        return False
    try:
        import stripe  # noqa: F401
        return True
    except Exception:
        return False


def _set_plan(conn: psycopg.Connection, user_id: int, plan: str, provider: str, status: str = "active",
              sub_id: str | None = None, cust_id: str | None = None, period_end=None) -> None:
    tier = PLANS[plan]["tier"]
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO subscriptions (user_id, plan, status, provider, provider_subscription_id,
                                          provider_customer_id, current_period_end, updated_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s, now())
               ON CONFLICT (user_id) DO UPDATE SET plan=EXCLUDED.plan, status=EXCLUDED.status,
                   provider=EXCLUDED.provider, provider_subscription_id=EXCLUDED.provider_subscription_id,
                   provider_customer_id=EXCLUDED.provider_customer_id,
                   current_period_end=EXCLUDED.current_period_end, updated_at=now()""",
            (user_id, plan, status, provider, sub_id, cust_id, period_end),
        )
        cur.execute("UPDATE users SET tier=%s WHERE id=%s AND tier <> 'admin'", (tier, user_id))
    conn.commit()
    authn.audit(conn, str(user_id), "billing_set_plan", plan, {"provider": provider, "status": status})


_TIER_PLAN = {"admin": "pro", "pro": "pro", "retail": "retail", "free": "free"}


def current_subscription(conn: psycopg.Connection, user_id: int) -> dict:
    with conn.cursor() as cur:
        cur.execute("SELECT plan, status, provider, current_period_end FROM subscriptions WHERE user_id=%s", (user_id,))
        r = cur.fetchone()
        if r:
            return {"plan": r[0], "status": r[1], "provider": r[2],
                    "current_period_end": r[3].isoformat() if r[3] else None}
        # No subscription row (e.g. a seeded admin/pro): the displayed plan follows users.tier,
        # which is the entitlement source of truth, so pricing never contradicts what the user has.
        cur.execute("SELECT tier FROM users WHERE id=%s", (user_id,))
        t = cur.fetchone()
    return {"plan": _TIER_PLAN.get(t[0] if t else "free", "free"), "status": "active",
            "provider": None, "current_period_end": None}


def create_checkout(conn: psycopg.Connection, user: dict, plan: str, base_url: str) -> dict:
    """Start an upgrade. Stripe-hosted Checkout when configured; otherwise a test-mode marker the
    frontend confirms with /test-activate (no charge)."""
    if plan not in ("retail", "pro"):
        return {"error": "unknown plan"}
    if not provider_configured():
        return {"mode": "test", "plan": plan}
    import stripe
    stripe.api_key = os.environ["STRIPE_SECRET_KEY"]
    price_id = os.environ.get(PLANS[plan]["price_id_env"])
    if not price_id:
        return {"error": f"server missing {PLANS[plan]['price_id_env']}"}
    session = stripe.checkout.Session.create(
        mode="subscription", line_items=[{"price": price_id, "quantity": 1}],
        success_url=f"{base_url}/?upgraded={plan}", cancel_url=f"{base_url}/?checkout=cancel",
        client_reference_id=str(user["id"]), customer_email=user["email"], metadata={"plan": plan},
    )
    return {"mode": "stripe", "url": session.url}


def test_activate(conn: psycopg.Connection, user: dict, plan: str) -> dict:
    """Demo-only self activation. Refuses once a real provider is configured, so it can never be a
    free-upgrade hole in production."""
    if provider_configured():
        return {"error": "test activation is disabled once a payment provider is configured"}
    if plan not in ("free", "retail", "pro"):
        return {"error": "unknown plan"}
    _set_plan(conn, user["id"], plan, "test")
    return {"activated": True, "plan": plan, "test_mode": True}


def cancel(conn: psycopg.Connection, user: dict) -> dict:
    prov = current_subscription(conn, user["id"]).get("provider") or "test"
    if provider_configured() and prov == "stripe":
        try:
            import stripe
            stripe.api_key = os.environ["STRIPE_SECRET_KEY"]
            with conn.cursor() as cur:
                cur.execute("SELECT provider_subscription_id FROM subscriptions WHERE user_id=%s", (user["id"],))
                r = cur.fetchone()
            if r and r[0]:
                stripe.Subscription.modify(r[0], cancel_at_period_end=True)
        except Exception as exc:
            # The local downgrade still happens — the user asked to cancel — but a provider
            # failure here means the subscription may still be live upstream. Never silent.
            log.warning("stripe cancel failed for user %s (%s)", user["id"], type(exc).__name__)
    _set_plan(conn, user["id"], "free", prov, status="canceled")
    return {"canceled": True}


def handle_webhook(conn: psycopg.Connection, body: bytes, sig_header: str | None) -> dict:
    """Verify and apply a Stripe webhook. Idempotent on the Stripe event id."""
    secret = os.environ.get("STRIPE_WEBHOOK_SECRET")
    if not (provider_configured() and secret):
        return {"error": "webhooks not configured"}
    import stripe
    try:
        event = stripe.Webhook.construct_event(body, sig_header, secret)
    except Exception:
        return {"error": "invalid signature"}
    obj = event["data"]["object"]
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO billing_events (provider, event_type, provider_event_id, payload) "
            "VALUES ('stripe',%s,%s,%s) ON CONFLICT (provider_event_id) DO NOTHING RETURNING id",
            (event["type"], event["id"], Json(obj)),
        )
        fresh = cur.fetchone() is not None
    conn.commit()
    if not fresh:
        return {"ok": True, "duplicate": True}
    if event["type"] == "checkout.session.completed":
        uid = obj.get("client_reference_id")
        plan = (obj.get("metadata") or {}).get("plan")
        if uid and plan in ("retail", "pro"):
            _set_plan(conn, int(uid), plan, "stripe", status="active",
                      sub_id=obj.get("subscription"), cust_id=obj.get("customer"))
    elif event["type"] in ("customer.subscription.deleted", "customer.subscription.paused"):
        with conn.cursor() as cur:
            cur.execute("SELECT user_id FROM subscriptions WHERE provider_subscription_id=%s", (obj.get("id"),))
            r = cur.fetchone()
        if r:
            _set_plan(conn, r[0], "free", "stripe", status="canceled")
    return {"ok": True}
