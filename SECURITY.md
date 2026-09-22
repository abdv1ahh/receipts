# Security

## Reporting something

Open a **private security advisory** on this repository (Security → Advisories → Report a
vulnerability). That keeps the report out of public issues while it is being fixed.

If you would rather not use GitHub, open a public issue saying only *"I have a security report,
please open a private channel"* — with no details — and one will be opened.

There is no bounty. This is a portfolio project with no revenue.

**What helps:** the version (a commit SHA), what you did, what happened, and what you expected. A
proof of concept is welcome and never required. If you are unsure whether something counts, report
it; a wrong guess costs a few minutes and the other kind of mistake does not.

---

## What is in scope

This product makes one promise a reader can check, so the highest-severity class is anything that
lets somebody **change a sealed record without the chain noticing**, or **publish into a record
that is not theirs**. A call is sealed on write and its verdict is permanent, so a forged or
altered entry cannot be corrected — it can only be disclosed.

In scope, roughly in order of how much it would matter:

| | |
|---|---|
| **Writing into another caller's chain** | Publishing, editing, deleting or reordering somebody else's calls by any route |
| **Defeating the append-only trigger** | Any path that changes a sealed column, or a resolved call's arithmetic, without the database refusing |
| **Forging a chain that verifies** | Two different calls hashing the same, or a rewritten chain the browser check accepts |
| **Authentication and session handling** | Session fixation, privilege escalation to `tier=admin`, bypassing TOTP on an admin account |
| **Authorization** | Reading or writing anything scoped to another account |
| **Injection** | SQL injection, HTML or script injection into a page, header injection |
| **SSRF** | Anything that makes the server fetch a URL an attacker chose |
| **Secret exposure** | A credential reaching a log, an error message, a stored row, or a response |
| **Denial of service that is cheap** | A single unauthenticated request that costs the server far more than it costs the sender |

The **browser verifier** (`tradeos/receipts/verify.js`) is in scope and is a good place to look: it
runs on a visitor's machine and decides whether a record is intact, so a bug that makes it report
*intact* when the chain is broken is worse than a bug that crashes it.

---

## What is NOT a vulnerability here

Some of these are real limits. They are documented, the product states them in its own interface,
and a report of one will be closed with a pointer to where it is already written down. If you can
show the mitigation does not actually hold, that IS a report.

**The operator can rewrite the whole chain.** We hold every field. An operator who edits a call and
recomputes every hash after it hands over a self-consistent chain that every client agrees is
intact. This is printed on the public record page, beneath the verify result, unprompted. Closing
it needs an anchor outside the operator's control and is not built. `docs/known_gaps.md` §5.

**Nobody's identity is verified.** Registration is open, there is no email confirmation, and a
handle proves nothing about who holds it. The record page says so. §1 and §2.

**Rate limiting is in-process.** It is a dict in one worker: it resets on restart, and with more
than one API replica each replica gets its own allowance. Honest for a single container, stated in
`tradeos/ratelimit.py`'s own docstring, and the login path is deliberately elsewhere — `authn`
limits it against a database table, which survives a restart. A report that the limiter is
per-process is a report of something already written down; a report that a limit can be bypassed
*within* one process is not.

**There is one copy of the chain.** No replica, no external anchor. The append-only trigger
protects the rows from being edited; nothing protects them from the disk. §3.

**A caller cannot retract a mistake.** Someone who types `AAPL` meaning `AAPD` has published a
permanent public call on a company they never meant to name, and it will be scored. That is the
seal working, and the fix is an append-only annotation that never enters the hash — not a weakened
seal. §4.

**Self-hosted misconfiguration.** Running with `COOKIE_SECURE=false` behind TLS, publishing the
Postgres port past loopback, or setting `DEV_ORIGINS` in production. `cli preflight` reports all
three. If you find one of these that preflight does *not* report, that is worth a report.

---

## What this deployment does

* Sessions are stored as a hash, `argon2` for passwords, TOTP required for `tier=admin`.
* `script-src 'self'` and `frame-ancestors 'none'`; no inline scripts anywhere (the browser
  verifier is served as a file for exactly that reason).
* All SQL is parameterised. Where SQL must be composed, it goes through `psycopg.sql` and never an
  f-string; ruff's `S608` enforces it across the whole package.
* Credentials are sent as headers, not query parameters, so a URL in an exception message cannot
  carry one — and exception text is redacted inside the function that stores it, not at the call
  sites, because the copy that drifts is the one that leaks.
* The container runs as a non-root user.
* `docker-compose.yml` ships **no default database password** and refuses to start without one, so
  a public repository cannot hand every self-hoster the same credential.
* `cli seed-demo` generates its password, prints it once, and refuses to run when
  `COOKIE_SECURE=true` unless given `--i-know`.

---

**Nothing in this repository is investment advice. It is not a recommendation, and no position on
any board it produces is an endorsement of any person.**
