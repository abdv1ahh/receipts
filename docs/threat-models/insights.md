# Threat model — advanced journal intelligence (Slice L)

Scope: migration 018 (`journal_reports` cache), `tradeos/insights.py`, `explain/gemini.py`
`generate_journal_report`, and the `/api/trades/{id}/similar`, `/api/simulate`, `/api/journal/report`
endpoints. These are the "advanced AI" features — a similar-trade finder, a position scenario
simulator, and an auto journal report. Because they synthesise a user's own trading data and (for the
report) run a model over it, the risks are **crossing the advice line, fabricated numbers/outcomes,
leaking another user's journal, and unbounded model spend**.

## Assets
- **The advice boundary** — every output must stay descriptive/educational; none may tell a user what
  to do or predict what a price or a specific position will do.
- **Numeric integrity** — no simulated figure or model sentence may invent a number, a probability, or
  an outcome that isn't computed from the user's inputs or the real backtest.
- **Journal privacy** — the similar-trade finder and the report operate on the requester's OWN trades
  only; a user must never see another user's journal.
- **Cost** — the report's model path must be bounded (the operator is bootstrapped).

## Attacks and the design that stops them
1. **Similarity/report drifting into advice.** The similar-trade finder is framed and computed as
   DESCRIPTIVE history of the user's own comparable setups ("of your trades like this one, here's how
   they resolved") and carries the small-sample floor: below `PERF_MIN_SAMPLE` closed it reports counts
   and says "too few … not a prediction", never a win rate. The report's model prose is held to the
   **same directive_guard + numbers_guard** as every other model path, with a deterministic fallback
   (`render_report`) that is guard-clean by construction; a guard trip discards the model text. *Verified
   live: the deterministic report passes both guards in tests; the cohort line states no rate below the
   floor.*
2. **The simulator implying a forecast.** `simulate` is pure arithmetic — P&L, R-multiple and
   account-risk at price points the USER names (stop, target, fixed ±5/10% moves). It assigns **no
   probability** to any outcome and makes no claim about what price will do. Where the symbol maps to a
   real convergence signal, the overlay is explicitly a **historical base rate for that signal bucket**,
   drawn from the backtest, labelled "not a forecast for this trade", and shown only when the sample is
   sufficient (otherwise honestly omitted — never fabricated). *Verified live: real base rate attached
   for a signalled symbol (38% at 90d, 138 episodes) with the not-a-forecast framing; null when
   insufficient.*
3. **Fabricated numbers in the report.** The model receives only the computed aggregate payload and is
   forbidden to introduce a number; the numbers_guard then rejects any token that doesn't trace to that
   payload (`allowed_numbers(report, …)`), including the sample floor which is carried in the payload as
   `min_sample`. If `win_rate` is null (small sample) the deterministic path states no rate and the
   guard would strip any model-invented one.
4. **Cross-user journal leakage.** `/api/trades/{id}/similar` resolves the trade and returns
   `found:false` unless the requester is the OWNER — a viewer (even of a public trade) never sees the
   author's private cohort; the search itself is scoped `WHERE user_id = <requester>`. `/api/journal/
   report` reports only the session user's trades. *Verified live: a non-owner and an anonymous request
   both get found:false.*
5. **Unbounded model spend.** The report is cached in `journal_reports` keyed by an inputs-hash over the
   journal's (id, updated_at) pairs + provider, so re-opening it does not re-call the model; it
   regenerates only when a trade is added/edited/removed or the provider changes. A template fallback
   from a model provider is NOT cached (a transient outage can't poison the cache — mirrors
   trade_analyses). The report's model path also honours the **`ai_trade_analysis` kill-switch flag**
   (Slice K): flip it off and the report is deterministic with zero model calls. *Verified live: cached
   on 2nd call, invalidated after a new trade, deterministic when the flag is off.*
6. **Abuse / flooding of the simulator and report.** `/api/simulate` is rate-limited and requires a
   session; it persists nothing. The report is a cached read. Neither accepts free-form text into the
   model — the simulator is pure math, and the report's model input is a fixed computed payload, so
   there is no prompt-injection surface from user prose.

## Residual / deferred (named, not silently assumed)
- **Similarity is heuristic** (asset/direction/strategy-tokens/RR-band/timeframe), not learned; it is
  deliberately simple and outcome-blind (no P&L feeds the score, so it can't just cluster winners). A
  richer embedding is a future enhancement and would keep the same honesty floors.
- **Base-rate overlay recomputes calibration per call** (`compute_calibration`); fine at demo scale,
  a cached/materialised calibration is the scale path (shared with the methodology page).
- **The simulator's fixed ±5/10% moves are illustrative**, not a distribution; by design it shows no
  probabilities, so a user can't mistake it for a Monte-Carlo forecast.
- **Report model latency**: generating with the model is a synchronous request; acceptable given the
  cache, and instantly disable-able via the kill-switch if quota/cost spikes.
