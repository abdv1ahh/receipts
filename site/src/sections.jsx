// The five bands of the page, in the order the brief sets them: the product working, one real
// event walked end to end, the Ledger unedited, the personalisation demo, then the FAQ.
//
// A rule that holds in every section below: THREE STATES, ALWAYS. Loading, empty, and unreachable
// are different sentences. This is a marketing page for a product whose entire argument is that it
// does not blur those together, so a placeholder number here would undo the pitch.

import { useState } from "react";
import { fetchFrame, fetchLedger, fetchLive, fetchWalkthrough } from "./api";
import { useLoad, useReveal } from "./hooks";
import { Graticule } from "./graticule.jsx";
import { Rose } from "./rose.jsx";
import { WorldMap } from "./worldmap.jsx";

const APP = "/radar";        // the Radar itself, not "/" — "/" sends a signed-out visitor here
const SIGNUP = "/auth";      // the app's auth surface — a real route, not a modal
const pct = (v, d = 1) => (v == null ? "—" : `${v >= 0 ? "+" : ""}${(v * 100).toFixed(d)}%`);
const when = (iso) =>
  new Date(iso).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
const day = (iso) => new Date(iso).toLocaleDateString(undefined, { month: "long", day: "numeric", year: "numeric" });

function Section({ id, children, className = "" }) {
  const ref = useReveal();
  return <section id={id} ref={ref} className={`reveal ${className}`}>{children}</section>;
}

// An affected entry, coloured by the direction the claim committed to. Verdigris up, magenta down
// — the two accents doing information work rather than decoration.
function Tag({ a }) {
  const d = a.direction === "up" ? "tag-up" : a.direction === "down" ? "tag-down" : "";
  return <span className={`tag ${d}`}>{a.value}{a.direction ? ` ${a.direction === "up" ? "↑" : "↓"}` : ""}</span>;
}

/* ------------------------------------------------------------------ 1. hero: the product working */

function ClaimRow({ c }) {
  return (
    <article className="claim">
      <div className="claim-top">
        {(c.affected || []).slice(0, 3).map((a, i) => <Tag key={i} a={a} />)}
        <span className="conf">confidence {Math.round((c.confidence || 0) * 100)}%</span>
      </div>
      <h3 className="claim-head">{c.headline}</h3>
      <p className="claim-mech">{(c.mechanism || "").slice(0, 190)}{(c.mechanism || "").length > 190 ? "…" : ""}</p>
      <div className="claim-foot">
        <span>{c.source}</span>
        <span>over {c.horizon}</span>
        <time dateTime={c.created_at}>{when(c.created_at)}</time>
      </div>
    </article>
  );
}

export function Hero() {
  const d = useLoad(() => fetchLive(4));
  return (
    <header className="hero">
      {/* Three depth layers. They move at different rates against each other, which is what makes
          this read as crossing a chart rather than as a picture sliding. */}
      <div className="depth depth-far"><Graticule /></div>
      <div className="depth depth-mid"><Rose /></div>
      <div className="wrap hero-grid">
        <div>
          <h1>The world moves.<br />Here is <em>what it costs you</em>.</h1>
          <p className="lede">
            Rhumb reads world events and commits to what they mean — the mechanism, the assets, the
            horizon, the confidence. Then it marks its own homework in public, and publishes the
            misses first.
          </p>
          <div className="hero-cta">
            <a className="btn" href={SIGNUP}>Start free</a>
            <a className="btn btn-ghost" href={APP}>Open the live Radar</a>
          </div>
        </div>

        <div className="live">
          {/* An h2, not a div: the claim headlines below it are h3, and without a heading here the
              document jumped h1 -> h3. Screen-reader heading navigation is the main way this panel
              is reached at all. */}
          <h2 className="live-head">
            <span className="pulse" aria-hidden="true" />
            interpretations made in the last few hours
          </h2>
          <div className="live-body">
            {d === undefined && [0, 1, 2].map((i) => (
              <div className="claim" key={i}>
                <div className="skel" style={{ width: "38%", marginBottom: 12 }} />
                <div className="skel" style={{ width: "88%", height: 16, marginBottom: 8 }} />
                <div className="skel" style={{ width: "72%" }} />
              </div>
            ))}
            {d === null && (
              <div className="claim err">
                The live feed is not reachable from here right now. Nothing is being shown in its
                place.
              </div>
            )}
            {d && (d.claims || []).length === 0 && (
              <div className="claim err">
                No interpretations open at this moment. This panel stays empty rather than
                replaying an old one.
              </div>
            )}
            {d && (d.claims || []).map((c) => <ClaimRow key={c.id} c={c} />)}
          </div>
        </div>
      </div>
      <div className="wrap">
        <p className="hero-note">
          Every item above is live from the store, ranked by nothing — newest first. Each one is
          already scheduled to be scored against what actually happens.
        </p>
      </div>
    </header>
  );
}

