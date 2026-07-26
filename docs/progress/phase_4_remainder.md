# Phase 4 remainder — threading, saved filters, subscribable alerts

Date: 2026-07-26 · 598 tests pass · 0 lint errors · migrations through 032

Three things the brief specified for the Radar that were carried as outstanding through five later
phases. Phase 4 is complete now.

---

## Threading — the substrate existed, the second reading did not

*"When an event develops over days, the card updates in place with a visible history of how the
interpretation changed... Users should be able to watch the system change its mind and see why."*

Events already clustered, and **39 clusters had gained sources after their first claim was made**.
What was missing is that `interpret` explicitly skipped any cluster that already had a claim
(`AND NOT EXISTS (SELECT 1 FROM claims WHERE cluster_id = c.id)`), so a developing story never got
a second reading and there was nothing to thread. Zero clusters had more than one claim.

`claims.reinterpret_developing` re-reads a story **only when the cluster has genuinely grown since
the last reading** — never merely because time passed. Re-running the model on unchanged input
would spend quota to produce a differently-worded version of the same thing and call it a revision.
`claims.supersedes` links the revision to what it revised; `radar.thread` assembles the chain.

**The rule that makes this honest: a superseded claim is still scored.** It is not withdrawn, not
marked unscoreable, not excluded from the hit rate. It was live, it committed to a direction, and
it is marked against what actually happened. If a revision removed the original from the Ledger,
"changing its mind" would be a mechanism for erasing misses, and the one number this product is
built on would become editable by writing a better guess afterwards. A test asserts the
re-interpretation path touches none of `status='unscoreable'`, `resolved_at`, or `DELETE FROM
claims`, and the card says it out loud: *"Still scored in the Ledger — a revised call is not a
withdrawn one."*

Run against the real store: 2 developing stories found, both revised, both threads showing
*"confidence moved from 60% to 70%"*. 60 claims now collapse to 58 cards.

The history sits **on the card, not behind the expand**. The first version put it inside the
collapsed reasoning panel, which defeats the purpose — a reader cannot see that the system changed
its mind if seeing it requires knowing to look.

---

## Saved filter sets

Five dimensions — category, geography, horizon, source, confidence floor — persisted per user, with
a live match count while editing so **a filter that matches nothing is obvious before it is saved
rather than after a week of silence**.

The geography dimension filters on what a claim **affects**, not who published it. That is the
project's most repeated mistake and a filter is a fresh place to make it; a test asserts a US-filed
story about the Middle East is caught by a Gulf filter and missed by a US one.

A spec is normalised into a fixed five-key shape before storage — an allowlist, not a sanitiser —
so matching never has to defend itself against a shape it did not expect. Matching runs in Python
over already-fetched claims rather than compiling into SQL: the page is bounded, and a user-defined
predicate that becomes a WHERE clause is a much larger surface than this is worth.

---

## Subscribable alerts, and the SSRF that comes with them

Subscribe to any saved set, by email or webhook, throttled hard — the floor is enforced server-side
so a client cannot ask to be notified more often. **Nothing is sent when nothing matched**; an alert
that says "no news" is exactly the noise a throttle exists to prevent.

**A webhook URL is supplied by a user and fetched by the server, which is SSRF by construction.**
The danger is not the public internet — it is that the server can reach what the user cannot: a
metadata endpoint holding cloud credentials, a database on a private subnet, another container by
name. `radar.webhook_target_ok`:

- requires **https** (http would also put the payload in the clear);
- resolves the host and checks **every** returned address, not just the first — a name resolving to
  one public and one private address would otherwise pass and then connect wherever the client
  picked;
- refuses private, loopback, link-local, reserved, multicast and unspecified addresses;
- refuses infrastructure ports (22, 5432, 6379, 27017, …);
- **re-checks at send time**, because DNS can change between saving and sending, which is precisely
  a rebinding attack;
- **refuses redirects**, because a 302 to `169.254.169.254` would walk straight past the check that
  just passed.

Verified live against all four vectors: plain http, `127.0.0.1`, `169.254.169.254`, and a
Postgres port — each refused with its own reason.

**The high-water mark is a claim id, not a timestamp** (ids are monotonic; a timestamp comparison
resends anything written in the same second), and it **advances only when the batch actually went
out**. The first version advanced it regardless, which would have dropped those claims permanently
on a transient outage — the reader never hears about them and nothing records that they were
missed. Holding it means a transient failure retries next tick; `last_sent_at` still moves, so a
permanently broken endpoint retries no faster than its own throttle and cannot become a hot loop.

Two scheduler jobs: `reinterpret` every 2 hours (bounded to 3, harder than first interpretation —
a revision costs the same quota and there are always more new events than developing ones) and
`radar_alerts` every 15 minutes (the per-filter throttle is the real control).

---

## Not done

**SMTP is still unconfigured**, so email alerts compose and then fail to send. Webhook delivery has
been exercised only against the refusal paths — no accepted endpoint has actually received a
payload, because that needs a real public URL.

---

**Status: Phase 4 complete.** All ten phases and the Phase 4 remainder are done.
