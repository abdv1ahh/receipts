// Unified search across assets, institutions, insiders, the library and traders.
//
// This file used to also hold LandingView (the app's own logged-out marketing page) and ExploreView
// (a discovery hub). Both are gone: "/" now sends a signed-out visitor to the marketing site in
// `site/`, so LandingView had no route left and was still pitching the pre-rebrand product, and
// ExploreView was imported by nothing and linked to a "community" surface that no longer exists.
import { useEffect, useState } from "react";
import { fetchSearch } from "./api";

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
