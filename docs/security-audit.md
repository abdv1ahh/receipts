# Dependency & secret audit

Run before any public launch and on a schedule; dependencies are pinned with lockfiles and
scanned continuously (founding brief). Last run: 2026-07-17.

## Python (`pip-audit -r requirements.txt`) — CLEAN

Result: **No known vulnerabilities found.** Reaching clean required upgrading:
- `fastapi 0.116.1 → 0.139.2` and `starlette 0.47.3 → 1.3.1` — cleared six runtime Starlette
  advisories (PYSEC-2026-161/248/249/1942/2280/2281). Starlette is the ASGI layer under FastAPI,
  so these were production-relevant and were fixed, not documented away.
- `pytest 8.4.1 → 9.0.3` — cleared PYSEC-2026-1845 (test-only, low risk, fixed anyway).

All 65 tests pass and the app is functionally verified under the upgraded versions.

## Frontend (`npm audit`) — one dev-only advisory, accepted

Remaining: **GHSA-67mh-4wv8-2f99** (esbuild ≤0.24.2, transitive via Vite 5).

- Assessment: this advisory affects only the **esbuild/Vite dev server** ("any website can send
  requests to the dev server and read the response"). TradeOSS never runs the dev server in the
  demo or in production — the multi-stage Docker build produces a static bundle that FastAPI
  serves. The vulnerable code path is not present at runtime.
- Remediation (tracked, not urgent): clearing it requires Vite 6 (a major bump with a build
  regression pass), scheduled as a routine frontend upgrade. Vite is pinned to 5.4.21 (latest
  5.x) meanwhile.

## Secret scanning

- `.env` is gitignored (holds the SEC/Tiingo/Gemini keys); `.env.example` is the committed
  template.
- `.pre-commit-config.yaml` wires the **gitleaks** hook (`pre-commit install`), and a full-history
  scan (`gitleaks detect --source .`) should run once before the repo is shared.
- A leaked key is an incident with a runbook, not a quiet fix: `docs/runbooks/leaked-secret.md`.

## Standing checklist (pre-public-launch)
- [ ] `pip-audit` + `npm audit` clean or documented (above) — Python clean; npm dev-only accepted.
- [ ] gitleaks pre-commit installed + full-history scan run once.
- [ ] Base image pinned by digest; container runs non-root (done).
- [ ] Egress allowlist verified on the host (sec.gov, openfigi.com, finra.org, api.tiingo.com,
      generativelanguage.googleapis.com) — see README.
- [ ] External penetration test; findings fixed, not filed (deferred registry).
