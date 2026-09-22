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

---

## 5. The browser check does not close the hole it makes most visible

Added 2026-09-22, alongside Part E (the public record page).

**State.** `/r/{handle}`'s Verify button recomputes the whole chain in the visitor's own browser
(`receipts/verify.js` over `/api/receipts/{handle}/chain`, which hands over the sealed fields and
states no verdict). That is a real improvement over asking our server whether our own record is
intact, and it is worth being precise about what it does and does not move:

| against | before | after |
|---|---|---|
| the CALLER editing, deleting, reordering or backdating | caught, by our server | caught, **by the visitor's own machine** |
| US rewriting the record and recomputing every hash after it | not caught | **still not caught** |

**Why the second row does not move.** We hold every field. A browser can only hash what it is
given, so an operator who rewrites a call and recomputes the chain from that point hands over a
self-consistent chain and every client agrees it is intact. Moving the arithmetic off our server
removes us from the *checking*; it cannot remove us from the *data*.

**What a reader is told.** The caveat is printed directly beneath the Verify result, unprompted, at
the moment a visitor is most impressed — the one string, from `record.methodology()["chain"]
["does_not_prove"]`, which every surface reads rather than copying:

> The chain does not prove that WE have not rewritten it. We hold every field, so this operator
> could edit a call and recompute the whole chain after it. Making that impossible needs an anchor
> outside our control, publishing the chain head daily somewhere we cannot revise, and that is not
> built yet. This is not a blockchain and we do not call it one.

**The one thing the panel does add against the operator.** It offers to break the record in front
of you: "Now show me it failing" changes one character of one thesis in your browser and reruns the
same code, which reports the tamper and names the call. A check that can only ever say yes is
indistinguishable from a green sticker, and a visitor has no way to tell them apart unless they see
it say no.

**What closing gap 5 needs.** The same anchor gap 3 needs, from the other side: publishing the
chain head somewhere we cannot revise. Until that exists, this page is tamper-evident against the
caller and trust-based against us, and says so in those words.

---

## 6. No price appears anywhere a reader can see

Added 2026-09-23, alongside the price-redistribution sweep.

**State.** The four component prices on a resolved call — `entry_price`, `exit_price`,
`benchmark_entry`, `benchmark_exit` — and the two component returns computed from them are stored,
sealed by migration 035, and **never served**. `receipts/calls._LIST_COLUMNS` does not select them,
so nothing downstream can serialise them. The publish screen's commitment panel used to print our
last close for the symbol and for SPY, live from `prices_eod`; it now prints the DATE our series
runs through instead. `/api/asset/{symbol}` used to return 130 daily closes on a public route; it
now returns the days only.

**Why it is a gap and not a feature.** The old proof panel was genuinely stronger for a sceptic:
four prices, two returns, a subtraction and a noise floor is arithmetic anyone can redo on the spot.
What replaces it is one step longer, because the reader has to fetch two closes themselves. That is
a real loss and it is not pretended otherwise.

**What a reader is told,** in one place — `receipts.record.NO_PRICES`, quoted by the methodology
page, by the call detail, by the server-rendered `/r/{handle}` and by the publish screen, all of
which read the constant rather than writing their own copy:

> No prices are shown anywhere on this site. They come from a market-data vendor whose terms do not
> permit redistributing their data, and those terms carry no exception for displaying it. What is
> published is the measurement; the prices it was measured from are kept, sealed and unchangeable,
> so a verdict can still be answered for.

The source is the vendor's own published answer to "Can I redistribute Alpaca API data via my
platform?", dated November 2022: *"Unfortunately, you cannot redistribute Alpaca API data."* One
sentence, no personal/commercial split, no exception for display. Their terms additionally
incorporate the NASDAQ display-service agreements by reference.

**And what replaces them,** wherever a score appears — `receipts.record.RECOMPUTE_NOTE`, read from
the same module by the same surfaces:

> Both session dates are shown so you can recompute this yourself from any price source you choose:
> take the close on the entry session and on the exit session for the symbol, do the same for the
> benchmark, and subtract the benchmark's move from the symbol's.

**Why the dates are enough, and in one way better.** The entry and exit sessions are exact, they
are ours to publish, and they are the whole input to the measurement. A reader who prices those two
sessions from a feed of their own choosing reproduces the excess return *without* having to trust
our copy of the closes — which is more than the old panel offered, since the old panel asked them
to believe our four numbers. What they lose is convenience, not verifiability.

**A self-hoster is in the same position,** running their own key against the same vendor. This is
why the rule lives in the product rather than in a note to one operator.

**What closing it would need.** A price source whose licence permits redistribution. There is no
free one that covers this universe; a paid data licence is the only path, and it is not worth it
for a portfolio project.

**Pinned by.** `tests/test_price_redistribution.py` plants six-decimal prices on a resolved call
and a scratch symbol in `prices_eod`, renders **every** route the app serves — anonymous and
signed in — and fails if any planted value or any of the six column names appears in the bytes.
It is a sweep rather than six assertions because the leak it closes was never a field anyone chose
to print: `/api/calls/{id}` returned the whole row and the prices came along invisibly, NULL on all
474 sealed rows, waiting for the first resolution to start publishing them.
Also `tests/test_receipts.py::test_the_components_that_arithmetic_used_never_reach_the_payload`
and `::test_the_stored_arithmetic_reconciles`, which check the same numbers from opposite sides.
