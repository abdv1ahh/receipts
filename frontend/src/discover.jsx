// Slice J: the front door + discovery. LandingView (marketing page for logged-out visitors),
// SearchView (unified search across assets/institutions/insiders/library/traders), and ExploreView
// (a discover hub composing the real surfaces). Honest, premium, calibration-first framing throughout.
import { useEffect, useState } from "react";
import { fetchClusters, fetchCommunityFeed, fetchCryptoTrending, fetchSearch, fetchTrending } from "./api";

const FEATURES = [
  ["🎯", "Smart-money convergence", "Insiders, activists and funds converging on one name — straight from the filings, with a backtested base rate attached."],
  ["📓", "AI trade journal", "Log your trades and get a guarded, educational analysis of each — cross-referenced against the smart-money signal for that ticker."],
  ["🧠", "AI market assistant", "Ask about a ticker, a strategy, or your own trades. Grounded in real platform data; honest about what it doesn't know."],
  ["📈", "Attention scanner", "What's being discussed more than usual, from real sources — with manipulation flags, not hype."],
  ["👥", "Trader community", "Share real, logged trades and learn from track records. The leaderboard ranks by honest win rate, never raw returns."],
  ["₿", "Live crypto", "Real market data and trending coins, with unmissable risk labels. Market data, never advice."],
];

export function LandingView({ onGetStarted, onExplore }) {
  return (
    <div className="landing">
      <div className="landing-hero">
        <div className="eyebrow">Trading intelligence, calibrated</div>
        <h1 className="landing-h1">See what the smartest money is quietly doing.</h1>
        <p className="landing-sub">
          TradeOS reads the filings the pros move on — insiders, activists, and funds converging on one
          name — then adds an AI trade journal, a grounded assistant, a live attention scanner, and a
          community that ranks by real track record. Honest, backtested, probability-framed.
          <b> Never guaranteed alpha.</b>
        </p>
        <div className="landing-cta">
          <button className="act act-on landing-btn" onClick={onGetStarted}>Get started — free</button>
          <button className="act landing-btn" onClick={onExplore}>Explore live →</button>
        </div>
        <div className="landing-trust">Calibration is the brand. Every performance figure is labeled backtested — and where the low-conviction bucket underperforms, we show it. Not investment advice.</div>
      </div>
      <div className="landing-grid">
        {FEATURES.map(([icon, title, body]) => (
          <div className="landing-card" key={title}>
            <div className="landing-icon">{icon}</div>
            <div className="landing-card-title">{title}</div>
            <div className="landing-card-body">{body}</div>
          </div>
        ))}
      </div>
      <div className="landing-foot">
        Built on the deepest legitimate map of what the world's best traders are doing — assembled only
        from sources we have the right to use. TradeOS never custodies funds and is not a broker.
      </div>
    </div>
  );
}

function ResultGroup({ title, items, render }) {
  if (!items || !items.length) return null;
  return (
    <div className="search-group">
      <div className="an-title">{title}</div>
      {items.map(render)}
    </div>
  );
}

export function SearchView({ query, onOpenSymbol, onOpenProfile, onOpenLibrary, onOpenTrader }) {
  const [data, setData] = useState(null);
  useEffect(() => { setData(null); if (query) fetchSearch(query).then(setData).catch(() => setData({ total: 0, results: {} })); }, [query]);
  if (!query) return <div className="detail"><div className="empty">Type a ticker, a fund, an insider, a concept, or a @trader.</div></div>;
  if (!data) return <div className="detail"><div className="skel" style={{ width: "50%" }} /></div>;
  const r = data.results || {};
  return (
    <div className="detail">
      <h2>Search · “{data.query}”</h2>
      {data.total === 0 && <div className="empty" style={{ marginTop: 12 }}>Nothing matched. Try a ticker, a company, or a @handle.</div>}
      <ResultGroup title="Assets" items={r.symbols} render={(s) => (
        <button key={s.symbol} className="search-row" onClick={() => onOpenSymbol(s.symbol)}><span className="sym">{s.symbol}</span><span className="name"> {s.name}</span></button>
      )} />
      <ResultGroup title="Institutions" items={r.institutions} render={(x) => (
        <button key={x.entity_id} className="search-row" onClick={() => onOpenProfile("institution", x.entity_id)}>{x.name}</button>
      )} />
      <ResultGroup title="Insiders" items={r.insiders} render={(x) => (
        <button key={x.cik} className="search-row" onClick={() => onOpenProfile("insider", x.cik)}>{x.name}</button>
      )} />
      <ResultGroup title="Intelligence library" items={r.library} render={(x) => (
        <button key={x.slug} className="search-row" onClick={() => onOpenLibrary(x.slug)}>{x.title}</button>
      )} />
      <ResultGroup title="Traders" items={r.traders} render={(x) => (
        <button key={x.handle} className="search-row" onClick={() => onOpenTrader(x.handle)}>@{x.handle}<span className="name"> {x.bio || ""}</span></button>
      )} />
    </div>
  );
}

