# Threat model: Authentication, sessions, and entitlements

Written before the code, per the security mandate. Accounts here sit one step from money
decisions and the paid product IS the data, so account takeover and signal exfiltration are
first-class threats (founding brief). This is demo-grade but real: the controls are genuine,
sized for an invite-only demo, with the production upgrades named.

## Who attacks this and how

**1. Account takeover — credential stuffing / brute force.** An attacker replays leaked
passwords or brute-forces logins. Bounded by: argon2id password hashing (slow, salted,
memory-hard); a breached-password check against a local top-list at registration (no external
call that could leak the password); and a login rate limit keyed on BOTH IP and account
(a simple Postgres counter at demo scale). MFA (TOTP) is available to all and REQUIRED for the
admin tier, so an admin credential alone is insufficient.

**2. Session theft / fixation.** A stolen or fixated session token grants access. Bounded by:
only a SHA-256 hash of the session token is stored (a DB leak does not yield usable tokens);
the cookie is HttpOnly + Secure + SameSite=Lax; sessions expire (24h) and are rotated on any
privilege change; logout deletes the session row.

**3. Signal exfiltration via tier bypass (the commercial attack).** The paid product is the
fresh signal, so the defining attack is a free (or unauthenticated) user reaching fresh
clusters by manipulating a request parameter. Removed structurally by: the free-tier delay is
a server-side WHERE clause (`knowable_time <= now() - interval '48 hours'`) applied from the
session's tier, NOT a client flag — no query parameter, `as_of`, id, or header can reach a
cluster newer than the delay for a free session. A test asserts the bypass fails. (Broader
scraping defenses — per-endpoint rate limits, anomaly detection, scoped API keys, canary
records — are on the post-funding roadmap; the delay is the structural floor.)

**4. Invite abuse.** Open registration would let anyone in. Removed by: registration requires
a valid, unused invite code; codes are single-use (marked used atomically); no invite, no
account.

**5. Privilege escalation / insider misuse.** A user editing a request to gain a higher tier,
or staff quietly reading pre-publication signals. Bounded by: tier is read server-side from the
session on every request and never taken from the client; every privileged action (invite
creation, tier change) and every admin read of a not-yet-public cluster writes to an
append-only `audit_log` (same immutability trigger as the raw layer) — the seed of the
staff-trading answer regulators will one day ask for.

**6. Information leak via errors.** Stack traces or differing error messages leak internals or
distinguish "user exists" from "wrong password". Bounded by: a uniform error shape with no
stack traces to clients, and a single "invalid credentials" message for login failures.

## What is demo-grade (and the production upgrade)

Passwords: argon2id now; a managed identity provider or the same with hardware-backed secrets
later. Rate limiting: a Postgres counter now; an edge/WAF limiter in production. MFA: TOTP now;
add WebAuthn later. New-device email: logged to output now (no email provider yet); a real
provider before public launch. Secrets: environment variables + gitignored `.env` now; a
managed secrets manager with rotation in production. None of these demo choices weaken the
structural guarantees above.
