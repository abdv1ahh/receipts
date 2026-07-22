// Slice H: Sentiment & Trend Scanner. Symbols ranked by public-attention velocity from real, free
// sources (Hacker News by default; Reddit/YouTube when the operator adds a free key). Honest: a name
// appears only above a mention floor, attention is a velocity vs its own baseline, manipulation is
// flagged, and unconnected sources say so rather than showing fabricated numbers.
import { useEffect, useState } from "react";
import { fetchTrending } from "./api";

const FLAG_LABEL = { single_source: "single source", bot_heavy: "bot-heavy" };

function AttentionBar({ score }) {
  return (
    <div className="att-bar" title={`attention ${score}/100`}>
      <div className="att-fill" style={{ width: `${score}%` }} />
      <span className="att-num">{score}</span>
    </div>
  );
}

function SourceStatus({ sources }) {
  if (!sources) return null;
  const dot = (s) => (s === "connected" ? "🟢" : s === "needs_key" ? "🟡" : "⚪");
  const suffix = (s) => (s === "needs_key" ? " · add free key" : s === "unavailable" ? " · no free tier" : "");
  return (
    <div className="src-status">
      {Object.entries(sources).map(([k, s]) => (
        <span key={k} className={`src-stat s-${s.state}`}>{dot(s.state)} {s.label}{suffix(s.state)}</span>
      ))}
    </div>
  );
}

export function ScannerView({ onOpenSymbol }) {
  const [data, setData] = useState(null);
  const [hours, setHours] = useState(48);
  useEffect(() => { setData(null); fetchTrending(hours).then(setData).catch(() => setData({ board: [], sources: null })); }, [hours]);

  return (
    <div className="detail">
      <div className="j-head">
        <h2>📈 Trending now</h2>
        <div className="seg">
          {[24, 48, 168].map((h) => <button key={h} className={hours === h ? "on" : ""} onClick={() => setHours(h)}>{h === 168 ? "7d" : `${h}h`}</button>)}
        </div>
      </div>
      <div className="meta">Symbols ranked by public-attention velocity — how much more they're being discussed than usual — from real, free sources. A name appears only above a mention floor; attention is a velocity vs its own baseline; possible manipulation is flagged, never hidden.</div>
      <SourceStatus sources={data?.sources} />

      {data === null ? <div className="skel" style={{ width: "50%", marginTop: 14 }} />
        : data.board?.length === 0 ? (
          <div className="empty" style={{ marginTop: 14 }}>{data.note || "No attention data yet."}</div>
        ) : (
          <table className="clusters" style={{ marginTop: 12 }}>
            <thead><tr><th>#</th><th>Symbol</th><th>Attention</th><th>Velocity</th><th>Mentions</th><th>Sentiment</th><th>Sources</th></tr></thead>
            <tbody>
              {data.board.map((r, i) => (
                <tr className="row" key={r.symbol} onClick={() => onOpenSymbol(r.symbol)}>
                  <td className="board-rank">{i + 1}</td>
                  <td>
                    <span className="sym">{r.symbol}</span>
                    {r.is_new && <span className="chip s-open" style={{ marginLeft: 6 }}>new</span>}
                    {r.flags?.map((f) => <span key={f} className="chip flag-chip" style={{ marginLeft: 6 }} title="manipulation-resistance flag">⚠ {FLAG_LABEL[f] || f}</span>)}
                    <div className="name">{r.name}</div>
                  </td>
                  <td style={{ minWidth: 120 }}><AttentionBar score={r.attention} /></td>
                  <td className="num">{r.velocity != null ? `${r.velocity}×` : "—"}</td>
                  <td className="num">{r.mentions}</td>
                  <td className="num">{r.sentiment != null ? r.sentiment.toFixed(2) : "—"}</td>
                  <td>{r.sources.map((s) => <span key={s} className="src-chip">{s}</span>)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      <div className="disc" style={{ marginTop: 16 }}>Attention reflects public discussion volume, not a recommendation. A “—” sentiment means the connected source measures attention but not sentiment; connect Reddit or YouTube (free keys) to add it.</div>
    </div>
  );
}
