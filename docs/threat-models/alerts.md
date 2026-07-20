# Threat model — follows, alerts, notifications, brief (Slice B)

Scope: `tradeos/alerts.py`, migration 010 (`follows`, `alert_prefs`, `notifications`, `email_outbox`),
and the `/api/follows`, `/api/notifications`, `/api/alert-prefs`, `/api/brief` endpoints. The reach-out
layer sits next to the paid signal, so it inherits the platform's two defining commercial threats
(exfiltration, poisoning) plus the standard account-takeover surface.

## Assets
- The **timing** of fresh (paid-tier) signals. Alerts fire on new convergences; if a free user could
  receive a real-time alert, the 48h paywall (decision #36) would be defeated through the side channel.
- A user's **follows and notifications** (who they watch is private and per-account).
- The **email channel** (a future outbound path; must not become a spam/abuse relay or leak).

## Attacks and the design that stops them
1. **Paywall bypass via the alert side channel.** The engine computes each user's *effective as_of*
   from their tier (`authn.delay_hours`) and only ever gathers/evaluates clusters and filings with
   `knowable_time <= that as_of`. A free user's alerts are therefore generated from the same 48h-delayed
   set as their feed. There is no request parameter that widens this; it is derived server-side from the
   session tier. → the paywall holds through the alert path.
2. **Object reference abuse (IDOR).** Every per-user query is scoped to the session `user_id`
   (`DELETE FROM follows WHERE id=%s AND user_id=%s`, notifications/prefs likewise). A follow_id or
   notification_id from another account matches nothing. Unauthenticated callers get an empty/authed=false
   payload, never another user's data.
3. **Notification spam / self-DoS.** Notifications insert `ON CONFLICT (user_id, dedup_key) DO NOTHING`;
   dedup_keys are stable per underlying event, and a multi-line Form 4 collapses to one alert per
   (insider, issuer, day). Re-running the engine is a no-op. Followed-actor gathers are windowed and
   capped. → no unbounded fan-out.
4. **Signal poisoning amplified by alerts.** Alerts ride on the same convergence gate (≥3 independent
   voices / ≥2 classes) and liquidity floor as the feed, so a single manufactured filing cannot mint a
   high-conviction alert. The alert layer adds no new trust in a source.
5. **Email abuse (future).** Email is not sent in the demo; rows queue in `email_outbox` and are only
   delivered when a provider is wired. When it is: send only to the account's own verified address,
   rate-limit per user, and sign/verify provider webhooks. The queue-only state is shown honestly in the
   UI so no user believes an email was delivered when it was not.
6. **Advice-line drift in alert copy.** Titles/bodies are deterministic, descriptive strings built from
   filing facts ("N insiders bought", "X filed a 13D"); they never tell a user to buy/sell. Same line as
   the rest of the product (decision #34).

## Residual / deferred
- Real email delivery, per-user email rate limits, and webhook signature verification land with the
  email provider (post-funding or a free provider key).
- Web push and scheduled generation (cron) are deferred; `generate-alerts` is run on demand / by an
  operator for now.
