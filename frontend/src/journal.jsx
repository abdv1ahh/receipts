// Slice E: your trades. Log a trade, get a guarded educational analysis (cross-referenced against
// the real smart-money signal), and see honest personal analytics — win rate and habits appear only
// once the sample is real, never inferred from a handful of trades. The analysis is guarded on the
// server (no advice language, no invented numbers); the UI renders only what it returns.
import { useEffect, useState } from "react";
import {
  createTrade, deleteTrade, extractTickers, fetchPerformance, fetchTrades, fetchTradeAnalysis,
  getTrade, updateTrade, uploadTradeImage,
} from "./api";

const pct = (v) => (v == null ? "—" : `${v >= 0 ? "+" : ""}${(v * 100).toFixed(1)}%`);
const cls = (v) => (v == null ? "" : v > 0 ? "pos-pos" : v < 0 ? "pos-neg" : "");
const money = (v) => (v == null ? "—" : `$${(+v).toLocaleString(undefined, { maximumFractionDigits: 2 })}`);
const DIRS = ["long", "short"];
const ASSETS = ["equity", "crypto", "forex", "option", "future", "other"];
const STATUSES = ["planned", "open", "closed"];
const UNITS = ["shares", "contracts", "usd", "units", "lots"];

const BLANK = {
  symbol: "", asset_class: "equity", direction: "long", status: "planned", entry_price: "",
  exit_price: "", stop_price: "", target_price: "", size: "", size_unit: "shares", timeframe: "",
  strategy: "", reason_entry: "", reason_exit: "", confidence: "", expected_outcome: "",
  opened_on: "", closed_on: "", is_public: false,
};

function toPayload(f) {
  const num = (x) => (x === "" || x == null ? null : Number(x));
  return {
    ...f, symbol: f.symbol || null, entry_price: num(f.entry_price), exit_price: num(f.exit_price),
    stop_price: num(f.stop_price), target_price: num(f.target_price), size: num(f.size),
    confidence: f.confidence ? Number(f.confidence) : null, timeframe: f.timeframe || null,
    strategy: f.strategy || null, reason_entry: f.reason_entry || null, reason_exit: f.reason_exit || null,
    expected_outcome: f.expected_outcome || null, opened_on: f.opened_on || null, closed_on: f.closed_on || null,
  };
}

// A returned trade dict -> the editable form shape (for edit + publish toggle, which PATCH-replace).
function editableFrom(t) {
  const g = (k) => (t[k] == null ? "" : t[k]);
  return {
    symbol: g("symbol"), asset_class: t.asset_class, direction: t.direction, status: t.status,
    entry_price: g("entry_price"), exit_price: g("exit_price"), stop_price: g("stop_price"),
    target_price: g("target_price"), size: g("size"), size_unit: t.size_unit, timeframe: g("timeframe"),
    strategy: g("strategy"), reason_entry: g("reason_entry"), reason_exit: g("reason_exit"),
    confidence: g("confidence"), expected_outcome: g("expected_outcome"),
    opened_on: t.opened_on ? t.opened_on.slice(0, 10) : "", closed_on: t.closed_on ? t.closed_on.slice(0, 10) : "",
    is_public: t.is_public,
  };
}

