// Slice C: "act + prove". Shadow the smart money with paper portfolios tracked honestly against
// SPY, and a public track record built straight from the backtest — published even when it's
// unflattering, because calibration is the brand.
import { useEffect, useState } from "react";
import {
  addPosition, createPortfolio, deletePortfolio, fetchPortfolios, fetchTrackRecord,
  getPortfolio, removePosition,
} from "./api";

const pct = (v) => (v == null ? "—" : `${v >= 0 ? "+" : ""}${(v * 100).toFixed(1)}%`);
const cls = (v) => (v == null ? "" : v > 0 ? "pos-pos" : v < 0 ? "pos-neg" : "");

function TrackRecord({ track }) {
  if (!track) return null;
  const buckets = ["high", "medium", "low"];
  const horizons = [30, 90];
  return (
    <div className="track">
      <div className="board-title" style={{ fontSize: 14 }}>📊 Live public track record — excess return vs SPY</div>
      <table className="clusters" style={{ marginTop: 6 }}>
        <thead><tr><th>Bucket</th>{horizons.map((h) => <th key={h}>{h}d avg excess</th>)}<th>hit rate</th></tr></thead>
        <tbody>
          {buckets.map((b) => {
            const c90 = track.per_bucket?.[b]?.["90"] || {};
            return (
              <tr key={b}>
                <td><span className={`pill pill-${b}`}>{b}</span></td>
                {horizons.map((h) => {
                  const c = track.per_bucket?.[b]?.[String(h)] || {};
                  return <td key={h} className={`num ${cls(c.mean_excess)}`}>{c.episodes ? pct(c.mean_excess) : "—"}</td>;
                })}
                <td className="num">{c90.episodes ? (c90.sufficient ? `${Math.round(c90.hit_rate * 100)}% (n=${c90.episodes})` : `insufficient (n=${c90.episodes})`) : "—"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <div className="name" style={{ marginTop: 6 }}>{track.note}</div>
    </div>
  );
}

function PositionsTable({ p, onRemove, onOpenSymbol }) {
  return (
    <table className="clusters" style={{ marginTop: 8 }}>
      <thead><tr><th>Ticker</th><th>Entry</th><th>Return</th><th>vs SPY</th><th>Excess</th><th></th></tr></thead>
      <tbody>
        {p.positions.map((x) => (
          <tr key={x.id}>
            <td><button className="linkish sym" onClick={() => onOpenSymbol(x.symbol)}>{x.symbol}</button></td>
            {x.priced ? (
              <>
                <td className="num">{x.entry_day}<div className="name">{x.days_held}d held</div></td>
                <td className={`num ${cls(x.return)}`}>{pct(x.return)}</td>
                <td className="num">{pct(x.spy_return)}</td>
                <td className={`num ${cls(x.excess)}`}>{pct(x.excess)}</td>
              </>
            ) : (
              <><td className="num">{x.opened_on}</td><td colSpan={3} className="name">pending — no priceable window yet</td></>
            )}
            <td><button className="linkish" style={{ color: "var(--muted)" }} onClick={() => onRemove(x.id)}>remove</button></td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function PortfoliosView({ user, onLogin, onOpenSymbol }) {
  const [track, setTrack] = useState(null);
  const [list, setList] = useState(null);
  const [authed, setAuthed] = useState(true);
  const [open, setOpen] = useState(null);   // opened portfolio detail
  const [sym, setSym] = useState("");
  const [busy, setBusy] = useState(false);

  const loadList = () => fetchPortfolios().then((d) => { setAuthed(d.authenticated); setList(d.portfolios || []); });
  useEffect(() => { fetchTrackRecord().then(setTrack).catch(() => {}); loadList().catch(() => setAuthed(false)); }, [user]);

  const shadowSignals = async () => {
    setBusy(true);
    const c = await createPortfolio("Shadow high-conviction", "shadow_bucket", ["high", "medium"]);
    await loadList();
    if (c.id) setOpen(await getPortfolio(c.id));
    setBusy(false);
  };
  const newManual = async () => { const c = await createPortfolio("My picks", "manual"); await loadList(); if (c.id) setOpen(await getPortfolio(c.id)); };
  const openOne = async (id) => setOpen(await getPortfolio(id));
  const add = async () => { if (!sym.trim() || !open) return; await addPosition(open.id, sym.trim().toUpperCase()); setSym(""); setOpen(await getPortfolio(open.id)); loadList(); };
  const remove = async (posId) => { await removePosition(open.id, posId); setOpen(await getPortfolio(open.id)); loadList(); };
  const del = async (id) => { await deletePortfolio(id); setOpen(null); loadList(); };

  return (
    <div className="detail">
      <h2>Shadow the smart money</h2>
      <div className="meta">Mirror the signals as paper positions and watch them against SPY — real prices, honest “pending” when a name can’t be priced. Below is our live public track record.</div>
      <TrackRecord track={track} />

      {!authed ? (
        <div className="empty" style={{ marginTop: 14 }}>
          Log in to build shadow portfolios and track your own P&amp;L vs SPY.
          <div style={{ marginTop: 10 }}><button className="act" onClick={onLogin}>log in</button></div>
        </div>
      ) : open ? (
        <div style={{ marginTop: 14 }}>
          <button className="back" onClick={() => setOpen(null)}>← all portfolios</button>
          <h3 style={{ margin: "4px 0" }}>{open.name} <span className="name">· {open.kind}</span></h3>
          {open.summary.priced > 0 ? (
            <div className="pnl-summary">
              <span>portfolio <b className={`num ${cls(open.summary.avg_return)}`}>{pct(open.summary.avg_return)}</b></span>
              <span>SPY <b className="num">{pct(open.summary.spy_return)}</b></span>
              <span>excess <b className={`num ${cls(open.summary.avg_excess)}`}>{pct(open.summary.avg_excess)}</b></span>
              <span className="name">{open.summary.beat_spy}/{open.summary.priced} beat SPY · {open.summary.pending} pending</span>
            </div>
          ) : <div className="name" style={{ margin: "6px 0" }}>No priceable positions yet ({open.summary.pending} pending).</div>}
          <div className="controls" style={{ marginTop: 8 }}>
            <input className="search" placeholder="add ticker…" value={sym} onChange={(e) => setSym(e.target.value)} onKeyDown={(e) => e.key === "Enter" && add()} />
            <button className="act" onClick={add}>add position</button>
            <button className="act" style={{ marginLeft: "auto" }} onClick={() => del(open.id)}>delete portfolio</button>
          </div>
          {open.positions.length > 0 && <PositionsTable p={open} onRemove={remove} onOpenSymbol={onOpenSymbol} />}
        </div>
      ) : (
        <div style={{ marginTop: 14 }}>
          <div className="controls">
            <button className="act act-on" disabled={busy} onClick={shadowSignals}>{busy ? "building…" : "⚡ Shadow high-conviction signals"}</button>
            <button className="act" onClick={newManual}>+ new manual portfolio</button>
          </div>
          {list === null ? <div className="skel" style={{ width: "40%", marginTop: 12 }} />
            : list.length === 0 ? <div className="name" style={{ marginTop: 12 }}>No portfolios yet. Shadow the signals or start a manual one.</div>
            : (
              <table className="clusters" style={{ marginTop: 10 }}>
                <thead><tr><th>Portfolio</th><th>Return</th><th>vs SPY</th><th>Excess</th><th>Positions</th></tr></thead>
                <tbody>
                  {list.map((p) => (
                    <tr className="row" key={p.id} onClick={() => openOne(p.id)}>
                      <td><div className="sym">{p.name}</div><div className="name">{p.kind}</div></td>
                      <td className={`num ${cls(p.summary.avg_return)}`}>{pct(p.summary.avg_return)}</td>
                      <td className="num">{pct(p.summary.spy_return)}</td>
                      <td className={`num ${cls(p.summary.avg_excess)}`}>{pct(p.summary.avg_excess)}</td>
                      <td className="num">{p.summary.priced}<span className="name"> priced · {p.summary.pending} pending</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
        </div>
      )}
    </div>
  );
}
