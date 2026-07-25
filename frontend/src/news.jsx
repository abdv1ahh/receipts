// News Intelligence (Milestone 1): SEC 8-K material events + market/macro headlines, ranked by a
// DETERMINISTIC impact score and explained by the guarded analyst plane. Every card cites its source
// and is labelled "AI analysis" (model-written) or "auto" (deterministic template) — never fabricated.
import { useEffect, useState } from "react";
import { fetchNews } from "./api";
import { CoverageView } from "./coverage.jsx";

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
          {it.has_signal && <span className="sig-badge" title="Smart money is converging on this name in TradeOSS signal data">⚡ smart money</span>}
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

const CATS = ["all", "earnings", "ma", "distress", "officer_change", "guidance", "regulatory", "macro", "markets"];
const CAT_TAB = { all: "All", earnings: "Earnings", ma: "M&A", distress: "Distress", officer_change: "Leadership", guidance: "Guidance", regulatory: "Regulatory", macro: "Macro", markets: "Markets" };

// Group same-ticker items into one story (removing duplicate reporting), leaving un-tickered macro/market
// headlines as their own entries. Items arrive impact-ranked, so a symbol's first item is its lead.
function groupStories(items) {
  const bySym = new Map();
  const entries = [];
  for (const it of items) {
    const sym = (it.symbols || [])[0];
    if (sym && bySym.has(sym)) { bySym.get(sym).related.push(it); continue; }
    const e = { key: sym || `i${it.id}`, lead: it, related: [] };
    if (sym) bySym.set(sym, e);
    entries.push(e);
  }
  return entries;
}

function NewsHero({ entry, onOpenSymbol }) {
  const it = entry.lead;
  return (
    <div className={`news-hero band-${IMPACT_BAND(it.impact)}`}>
      <div className="news-hero-top">
        <span className="news-hero-kicker"><span className="live-dot" /> Top story now</span>
        <span className="cat-tag">{CAT_LABEL[it.category] || it.category || "News"}</span>
        {it.has_signal && <span className="sig-badge">⚡ smart money</span>}
        <span className="spacer" />
        <span className={`impact-pill band-${IMPACT_BAND(it.impact)}`}>impact {it.impact}</span>
      </div>
      <a className="news-hero-headline" href={it.url} target="_blank" rel="noreferrer">{it.headline}</a>
      {it.why_it_matters && <p className="news-hero-why">{it.why_it_matters}</p>}
      <div className="news-hero-foot">
        {(it.symbols || []).slice(0, 5).map((s) => <button key={s} className="tkr" onClick={() => onOpenSymbol?.(s)}>{s}</button>)}
        {entry.related.length > 0 && <span className="related-count">＋{entry.related.length} related</span>}
        <span className="spacer" />
        <span className={`ai-tag ${it.ai_generated ? "ai-on" : ""}`}>{it.ai_generated ? "✦ AI analysis" : "auto"}</span>
        <span className="news-time">{timeAgo(it.knowable_time)}</span>
        <span className="src">{sourceLabel(it.source)}</span>
      </div>
    </div>
  );
}

