// One call, with its proof.
//
// The test this page has to pass: a sceptic with a calculator can check the arithmetic. Not "trust
// the verdict", not "here is a chart" — the two sessions, the excess against SPY, the noise floor,
// and the rule that turned that into a word. If any of those is missing the verdict is an
// assertion, and an assertion is what every other track record already offers.
//
// IT USED TO SHOW THE FOUR COMPONENT PRICES AND THE TWO COMPONENT RETURNS, and that was the
// stronger panel right up until the licence was read: the prices come from a market-data vendor
// whose terms permit no redistribution and carry no exception for display, and this page is
// public. So the panel now hands over the two SESSION DATES instead, and they turn out to be the
// better answer anyway — a reader who prices those two sessions from a feed of their own choosing
// reproduces the number without having to trust our copy of it, which is more than the old panel
// offered. Both explanatory strings come from `receipts/record.py` through the API; see
// `record.NO_PRICES` and `record.RECOMPUTE_NOTE`.
import { useEffect, useState } from "react";
import { fetchCall } from "./api";
import { Icon } from "./icons.jsx";
import { EmptyState, LoadError } from "./shell.jsx";
import { Disclaimer, VerdictChip, day, shortHash, signed } from "./receiptsui.jsx";

function Field({ label, value, missing, mono = true, wide = false }) {
  return (
    <div className={`cd-field ${wide ? "wide" : ""}`}>
      <span className="cd-label">{label}</span>
      {value == null ? (
        <span className="cd-missing">{missing || "not held"}</span>
      ) : (
        <b className={mono ? "num" : ""}>{value}</b>
      )}
    </div>
  );
}

function Context({ snapshot }) {
  if (!snapshot) return null;
  if (snapshot.basis === "unavailable") {
    return (
      <p className="cd-ctx-none">
        No world context was frozen for this call. {snapshot.unavailable_reason}
      </p>
    );
  }
  const onSymbol = snapshot.snapshot?.on_symbol || [];
  return (
    <div className="cd-ctx">
      <div className="cd-ctx-row">
        <b className="num">{snapshot.n_live}</b> interpretations were live on the Radar at the
        moment this was published, of which <b className="num">{snapshot.n_on_symbol}</b> named this
        instrument.
      </div>
      <div className={`cd-align ${snapshot.alignment}`}>
        {snapshot.alignment === "none"
          ? "Nothing live pointed either way on this name. Most calls are made in silence, and that is not a failing."
          : snapshot.alignment === "with"
            ? "Every live read on this name pointed the same way as the call."
            : snapshot.alignment === "against"
              ? "Every live read on this name pointed the other way."
              : "The live reads on this name disagreed with each other."}
      </div>
      {onSymbol.length > 0 && (
        <ul className="cd-ctx-list">
          {onSymbol.map((c, i) => (
            <li key={c.claim_id || i}>
              <span className="num">{c.direction}</span> {c.headline || c.mechanism}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function CallDetailView({ callId, onBack, onOpenRecord }) {
  const [data, setData] = useState(null);
  const [failed, setFailed] = useState(false);

  const load = () => {
    setData(null);
    setFailed(false);
    fetchCall(callId).then(setData).catch(() => setFailed(true));
  };
  useEffect(load, [callId]);

  if (failed) return <LoadError what="this call" onRetry={load} />;
  if (!data) return <div className="rc-skel"><div className="skel" style={{ width: 280, height: 40 }} /></div>;
  if (data.error) {
    return (
      <EmptyState title="No such call"
                  action={<button className="act" onClick={onBack}>Go back</button>}>
        This call does not exist. Nothing has been removed: a call cannot be deleted once it is
        published, so a link that does not resolve was never a link to a real one.
      </EmptyState>
    );
  }

  const c = data.call;

  return (
    <div className="cd-page">
      <button className="rc-back" onClick={onBack}><Icon name="arrow" size={14} /> back</button>

      <header className="cd-head">
        <div className="cd-head-l">
          <div className="cd-sym num">{c.symbol}</div>
          <div className="cd-said">
            said <b>{c.direction}</b> over {c.horizon_days} days, {c.confidence} confidence
          </div>
        </div>
        <div className="cd-head-r">
          <VerdictChip verdict={c.verdict || "open"} />
          {c.excess_return != null && <div className="cd-x num">{signed(c.excess_return)}</div>}
        </div>
      </header>

      <button className="cd-by" onClick={() => onOpenRecord(data.caller.handle)}>
        by {data.caller.display_name} <span className="num">@{data.caller.handle}</span>
        {data.caller.is_house && <span className="bd-tag ours">ours</span>}
      </button>

      <p className="cd-thesis">{c.thesis}</p>

      <section className="cd-proof">
        <h2 className="rc-h2">The proof</h2>
        {/* "Everything the verdict was computed from" was true when the four component prices
            were in this grid. It is not true now and the lede must not outlive the panel. */}
        <p className="rc-lede">
          What the verdict was computed over, and the rule it was computed by. Entry is the close of
          the first session strictly after publication, never the session in progress.
        </p>

        <div className="cd-grid">
          <Field label="published at" value={c.published_at} />
          <Field label="knowable time" value={c.knowable_time} />
          <Field label="sequence in the chain" value={`#${c.seq}`} />
          <Field label="benchmark" value={c.benchmark_symbol} />
          <Field label="chains from" value={shortHash(c.prev_hash)} />
          <Field label="content hash" value={c.content_hash} wide />
        </div>

        {/* The four component prices and the two component returns used to sit in this grid.
            They were the vendor's data on a public page; see `record.NO_PRICES`. What a sceptic
            needs is not our copy of the closes but the two SESSIONS, which are exact, are ours to
            publish, and let them price the same window from any feed they like. */}
        <div className="cd-grid">
          <Field label="entry session" value={c.entry_session ? day(c.entry_session) : null}
                 missing="not scored yet" />
          <Field label="exit session" value={c.exit_session ? day(c.exit_session) : null}
                 missing="not scored yet" />
          <Field label="excess against the benchmark"
                 value={c.excess_return == null ? null : signed(c.excess_return)}
                 missing="not scored yet" />
          <Field label="noise floor applied"
                 value={`plus or minus ${(data.noise_floor * 100).toFixed(0)}%`} />
        </div>

        {/* Both strings come from the server, which reads them from `record.py`. Typing them here
            would be the copy that drifts, on the panel whose entire job is to be checkable. */}
        <p className="cd-recompute">
          <b>Why there are no prices here.</b> {data.no_prices} {data.recompute}
        </p>

        {c.verdict_note && (
          <div className="cd-note">
            <b>{c.verdict || "open"}</b> {c.verdict_note}
          </div>
        )}
      </section>

      <section className="cd-context">
        <h2 className="rc-h2">What the system was showing at the time</h2>
        <p className="rc-lede">
          Frozen at publication, so it cannot be reconstructed favourably afterwards.
        </p>
        <Context snapshot={data.context_snapshot} />
      </section>

      <Disclaimer text={data.disclaimer} />
    </div>
  );
}
