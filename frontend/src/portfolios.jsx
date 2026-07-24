// Portfolio: shadow the smart money with paper positions tracked honestly against SPY, plus a
// portfolio health read (diversification + smart-money coverage + vs-SPY), concentration warnings, and
// equal-weight allocation. Every P&L figure is real prices vs SPY; a name we can't price is "pending",
// never a guessed value. We DON'T compute sector exposure, correlation, dividends, expected returns or
// stress tests (no data/pricing model wired) and say so rather than fake them.
import { useEffect, useState } from "react";
import {
  addPosition, createPortfolio, deletePortfolio, fetchPortfolios, fetchTrackRecord,
  getPortfolio, removePosition,
} from "./api";
import { Icon } from "./icons.jsx";

const pct = (v) => (v == null ? "—" : `${v >= 0 ? "+" : ""}${(v * 100).toFixed(1)}%`);
const cls = (v) => (v == null ? "" : v > 0 ? "pos-pos" : v < 0 ? "pos-neg" : "");

function health(s) {
  const n = s.positions || 0;
  const cov = n ? (s.signal_count || 0) / n : 0;
  let score = 45;
  const drivers = [];
  score += Math.min(22, n * 3);
  drivers.push({ pol: n >= 8 ? "pos" : n >= 4 ? "neutral" : "warn", label: "Diversification",
                 text: `${n} position${n !== 1 ? "s" : ""}${n < 5 ? " — thin, concentrated" : ""}` });
  score += Math.round(cov * 18);
  drivers.push({ pol: cov >= 0.5 ? "pos" : cov > 0 ? "neutral" : "warn", label: "Smart-money coverage",
                 text: `${s.signal_count || 0} of ${n} still show a live signal` });
  if (s.priced > 0 && s.avg_excess != null) {
    const beat = s.avg_excess > 0;
    score += beat ? 15 : -12;
    drivers.push({ pol: beat ? "pos" : "neg", label: "Vs SPY",
                   text: `${beat ? "beating" : "trailing"} SPY by ${pct(Math.abs(s.avg_excess))} · ${s.beat_spy}/${s.priced} names ahead` });
  } else {
    drivers.push({ pol: "neutral", label: "Vs SPY", text: "no priceable window yet" });
  }
  score = Math.max(5, Math.min(98, Math.round(score)));
  return { score, band: score >= 66 ? "high" : score >= 45 ? "medium" : "low", drivers };
}

function HealthCard({ summary }) {
  const h = health(summary);
  const n = summary.positions || 0;
  return (
    <div className="pf-health">
      <div className={`pf-health-med band-${h.band === "high" ? "high" : h.band === "medium" ? "med" : "low"}`}>
        <div className="med-score num">{h.score}</div><div className="med-label">HEALTH</div>
      </div>
      <div className="pf-health-body">
        <div className="pf-drivers">
          {h.drivers.map((d, i) => <div key={i} className="driver"><span className={`dot ${d.pol}`} /><span><b>{d.label}:</b> {d.text}</span></div>)}
        </div>
        {n > 0 && n < 5 && (
          <div className="pf-warn"><Icon name="target" size={13} /> Concentrated — only {n} name{n !== 1 ? "s" : ""}. Each is ~{Math.round(100 / n)}% of this equal-weight paper book, so a stumble in one moves the whole book.</div>
        )}
      </div>
    </div>
  );
}

function Allocation({ positions }) {
  const syms = positions.map((p) => p.symbol);
  if (syms.length === 0) return null;
  const w = 100 / syms.length;
  return (
    <div className="pf-alloc">
      <div className="pf-alloc-bar">
        {syms.map((s, i) => <span key={s} className="pf-alloc-seg" style={{ width: `${w}%`, background: `hsl(${(i * 47) % 360} 55% 55% / 0.75)` }} title={`${s} · ${w.toFixed(0)}%`} />)}
      </div>
      <div className="pf-alloc-note">Equal-weight paper allocation · {w.toFixed(0)}% per name</div>
    </div>
  );
}

