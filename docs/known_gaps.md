# Known gaps — what is deliberately not built, and what a reader is told instead

Written 2026-09-15, alongside Part B (open registration). One entry per thing that is *absent by
decision* rather than by oversight. The rule for this file: if a gap is visible to a user, the
product has to say so in its own interface, and the sentence it says has to be named here so the
two cannot drift.

---

## 1. There is no email verification, and no email at all

**State.** `SMTP_HOST` and `MAIL_FROM` are empty. `cli preflight` reports it. `tradeos/mail.py`
refuses to send unconfigured and never half-sends, which is the right behaviour and is why nothing
silently fails.

**What that means for a caller.** An account works fully without a confirmed address. `users.
email_verified_at` stays NULL for every human account. A caller who forgets their password cannot
recover it: the reset API exists and the mail path will not fire. Their *record* survives —
`callers.user_id` is nullable with `ON DELETE SET NULL` — but they can never publish to it again.

**What that means for a reader.** Registration is open, so the only thing standing behind a handle
is an address nobody has confirmed. A reader is told this in as many words, in one place:
`receipts.record.identity_note()`. Both the React record page and the server-rendered
`/r/{handle}` share page print that exact sentence; neither writes its own copy.

> Nobody has verified who holds this handle. There is no email confirmation on this account and the
> audience link has not been proved, so treat the identity as unconfirmed. The calls themselves are
> sealed and every hash can be recomputed here, which is the part that does not depend on trusting
> them or us.

**Why it is a gap and not a defect.** The distinction the sentence draws is the real one: identity
verification is about *who is speaking*, and the seal is about *what was said*. An unverified
identity is a reason to discount the speaker, not a reason to doubt the record. Building an email
flow before there is a single caller would be a detour; saying nothing would let a reader assume
more than we know.

**What closing it needs.** A configured SMTP or API mail provider (a free tier covers it), then
`/api/auth/verify/*` already exists. `docs/receipts_gap_analysis.md` §GAP 2 estimates 2–3 hours,
config and a live send test. `pytest -k registration` pins that registration works without it.

**Pinned by.** `tests/test_registration.py`, `tests/test_receipts_api.py`. `GET
/api/auth/registration` reports `"email_verification": false` so no client can assume otherwise.

---

## 2. A caller's audience cannot be verified end to end

**State.** `POST /api/callers/verify/start` and `/confirm` work and are tested. The reviewer queue
— `GET /api/admin/callers/pending` and `POST /api/admin/callers/{id}/verify` — works, is tested,
and **nothing in the frontend calls either**. `caller_verifications` holds 0 rows because nobody
has ever tried.

**What a reader is told.** The same `identity_note()` sentence. The `✓ verified` badge is shown
only where `callers.verified_at` is actually set, and for a caller verified by audience but with no
confirmed account the note still appears — a badge earned by proving control of a newsletter is not
an identity check.

**Deliberately out of scope** for the current work: callers are unverified for now and the page says
so. See `docs/receipts_gap_analysis.md` §GAP 6, estimated 4 hours.

---

## 3. There is one copy of the chain

**State.** `calls` has no replica, no streaming copy and no external anchor. 473 sealed rows live in
one Docker volume. The append-only trigger protects them from being *edited*; nothing protects them
from the disk.

**What a reader is told.** The methodology page states the stronger version of this already: the
chain does not prove that *we* have not rewritten it, because we hold every field. That caveat is
printed directly beneath the Verify result, at the moment a visitor is most impressed.

**What closing it needs.** Automated `pg_dump` off-machine plus a restore drill, gated on
`cli verify-chain`. `docs/runbooks/backups.md` exists; the automation does not.
`docs/receipts_gap_analysis.md` §GAP 12.

---

## 4. A caller cannot disclose a genuine mistake

**State.** No retract, amend, annotate or withdraw exists — not a route, not a column, not a button.
A caller who types `AAPL` meaning `AAPD` has published a permanent, public, sealed call on a company
they never meant to name, and it will be scored.

**Why the seal is still right.** The fix is not a weakened seal. It is an append-only annotation in
its own table that never touches `calls` and never enters the hash, so `verify_chain` is unaffected
and every integrity property survives. The open design question — recorded here because it is a
product decision, not an implementation detail — is whether an annotation may change a verdict. It
must not: a record full of excused misses is worth less than one without the feature.

`docs/receipts_gap_analysis.md` §GAP 8.
