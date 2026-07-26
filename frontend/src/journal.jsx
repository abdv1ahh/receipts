// The Trading Journal — your AI coach, not a notebook. Capture a trade by dropping/pasting a chart
// screenshot (the AI auto-detects ticker, setup and levels); every trade gets a guarded educational
// review; and the top of the page is a coach read of your whole journal — recurring habits to watch and
// what's working — surfaced the moment the sample is real. Nothing here is advice, and no win rate or
// habit is claimed from a handful of trades (the honesty line the rest of the product holds).
import { useEffect, useRef, useState } from "react";
import {
  analyzeChartImage, createTrade, deleteTrade, extractTickers, fetchChartAnalysis, fetchJournalReport,
  fetchPerformance, fetchSimilarTrades, fetchTradeContext, fetchTrades, fetchTradeAnalysis, getTrade,
  simulateTrade, updateTrade, uploadTradeImage,
} from "./api";
import { Icon } from "./icons.jsx";
import { BRAND } from "./brand.js";

const pct = (v) => (v == null ? "—" : `${v >= 0 ? "+" : ""}${(v * 100).toFixed(1)}%`);
const cls = (v) => (v == null ? "" : v > 0 ? "pos-pos" : v < 0 ? "pos-neg" : "");
const money = (v) => (v == null ? "—" : `$${(+v).toLocaleString(undefined, { maximumFractionDigits: 2 })}`);
const DIRS = ["long", "short"];
const ASSETS = ["equity", "crypto", "forex", "option", "future", "other"];
const STATUSES = ["planned", "open", "closed"];
const UNITS = ["shares", "contracts", "usd", "units", "lots"];
const today = () => new Date().toISOString().slice(0, 10);

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

// ------------------------------------------------------------------ effortless capture

function CaptureZone({ onCaptured, onManual }) {
  const [busy, setBusy] = useState(false);
  const [over, setOver] = useState(false);
  const [msg, setMsg] = useState("");
  const inputRef = useRef(null);

  const handle = async (file) => {
    if (!file || !file.type?.startsWith("image/")) { setMsg("Drop an image of a chart"); return; }
    setBusy(true); setMsg("");
    let tickers = null, chart = null;
    try {
      [tickers, chart] = await Promise.all([
        extractTickers(file).catch(() => null),
        analyzeChartImage(file).catch(() => null),
      ]);
    } catch { /* fall through to whatever resolved */ }
    setBusy(false);
    const a = chart?.analysis || {};
    const det = a.detected || {};
    const sym = (tickers?.recognized || [])[0] || (tickers?.unrecognized || [])[0] || det.symbol || "";
    onCaptured({
      file, read: a,
      prefill: {
        symbol: sym, timeframe: det.timeframe || "", direction: det.direction || "long",
        entry_price: det.entry ?? "", stop_price: det.stop ?? "", target_price: det.target ?? "",
        strategy: a.pattern || "", status: det.entry != null ? "open" : "planned",
        opened_on: det.entry != null ? today() : "",
      },
    });
  };

  // Paste a screenshot from anywhere on this screen.
  useEffect(() => {
    const onPaste = (e) => {
      const item = [...(e.clipboardData?.items || [])].find((i) => i.type.startsWith("image/"));
      const f = item?.getAsFile();
      if (f) { e.preventDefault(); handle(f); }
    };
    window.addEventListener("paste", onPaste);
    return () => window.removeEventListener("paste", onPaste);
  }, []);

  return (
    <div className={`capture ${over ? "over" : ""} ${busy ? "busy" : ""}`}
         onDragOver={(e) => { e.preventDefault(); setOver(true); }}
         onDragLeave={() => setOver(false)}
         onDrop={(e) => { e.preventDefault(); setOver(false); handle(e.dataTransfer.files?.[0]); }}>
      <input ref={inputRef} type="file" accept="image/png,image/jpeg,image/webp" hidden onChange={(e) => handle(e.target.files[0])} />
      <div className="capture-icon">{busy ? <span className="spinner" /> : <Icon name="journal" size={24} />}</div>
      <div className="capture-title">{busy ? "Reading your chart…" : "Drop, paste, or upload a chart screenshot"}</div>
      <div className="capture-sub">
        {busy ? "Detecting the ticker, setup and levels — one moment."
              : "The AI auto-detects the ticker, timeframe, setup and levels. You just confirm and log."}
      </div>
      {!busy && (
        <div className="capture-actions">
          <button className="act act-on" onClick={() => inputRef.current?.click()}>Choose screenshot</button>
          <button className="act" onClick={onManual}>Log manually</button>
        </div>
      )}
      {msg && <div className="capture-msg">{msg}</div>}
    </div>
  );
}

