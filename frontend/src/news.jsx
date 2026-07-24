// News Intelligence (Milestone 1): SEC 8-K material events + market/macro headlines, ranked by a
// DETERMINISTIC impact score and explained by the guarded analyst plane. Every card cites its source
// and is labelled "AI analysis" (model-written) or "auto" (deterministic template) — never fabricated.
import { useEffect, useState } from "react";
import { fetchNews } from "./api";

const IMPACT_BAND = (n) => (n >= 70 ? "high" : n >= 45 ? "medium" : "low");
const CAT_LABEL = {
  earnings: "Earnings", ma: "M&A", distress: "Distress", officer_change: "Leadership",
  guidance: "Guidance", agreement: "Agreement", financing: "Financing", regulatory: "Regulatory",
  governance: "Governance", macro: "Macro", markets: "Markets", disclosure: "Disclosure", general: "News",
};
const SRC_LABEL = {
  "sec/8-k": "SEC 8-K", "rss/fed": "Federal Reserve", "rss/sec": "SEC Press",
  "rss/cnbc-markets": "CNBC", "rss/cnbc-top": "CNBC",
};
export const sourceLabel = (s) => SRC_LABEL[s] || (s || "").replace("rss/", "").replace("sec/", "SEC ");

export function timeAgo(iso) {
  if (!iso) return "";
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
}

export function NewsCard({ it, onOpenSymbol }) {
  return (
    <div className="news-card">
      <div className={`impact band-${IMPACT_BAND(it.impact)}`} title="Estimated market impact (deterministic 0–100)">
        <span className="impact-n num">{it.impact}</span>
        <span className="impact-l">IMPACT</span>
      </div>
      <div className="news-body">
        <div className="news-head">
          {(it.symbols || []).slice(0, 4).map((s) => (
            <button key={s} className="tkr" onClick={() => onOpenSymbol && onOpenSymbol(s)}>{s}</button>
          ))}
          <span className="cat-tag">{CAT_LABEL[it.category] || it.category || "News"}</span>
          {it.has_signal && <span className="sig-badge" title="Smart money is converging on this name in TradeOS signal data">⚡ smart money</span>}
          <span className="spacer" />
          <span className="news-time">{timeAgo(it.knowable_time)}</span>
        </div>
        <a className="news-headline" href={it.url} target="_blank" rel="noreferrer">{it.headline}</a>
        {it.why_it_matters && <div className="news-why">{it.why_it_matters}</div>}
        <div className="news-foot">
          {it.confidence && <span className={`conf conf-${it.confidence}`}>{it.confidence} confidence</span>}
          <span className={`ai-tag ${it.ai_generated ? "ai-on" : ""}`}>{it.ai_generated ? "✦ AI analysis" : "auto"}</span>
          <span className="spacer" />
          <span className="src">{sourceLabel(it.source)}</span>
        </div>
      </div>
    </div>
  );
}

function SourceStrip({ sources }) {
  if (!sources) return null;
  return (
    <div className="src-strip">
      {sources.map((s) => (
        <span key={s.key} className={`src-dot ${s.state === "connected" ? "on" : "off"}`} title={`${s.state}${s.freshest ? ` · ${s.freshest.slice(0, 10)}` : ""}`}>
          <i /> {s.label}
        </span>
      ))}
    </div>
  );
}

const CATS = ["all", "earnings", "ma", "distress", "officer_change", "macro", "markets"];
const CAT_TAB = { all: "All", earnings: "Earnings", ma: "M&A", distress: "Distress", officer_change: "Leadership", macro: "Macro", markets: "Markets" };

export function NewsView({ onOpenSymbol }) {
  const [data, setData] = useState(null);
  const [cat, setCat] = useState("all");
  const [err, setErr] = useState(null);
  useEffect(() => {
    setData(null);
    fetchNews({ category: cat === "all" ? undefined : cat, hours: 120, limit: 40 })
      .then(setData).catch((e) => setErr(String(e)));
  }, [cat]);

  return (
    <div>
      <div className="page-head">
        <div>
          <h1 className="page-title">News Intelligence</h1>
          <div className="page-sub">Material events and market news, ranked by impact and explained — sourced, never fabricated.</div>
        </div>
      </div>
      <div className="controls">
        <div className="seg">
          {CATS.map((c) => <button key={c} className={cat === c ? "on" : ""} onClick={() => setCat(c)}>{CAT_TAB[c]}</button>)}
        </div>
      </div>
      {data && <SourceStrip sources={data.sources} />}
      {err && <div className="err">error: {err}</div>}
      {data === null ? (
        [...Array(5)].map((_, i) => <div key={i} className="news-card news-skel"><div className="skel" style={{ width: `${70 - i * 7}%` }} /></div>)
      ) : data.items.length === 0 ? (
        <div className="empty">No news at this filter in the last few days. The 8-K feed and market feeds fill in as filings and headlines cross the wire.</div>
      ) : (
        data.items.map((it) => <NewsCard key={it.id} it={it} onOpenSymbol={onOpenSymbol} />)
      )}
    </div>
  );
}
