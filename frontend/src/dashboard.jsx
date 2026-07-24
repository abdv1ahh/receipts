// The Dashboard — the calm command center. Answers one question on open: "what does a trader need
// right now?" A Market Pulse that shows its own drivers, today's biggest opportunities, what matters
// now in the news, the smart-money digest, and what's on the radar. Every tile deep-links to its full
// surface. Numbers come straight from /api/dashboard (real records only); nothing here is fabricated.
import { useEffect, useState } from "react";
import { fetchDashboard } from "./api";
import { Icon } from "./icons.jsx";

const BAND = { high: "band-high", medium: "band-medium", low: "band-low" };
const TONE_LABEL = { risk_on: "Risk-on", mixed: "Mixed", risk_off: "Risk-off" };

const prefersReduced = () =>
  typeof window !== "undefined" && window.matchMedia
    && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

// Count a number up to its target on mount (eased), unless the user prefers reduced motion.
function useCountUp(target, ms = 950) {
  const [v, setV] = useState(() => (prefersReduced() ? target : 0));
  useEffect(() => {
    if (target == null) return;
    if (prefersReduced()) { setV(target); return; }
    let raf, start;
    const tick = (t) => {
      if (!start) start = t;
      const p = Math.min(1, (t - start) / ms);
      setV(Math.round(target * (1 - Math.pow(1 - p, 3))));
      if (p < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => raf && cancelAnimationFrame(raf);
  }, [target, ms]);
  return v;
}

// Render the light **bold** markup the backend uses inside driver text.
function rich(text) {
  return String(text || "").split(/(\*\*[^*]+\*\*)/g).map((p, i) =>
    p.startsWith("**") && p.endsWith("**") ? <b key={i}>{p.slice(2, -2)}</b> : <span key={i}>{p}</span>);
}

const money = (v) => {
  if (v == null) return "—";
  const n = Number(v);
  if (n >= 1e9) return `$${(n / 1e9).toFixed(1)}B`;
  if (n >= 1e6) return `$${(n / 1e6).toFixed(1)}M`;
  if (n >= 1e3) return `$${(n / 1e3).toFixed(0)}K`;
  return `$${Math.round(n)}`;
};

const ago = (iso) => {
  if (!iso) return "";
  const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  if (mins < 1440) return `${Math.round(mins / 60)}h ago`;
  return `${Math.round(mins / 1440)}d ago`;
};

const impactBand = (n) => (n >= 60 ? "high" : n >= 35 ? "medium" : "low");

const greeting = () => {
  const h = new Date().getHours();
  return h < 5 ? "Still up" : h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
};

// ------------------------------------------------------------------ Market Pulse

function MarketPulse({ p }) {
  const score = useCountUp(p.score);
  return (
    <div className="pulse rise rise-1">
      <div className="pulse-l">
        <div className="pulse-kicker"><span className="live-dot" /> Market Pulse</div>
        <div className={`pulse-tone ${p.tone}`}>{TONE_LABEL[p.tone] || "—"}</div>
        <div className="pulse-scorewrap">
          <span className="pulse-score">{score}</span>
          <span className="pulse-score-max">/ 100</span>
        </div>
        <div className="pulse-gauge"><i style={{ width: `${p.score}%` }} /></div>
        <div className="pulse-gauge-scale"><span>defensive</span><span>constructive</span></div>
      </div>
      <div className="pulse-r">
        <p className="pulse-headline">{p.headline}</p>
        <div className="pulse-risk-row">
          <span className={`risk-chip ${p.risk}`}><Icon name="activity" size={13} /> {p.risk} risk</span>
          <span style={{ color: "var(--faint)", fontSize: 12 }}>measures {p.measures}</span>
        </div>
        {p.drivers?.length > 0 ? (
          <div className="pulse-drivers">
            {p.drivers.map((d, i) => (
              <div key={i} className="driver"><span className={`dot ${d.pol}`} /><span>{rich(d.text)}</span></div>
            ))}
          </div>
        ) : (
          <div className="sec-empty" style={{ padding: 0 }}>
            Limited fresh data at the moment — as filings, news and attention flow in, the pulse fills
            out. An honest reading, not a blank one.
          </div>
        )}
        <div className="pulse-inputs-note">
          A transparent read of flow &amp; positioning from real filings, news and attention — not a
          forecast, and not advice.
        </div>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ sections

function Section({ icon, title, count, linkLabel, onLink, riseN, span, children }) {
  return (
    <div className={`sec ${span ? "span-2" : ""} rise rise-${riseN}`}>
      <div className="sec-head">
        <div className="sec-title"><span className="ico"><Icon name={icon} size={16} /></span> {title}</div>
        {count != null && <span className="sec-count">{count}</span>}
        {onLink && <button className="sec-link" onClick={onLink}>{linkLabel} <Icon name="arrow" size={14} /></button>}
      </div>
      {children}
    </div>
  );
}

function Opportunities({ items, highCount, onOpenSymbol, onNav, riseN }) {
  return (
    <Section icon="zap" title="Today's biggest opportunities" span riseN={riseN}
             count={highCount > 0 ? `${highCount} high-conviction` : null}
             linkLabel="Smart Money" onLink={() => onNav("home")}>
      {items.length === 0 ? (
        <div className="sec-empty">No smart-money convergence at this threshold right now — smart money
          isn't clustering on a name today, which is an honest signal too.</div>
      ) : (
        <div className="opp-grid">
          {items.map((o) => (
            <button key={o.issuer_entity} className="opp"
                    onClick={() => (o.symbol ? onOpenSymbol(o.symbol) : onNav("home"))}>
              <div className={`opp-score ${BAND[o.confidence_bucket] || "band-low"}`}>
                <b>{o.smart_money_score}</b><span>SCORE</span>
              </div>
              <div className="opp-body">
                <div className="opp-head">
                  <span className="opp-sym">{o.symbol || o.name}</span>
                  {o.symbol && <span className="opp-name">{o.name}</span>}
                  {o.confidence_bucket === "high" && <span className="pill pill-high">high</span>}
                </div>
                <div className="opp-why">{o.headline || "converging smart-money activity"}</div>
              </div>
              <span className="opp-arrow"><Icon name="chevron" size={18} /></span>
            </button>
          ))}
        </div>
      )}
    </Section>
  );
}

function WhatMatters({ items, onOpenSymbol, onNav, riseN }) {
  return (
    <Section icon="news" title="What matters now" riseN={riseN}
             linkLabel="News" onLink={() => onNav("news")}>
      {items.length === 0 ? (
        <div className="sec-empty">No high-impact developments on the wire in the last two days.</div>
      ) : items.map((n) => {
        const band = impactBand(n.impact || 0);
        const tkr = (n.symbols || [])[0];
        return (
          <button key={n.id} className="dnews"
                  onClick={() => (tkr ? onOpenSymbol(tkr) : onNav("news"))}>
            <span className={`dnews-impact band-${band}`}>{n.impact}</span>
            <span className="dnews-body">
              <span className="dnews-title">{n.headline}</span>
              <span className="dnews-meta">
                {tkr && <span className="dnews-tkr">{tkr}</span>}
                {n.category && <span>{n.category}</span>}
                <span>· {ago(n.knowable_time)}</span>
                {n.ai_generated && <span style={{ color: "var(--accent-2)" }}>✦ AI</span>}
              </span>
            </span>
          </button>
        );
      })}
    </Section>
  );
}

function SmartMoney({ sm, onOpenSymbol, onNav, riseN }) {
  const buys = sm?.biggest_buys || [];
  return (
    <Section icon="signal" title="Smart money" riseN={riseN}
             linkLabel="All activity" onLink={() => onNav("home")}>
      <div className="sec-empty" style={{ padding: "0 2px 10px", color: "var(--muted)" }}>
        Biggest insider buys on the tape
      </div>
      {buys.length === 0 ? (
        <div className="sec-empty">No notable insider purchases in the recent window.</div>
      ) : buys.map((b, i) => (
        <button key={i} className="mrow" onClick={() => (b.symbol ? onOpenSymbol(b.symbol) : onNav("home"))}>
          <span className="mrow-sym">{b.symbol || (b.name || "").slice(0, 6)}</span>
          <span className="mrow-main">{b.insider}</span>
          <span className="mrow-val">{money(b.value_usd)}</span>
        </button>
      ))}
    </Section>
  );
}

function Radar({ events, onOpenSymbol, onNav, riseN }) {
  const fmtDay = (iso) => {
    try {
      const d = new Date(iso + "T00:00:00");
      return { wd: d.toLocaleDateString(undefined, { weekday: "short" }),
               dm: d.toLocaleDateString(undefined, { month: "short", day: "numeric" }) };
    } catch { return { wd: "", dm: iso }; }
  };
  return (
    <Section icon="radar" title="On the radar" span riseN={riseN}
             linkLabel="Calendar" onLink={() => onNav("events")}>
      {(!events || events.length === 0) ? (
        <div className="sec-empty">Nothing major scheduled in the next several days.</div>
      ) : events.map((e) => {
        const d = fmtDay(e.date);
        const isMacro = e.scope === "macro";
        const title = isMacro ? e.title : `${e.symbol || e.title} earnings`;
        const why = isMacro ? (e.moves || e.what) : (e.cross_plane?.length ? "On a name with a live signal" : "Scheduled report");
        return (
          <div key={e.id} className="radar-row">
            <span className="radar-when"><b>{d.wd}</b>{d.dm}{e.time ? ` · ${e.time}` : ""}</span>
            <span className={`radar-kind imp-${e.importance || "low"}`}>{isMacro ? (e.kind || "macro") : "earnings"}</span>
            <span className="radar-body" style={{ cursor: e.symbol ? "pointer" : "default" }}
                  onClick={() => e.symbol && onOpenSymbol(e.symbol)}>
              <span className="radar-title">{title}</span>
              <span className="radar-why">{why}</span>
            </span>
            {(e.cross_plane || []).includes("smart_money") && <span className="radar-xp sm">⚡ smart money</span>}
            {(e.cross_plane || []).includes("attention") && <span className="radar-xp attn">🔥 attention</span>}
          </div>
        );
      })}
    </Section>
  );
}

// ------------------------------------------------------------------ view

function Skeleton() {
  return (
    <div className="dash">
      <div className="dash-top"><div className="skel" style={{ width: 260, height: 28 }} /></div>
      <div className="pulse"><div className="skel" style={{ width: "40%", height: 90 }} />
        <div className="skel" style={{ width: "90%", height: 90 }} /></div>
      <div className="dash-grid">
        {[0, 1].map((i) => <div key={i} className="sec"><div className="skel" style={{ width: "60%", height: 16 }} />
          <div className="skel" style={{ width: "100%", height: 54, marginTop: 12 }} /></div>)}
      </div>
    </div>
  );
}

export function Dashboard({ user, onOpenSymbol, onNav }) {
  const [d, setD] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => { fetchDashboard().then(setD).catch((e) => setErr(String(e))); }, []);

  if (err) return <div className="err">error: {err}</div>;
  if (!d) return <Skeleton />;

  const name = user?.email ? user.email.split("@")[0] : null;
  const dateStr = new Date().toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" });
  const live = d.delayed_hours > 0 ? `${d.delayed_hours}h delayed feed` : "live";

  return (
    <div className="dash">
      <div className="dash-top">
        <div>
          <h1 className="dash-hi">{greeting()}{name ? <>, <span className="accent">{name}</span></> : ""}</h1>
          <div className="dash-date">
            {dateStr}
            <span className="dot-sep">·</span>
            <span className="dash-live"><span className="live-dot" /> {live}</span>
          </div>
        </div>
      </div>

      <MarketPulse p={d.market_pulse} />

      <Opportunities items={d.opportunities || []} highCount={d.high_conviction_count || 0}
                     onOpenSymbol={onOpenSymbol} onNav={onNav} riseN={2} />

      <div className="dash-grid">
        <WhatMatters items={d.news || []} onOpenSymbol={onOpenSymbol} onNav={onNav} riseN={3} />
        <SmartMoney sm={d.smart_money} onOpenSymbol={onOpenSymbol} onNav={onNav} riseN={3} />
      </div>

      <div style={{ marginTop: "var(--s4)" }}>
        <Radar events={d.radar || []} onOpenSymbol={onOpenSymbol} onNav={onNav} riseN={4} />
      </div>
    </div>
  );
}