function ChartReadPreview({ read }) {
  if (!read || (!read.pattern && !read.structure && !(read.observations || []).length)) return null;
  const ai = read.source === "ai";
  return (
    <div className="chart-read">
      <div className="chart-read-head"><Icon name="sparkles" size={14} /> What the AI saw <span className={`ai-tag ${ai ? "ai-on" : ""}`}>{ai ? "✦ AI vision" : "levels only"}</span></div>
      {read.pattern && <div className="ca-row"><span className="ca-l">Pattern</span> {read.pattern}</div>}
      {read.structure && <p className="an-prose" style={{ margin: "6px 0" }}>{read.structure}</p>}
      {(read.observations || []).length > 0 && <ul className="an-list" style={{ marginTop: 4 }}>{read.observations.slice(0, 3).map((o, i) => <li key={i}>{o}</li>)}</ul>}
    </div>
  );
}

function TradeForm({ initial, initialImage, chartRead, onSaved, onCancel }) {
  const [f, setF] = useState(() => ({ ...BLANK, ...(initial || {}) }));
  const [img, setImg] = useState(initialImage || null);
  const [thumbUrl, setThumbUrl] = useState(typeof initialImage === "string" ? initialImage : null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  // Preview as a data: URL (the strict CSP allows 'self' data:, not blob:).
  useEffect(() => {
    if (img && typeof img !== "string") { const r = new FileReader(); r.onload = () => setThumbUrl(r.result); r.readAsDataURL(img); }
  }, [img]);
  const set = (k) => (e) => setF((s) => ({ ...s, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value }));
  const autofilled = Boolean(chartRead) || Boolean(initial?.symbol && !initial?.id);

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

  const L = (label, node, hint) => <label className="fld"><span>{label}{hint && <em className="fld-detected">✦ detected</em>}</span>{node}</label>;
  const inp = (k, extra = {}) => <input value={f[k]} onChange={set(k)} {...extra} />;
  const sel = (k, opts) => <select value={f[k]} onChange={set(k)}>{opts.map((o) => <option key={o} value={o}>{o || "—"}</option>)}</select>;
  const det = (k) => autofilled && f[k] !== "" && f[k] != null && !initial?.id;

  return (
    <div className="trade-form">
      {autofilled && !initial?.id && (
        <div className="autofill-banner"><Icon name="sparkles" size={14} /> Auto-filled from your screenshot — please verify the ticker and levels before logging.</div>
      )}
      <div className="tf-body">
        <div className="tf-main">
          <div className="form-grid">
            {L("Ticker / asset", <div className="sym-row">{inp("symbol", { placeholder: "NVDA", style: { textTransform: "uppercase" } })}{img && <button type="button" className="act mini" onClick={scan}>rescan</button>}</div>, det("symbol"))}
            {L("Asset class", sel("asset_class", ASSETS))}
            {L("Direction", sel("direction", DIRS), det("direction"))}
            {L("Status", sel("status", STATUSES))}
            {L("Entry", inp("entry_price", { type: "number", step: "any", placeholder: "165" }), det("entry_price"))}
            {L("Exit", inp("exit_price", { type: "number", step: "any" }))}
            {L("Stop-loss", inp("stop_price", { type: "number", step: "any", placeholder: "155" }), det("stop_price"))}
            {L("Profit target", inp("target_price", { type: "number", step: "any", placeholder: "180" }), det("target_price"))}
            {L("Size", inp("size", { type: "number", step: "any" }))}
            {L("Unit", sel("size_unit", UNITS))}
            {L("Timeframe", inp("timeframe", { placeholder: "swing / day / 1h" }), det("timeframe"))}
            {L("Strategy / setup", inp("strategy", { placeholder: "breakout" }), det("strategy"))}
            {L("Confidence", sel("confidence", ["", "1", "2", "3", "4", "5"]))}
            {L("Opened", inp("opened_on", { type: "date" }))}
            {L("Closed", inp("closed_on", { type: "date" }))}
            {!initialImage && L("Screenshot", <input type="file" accept="image/png,image/jpeg,image/webp" onChange={(e) => setImg(e.target.files[0])} />)}
          </div>
          {L("Reason for entering", <textarea value={f.reason_entry} onChange={set("reason_entry")} rows={2} placeholder="AI earnings momentum + technical breakout" />)}
          {L("Reason for exiting", <textarea value={f.reason_exit} onChange={set("reason_exit")} rows={2} />)}
          <label className="fld-check"><input type="checkbox" checked={f.is_public} onChange={set("is_public")} /><span>Make this trade public on my profile</span></label>
        </div>
        {(thumbUrl || chartRead) && (
          <div className="tf-side">
            {thumbUrl && <img className="tf-thumb" src={thumbUrl} alt="your chart" />}
            <ChartReadPreview read={chartRead} />
          </div>
        )}
      </div>
      <div className="controls" style={{ marginTop: 10 }}>
        <button className="act act-on" disabled={busy} onClick={save}>{busy ? "saving…" : (initial?.id ? "save changes" : "log trade")}</button>
        <button className="act" onClick={onCancel}>cancel</button>
        {msg && <span className="name" style={{ marginLeft: 6 }}>{msg}</span>}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ trade cards + tabs

function TradeCard({ t, onOpen }) {
  return (
    <button className="tcard" onClick={() => onOpen(t.id)}>
      {t.has_image && <span className="tcard-thumb"><img src={`/api/trades/${t.id}/image`} alt="" loading="lazy" /></span>}
      <span className="tcard-body">
        <span className="tcard-top">
          <span className="tcard-sym">{t.symbol || "idea"}</span>
          <span className={`chip chip-${t.direction}`}>{t.direction}</span>
          <span className={`chip s-${t.status}`}>{t.status}</span>
          {t.is_public && <span className="tcard-flag">🌐</span>}
        </span>
        <span className="tcard-strat">{t.asset_class}{t.strategy ? ` · ${t.strategy}` : ""}</span>
        <span className="tcard-stats">
          <span>entry <b>{money(t.entry_price)}</b></span>
          {t.status === "closed"
            ? <span>P&amp;L <b className={cls(t.realized_pnl_pct)}>{pct(t.realized_pnl_pct)}</b></span>
            : <span>target <b>{money(t.target_price)}</b></span>}
          <span>R:R <b>{t.reward_risk != null ? `${t.reward_risk}:1` : "—"}</b></span>
        </span>
      </span>
    </button>
  );
}

// ------------------------------------------------------------------ the AI coach (top of the journal)

function Stat({ label, value, c }) {
  return <div className="stat"><div className={`stat-v ${c || ""}`}>{value}</div><div className="stat-l">{label}</div></div>;
}

function CoachStrip({ refreshKey, onOpenPerformance }) {
  const [r, setR] = useState(undefined); // undefined loading, null failed
  useEffect(() => { setR(undefined); fetchJournalReport().then((d) => setR(d.report || null)).catch(() => setR(null)); }, [refreshKey]);

  if (r === undefined) return <div className="coach"><div className="skel" style={{ width: "55%", height: 18 }} /><div className="skel" style={{ width: "85%", height: 14, marginTop: 10 }} /></div>;
  if (!r) return null;
  const model = r.used_template ? `${BRAND} rules` : r.model_id;

  return (
    <div className="coach">
      <div className="coach-head">
        <span className="coach-badge"><Icon name="compass" size={16} /></span>
        <div>
          <div className="coach-title">Your AI coach</div>
          <div className="coach-tag">reads every trade you log · educational, not advice</div>
        </div>
        <button className="sec-link" style={{ marginLeft: "auto" }} onClick={onOpenPerformance}>Full performance <Icon name="arrow" size={14} /></button>
      </div>
      {r.prose && <p className="coach-prose">{r.prose}</p>}
      <div className="coach-stats">
        <Stat label="logged" value={r.n_total} />
        <Stat label="closed" value={r.n_closed} />
        <Stat label="win rate" value={r.sufficient ? `${Math.round(r.win_rate * 100)}%` : "—"} />
        <Stat label="avg R:R" value={r.avg_reward_risk != null ? `${r.avg_reward_risk}:1` : "—"} />
      </div>
      <div className="coach-cols">
        <div className="coach-col">
          <div className="coach-col-h warn"><Icon name="target" size={13} /> Watch these habits</div>
          {r.habits?.length > 0
            ? <ul className="coach-list warn">{r.habits.map((h, i) => <li key={i}>{h.count} of {h.of} — {h.label}</li>)}</ul>
            : <div className="coach-empty">{r.sufficient ? "No recurring risk habits stand out. Keep it up." : "Log a few more closed trades and your coach will start flagging recurring habits."}</div>}
        </div>
        <div className="coach-col">
          <div className="coach-col-h ok"><Icon name="trending" size={13} /> What's working</div>
          {r.performance_insights?.length > 0
            ? <ul className="coach-list ok">{r.performance_insights.map((s, i) => <li key={i}>{s}</li>)}</ul>
            : <div className="coach-empty">Strengths appear here once your sample is real — never inferred from a handful of trades.</div>}
        </div>
      </div>
      {r.context_patterns?.length > 0 && (
        <div className="coach-patterns">
          <div className="coach-col-h"><Icon name="radar" size={13} /> How you decide — read from what the world was showing when you entered</div>
          {r.context_patterns.map((p) => (
            <div key={p.key} className={`pattern pattern-${p.tone}`}>
              <div className="pattern-h">{p.headline}</div>
              <div className="pattern-d">{p.detail}</div>
            </div>
          ))}
        </div>
      )}
      <div className="coach-foot">
        Generated by {model}{r.from_cache ? " · cached" : ""} · aggregated from trades you logged.
        {r.n_with_context > 0 && ` ${r.n_with_context} of them carry the world context recorded at entry.`}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ per-trade panels (guarded, reused)

function Section({ title, items, warn }) {
  return <div className="an-sec"><div className="an-title">{title}</div><ul className={warn ? "an-list warn" : "an-list"}>{items.map((s, i) => <li key={i}>{s}</li>)}</ul></div>;
}

function AnalysisPanel({ id, onOpenLibrary }) {
  const [a, setA] = useState(null);
  useEffect(() => { setA(null); fetchTradeAnalysis(id).then((d) => setA(d.analysis || null)).catch(() => {}); }, [id]);
  if (!a) return <div className="analysis"><div className="skel" style={{ width: "70%" }} /></div>;
  const model = a.used_template ? `${BRAND} rules` : a.model_id;
  return (
    <div className="analysis">
      <div className="an-head">🧠 The coach on this trade <span className="name">· educational, not advice</span></div>
      {a.prose && <p className="an-prose">{a.prose}</p>}
      {a.observations?.length > 0 && <Section title="Observations" items={a.observations} />}
      {a.risk_flags?.length > 0 && <Section title="Risk & mistakes to avoid" items={a.risk_flags} warn />}
      {a.context?.length > 0 && <Section title="Smart-money context" items={a.context} />}
      {a.learn?.length > 0 && (
        <div className="an-sec"><div className="an-title">Learn the pattern</div>
          <div className="an-learn">{a.learn.map((l) => <button key={l.slug} className="pill pill-link" onClick={() => onOpenLibrary?.(l.slug)}>{l.title}</button>)}</div>
        </div>
      )}
      <div className="an-foot">Generated by {model}. Descriptive context and risk framing only — never advice about any position.</div>
    </div>
  );
}

function SimilarTrades({ id, onOpen }) {
  const [d, setD] = useState(null);
  useEffect(() => { setD(null); fetchSimilarTrades(id).then(setD).catch(() => setD({ similar: [] })); }, [id]);
  if (!d || d.found === false) return null;
  return (
    <div className="analysis similar">
      <div className="an-head">🔎 Your trades like this one <span className="name">· your own history, not a prediction</span></div>
      <p className="an-prose">{d.line}</p>
      {d.similar?.length > 0 && (
        <div className="sim-list">{d.similar.map((s) => (
          <button key={s.id} className="sim-row" onClick={() => onOpen?.(s.id)}>
            <span className="sim-sym">{s.symbol || "idea"}</span>
            <span className={`chip chip-${s.direction}`}>{s.direction}</span>
            <span className="name">{s.strategy || "—"}</span>
            <span className="sim-rr">R:R {s.reward_risk != null ? `${s.reward_risk}:1` : "—"}</span>
            <span className={`sim-pnl ${cls(s.realized_pnl_pct)}`}>{s.status === "closed" ? pct(s.realized_pnl_pct) : s.status}</span>
          </button>
        ))}</div>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ world context at trade time

const ALIGN = {
  with: { label: "pointed your way", cls: "wc-with", icon: "trending" },
  against: { label: "pointed the other way", cls: "wc-against", icon: "alert" },
  mixed: { label: "pointed both ways", cls: "wc-mixed", icon: "layers" },
  none: { label: "was silent on this name", cls: "wc-none", icon: "radar" },
};

// What the Radar was showing at the moment this trade was logged, frozen. It is deliberately shown
// even when nothing was live — "the world was busy and had nothing to say about your name" is a
// real answer, and blanking the panel would quietly imply the feature had failed.
function WorldContext({ id, onOpenClaim }) {
  const [d, setD] = useState(undefined); // undefined loading, null unavailable
  const [open, setOpen] = useState(false);
  useEffect(() => { setD(undefined); fetchTradeContext(id).then(setD).catch(() => setD(null)); }, [id]);

  if (d === undefined) return <div className="analysis world-ctx"><div className="skel" style={{ width: "65%" }} /></div>;
  if (!d || d.found === false) return null;
  if (!d.context) {
    return (
      <div className="analysis world-ctx">
        <div className="an-head"><Icon name="radar" size={15} /> When you entered <span className="name">· world context</span></div>
        <div className="coach-empty">{d.note}</div>
      </div>
    );
  }
  const c = d.context;
  const a = ALIGN[c.alignment] || ALIGN.none;
  const when = new Date(c.as_of).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
  const claims = c.claims || [];

  return (
    <div className="analysis world-ctx">
      <div className="an-head">
        <Icon name="radar" size={15} /> When you entered, the Radar was showing…
        <span className="name"> · {when}</span>
      </div>
      <div className={`wc-verdict ${a.cls}`}>
        <Icon name={a.icon} size={16} />
        <div>
          {c.n_live === 0
            ? <>Nothing was live on the Radar — no interpretation had been made yet that was still
                within its horizon. This entry was entirely your own read.</>
            : <>
                <b>{c.n_live} live interpretation{c.n_live === 1 ? "" : "s"}</b>
                {c.n_on_symbol > 0
                  ? <> · {c.n_on_symbol} named {c.symbol} and {a.label}</>
                  : <> · none named {c.symbol || "this instrument"}, so the read {a.label}</>}
              </>}
        </div>
      </div>

      {(c.on_symbol || []).length > 0 && (
        <div className="an-sec">
          <div className="an-title">On {c.symbol} specifically</div>
          {c.on_symbol.map((o, i) => (
            <div key={i} className="wc-sym">
              <span className={`chip chip-${o.direction === "up" ? "long" : "short"}`}>{o.direction}</span>
              <span className="wc-sym-body">
                <b>{o.named_as}</b> — {o.headline || "interpretation"}
                <span className="name"> · confidence {o.confidence != null ? `${Math.round(o.confidence * 100)}%` : "—"} · over {o.horizon || "—"}</span>
              </span>
            </div>
          ))}
        </div>
      )}

      {claims.length > 0 && (
        <button className="linkish" onClick={() => setOpen(!open)} style={{ marginTop: 4 }}>
          {open ? "hide" : `show the ${claims.length} most relevant to you`}
        </button>
      )}
      {open && (
        <div className="wc-list">
          {claims.map((k) => (
            <button key={k.id} className="wc-row" onClick={() => onOpenClaim?.(k.id)}>
              <span className="wc-rel">{Math.round((k.relevance || 0) * 100)}</span>
              <span className="wc-row-body">
                <b>{k.headline || "interpretation"}</b>
                <span className="name">{k.why_shown} · {k.source || "—"} · over {k.horizon}</span>
              </span>
            </button>
          ))}
        </div>
      )}

      <div className="an-foot">
        {c.basis === "live"
          ? "Captured the moment you logged this trade and never rewritten — so it records what you could actually see, not what is known now."
          : "Reconstructed afterwards from claims whose timestamps prove they were live then, but ranked against your frame today rather than the one you had at the time."}
        {c.mean_novelty != null && ` Mean novelty of the live reads was ${c.mean_novelty} — ${c.mean_novelty >= 0.5 ? "the news was genuinely breaking" : "a comparatively quiet stretch"}.`}
      </div>
    </div>
  );
}

function ChartAnalysisPanel({ id }) {
  const [a, setA] = useState(null);
  const [busy, setBusy] = useState(false);
  const load = (refresh) => { setBusy(true); fetchChartAnalysis(id, refresh).then((d) => setA(d.analysis || {})).catch(() => setA({})).finally(() => setBusy(false)); };
  useEffect(() => { load(false); }, [id]);
  if (!a) return <div className="analysis"><div className="skel" style={{ width: "60%" }} /></div>;
  const ai = a.source === "ai";
  return (
    <div className="analysis chart-analysis">
      <div className="ca-head"><b>AI chart read</b><span className={`ai-tag ${ai ? "ai-on" : ""}`}>{ai ? "✦ AI vision" : "levels only"}</span>
        <span className="spacer" style={{ flex: 1 }} /><button className="linkish" onClick={() => load(true)} disabled={busy}>{busy ? "reading…" : "re-analyze"}</button>
      </div>
      {a.pattern && <div className="ca-row"><span className="ca-l">Pattern</span> {a.pattern}</div>}
      {a.structure && <p className="explain-prose" style={{ marginTop: 6 }}>{a.structure}</p>}
      {a.risk_reward && <div className="ca-row"><span className="ca-l">Risk : reward</span> {a.risk_reward}</div>}
      {a.observations?.length > 0 && <Section title="Observations" items={a.observations} />}
      {a.risk_flags?.length > 0 && <Section title="Risk flags" items={a.risk_flags} warn />}
      {a.psychology && <div className="ca-row"><span className="ca-l">Psychology</span> {a.psychology}</div>}
      <div className="disc" style={{ marginTop: 8 }}>{a.disclaimer || "Educational, not advice."}</div>
    </div>
  );
}

function TradeDetail({ id, onBack, onEdit, onChanged, onOpenSymbol, onOpenLibrary, onOpenTrade }) {
  const [d, setD] = useState(null);
  const load = () => getTrade(id).then(setD);
  useEffect(() => { load(); }, [id]);
  if (!d) return <div className="skel" style={{ width: "50%" }} />;
  if (!d.found) return <><button className="issuer-back" onClick={onBack}>← journal</button><div className="empty" style={{ marginTop: 12 }}>Trade not found or private.</div></>;
  const t = d.trade, owner = d.owner;
  const togglePublish = async () => { await updateTrade(id, toPayload({ ...editableFrom(t), is_public: !t.is_public })); load(); onChanged?.(); };
  const del = async () => { if (!window.confirm("Delete this trade?")) return; await deleteTrade(id); onChanged?.(); onBack(); };
  const kv = (label, val) => <div className="kv"><span className="kv-l">{label}</span><span className="kv-v">{val}</span></div>;

  return (
    <>
      <button className="issuer-back" onClick={onBack}><Icon name="arrow" size={15} style={{ transform: "scaleX(-1)" }} /> journal</button>
      <div className="td-head">
        <button className="linkish sym td-sym" onClick={() => t.symbol && onOpenSymbol(t.symbol)}>{t.symbol || "untitled idea"}</button>
        <span className={`chip chip-${t.direction}`}>{t.direction}</span>
        <span className={`chip s-${t.status}`}>{t.status}</span>
        <span className="chip">{t.asset_class}</span>
        {owner && <span className="chip">{t.is_public ? "🌐 public" : "🔒 private"}</span>}
      </div>
      {t.has_image && <img className="td-img" src={`/api/trades/${id}/image`} alt="trade screenshot" />}
      {owner && t.has_image && <ChartAnalysisPanel id={id} />}
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
      {owner && <WorldContext id={id} />}
      <AnalysisPanel id={id} onOpenLibrary={onOpenLibrary} />
      {owner && <SimilarTrades id={id} onOpen={onOpenTrade} />}
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

// ------------------------------------------------------------------ performance + simulator (secondary)

function PerformancePanel() {
  const [perf, setPerf] = useState(null);
  useEffect(() => { fetchPerformance().then(setPerf).catch(() => {}); }, []);
  if (!perf) return <div className="skel" style={{ width: "50%", marginTop: 14 }} />;
  if (perf.authenticated === false) return null;
  const s = perf.summary;
  if (!s.sufficient) {
    return (
      <div className="perf">
        <div className="perf-row"><Stat label="closed trades" value={s.n_closed} /><Stat label="wins" value={s.wins} c="pos-pos" /><Stat label="losses" value={s.losses} c="pos-neg" /></div>
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

const SIM_BLANK = { symbol: "", direction: "long", entry_price: "", stop_price: "", target_price: "", size: "", account_size: "" };

function SimulatorPanel() {
  const [f, setF] = useState(SIM_BLANK);
  const [res, setRes] = useState(null);
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setF((s) => ({ ...s, [k]: e.target.value }));
  const num = (x) => (x === "" || x == null ? null : Number(x));
  const run = async () => {
    setBusy(true);
    const r = await simulateTrade({
      symbol: f.symbol || null, direction: f.direction, entry_price: num(f.entry_price), stop_price: num(f.stop_price),
      target_price: num(f.target_price), size: num(f.size), size_unit: "shares", account_size: num(f.account_size),
    }).catch(() => ({ ok: false, reason: "could not run the simulation" }));
    setRes(r); setBusy(false);
  };
  const L = (label, node) => <label className="fld"><span>{label}</span>{node}</label>;
  const n = (k, extra = {}) => <input value={f[k]} onChange={set(k)} type="number" step="any" {...extra} />;
  return (
    <div>
      <div className="meta">A what-if calculator for a position: enter the levels and see P&amp;L, R-multiple and account risk at your stop, your target, and fixed price moves. Pure arithmetic — never a prediction of what price will do.</div>
      <div className="trade-form" style={{ marginTop: 10 }}>
        <div className="form-grid">
          {L("Ticker (optional)", <input value={f.symbol} onChange={set("symbol")} placeholder="NVDA" style={{ textTransform: "uppercase" }} />)}
          {L("Direction", <select value={f.direction} onChange={set("direction")}>{DIRS.map((o) => <option key={o} value={o}>{o}</option>)}</select>)}
          {L("Entry", n("entry_price", { placeholder: "165" }))}
          {L("Stop-loss", n("stop_price", { placeholder: "155" }))}
          {L("Profit target", n("target_price", { placeholder: "185" }))}
          {L("Size (shares)", n("size", { placeholder: "100" }))}
          {L("Account size ($)", n("account_size", { placeholder: "25000" }))}
        </div>
        <div className="controls" style={{ marginTop: 6 }}><button className="act act-on" disabled={busy} onClick={run}>{busy ? "simulating…" : "simulate"}</button></div>
      </div>
      {res && (res.ok === false
        ? <div className="empty" style={{ marginTop: 12 }}>{res.reason}</div>
        : (
          <div className="analysis" style={{ marginTop: 12 }}>
            <div className="perf-row">
              <Stat label="reward : risk" value={res.reward_risk != null ? `${res.reward_risk}:1` : "—"} />
              <Stat label="to stop" value={res.distance_to_stop_pct != null ? `${res.distance_to_stop_pct}%` : "—"} />
              <Stat label="to target" value={res.distance_to_target_pct != null ? `${res.distance_to_target_pct}%` : "—"} />
              <Stat label="account risk" value={res.account_risk_pct != null ? `${res.account_risk_pct}%` : "—"} c={res.account_risk_pct > 2 ? "pos-neg" : ""} />
            </div>
            <table className="clusters" style={{ marginTop: 12 }}>
              <thead><tr><th>Scenario</th><th>Price</th><th>Return</th><th>R</th><th>P&amp;L</th></tr></thead>
              <tbody>{res.scenarios.map((s, i) => (
                <tr key={i}><td>{s.label}</td><td className="num">{money(s.price)}</td>
                  <td className={`num ${cls(s.return_pct)}`}>{s.return_pct != null ? `${s.return_pct >= 0 ? "+" : ""}${s.return_pct}%` : "—"}</td>
                  <td className="num">{s.r_multiple != null ? `${s.r_multiple}R` : "—"}</td>
                  <td className={`num ${cls(s.pnl_amount)}`}>{s.pnl_amount != null ? money(s.pnl_amount) : "—"}</td>
                </tr>
              ))}</tbody>
            </table>
            {res.notes?.length > 0 && <Section title="Notes" warn items={res.notes} />}
            <div className="an-foot">Deterministic arithmetic from the levels you entered. Not a prediction, recommendation, or forecast.</div>
          </div>
        ))}
    </div>
  );
}

// ------------------------------------------------------------------ the journal

const FILTERS = [
  { k: "all", label: "All" },
  { k: "open", label: "Open", test: (t) => t.status === "open" || t.status === "planned" },
  { k: "closed", label: "Closed", test: (t) => t.status === "closed" },
  { k: "today", label: "Today", test: (t) => (t.opened_on || "").slice(0, 10) === today() },
];

export function JournalView({ user, onLogin, onOpenSymbol, onOpenLibrary }) {
  const [list, setList] = useState(null);
  const [authed, setAuthed] = useState(true);
  const [openId, setOpenId] = useState(null);
  const [form, setForm] = useState(null);       // null | { initial, image, read }
  const [filter, setFilter] = useState("all");
  const [tool, setTool] = useState(null);        // null | "performance" | "simulator"
  const [coachKey, setCoachKey] = useState(0);

  const load = () => fetchTrades().then((d) => { setAuthed(d.authenticated !== false); setList(d.trades || []); });
  useEffect(() => { load().catch(() => setAuthed(false)); }, [user]);
  const afterChange = () => { load(); setCoachKey((k) => k + 1); };

  if (!authed) {
    return (
      <div>
        <div className="page-head"><div><h1 className="page-title">Trading Journal</h1><p className="page-sub">Your AI trading coach — log trades from a screenshot and get an educational review of each.</p></div></div>
        <div className="empty" style={{ marginTop: 14 }}>
          Log in to journal your trades and get an educational analysis of each — cross-referenced against the smart-money signal for the same name.
          <div style={{ marginTop: 10 }}><button className="act" onClick={onLogin}>log in</button></div>
        </div>
      </div>
    );
  }

  if (openId) {
    return (
      <div className="issuer">
        <TradeDetail id={openId} onBack={() => { setOpenId(null); afterChange(); }}
          onEdit={(t) => { setOpenId(null); setForm({ initial: { ...editableFrom(t), id: t.id } }); }}
          onChanged={afterChange} onOpenSymbol={onOpenSymbol} onOpenLibrary={onOpenLibrary} onOpenTrade={setOpenId} />
      </div>
    );
  }

  const f = FILTERS.find((x) => x.k === filter) || FILTERS[0];
  const shown = (list || []).filter((t) => (f.test ? f.test(t) : true));
  const countFor = (flt) => (list || []).filter((t) => (flt.test ? flt.test(t) : true)).length;

  return (
    <div>
      <div className="page-head">
        <div><h1 className="page-title">Trading Journal</h1><p className="page-sub">Drop a chart, get it logged and coached. Every trade reviewed for setup, risk and habits — never advice.</p></div>
        <div className="sm-filter">
          <button className={tool === null ? "on" : ""} onClick={() => setTool(null)}>Journal</button>
          <button className={tool === "performance" ? "on" : ""} onClick={() => setTool("performance")}>Performance</button>
          <button className={tool === "simulator" ? "on" : ""} onClick={() => setTool("simulator")}>Simulator</button>
        </div>
      </div>

      {tool === "performance" ? <PerformancePanel />
        : tool === "simulator" ? <SimulatorPanel />
        : form ? (
          <TradeForm initial={form.initial} initialImage={form.image} chartRead={form.read}
            onSaved={(id) => { setForm(null); afterChange(); if (id) setOpenId(id); }}
            onCancel={() => setForm(null)} />
        ) : (
          <>
            <CoachStrip refreshKey={coachKey} onOpenPerformance={() => setTool("performance")} />
            <CaptureZone onCaptured={({ file, read, prefill }) => setForm({ initial: prefill, image: file, read })}
                         onManual={() => setForm({ initial: BLANK })} />
            <div className="j-tabs">
              {FILTERS.map((x) => (
                <button key={x.k} className={`j-tab ${filter === x.k ? "on" : ""}`} onClick={() => setFilter(x.k)}>
                  {x.label} <span className="j-tab-n">{countFor(x)}</span>
                </button>
              ))}
            </div>
            {list === null ? <div className="skel" style={{ width: "40%", marginTop: 14 }} />
              : shown.length === 0 ? <div className="empty" style={{ marginTop: 6 }}>{list.length === 0 ? "No trades logged yet. Drop your first chart screenshot above — the AI does the rest." : "Nothing in this view."}</div>
              : <div className="tcard-grid">{shown.map((t) => <TradeCard key={t.id} t={t} onOpen={setOpenId} />)}</div>}
          </>
        )}

      <div className="disc" style={{ marginTop: 18 }}>{BRAND} analyzes trades you log for education and journaling. It describes patterns and risk; it never tells you what to buy, sell, or hold.</div>
    </div>
  );
}
