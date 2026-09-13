# Can this codebase become an event-to-company-exposure engine?

A read-only investigation, 2026-08-23. Everything below was measured against the running
stack and the live SEC and GDELT APIs on the day of writing. Where a figure in the brief
differed from what I measured, I have used my measurement and said so.

No application code was changed. Two temporary claims were inserted into the development
database to run the real resolver end to end, then deleted; the claim and outcome counts
before and after are identical and are shown in Question 1.

---

## Corrections to the figures in the brief

Three of the numbers I was given have moved, and one was wrong in a way that matters.

The impact engine has **142 claims — 133 unscoreable and 9 open**, which matches. But the
signal plane has **473 resolved claims**, not 412. The 412 figure is the count of
*hit-or-miss outcomes*; another 61 resolved to `inconclusive`, which is a real verdict in
this system rather than a discard. The **178 hits and 234 misses** are exactly right.

There are **273 unscoreable outcome rows** but only **133 unscoreable claims**, because an
impact-engine claim names several subjects and each gets its own outcome row. The nine open
claims have no outcome rows at all.

The events corpus is **4,038 events**, of which **2,697 (66.8%) are `other`**,
**80 are `supply_chain` (2.0%)** and **30 are `trade_policy` (0.7%)**.

---

## Question 1: why the impact engine cannot be scored

### The single note, and why it is lying

Every one of the 273 unscoreable outcome rows carries the same note, with no variation at all:

```
no price series for this subject   | 273
```

That note is generated in `tradeos/ledger.py:103`, in `verdict_for`, which returns
`("unscoreable", "no price series for this subject")` whenever the excess return handed to it
is `None`. The problem is that `None` arrives there for two completely different reasons and
the note only describes one of them. In `measure_claim`:

```python
excess, _why = excess_return(sym, spy, as_of_day, horizon_days)   # ledger.py:149
```

`excess_return` returns a second element specifically so the caller can tell the two cases
apart — its docstring says so: *"The second element flags WHY it is None so the driver can
separate 'horizon still open' from 'excluded for missing price history'."* The Ledger binds it
to `_why` and throws it away. So a subject that has a full five-year price series and a subject
that is the word "tourism" produce byte-identical diagnostics. That is why 133 claims look like
one problem when they are actually two.

### Blocker one: the resolver only prices one of the five subject kinds

`tradeos/ledger.py:146` is the precise line where an impact-engine claim stops being scoreable:

```python
if item.get("kind") in ("asset",) and subject:
```

Only `kind == "asset"` is ever looked up in `prices_eod`. Everything else falls straight
through to `verdict_for(direction, None)`. Meanwhile `claims.py:39` lets the model emit five
kinds:

```python
KINDS = ("asset", "sector", "currency", "region", "commodity")
```

Four of those five are unscoreable by construction. Across all 142 impact claims there are
**292 affected subjects**, split like this:

| kind | subjects | share | scoreable? |
|---|---|---|---|
| sector | 116 | 39.7% | no |
| region | 71 | 24.3% | no |
| commodity | 47 | 16.1% | no |
| asset | 33 | 11.3% | only if it is a real ticker with prices |
| currency | 25 | 8.6% | no |

**259 of 292 subjects (88.7%) are sectors, regions, commodities or currencies.** The model is
not misbehaving — it is using the vocabulary it was handed. The prompt at `claims.py:98-100`
offers all five kinds as equals and says only "Use real tickers/currency codes/commodity
names". Nothing tells the model that four of the five options cannot be scored, so it picks
the one that best describes the event, which for a world-news event is almost always a sector
or a region.

Even inside `kind == "asset"` the values are not all tickers. Of the 33 asset subjects, only
**20 have a plain ticker shape** (`^[A-Z]{1,5}$`), covering **17 distinct symbols**. The rest
are prose: `stocks`, `equities`, `US Treasuries`, `Treasury bonds`, `SHEIN IPO`,
`Chinese chipmaker shares`, `IDX Composite Index`, and
`AMC Entertainment Holdings Inc. (AMC)`. So **20 of 292 subjects (6.8%) are cleanly named
tickers**.

