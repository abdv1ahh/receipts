// The Morning Brief — the reason to open TradeOS before your charts. One cross-plane briefing: an AI
// executive summary, the names you follow, impact-ranked "what changed overnight" news (Intelligence
// plane), and the smart-money convergence digest (Signal plane). Degrades to deterministic prose.
import { useEffect, useState } from "react";
import { fetchBrief, fetchJobs } from "./api";
import { NewsCard } from "./news.jsx";

function AutoUpdate() {
  const [j, setJ] = useState(null);
  useEffect(() => { fetchJobs().then(setJ).catch(() => {}); }, []);
  const runs = (j?.jobs || []).map((x) => x.last_run).filter(Boolean).sort();
  if (runs.length === 0) return null;
  const mins = Math.round((Date.now() - new Date(runs[runs.length - 1]).getTime()) / 60000);
  const ago = mins < 1 ? "just now" : mins < 60 ? `${mins}m ago` : `${Math.round(mins / 60)}h ago`;
  const ok = (j.jobs || []).filter((x) => x.status === "ok").length;
  return <span className="auto-upd" title={`${ok}/${j.jobs.length} update jobs healthy`}><i className="live-dot" /> auto-updating · last refresh {ago}</span>;
}

export function BriefView({ user, onOpenSymbol, onOpenProfile, onNav }) {
  const [b, setB] = useState(null);
  const [err, setErr] = useState(null);
  useEffect(() => { fetchBrief().then(setB).catch((e) => setErr(String(e))); }, []);

  if (err) return <div className="err">error: {err}</div>;
  if (!b) return <div className="brief"><div className="brief-hero"><div className="skel" style={{ width: "55%", height: 26 }} /><div className="skel" style={{ width: "85%", marginTop: 14 }} /></div></div>;

  const money = (v) => (v == null ? "—" : "$" + Number(v).toLocaleString());
  const es = b.executive_summary || {};
  const sm = b.smart_money || {};

  return (
    <div className="brief">
      <div className="brief-hero">
        <div className="brief-hero-head">
          <div>
            <div className="brief-kicker">MORNING BRIEF · {b.date}</div>
            <h1 className="brief-title">What changed overnight</h1>
          </div>
          <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 4 }}>
            <span className={b.delayed_hours > 0 ? "fresh a" : "fresh g"}>
              {b.delayed_hours > 0 ? `${b.delayed_hours}h delayed` : "live"} · {b.tier}
            </span>
            <AutoUpdate />
          </div>
        </div>
        <p className="brief-exec">{es.text}</p>
        <div className="brief-exec-tag">
          <span className={`ai-tag ${es.used_template ? "" : "ai-on"}`}>{es.used_template ? "auto-generated" : "✦ AI summary"}</span>
          <span className="dot-sep">·</span> grounded in the items below, not advice
        </div>
      </div>

      {b.your_names ? (
        <section className="brief-sec">
          <div className="section">
            Your names
            {b.your_names.with_signal?.length > 0 && (
              <span className="sig-badge" style={{ marginLeft: 8 }} title="Smart money is converging on these">⚡ {b.your_names.with_signal.join(" · ")}</span>
            )}
          </div>
          {b.your_names.news.length === 0
            ? <div className="name">No fresh news on the names you follow right now — that's an honest signal too.</div>
            : b.your_names.news.map((it) => <NewsCard key={it.id} it={it} onOpenSymbol={onOpenSymbol} />)}
        </section>
      ) : user ? (
        <div className="brief-nudge">
          Follow a few tickers to get a brief tuned to your names.
          <button className="linkish" onClick={() => onNav && onNav("news")}>Browse news →</button>
        </div>
      ) : null}

      <section className="brief-sec">
        <div className="section">What changed overnight</div>
        {(b.what_changed || []).map((it) => <NewsCard key={it.id} it={it} onOpenSymbol={onOpenSymbol} />)}
      </section>

      {b.crowd_watching?.length > 0 && (
        <section className="brief-sec">
          <div className="section">What the crowd is watching</div>
          {b.crowd_watching.slice(0, 5).map((r) => (
            <div key={r.symbol} className="crowd-row">
              <button className="tkr" onClick={() => onOpenSymbol(r.symbol)}>{r.symbol}</button>
              {r.velocity != null && <span className="crowd-vel">{r.velocity}× usual attention</span>}
              {r.flags?.map((f) => <span key={f} className="chip flag-chip">⚠ {f.replace("_", " ")}</span>)}
              <span className="crowd-why">{r.why?.text}</span>
            </div>
          ))}
        </section>
      )}

      {b.whats_coming?.length > 0 && (
        <section className="brief-sec">
          <div className="section">What's coming</div>
          {b.whats_coming.map((e) => (
            <div key={e.id} className="crowd-row">
              {e.scope === "company"
                ? <button className="tkr" onClick={() => onOpenSymbol(e.symbol)}>{e.symbol}</button>
                : <span className={`ev-kind imp-${e.importance}`}>{(e.kind || "macro").toUpperCase()}</span>}
              <span className="crowd-vel">{new Date(e.date + "T00:00:00").toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" })}{e.time ? ` · ${e.time}` : ""}</span>
              {(e.cross_plane || []).map((f) => <span key={f} className={`xp xp-${f}`}>{f === "smart_money" ? "⚡ smart money" : "🔥 attention"}</span>)}
              <span className="crowd-why">{e.scope === "company" ? `${e.title.replace(/ earnings$/, "")} reports${e.meta?.eps_forecast ? ` · est ${e.meta.eps_forecast}` : ""}` : e.moves}</span>
            </div>
          ))}
        </section>
      )}

      <section className="brief-sec">
        <div className="section">Smart money today</div>
        <p className="meta" style={{ marginBottom: 10 }}>{sm.intro}</p>
        <div className="sm-grid">
          <div className="sm-col">
            <div className="sm-h">Top convergences</div>
            {(sm.top_convergences || []).map((c) => (
              <button key={c.issuer_entity} className="brief-row" onClick={() => c.symbol && onOpenSymbol(c.symbol)}>
                <span className={`brief-score band-${c.confidence_bucket}`}>{c.smart_money_score}</span>
                <span className="brief-main"><b>{c.symbol || c.name}</b> <span className="name">{c.headline}</span></span>
              </button>
            ))}
          </div>
          <div className="sm-col">
            <div className="sm-h">Biggest insider buys</div>
            {(sm.biggest_buys || []).map((x, i) => (
              <button key={i} className="brief-row" onClick={() => x.symbol && onOpenSymbol(x.symbol)}>
                <span className="brief-main"><b>{x.symbol || x.name}</b> <span className="name">{x.insider}</span></span>
                <b className="num">{money(x.value_usd)}</b>
              </button>
            ))}
          </div>
          <div className="sm-col">
            <div className="sm-h">New activist stakes</div>
            {(sm.new_activist_stakes || []).map((a, i) => (
              <button key={i} className="brief-row" onClick={() => onOpenProfile("institution", a.filer_entity)}>
                <span className="brief-main"><b>{a.symbol || a.issuer}</b> <span className="name">{a.filer}</span></span>
                <span className="pill pill-medium">13D</span>
              </button>
            ))}
          </div>
        </div>
      </section>

      <div className="src-strip brief-src">
        {(b.sources_status || []).map((s) => (
          <span key={s.key} className={`src-dot ${s.state === "connected" ? "on" : "off"}`}
                title={`${s.state}${s.freshest ? ` · ${s.freshest.slice(0, 10)}` : ""}`}><i /> {s.label}</span>
        ))}
      </div>
    </div>
  );
}
