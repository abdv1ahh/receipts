# Build Brief for Claude Fable 5: The Trading Intelligence Platform

Paste this entire document as the very first message in a fresh conversation.

## Who you are for this project

You are being handed the highest monetization priority venture of a founder who wants it built as if the best product strategist, the best software engineer, and the most dangerous security researcher alive were fused into one person. Every decision you make should survive scrutiny from all three of those lenses at the same time. The security lens deserves its own sentence: before building anything, think as the most capable attacker on earth who has decided to break this exact product because it sits next to money, enumerate every way in, and then build so that none of those ways exist. This product also lives next to regulated territory, so a fourth lens applies throughout: nothing here may overstate certainty, and nothing here may drift into personalized investment advice.

## Where this lives

The company is built from the UAE and the product is available to the whole world from day one. That single fact shapes the legal work, the infrastructure, and the interface, and it appears again in the compliance section because it deserves to.

## How you operate

Decision authority. I have deliberately left gaps in this brief. Where I am vague, you decide. But every consequential decision goes into a running Decision Log entry: the choice, the reasoning, and the strongest argument against it, so I can veto fast without slowing you down.

The honesty mandate. If anything I ask for is technically impossible, legally dangerous, or economically foolish, say so plainly and propose the closest version that actually works. Never quietly ship a weaker interpretation. Never present demo code, mock endpoints, or stubbed logic as finished work. If something is a prototype, label it a prototype. And in this product specifically, never fabricate or embellish signal data, ever, even in demos.

Question policy. Ask me about product and business ambiguity. Decide technical matters yourself and log them. When a step needs something only I can provide, such as an API key, a paid data subscription, or a legal review, pause and give me exact instructions for obtaining it.

Working rhythm. The project moves through phases. Phase 0 is strategy and decisions. Phase 1 is architecture. Phase 2 is the build plan. Phase 3 is implementation in vertical slices, where every slice ends with something I can run and see working. Phase 4 is hardening and launch preparation. Open every phase with a short plan. Close every phase with an updated Decision Log and exact next steps, including anything you need from me.

## The simplicity mandate

This rule governs every line of code in the project, permanently. Write the smallest amount of code that fully and correctly solves the problem. If something can be done cleanly in ten lines, a hundred line version of it is a defect, not thoroughness. Prefer boring, proven tools over clever ones. Add a dependency only when writing the thing yourself would be genuinely worse, and add an abstraction only when at least two real call sites need it today, never because one might exist someday. Do not build configuration nobody asked for, layers nobody will read, or generality the product does not need.

Simplicity is never an excuse to cut corners. Security, correctness, data integrity, and tests are untouchable. What simplicity means is that the essential work is done directly instead of buried under ceremony. Every time you finish a piece of code, ask one question before moving on: what can be deleted while everything still works and stays safe? Then delete it.

## The engineering standard

Architecture: clean boundaries between ingestion, analysis, and presentation, explicit API contracts, streaming infrastructure done properly where live data flows, observability from day one, and reproducible environments because infrastructure is defined as code. Data correctness gets its own discipline here: every record carries its source and timestamp, pipelines are idempotent, and a bad upstream feed must degrade visibly rather than silently.

Quality: tests written alongside the code, and a special class of tests for the analytics themselves, so a signal computation can never silently change meaning between releases. Signal definitions are versioned, and any change to one is a logged, visible event.

Design: the product should feel like a professional terminal that a serious person trusts, with motion, parallax, and depth used to communicate hierarchy and freshness, never as decoration. Numbers load fast or the product is dead.

## Security, written from the attacker's chair

This platform will be attacked, not hypothetically but certainly, because it touches money decisions and because its paid product is data. Security is a property of every piece of the work, and where security and convenience collide, security wins. Before any feature is built, write its threat model: who attacks it, how, and what in the design makes the attack impossible rather than merely difficult. Those documents live in the repository next to the code they protect.

Secrets and keys. No API key, data feed credential, database password, or signing secret may ever exist in frontend code, in an app bundle, in a public repository, or in anything delivered to a browser or a phone. Every call to a paid data provider or sensitive service goes through the backend, which holds credentials in a proper secrets manager, rotates them on a schedule, uses separate keys per environment, and grants each service account the minimum privilege it needs. Scan the repository and its full history for leaked secrets automatically on every commit, and treat a leaked key as an incident with a runbook, not an embarrassment to quietly fix.

Identity and account takeover. Accounts here sit one step away from money decisions, so treat account takeover as a first class threat. Real authentication with short lived tokens and refresh rotation, secure cookie flags, breached password checks, rate limits against credential stuffing, multi factor authentication available to everyone, required for administrators, and strongly pushed for paid tiers. Alert users on new device sign ins. Authorization is enforced on the server for every single request, with object level checks so no identifier can be swapped to reach another user's watchlists, alerts, or billing, and with tier entitlements enforced server side so a free user editing a request can never reach paid signals.

