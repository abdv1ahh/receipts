// Slice B surfaces: the in-app notifications feed, alert settings (+ your follows), and the
// Daily Smart-Money Brief. These make TradeOS reach out instead of waiting to be visited.
import { useEffect, useState } from "react";
import {
  fetchAlertPrefs, fetchBrief, fetchFollows, fetchNotifications, markNotificationsRead,
  removeFollow, saveAlertPrefs,
} from "./api";
import { Backtested } from "./components.jsx";

function timeAgo(iso) {
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
}

const NOTIF_ICON = { high_conviction: "🔥", followed_symbol: "⭐", followed_actor: "👤" };

function LoginGate({ label, onLogin }) {
  return (
    <div className="detail">
      <h2>{label}</h2>
      <div className="empty" style={{ marginTop: 10 }}>
        Log in to {label.toLowerCase()}. Free accounts get alerts on the same 48h delay as the feed;
        paid tiers get them in real time.
        <div style={{ marginTop: 10 }}><button className="act" onClick={onLogin}>log in</button></div>
      </div>
    </div>
  );
}

export function NotificationsView({ onOpenSymbol, onLogin, onChanged }) {
  const [data, setData] = useState(null);
  useEffect(() => {
    fetchNotifications().then((d) => {
      setData(d);
      if (d.authenticated && d.unread > 0) markNotificationsRead().then(() => onChanged && onChanged());
    }).catch(() => setData({ authenticated: false, notifications: [] }));
  }, []);
  if (!data) return <div className="detail"><div className="skel" style={{ width: 220 }} /></div>;
  if (!data.authenticated) return <LoginGate label="Notifications" onLogin={onLogin} />;
  return (
    <div className="detail">
      <h2>Notifications</h2>
      <div className="meta">Alerts fire when smart money converges on a name, or when someone you follow files. Tune them under Alerts.</div>
      {data.notifications.length === 0 ? (
        <div className="empty" style={{ marginTop: 12 }}>No alerts yet. Follow some names or people, then check back — or an admin can run the alert engine.</div>
      ) : (
        <div className="notif-list">
          {data.notifications.map((n) => (
            <button key={n.id} className={`notif ${n.read ? "" : "notif-unread"}`} onClick={() => n.symbol && onOpenSymbol(n.symbol)}>
              <span className="notif-ico">{NOTIF_ICON[n.kind] || "•"}</span>
              <span className="notif-main">
                <span className="notif-title">{n.title}</span>
                <span className="notif-body">{n.body}</span>
              </span>
              <span className="notif-time">{timeAgo(n.created_at)}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function Toggle({ on, onChange, label, hint }) {
  return (
    <div className="toggle-row" onClick={() => onChange(!on)}>
      <div><div className="toggle-label">{label}</div>{hint && <div className="toggle-hint">{hint}</div>}</div>
      <span className={`switch ${on ? "switch-on" : ""}`}><span className="knob" /></span>
    </div>
  );
}

export function AlertsView({ onLogin, onOpenSymbol }) {
  const [prefs, setPrefs] = useState(null);
  const [follows, setFollows] = useState(null);
  const [authed, setAuthed] = useState(true);
  const [saved, setSaved] = useState(false);
  useEffect(() => {
    fetchAlertPrefs().then((d) => { setAuthed(d.authenticated); setPrefs(d.prefs); }).catch(() => setAuthed(false));
    fetchFollows().then((d) => setFollows(d.follows || [])).catch(() => setFollows([]));
  }, []);
  const save = async (next) => { setPrefs(next); await saveAlertPrefs(next); setSaved(true); setTimeout(() => setSaved(false), 1500); };
  const unfollow = async (id) => { await removeFollow(id); setFollows((f) => f.filter((x) => x.id !== id)); };
  if (!authed) return <LoginGate label="Alerts" onLogin={onLogin} />;
  if (!prefs) return <div className="detail"><div className="skel" style={{ width: 220 }} /></div>;
  return (
    <div className="detail">
      <h2>Alerts {saved && <span className="fresh g" style={{ marginLeft: 8 }}>saved ✓</span>}</h2>
      <div className="meta">Choose what reaches out to you. Everything respects your tier: free alerts run on the 48h delay, paid tiers are live.</div>
      <Toggle on={prefs.new_high_conviction} label="New high-conviction convergence"
              hint={`Alert when any name crosses a Smart Money Score of ${prefs.min_score}.`}
              onChange={(v) => save({ ...prefs, new_high_conviction: v })} />
      <div className="toggle-row" style={{ cursor: "default" }}>
        <div><div className="toggle-label">Score threshold</div><div className="toggle-hint">Only alert on scores at or above this.</div></div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <input type="range" min="40" max="95" value={prefs.min_score}
                 onChange={(e) => setPrefs({ ...prefs, min_score: Number(e.target.value) })}
                 onMouseUp={(e) => save({ ...prefs, min_score: Number(e.target.value) })} />
          <b className="num" style={{ width: 28 }}>{prefs.min_score}</b>
        </div>
      </div>
      <Toggle on={prefs.followed_activity} label="Activity on names & people I follow"
              hint="Alert when a followed ticker converges or a followed insider/fund files."
              onChange={(v) => save({ ...prefs, followed_activity: v })} />
      <Toggle on={prefs.email_enabled} label="Email me a digest"
              hint="Queues a digest email. No email provider is configured yet, so digests stay queued until one is connected."
              onChange={(v) => save({ ...prefs, email_enabled: v })} />

      <div className="section">Following {follows ? `(${follows.length})` : ""}</div>
      {!follows ? <div className="skel" style={{ width: "40%" }} />
        : follows.length === 0 ? <div className="name">Not following anything yet. Hit “follow” on a name or a person.</div>
        : (
          <div className="follow-list">
            {follows.map((f) => (
              <div key={f.id} className="follow-chip">
                <span className={`pill pill-${f.kind === "symbol" ? "high" : "low"}`}>{f.kind}</span>
                <button className="linkish" onClick={() => f.kind === "symbol" && onOpenSymbol(f.ref)}>{f.label || f.ref}</button>
                <button className="linkish" style={{ color: "var(--muted)" }} onClick={() => unfollow(f.id)}>remove</button>
              </div>
            ))}
          </div>
        )}
    </div>
  );
}

export function BriefView({ calibration, horizon, onOpenSymbol, onOpenProfile }) {
  const [b, setB] = useState(null);
  useEffect(() => { fetchBrief().then(setB).catch(() => setB(null)); }, []);
  if (!b) return <div className="detail"><div className="skel" style={{ width: 260 }} /></div>;
  const calFor = (bucket) => calibration?.per_bucket?.[bucket]?.[String(horizon)];
  const money = (v) => (v == null ? "—" : "$" + Number(v).toLocaleString());
  return (
    <div className="detail">
      <h2>Daily Smart-Money Brief</h2>
      <div className="meta">
        {b.delayed_hours > 0 ? <span className="fresh a">{b.delayed_hours}h delayed</span> : <span className="fresh g">live</span>}
        {b.as_of ? ` · as of ${b.as_of.slice(0, 10)}` : ""}
      </div>
      <p className="explain-prose" style={{ marginTop: 10 }}>{b.intro}</p>

      <div className="section">Top convergences</div>
      {b.top_convergences.map((c) => (
        <button key={c.issuer_entity} className="brief-row" onClick={() => c.symbol && onOpenSymbol(c.symbol)}>
          <span className={`brief-score band-${c.confidence_bucket}`}>{c.smart_money_score}</span>
          <span className="brief-main"><b>{c.symbol || c.name}</b> <span className="name">{c.headline}</span></span>
          <Backtested cal={calFor(c.confidence_bucket)} />
        </button>
      ))}

      <div className="section">Biggest insider buys</div>
      {b.biggest_buys.map((x, i) => (
        <button key={i} className="brief-row" onClick={() => x.symbol && onOpenSymbol(x.symbol)}>
          <span className="brief-main"><b>{x.symbol || x.name}</b> <span className="name">{x.insider} · {x.date}</span></span>
          <b className="num">{money(x.value_usd)}</b>
        </button>
      ))}

      <div className="section">New activist stakes</div>
      {b.new_activist_stakes.map((a, i) => (
        <button key={i} className="brief-row" onClick={() => onOpenProfile("institution", a.filer_entity)}>
          <span className="brief-main"><b>{a.symbol || a.issuer}</b> <span className="name">{a.filer} · {a.date}</span></span>
          <span className="pill pill-medium">13D</span>
        </button>
      ))}
    </div>
  );
}