### Blocker two: the price universe is the wrong universe, and it is stale

Of those 17 distinct tickers, **exactly 2 have any price history**: `BA` and `SPY`. The
others — `AAPL`, `MSFT`, `META`, `NVDA`, `JNJ`, `PLTR`, `SBUX`, `EBAY`, `UPS`, `V` — return
zero rows.

That is not a gap; it is a different universe. `prices_eod` holds **499 symbols, 235,162 rows,
2021-06-01 to 2026-07-24**, and those 499 symbols are exactly the set referenced by
`signal_clusters`. `cli.py:159-174` shows why: `ingest-prices` draws its symbol list from
`backtest.symbols_for_clusters(conn)` — the issuers that appear in smart-money signal
clusters. The price feed was built to serve the signal plane and has never been asked to cover
anything the impact engine names. Apple is absent because Apple has never triggered a 13D/G
convergence cluster.

Then there is the second, subtler failure, and it is the one the misleading note hides.
**All 142 impact claims were created between 2026-07-25 and 2026-07-30. The price table ends
2026-07-24.** In `backtest/engine.py:53`:

```python
entry = _first_gt(sym.days, as_of_day)          # first trading day strictly after as_of
if entry is None or entry not in spy.close:
    return None, "no_entry_price"
```

For a claim made on 2026-07-26 there is no trading day after that date anywhere in the series,
so `entry` is `None` and the function returns `no_entry_price`. This is why `BA` and `SPY` —
which have 1,293 price rows each — are still recorded as "no price series for this subject".
Their series ends two to four days *before* the claims that name them were even made.

So the two claims naming `BA` and the one naming `SPY` are blocked by staleness, and the other
139 are blocked by vocabulary. Fixing the price feed alone would unlock **3 claims out of 142**.

### The nine open claims are fine

They are not stuck. All nine are `months`-horizon claims (`horizon_days = 90`) created
2026-07-25 to 2026-07-27 and due 2026-10-23 to 2026-10-25. `measure_due` correctly leaves them
alone because their horizon has not elapsed. There is no bug here.

### Would the resolver score a ticker-only claim without modification? Yes. Here is the proof.

I built two claims from real historical data and ran them through the real
`tradeos.ledger.measure_claim` — not a reimplementation, the actual function the scheduler
calls. Both were dated 2026-05-01 with a 21-day (`weeks`) horizon, placing the whole window
inside the price coverage that exists. Subjects were drawn from the real price table:
ABCL rose 15.25% and ABR fell 28.99% over the window while SPY rose 4.54%.

**Claim A — only listed companies, by ticker:**

```
measure_claim() -> {'claim_id': 622, 'status': 'resolved',
                    'hit': 1, 'miss': 1, 'inconclusive': 1, 'unscoreable': 0}
  ABCL   pred=up  hit           entry=2026-05-04 exit=2026-05-26 excess=+0.1071
  ABR    pred=up  miss          entry=2026-05-04 exit=2026-05-26 excess=-0.3353
  ADM    pred=up  inconclusive  entry=2026-05-04 exit=2026-05-26 excess=-0.0157
                                moved -1.57% vs SPY, inside the 2% noise floor
  claims.status -> resolved
```

**Claim B — the same three tickers plus the abstractions the engine emits today:**

```
measure_claim() -> {'claim_id': 623, 'status': 'resolved',
                    'hit': 1, 'miss': 1, 'inconclusive': 1, 'unscoreable': 3}
  ABCL              hit           excess=+0.1071
  ABR               miss          excess=-0.3353
  ADM               inconclusive  excess=-0.0157
  BRENT CRUDE OIL   unscoreable   no price series for this subject
  NORTH AMERICA     unscoreable   no price series for this subject
  TECHNOLOGY        unscoreable   no price series for this subject
  claims.status -> resolved
```