function TradeForm({ initial, onSaved, onCancel }) {
  const [f, setF] = useState(() => initial || BLANK);
  const [img, setImg] = useState(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const set = (k) => (e) => setF((s) => ({ ...s, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value }));

  const scan = async () => {
    if (!img) { setMsg("choose a screenshot first"); return; }
    setMsg("scanning…");
    try {
      const d = await extractTickers(img);
      const sym = (d.recognized || [])[0] || (d.unrecognized || [])[0];
      if (sym) { setF((s) => ({ ...s, symbol: sym })); setMsg(`found ${sym}`); }
      else setMsg(d.provider_available ? "no ticker found in image" : "screenshot scanning needs the vision model");
    } catch { setMsg("could not scan that image"); }
  };

  const save = async () => {
    setBusy(true); setMsg("");
    const payload = toPayload(f);
    let id = initial?.id, res;
    if (id) res = await updateTrade(id, payload);
    else { res = await createTrade(payload); id = res.id; }
    if (res.error) { setMsg(res.error); setBusy(false); return; }
    if (img && id) await uploadTradeImage(id, img);
    setBusy(false);
    onSaved(id);
  };

  const L = (label, node) => <label className="fld"><span>{label}</span>{node}</label>;
  const inp = (k, extra = {}) => <input value={f[k]} onChange={set(k)} {...extra} />;
  const sel = (k, opts) => <select value={f[k]} onChange={set(k)}>{opts.map((o) => <option key={o} value={o}>{o || "—"}</option>)}</select>;

  return (
    <div className="trade-form">
      <div className="form-grid">
        {L("Ticker / asset", <div className="sym-row">{inp("symbol", { placeholder: "NVDA", style: { textTransform: "uppercase" } })}<button type="button" className="act mini" onClick={scan}>scan 📎</button></div>)}
        {L("Asset class", sel("asset_class", ASSETS))}
        {L("Direction", sel("direction", DIRS))}
        {L("Status", sel("status", STATUSES))}
        {L("Entry", inp("entry_price", { type: "number", step: "any", placeholder: "165" }))}
        {L("Exit", inp("exit_price", { type: "number", step: "any" }))}
        {L("Stop-loss", inp("stop_price", { type: "number", step: "any", placeholder: "155" }))}
        {L("Profit target", inp("target_price", { type: "number", step: "any", placeholder: "180" }))}
        {L("Size", inp("size", { type: "number", step: "any" }))}
        {L("Unit", sel("size_unit", UNITS))}
        {L("Timeframe", inp("timeframe", { placeholder: "swing / day / position" }))}
        {L("Strategy", inp("strategy", { placeholder: "breakout" }))}
        {L("Confidence", sel("confidence", ["", "1", "2", "3", "4", "5"]))}
        {L("Opened", inp("opened_on", { type: "date" }))}
        {L("Closed", inp("closed_on", { type: "date" }))}
        {L("Screenshot", <input type="file" accept="image/png,image/jpeg,image/webp" onChange={(e) => setImg(e.target.files[0])} />)}
      </div>
      {L("Reason for entering", <textarea value={f.reason_entry} onChange={set("reason_entry")} rows={2} placeholder="AI earnings momentum + technical breakout" />)}
      {L("Reason for exiting", <textarea value={f.reason_exit} onChange={set("reason_exit")} rows={2} />)}
      {L("Expected outcome", <textarea value={f.expected_outcome} onChange={set("expected_outcome")} rows={2} />)}
      <label className="fld-check"><input type="checkbox" checked={f.is_public} onChange={set("is_public")} /><span>Make this trade public on my profile</span></label>
      <div className="controls" style={{ marginTop: 6 }}>
        <button className="act act-on" disabled={busy} onClick={save}>{busy ? "saving…" : (initial?.id ? "save changes" : "log trade")}</button>
        <button className="act" onClick={onCancel}>cancel</button>
        {msg && <span className="name" style={{ marginLeft: 6 }}>{msg}</span>}
      </div>
    </div>
  );
}

function TradeCard({ t, onOpen }) {
  return (
    <button className="trade-card" onClick={() => onOpen(t.id)}>
      <div className="tc-top">
        <span className="tc-sym">{t.symbol || "idea"}</span>
        <span className={`chip chip-${t.direction}`}>{t.direction}</span>
        <span className={`chip s-${t.status}`}>{t.status}</span>
        <span className="tc-flags">{t.is_public ? "🌐" : ""}{t.has_image ? "📎" : ""}</span>
      </div>
      <div className="name tc-strat">{t.asset_class}{t.strategy ? ` · ${t.strategy}` : ""}</div>
      <div className="tc-stats">
        <span>entry <b>{money(t.entry_price)}</b></span>
        {t.status === "closed"
          ? <span>P&amp;L <b className={cls(t.realized_pnl_pct)}>{pct(t.realized_pnl_pct)}</b></span>
          : <span>target <b>{money(t.target_price)}</b></span>}
        <span>R:R <b>{t.reward_risk != null ? `${t.reward_risk}:1` : "—"}</b></span>
      </div>
    </button>
  );
}

function Section({ title, items, warn }) {
  return (
    <div className="an-sec">
      <div className="an-title">{title}</div>
      <ul className={warn ? "an-list warn" : "an-list"}>{items.map((s, i) => <li key={i}>{s}</li>)}</ul>
    </div>
  );
}

export function AnalysisPanel({ id, onOpenLibrary }) {
  const [a, setA] = useState(null);
  useEffect(() => { setA(null); fetchTradeAnalysis(id).then((d) => setA(d.analysis || null)).catch(() => {}); }, [id]);
  if (!a) return <div className="analysis"><div className="skel" style={{ width: "70%" }} /></div>;
  const model = a.used_template ? "TradeOS rules" : a.model_id;
  return (
    <div className="analysis">
      <div className="an-head">🧠 Analysis <span className="name">· educational, not advice</span></div>
      {a.prose && <p className="an-prose">{a.prose}</p>}
      {a.observations?.length > 0 && <Section title="Observations" items={a.observations} />}
      {a.risk_flags?.length > 0 && <Section title="Risk" items={a.risk_flags} warn />}
      {a.context?.length > 0 && <Section title="Smart-money context" items={a.context} />}
      {a.learn?.length > 0 && (
        <div className="an-sec">
          <div className="an-title">Learn the pattern</div>
          <div className="an-learn">{a.learn.map((l) => <button key={l.slug} className="pill pill-link" onClick={() => onOpenLibrary?.(l.slug)}>{l.title}</button>)}</div>
        </div>
      )}
      <div className="an-foot">Generated by {model}. Descriptive context and risk framing only — never advice about any position.</div>
    </div>
  );
}

function TradeDetail({ id, onBack, onEdit, onChanged, onOpenSymbol, onOpenLibrary }) {
  const [d, setD] = useState(null);
  const load = () => getTrade(id).then(setD);
  useEffect(() => { load(); }, [id]);
  if (!d) return <div className="skel" style={{ width: "50%" }} />;
  if (!d.found) return <><button className="back" onClick={onBack}>← journal</button><div className="empty" style={{ marginTop: 12 }}>Trade not found or private.</div></>;
  const t = d.trade, owner = d.owner;
  const togglePublish = async () => { await updateTrade(id, toPayload({ ...editableFrom(t), is_public: !t.is_public })); load(); onChanged?.(); };
  const del = async () => { if (!window.confirm("Delete this trade?")) return; await deleteTrade(id); onChanged?.(); onBack(); };
  const kv = (label, val) => <div className="kv"><span className="kv-l">{label}</span><span className="kv-v">{val}</span></div>;

  return (
    <>
      <button className="back" onClick={onBack}>← journal</button>
      <div className="td-head">
        <button className="linkish sym td-sym" onClick={() => t.symbol && onOpenSymbol(t.symbol)}>{t.symbol || "untitled idea"}</button>
        <span className={`chip chip-${t.direction}`}>{t.direction}</span>
        <span className={`chip s-${t.status}`}>{t.status}</span>
        <span className="chip">{t.asset_class}</span>
        {owner && <span className="chip">{t.is_public ? "🌐 public" : "🔒 private"}</span>}
      </div>
      {t.has_image && <img className="td-img" src={`/api/trades/${id}/image`} alt="trade screenshot" />}
      <div className="kv-grid">
        {kv("Entry", money(t.entry_price))}
        {kv("Exit", money(t.exit_price))}
        {kv("Stop-loss", money(t.stop_price))}
        {kv("Profit target", money(t.target_price))}
        {kv("Size", t.size != null ? `${t.size} ${t.size_unit}` : "—")}
        {kv("Reward : Risk", t.reward_risk != null ? `${t.reward_risk} : 1` : "—")}
        {t.status === "closed" && kv("Realized P&L", <span className={cls(t.realized_pnl_pct)}>{pct(t.realized_pnl_pct)}</span>)}
        {kv("Confidence", t.confidence ? `${t.confidence} / 5` : "—")}
        {kv("Timeframe", t.timeframe || "—")}
        {kv("Strategy", t.strategy || "—")}
      </div>
      {(t.reason_entry || t.reason_exit || t.expected_outcome) && (
        <div className="reasons">
          {t.reason_entry && <p><b>Why entered:</b> {t.reason_entry}</p>}
          {t.reason_exit && <p><b>Why exited:</b> {t.reason_exit}</p>}
          {t.expected_outcome && <p><b>Expected:</b> {t.expected_outcome}</p>}
        </div>
      )}
      <AnalysisPanel id={id} onOpenLibrary={onOpenLibrary} />
      {owner && (
        <div className="controls" style={{ marginTop: 12 }}>
          <button className="act" onClick={() => onEdit(t)}>edit</button>
          <button className="act" onClick={togglePublish}>{t.is_public ? "make private" : "publish to profile"}</button>
          <button className="act td-del" onClick={del}>delete</button>
        </div>
      )}
    </>
  );
}

function Stat({ label, value, c }) {
  return <div className="stat"><div className={`stat-v ${c || ""}`}>{value}</div><div className="stat-l">{label}</div></div>;
}

function PerformancePanel({ perf }) {
  if (!perf) return <div className="skel" style={{ width: "50%", marginTop: 14 }} />;
  if (perf.authenticated === false) return null;
  const s = perf.summary;
  if (!s.sufficient) {
    return (
      <div className="perf">
        <div className="perf-row">
          <Stat label="closed trades" value={s.n_closed} />
          <Stat label="wins" value={s.wins} c="pos-pos" />
          <Stat label="losses" value={s.losses} c="pos-neg" />
        </div>
        <div className="empty" style={{ marginTop: 12 }}>{s.note}</div>
      </div>
    );
  }
  return (
    <div className="perf">
      <div className="perf-row">
        <Stat label="win rate" value={`${Math.round(s.win_rate * 100)}%`} />
        <Stat label="expectancy / trade" value={pct(s.expectancy)} c={cls(s.expectancy)} />
        <Stat label="avg win" value={pct(s.avg_win)} c="pos-pos" />
        <Stat label="avg loss" value={pct(s.avg_loss)} c="pos-neg" />
        <Stat label="avg R:R" value={s.avg_reward_risk != null ? `${s.avg_reward_risk}:1` : "—"} />
        <Stat label="closed" value={s.n_closed} />
      </div>
      {s.insights?.length > 0 && <div className="insights">{s.insights.map((t, i) => <div key={i} className="insight">💡 {t}</div>)}</div>}
      {s.by_strategy?.length > 0 && (
        <table className="clusters" style={{ marginTop: 12 }}>
          <thead><tr><th>Strategy</th><th>Trades</th><th>Win rate</th><th>Avg return</th></tr></thead>
          <tbody>{s.by_strategy.map((r) => (
            <tr key={r.strategy}><td>{r.strategy}</td><td className="num">{r.n}</td><td className="num">{Math.round(r.win_rate * 100)}%</td><td className={`num ${cls(r.avg_return)}`}>{pct(r.avg_return)}</td></tr>
          ))}</tbody>
        </table>
      )}
      <div className="name" style={{ marginTop: 10 }}>Computed only from trades you closed with a recorded entry and exit. Habits are named only once the sample is real.</div>
    </div>
  );
}

export function JournalView({ user, onLogin, onOpenSymbol, onOpenLibrary }) {
  const [tab, setTab] = useState("journal");
  const [list, setList] = useState(null);
  const [authed, setAuthed] = useState(true);
  const [openId, setOpenId] = useState(null);
  const [form, setForm] = useState(null);   // null | BLANK (new) | {..editable, id} (edit)
  const [perf, setPerf] = useState(null);

  const load = () => fetchTrades().then((d) => { setAuthed(d.authenticated !== false); setList(d.trades || []); });
  useEffect(() => { load().catch(() => setAuthed(false)); }, [user]);
  useEffect(() => { if (tab === "performance") fetchPerformance().then(setPerf).catch(() => {}); }, [tab, list]);

  if (!authed) {
    return (
      <div className="detail">
        <h2>Your trading journal</h2>
        <div className="empty" style={{ marginTop: 14 }}>
          Log in to journal your trades and get an educational analysis of each — cross-referenced against the smart-money signal for the same name.
          <div style={{ marginTop: 10 }}><button className="act" onClick={onLogin}>log in</button></div>
        </div>
      </div>
    );
  }

  if (openId) {
    return (
      <div className="detail">
        <TradeDetail id={openId} onBack={() => { setOpenId(null); load(); }}
          onEdit={(t) => { setOpenId(null); setForm({ ...editableFrom(t), id: t.id }); }}
          onChanged={load} onOpenSymbol={onOpenSymbol} onOpenLibrary={onOpenLibrary} />
      </div>
    );
  }

  return (
    <div className="detail">
      <div className="j-head">
        <h2>Your trading journal</h2>
        <div className="seg">
          <button className={tab === "journal" ? "on" : ""} onClick={() => setTab("journal")}>journal</button>
          <button className={tab === "performance" ? "on" : ""} onClick={() => setTab("performance")}>performance</button>
        </div>
      </div>
      <div className="meta">Log your trades and get a guarded, educational analysis of each — pattern, reward-to-risk, risk flags, and the real smart-money convergence for the same name. Private by default.</div>

      {tab === "journal" ? (
        <>
          {form ? (
            <TradeForm initial={form.id ? form : null} onSaved={(id) => { setForm(null); load(); if (id) setOpenId(id); }} onCancel={() => setForm(null)} />
          ) : (
            <div className="controls" style={{ marginTop: 8 }}>
              <button className="act act-on" onClick={() => setForm(BLANK)}>＋ Log a trade</button>
            </div>
          )}
          {list === null ? <div className="skel" style={{ width: "40%", marginTop: 14 }} />
            : list.length === 0 ? <div className="name" style={{ marginTop: 14 }}>No trades logged yet. Log your first — screenshot, levels, and reasoning.</div>
              : <div className="trade-grid">{list.map((t) => <TradeCard key={t.id} t={t} onOpen={setOpenId} />)}</div>}
        </>
      ) : (
        <PerformancePanel perf={perf} />
      )}
      <div className="disc" style={{ marginTop: 16 }}>TradeOS analyzes trades you log for education and journaling. It describes patterns and risk; it never tells you what to buy, sell, or hold.</div>
    </div>
  );
}