function TrackRecord({ track }) {
  if (!track) return null;
  const buckets = ["high", "medium", "low"], horizons = [30, 90];
  return (
    <div className="sec" style={{ marginTop: 14 }}>
      <div className="sec-head"><div className="sec-title"><span className="ico"><Icon name="target" size={16} /></span> Live public track record — excess vs SPY</div></div>
      <table className="clusters">
        <thead><tr><th>Bucket</th>{horizons.map((h) => <th key={h}>{h}d avg excess</th>)}<th>hit rate</th></tr></thead>
        <tbody>
          {buckets.map((b) => {
            const c90 = track.per_bucket?.[b]?.["90"] || {};
            return (
              <tr key={b}>
                <td><span className={`pill pill-${b}`}>{b}</span></td>
                {horizons.map((h) => { const c = track.per_bucket?.[b]?.[String(h)] || {}; return <td key={h} className={`num ${cls(c.mean_excess)}`}>{c.episodes ? pct(c.mean_excess) : "—"}</td>; })}
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
    <table className="clusters" style={{ marginTop: 10 }}>
      <thead><tr><th>Ticker</th><th>Signal</th><th>Return</th><th>vs SPY</th><th>Excess</th><th></th></tr></thead>
      <tbody>
        {p.positions.map((x) => (
          <tr key={x.id}>
            <td><button className="linkish sym" onClick={() => onOpenSymbol(x.symbol)}>{x.symbol}</button>{x.priced && <div className="name">{x.days_held}d held</div>}</td>
            <td>{x.has_signal ? <span className="att-xp"><Icon name="signal" size={11} /> live</span> : <span className="name">—</span>}</td>
            {x.priced ? (
              <>
                <td className={`num ${cls(x.return)}`}>{pct(x.return)}</td>
                <td className="num">{pct(x.spy_return)}</td>
                <td className={`num ${cls(x.excess)}`}>{pct(x.excess)}</td>
              </>
            ) : <td colSpan={3} className="name">pending — no priceable window yet</td>}
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
  const [open, setOpen] = useState(null);
  const [sym, setSym] = useState("");
  const [busy, setBusy] = useState(false);

  const loadList = () => fetchPortfolios().then((d) => { setAuthed(d.authenticated); setList(d.portfolios || []); });
  useEffect(() => { fetchTrackRecord().then(setTrack).catch(() => {}); loadList().catch(() => setAuthed(false)); }, [user]);

  const shadowSignals = async () => { setBusy(true); const c = await createPortfolio("Shadow high-conviction", "shadow_bucket", ["high", "medium"]); await loadList(); if (c.id) setOpen(await getPortfolio(c.id)); setBusy(false); };
  const newManual = async () => { const c = await createPortfolio("My picks", "manual"); await loadList(); if (c.id) setOpen(await getPortfolio(c.id)); };
  const openOne = async (id) => setOpen(await getPortfolio(id));
  const add = async () => { if (!sym.trim() || !open) return; await addPosition(open.id, sym.trim().toUpperCase()); setSym(""); setOpen(await getPortfolio(open.id)); loadList(); };
  const remove = async (posId) => { await removePosition(open.id, posId); setOpen(await getPortfolio(open.id)); loadList(); };
  const del = async (id) => { await deletePortfolio(id); setOpen(null); loadList(); };

  return (
    <div>
      <div className="page-head">
        <div><h1 className="page-title">Portfolio</h1><p className="page-sub">Shadow the smart money as paper positions, tracked honestly against SPY — with a portfolio health read and concentration warnings. Never advice.</p></div>
      </div>

      {!authed ? (
        <>
          <TrackRecord track={track} />
          <div className="empty" style={{ marginTop: 14 }}>Log in to build shadow portfolios and track your own P&amp;L vs SPY.<div style={{ marginTop: 10 }}><button className="act" onClick={onLogin}>log in</button></div></div>
        </>
      ) : open ? (
        <div style={{ marginTop: 6 }}>
          <button className="issuer-back" onClick={() => setOpen(null)}><Icon name="arrow" size={15} style={{ transform: "scaleX(-1)" }} /> all portfolios</button>
          <div className="td-head"><span className="td-sym">{open.name}</span><span className="chip">{open.kind}</span></div>

          {open.summary.priced > 0 ? (
            <div className="pnl-summary">
              <span>portfolio <b className={`num ${cls(open.summary.avg_return)}`}>{pct(open.summary.avg_return)}</b></span>
              <span>SPY <b className="num">{pct(open.summary.spy_return)}</b></span>
              <span>excess <b className={`num ${cls(open.summary.avg_excess)}`}>{pct(open.summary.avg_excess)}</b></span>
              <span className="name">{open.summary.beat_spy}/{open.summary.priced} beat SPY · {open.summary.pending} pending</span>
            </div>
          ) : <div className="name" style={{ margin: "6px 0" }}>No priceable positions yet ({open.summary.pending} pending).</div>}

          {open.positions.length > 0 && <HealthCard summary={open.summary} />}
          {open.positions.length > 0 && <Allocation positions={open.positions} />}

          <div className="controls" style={{ marginTop: 10 }}>
            <input className="search" placeholder="add ticker…" value={sym} onChange={(e) => setSym(e.target.value)} onKeyDown={(e) => e.key === "Enter" && add()} />
            <button className="act" onClick={add}>add position</button>
            <button className="act" style={{ marginLeft: "auto" }} onClick={() => del(open.id)}>delete portfolio</button>
          </div>
          {open.positions.length > 0 && <PositionsTable p={open} onRemove={remove} onOpenSymbol={onOpenSymbol} />}
          <div className="disc" style={{ marginTop: 14 }}>Paper positions, equal-weight, priced from real EOD data vs SPY. Sector exposure, correlation, dividends, expected returns and stress tests need pricing/fundamental data that isn't wired yet — we show what's real and never fabricate the rest.</div>
        </div>
      ) : (
        <div style={{ marginTop: 6 }}>
          <div className="controls">
            <button className="act act-on" disabled={busy} onClick={shadowSignals}>{busy ? "building…" : "⚡ Shadow high-conviction signals"}</button>
            <button className="act" onClick={newManual}>+ new manual portfolio</button>
          </div>
          {list === null ? <div className="skel" style={{ width: "40%", marginTop: 12 }} />
            : list.length === 0 ? <div className="name" style={{ marginTop: 12 }}>No portfolios yet. Shadow the signals or start a manual one.</div>
            : (
              <table className="clusters" style={{ marginTop: 10 }}>
                <thead><tr><th>Portfolio</th><th>Health</th><th>Return</th><th>vs SPY</th><th>Excess</th><th>Positions</th></tr></thead>
                <tbody>
                  {list.map((p) => {
                    const h = health(p.summary);
                    return (
                      <tr className="row" key={p.id} onClick={() => openOne(p.id)}>
                        <td><div className="sym">{p.name}</div><div className="name">{p.kind}</div></td>
                        <td><span className={`pill pill-${h.band === "high" ? "high" : h.band === "medium" ? "medium" : "low"}`}>{h.score}</span></td>
                        <td className={`num ${cls(p.summary.avg_return)}`}>{pct(p.summary.avg_return)}</td>
                        <td className="num">{pct(p.summary.spy_return)}</td>
                        <td className={`num ${cls(p.summary.avg_excess)}`}>{pct(p.summary.avg_excess)}</td>
                        <td className="num">{p.summary.priced}<span className="name"> priced · {p.summary.pending} pending</span></td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          <TrackRecord track={track} />
        </div>
      )}
    </div>
  );
}