The answer is unambiguous: **the resolver already works, correctly, with zero modification.**
It produced a hit, a miss, a correctly-floored inconclusive, proper entry and exit days on the
right trading sessions, and excess returns measured against SPY. It also demonstrates the
noise floor doing its job — ADM's −1.57% is honestly recorded as inconclusive rather than
counted as a miss.

Claim B additionally shows that the two failure modes coexist cleanly: naming a sector
alongside tickers does not break the claim, it just adds unscoreable rows beside the scoreable
ones, and the claim still resolves.

The database was restored afterwards. Before and after, identically:

```
resolved 473 | unscoreable 133 | open 9
unscoreable 273 | miss 234 | hit 178 | inconclusive 61
```

### What this means

The impact engine's scoring problem is **not** a resolver problem. It is a vocabulary problem
with a data-coverage problem stacked behind it. In order of what actually blocks scoring:

1. **The claim prompt does not ask for tickers.** 88.7% of subjects are unscoreable by kind.
   This is the whole ballgame, and it is a prompt change plus a validation rule, not an
   engineering project.
2. **The price universe covers the wrong companies.** Even perfect claims would find 2 of 17
   named tickers priced.
3. **The price feed is stale by two days relative to the claims**, which silently zeroes out
   even the subjects that would otherwise work.
4. **The note field discards the reason**, which is why (2) and (3) have been invisible and
   looked like (1).

---

## Question 2: is geographic revenue available in structured form?

Short answer: **yes, in structured, machine-readable XBRL with explicit country and region
dimensions — but not from the endpoints you would first reach for.** It is not prose-only, and
it does not require parsing 10-K narrative. It is in a different SEC product than the one this
codebase currently touches.

### companyfacts and frames do not have it, structurally

I pulled `companyfacts` for five large caps and five mid caps. All ten returned HTTP 200.

| ticker | CIK | entity | tags | geo-named tags | revenue facts, FY 10-K |
|---|---|---|---|---|---|
| AAPL | 320193 | Apple Inc. | 505 | 21 | one value per period |
| MSFT | 789019 | Microsoft Corporation | 565 | 24 | one value per period |
| NVDA | 1045810 | NVIDIA Corp | 643 | 14 | one value per period |
| JNJ | 200406 | Johnson & Johnson | 611 | 23 | one value per period |
| KO | 21344 | Coca Cola Co | 726 | 39 | duplicates, see below |
| CROX | 1334036 | Crocs, Inc. | 545 | 37 | one value per period |
| YETI | 1670592 | YETI Holdings, Inc. | 377 | 9 | one value per period |
| COLM | 1050797 | Columbia Sportswear | 455 | 20 | duplicates, see below |
| WING | 1636222 | Wingstop Inc. | 338 | 11 | one value per period |
| FIVE | 1177609 | Five Below, Inc. | 310 | 2 | one value per period |

The decisive evidence is not the counts — it is the **shape of a single fact**. Every fact in
every one of the ten responses has exactly these keys:

```
['accn', 'end', 'filed', 'form', 'fp', 'frame', 'fy', 'start', 'val']
```

There is no `dimensions`, no `segment`, no `axis`, no `member`. The geographic breakdown in a
filing is carried by XBRL dimensions, and **companyfacts does not expose dimensions at all**.
This is not a coverage gap that varies by filer; it is the design of the endpoint. A real
Apple fact looks like this:

```json
{"start": "2024-09-29", "end": "2025-09-27", "val": 416161000000,
 "accn": "0000320193-25-000079", "fy": 2025, "fp": "FY", "form": "10-K",
 "filed": "2025-10-31", "frame": "CY2025"}
```

One consolidated number. Nowhere to hang a country.

Two false leads worth recording so nobody follows them again:

