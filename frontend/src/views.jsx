// Deep-dive, screener, and profile surfaces. Every figure carries its freshness; a filer is
// a link into its profile; nothing evaluates a user's position (the advice line).
import { useEffect, useState } from "react";
import { addFollow, addWatchlist, analyzeChartImage, authLogin, authRegister, extractTickers, fetchActivity, fetchAsset, fetchExplanation, fetchInsider, fetchInstitution, fetchLibrary, fetchLibraryEntry, fetchScreener, fetchWatchlist, removeWatchlist } from "./api";
import { Backtested, Disclaimer, Freshness } from "./components.jsx";
import { Icon } from "./icons.jsx";

function fmtDetail(o) {
  return Object.entries(o)
    .filter(([, v]) => v != null)
    .map(([k, v]) => `${k}=${typeof v === "number" ? v.toLocaleString() : v}`)
    .join("  ");
}

function Sparkline({ prices, markers }) {
  if (!prices || prices.length < 2) return <div className="name">no price history</div>;
  const w = 640, h = 90, pad = 4;
  const xs = prices.map((p) => new Date(p.day).getTime());
  const ys = prices.map((p) => p.close);
  const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
  const px = (t) => pad + ((t - x0) / (x1 - x0 || 1)) * (w - 2 * pad);
  const py = (v) => h - pad - ((v - y0) / (y1 - y0 || 1)) * (h - 2 * pad);
  const pts = prices.map((p) => `${px(new Date(p.day).getTime()).toFixed(1)},${py(p.close).toFixed(1)}`).join(" ");
  return (
    <svg className="spark" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none">
      <polyline points={pts} fill="none" stroke="#4c8dff" strokeWidth="1.5" />
      {(markers || []).map((m, i) => {
        const t = new Date(m.as_of).getTime();
        if (t < x0 || t > x1) return null;
        const x = px(t);
        const col = m.bucket === "high" ? "#3fb950" : m.bucket === "medium" ? "#d9a441" : "#6b7688";
        return <line key={i} x1={x} y1="0" x2={x} y2={h} stroke={col} strokeWidth="1" opacity="0.5" />;
      })}
    </svg>
  );
}

