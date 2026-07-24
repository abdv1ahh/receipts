// Social & Attention Intelligence — what the crowd is discovering, ranked by how fast discussion is
// accelerating vs each name's OWN baseline. Honest by construction: velocity is a real ratio, sentiment
// shows only where a connected source measures it (Wikipedia/HN measure attention, not mood; Reddit adds
// mood when keyed), manipulation is flagged not hidden, and sources with no free tier (X, StockTwits)
// say "unavailable" rather than being faked. The strongest tell — attention that OVERLAPS a smart-money
// signal — is surfaced as a cross-plane badge. Nothing here is a recommendation.
import { useEffect, useMemo, useState } from "react";
import { fetchTrending } from "./api";
import { Icon } from "./icons.jsx";

const FLAG_LABEL = { single_source: "single source", bot_heavy: "bot-heavy" };
const SRC_LABEL = { wikipedia: "Wikipedia", hn: "Hacker News", reddit: "Reddit", youtube: "YouTube", stocktwits: "StockTwits", x: "X" };
const band = (n) => (n >= 70 ? "high" : n >= 45 ? "medium" : "low");
const SPIKE = 1.5;
const isBull = (v) => v != null && v > 0.2;
const isBear = (v) => v != null && v < -0.2;

function Sentiment({ v }) {
  if (v == null) return <span className="sent-na" title="This source measures attention, not mood">attention only</span>;
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
  const spiking = (r.velocity || 0) >= SPIKE;
  return (
    <div className={`att-card ${r.has_signal ? "att-hot" : ""}`}>
      <div className="att-rank">{rank}</div>
      <div className={`att-score band-${band(r.attention)}`}>
        <span className="att-n num">{r.attention}</span><span className="att-l">ATTN</span>
      </div>
      <div className="att-body">
        <div className="att-head">
          <button className="tkr" onClick={() => onOpenSymbol(r.symbol)}>{r.symbol}</button>
          <span className="att-name">{r.name}</span>
          {r.velocity != null && <span className={`att-vel ${spiking ? "spiking" : ""}`}>{spiking && "⚡ "}{r.velocity}× usual</span>}
          <Sentiment v={r.sentiment} />
          {r.has_signal && <span className="att-xp"><Icon name="signal" size={11} /> smart money here too</span>}
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

export function SocialView({ onOpenSymbol }) {
  const [data, setData] = useState(null);
  const [hours, setHours] = useState(96);
  const [filter, setFilter] = useState("all");
  useEffect(() => { setData(null); setFilter("all"); fetchTrending(hours).then(setData).catch(() => setData({ board: [], sources: null })); }, [hours]);

  const board = data?.board || [];
  const m = useMemo(() => {
    const measured = board.filter((r) => r.sentiment != null);
    return {
      spiking: board.filter((r) => (r.velocity || 0) >= SPIKE).length,
      overlap: board.filter((r) => r.has_signal).length,
      flagged: board.filter((r) => r.flags?.length).length,
      measured: measured.length,
      bull: measured.filter((r) => isBull(r.sentiment)).length,
      bear: measured.filter((r) => isBear(r.sentiment)).length,
    };
  }, [board]);

  const FILTERS = [
    { k: "all", label: "All", test: () => true },
    { k: "signal", label: "⚡ Smart money", test: (r) => r.has_signal },
    { k: "spiking", label: "Spiking", test: (r) => (r.velocity || 0) >= SPIKE },
    ...(m.measured > 0 ? [
      { k: "bull", label: "Bullish", test: (r) => isBull(r.sentiment) },
      { k: "bear", label: "Bearish", test: (r) => isBear(r.sentiment) },
    ] : []),
    { k: "flagged", label: "⚠ Flagged", test: (r) => r.flags?.length },
  ];
  const active = FILTERS.find((x) => x.k === filter) || FILTERS[0];
  const shown = board.filter(active.test);
  const countFor = (flt) => board.filter(flt.test).length;

  return (
    <div>
      <div className="page-head">
        <div>
          <h1 className="page-title">Social &amp; Attention Intelligence</h1>
          <div className="page-sub">What the crowd is discovering — ranked by attention velocity, with the likely catalyst. Never fabricated.</div>
        </div>
        <div className="sm-filter">
          {[24, 96, 168, 336].map((h) => <button key={h} className={hours === h ? "on" : ""} onClick={() => setHours(h)}>{h >= 168 ? `${h / 24}d` : `${h}h`}</button>)}
        </div>
      </div>

      {data && board.length > 0 && (
        <div className="soc-pulse">
          <div className="soc-pulse-l">
            <div className="pulse-kicker"><span className="live-dot" /> Attention Pulse</div>
            <div className="soc-pulse-head">{board.length} name{board.length !== 1 ? "s" : ""} drawing unusual attention</div>
            <div className="soc-pulse-sub">ranked by how fast discussion is accelerating vs each name's own baseline</div>
          </div>
          <div className="soc-stats">
            <div className="soc-stat"><b>{m.spiking}</b><span>spiking ≥{SPIKE}×</span></div>
            <div className="soc-stat"><b className="sm-hi">{m.overlap}</b><span>⚡ + smart money</span></div>
            {m.measured > 0
              ? <><div className="soc-stat"><b className="pos-pos">{m.bull}</b><span>bullish</span></div>
                  <div className="soc-stat"><b className="pos-neg">{m.bear}</b><span>bearish</span></div></>
              : <div className="soc-stat wide"><b>—</b><span>mood not measured · connect Reddit</span></div>}
          </div>
        </div>
      )}

      {data && <SourceStatus sources={data.sources} />}

      {data && board.length > 0 && (
        <div className="j-tabs" style={{ marginTop: 14 }}>
          {FILTERS.map((x) => (
            <button key={x.k} className={`j-tab ${filter === x.k ? "on" : ""}`} onClick={() => setFilter(x.k)}>
              {x.label} <span className="j-tab-n">{countFor(x)}</span>
            </button>
          ))}
        </div>
      )}

      {data === null ? (
        [...Array(5)].map((_, i) => <div key={i} className="att-card news-skel"><div className="skel" style={{ width: `${65 - i * 7}%` }} /></div>)
      ) : board.length === 0 ? (
        <div className="empty" style={{ marginTop: 14 }}>{data.note || "No attention data yet."}</div>
      ) : shown.length === 0 ? (
        <div className="empty" style={{ marginTop: 6 }}>Nothing in this view right now.</div>
      ) : (
        shown.map((r, i) => <AttentionCard key={r.symbol} r={r} rank={board.indexOf(r) + 1} onOpenSymbol={onOpenSymbol} />)
      )}

      <div className="disc" style={{ marginTop: 16 }}>Attention reflects public discussion/lookup volume, not a recommendation. “attention only” means the connected source measures attention but not mood; connect Reddit (free key) to add discussion sentiment. “⚡ smart money here too” means this name also shows an SEC-derived convergence signal — the crowd and the filings are pointing at the same place.</div>
    </div>
  );
}