**The `Geograph`-named tags are not what they look like.** JNJ carries
`EntityWideDisclosureOnGeographicAreasRevenueFromExternalCustomersAttributedToIndividualForeignCountriesAmount`,
which sounds exactly right. It is labelled **"(Deprecated 2011-01-31)"** and holds three facts,
all from a single 2011 filing, all un-dimensioned. Most of the other geo-named tags across the
ten filers are tax-line items — `CurrentForeignTaxExpenseBenefit`,
`DeferredTaxLiabilitiesUndistributedForeignEarnings` — not revenue.

**The "multiple per period" cases are amendments, not breakdowns.** For KO and COLM I checked
whether duplicate facts within one period were a hidden geographic split. Every duplicate
period holds the **same value**, restated across successive filings. Not a breakdown.

The `frames` endpoint is worse, and dangerously so:

```
us-gaap/Revenues/USD/CY2024.json                      HTTP 200, 2497 filers
per-filer keys: ['accn', 'cik', 'end', 'entityName', 'loc', 'start', 'val']
sample: {"cik": 2098, "entityName": "ACME UNITED CORP", "loc": "US-CT",
         "start": "2024-01-01", "end": "2024-12-31", "val": 194489991}
```

There *is* a `loc` field, and it is a trap. `US-CT` is Acme United's **registered business
address in Connecticut**, not where its revenue came from. This is precisely the
outlet-versus-subject confusion that `CLAUDE.md` lists as gotcha #2 and calls "the single most
repeated mistake in this project — made three times." Using `frames.loc` as revenue geography
would make it four.

Attempts to ask `frames` for a dimension directly both 404:

```
us-gaap/RevenueFromContractWithCustomerExcludingAssessedTax/country:US/USD/CY2024.json  -> 404
srt/RevenueFromExternalCustomersByGeographicAreas/USD/CY2024.json                       -> 404
```

`companyconcept` is the same data as companyfacts filtered to one tag, with the same
dimensionless fact shape. No help.

### Where it actually lives: the DERA Financial Statement Data Sets

The SEC publishes quarterly bulk archives at
`https://www.sec.gov/files/dera/data/financial-statement-data-sets/YYYYqN.zip`. I downloaded
2025q1 (128 MB) and 2025q4 (66 MB). The archive contains `sub.txt`, `num.txt`, `pre.txt`,
`tag.txt`, and `num.txt` has the column companyfacts lacks:

```
['adsh', 'tag', 'version', 'ddate', 'qtrs', 'uom', 'segments', 'coreg', 'value', 'footnote']
```

`segments` carries the dimensions, serialised as `Axis=Member;` pairs. Real rows:

```
Revenues                                            segments=Geographical=US;                    ddate=20231231  value=393355000
RevenueFromContractWithCustomerExcludingAssessedTax segments=Geographical=MX;                    ddate=20221231  value=3931000
Revenues                                            segments=Geographical=NorthAmerica;          ddate=20221231  value=15163000000
RevenueFromContractWithCustomerExcludingAssessedTax segments=BusinessSegments=BiologicsSafetyTestingSegment;Geographical=AsiaPacific;
                                                                                                 ddate=20221231  value=24286000
```

Scanning the **full** 2025q1 quarter — 3,658,551 numeric facts across 6,231 submissions:

- **4,481 filers report some revenue tag**
- **1,715 of them (38.3%) report revenue broken out by geography**
- **35,719 geographic revenue fact rows**, mostly from 10-Ks (25,262), then 10-Qs (5,177) and
  20-Fs (3,126)

Granularity per filer is genuinely useful: 466 filers report 2 geographies, 339 report 3,
277 report 4, 189 report 5, and 322 report 6 or more.

And Apple, which showed no geographic revenue in 2025q1 purely because its September fiscal
year puts its 10-K in a different archive, is fully present in **2025q4**:

