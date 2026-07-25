// The Ledger — the system scoring itself, misses first.
//
// This is the most important screen in the product and the only one whose value comes from
// showing bad news. Every competitor can copy a feature; none of them can retroactively publish
// a track record they did not keep. So the design rules here are unusual on purpose:
//
//   * recent misses appear ABOVE the breakdowns, not in a footnote;
//   * a slice with too few resolved claims shows its count, never a percentage — 2 of 3 must
//     never render as "67% accurate";
//   * calibration is shown as stated-versus-observed, because "we said 70% and it landed at 68%"
//     is the honest question and a hit rate alone cannot answer it.
import { useEffect, useState } from "react";
import { fetchLedger } from "./api";
import { Icon } from "./icons.jsx";
import { EmptyState, LoadError } from "./shell.jsx";

const pct = (v) => (v == null ? "—" : `${Math.round(v * 100)}%`);
const signed = (v) => (v == null ? "—" : `${v >= 0 ? "+" : ""}${(v * 100).toFixed(1)}%`);

function Headline({ o }) {
  return (
    <div className="lg-head">
      <div className="lg-head-l">
        <div className="pulse-kicker"><Icon name="target" size={13} /> Track record</div>
        {o.sufficient ? (
          <>
            <div className="lg-rate">{pct(o.hit_rate)}</div>
            <div className="lg-rate-sub">of {o.n} resolved calls were right</div>
          </>
        ) : (
          <>
            <div className="lg-rate thin">{o.n}</div>
            <div className="lg-rate-sub">
              resolved calls so far — not enough to state a rate
            </div>
          </>
        )}
      </div>
      <div className="lg-counts">
        <div className="lg-count ok"><b>{o.hit}</b><span>right</span></div>
        <div className="lg-count bad"><b>{o.miss}</b><span>wrong</span></div>
        <div className="lg-count"><b>{o.inconclusive}</b><span>too small to call</span></div>
        <div className="lg-count"><b>{o.unscoreable}</b><span>no price series</span></div>
      </div>
    </div>
  );
}

function Misses({ misses }) {
  if (!misses?.length) return null;
  return (
    <div className="sec lg-misses">
      <div className="sec-head">
        <div className="sec-title"><span className="ico"><Icon name="alert" size={15} /></span> Recent misses</div>
        <span className="lg-misses-why">shown first, on purpose</span>
      </div>
      {misses.map((m) => (
        <div key={`${m.claim_id}-${m.subject}`} className="lg-miss">
          <div className="lg-miss-top">
            <span className="lg-miss-sym">{m.subject}</span>
            <span className="lg-miss-said">said <b>{m.predicted}</b></span>
            <span className="lg-miss-got">got <b className="pos-neg">{signed(m.excess_return)}</b> vs SPY</span>
            <span className="lg-miss-conf">stated {pct(m.confidence)} confident</span>
            <span className="spacer" />
            <span className="name">{m.horizon}</span>
          </div>
          {m.headline && (
            m.url
              ? <a className="lg-miss-head" href={m.url} target="_blank" rel="noreferrer noopener">{m.headline} ↗</a>
              : <div className="lg-miss-head">{m.headline}</div>
          )}
          {m.mechanism && <p className="lg-miss-mech">{m.mechanism}</p>}
        </div>
      ))}
    </div>
  );
}

function Breakdown({ title, rows }) {
  if (!rows?.length) return null;
  return (
    <div className="sec">
      <div className="sec-head"><div className="sec-title">By {title}</div></div>
      <table className="clusters">
        <thead><tr><th>{title}</th><th className="num">right</th><th className="num">wrong</th><th className="num">rate</th></tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.key}>
              <td>{r.key}</td>
              <td className="num">{r.hits}</td>
              <td className="num">{r.misses}</td>
              <td className="num">
                {r.sufficient
                  ? pct(r.hit_rate)
                  : <span className="lg-thin" title="too few resolved calls to state a rate">n={r.n}</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Calibration({ rows }) {
  if (!rows?.length) return null;
  return (
    <div className="sec">
      <div className="sec-head">
        <div className="sec-title">Calibration</div>
        <span className="lg-misses-why">when it says 70%, does it land near 70%?</span>
      </div>
      <table className="clusters">
        <thead><tr><th>Said</th><th className="num">Actually right</th><th className="num">n</th><th>Gap</th></tr></thead>
        <tbody>
          {rows.map((r, i) => {
            const gap = r.observed != null ? r.observed - r.stated_avg : null;
            return (
              <tr key={i}>
                <td>{pct(r.stated_avg)}</td>
                <td className="num">{r.sufficient ? pct(r.observed) : <span className="lg-thin">n={r.n}</span>}</td>
                <td className="num">{r.n}</td>
                <td className={gap == null ? "" : Math.abs(gap) < 0.1 ? "pos-pos" : "pos-neg"}>
                  {gap == null ? "—" : `${gap >= 0 ? "+" : ""}${Math.round(gap * 100)}pts`}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export function LedgerView() {
  const [d, setD] = useState(undefined);
  const load = () => { setD(undefined); fetchLedger().then(setD).catch(() => setD(null)); };
  useEffect(load, []);

  if (d === null) return <LoadError what="the track record" onRetry={load} />;
  if (d === undefined) return <div className="skel" style={{ width: "50%", height: 90, marginTop: 14 }} />;

  const l = d.ledger;
  const o = l.overall;

  return (
    <div>
      <div className="page-head">
        <div>
          <h1 className="page-title">The Ledger</h1>
          <p className="page-sub">
            Every interpretation this system makes is timestamped when it is made, then scored
            against what actually happened. Including the ones it got wrong.
          </p>
        </div>
      </div>

      <Headline o={o} />

      {o.n === 0 && (
        <EmptyState title="Nothing has resolved yet">
          {l.open_claims > 0
            ? <>There {l.open_claims === 1 ? "is" : "are"} <b>{l.open_claims}</b> live interpretation
               {l.open_claims === 1 ? "" : "s"} waiting for their horizon to elapse. Each one will
               be scored automatically and appear here — right or wrong.</>
            : <>No interpretations have been made yet. They appear here as soon as their horizon
               closes.</>}
        </EmptyState>
      )}

      <Misses misses={d.recent_misses} />

      {o.n > 0 && (
        <>
          {/* Origin leads: pooling a backtested signal's hit rate with the model's would make
              both numbers meaningless, so they are always shown apart. */}
          <Breakdown title="origin" rows={l.by?.origin} />
          <Calibration rows={l.calibration} />
          <div className="dash-grid">
            <Breakdown title="category" rows={l.by?.category} />
            <Breakdown title="horizon" rows={l.by?.horizon} />
          </div>
          <Breakdown title="source" rows={l.by?.source} />
        </>
      )}

      <div className="disc" style={{ marginTop: 16 }}>{l.note}</div>
    </div>
  );
}