function ActivityTable({ items, onOpenProfile }) {
  return (
    <table className="clusters">
      <thead>
        <tr><th>Source</th><th>Actor</th><th>Detail</th><th>Event</th><th>Knowable</th><th>Freshness</th></tr>
      </thead>
      <tbody>
        {items.map((it, i) => (
          <tr key={i}>
            <td><span className={`chip ${it.source_class}`}>{it.source_class.replace(/_/g, " ")}</span></td>
            <td>
              {it.actor_id ? (
                <button className="linkish" onClick={() => onOpenProfile(it.actor_kind, it.actor_id)}>{it.actor}</button>
              ) : (it.actor || "—")}
            </td>
            <td className="name">{fmtDetail(it.detail)}</td>
            <td className="num">{it.event_time}</td>
            <td className="num">{it.knowable_time.slice(0, 10)}</td>
            <td><Freshness iso={it.knowable_time} quarterly={it.source_class === "institutional_holding"} /> <span className="name">lag {it.knowable_lag_days}d</span></td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function AssetView({ symbol, calibration, horizon, onOpenProfile, onBack }) {
  const [asset, setAsset] = useState(null);
  const [activity, setActivity] = useState(null);
  const [explanation, setExplanation] = useState(null);
  const [added, setAdded] = useState(false);
  const [err, setErr] = useState(null);

  useEffect(() => {
    setAsset(null); setActivity(null); setExplanation(null); setErr(null); setAdded(false);
    fetchAsset(symbol).then((a) => {
      setAsset(a);
      if (a.resolved && a.current_cluster) {
        fetchExplanation(a.entity.id, horizon).then(setExplanation).catch(() => {});
      }
    }).catch((e) => setErr(String(e)));
    fetchActivity(symbol).then(setActivity).catch(() => {});
  }, [symbol, horizon]);

  if (err) return <div className="err">error: {err}</div>;
  if (!asset) return <div className="detail"><div className="skel" style={{ width: 240 }} /></div>;
  if (!asset.resolved) return <div className="detail"><button className="back" onClick={onBack}>← back</button><div className="name" style={{ marginTop: 10 }}>“{asset.symbol}” is not a resolved issuer.</div></div>;

  const cur = asset.current_cluster;
  const cal = cur && calibration?.per_bucket?.[cur.bucket]?.[String(horizon)];
  const st = asset.name_stats;
  return (
    <div className="detail">
      <button className="back" onClick={onBack}>← back to dashboard</button>
      <h2>
        {asset.symbol} · {asset.entity.name}
        <button className="shot-btn" style={{ fontSize: 11, marginLeft: 10, verticalAlign: "middle" }}
                onClick={async () => { await addWatchlist(asset.symbol); setAdded(true); }}>
          {added ? "on watchlist ✓" : "+ watchlist"}
        </button>
      </h2>
      <div className="meta">CIK {asset.entity.cik} · deep dive</div>

      {cur ? (
        <div style={{ margin: "6px 0 10px" }}>
          latest cluster: <b className="num">{cur.score.toFixed(2)}</b>{" "}
          <span className={`bucket ${cur.bucket}`}>{cur.bucket.toUpperCase()}</span>{" "}
          <span className="name">as of {cur.as_of.slice(0, 10)}</span> · <Backtested cal={cal} />
        </div>
      ) : <div className="name" style={{ margin: "6px 0" }}>no active convergence cluster on this name right now.</div>}

      <div className="section">Price (last ~6 months) · vertical marks = cluster days</div>
      <Sparkline prices={asset.prices} markers={asset.cluster_history} />
      <div className="name" style={{ marginTop: 4 }}>
        This name’s own backtested record (30d):{" "}
        {st.sufficient ? `${Math.round(st.hit_rate_30d * 100)}% across ${st.episodes_30d} episodes`
                       : `insufficient sample (${st.episodes_30d} episodes)`}
      </div>

      {explanation && (
        <div className="explain">
          <div className="section">Plain-language explanation</div>
          <p className="explain-prose">{explanation.prose}</p>
          <div className="name">generated by {explanation.model_id}{explanation.used_template ? " · guard fallback" : ""}</div>
        </div>
      )}

      <div className="section">Merged disclosure activity (point-in-time)</div>
      {activity && activity.resolved
        ? <ActivityTable items={activity.activity} onOpenProfile={onOpenProfile} />
        : <div className="skel" style={{ width: "60%" }} />}
      <Disclaimer />
    </div>
  );
}

export function Screener({ onOpenSymbol }) {
  const [minC, setMinC] = useState("low");
  const [cls, setCls] = useState("");
  const [data, setData] = useState(null);
  useEffect(() => { setData(null); fetchScreener(minC, cls).then(setData).catch(() => setData({ clusters: [] })); }, [minC, cls]);
  const CLASSES = ["", "insider", "activist", "passive_stake", "institutional_holding"];
  return (
    <div>
      <div className="controls">
        <div className="seg">{["low", "medium", "high"].map((b) => <button key={b} className={minC === b ? "on" : ""} onClick={() => setMinC(b)}>{b}+</button>)}</div>
        <div className="seg">{CLASSES.map((c) => <button key={c || "any"} className={cls === c ? "on" : ""} onClick={() => setCls(c)}>{c ? c.replace(/_/g, " ") : "any"}</button>)}</div>
      </div>
      {minC === "low" && (
        <div className="warn">Showing sub-floor / low-confidence clusters. Thinly-traded or below-liquidity-floor names are the cheapest to manipulate — treat low-bucket clusters with caution.</div>
      )}
      {data === null ? <div className="skel" style={{ width: "50%", marginTop: 12 }} />
        : data.clusters.length === 0 ? <div className="name" style={{ marginTop: 12 }}>no matching clusters.</div>
        : (
          <table className="clusters">
            <thead><tr><th>Ticker</th><th>Score</th><th>Confidence</th><th>Voices</th><th>Sources</th></tr></thead>
            <tbody>
              {data.clusters.map((c) => (
                <tr className="row" key={c.issuer_entity} onClick={() => c.symbol && onOpenSymbol(c.symbol)}>
                  <td><div className="sym">{c.symbol || "—"}</div><div className="name">{c.name}</div></td>
                  <td className="score num">{c.score.toFixed(2)}</td>
                  <td><span className={`bucket ${c.confidence_bucket}`}>{c.confidence_bucket.toUpperCase()}</span></td>
                  <td className="num">{c.voices}</td>
                  <td><div className="chips">{c.source_classes.map((s) => <span key={s} className={`chip ${s}`}>{s.replace(/_/g, " ")}</span>)}</div></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      <Disclaimer />
    </div>
  );
}

function _esc(s) { return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"); }
function renderMd(md) {
  return (md || "").split(/\n\n+/).map((p, i) => (
    <p key={i} className="lib-p" dangerouslySetInnerHTML={{ __html: _esc(p).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>") }} />
  ));
}

function ScreenshotImport({ onAdd }) {
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [chosen, setChosen] = useState({});
  const onFile = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setBusy(true); setResult(null);
    try {
      const r = await extractTickers(file);
      setResult(r);
      setChosen(Object.fromEntries((r.recognized || []).map((s) => [s, true])));
    } catch { setResult({ error: "extraction failed; type symbols manually", recognized: [], unrecognized: [] }); }
    setBusy(false);
    e.target.value = ""; // never keep the file around
  };
  return (
    <div className="shot">
      <label className="shot-btn">
        {busy ? "reading…" : "import from screenshot"}
        <input type="file" accept="image/png,image/jpeg,image/webp" onChange={onFile} hidden />
      </label>
      <span className="name"> paste a brokerage screenshot — we read tickers only, never prices or positions, and never store the image.</span>
      {result && (
        <div style={{ marginTop: 8 }}>
          {result.error && <div className="warn">{result.error}</div>}
          {(result.recognized || []).length > 0 && (
            <>
              <div className="name">Confirm the symbols to add:</div>
              <div className="chips" style={{ margin: "6px 0" }}>
                {result.recognized.map((s) => (
                  <button key={s} className={`chip ${chosen[s] ? "chip-on" : "chip-off"}`} onClick={() => setChosen((c) => ({ ...c, [s]: !c[s] }))}>
                    {s} {chosen[s] ? "✓" : "+"}
                  </button>
                ))}
              </div>
              <button className="shot-btn" onClick={() => onAdd(Object.keys(chosen).filter((s) => chosen[s]))}>add selected to watchlist</button>
            </>
          )}
          {(result.unrecognized || []).length > 0 && (
            <div className="name" style={{ marginTop: 6 }}>Not recognized (ignored): {result.unrecognized.join(", ")}</div>
          )}
          {result.recognized && result.recognized.length === 0 && !result.error && (
            <div className="name">No known tickers found. Type a symbol above instead.</div>
          )}
        </div>
      )}
    </div>
  );
}

const wBand = (n) => (n >= 70 ? "high" : n >= 45 ? "med" : "low");
const SENT = (v) => (v == null ? null : v > 0.2 ? ["bull", "bullish"] : v < -0.2 ? ["bear", "bearish"] : ["neutral", "mixed"]);

function WatchChartAnalyzer() {
  const [read, setRead] = useState(null);
  const [busy, setBusy] = useState(false);
  const analyze = async (file) => { if (!file) return; setBusy(true); const d = await analyzeChartImage(file).catch(() => null); setRead(d?.analysis || { error: true }); setBusy(false); };
  return (
    <div className="watch-analyzer">
      <label className="watch-analyzer-btn">
        <Icon name="sparkles" size={15} /> {busy ? "reading chart…" : "Analyze a chart screenshot"}
        <input type="file" accept="image/png,image/jpeg,image/webp" hidden disabled={busy} onChange={(e) => analyze(e.target.files[0])} />
      </label>
      {read && !read.error && (read.pattern || read.structure) && (
        <div className="chart-read" style={{ marginTop: 10 }}>
          <div className="chart-read-head"><Icon name="sparkles" size={14} /> What the AI saw <span className={`ai-tag ${read.source === "ai" ? "ai-on" : ""}`}>{read.source === "ai" ? "✦ AI vision" : "levels only"}</span></div>
          {read.pattern && <div className="ca-row"><span className="ca-l">Pattern</span> {read.pattern}</div>}
          {read.structure && <p className="an-prose" style={{ margin: "6px 0" }}>{read.structure}</p>}
          {(read.observations || []).length > 0 && <ul className="an-list" style={{ marginTop: 4 }}>{read.observations.slice(0, 3).map((o, i) => <li key={i}>{o}</li>)}</ul>}
          <div className="disc" style={{ marginTop: 6 }}>Educational read of the chart, not advice.</div>
        </div>
      )}
      {read?.error && <div className="name" style={{ marginTop: 8 }}>Couldn't read that image right now.</div>}
    </div>
  );
}

function WatchCard({ w, onOpenSymbol, onRemove }) {
  const conv = w.conviction;
  const sm = w.smart_money, att = w.attention;
  const sent = att ? SENT(att.sentiment) : null;
  return (
    <div className="watch-card">
      <button className={`opp-score band-${conv ? wBand(conv.score) : "low"}`} onClick={() => onOpenSymbol(w.symbol)}>
        <b>{conv ? conv.score : "—"}</b><span>CONVICTN</span>
      </button>
      <div className="watch-body">
        <div className="watch-head">
          <button className="opp-sym linkish" onClick={() => onOpenSymbol(w.symbol)}>{w.symbol}</button>
          <span className="opp-name">{w.name || (w.resolved ? "" : "unresolved ticker")}</span>
          <span className="spacer" style={{ flex: 1 }} />
          <button className="linkish" style={{ color: "var(--muted)", fontSize: 12 }} onClick={() => onRemove(w.symbol)}>remove</button>
        </div>
        <div className="watch-scores">
          <span className="wscore"><i>Smart money</i>{sm ? <b className={`band-${wBand(sm.score)}`}>{sm.score}</b> : <b className="wna">—</b>}</span>
          <span className="wscore"><i>Social</i>{att ? <b className={`band-${wBand(att.score)}`}>{att.score}</b> : <b className="wna">—</b>}{att?.velocity ? <em>{att.velocity}×</em> : null}</span>
          {sent && <span className={`sent sent-${sent[0]}`}>{sent[1]}</span>}
          {w.cluster && <span className={`bucket ${w.cluster.bucket}`}>{w.cluster.bucket.toUpperCase()}</span>}
        </div>
        {w.news && <a className="watch-news" href={w.news.url} target="_blank" rel="noreferrer"><span className={`related-impact band-${w.news.impact >= 60 ? "high" : w.news.impact >= 35 ? "medium" : "low"}`}>{w.news.impact}</span> {w.news.headline}</a>}
        {w.next_event && <div className="watch-event"><Icon name="calendar" size={12} /> next: {(w.next_event.title || "earnings").replace(/ earnings$/i, " earnings")} · {new Date(w.next_event.date + "T00:00:00").toLocaleDateString(undefined, { month: "short", day: "numeric" })}</div>}
      </div>
    </div>
  );
}

export function WatchlistView({ onOpenSymbol, onLogin }) {
  const [data, setData] = useState(null);
  const [sym, setSym] = useState("");
  const load = () => fetchWatchlist().then(setData).catch(() => setData({ watchlist: [] }));
  useEffect(() => { load(); }, []);
  // The watchlist is now per-account (bug B-22 — it used to be one shared list keyed by a query
  // parameter), so a logged-out reader gets an invitation rather than someone else's names.
  if (data && data.authenticated === false) {
    return (
      <div>
        <div className="page-head"><div><h1 className="page-title">Watchlist</h1></div></div>
        <div className="empty" style={{ marginTop: 14 }}>
          Log in to keep a watchlist. Names you watch also sharpen how the Radar ranks events for you.
          <div style={{ marginTop: 10 }}><button className="act" onClick={onLogin}>log in</button></div>
        </div>
      </div>
    );
  }
  const add = async (s) => { if (s) { await addWatchlist(s); load(); } };
  const addMany = async (arr) => { for (const s of arr) await addWatchlist(s); load(); };
  const remove = async (s) => { await removeWatchlist(s); load(); };
  return (
    <div>
      <div className="page-head">
        <div><h1 className="page-title">Watchlist</h1><p className="page-sub">Names to watch, each scored on what's real — smart-money conviction, public attention, fresh news and the next catalyst. Add by ticker or from a screenshot.</p></div>
      </div>
      <div className="controls" style={{ marginTop: 4 }}>
        <input className="search" style={{ width: 150 }} placeholder="add ticker…" value={sym}
               onChange={(e) => setSym(e.target.value)}
               onKeyDown={(e) => { if (e.key === "Enter") { add(sym.trim().toUpperCase()); setSym(""); } }} />
        <button className="act act-on" onClick={() => { add(sym.trim().toUpperCase()); setSym(""); }}>add</button>
      </div>
      <ScreenshotImport onAdd={addMany} />
      <WatchChartAnalyzer />
      {!data ? <div className="skel" style={{ width: "50%", marginTop: 14 }} />
        : data.watchlist.length === 0 ? <div className="empty" style={{ marginTop: 12 }}>Your watchlist is empty. Add a ticker above, or import from a screenshot.</div>
        : <div className="watch-grid">{data.watchlist.map((w) => <WatchCard key={w.symbol} w={w} onOpenSymbol={onOpenSymbol} onRemove={remove} />)}</div>}
      <div className="disc" style={{ marginTop: 16 }}>Conviction blends the two real per-name scores we have — smart-money and public attention. We don't compute technical, fundamental or momentum ratings and never fake them. Not investment advice.</div>
    </div>
  );
}

export function AuthPanel({ onAuthed, onBack, initialInvite }) {
  const [mode, setMode] = useState(initialInvite ? "register" : "login");
  const [email, setEmail] = useState("");
  const [pw, setPw] = useState("");
  const [invite, setInvite] = useState(initialInvite || "");
  const [totp, setTotp] = useState("");
  const [err, setErr] = useState(null);
  const submit = async () => {
    setErr(null);
    const r = mode === "login" ? await authLogin(email, pw, totp) : await authRegister(email, pw, invite);
    if (r.error) { setErr(r.error); return; }
    onAuthed(r.user);
  };
  return (
    <div className="detail" style={{ maxWidth: 440 }}>
      <button className="back" onClick={onBack}>← back</button>
      <h2>{mode === "login" ? "Log in" : "Create account"}</h2>
      <div className="meta">Invite-only. Free tier sees signals on a 48-hour delay; paid tiers see them live.</div>
      {initialInvite && mode === "register" && <div className="warn" style={{ borderColor: "#2f4a2f", color: "var(--green)", background: "#0f2417" }}>You were referred — register to start a 14-day Pro trial free.</div>}
      <div className="auth-form">
        <input className="search" style={{ width: "100%" }} placeholder="email" value={email} onChange={(e) => setEmail(e.target.value)} />
        <input className="search" style={{ width: "100%" }} type="password" placeholder="password (10+ chars)" value={pw} onChange={(e) => setPw(e.target.value)} />
        {mode === "register" && <input className="search" style={{ width: "100%" }} placeholder="invite or referral code" value={invite} onChange={(e) => setInvite(e.target.value)} />}
        {mode === "login" && <input className="search" style={{ width: "100%" }} placeholder="TOTP code (admins only)" value={totp} onChange={(e) => setTotp(e.target.value)} />}
        <button className="shot-btn" onClick={submit}>{mode === "login" ? "log in" : "register"}</button>
        {err && <div className="warn">{err}</div>}
        <button className="linkish" onClick={() => { setMode(mode === "login" ? "register" : "login"); setErr(null); }}>
          {mode === "login" ? "have an invite? create an account" : "already have an account? log in"}
        </button>
      </div>
      <Disclaimer />
    </div>
  );
}

export function LibraryView({ onOpenEntry }) {
  const [data, setData] = useState(null);
  useEffect(() => { fetchLibrary().then(setData).catch(() => setData({ entries: [] })); }, []);
  if (!data) return <div className="detail"><div className="skel" style={{ width: 220 }} /></div>;
  const groups = { concept: [], investor_profile: [] };
  data.entries.forEach((e) => (groups[e.kind] || (groups[e.kind] = [])).push(e));
  const Section = ({ title, items }) => (
    <>
      <div className="section">{title}</div>
      <div className="lib-grid">
        {items.map((e) => (
          <button key={e.slug} className="lib-card" onClick={() => onOpenEntry(e.slug)}>
            <div className="lib-title">{e.title}</div>
            {e.review_status !== "published" && <span className="lib-draft">draft</span>}
          </button>
        ))}
      </div>
    </>
  );
  return (
    <div className="detail">
      <h2>Intelligence library</h2>
      <div className="meta">{data.note}</div>
      <Section title="Concepts & methodology" items={groups.concept || []} />
      <Section title="Investor profiles" items={groups.investor_profile || []} />
      <Disclaimer />
    </div>
  );
}

export function LibraryEntry({ slug, onBack, onOpenLibrary }) {
  const [e, setE] = useState(null);
  useEffect(() => { setE(null); fetchLibraryEntry(slug).then(setE).catch(() => setE({ found: false })); }, [slug]);
  if (!e) return <div className="detail"><div className="skel" style={{ width: 240 }} /></div>;
  if (e.found === false) return <div className="detail"><button className="back" onClick={onBack}>← back</button><div className="name" style={{ marginTop: 10 }}>entry not found.</div></div>;
  return (
    <div className="detail">
      <button className="back" onClick={onBack}>← back to library</button>
      <h2>{e.title}</h2>
      <div className="meta">{e.kind.replace("_", " ")}{e.review_status !== "published" ? " · draft (pending founder review)" : ""}</div>
      <div className="lib-body">{renderMd(e.body_md)}</div>
      <div className="section">Sources</div>
      <ul className="lib-sources">
        {(e.sources || []).map((s, i) => (
          <li key={i}><a href={s.url} target="_blank" rel="noreferrer">{s.title}</a> <span className="name">· {s.basis.replace(/_/g, " ")}</span></li>
        ))}
      </ul>
      <Disclaimer />
    </div>
  );
}

export function ProfileView({ kind, id, user, onOpenSymbol, onBack }) {
  const [data, setData] = useState(null);
  const [followed, setFollowed] = useState(false);
  useEffect(() => {
    setData(null); setFollowed(false);
    (kind === "insider" ? fetchInsider(id) : fetchInstitution(id)).then(setData).catch(() => setData({ found: false }));
  }, [kind, id]);
  if (!data) return <div className="detail"><div className="skel" style={{ width: 220 }} /></div>;
  if (data.found === false) return <div className="detail"><button className="back" onClick={onBack}>← back</button><div className="name" style={{ marginTop: 10 }}>profile not found.</div></div>;

  const doFollow = async () => {
    if (kind === "insider") await addFollow("insider", data.owner_cik, data.name);
    else await addFollow("filer", String(id), data.name);
    setFollowed(true);
  };
  const Sym = ({ s }) => s ? <button className="linkish" onClick={() => onOpenSymbol(s)}>{s}</button> : <span>—</span>;
  return (
    <div className="detail">
      <button className="back" onClick={onBack}>← back</button>
      <h2>
        {data.name}
        {user && <button className="act" style={{ marginLeft: 10, fontSize: 12, verticalAlign: "middle" }} onClick={doFollow}>{followed ? "following ✓" : "+ follow"}</button>}
      </h2>
      <div className="meta">{kind === "insider" ? `insider · CIK ${data.owner_cik}` : `${data.kind} · CIK ${data.cik}`} · positioning from public filings only</div>

      {kind === "insider" ? (
        <table className="clusters">
          <thead><tr><th>Issuer</th><th>Code</th><th>A/D</th><th>Shares</th><th>Price</th><th>Knowable</th></tr></thead>
          <tbody>{data.transactions.map((t, i) => (
            <tr key={i}><td><Sym s={t.symbol} /> <span className="name">{t.issuer}</span></td>
              <td className="num">{t.transaction_code}</td><td className="num">{t.acquired_disposed}</td>
              <td className="num">{t.shares?.toLocaleString() ?? "—"}</td><td className="num">{t.price_per_share ?? "—"}</td>
              <td><Freshness iso={t.knowable_time} /></td></tr>
          ))}</tbody>
        </table>
      ) : (
        <>
          <div className="section">Recent stake filings</div>
          <table className="clusters"><thead><tr><th>Issuer</th><th>Form</th><th>Event</th><th>Knowable</th></tr></thead>
            <tbody>{data.stakes.map((s, i) => (
              <tr key={i}><td><Sym s={s.symbol} /> <span className="name">{s.issuer}</span></td><td className="num">{s.form_type}</td>
                <td className="num">{s.event_time}</td><td><Freshness iso={s.knowable_time} /></td></tr>
            ))}</tbody></table>
          <div className="section">Top 13F holdings (latest quarter)</div>
          <table className="clusters"><thead><tr><th>Issuer</th><th>Value USD</th><th>Shares</th><th>Freshness</th></tr></thead>
            <tbody>{data.top_holdings.map((h, i) => (
              <tr key={i}><td><Sym s={h.symbol} /> <span className="name">{h.issuer}</span></td>
                <td className="num">{h.value_usd?.toLocaleString() ?? "—"}</td><td className="num">{h.shares?.toLocaleString() ?? "—"}</td>
                <td><Freshness iso={h.knowable_time} quarterly /></td></tr>
            ))}</tbody></table>
        </>
      )}
      <Disclaimer />
    </div>
  );
}
