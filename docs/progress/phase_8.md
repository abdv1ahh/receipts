# Phase 8 — accounts, limits, deployment · progress report

Date: 2026-07-26 · Branch: `phase/6-sections` · 527 tests pass · 0 lint errors

Migrations 029 (onboarding state) and 030 (OAuth identities). New modules `onboarding.py` and
`oauth.py`. `docs/deploy.md` written from the running system.

---

## First-run setup — the piece whose absence was quietly expensive

The brief: *"onboarding capturing country, base currency, and initial watchlist in under a minute,
because relevance scoring is worthless without it. Skippable but gently persistent."*

`user_profiles` and `PUT /api/profile/frame` have existed since Phase 3. Nothing ever asked a new
account to fill them, so almost every profile was empty — which, combined with the geo bug Phase 7
found, means personal relevance has effectively been off for everyone since it was built. Two
separate omissions, in the same feature, neither of which broke anything visibly.

Three questions on one screen, not a wizard: a stepper for three optional fields is theatre and
makes a sixty-second job feel like a form. The currency is **proposed** from the country's
published row and labelled as a proposal — a reader in Singapore may well account in USD, and
deciding that silently is the sort of small wrong answer that erodes trust in the large ones. Only
the ten countries with hand-checked exposure figures are offered; accepting a frame the product
cannot score against would be worse than not asking.

Two rules held mechanically by tests:

- **Nothing here gates a feature.** A reader who skips forever gets the whole product, with the
  unranked-for-them ordering the Radar already announces. `test_setup_never_gates_a_feature`
  fails if this module ever grows an entitlement check.
- **A skip snoozes; it never marks complete.** Three days, then the question returns. Someone who
  skips on day one has not yet seen the feed they would be personalising.

Verified end to end in the browser: register → card appears → pick Brazil → BRL proposed with its
source shown → symbols parsed live → save → card gone → `/api/claims` returns
`personalised: true, country: BR`.

A bug the tests found on the way: `str(None)` is `"NONE"`, so a null in the submitted symbol list
became a watchlist holding called NONE.

---

## Tier gating

`exposure` added to the entitlements table and enforced in the read path, matching the split the
brief sets. It returns what the surface *would* show and what unlocks it, rather than a bare 403 —
a locked feature that says nothing is indistinguishable from a broken one.

**The Ledger is deliberately in no tier's entitlements**, and a test asserts it stays that way. An
accuracy record behind a paywall is not an accuracy record, and that is the product's whole
argument.

The rest of the gating already existed and is unchanged: limits are enforced in write paths, and
the 48-hour delay for free accounts is applied server-side where no parameter can reach past it.

---

## Sign in with Google — built, and honestly unverified

**Implemented, config-gated, and never exercised against Google.** No credentials were available.
The validation logic is unit-tested against payloads shaped like real ones; the network round trip
is not. It is registered in `sources.py` as unconfigured, `preflight` warns when it is switched on,
and `docs/deploy.md` says the same thing in the place an operator will read it. Email and password
signup is unaffected either way.

Writing untested auth code is a real risk, so the decisions that matter are stated in the module
docstring and pinned by tests:

- **`state` is consumed by deletion**, and the CSRF check is that a row was actually deleted. A
  read-then-delete leaves a window where two callbacks both see a valid state.
- **Identity is the provider's `sub`, never the email.** An address is reassignable — a corporate
  mailbox handed to a new employee would otherwise inherit that employee's account.
- **`email_verified` must be true**, or anyone able to set an unverified address at a provider
  could claim a matching local account.
- **Merging into an existing password account is refused**, not performed silently. Merge-on-email
  is a well-worn takeover path, and the safe resolution needs a flow that does not exist yet.
- **The ID token's signature is not verified**, which is defensible *only* because it arrives
  directly from Google's token endpoint over TLS in a server-to-server call. The docstring states
  the exact conditions under which that stops being true.

The callback consumes state before exchanging the code — a test asserts that ordering, because
redeeming an attacker-supplied code before the CSRF check would defeat the check.

`TOKEN_URL` had to become `EXCHANGE_ENDPOINT`: ruff's S105 reads any constant with TOKEN in its
name as a hardcoded credential. Renaming beat suppressing a rule that is right to be suspicious of
exactly that shape.

---

## Deployment

`docs/deploy.md`, written from the running system. Every environment variable the code reads is
listed with where to obtain it, and the list was **checked against the source** rather than
recalled — three (`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `PUBLIC_BASE_URL`) were missing from
`.env.example` and are now there.

`preflight` gained three checks: `DEV_ORIGINS` set in production is a **problem** rather than a
warning (it widens the CSRF origin check), half-configured OAuth is refused, and an OAuth redirect
over plain http is refused because it leaks the authorization code.

The document is explicit that **it has never been executed against a real host**. The platform
steps come from provider documentation. It also records what is missing rather than leaving it to
be discovered: no CORS configuration (needed the moment the marketing site moves to its own
domain), no rate limiting on the public endpoints, no backup schedule for a dataset that took hours
of rate-limited SEC backfill to build.

---

## The marketing site now converts

Its CTAs pointed at `/`. They point at `/auth` now, and a closing band was added before the footer
— the page previously ended on the FAQ, which is where a reader who is already convinced has to go
hunting for the button.

---

## Two name collisions, same shape, both caught by running the thing

`def onboarding(...)` — the older activation-checklist route handler — shadowed the `onboarding`
module the moment Phase 8 imported one, and every `onboarding.state(...)` call became an
`AttributeError` on a function. Renamed to `activation_checklist`; the route path is unchanged.

The identical mistake then happened in JavaScript: `fetchOnboarding` already existed for that same
old endpoint. The new ones are named for what they set — `fetchFrameSetup`, `saveFrameSetup`,
`snoozeFrameSetup`.

Neither was caught by a test. Both were caught within a minute of using the feature, which is the
argument for the browser check that `CLAUDE.md` already makes.

---

## Not done

**No email verification, and no password reset.** A new account is usable immediately with an
unverified address. Both are real gaps for a product with real users; neither is in the brief's
Phase 8 list, so they are recorded rather than silently added.

**OAuth's live handshake.** Above.

**The deployment itself.** The document exists; the deployment does not.

---

**Status: Phase 8 complete.** Phase 9 (security) is next and closes the build.
