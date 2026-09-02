// Primitives shared by every Receipts surface.
//
// They live here rather than being repeated per surface because of a lesson this codebase already
// paid for: `pct` existed as near-identical copies in three files and the fourth copy dropped the
// x100, publishing a +10% trade to other people as "+0.1%". A record whose counts render one way
// on the board and another way on the record page is the same failure with higher stakes.
//
// THE RULE THAT MATTERS MOST: `Rate` renders a percentage only when the server sent one. The
// server withholds it below the sample gate, so no surface can print a rate the sample cannot
// support unless someone deliberately routes around this component.
import { useState } from "react";
import { Icon } from "./icons.jsx";
import { money, pct } from "./format.js";

// The shared formatter, configured, never reimplemented. This file was about to hold the fifth
// `pct` in the codebase, and the fourth one is the copy that dropped the x100 and published a +10%
// trade to other people as "+0.1%". The differences here are real and they are ARGUMENTS: a rate
// is unsigned, a proof panel wants two decimals, and an absent value says what it IS rather than
// showing a dash, because "not scored" and "not held" are different facts and a reader checking a
// track record is entitled to know which one they are looking at.
export const pct1 = (v) => pct(v, { dp: 1, sign: false, empty: "not scored" });
export const signed = (v) => pct(v, { dp: 2, empty: "not scored" });
export const price = (v) => money(v, { dp: 2, empty: null });
export const shortHash = (h) => (h ? `${h.slice(0, 10)}…${h.slice(-6)}` : "not held");
export const day = (iso) => (iso ? String(iso).slice(0, 10) : "not held");

// Verdict vocabulary, in the reader's words. A miss is a normal outcome of making calls in public
// and its treatment says so: muted, not an alarm.
export const VERDICT = {
  hit: { label: "hit", cls: "rc-hit" },
  miss: { label: "miss", cls: "rc-miss" },
  inconclusive: { label: "inconclusive", cls: "rc-incon" },
  unscoreable: { label: "unscoreable", cls: "rc-unsc" },
  open: { label: "open", cls: "rc-open" },
};

export function VerdictChip({ verdict }) {
  const v = VERDICT[verdict] || VERDICT.open;
  return <span className={`rc-chip ${v.cls}`}>{v.label}</span>;
}

/** The five counts, always all five, always visible. An absent category is a zero, not a gap: a
 *  record that shows four counts invites the question of what the fifth one was. */
export function Counts({ counts, size = "lg" }) {
  const rows = [
    ["hit", counts.hit, "rc-hit"],
    ["miss", counts.miss, "rc-miss"],
    ["inconclusive", counts.inconclusive, ""],
    ["unscoreable", counts.unscoreable, ""],
    ["open", counts.open, ""],
  ];
  return (
    <div className={`rc-counts ${size}`}>
      {rows.map(([label, n, cls]) => (
        <div className="rc-count" key={label}>
          <b className={cls}>{n ?? 0}</b>
          <span>{label}</span>
        </div>
      ))}
    </div>
  );
}

/**
 * The record's statistics.
 *
 * Hierarchy note, and it is deliberate: the counts and the intervals are the largest thing on the
 * page and the hit rate is not the hero. That is the opposite of what every competitor does, and
 * it is the honest arrangement, because a rate without its interval is the number that misleads.
 */
export function Rate({ summary }) {
  if (summary.gated) {
    return (
      <div className="rc-rate gated">
        <div className="rc-lown">
          <span className="rc-lown-chip">Low N</span>
          <b className="num">{summary.resolved_scoreable}</b>
          <span>resolved as a hit or a miss so far</span>
        </div>
        <p className="rc-gatewhy">{summary.gate_reason}</p>
      </div>
    );
  }
  const ci = summary.hit_rate_ci;
  const eci = summary.expectancy_ci;
  return (
    <div className="rc-rate">
      <div className="rc-rate-grid">
        <div className="rc-stat">
          <span className="rc-stat-l">right on {summary.resolved_scoreable} resolved calls</span>
          <b className="rc-stat-v num">{pct1(summary.hit_rate)}</b>
          {ci && (
            <span className="rc-stat-ci num">
              95% interval {pct1(ci[0])} to {pct1(ci[1])}
            </span>
          )}
        </div>
        <div className="rc-stat">
          <span className="rc-stat-l">average excess per call against SPY</span>
          <b className="rc-stat-v num">{signed(summary.expectancy)}</b>
          {eci && (
            <span className="rc-stat-ci num">
              95% interval {signed(eci[0])} to {signed(eci[1])}
            </span>
          )}
        </div>
      </div>

      {/* The two statistics genuinely disagree in this data and both are published. Frequency can
          be significantly below chance while the returns cancel out, and saying only one of those
          would be true and misleading at the same time. */}
      <div className="rc-signif">
        {eci && (
          eci[0] < 0 && eci[1] > 0 ? (
            <b>The interval on the average spans zero, so on this sample no edge is shown in
              either direction.</b>
          ) : (
            <b>
              The interval on the average does not span zero, so this sample does show an effect
              of {signed(summary.expectancy)} per call.
            </b>
          )
        )}
        {summary.z_vs_coinflip != null && (
          <span>
            {" "}How often, separately: {Math.abs(summary.z_vs_coinflip).toFixed(2)} standard errors{" "}
            {summary.z_vs_coinflip < 0 ? "below" : "above"} a coin flip.
          </span>
        )}
        {summary.sample_needed_1pct != null && (
          <span>
            {" "}At the dispersion measured here it would take{" "}
            <b className="num">{summary.sample_needed_1pct.toLocaleString()}</b> resolved calls to
            detect a 1% per call edge, against the{" "}
            <b className="num">{summary.resolved_scoreable}</b> held.
          </span>
        )}
      </div>
    </div>
  );
}

