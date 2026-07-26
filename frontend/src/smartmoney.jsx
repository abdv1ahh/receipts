// Smart Money — the pillar, redesigned to be legible to anyone. The feed answers "who is smart money
// piling into, and why does it matter?" in plain language; the detail translates raw SEC filings into
// a story, the named people behind it, an AI read, an honest track record, and the price since the
// signal — with the raw contributing filings tucked behind ONE expand (no data dumping). Every figure
// is real: conviction from the calibrated score, base rates from the backtest, prices from EOD data.
import { useEffect, useState } from "react";
import { addFollow, addWatchlist, fetchAsset, fetchHome, fetchLeaderboards, shadowSymbol } from "./api";
import { Backtested, Freshness } from "./components.jsx";
import { Icon } from "./icons.jsx";
import { BRAND } from "./brand.js";

const BAND = { high: "band-high", medium: "band-med", low: "band-low" };
const money = (v) => {
  if (v == null) return null;
  const n = Number(v);
  if (n >= 1e9) return `$${(n / 1e9).toFixed(1)}B`;
  if (n >= 1e6) return `$${(n / 1e6).toFixed(1)}M`;
  if (n >= 1e3) return `$${(n / 1e3).toFixed(0)}K`;
  return `$${Math.round(n)}`;
};

// A plain, deterministic "why it matters" from the confidence bucket + which smart-money classes fired.
// Descriptive only — no advice, no forecast (the same line the rest of the product holds).
function whyItMatters(bucket, classes) {
  const set = new Set(classes || []);
  const activist = set.has("activist");
  if (bucket === "high")
    return activist
      ? "Highest conviction: several independent smart-money actors are accumulating at once — and an activist is pushing for change."
      : "Highest conviction: several independent smart-money actors are converging on this name at the same time.";
  if (bucket === "medium")
    return activist
      ? "A building cluster of smart-money activity — including an activist stake, which often acts as a catalyst."
      : "A building cluster of smart-money activity worth watching as it develops.";
  return "Early, lower-conviction smart-money interest — one to keep on the radar.";
}

function Avatar({ name }) {
  const initials = (name || "?").split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join("").toUpperCase();
  let h = 0;
  for (let i = 0; i < (name || "").length; i++) h = (h * 31 + name.charCodeAt(i)) % 360;
  return <span className="avatar" style={{ background: `hsl(${h} 42% 26%)`, borderColor: `hsl(${h} 42% 40%)` }}>{initials}</span>;
}

// ------------------------------------------------------------------ feed card

