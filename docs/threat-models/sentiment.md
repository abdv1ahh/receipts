# Threat model — sentiment & trend scanner (Slice H)

Scope: migration 015 (`sentiment_observations`), `tradeos/sentiment.py`, the source clients
(`ingestion/sentiment_hn.py`, and the key-gated Reddit/YouTube clients when added), the
`ingest-sentiment` CLI, and `/api/trending` + `/api/sentiment/{symbol}`. The master brief names the
**poisoning threat** — an adversary manufacturing a signal via coordinated social campaigns or bots to
make the platform pump an asset — as business-ending, so it gets business-ending seriousness here.

## Assets
- **Truth of the attention signal** — a "trend" must reflect real public discussion, never a single
  stray post or a coordinated/bot campaign dressed as organic interest.
- **Source-supply cleanliness** — every source must be a legitimate, ToS-respecting feed (the data
  supply chain is the business).
- **Honest connectivity** — a source that isn't wired must read "not connected", never be simulated.

## Attacks and the design that stops them
1. **Manufactured trend (the poisoning attack).** Defended in depth: (a) a symbol appears only above a
   real **mention floor** (a lone post is never a trend); (b) attention is a **velocity vs the symbol's
   own baseline**, so a low-history name can't spike from one burst without being flagged **new**;
   (c) **manipulation flags** are explicit and shown — `single_source` (all attention from one feed →
   no corroboration) and `bot_heavy` (filtered-bot share over the window is high); (d) corroboration
   across **independent sources** is surfaced (the master brief's "ten signals echoing one origin are
   one signal"). Sentiment scoring never feeds the hash-locked convergence signal, so a social campaign
   cannot move the backtested product.
2. **Bot amplification.** Social sources (Reddit/YouTube/X) run per-account bot heuristics at ingestion;
   the removed count is stored as `bots_filtered` and folded into the `bot_heavy` flag. (HN/Wikipedia
   are low-bot; their `bots_filtered` is 0. Per-account bot scoring for Reddit lands with that client.)
3. **ToS / supply-chain violation.** Only sources with a legitimate free interface are wired: **Hacker
   News (Algolia)** is a public, keyless API used with a declared User-Agent; **Reddit/YouTube** use
   their official APIs and only run when the operator supplies their own key. **X/Twitter has no free
   tier, so it is honestly `unavailable` — never scraped, never faked.** Every client pins its host in
   an allowlist (SSRF defense), the pattern already used for SEC/FINRA/Tiingo/Gemini.
4. **Fabricated data with no source connected.** With no observations, `/api/trending` returns an empty
   board plus the honest source-status map; the UI says "connect a source", never invents attention.
   The never-fabricate mandate applies exactly as it does to signals.
5. **SSRF / injection via a symbol or query.** Source queries are built from resolved symbols/entity
   names, host-allowlisted, and responses are parsed as JSON only; nothing user-controlled reaches a URL
   host. Stored `meta` is JSON, rendered escaped by React.
6. **Tier / exfiltration.** Attention is derived from public discussion (not the proprietary convergence
   signal), so it is not tier-gated; it never exposes a fresher convergence signal than a tier is owed.
   Point-in-time discipline holds: each observation's `knowable_time` is its window end.

## Residual / deferred (named, not silently assumed)
- **Per-account bot classification** for Reddit/social and **cross-source entity de-duplication** deepen
  with each source; HN attention is text-match on the company name and can be noisy for generic names
  (a precision pass — ticker + name corroboration — is named).
- **Reddit/YouTube go live** only when the operator adds free keys (`REDDIT_CLIENT_ID/SECRET`,
  `YOUTUBE_API_KEY`); until then they are `needs_key`, honestly. **X stays `unavailable`.**
- Smart alerts on an attention spike for a followed/watchlisted symbol reuse the Slice B alert engine
  (dedup + tier-aware) and are wired as the observation history grows.
