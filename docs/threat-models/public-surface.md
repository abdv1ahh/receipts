# Threat model — the public surface

Covers everything reachable **without a session**: the marketing site's four endpoints, the Ledger,
and the static bundles. Written in Phase 9, after Phase 7 created most of it.

The other threat models in this directory cover authenticated features. This one exists because the
public surface has a property none of them have: **its whole audience is people we know nothing
about**, and it is the only part of the system a search engine, a scraper or an attacker will reach
first.

---

## What is exposed

| Endpoint | Returns | Auth |
|---|---|---|
| `GET /api/public/live` | Newest event-derived interpretations | none |
| `GET /api/public/walkthrough` | One interpretation walked end to end + one settled call | none |
| `GET /api/public/frame?country=XX` | Live claims ranked for a country | none |
| `GET /api/ledger` | The accuracy record and recent misses | none |
| `GET /site/*` | The marketing bundle | none |

Everything is `GET`. `tests/test_public_site.py` asserts no `POST`/`PUT`/`PATCH`/`DELETE` route
exists under `/api/public`, so the surface cannot quietly acquire a write.

---

## Assets, and what would be bad

**The reader's identity — the one thing that must never appear here.** These endpoints personalise
*without a person*: `frame` takes an ISO country code and scores against published reference data,
not against anyone's profile. If a user identifier ever became acceptable input, the endpoint would
become an enumeration oracle for other people's frames.

*Controls.* No session parameter is read. No query touches `users`, `trades`, `watchlists`,
`user_profiles` or `trade_context`. Both are asserted mechanically against the module source in
`tests/test_public_site.py`, and adversarially in `tests/test_authz_adversarial.py`, which creates
a real user with distinctive data and then greps every public response for it.

**The integrity of the record.** The Ledger's argument is that it is unedited. A public surface
that selected *which* call to display could make that false without changing a single stored
number — the most plausible dishonesty available to this product, and it would look like a
harmless UX improvement in a diff.

*Controls.* The walkthrough rotates by `date.toordinal() % len(pool)` over a pool ordered by
recency alone, and the settled example is drawn newest-first with no verdict filter. A test asserts
the selection statement is *exactly* that expression, and that the pool ordering mentions no
outcome column.

**Availability and cost.** Uncached, unauthenticated endpoints running real queries.

*Controls.* 120 requests per client per minute (`ratelimit.py`), applied in middleware before any
work is done. **In-process**, which is honest for one container and wrong for several — see the
module docstring and `docs/deploy.md`.

---

## Attacks considered

**Scraping the whole claim store.** Possible, within the rate limit, and largely *fine*: every
claim on these endpoints is already published on the Ledger by design. The interesting content —
who read what, from where — is not here.

**Enumeration via the country parameter.** The code is validated against the ten-row
`country_exposure` table and an unknown value is refused with a message rather than approximated.
There is nothing to enumerate: the country list is returned in full on every call, on purpose.

**Prompt injection through ingested text.** Claim mechanisms and headlines originate in external
sources and are rendered on the marketing page. They are **not** passed to any model from here —
the site makes no model calls at all. The injection boundary stays where it was built, in
`claims.py`, at ingestion time.

**XSS through ingested text.** Rendered through React JSX, which escapes. No
`dangerouslySetInnerHTML` anywhere in `site/`. CSP is `default-src 'self'` with no `unsafe-eval`,
and the page loads no third-party script, font or image — everything is self-hosted, which also
means no visitor's IP reaches a font CDN.

**Clickjacking.** `X-Frame-Options: DENY` and `frame-ancestors 'none'`.

---

## Known gaps

1. **No CORS configuration.** Correct today — both bundles are same-origin. The moment the
   marketing site moves to its own domain (Phase 8's deployment note), its `/api/public/*` calls
   become cross-origin and need a deliberate, narrow policy. Writing a permissive one under
   deadline pressure is the predictable failure here.
2. **The rate limiter is per-process.** With N replicas the effective limit is N × the configured
   one, and it resets on deploy. Replacing it with a shared store is the correct fix at the point
   where a second replica exists, not before.
3. **`X-Forwarded-For` is trusted for client identity.** Forgeable by anyone who can reach the app
   directly, which is why the deployment must expose it only through the reverse proxy. If that
   invariant breaks, the limiter is bypassable — it is not a confidentiality control, so this is
   ranked accordingly, but it is stated rather than assumed.
4. **No caching.** Every public request runs its queries. A CDN or a short-TTL cache in front of
   these four endpoints would remove most of the load the rate limiter currently exists to bound.