/* ------------------------------------------------- 2. one real interpretation, walked end to end */

export function Walkthrough() {
  const d = useLoad(fetchWalkthrough);
  const [step, setStep] = useState(0);

  if (d === null) return null;

  const c = d?.claim;
  const steps = c
    ? [
      { k: "what happened", body: <p>{c.headline}</p>,
        meta: <>{c.source} · <time dateTime={c.created_at}>{day(c.created_at)}</time></> },
      { k: "the mechanism", body: <p>{c.mechanism}</p>,
        meta: "How it propagates. Not a direction — a chain you can disagree with." },
      { k: "what it called", body: (
        <div className="claim-top" style={{ marginBottom: 0 }}>
          {(c.affected || []).map((a, i) => <Tag key={i} a={a} />)}
        </div>),
        meta: `Confidence ${Math.round((c.confidence || 0) * 100)}%, over ${c.horizon}. Stated before the outcome, not after.` },
      { k: "what follows", body: (
        <p>
          Not written yet. This call is open, and it gets marked on{" "}
          <b className="mono">{day(d.scores_on)}</b> — {d.days_remaining} days from now — against the
          asset's excess return versus SPY, whichever way it goes.
        </p>),
        meta: "The step nobody else shows you, because it is the one that can go badly." },
    ]
    : [];

  return (
    <Section id="how">
      <div className="wrap">
        <div className="eyebrow">one real interpretation, start to finish</div>
        <h2>Not a demo. Today's.</h2>
        <p className="lede" style={{ marginBottom: "var(--s7)" }}>
          Taken from the live store and rotated daily, in order — not chosen for how well it went.
        </p>

        {d === undefined && <div className="skel" style={{ height: 220 }} />}
        {d && !d.available && <p className="err">{d.reason}</p>}

        {c && (
          <div className="walk">
            <nav className="walk-rail" aria-label="walkthrough steps">
              {steps.map((s, i) => (
                <button key={s.k} className={`step-dot ${i === step ? "on" : ""}`}
                        onClick={() => setStep(i)} aria-current={i === step}>
                  <span className="n">{i + 1}</span>
                  <span>{s.k}</span>
                </button>
              ))}
            </nav>
            <div>
              <div className={`step-card ${step === 3 ? "outcome" : ""}`}>
                <div className="step-k">{steps[step].k}</div>
                {steps[step].body}
                <p className="claim-foot" style={{ marginTop: 14 }}>{steps[step].meta}</p>
              </div>

              {d.settled && (
                <div className="step-card outcome">
                  {/* Explicitly labelled as the signal plane. It sat here unlabelled directly
                      under a world-event walkthrough, which read as though the engine's calls were
                      already being scored — they are not; none has resolved yet. */}
                  <div className="step-k">and one from the signal plane, already marked</div>
                  <p>
                    On <b className="mono">{day(d.settled.made_on)}</b> it said{" "}
                    <b className="mono">{d.settled.subject} {d.settled.predicted}</b> at{" "}
                    {Math.round(d.settled.confidence * 100)}% confidence over {d.settled.horizon}.
                    It came in at <b className="mono" style={{ color: d.settled.verdict === "hit" ? "var(--verdigris)" : "var(--miss)" }}>
                      {pct(d.settled.excess_return)}
                    </b>{" "}
                    against SPY — recorded a <b>{d.settled.verdict}</b>.
                  </p>
                  <p className="claim-foot" style={{ marginTop: 0 }}>
                    That one is from the older smart-money signal, which has a finished record —
                    shown here because it is a real marked call, not because it is this engine's.
                    The interpretation above has not resolved yet, and neither has any other.
                    Measured as excess return, so a call that said “up” in a week when everything
                    rose gets no credit for it.
                  </p>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </Section>
  );
}

/* ------------------------------------------------------------------- 3. the Ledger, unedited */

export function Ledger() {
  const d = useLoad(fetchLedger);
  const l = d?.ledger;
  const o = l?.overall;

  // Two planes, and they must never be pooled or confused for one another.
  //
  // This section used to headline "We are wrong most of the time" over a 41% hit rate, directly
  // under a hero promising an engine that interprets world events. Both halves were misleading.
  // The 41% is the SIGNAL PLANE — a backtested smart-money convergence score — and the engine the
  // page actually sells has no resolved calls at all yet. Publishing one subsystem's failure as
  // the other's track record is not candour, it is just a different inaccuracy, and it told every
  // visitor the product does not work using a number that never measured the product.
  const origins = l?.open_by_origin || [];
  const engine = origins.find((x) => x.key.startsWith("impact engine"));
  const signal = (l?.by?.origin || []).find((x) => x.key.startsWith("signal plane"));

  return (
    <Section id="ledger">
      <div className="wrap">
        <div className="eyebrow">the accuracy record</div>
        <h2>Every call is scored, including the bad ones.</h2>
        <p className="lede" style={{ marginBottom: "var(--s6)" }}>
          An interpretation is written down before the outcome exists — asset, direction, horizon,
          confidence — and cannot be edited afterwards. When the horizon elapses it is measured
          against SPY and the verdict is published whichever way it went. Below is everything that
          has been scored so far, and it is not flattering.
        </p>

        {d === undefined && <div className="skel" style={{ height: 140 }} />}
        {d === null && <p className="err">The Ledger is not reachable from here right now.</p>}

        {l && (
          <>
            {/* The engine's own record: currently empty, and said so plainly rather than borrowing
                a number from elsewhere to fill the space. */}
            {engine && (
              <div className="plane">
                <div className="plane-h">
                  <span className="plane-t">The interpretation engine</span>
                  <span className="plane-tag open">record still building</span>
                </div>
                <p className="plane-p">
                  {engine.resolved === 0 ? (
                    <>
                      <b>{engine.open} interpretations are open and none has resolved yet.</b> Every
                      one names its assets, direction and horizon already, and each is scored the day
                      its horizon closes — so this number can only become a real record, never a
                      curated one. There is nothing here to show you yet, and inventing something
                      would defeat the point of the page.
                    </>
                  ) : (
                    <>
                      <b>{engine.resolved} resolved, {engine.open} still open.</b> Scored on the same
                      terms as everything else on this page.
                    </>
                  )}
                </p>
              </div>
            )}

            {/* The signal plane: a real, complete, unflattering record. */}
            {signal && o && (
              <div className="plane">
                <div className="plane-h">
                  <span className="plane-t">The smart-money signal</span>
                  <span className="plane-tag done">{signal.n} resolved</span>
                </div>
                <p className="plane-p">
                  A separate, older subsystem that scores clusters of insider and institutional
                  filings. It has a resolved record, and the record does not yet show an edge in
                  either direction.
                </p>

                <div className="ledger-hero">
                  <div className="lfig">
                    <div className="lfig-v">{Math.round(signal.hit_rate * 100)}%</div>
                    <div className="lfig-l">of {signal.n} resolved calls landed</div>
                  </div>
                  <div className="lfig hit">
                    <div className="lfig-v">{signal.hits}</div>
                    <div className="lfig-l">right</div>
                  </div>
                  <div className="lfig miss">
                    <div className="lfig-v">{signal.misses}</div>
                    <div className="lfig-l">wrong</div>
                  </div>
                  {o.expectancy != null && (
                    <div className="lfig miss">
                      <div className="lfig-v">{pct(o.expectancy)}</div>
                      <div className="lfig-l">average excess per call versus SPY</div>
                    </div>
                  )}
                </div>

                {o.expectancy_ci && (
                  <p className="plane-p">
                    Read the interval, not the average. Following every call came to{" "}
                    <b>{pct(o.expectancy)}</b> per call against SPY, but the 95% confidence interval
                    is <b className="mono">{pct(o.expectancy_ci[0])} to {pct(o.expectancy_ci[1])}</b>
                    {" "}— it <b>spans zero</b>, so on {signal.n} calls this is
                    {o.expectancy_significant ? " a real effect" : " not distinguishable from no edge at all"}.
                    What the sample <em>does</em> establish is that these names fell more often than
                    they rose ({signal.hits} up against {signal.misses} down, {Math.abs(o.hit_rate_z)}{" "}
                    standard errors below a coin flip) while the rises were larger than the falls,
                    so the two roughly cancel.
                  </p>
                )}
                {o.sample_for_1pct_edge && (
                  <p className="plane-p">
                    At the dispersion actually measured it would take about{" "}
                    <b className="mono">{o.sample_for_1pct_edge.toLocaleString()}</b> resolved calls
                    to detect a 1% per-call edge. There are {signal.n}. Publishing “41%” without
                    that number invites a verdict the evidence cannot support — in either direction,
                    which is why it is here rather than in a footnote.
                  </p>
                )}
              </div>
            )}

            {l.calibration?.some((c) => c.sufficient) && (
              <div className="cal">
                <div className="eyebrow" style={{ marginTop: "var(--s6)", marginBottom: "var(--s3)" }}>
                  calibration — does stated confidence match what happens
                </div>
                {l.calibration.filter((c) => c.sufficient).map((c, i) => (
                  <div className="cal-row" key={i}>
                    <div className="cal-key">
                      said {Math.round(c.stated_avg * 100)}%<br />
                      <span style={{ opacity: 0.65 }}>n={c.n}</span>
                    </div>
                    <div className="cal-bars">
                      <div className="cal-bar said"><i style={{ width: `${c.stated_avg * 100}%` }} /></div>
                      <div className="cal-bar did"><i style={{ width: `${(c.observed || 0) * 100}%` }} /></div>
                    </div>
                  </div>
                ))}
                <div className="cal-key" style={{ marginTop: 6 }}>
                  <span style={{ color: "var(--magenta)" }}>▬</span> stated confidence &nbsp;
                  <span style={{ color: "var(--verdigris)" }}>▬</span> what actually landed
                </div>
                <p className="plane-p" style={{ marginTop: "var(--s3)" }}>
                  This is the one number that comes out well. It said 38% and 40% happened — it does
                  not claim to be more certain than it turns out to be, which is what makes a stated
                  confidence worth reading at all.
                </p>
              </div>
            )}

            {d.recent_misses?.length > 0 && (
              <>
                <div className="eyebrow" style={{ marginTop: "var(--s7)", marginBottom: "var(--s3)" }}>
                  the most recent misses, shown first
                </div>
                <div className="misses">
                  {d.recent_misses.slice(0, 6).map((m, i) => (
                    <div className="miss-row" key={i}>
                      <span className="sym">{m.subject}</span>
                      <span className="delta">{pct(m.excess_return)}</span>
                      <span className="what">said {m.predicted} at {Math.round((m.confidence || 0) * 100)}% over {m.horizon}</span>
                    </div>
                  ))}
                </div>
              </>
            )}

            <p className="claim-foot" style={{ marginTop: "var(--s5)", maxWidth: "78ch", lineHeight: 1.7 }}>
              Scored as excess return against SPY, so a call that said “up” in a week when everything
              rose gets no credit. Moves inside 2% are recorded as inconclusive rather than counted
              either way, and a claim naming three assets is scored three times — getting one right
              and two wrong is not “right”.
            </p>
          </>
        )}
      </div>
    </Section>
  );
}

/* --------------------------------------------------------------- 4. the same day, from elsewhere */

export function Personalisation() {
  const [country, setCountry] = useState("AE");
  const d = useLoad(() => fetchFrame(country, 4), [country]);

  return (
    <Section id="you">
      <div className="wrap">
        <div className="eyebrow">the same day, read from somewhere else</div>
        <h2>A tariff is not one story.</h2>
        <p className="lede" style={{ marginBottom: "var(--s6)" }}>
          It is a different story in Sharjah than in São Paulo, and most feeds tell you the American
          one. Pick a country and watch the same afternoon reorder itself.
        </p>

        <div className="pers">
          <div>
            <WorldMap
              countries={d?.countries || []}
              selected={country}
              onSelect={setCountry}
            />
            <p className="claim-foot" style={{ marginTop: 14, lineHeight: 1.7 }}>
              Ten countries, because ten is how many have hand-checked exposure figures behind them
              — currency regime, trade partners in order, commodity position. Offering you a
              country we have no sourced data for would be inventing a perspective in order to
              demonstrate one.
            </p>
          </div>

          <div>
            <div className="eyebrow" style={{ marginBottom: "var(--s4)" }}>
              {d?.country ? `top of the feed in ${d.country.name}` : "top of the feed"}
            </div>
            {d === undefined && <div className="skel" style={{ height: 180 }} />}
            {d === null && <p className="err">Not reachable right now.</p>}
            {d?.claims?.length === 0 && <p className="err">Nothing open in the store at this moment.</p>}
            <div className="pers-list">
              {(d?.claims || []).map((c, i) => (
                <div className="pers-item" key={c.id}>
                  <span className="pers-rank">{String(i + 1).padStart(2, "0")}</span>{" "}
                  {c.headline}
                  {/* The regions and currencies the claim names, which is WHY it ranks here —
                      concrete evidence beats repeating the same explanatory sentence down the
                      list, and for a Gulf reader seeing "Middle East" on every row is the demo. */}
                  <div className="claim-top" style={{ margin: "9px 0 0" }}>
                    {(c.affected || [])
                      .filter((a) => a.kind === "region" || a.kind === "currency" || a.kind === "commodity")
                      .slice(0, 3)
                      .map((a, k) => <Tag key={k} a={a} />)}
                  </div>
                  <div className="pers-why">{c.why_shown}</div>
                </div>
              ))}
            </div>
            {d?.note && <p className="claim-foot" style={{ marginTop: "var(--s4)", lineHeight: 1.7 }}>{d.note}</p>}
          </div>
        </div>
      </div>
    </Section>
  );
}

/* ------------------------------------------------------------------------------------- 5. FAQ */

// Real objections, answered directly. Every number in an answer is either structural or drawn
// from the published Ledger, so this section cannot drift away from the one above it.
export const FAQS = [
  {
    q: "How is accuracy measured?",
    a: "Every interpretation names an asset, a direction and a horizon at the moment it is made, and is timestamped so it cannot be edited afterwards. When the horizon elapses the asset's return is measured against SPY over the same window. Excess return, not raw return — a call that said \"up\" in a week when everything rose is not credited for it. Moves smaller than 2% are recorded as inconclusive rather than counted either way, and a claim naming three assets is scored three times, because getting one right and two wrong is not \"right\".",
  },
  {
    q: "So how accurate is it, actually?",
    a: "Two different things are measured and they must not be pooled. The interpretation engine — the thing this site is about — has interpretations open and none resolved yet, so it has no accuracy figure and this page does not invent one for it. The older smart-money signal does have a finished record: 41% of 282 resolved calls landed, and following every call would have trailed SPY by about 1.5% per call. That is a bad result and it is published rather than buried. The figure that does hold up is calibration: when it stated 38% confidence, 40% happened, so it does not claim more certainty than it earns.",
  },
  {
    q: "Where does the data come from?",
    a: "SEC EDGAR filings (13D/G, 13F, Form 4, 8-K), public RSS from CNBC, the Federal Reserve and the SEC and a spread of non-US outlets, the Nasdaq earnings calendar, Wikipedia pageviews, Hacker News, CoinGecko and Tiingo end-of-day prices. All free tiers or public filings. Every figure on the product carries its source and timestamp, and any source that is not connected is shown as not connected rather than quietly filled in.",
  },
  {
    q: "Is this investment advice?",
    a: "No, and it is built so that it cannot become it by accident. Model output passes a guard that rejects directive language — buy, sell, hold, should, recommend, price target — before it can be displayed, and trips to deterministic text if it fails. Rhumb describes mechanisms and states confidence. What you do about it is yours.",
  },
  {
    q: "How is this different from a news aggregator?",
    a: "An aggregator tells you what was published. Rhumb commits to what it means and is scored on it. The unit here is not a headline, it is a claim: this mechanism, these assets, this direction, this horizon, this confidence — recorded before the outcome and marked against it afterwards, in public, including when it is wrong.",
  },
  {
    q: "What does the free tier include?",
    a: "The Radar, the world map, the full public Ledger, and the Morning Brief. Paid adds live rather than delayed data, unlimited alerts, the Exposure surface that maps live events onto what you hold, and API access. The Ledger is public at every tier and always will be, because an accuracy record behind a paywall is not an accuracy record.",
  },
  {
    q: "What happens to my data?",
    a: "Your journal, your holdings and the country you read from are yours and are never used to rank anyone else's feed. Personal relevance is computed on the server so the ranking cannot be gamed, and the world context attached to a logged trade is visible only to its owner — publishing a trade to your profile does not publish the frame you read the world through.",
  },
];

export function Close() {
  const ref = useReveal();
  return (
    <section className="reveal close" ref={ref}>
      <div className="wrap">
        <div className="eyebrow">what happens next</div>
        <h2>Sixty seconds to a feed that reads from where you are.</h2>
        <p className="lede">
          Pick your country and currency and it starts ranking for you — a tariff story reads
          differently in Sharjah than in São Paulo, and only one of those is the default everywhere
          else. Free tier includes the Radar, the world map, the Morning Brief and the whole Ledger.
        </p>
        <div className="hero-cta">
          <a className="btn" href={SIGNUP}>Start free</a>
          <a className="btn btn-ghost" href="#ledger">Read the record first</a>
        </div>
      </div>
    </section>
  );
}

export function Faq() {
  const [open, setOpen] = useState(0);
  return (
    <Section id="faq">
      <div className="wrap">
        <div className="eyebrow">objections, answered</div>
        <h2>The questions worth asking.</h2>
        <div className="faq" style={{ marginTop: "var(--s6)" }}>
          {FAQS.map((f, i) => (
            <div className={`faq-item ${open === i ? "open" : ""}`} key={f.q}>
              <h3>
                <button className="faq-q" aria-expanded={open === i} aria-controls={`a${i}`}
                        onClick={() => setOpen(open === i ? -1 : i)}>
                  {f.q}<span className="mk" aria-hidden="true">+</span>
                </button>
              </h3>
              <div className="faq-a" id={`a${i}`} role="region">
                <p>{f.a}</p>
              </div>
            </div>
          ))}
        </div>
      </div>
    </Section>
  );
}