function SmartCard({ c, calibration, horizon, user, onLogin, onNav, onOpenSymbol, onOpenDetail, onOpenProfile }) {
  const [followed, setFollowed] = useState(false);
  const [shadowed, setShadowed] = useState(false);
  const [shared, setShared] = useState(false);
  const cal = calibration?.per_bucket?.[c.confidence_bucket]?.[String(horizon)];
  // Always open the insight-first issuer detail; that view links out to the full chart deep-dive.
  const open = () => onOpenDetail(c.issuer_entity);
  const stop = (fn) => (e) => { e.stopPropagation(); fn(e); };

  const follow = async (e) => {
    if (!c.symbol) return;
    if (user) { const r = await addFollow("symbol", c.symbol, c.name); if (r?.upgrade) return onNav?.("pricing"); }
    else await addWatchlist(c.symbol);
    setFollowed(true);
  };
  const shadow = async () => {
    if (!user) return onLogin?.();
    if (!c.symbol) return;
    const r = await shadowSymbol(c.symbol); if (!r.error) setShadowed(true);
  };
  const share = async () => {
    try { await navigator.clipboard.writeText(`${location.origin}/s/${encodeURIComponent(c.symbol || "")}`); } catch { /* clipboard may be blocked */ }
    setShared(true); setTimeout(() => setShared(false), 1600);
  };

  const prot = c.story?.protagonists || [];
  return (
    <div className="card" onClick={open}>
      <div className={`medallion ${BAND[c.confidence_bucket] || "band-low"}`}>
        <div className="med-score num">{c.smart_money_score}</div>
        <div className="med-label">SCORE</div>
      </div>
      <div className="card-body">
        <div className="card-head">
          <span className="card-sym">{c.symbol || "—"}</span>
          <span className="card-name">{c.name}</span>
          <span className={`pill pill-${c.confidence_bucket}`}>{c.confidence_bucket}</span>
        </div>
        <div className="card-story">{c.headline || "converging smart-money activity"}</div>
        {prot.length > 0 && (
          <div className="protags">
            {prot.map((p, i) => (
              <button key={i} className="protag" title={`${p.role} — open profile`}
                      onClick={stop(() => onOpenProfile(p.kind === "insider" ? "insider" : "institution", p.id))}>
                <Avatar name={p.name} />
                <span className="protag-name">{p.name}</span>
                <span className="protag-role">{p.role}</span>
              </button>
            ))}
          </div>
        )}
        <div className="why">
          <span className="ico"><Icon name="sparkles" size={14} /></span>
          <span>{whyItMatters(c.confidence_bucket, c.source_classes)}</span>
        </div>
        <div className="card-foot">
          <Backtested cal={cal} />
          <Freshness iso={c.freshest_contributing_knowable} />
          <span className="spacer" />
          <button className={`act ${followed ? "act-on" : ""}`} onClick={stop(follow)} disabled={!c.symbol}>{followed ? "following ✓" : "+ follow"}</button>
          <button className={`act ${shadowed ? "act-on" : ""}`} onClick={stop(shadow)} disabled={!c.symbol}>{shadowed ? "shadowing ✓" : "shadow"}</button>
          <button className="act" onClick={stop(share)}>{shared ? "copied ✓" : "share"}</button>
        </div>
      </div>
    </div>
  );
}

