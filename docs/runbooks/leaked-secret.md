# Runbook: leaked secret

A leaked API key, database password, or session-signing secret is an incident with a
procedure, not an embarrassment to quietly fix (founding brief). Work top to bottom.

## 1. Contain (minutes)
- Identify the leaked credential and where it leaked (commit, log, screenshot, paste).
- **Rotate it immediately** at the source:
  - Tiingo / Gemini / OpenFIGI: revoke the key in the provider console, issue a new one, update
    `.env` (and the deployment's secret store), redeploy.
  - Database password: change it in the managed DB, update `DATABASE_URL`, redeploy.
- If the secret is auth-adjacent (session or DB), **invalidate sessions**: `TRUNCATE sessions;`
  forces every user to re-authenticate.

## 2. Assess exposure
- How long was it exposed, and to whom (public repo? shared log?).
- Check provider usage dashboards for anomalous calls on the leaked key.
- Query `audit_log` for suspicious privileged actions in the window.

## 3. Purge and scan
- Remove the secret from wherever it leaked. For git history: rewrite history (filter-repo) and
  force-push, then rotate again (assume it was scraped the moment it was pushed).
- Run a full-history secret scan (gitleaks) to confirm nothing else is exposed.

## 4. Record
- Write a short incident entry in the decision log: what leaked, how, blast radius, actions,
  and the prevention (e.g. add/verify the gitleaks pre-commit hook). This is the honest record
  regulators and partners will expect.

## Prevention (standing)
- Secrets only in env vars / a secrets manager; `.env` is gitignored; no secret in frontend
  bundles or logs. A gitleaks pre-commit hook + CI scan is the tripwire; treat every finding as
  this runbook, not a quiet fix.