```
AAPL 10-K  RevenueFromContractWithCustomerExcludingAssessedTax  US              ddate=20250930  value=151,790,000,000
AAPL 10-K  RevenueFromContractWithCustomerExcludingAssessedTax  CN              ddate=20250930  value= 64,377,000,000
AAPL 10-K  RevenueFromContractWithCustomerExcludingAssessedTax  OtherCountries  ddate=20250930  value=199,994,000,000
```

Three fiscal years, exact dollar values, machine-readable. Seven of the ten probe companies
have it; MSFT reports `US`/`NonUs`, NVDA reports `US`/`TW`/`SG`/`ChinaIncludingHongKong`/
`OtherCountries`, JNJ reports six members, COLM reports five. WING and FIVE genuinely have
none — they are domestic-only businesses, which is a true negative, not a data gap.

### The catch, and it is the important one

**988 distinct member strings** appear across those 35,719 facts, and only **42.3% are bare
ISO-3166 country codes**. The top members by volume:

```
US 6772 · NonUs 2472 · Europe 1955 · AsiaPacific 1945 · NorthAmerica 1562 · CA 1341
EMEA 1272 · Americas 973 · CN 873 · GB 817 · Asia 600 · LatinAmerica 568
OtherCountries 501 · International 452 · RestOfWorld 441 · DE 419 · MX 374
```

So more than half the data is regions, buckets, and filer-invented members
(`OtherThanUnitedStates`, `WesternHemisphereExcludingUS`, `LatinAmericaAndAsiaPacific`,
`AllOtherCountries`, `OtherForeignCountriesThree`). Normalising 988 strings onto a country and
region taxonomy is the actual work of this adapter, and it will never be lossless. Look again
at Apple: **$199,994,000,000 — 48% of its total revenue — sits in a member called
`OtherCountries`.** No engineering recovers what the filer chose not to disclose.

### What an adapter would involve

**Reusable as is:**

- `EdgarClient`'s throttle / exponential-backoff / sha256-checksum pattern, and its
  `ALLOWED_HOSTS` already contains `www.sec.gov`, which is where the bulk ZIPs live. Note it
  is constructed with `follow_redirects=False`; my downloads used redirects, so that needs
  checking rather than assuming.
- `ingestion/common.reject()` for per-row rejects, the `source_calls` recording convention,
  the ordered-`.sql` migration pattern, and the `sources.py` CATALOG requirement.
- `tradeos/resolution/` for CIK → ticker. The bulk set keys on CIK and accession only, so this
  is load-bearing, and it already exists and works.
- The point-in-time discipline: `sub.txt` carries the filing date, which maps cleanly onto the
  existing `knowable_time` convention.

**Not reusable:** `sgml.py`. It parses the SGML submission *header* — acceptance datetime,
form type, filer CIKs. It has nothing to do with XBRL facts and offers zero reuse here. That is
worth saying plainly, because its name suggests otherwise.

**New work:** a migration and table for company × geography × period × value; a streaming
TSV reader (3.6 M rows per quarter, so it must stream rather than load); a `segments` parser;
the member-normalisation taxonomy; CIK→ticker wiring; a CLI command; a backfill across
quarters; tests; the CATALOG entry and integration-page state.

**Estimate: 8 working days** for a solid first version, of which roughly three are the
normalisation taxonomy alone. The top 30 members cover most of the volume, so a useful version
lands sooner than a complete one. Backfilling history is a one-off overnight cost — roughly
68 quarters at 60–130 MB each.

For contrast, the route this question originally proposed — an adapter parsing geographic
tables out of 10-K and 10-Q *documents* — would be several weeks and produce worse data. It is
not needed. **Do not build it.**

---

## Question 3: are trade policy events missing, or mislabelled?

Both, but the honest answer is **mostly missing** — and the mislabelling has a cause that is
much more embarrassing and much cheaper to fix than it looks.

### The measured split

4,038 events:

