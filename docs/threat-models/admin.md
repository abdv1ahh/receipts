# Threat model — admin dashboard (Slice K)

Scope: migration 017 (`users.banned`, `content_reports.resolved_at/resolved_by/resolution`),
`tradeos/admin.py`, `tradeos/flags.py`, the `/api/admin/*` endpoints, and the flag enforcement wired
into `/api/auth/register`, `/api/assistant`, `/api/trades/{id}/analysis`, the community write paths,
and `/api/crypto/*`. The admin surface is the platform's highest-privilege control plane — moderation,
tier/entitlement changes, account suspension, runtime behaviour flags — so the risks are **privilege
escalation, self-lockout, moderation abuse, dishonest controls, and PII exposure**.

## Assets
- **The admin control plane** — only a real admin (tier=`admin`, MFA'd in) may reach it.
- **Account integrity** — a ban/tier change must be correct, auditable, and reversible, and must never
  lock the operator out of their own admin.
- **Honest controls** — a toggle in the console must change real behaviour, or be shown as read-only;
  it must never be a fake switch (the project's honesty mandate).
- **The audit trail** — every privileged action is recorded and the record cannot be altered.

## Attacks and the design that stops them
1. **Reaching admin without being an admin.** Every `/api/admin/*` route calls `_require_admin`, which
   resolves the session and returns **401 (no session) / 403 (non-admin)** before any work. Admin is a
   real tier gated by **TOTP at login** (`authn.login` refuses an admin whose secret is unset and
   requires a valid code), so the admin identity is the same one that passed MFA — there is no separate
   client-settable admin flag. *Verified live: anon→401, normal user→403, admin→200.*
2. **Privilege escalation to admin.** Tier changes are limited to `free|retail|pro`
   (`admin.validate_tier_change`); **granting `admin` is refused** at the API and in the pure guard —
   admin is provisioned only via the CLI (`seed-admin`, which also sets the required TOTP secret), so a
   web click can never mint an admin or hand out an account with no MFA. Re-tiering an existing admin is
   also refused.
3. **Self-lockout / self-harm.** You **cannot change your own tier** and **cannot ban yourself**
   (pure `validate_tier_change` / `can_ban`, enforced server-side); admins cannot be banned or re-tiered
   from the console at all. So a misclick can't strip the last operator of access. *Verified live:
   self-ban→400, tier=admin→400.*
4. **Dishonest controls (fake switches).** The flag console only exposes flags that are **actually read
   on the request path** (`flags.enabled` at register / assistant / trade-analysis / community-write /
   crypto gates); flipping one changes real behaviour within a bounded few-second cache. Things that are
   genuinely controlled by deployment env or a third-party key (the modular SEC inputs, Reddit/YouTube
   keys, Stripe) are shown **read-only** with their true state and who controls them — never a toggle
   that pretends to work. `flags.set_flag` rejects unknown names so the console can't create phantom
   flags. *Verified live: `ai_assistant=off` forced the assistant to the deterministic template with no
   model call; `registration=off` returned 403 on signup.*
5. **Moderation abuse / tampering.** Resolving a report is **non-destructive**: it stamps
   `resolved_at/resolved_by/resolution` instead of deleting, so the moderation history survives, and the
   auto-hide counter (`community.report`) now counts only **unresolved** reports so a dismissal resets it
   cleanly (a resolved item can't be instantly re-hidden by stale reports). Hide/unhide only flip the
   `hidden` boolean; the trade/comment content and the convergence signal are untouched. *Verified live:
   2 reports→queue→admin hide resolves both→leaves feed & queue→a fresh report counts from 1.*
6. **Ban evasion / lingering access.** A ban drops the account's **sessions** immediately, sets
   `users.banned`, and hides its **public trades**; `authn.session_user` excludes banned users
   (`AND NOT u.banned`) so any surviving cookie is inert, and `authn.login` refuses a banned account
   after password verification with an honest "suspended" message. *Verified live: banned user's live
   session went null and re-login was refused.*
7. **PII exposure.** The user-management list returns emails — that is admin-only data and every route
   that returns it is admin-gated. Public surfaces (profiles, leaderboard, feed) remain keyed by handle
   and never leak email/id (Slice F). User search escapes LIKE wildcards (`admin._like`) so a stray
   `%`/`_` can't match-all.
8. **Audit integrity.** Every mutation (`mod_resolve`, `admin_set_tier`, `admin_ban`/`admin_unban`,
   `admin_set_flag`) is written to `audit_log` via `authn.audit`; the table carries the append-only
   `forbid_mutation` trigger (migration 009), so the audit viewer is strictly read-only and the record
   cannot be edited or deleted — not even by an admin. *Verified live: all four actions present in the
   audit feed after the run.*

## Residual / deferred (named, not silently assumed)
- **Flag cache staleness:** `flags.enabled` caches for ~3s per process (single uvicorn worker today),
  so a toggle can lag a few seconds; `set_flag` clears the cache to make the operator's own flip feel
  instant. With multiple workers the bound is the TTL, which is acceptable and documented.
- **Admin action rate-limiting / four-eyes:** high-impact actions (mass ban, tier grants) are logged but
  not yet rate-limited or dual-controlled; a second-admin approval for destructive actions is a future
  hardening.
- **Ban does not auto-restore content on unban:** unbanning re-enables login but leaves previously
  hidden trades hidden, so a moderator restores them deliberately via the queue (intentional, to avoid
  un-hiding separately-moderated items).
- **Audit retention/rotation** and a signed/exported audit stream are deferred; the log is append-only
  and unbounded at demo scale.