function StoryCard({ entry, onOpenSymbol }) {
  const [open, setOpen] = useState(false);
  const it = entry.lead;
  const rel = entry.related;
  return (
    <div className="news-card">
      <div className={`impact band-${IMPACT_BAND(it.impact)}`} title="Estimated market impact (deterministic 0–100)">
        <span className="impact-n num">{it.impact}</span><span className="impact-l">IMPACT</span>
      </div>
      <div className="news-body">
        <div className="news-head">
          {(it.symbols || []).slice(0, 4).map((s) => <button key={s} className="tkr" onClick={() => onOpenSymbol?.(s)}>{s}</button>)}
          <span className="cat-tag">{CAT_LABEL[it.category] || it.category || "News"}</span>
          {it.has_signal && <span className="sig-badge" title="Smart money is converging on this name in TradeOSS signal data">⚡ smart money</span>}
          <span className="spacer" />
          <span className="news-time">{timeAgo(it.knowable_time)}</span>
        </div>
        <a className="news-headline" href={it.url} target="_blank" rel="noreferrer">{it.headline}</a>
        {it.why_it_matters && <div className="news-why">{it.why_it_matters}</div>}
        <div className="news-foot">
          {it.confidence && <span className={`conf conf-${it.confidence}`}>{it.confidence} confidence</span>}
          <span className={`ai-tag ${it.ai_generated ? "ai-on" : ""}`}>{it.ai_generated ? "✦ AI analysis" : "auto"}</span>
          {rel.length > 0 && <button className="related-toggle" onClick={() => setOpen((o) => !o)}>＋{rel.length} related on {(it.symbols || [])[0]}</button>}
          <span className="spacer" />
          <span className="src">{sourceLabel(it.source)}</span>
        </div>
        {open && rel.length > 0 && (
          <div className="related">
            {rel.map((r) => (
              <a key={r.id} className="related-link" href={r.url} target="_blank" rel="noreferrer">
                <span className={`related-impact band-${IMPACT_BAND(r.impact)}`}>{r.impact}</span>
                <span className="related-hl">{r.headline}</span>
                <span className="related-meta">{sourceLabel(r.source)} · {timeAgo(r.knowable_time)}</span>
              </a>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export function NewsView({ onOpenSymbol }) {
  const [data, setData] = useState(null);
  const [cat, setCat] = useState("all");
  const [tab, setTab] = useState("stories");
  const [err, setErr] = useState(null);
  useEffect(() => {
    setData(null);
    fetchNews({ category: cat === "all" ? undefined : cat, hours: 168, limit: 80 })
      .then(setData).catch((e) => setErr(String(e)));
  }, [cat]);

  const items = data?.items || [];
  const entries = groupStories(items);
  const highN = items.filter((i) => i.impact >= 60).length;
  const freshest = items[0]?.knowable_time || items.reduce((a, i) => (!a || i.knowable_time > a ? i.knowable_time : a), null);

  return (
    <div>
      <div className="page-head">
        <div>
          <h1 className="page-title">News Intelligence</h1>
          <div className="page-sub">Every material event and market headline, deduped and ranked by expected impact, each explained by the analyst — sourced, never fabricated.</div>
        </div>
        <div className="sm-filter">
          <button className={tab === "stories" ? "on" : ""} onClick={() => setTab("stories")}>Stories</button>
          <button className={tab === "coverage" ? "on" : ""} onClick={() => setTab("coverage")}>Coverage</button>
        </div>
      </div>

      {tab === "coverage" && <CoverageView />}

      {tab === "coverage" ? null : data && items.length > 0 && (
        <div className="news-pulse">
          <span className="dash-live"><span className="live-dot" /> updated {timeAgo(freshest)}</span>
          <span className="dot-sep">·</span>
          <span><b>{items.length}</b> stories</span>
          <span className="dot-sep">·</span>
          <span><b className="sm-hi">{highN}</b> high-impact</span>
          <span className="dot-sep">·</span>
          <span>{entries.length} after grouping duplicates</span>
        </div>
      )}

      {tab === "coverage" ? null : <div className="j-tabs" style={{ marginTop: 12 }}>
        {CATS.map((c) => <button key={c} className={`j-tab ${cat === c ? "on" : ""}`} onClick={() => setCat(c)}>{CAT_TAB[c]}</button>)}
      </div>}

      {tab === "coverage" ? null : data && <SourceStrip sources={data.sources} />}
      {tab === "coverage" ? null : err && <div className="err">error: {err}</div>}

      {tab === "coverage" ? null : data === null ? (
        [...Array(5)].map((_, i) => <div key={i} className="news-card news-skel"><div className="skel" style={{ width: `${70 - i * 7}%` }} /></div>)
      ) : items.length === 0 ? (
        <div className="empty">No news at this filter in the last few days. The 8-K feed and market feeds fill in as filings and headlines cross the wire.</div>
      ) : (
        <>
          <NewsHero entry={entries[0]} onOpenSymbol={onOpenSymbol} />
          {entries.slice(1).map((e) => <StoryCard key={e.key} entry={e} onOpenSymbol={onOpenSymbol} />)}
        </>
      )}
    </div>
  );
}
