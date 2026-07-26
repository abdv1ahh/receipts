// Slice D: pricing, upgrade, and the Pro API keys. Card data never touches us — real upgrades go
// through Stripe Checkout. Until a Stripe key is configured it runs in test mode (no charge),
// clearly labeled. Upgrading flips your tier server-side, which unlocks live signals.
import { useEffect, useState } from "react";
import {
  cancelSub, checkout, createKey, fetchKeys, fetchPlans, fetchReferral, revokeKey, testActivate,
} from "./api";
import { BRAND } from "./brand.js";

function ReferralCard() {
  const [d, setD] = useState(null);
  const [copied, setCopied] = useState(false);
  useEffect(() => { fetchReferral().then(setD).catch(() => {}); }, []);
  if (!d || !d.authenticated) return null;
  const link = `${location.origin}/?ref=${d.code}`;
  const copy = async () => { try { await navigator.clipboard.writeText(link); } catch { /* clipboard blocked */ } setCopied(true); setTimeout(() => setCopied(false), 1500); };
  return (
    <div className="track" style={{ marginTop: 22 }}>
      <div className="board-title" style={{ fontSize: 14 }}>🎁 Invite friends — they get 14 days of Pro free</div>
      <div className="meta">Share your link. Anyone who joins through it starts on a 14-day Pro trial, and you’ve referred {d.referred} {d.referred === 1 ? "person" : "people"} so far.</div>
      <div className="controls" style={{ marginTop: 8 }}>
        <input className="search" style={{ width: 340, maxWidth: "100%" }} readOnly value={link} onFocus={(e) => e.target.select()} />
        <button className="act act-on" onClick={copy}>{copied ? "copied ✓" : "copy link"}</button>
      </div>
    </div>
  );
}

function feats(e) {
  return [
    e.live_signals ? "Live signals (no delay)" : "Signals on a 48h delay",
    `Follow up to ${e.max_follows >= 100000 ? "unlimited" : e.max_follows} names/people`,
    `${e.max_portfolios >= 1000 ? "Unlimited" : e.max_portfolios} shadow portfolio${e.max_portfolios === 1 ? "" : "s"}`,
    e.realtime_alerts ? "Real-time alerts" : "Delayed alerts",
    e.api ? "Pro data API + keys" : "No API access",
  ];
}

function ApiKeys() {
  const [data, setData] = useState(null);
  const [fresh, setFresh] = useState(null);   // raw key shown once
  const load = () => fetchKeys().then(setData).catch(() => setData({ keys: [], api_enabled: false }));
  useEffect(() => { load(); }, []);
  if (!data) return null;
  if (!data.api_enabled) return null;
  const make = async () => { const r = await createKey("api key"); if (r.key) setFresh(r.key); load(); };
  const kill = async (id) => { await revokeKey(id); load(); };
  return (
    <div style={{ marginTop: 22 }}>
      <div className="section">Pro data API keys</div>
      <div className="meta">Scoped, revocable keys, stored hashed. Every response carries a per-key trace so a leaked dataset is traceable to the key. Call <code>GET /api/v1/clusters</code> with <code>Authorization: Bearer &lt;key&gt;</code>.</div>
      <button className="act act-on" onClick={make} style={{ marginTop: 8 }}>+ create API key</button>
      {fresh && <div className="key-fresh">Copy this key now — it is shown only once:<br /><code>{fresh}</code></div>}
      {data.keys.length > 0 && (
        <table className="clusters" style={{ marginTop: 10 }}>
          <thead><tr><th>Key</th><th>Created</th><th>Last used</th><th></th></tr></thead>
          <tbody>
            {data.keys.map((k) => (
              <tr key={k.id}>
                <td className="num">{k.prefix}… {k.revoked && <span className="name">(revoked)</span>}</td>
                <td className="name">{k.created_at.slice(0, 10)}</td>
                <td className="name">{k.last_used_at ? k.last_used_at.slice(0, 10) : "never"}</td>
                <td>{!k.revoked && <button className="linkish" style={{ color: "var(--muted)" }} onClick={() => kill(k.id)}>revoke</button>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

export function PricingView({ user, onUpgraded, onLogin }) {
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState("");
  const [msg, setMsg] = useState(null);
  const load = () => fetchPlans().then(setData).catch(() => setData(null));
  useEffect(() => { load(); }, [user]);
  if (!data) return <div className="detail"><div className="skel" style={{ width: 240 }} /></div>;

  const current = data.current?.plan || "free";
  const pick = async (plan) => {
    if (!user) return onLogin();
    setBusy(plan); setMsg(null);
    if (plan === "free") { await cancelSub(); await onUpgraded(); await load(); setBusy(""); setMsg("Downgraded to Free."); return; }
    const r = await checkout(plan);
    if (r.mode === "stripe" && r.url) { window.location = r.url; return; }
    if (r.mode === "test") { const a = await testActivate(plan); if (a.activated) { await onUpgraded(); await load(); setMsg(`You're on ${plan} (test mode — no charge).`); } }
    else if (r.error) setMsg(r.error);
    setBusy("");
  };

  return (
    <div className="detail">
      <h2>Pricing</h2>
      <div className="meta">
        See what smart money is doing — free. Go live, unlimited, and API-enabled as you grow.
        {!data.provider_configured && <span className="fresh a" style={{ marginLeft: 8 }}>test mode · no real charge</span>}
      </div>
      {msg && <div className="warn" style={{ borderColor: "#2f4a2f", color: "var(--green)", background: "#0f2417" }}>{msg}</div>}
      <div className="plans">
        {data.plans.map((p) => (
          <div key={p.id} className={`plan ${current === p.id ? "plan-current" : ""} ${p.id === "pro" ? "plan-hi" : ""}`}>
            <div className="plan-name">{p.name}</div>
            <div className="plan-price">${p.price}<span className="name">/mo</span></div>
            <ul className="plan-feats">{feats(p.entitlements).map((f, i) => <li key={i}>{f}</li>)}</ul>
            {current === p.id
              ? <button className="act" disabled>current plan</button>
              : <button className={`act ${p.id !== "free" ? "act-on" : ""}`} disabled={busy === p.id} onClick={() => pick(p.id)}>
                  {busy === p.id ? "…" : p.id === "free" ? "downgrade" : `get ${p.name}`}
                </button>}
          </div>
        ))}
      </div>
      {!user && <div className="name" style={{ marginTop: 10 }}>Log in to upgrade.</div>}
      {user && <ReferralCard />}
      {user && <ApiKeys />}
      <div className="disclaimer" style={{ marginTop: 20 }}>
        Payments are handled by Stripe; card data never touches {BRAND} servers. {BRAND} is analytics and
        education, not investment advice.
      </div>
    </div>
  );
}