function Leaderboards({ data, onOpenSymbol, onOpenProfile }) {
  if (!data) return null;
  return (
    <div className="boards">
      <div className="board">
        <div className="board-title">🔥 Most bought this month</div>
        {data.most_bought.length === 0 ? <div className="name">—</div> : data.most_bought.map((m, i) => (
          <button key={i} className="board-row" onClick={() => m.symbol && onOpenSymbol(m.symbol)}>
            <span className="board-rank">{i + 1}</span><span className="board-sym">{m.symbol || m.name.slice(0, 14)}</span>
            <span className="board-val">{m.buyers} insiders</span>
          </button>
        ))}
      </div>
      <div className="board">
        <div className="board-title">⚔️ New activist stakes</div>
        {data.new_activist_stakes.length === 0 ? <div className="name">—</div> : data.new_activist_stakes.slice(0, 8).map((a, i) => (
          <button key={i} className="board-row" onClick={() => onOpenProfile("institution", a.filer_entity)}>
            <span className="board-sym">{a.symbol || a.issuer.slice(0, 10)}</span><span className="board-actor">{a.filer}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

export function SmartMoneyView({ calibration, horizon, minC, user, onLogin, onNav, onOpenSymbol, onOpenDetail, onOpenProfile }) {
  const [conf, setConf] = useState(minC || "medium");
  const [data, setData] = useState(null);
  const [boards, setBoards] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => { setData(null); fetchHome(conf).then(setData).catch((e) => setErr(String(e))); }, [conf]);
  useEffect(() => { fetchLeaderboards().then(setBoards).catch(() => {}); }, []);

  if (err) return <div className="err">error: {err}</div>;
  const feed = data?.feed || [];
  const highN = feed.filter((c) => c.confidence_bucket === "high").length;

  return (
    <div>
      <div className="page-head">
        <div>
          <h1 className="page-title">Smart Money</h1>
          <p className="page-sub">Who the smartest money is quietly buying — decoded from SEC filings into plain language. Nothing here is advice.</p>
        </div>
        <div className="sm-filter">
          {["high", "medium", "low"].map((b) => (
            <button key={b} className={conf === b ? "on" : ""} onClick={() => setConf(b)}>{b === "low" ? "all" : b}</button>
          ))}
        </div>
      {/* The 13F lag is stated up front, not in a footnote. A holding can be 45 days stale by the
          time it is public, and a surface that omits that is misleading even when every number on
          it is correct. */}
      <div className="sm-lag" data-testid="reporting-lag">
        <Icon name="alert" size={14} />
        <span>
          <b>Reporting lag.</b> Institutional 13F holdings are disclosed up to <b>45 days</b> after
          the quarter ends, so a position here may already have changed. Insider Form 4 filings are
          far fresher — typically two business days. Every signal below is scored in the{" "}
          <b>Ledger</b> like any other interpretation.
        </span>
      </div>

      </div>

      {data && (
        <div className="sm-summary">
          <span><b>{feed.length}</b> name{feed.length !== 1 ? "s" : ""} converging</span>
          {highN > 0 && <><span className="sm-hi">●</span><span><b className="sm-hi">{highN}</b> high-conviction</span></>}
          <span>·</span>
          {data.delayed_hours > 0
            ? <button className="fresh a nudge" onClick={() => onNav?.("pricing")}>{data.delayed_hours}h delayed · upgrade for live ⚡</button>
            : <span className="fresh g">live · {data.tier}</span>}
          {data.as_of && <span>· as of {data.as_of.slice(0, 10)}</span>}
        </div>
      )}

      <div className="home">
        <div className="feed-col">
          {data === null ? (
            [...Array(4)].map((_, i) => <div key={i} className="card card-skel"><div className="skel" style={{ width: `${60 - i * 6}%` }} /></div>)
          ) : feed.length === 0 ? (
            <div className="empty">No convergences at this threshold right now. Smart money isn't clustering on a name today — that's an honest signal too.</div>
          ) : feed.map((c) => (
            <SmartCard key={c.issuer_entity} c={c} calibration={calibration} horizon={horizon} user={user}
                       onLogin={onLogin} onNav={onNav} onOpenSymbol={onOpenSymbol} onOpenDetail={onOpenDetail} onOpenProfile={onOpenProfile} />
          ))}
        </div>
        <div className="rail"><Leaderboards data={boards} onOpenSymbol={onOpenSymbol} onOpenProfile={onOpenProfile} /></div>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ issuer detail (insight-first)

function Sparkline({ prices }) {
  if (!prices || prices.length < 2) return null;
  const vals = prices.map((p) => p.close);
  const min = Math.min(...vals), max = Math.max(...vals), span = max - min || 1;
  const n = vals.length;
  const pts = vals.map((v, i) => `${(i / (n - 1)) * 100},${34 - ((v - min) / span) * 32}`).join(" ");
  const up = vals[n - 1] >= vals[0];
  const col = up ? "var(--green)" : "var(--red)";
  return (
    <svg className="price-spark" viewBox="0 0 100 36" preserveAspectRatio="none">
      <polyline points={pts} fill="none" stroke={col} strokeWidth="1.4" vectorEffect="non-scaling-stroke" strokeLinejoin="round" />
    </svg>
  );
}

function PriceContext({ symbol, asOf }) {
  const [a, setA] = useState(undefined); // undefined=loading, null=unavailable
  useEffect(() => { let live = true; fetchAsset(symbol).then((d) => live && setA(d.resolved ? d : null)).catch(() => live && setA(null)); return () => { live = false; }; }, [symbol]);
  if (a === undefined) return <div className="price-ctx"><div className="skel" style={{ width: "100%", height: 20 }} /></div>;
  if (!a || !a.prices || a.prices.length < 2) return null;
  const prices = a.prices;
  const day = (asOf || "").slice(0, 10);
  const baseIdx = Math.max(0, prices.findIndex((p) => p.day >= day));
  const base = prices[baseIdx >= 0 ? baseIdx : 0].close;
  const last = prices[prices.length - 1].close;
  const pct = base ? ((last - base) / base) * 100 : 0;
  const dir = pct > 0.5 ? "pos" : pct < -0.5 ? "neg" : "flat";
  const shown = prices.slice(baseIdx >= 0 ? baseIdx : 0);
  return (
    <div className="price-ctx">
      <div>
        <div className={`price-move ${dir}`}>{pct >= 0 ? "+" : ""}{pct.toFixed(1)}%</div>
        <div className="price-since">since the signal ({day})</div>
      </div>
      <Sparkline prices={shown.length >= 2 ? shown : prices} />
    </div>
  );
}

function TrackRecord({ detail, calibration, horizon }) {
  const [stats, setStats] = useState(undefined);
  useEffect(() => {
    if (!detail.symbol) { setStats(null); return; }
    let live = true;
    fetchAsset(detail.symbol).then((d) => live && setStats(d.resolved ? d.name_stats : null)).catch(() => live && setStats(null));
    return () => { live = false; };
  }, [detail.symbol]);
  const cal = calibration?.per_bucket?.[detail.confidence_bucket]?.[String(horizon)];
  const bucketRate = cal && cal.sufficient ? `${Math.round(cal.hit_rate * 100)}%` : null;
  const nameRate = stats && stats.sufficient ? `${Math.round(stats.hit_rate_30d * 100)}%` : null;
  return (
    <div className="track-cards">
      <div className="track-card">
        <div className="track-k">Conviction</div>
        <div className="track-v">{detail.smart_money_score}<span style={{ fontSize: 13, color: "var(--faint)" }}> / 100</span></div>
        <div className="track-sub">{detail.confidence_bucket} band · raw {detail.score.toFixed(2)}</div>
      </div>
      <div className="track-card">
        <div className="track-k">{detail.confidence_bucket}-band base rate</div>
        <div className="track-v">{bucketRate || "—"}</div>
        <div className="track-sub">{cal && cal.sufficient
          ? `beat SPY over ${horizon}d · n=${cal.episodes} resolved`
          : "insufficient resolved sample — not claimed"}</div>
      </div>
      <div className="track-card">
        <div className="track-k">This name's history</div>
        <div className="track-v">{stats === undefined ? "…" : (nameRate || "—")}</div>
        <div className="track-sub">{stats === undefined ? "loading"
          : nameRate ? `beat SPY over 30d · n=${stats.episodes_30d} resolved`
          : "not enough resolved episodes yet"}</div>
      </div>
    </div>
  );
}

export function IssuerDetail({ detail, onBack, calibration, horizon, explanation, onOpenLibrary, onOpenSymbol, onOpenProfile }) {
  const [showFilings, setShowFilings] = useState(false);
  const inp = detail.inputs || {};
  const contributions = inp.contributions || [];
  const prot = detail.story?.protagonists || [];
  const cal = calibration?.per_bucket?.[detail.confidence_bucket]?.[String(horizon)];

  return (
    <div className="issuer">
      <button className="issuer-back" onClick={onBack}><Icon name="arrow" size={15} style={{ transform: "scaleX(-1)" }} /> back to Smart Money</button>

      <div className="issuer-hero">
        <div className={`medallion ${BAND[detail.confidence_bucket] || "band-low"}`}>
          <div className="med-score num">{detail.smart_money_score}</div>
          <div className="med-label">SCORE</div>
        </div>
        <div className="issuer-h">
          <div className="issuer-sym">{detail.symbol || "—"}</div>
          <div className="issuer-name">{detail.name}</div>
          <div className="issuer-meta">
            <span className={`pill pill-${detail.confidence_bucket}`}>{detail.confidence_bucket} conviction</span>
            <Backtested cal={cal} />
            <Freshness iso={inp.freshest_knowable} />
            {detail.symbol && <button className="act mini" onClick={() => onOpenSymbol?.(detail.symbol)}>open {detail.symbol} →</button>}
          </div>
          <p className="issuer-story">{detail.story?.headline || "Converging smart-money activity."}</p>
        </div>
      </div>

      {prot.length > 0 && (
        <div className="sm-block">
          <div className="sm-block-title"><span className="ico"><Icon name="users" size={14} /></span> Who's behind it</div>
          <div className="who-grid">
            {prot.map((p, i) => (
              <button key={i} className="who-card" onClick={() => onOpenProfile?.(p.kind === "insider" ? "insider" : "institution", p.id)}>
                <Avatar name={p.name} />
                <span className="who-meta"><span className="who-name">{p.name}</span><span className="who-role">{p.role}</span></span>
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="sm-block">
        <div className="sm-block-title"><span className="ico"><Icon name="sparkles" size={14} /></span> Why it matters</div>
        {/* Always show a plain read; upgrade to the guarded AI explanation when it arrives (never a stuck skeleton). */}
        <div className="analysis" style={{ marginTop: 0 }}>
          <p className="an-prose" style={{ marginBottom: 8 }}>
            {explanation?.prose || whyItMatters(detail.confidence_bucket, detail.source_classes)}
          </p>
          <div className="an-foot" style={{ marginTop: 0 }}>
            {explanation && !explanation.used_template ? `✦ AI analysis · ${explanation.model_id}` : "Deterministic summary"}
            {explanation?.from_cache ? " · cached" : ""} · context, not advice
          </div>
        </div>
      </div>

      <div className="sm-block">
        <div className="sm-block-title"><span className="ico"><Icon name="target" size={14} /></span> Conviction &amp; track record</div>
        <TrackRecord detail={detail} calibration={calibration} horizon={horizon} />
        <div className="track-note">Base rates are historical hit rates for a bucket or a name where the resolved-episode sample is sufficient — they describe the past, not this trade, and are never a forecast.</div>
      </div>

      {detail.symbol && (
        <div className="sm-block">
          <div className="sm-block-title"><span className="ico"><Icon name="trending" size={14} /></span> Price since the signal</div>
          <PriceContext symbol={detail.symbol} asOf={detail.as_of} />
        </div>
      )}

      {detail.library_links?.length > 0 && onOpenLibrary && (
        <div className="sm-block">
          <div className="sm-block-title"><span className="ico"><Icon name="book" size={14} /></span> Understand this pattern</div>
          <div className="an-learn">
            {detail.library_links.map((l) => <button key={l.slug} className="pill pill-link" onClick={() => onOpenLibrary(l.slug)}>{l.title}</button>)}
          </div>
        </div>
      )}

      <div className="sm-block">
        <button className={`filings-toggle ${showFilings ? "open" : ""}`} onClick={() => setShowFilings((o) => !o)}>
          <span className="ico"><Icon name="news" size={15} /></span>
          The underlying filings ({contributions.length} scored event{contributions.length !== 1 ? "s" : ""})
          <span className="chev"><Icon name="chevron" size={14} /></span>
        </button>
        {showFilings && (
          <div className="filings-wrap">
            <table>
              <thead><tr><th>Type</th><th>Detail</th><th>Filed</th><th>Weight</th></tr></thead>
              <tbody>
                {contributions.map((e, i) => (
                  <tr key={i}>
                    <td><span className={`chip ${e.source_class}`}>{(e.source_class || "").replace(/_/g, " ")}</span></td>
                    <td>{e.subtype?.replace(/_/g, " ")}</td>
                    <td><Freshness iso={e.knowable_time} /></td>
                    <td className="num">{Number(e.decayed_weight).toFixed(3)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="disclaimer">
        {BRAND} is an analytics and education platform. Nothing here is investment advice. Signals describe disclosed
        activity by third parties, with delays as labeled. Backtested rates read “insufficient sample” wherever the
        resolved-episode count is too low to claim a number.
      </div>
    </div>
  );
}