/** The one strongest accent in the palette is spent here and nowhere else: this is the moment
 *  something is proved rather than asserted. */
export function ChainStrip({ handle, links, head, onVerify }) {
  const [state, setState] = useState(null);      // null | "running" | result
  const [step, setStep] = useState(0);

  const run = async () => {
    setState("running");
    setStep(0);
    const result = await onVerify(handle);
    // Walk the links visibly rather than flashing an answer. Verification is the moment the demo
    // turns on, and an instant green tick reads like a decoration rather than like work.
    const total = Math.max(1, result.links);
    const ticks = Math.min(28, total);
    for (let i = 1; i <= ticks; i += 1) {
      await new Promise((r) => setTimeout(r, 26));
      setStep(Math.round((i / ticks) * total));
    }
    setState(result);
  };

  const running = state === "running";
  const done = state && state !== "running";

  return (
    <div className={`rc-chain ${done ? (state.intact ? "ok" : "broken") : ""}`}>
      <div className="rc-chain-l">
        <div className="rc-chain-n num">{links}</div>
        <div className="rc-chain-lab">
          sealed calls, each carrying the hash of the one before it
          <div className="rc-chain-head num" title={head}>head {shortHash(head)}</div>
        </div>
      </div>
      <div className="rc-chain-r">
        {!state && (
          <button className="rc-verify" onClick={run}>
            <Icon name="shield" size={15} /> Verify chain
          </button>
        )}
        {running && (
          <div className="rc-chain-run num">
            checking link {step} of {links}
            <div className="rc-chain-bar"><i style={{ width: `${(step / Math.max(1, links)) * 100}%` }} /></div>
          </div>
        )}
        {done && state.intact && (
          <div className="rc-chain-res ok">
            <Icon name="shield" size={15} />
            <div>
              <b>Intact. All {state.links} links recompute.</b>
              <span>{state.reason}</span>
            </div>
          </div>
        )}
        {done && !state.intact && (
          <div className="rc-chain-res broken">
            <Icon name="alert" size={15} />
            <div>
              <b>Broken at call {state.broken_at_seq}.</b>
              <span>{state.reason}</span>
            </div>
          </div>
        )}
      </div>
      {done && (
        <p className="rc-chain-caveat">{state.caveat}</p>
      )}
    </div>
  );
}

/** The persistent footer. One string from the server, on every public surface, so there is no
 *  second copy to drift. */
export function Disclaimer({ text }) {
  if (!text) return null;
  return <p className="rc-disclaimer">{text}</p>;
}

/** The label a record carries when it is ours. Stated plainly, because a house record that reads
 *  like anyone else's is the one dishonest thing this product could do. */
export function HouseBanner({ house }) {
  if (!house) return null;
  const spans = house.expectancy_ci && house.expectancy_ci[0] < 0 && house.expectancy_ci[1] > 0;
  return (
    <div className="rc-house">
      <div className="rc-house-tag">This is our own signal engine</div>
      <p>
        Across both registered versions of it, {house.resolved_scoreable} calls resolved as a hit or
        a miss and it was right <b className="num">{pct1(house.hit_rate)}</b> of the time, which is
        below a coin flip.{" "}
        {spans && <>Its expectancy interval spans zero, so no edge is shown in either direction.{" "}</>}
        At this dispersion it would take{" "}
        <b className="num">{house.sample_needed_1pct?.toLocaleString()}</b> resolved calls to detect
        a 1% per call edge. We publish it because a scoreboard that only shows winners is not a
        scoreboard.
      </p>
    </div>
  );
}
