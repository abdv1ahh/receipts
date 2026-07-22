# Threat model — paper portfolios, track record, share cards (Slice C)

Scope: migration 011 (`portfolios`, `portfolio_positions`), `tradeos/portfolio.py`, and the
`/api/portfolios*`, `/api/track-record`, `/api/card/{sym}.svg`, `/s/{sym}` endpoints.

## Assets
- A user's **portfolios and positions** (private, per-account).
- The **integrity of every displayed return** (a fabricated or flattering P&L is a trust-killer
  and, next to money, a compliance risk).
- The **paywall** — a public share card must not become a hole that leaks fresh paid signals.

## Attacks and the design that stops them
1. **IDOR on portfolios.** Every read/write is scoped to the session `user_id`
   (`detail(... user_id)`, `DELETE ... WHERE id=%s AND user_id=%s`, position deletes joined through
   the owning portfolio). A portfolio_id or position_id from another account resolves to nothing.
2. **Fabricated / look-ahead P&L.** Returns come only from real `prices_eod` vs SPY over the actual
   holding window, via the same pure engine the backtest uses. A name without a priceable window is
   `pending` and excluded from the averages — the code never substitutes 0 or a guess. Entry is the
   first trading day on/after the paper entry date (no negative-time entries).
3. **Cherry-picked-window flattery.** A shadow portfolio's average can be lifted by a few winners.
   Mitigations are honesty, not suppression: every position is shown individually (winners and
   losers), pending names are counted, and the **full-sample public track record is shown alongside**
   with its unflattering numbers. Nothing claims future results.
4. **Paywall leak through the public card.** `/api/card` and `/s/` compute from the **free-tier
   (48h-delayed) view** (`_effective_as_of(..., "free")`), so a public, unauthenticated artifact can
   never expose a signal fresher than the free tier already sees.
5. **SVG / HTML injection via issuer or story text.** All interpolated text (ticker, name, headline,
   OG tags) is XML/attribute-escaped (`presentation._xml_escape`); the card is a static string with no
   script, and the share page has no inline script (CSP `script-src 'self'`). A crafted issuer name
   cannot break out into markup or script.
6. **Resource abuse.** Card/track-record queries are bounded (single latest cluster; calibration is a
   read-only aggregate); cards send `Cache-Control: public, max-age=300`. Portfolio population is
   capped (default 20 positions).

## Residual / deferred
- Per-IP rate limiting on the public card/share endpoints (belongs with the edge limiter, post-funding).
- Rasterizing the SVG to PNG for social scrapers that reject SVG og:images (cosmetic; deferred).