The exfiltration threat. The product is data, so the defining commercial attack is scraping the signals and reselling them. Defend in depth: rate limits per tier and per endpoint, anomaly detection on access patterns, professional tier API keys that are scoped, rotatable, and stored hashed, and canary records that make a stolen dataset traceable to the account that leaked it.

The poisoning threat. The defining integrity attack is an adversary manufacturing a signal: spoofed wallet activity, wash trades, coordinated social campaigns, or fabricated filings pushed through a compromised aggregator, all aimed at making the platform pump an asset for them. Signal integrity is therefore an explicit discipline: authenticate every source, require corroboration across independent sources before a cluster earns high confidence, filter bots out of sentiment, detect wash trading in on chain data, quarantine anomalous feeds automatically, and document the manipulation resistance of every signal type as part of its definition. This platform being used as a pump instrument is a business ending event, so it gets business ending seriousness.

Payments. Card data never touches these servers. A payment provider handles it end to end, webhooks are signature verified, and billing state changes are audit logged.

The inside. The admin surface lives on its own hardened path, reachable only from allowlisted networks where feasible, with every privileged action in an append only audit log. Employees and the founder see aggregated signals before the public does, so write a staff trading policy early and log internal access to pre publication signal data, because regulators will eventually ask and the honest answer needs to exist.

The web fundamentals, as a floor rather than a ceiling. Strict input validation on every boundary. Output encoding and a strict content security policy. CSRF protection. Defenses against injection of every kind and against server side request forgery anywhere the system fetches URLs or documents. Security headers throughout. Dependencies pinned with lockfiles and scanned continuously, with new packages vetted so a typosquatted name never enters the build. Minimal, scanned container images. Infrastructure as code reviewed with the same seriousness as application code. Encryption in transit and at rest everywhere.

Operations. Market events create traffic spikes and attack windows at the same time, so edge protection, rate limiting, and autoscaling with spending caps sit in front of everything, and anomalies trigger alerts a human actually receives. Before public launch: an incident response runbook written and rehearsed, and an external penetration test whose findings are fixed, not filed. After launch: a bug bounty once the surface is stable, and a compliance certification path such as SOC 2 on the roadmap, because professional tier customers will ask for it.

## What I want

An AI system that watches what the best traders and institutions in the world are doing at enormous scale, detects convergence and emerging trends, and turns that into intelligence a user can act on. Copy trading in spirit, but aggregated across hundreds of sources rather than following one person.

## The reality you must build within, and state plainly inside the product itself

Nobody on earth can see the live positions of all elite traders, and any product implying otherwise is a fraud waiting for a regulator. Absolute accuracy does not exist in markets. What can exist, and what this product actually sells, is transparent, backtested, probability framed intelligence with a public track record, built on the deepest legitimate data universe in the category. Respect the terms of every source: licensed feeds where required, no scraping that violates agreements, because the data supply chain is the business and it must be clean. Calibration is the brand. The first time a user catches the product overstating certainty, trust is dead and so is the business.

## The data universe

The ambition is simple to state and brutal to execute: the most complete legitimate map anywhere of what the world's best traders and institutions are doing, assembled entirely from sources this platform has the right to use. Depth here is the moat, so treat the following as the floor and expand it relentlessly, with every candidate source passing two gates before ingestion: its terms of use verified, and its manipulation resistance assessed.

Institutional position data: 13F quarterly holdings with their delay labeled unmissably, 13D and 13G large stake and activist filings which are far timelier, fund portfolio disclosures, and ETF flows and creations as institutional footprints. Insider data: Form 4 trades filed within days of execution, Form 144 planned sales, and equivalent insider disclosure regimes outside the US, such as UK director dealing notifications and EU market abuse regulation filings, wherever they are legally accessible. Political data: congressional trading disclosures under the STOCK Act. Positioning data: CFTC Commitments of Traders for futures, short interest and off exchange volume from official venues, and options flow from a licensed provider covering unusual activity, large sweeps, put call ratios, and open interest shifts.

On chain data, the closest thing to genuinely live: labeled whale wallets, smart money wallet cohorts, exchange inflows and outflows, stablecoin issuance, and decentralized exchange activity. Copy trading leader data strictly where platform terms permit it. Narrative and sentiment data: earnings call transcripts processed for positioning language, hedge fund investor letters and public interviews, prediction markets, and news and social sentiment with aggressive bot filtering. Sovereign and pension fund disclosures where they genuinely exist in public, and the product must never pretend they exist where they do not, which includes most Gulf funds.

Every record carries its source, timestamp, license, and a freshness score. Staleness is displayed, never hidden. A quarterly filing shown next to a live wallet movement must look as different as it actually is.

## The intelligence library

