// The public record page. This is the product, so it gets the most care.
//
// The order of this page is an argument, and it is the same argument `ledger.jsx` makes:
//
//   1. who this is, and whether they have proved they are who they say
//   2. the chain, with a button that recomputes it in front of you
//   3. the counts and the intervals, which are the largest thing here
//   4. the MISSES, above the breakdowns, never in a footnote
//   5. calibration: did the high confidence calls actually do better
//   6. every call, newest first
//
// The hit rate is not the hero. That is deliberate and it is the opposite of what every competitor
// does, because a rate without its interval beside it is the number that misleads.
import { useEffect, useState } from "react";
import { fetchRecord, verifyChain } from "./api";
import { Icon } from "./icons.jsx";
import { EmptyState, LoadError } from "./shell.jsx";
import {
  ChainStrip, Counts, Disclaimer, HouseBanner, Rate, VerdictChip, day, signed,
} from "./receiptsui.jsx";

function Header({ caller }) {
  return (
    <header className="rc-head">
      <div className="rc-head-main">
        <h1 className="rc-name">{caller.display_name}</h1>
        <div className="rc-handle num">@{caller.handle}</div>
      </div>
      <div className="rc-head-meta">
        {caller.verified_at ? (
          <span className="rc-verified">
            <Icon name="shield" size={14} /> verified
            <span className="rc-verified-how">
              {caller.verification_method === "house"
                ? " as ours"
                : ` by ${String(caller.verification_method).replace("_", " ")}`}
            </span>
            {caller.verification_evidence_url && (
              <>
                {" · "}
                <a href={caller.verification_evidence_url} target="_blank" rel="noreferrer noopener">
                  evidence
                </a>
              </>
            )}
          </span>
        ) : (
          <span className="rc-unverified">
            not yet verified. The record is real and sealed either way; what is unproven is that
            this handle is the person who publishes elsewhere.
          </span>
        )}
        {caller.audience_url && (
          <a className="rc-audience" href={caller.audience_url} target="_blank" rel="noreferrer noopener">
            {caller.audience_url.replace(/^https?:\/\//, "")}
          </a>
        )}
        {caller.kind === "algorithm" && <span className="rc-kindtag">algorithm</span>}
      </div>
      {caller.bio && <p className="rc-bio">{caller.bio}</p>}
    </header>
  );
}

function Misses({ misses, onOpenCall }) {
  if (!misses.length) {
    return (
      <EmptyState title="No misses yet">
        Nothing here has resolved against the caller so far. This panel exists to be filled: it is
        the first breakdown on the page, above every other, and it stays that way.
      </EmptyState>
    );
  }
  return (
    <div className="rc-misses">
      {misses.map((m) => (
        <button className="rc-miss-row" key={m.id} onClick={() => onOpenCall(m.id)}>
          <span className="rc-miss-sym num">{m.symbol}</span>
          <span className="rc-miss-dir">said {m.direction}</span>
          <span className="rc-miss-x num">{signed(m.excess_return)}</span>
          <span className="rc-miss-thesis">{m.thesis}</span>
          <span className="rc-miss-when num">{day(m.published_at)}</span>
        </button>
      ))}
    </div>
  );
}

function Calibration({ rows }) {
  const any = rows.some((r) => r.n > 0);
  if (!any) {
    return (
      <EmptyState title="Nothing to calibrate yet">
        Calibration compares what a caller said their confidence was against what actually
        happened. It appears once calls have resolved in each bucket.
      </EmptyState>
    );
  }
  return (
    <table className="rc-cal">
      <thead>
        <tr>
          <th>stated</th><th>resolved</th><th>observed</th><th>hit</th><th>miss</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.stated}>
            <td className="rc-cal-stated">{r.stated}</td>
            <td className="num">{r.n}</td>
            <td className="num">
              {r.observed == null ? (
                <span className="rc-thin">
                  {r.n === 0 ? "no calls yet" : `${r.n} resolved, too few for a rate`}
                </span>
              ) : (
                <>
                  {(r.observed * 100).toFixed(1)}%
                  {r.observed_ci && (
                    <span className="rc-cal-ci">
                      {" "}({(r.observed_ci[0] * 100).toFixed(0)} to {(r.observed_ci[1] * 100).toFixed(0)})
                    </span>
                  )}
                </>
              )}
            </td>
            <td className="num">{r.hit}</td>
            <td className="num">{r.miss}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function AllCalls({ calls, onOpenCall }) {
  if (!calls.length) {
    return (
      <EmptyState title="No calls published yet">
        This record is empty and says so. Nothing has been sealed into the chain, so there is
        nothing to score and nothing to hide. A record starts here for everyone.
      </EmptyState>
    );
  }
  return (
    <div className="rc-calls">
      {calls.map((c) => (
        <button className="rc-call-row" key={c.id} onClick={() => onOpenCall(c.id)}>
          <span className="rc-call-seq num">#{c.seq}</span>
          <span className="rc-call-sym num">{c.symbol}</span>
          <span className="rc-call-dir">{c.direction}</span>
          <span className="rc-call-h num">{c.horizon_days}d</span>
          <VerdictChip verdict={c.verdict || "open"} />
          <span className="rc-call-x num">{c.excess_return == null ? "" : signed(c.excess_return)}</span>
          <span className="rc-call-when num">{day(c.published_at)}</span>
        </button>
      ))}
    </div>
  );
}

export function RecordView({ handle, onOpenCall, onNav }) {
  const [data, setData] = useState(null);
  const [failed, setFailed] = useState(false);

  const load = () => {
    setData(null);
    setFailed(false);
    fetchRecord(handle)
      .then(setData)
      .catch(() => setFailed(true));
  };
  useEffect(load, [handle]);

  if (failed) return <LoadError what="this record" onRetry={load} />;
  if (!data) return <div className="rc-skel"><div className="skel" style={{ width: 320, height: 54 }} /></div>;
  if (data.error) {
    return (
      <EmptyState
        title="No record here"
        action={<button className="act" onClick={() => onNav("board")}>See every record</button>}
      >
        Nobody holds the handle {handle}.
      </EmptyState>
    );
  }

  return (
    <div className="rc-page">
      <Header caller={data.caller} />
      {data.caller.is_house && <HouseBanner house={data.house} />}

      <ChainStrip
        handle={data.caller.handle}
        links={data.chain_links}
        head={data.chain_head}
        onVerify={verifyChain}
      />

      <section className="rc-section">
        <h2 className="rc-h2">The record</h2>
        <Counts counts={data.summary.counts} />
        <Rate summary={data.summary} />
      </section>

      {/* Above the breakdowns. This ordering is the argument, not a layout preference. */}
      <section className="rc-section">
        <h2 className="rc-h2">Recent misses</h2>
        <p className="rc-lede">
          Shown first, and shown in full. Every competitor can copy a feature; none of them can
          retroactively publish a record they did not keep.
        </p>
        <Misses misses={data.misses} onOpenCall={onOpenCall} />
      </section>

      <section className="rc-section">
        <h2 className="rc-h2">Calibration</h2>
        <p className="rc-lede">
          What they said their confidence was, against what happened. A caller who is right more
          often when they said they were sure is worth reading. One whose high confidence calls do
          worse than their low confidence ones is not, however good the headline looks.
        </p>
        <Calibration rows={data.calibration} />
      </section>

      <section className="rc-section">
        <h2 className="rc-h2">Every call</h2>
        <p className="rc-lede">
          All {data.chain_links}, newest first, including the ones that went nowhere. Nothing can be
          removed from this list.
        </p>
        <AllCalls calls={data.calls} onOpenCall={onOpenCall} />
      </section>

      <Disclaimer text={data.disclaimer} />
    </div>
  );
}

/**
 * "My record" with no handle in the URL: resolve the signed-in caller's own and go there.
 *
 * A separate component rather than a branch inside RecordView because it needs a different data
 * source (who am I) and has a different empty state (you do not have a record yet), and folding
 * two of those into one component is how a surface ends up asking the server who you are before it
 * can render somebody else's public page.
 */
export function MyRecord({ user, onLogin, onOpenRecord, onNav }) {
  const [state, setState] = useState(null);

  useEffect(() => {
    if (!user) return;
    import("./api").then(({ fetchMyCaller }) =>
      fetchMyCaller().then(setState).catch(() => setState({ caller: null })));
  }, [user]);

  useEffect(() => {
    if (state?.caller) onOpenRecord(state.caller.handle);
  }, [state]);

  if (!user) {
    return (
      <EmptyState title="Sign in to see your record"
                  action={<button className="act act-on" onClick={onLogin}>Sign in</button>}>
        Reading every record is free and needs no account. Holding one needs a handle.
      </EmptyState>
    );
  }
  if (!state) return <div className="rc-skel"><div className="skel" style={{ width: 260, height: 40 }} /></div>;
  if (!state.caller) {
    return (
      <EmptyState title="You do not have a record yet"
                  action={<button className="act act-on" onClick={() => onNav("publish")}>Claim a handle</button>}>
        A record starts the moment you claim a handle. It begins empty, it says so, and nothing can
        be removed from it afterwards.
      </EmptyState>
    );
  }
  return null;      // the effect above has already navigated to the handle
}
