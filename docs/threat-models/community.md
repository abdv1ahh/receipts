# Threat model — community & social (Slice F)

Scope: migration 016 (`users.handle/bio`, `trades.hidden`, `user_follows`, `trade_reactions`,
`trade_comments`, `content_reports`), `tradeos/community.py`, and the `/api/community/*`, `/api/u/*`,
`/api/trades/{id}/react|comments`, `/api/comments/*`, `/api/report`, `/api/leaderboard/traders`
endpoints. Public user-generated content next to money is the master brief's **poisoning threat** — a
coordinated pump — plus the usual UGC risks (XSS, IDOR, impersonation, spam).

## Assets
- **Feed integrity** — the community surface must not be usable as a pump instrument.
- **Truthful reputation** — the trader leaderboard must reflect an honest track record, not hype.
- **User content & identity** — comments/handles must not enable XSS, impersonation, or IDOR.

## Attacks and the design that stops them
1. **Coordinated pump via public trades/comments (poisoning).** Defended in depth: (a) public trades
   keep their **"not advice" framing** and are journal entries, never platform-endorsed calls; (b) the
   **leaderboard ranks by an honest win rate above a real sample floor** (≥10 closed public trades),
   never a single raw-return number — so hype/fabrication can't climb it; (c) **report → auto-hide**
   (≥3 distinct reports hides content pending review) + per-user **rate limits** on posting; (d) the
   platform never amplifies directive content, and reactions/comments carry no analytical imprimatur.
   The convergence signal is hash-locked and untouched by community activity.
2. **Stored XSS via comments/bio/handle.** Handles are validated to `^[a-z0-9_]{3,20}$` (reserved names
   blocked); bio and comments are length-capped and rendered by React (auto-escaped); no user string is
   interpolated into HTML/SVG unescaped. Comment bodies are never sent to the model.
3. **IDOR / privilege abuse.** Every mutation is scoped to the session `user_id`: you can react/comment
   only as yourself; a comment is deletable only by its author, the trade's owner, or an admin; you can
   react/comment only on a **public, non-hidden** trade (private trades stay invisible, per Slice E).
   Reacting/commenting cannot reveal a private trade's existence.
4. **Impersonation via handles.** Handles are unique (citext), format-validated, and reserved words
   (`admin`, `tradeos`, `official`, …) are blocked, so no one can pose as staff.
5. **Leaderboard gaming.** Ranking uses win rate over **public closed trades above the sample floor**;
   a flood of fake open/planned trades or a handful of cherry-picked wins doesn't qualify, and there is
   no raw-return metric to inflate. Sample size is shown next to the rate.
6. **Spam / flooding.** Comment and reaction endpoints are rate-limited and length-capped; reactions are
   idempotent (unique per (trade,user,kind)); reports are one-per-user-per-target.
7. **Privacy.** Only a user's **explicitly public** trades and the derived public track record are ever
   exposed on a profile; private trades, email, and internal ids are never surfaced (profiles are keyed
   by handle, not id).

## Residual / deferred (named, not silently assumed)
- **Moderation console** (review the auto-hide queue, ban, unhide) is Slice K (admin); the report +
  auto-hide primitives land here so the queue exists.
- **Per-account bot/sockpuppet detection** for coordinated reporting/liking and a shared edge rate
  limiter deepen at scale; the N+1 leaderboard query is fine at demo scale and named for a materialized
  view later.
- Comment **abuse classification** (a model pass flagging directive/pump language for review) is a
  future enhancement; today the defense is framing + report/auto-hide + rate limits.