| category | n | % |
|---|---|---|
| other | 2,697 | 66.8 |
| conflict | 332 | 8.2 |
| technology | 276 | 6.8 |
| monetary_policy | 204 | 5.1 |
| earnings | 115 | 2.8 |
| supply_chain | 80 | 2.0 |
| disaster | 76 | 1.9 |
| regulation | 53 | 1.3 |
| macro | 39 | 1.0 |
| election | 32 | 0.8 |
| **trade_policy** | **30** | **0.7** |
| health / labour / corporate / energy | 104 | 2.6 |

### Reading 100 random `other` events

I sampled 100 at random and read them. **Six are genuinely trade policy, sanctions or supply
chain disruption:**

- *"...a whiplash year of President Trump's **tariffs**... American brands seeking a location
  for their factories"* — trade policy and production relocation
- *"Houthis want to copy Iran's Hormuz control in the Red Sea"* — chokepoint control
- *"Iran's government signals fuel price hike on eve of new US **sanctions**"* — sanctions
- *"Iran rejects Trump frozen funds plan, warns ships of Hormuz **transit ban**"* — shipping
- *"...threatens U.S. **supply chains** and competitiveness"* — supply chain
- *"A tanker... under European **sanctions** is leaking oil off Oman"* — sanctions and shipping

Three more are arguable — Geely building EVs at a Ford plant in Spain, Kia moving $649 M of EV
production to Mexico, Taiwan's record defence budget. All three are cross-border production
and policy responses, but none names a policy instrument, so I have excluded them from the
count. Strictly **6 of 100**; generously **9 of 100**.

A regex sweep of the full `other` bucket for explicit trade, sanctions and supply-chain
vocabulary finds **78 of 2,697 (2.9%)**. The 6% sample rate and the 2.9% sweep are consistent —
the binomial 95% interval on 6/100 is roughly [2.2%, 12.6%] — with the sweep being a
conservative floor because it requires named vocabulary. The honest range is **3–6%, or
roughly 80 to 160 events**.

### Why they were missed: the cue table cannot match plurals

`classify()` in `spine.py:106` is a deliberate lookup table, ordered, first match wins. The
cues are compiled with word boundaries at `spine.py:103`:

```python
alternation = "|".join(re.escape(c) for c in cues)
_CUE_PATTERNS.append((category, re.compile(rf"\b(?:{alternation})\b", re.IGNORECASE)))
```

`\btariff\b` cannot match `tariffs`. The trailing `\b` requires a non-word character after
`tariff`, and `s` is a word character. I ran the real classifier to confirm:

```
trade_policy       Tariff on steel announced
other              Tariffs on steel announced
regulation         New sanction on Russia
other              New sanctions on Russia
monetary_policy    Interest rate decision due
other              Interest rates held steady
disaster           Wildfire spreads in Spain
other              Wildfires spread in Spain
supply_chain       Supply chain disruption worsens
other              Supply chains disrupted worsens
supply_chain       Export ban imposed
other              Export bans imposed
```

**Every plural falls to `other`.** And the corpus confirms this is not theoretical — within
the `other` bucket:

| term | occurrences in `other` |
|---|---|
| "tariffs" (plural) | 37 |
| **"tariff" (singular)** | **0** |
| "sanctions" (plural) | 26 |
| **"sanction" (singular)** | **0** |

The singular counts being **exactly zero** is the proof. Any event using the singular was
caught by the cue and never reached `other`. Every trade-policy event that landed in `other`
did so because it used a plural.

The most damning detail: the cue list contains **both `"port"` and `"ports"`**
(`spine.py:79`), with a comment about cue hygiene directly above it. The author hit the plural
problem once, patched that single instance, and never generalised it. Nothing else in the
table has a plural form.

There are two further defects in the same function.

**Ordering.** The table is checked in order and `trade_policy` sits ninth of thirteen, behind
`conflict` (second) and `regulation` (fourth). So:

```
conflict           Trade war escalates
```

`\bwar\b` matches inside "trade war", and `conflict` is checked first. Likewise `sanction`
lives in `regulation`, so "sanction on Russia" is regulation, never trade policy. The two
categories most likely to contain a trade-policy story are both evaluated before it.

