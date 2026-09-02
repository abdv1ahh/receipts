// The public board: every caller, with what their record actually says.
//
// Two rules hold this page honest and both are visible rather than implied.
//
// A GATED CALLER IS NEVER RANKED. Below the sample gate there is no rank number and no percentage,
// only counts and a Low N chip that reads as a neutral fact rather than as a warning. Placing a
// thin record among the ranks by accident of sort order would itself be a claim about it.
//
// THE RANK MEASURES THE PAST AND ONLY THE PAST. It is not a forecast, not a recommendation, and
// not a suggestion to follow anybody. That sentence sits at the top of the page rather than in a
// footer, because a reader who is going to misread a scoreboard does it in the first five seconds.
import { useEffect, useState } from "react";
import { fetchBoard } from "./api";
import { Icon } from "./icons.jsx";
import { EmptyState, LoadError } from "./shell.jsx";
import { Counts, Disclaimer, pct1, signed } from "./receiptsui.jsx";

function Row({ entry, onOpen }) {
  const s = entry.summary;
  return (
    <button className={`bd-row ${entry.is_house ? "house" : ""}`} onClick={() => onOpen(entry.handle)}>
      <div className="bd-rank num">{entry.rank ?? ""}</div>
      <div className="bd-who">
        <div className="bd-name">
          {entry.display_name}
          {entry.verified && <Icon name="shield" size={13} />}
          {entry.kind === "algorithm" && <span className="bd-tag">algorithm</span>}
          {entry.is_house && <span className="bd-tag ours">ours</span>}
        </div>
        <div className="bd-handle num">@{entry.handle}</div>
      </div>

      <div className="bd-counts">
        <Counts counts={s.counts} size="sm" />
      </div>

      <div className="bd-rate">
        {s.gated ? (
          <>
            <span className="rc-lown-chip">Low N</span>
            <span className="bd-rate-sub num">{s.resolved_scoreable} resolved</span>
          </>
        ) : (
          <>
            <b className="num">{pct1(s.hit_rate)}</b>
            <span className="bd-rate-sub num">
              {s.hit_rate_ci && `${pct1(s.hit_rate_ci[0])} to ${pct1(s.hit_rate_ci[1])}`}
            </span>
          </>
        )}
      </div>

      {/* Hit rate and expectancy genuinely disagree in this data, so both are on the row. Showing
          only the frequency would be true and misleading at the same time. */}
      <div className="bd-exp">
        {s.gated ? (
          <span className="rc-thin">not shown yet</span>
        ) : (
          <>
            <b className="num">{signed(s.expectancy)}</b>
            <span className="bd-rate-sub">
              {s.expectancy_significant ? "per call" : "per call, interval spans zero"}
            </span>
          </>
        )}
      </div>
    </button>
  );
}

export function BoardView({ onOpenRecord, onNav }) {
  const [data, setData] = useState(null);
  const [failed, setFailed] = useState(false);

  const load = () => {
    setData(null);
    setFailed(false);
    fetchBoard().then(setData).catch(() => setFailed(true));
  };
  useEffect(load, []);

  if (failed) return <LoadError what="the board" onRetry={load} />;
  if (!data) return <div className="rc-skel"><div className="skel" style={{ width: 380, height: 44 }} /></div>;

  const ranked = data.board.filter((e) => e.rank != null);
  const gated = data.board.filter((e) => e.rank == null);

  return (
    <div className="bd-page">
      <header className="bd-head">
        <h1 className="rc-name">The board</h1>
        <p className="bd-note">{data.ranking_note}</p>
      </header>

      {data.board.length === 0 ? (
        <EmptyState title="Nobody has published yet">
          Records appear here as soon as a caller seals their first call. Nothing is listed until
          somebody has actually said something in advance.
        </EmptyState>
      ) : (
        <>
          <div className="bd-table">
            <div className="bd-header">
              <span>rank</span><span>caller</span><span>outcomes</span><span>hit rate</span>
              <span>average excess</span>
            </div>
            {ranked.map((e) => <Row key={e.handle} entry={e} onOpen={onOpenRecord} />)}
          </div>

          {gated.length > 0 && (
            <div className="bd-gated">
              <h2 className="rc-h2">Below the sample gate</h2>
              <p className="rc-lede">
                These records are real and every call in them is sealed. What is not shown is a
                percentage, because fewer than {data.sample_gate} of their calls have resolved as a
                hit or a miss and a rate on that sample would suggest a precision it cannot support.
                They carry no rank for the same reason.
              </p>
              <div className="bd-table">
                {gated.map((e) => <Row key={e.handle} entry={e} onOpen={onOpenRecord} />)}
              </div>
            </div>
          )}
        </>
      )}

      <div className="bd-foot">
        <button className="act" onClick={() => onNav("methodology")}>
          How a call is scored
        </button>
        <button className="act" onClick={() => onNav("publish")}>
          Publish a call
        </button>
      </div>
      <Disclaimer text={data.disclaimer} />
    </div>
  );
}