function Sec({ title, onAll, children }) {
  return (
    <div className="board" style={{ marginTop: 12 }}>
      <div className="board-title" style={{ display: "flex" }}>{title}{onAll && <button className="linkish" style={{ marginLeft: "auto" }} onClick={onAll}>see all →</button>}</div>
      {children}
    </div>
  );
}

export function ExploreView({ onOpenSymbol, onNav, onOpenTrader }) {
  const [clusters, setClusters] = useState(null);
  const [trend, setTrend] = useState(null);
  const [coins, setCoins] = useState(null);
  const [feed, setFeed] = useState(null);
  useEffect(() => {
    fetchClusters("high").then((d) => setClusters(d.clusters || [])).catch(() => setClusters([]));
    fetchTrending(48).then((d) => setTrend(d.board || [])).catch(() => setTrend([]));
    fetchCryptoTrending().then((d) => setCoins(d.trending || [])).catch(() => setCoins([]));
    fetchCommunityFeed("public").then((d) => setFeed(d.feed || [])).catch(() => setFeed([]));
  }, []);
  const chip = (label, onClick) => <button key={label} className="coin-chip linkish" onClick={onClick}>{label}</button>;
  return (
    <div className="detail">
      <h2>Explore</h2>
      <div className="meta">One place to discover what's moving — smart money, public attention, crypto, and the community.</div>
      <Sec title="🎯 Strongest smart-money convergences" onAll={() => onNav("dashboard")}>
        <div className="trending-coins">{clusters === null ? <span className="name">loading…</span> : clusters.length === 0 ? <span className="name">none right now</span> : clusters.slice(0, 10).map((c) => chip(`${c.symbol || c.name} · ${c.confidence_bucket}`, () => c.symbol && onOpenSymbol(c.symbol)))}</div>
      </Sec>
      <Sec title="📈 Trending attention" onAll={() => onNav("trending")}>
        <div className="trending-coins">{trend === null ? <span className="name">loading…</span> : trend.length === 0 ? <span className="name">run ingest-sentiment to populate</span> : trend.slice(0, 10).map((t) => chip(`${t.symbol} · ${t.attention}`, () => onOpenSymbol(t.symbol)))}</div>
      </Sec>
      <Sec title="₿ Trending crypto" onAll={() => onNav("crypto")}>
        <div className="trending-coins">{coins === null ? <span className="name">loading…</span> : coins.length === 0 ? <span className="name">unavailable</span> : coins.slice(0, 10).map((c) => <span key={c.id || c.symbol} className="coin-chip">{c.symbol}</span>)}</div>
      </Sec>
      <Sec title="👥 Fresh from the community" onAll={() => onNav("community")}>
        <div className="trending-coins">{feed === null ? <span className="name">loading…</span> : feed.length === 0 ? <span className="name">no public trades yet</span> : feed.slice(0, 8).map((t) => chip(`${t.symbol || "idea"} · @${t.author}`, () => t.author && t.author !== "trader" && onOpenTrader(t.author)))}</div>
      </Sec>
    </div>
  );
}