**Missing vocabulary.** These all return `other`:

```
other  Export controls on chips          other  Embargo on Iranian oil
other  US imposes levy on imports        other  Section 301 investigation opened
other  Entity list additions announced   other  Anti-dumping duty set
other  Import duties raised              other  Trade barriers rise
other  Customs duty increase             other  Protectionism grows
```

The `trade_policy` cue list is six entries long: `tariff`, `trade deal`, `trade war`,
`import duty`, `wto`, `quota on`. It has no word for export controls, embargoes, entity
listings, anti-dumping, countervailing duties, or protectionism — the actual vocabulary of
2020s trade policy.

The brittleness is not confined to trade. *"Divided Fed holds interest rates steady, but three
members voted to hike... the Federal Open Market Committee voted 9-3 to leave the federal funds
rate..."* is classified `other`. "interest rates" is plural, "Federal Open Market Committee" is
spelled out rather than "fomc", "federal funds rate" is not a cue, and "the fed" requires that
exact string. An unambiguous FOMC decision misses every one of eight monetary-policy cues.

### GDELT: the queries never ran

This is the clearer half of the answer. GDELT's five topic queries are defined at
`gdelt.py:64-70` in this order: `monetary_policy`, `conflict`, `supply_chain`, `energy`,
`trade_policy`.

Every GDELT event in the database:

```
conflict          142
monetary_policy   142
```

**The first two queries only.** `supply_chain`, `energy` and `trade_policy` — positions three,
four and five — have produced **zero events, ever**. GDELT contributed 284 of 4,038 events, and
none of them is a trade-policy event, because that query has never successfully executed.

The mechanism is in `ingest()` at `gdelt.py:186-189`: a 429 sets `rate_limited` and `break`s
the entire pass. Since `QUERIES` is a fixed ordered list and the limiter bites after two or
three requests, the loop reliably dies before reaching position three. `trade_policy` is last,
so it is starved by construction.

The call history in `source_calls` — 118 calls, 2026-07-25 to 2026-08-23:

| status | calls | share | avg ms |
|---|---|---|---|
| 0 (exception) | 89 | 75.4% | 3,168 |
| 429 | 22 | 18.6% | 14,064 |
| 200 | 7 | **5.9%** | 18,351 |

**Seven successful calls in a month.** And since 2026-08-21 there have been 57 calls and not a
single 200 — 30 on the 21st, 25 on the 22nd, 2 on the 23rd, all status 0.

A live probe just now, from a cold start with no prior traffic from me, using the adapter's own
User-Agent and its exact `trade_policy` query:

```
HTTP 429  12796ms  bytes=444
"Please limit requests to one every 5 seconds or contact ... for larger queries.
 All high-traffic users should switch to our ngrams dataset..."
```

Rate-limited on the very first request. The adapter's own docstring already documents this:
GDELT's throttle is keyed on the User-Agent and "once a UA is penalised it stays penalised for
hours." The project deliberately refuses to rotate the UA, which is the right call and should
not change.

There is a real bug compounding it. `_in_backoff()` at `gdelt.py:56` looks only for
`status = 429`:

```sql
SELECT ... FROM source_calls WHERE source = 'gdelt' AND status = 429
```

But 75% of failures are recorded as **status 0**, from the generic `except Exception` branch —
most likely `ValueError("gdelt returned a non-JSON body")`, raised when GDELT answers with a
200 and a plain-text rate-limit message, which the adapter's own comment at `gdelt.py:160`
warns it does. **The most common rate-limit signature is invisible to the backoff logic**, so
the six-hour penalty never triggers, the scheduler keeps hammering, and the UA stays
permanently penalised. It is a self-reinforcing failure loop: 30 calls in one day, zero
successes, no backoff.

