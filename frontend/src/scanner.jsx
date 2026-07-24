// Social & Attention Intelligence (Milestone 2). Names ranked by public-attention VELOCITY across
// real sources — Wikipedia pageviews + Hacker News now, Reddit discussion when its free key is set —
// each with the analyst's "why it's drawing attention" connecting the spike to its likely news
// catalyst. Honest by construction: velocity is vs a name's own baseline, manipulation is flagged,
// sentiment shows only where a source measures it, and unconnected sources say so.
import { useEffect, useState } from "react";
import { fetchTrending } from "./api";

const FLAG_LABEL = { single_source: "single source", bot_heavy: "bot-heavy" };
const SRC_LABEL = { wikipedia: "Wikipedia", hn: "Hacker News", reddit: "Reddit", youtube: "YouTube" };
const band = (n) => (n >= 70 ? "high" : n >= 45 ? "medium" : "low");

function Sentiment({ v }) {
  if (v == null) return <span className="sent-na" title="This source measures attention, not sentiment">attention only</span>;
  const s = v > 0.2 ? ["bull", "bullish"] : v < -0.2 ? ["bear", "bearish"] : ["neutral", "mixed"];
  return <span className={`sent sent-${s[0]}`}>{s[1]} {v.toFixed(2)}</span>;
}

function SourceStatus({ sources }) {
  if (!sources) return null;
  return (
    <div className="src-strip">
      {Object.entries(sources).map(([k, s]) => (
        <span key={k} className={`src-dot ${s.state === "connected" ? "on" : s.state === "needs_key" ? "warn" : "off"}`}
              title={s.state === "needs_key" ? "add a free key to connect" : s.state === "unavailable" ? "no reachable free tier" : "connected"}>
          <i /> {s.label}{s.state === "needs_key" ? " · add key" : s.state === "unavailable" ? " · n/a" : ""}
        </span>
      ))}
    </div>
  );
}

function AttentionCard({ r, rank, onOpenSymbol }) {
  return (
    <div className="att-card">
      <div className="att-rank">{rank}</div>
      <div className={`att-score band-${band(r.attention)}`}>
        <span className="att-n num">{r.attention}</span><span className="att-l">ATTN</span>
      </div>
      <div className="att-body">
        <div className="att-head">
          <button className="tkr" onClick={() => onOpenSymbol(r.symbol)}>{r.symbol}</button>
          <span className="att-name">{r.name}</span>
          {r.velocity != null && <span className="att-vel">{r.velocity}× usual</span>}
          <Sentiment v={r.sentiment} />
          {r.is_new && <span className="chip s-open">new</span>}
          {r.flags?.map((f) => <span key={f} className="chip flag-chip" title="manipulation-resistance flag">⚠ {FLAG_LABEL[f] || f}</span>)}
          <span className="spacer" />
          {(r.sources || []).map((s) => <span key={s} className="src-badge">{SRC_LABEL[s] || s}</span>)}
        </div>
        {r.why?.text && (
          <div className="att-why">
            {r.why.text}
            {r.why.confidence && <span className={`conf conf-${r.why.confidence}`} style={{ marginLeft: 8 }}>{r.why.confidence} confidence</span>}
          </div>
        )}
        {r.news?.length > 0 && (
          <div className="att-news">
            {r.news.map((n) => <a key={n.id} className="att-news-link" href={n.url} target="_blank" rel="noreferrer">↗ {n.headline}</a>)}
          </div>
        )}
      </div>
    </div>
  );
}

export function ScannerView({ onOpenSymbol }) {
  const [data, setData] = useState(null);
  const [hours, setHours] = useState(96);
  useEffect(() => { setData(null); fetchTrending(hours).then(setData).catch(() => setData({ board: [], sources: null })); }, [hours]);

  return (
    <div>
      <div className="page-head">
        <div>
          <h1 className="page-title">Social &amp; Attention Intelligence</h1>
          <div className="page-sub">What the crowd is discovering — ranked by attention velocity, with the likely catalyst. Never fabricated.</div>
        </div>
        <div className="seg">
          {[24, 96, 168, 336].map((h) => <button key={h} className={hours === h ? "on" : ""} onClick={() => setHours(h)}>{h >= 168 ? `${h / 24}d` : `${h}h`}</button>)}
        </div>
      </div>
      {data && <SourceStatus sources={data.sources} />}
      {data === null ? (
        [...Array(5)].map((_, i) => <div key={i} className="att-card news-skel"><div className="skel" style={{ width: `${65 - i * 7}%` }} /></div>)
      ) : data.board?.length === 0 ? (
        <div className="empty" style={{ marginTop: 14 }}>{data.note || "No attention data yet."}</div>
      ) : (
        data.board.map((r, i) => <AttentionCard key={r.symbol} r={r} rank={i + 1} onOpenSymbol={onOpenSymbol} />)
      )}
      <div className="disc" style={{ marginTop: 16 }}>Attention reflects public discussion/lookup volume, not a recommendation. "attention only" means the connected source measures attention but not mood; connect Reddit (free key) to add discussion sentiment.</div>
    </div>
  );
}
