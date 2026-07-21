# Threat model — crypto market data (Slice I)

Scope: `tradeos/ingestion/coingecko.py`, `tradeos/crypto.py`, and `/api/crypto/markets` +
`/api/crypto/trending`. This promotes the watermarked crypto *preview* to real data. Crypto sits in
the most regulatory-sensitive, most manipulation-prone corner of the product, so risk labeling and
"this is market data, not advice" are load-bearing, not decoration.

## Assets
- **Truthfulness** — only real market data is shown; a fetch failure degrades to an honest "unavailable",
  never a fabricated or stale-as-fresh price.
- **The regulatory line** — crypto data must stay descriptive market data + attention, never advice, and
  high-risk names must be labeled unmissably (the master brief's explicit mandate for meme coins).
- **The upstream feed** — CoinGecko's free API must be used within its terms and not abused.

## Attacks and the design that stops them
1. **SSRF / feed spoofing.** The client pins `api.coingecko.com` in a host allowlist (the SEC/FINRA/
   Tiingo/HN pattern) and parses JSON only; no user input reaches a URL host.
2. **Fabricated / stale prices.** Data is fetched live from CoinGecko with a short in-process TTL cache;
   on any error the endpoint returns an explicit `error` + empty list, never a guessed or last-known price
   dressed as current. Every response carries `source: CoinGecko` and the "market data, not advice" note.
3. **Missing risk labels (regulatory).** `crypto.risk_flags` labels **high_volatility** (|24h| ≥ 20%),
   **microcap** (< $100M), and **thin_volume** unmissably per coin, and the surface carries a persistent
   "crypto is high-risk and volatile" banner. Nothing is framed as a recommendation; there is no buy/sell
   language anywhere on the surface.
4. **Upstream rate-limit abuse / dependency as a DoS vector.** The TTL cache bounds outbound calls
   regardless of inbound traffic; the endpoint never proxies arbitrary CoinGecko paths (only the two
   fixed queries), so it can't be used as an open proxy. A CoinGecko outage degrades this one surface
   loudly and touches nothing else.
5. **Contaminating the real signal.** Crypto market data is entirely separate from the hash-locked
   convergence signal and its backtest; it is displayed market data, tier-ungated (public prices), and
   never feeds calibration — so a volatile crypto feed can't move the product's proprietary intelligence.

## Residual / deferred (named, not silently assumed)
- **On-chain data** (whale wallets, exchange flows, DEX activity) — the "closest thing to live" — is
  explicitly deferred (needs its own sourcing + manipulation analysis per the master brief).
- **Per-category meme detection** and a **licensed/keyed higher-rate feed** land later; today the honest
  risk labels (volatility/microcap/thin volume) + the persistent banner cover the mandate.
- Wiring crypto attention into the assistant/scanner is a small follow-up (named), kept out of this slice.