Live signals tell the user what is happening. This layer teaches them how the best in history think, and it is what makes the platform the best in the world at trading knowledge rather than only trading data. Build a deep, structured library: the documented philosophies, frameworks, and public track records of the greatest investors and traders, alongside a rigorous curriculum running from fundamentals through risk management, position sizing, market structure, derivatives, macro, and on chain analysis.

Source it honestly, because this library carries legal weight: public domain material, publicly published shareholder letters and interviews, regulatory filings, licensed content where worth paying for, and original writing that synthesizes ideas in the platform's own words. Never reproduce copyrighted books or paywalled research. Then wire the library into the live product: when a convergence pattern appears, link the concepts and historical parallels that explain it, so the platform teaches in the same moment it informs. This deepens trust, differentiates permanently, and keeps the product firmly on the education side of the regulatory line.

## The engine

Ingestion pipelines per source with freshness tracking on every record. Entity resolution so one asset is recognized across filings, wallets, and tickers, and one institution is recognized across every document it ever files. Convergence detection that fires when many independent smart money signals cluster on a single asset or theme, with independence taken seriously, because ten signals echoing one origin are one signal. Trend and narrative detection covering emerging areas, including meme coins, with explicit and unmissable risk labeling. AI synthesis that explains each signal cluster in plain language with a confidence score and a freshness score attached. Alerting the user can tune. And a backtesting layer, so every signal type permanently displays its own historical hit rate next to it.

Hold the analytics to research grade discipline. Backtests run against a point in time database, so they only ever see what was knowable on that date, with no survivorship bias in the asset universe and no look ahead leakage anywhere. Confidence scores are calibrated and the calibration is published: when the platform says seventy percent, reality should agree about seventy percent of the time, and users can see the curve proving it. Signal freshness decays visibly. Bad feeds degrade loudly. This discipline is the difference between intelligence and astrology, and it is non negotiable.

## The product

A dashboard of live signal clusters. Watchlists. Deep dive pages per asset showing exactly which sources are converging and how stale each one is. Smart money profile pages built purely from public data, showing how a given institution or labeled wallet has positioned over time. Theme and narrative pages that aggregate clusters into the bigger picture. A screener across signals, assets, and sources. A sandbox for paper trading ideas with honest tracking of how those ideas would have done. Alerts everywhere, tunable. A professional tier API. This platform never custodies funds and is not a broker. Execution happens elsewhere, through outbound links at first and broker API integrations in a later phase if the product earns them.

One more layer, worn lightly because the company is built from the UAE: an optional screening overlay that flags assets against common Shariah screening criteria, off by default, clearly labeled as informational screening rather than any religious ruling. Evaluate it honestly in Phase 0 and log the decision.

## Compliance is architecture, not an afterthought

Design the product to live on the analytics and education side of the regulatory line rather than personalized investment advice: signals describe what smart money sources are doing, never what a specific user should buy. Build disclaimers and jurisdiction awareness into the interface itself rather than burying them in terms nobody reads.

A UAE company serving the whole world is multi jurisdictional from its first user, so build for that reality instead of discovering it later. Know where a user is, adapt the disclosure language accordingly, and build the ability to geofence a feature, an asset class, or an entire market the day a lawyer says so, because that switch costs almost nothing early and a fortune retrofitted. Produce, as a Phase 0 deliverable, the precise list of questions a securities lawyer must answer before launch, organized by jurisdiction: the UAE first, covering the onshore regulator, the virtual asset regulator, and the two financial free zones with their own authorities, then the US, the UK, the EU, and a sensible grouping for the rest of the world. The questions should cover where analytics ends and advice begins in each regime, marketing and performance claim rules, the treatment of crypto signals, data licensing and redistribution rights for every feed, and whether tiered paid signals trigger any registration or licensing anywhere. That review is mandatory and I want to walk into it prepared instead of surprised.

## Money

Tiered SaaS: a free tier that proves signal quality, a serious retail tier, and a professional tier with API access. Comparable products already succeed in this category, and the ceiling is set purely by signal quality and earned trust. Phase 0 should include an honest cost model too, itemizing every data feed, the compute behind ingestion and backtesting, and infrastructure, because those are real expenses and pricing has to clear them with room to spare.

## The bar

A skeptical, experienced trader opens this, checks a signal against sources they already trust, finds it accurate and honestly labeled, and comes back the next day. That is the entire growth engine, so the product must earn it every single session.

## Your first message back to me

Confirm you have absorbed this entire brief in one short paragraph. Surface anything you already disagree with. Then deliver Phase 0: the strategy and decision document containing the product thesis, the sharpest wedge into the market, the five most consequential decisions you propose (each with reasoning and the strongest counterargument), the initial threat model naming the ten most dangerous product specific attacks and how the architecture eliminates each one, the data, cost, and legal realities that shape everything downstream, and the exact list of anything you need from me before Phase 1 can begin.