So, to answer the question as posed: the low event count is **not** queries that are too
narrow, and **not** GDELT returning little. It is **backoff triggering constantly and being
mishandled**, plus an ordering choice that puts trade policy last in a list that never gets
past position two.

### What fixing all of it actually buys

Repairing plurals, reordering the table, and adding modern trade vocabulary would move perhaps
80–160 events out of `other`, taking `trade_policy` + `supply_chain` from 110 to roughly 190–270
of 4,038. That is a real improvement and it costs about **two days**.

But it does not make this a trade-policy corpus. **Bluesky is 2,159 of 4,038 events (53.5%)**,
and 1,705 of those sit in `other` — it is general social news, not policy reporting. The
corpus is thin on trade policy because the ingestion is thin on trade policy, not mainly
because the labels are wrong. Fixing the classifier is necessary and cheap; it is not
sufficient.

---

## Verdict

**Three months.** Not one, and it should not need six.

One month is not credible. The three workstreams — pointing claims at tickers, building the
XBRL geographic-revenue adapter, and repairing classification and ingestion — total roughly
four weeks of pure build with no slack, no integration, and no validation. You would arrive at
a pipeline with no track record, which for this product specifically is the same as arriving at
nothing. The Ledger is the thing that makes the product defensible; shipping the engine without
resolved claims reproduces the exact failure `CLAUDE.md` §0a already documents, where the
marketing site published the signal plane's hit rate under a heading about an engine that had
never measured anything.

Three months is realistic, and the evidence is unusually encouraging on the hard parts. The
resolver already works — I ran a ticker-only claim through it unmodified and got a hit, a
miss, and a correctly-floored inconclusive. Geographic revenue is not locked inside 10-K prose;
it is structured XBRL with explicit country dimensions covering 38% of revenue-reporting filers,
about eight days of adapter work. The classifier bugs are a two-day fix. None of the three
questions uncovered an architectural obstacle. What they uncovered was a prompt that offers the
model four unscoreable options out of five, a price feed scoped to a different subsystem and
two days stale, a regex that cannot match a plural, and a rate-limit handler blind to its own
most common failure. Every one of those is small. That is genuinely good news, and it is the
main finding of this investigation.

Six months is what it takes to know whether the engine has an *edge*, which is a different
question from whether it works. The codebase has already measured this and the numbers are in
`ledger.py`: at the observed 18.17% dispersion, detecting a 1% per-call edge needs **1,268
resolved calls**. The impact engine currently has zero.

### The single hardest part

Not the plumbing. It is that **disclosed geographic revenue is too coarse to support the claims
the product wants to make, and no amount of engineering fixes it, because it is a disclosure
limit rather than a data-access limit.**

Apple is the proof. Its geographic revenue, in full, is US $151.8 B, China $64.4 B, and
`OtherCountries` $200.0 B. Forty-eight per cent of the world's most-analysed company's revenue
is in a bucket named "Other". Across the whole quarter, 988 distinct member strings and only
42.3% bare ISO country codes; the rest are `EMEA`, `RestOfWorld`, `NonUs`,
`WesternHemisphereExcludingUS`. Meanwhile the events that matter are specific: an export
control on a chip category, a tariff on one tariff line, a strait closure affecting one trade
lane.

The join is where the product lives, and it is a genuine mismatch of resolution. "US raises
tariffs on Chinese semiconductors" needs company exposure by *product line within country*.
XBRL gives you revenue by country, undifferentiated by product, and often only by continent.
An engine built naively on it will confidently announce that a China tariff hits every filer
with China revenue equally — which is the same category of error as
`COMMODITY_COUNTRIES["oil"]` treating six producers as interchangeable, the bug `CLAUDE.md`
§0a0 records as having killed personalisation once already.

Getting that join right — knowing when the data supports a company-specific claim and when it
only supports a coarse one, and saying so honestly rather than papering over it — is the hard
part. It is a judgement and modelling problem, and it will outlast all three engineering
workstreams. Everything else measured here is a bug with a known fix.
