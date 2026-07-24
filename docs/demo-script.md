# TradeOSS — investor demo script

The whole growth engine is one moment: a skeptical trader checks a signal against a source
they already trust, finds it accurate and honestly labeled, and comes back. This script builds
to that moment. Total time ~8 minutes.

## Setup (once)
1. `make demo` — builds and loads a quick data window (a few minutes). For a deep, publishable
   calibration first run `make backfill-full` (hours) beforehand.
2. Create the admin and note the TOTP: `docker compose exec api python -m tradeos.cli seed-admin --email you@example.com`
3. `make demo` printed 5 invite codes — keep one handy.
4. Open http://localhost:8000.

## The flow

1. **The dashboard (10s).** "These are live convergence clusters — cases where several
   independent smart-money disclosures landed on the same company. Every number here is
   computed from real SEC filings; nothing is illustrative." Point at the feed-health strip:
   real record counts, real reject counts. "Honesty is the surface."

2. **Open a high-confidence cluster (60s).** Click the top cluster. Walk the parts: the
   convergence score, the confidence bucket, the distinct independent voices, the source
   classes, and — critically — the freshness chips. "Insider filings are days old; a 13F is a
   quarter old, and we show that difference, we never hide it." Read the plain-language
   explanation. "That prose is written by a model, but every number in it is checked against
   the computation — if the model invents a figure or says 'buy', it's discarded and a
   deterministic template renders instead."

3. **THE TRUST MOMENT (90s).** Pick one contributing insider purchase. Open EDGAR full-text
   search live: https://efts.sec.gov/LATEST/search-index?q= (or https://www.sec.gov/edgar/search/)
   and look up the issuer. Show the actual Form 4 on sec.gov. "This is the primary document.
   Our number came from it. You can do this with any signal on the platform." This is the
   entire pitch — verifiability.

4. **The backtest / methodology (90s).** Open the methodology tab. Show the calibration table:
   the honest hit rates where the sample is sufficient, and "insufficient sample" where it
   isn't. "We refuse to state a rate on fewer than 30 episodes. When we say a number, it's
   earned." Show the exclusion counts and the pre-commitment: the live curve replaces this
   backtest at 200 resolved signals per type.

5. **Bring-your-names (60s).** Type a ticker in the search box → the deep dive. Or click
   "import from screenshot," upload a brokerage screenshot: "we read the tickers only — never
   your prices, your size, or your P&L, and we never store the image." Add a couple to the
   watchlist.

6. **The paywall, shown honestly (45s).** Log in as the free demo user vs the pro user (or
   explain): "Free tier sees signals on a 48-hour delay — enforced server-side, no parameter
   can bypass it. Freshness is the paid product, and it's the one thing a scraper can't fix."

7. **The roadmap previews (30s).** Open the options and crypto tabs. "These are watermarked
   design previews — clearly not live data. Options flow and on-chain arrive post-funding via
   licensed feeds. We will never let a mockup be mistaken for a measurement."

8. **Close.** "Everything you saw is real primary-source data, computed point-in-time, honestly
   labeled, and verifiable against the SEC on the spot. That's the moat: the deepest legitimate
   data map in the category, and calibration you can trust."

## If asked "why is the sample short?"
Be direct: the demo used a bounded backfill window to fit the build timeline; the methodology
page states the exact sample window, and the full ten-year backfill runs before any public
launch so published calibration rests on the deep sample.
