// Admin dashboard (Slice K): moderation queue, user/tier management, a real feature-flag console,
// and an append-only audit viewer. Every action here hits an admin-only endpoint (tier=admin, TOTP
// at login) and is itself written to the audit log. The flag toggles control real server behaviour;
// the "operational config" panel shows env/key-gated state read-only (a web switch can't set a key).
import { useEffect, useState } from "react";
import {
  adminOverview, adminModeration, adminResolve, adminUsers, adminSetTier, adminSetBanned,
  adminFlags, adminSetFlag, adminAudit,
} from "./api";

const TABS = ["overview", "moderation", "users", "flags", "audit"];

export function AdminView({ user }) {
  const [tab, setTab] = useState("overview");
  if (!user || user.tier !== "admin")
    return <div className="detail"><h2>🛡️ Admin</h2><div className="empty">This area is for administrators only.</div></div>;
  return (
    <div className="detail admin">
      <h2>🛡️ Admin console</h2>
      <div className="meta">Real moderation, user management, feature flags and an append-only audit trail. Every action you take is logged.</div>
      <div className="seg admin-tabs">
        {TABS.map((t) => <button key={t} className={tab === t ? "on" : ""} onClick={() => setTab(t)}>{t}</button>)}
      </div>
      {tab === "overview" && <Overview />}
      {tab === "moderation" && <Moderation />}
      {tab === "users" && <Users />}
      {tab === "flags" && <Flags />}
      {tab === "audit" && <Audit />}
    </div>
  );
}

function Overview() {
  const [d, setD] = useState(null);
  useEffect(() => { adminOverview().then(setD).catch(() => setD({ error: true })); }, []);
  if (!d) return <div className="skel" style={{ width: "60%", marginTop: 14 }} />;
  if (d.error) return <div className="empty">Couldn't load the overview.</div>;
  const o = d.overview;
  const stat = (label, value) => <div className="admin-stat"><div className="n">{value}</div><div className="l">{label}</div></div>;
  return (
    <div>
      <div className="admin-stats">
        {stat("users", o.users.total)}
        {stat("banned", o.users.banned)}
        {stat("trades", o.trades.total)}
        {stat("public trades", o.trades.public)}
        {stat("open reports", o.moderation.open_reports)}
        {stat("hidden items", o.trades.hidden + o.comments.hidden)}
        {stat("audit rows", o.audit_rows)}
      </div>
      <div className="board" style={{ marginTop: 14 }}>
        <div className="board-title">Users by tier</div>
        <div className="admin-tiers">
          {["free", "retail", "pro", "admin"].map((t) => <span key={t} className="chip">{t}: <b>{o.users.by_tier[t] || 0}</b></span>)}
        </div>
      </div>
      <FlagsSummary flags={d.flags} config={d.config} />
    </div>
  );
}

function FlagsSummary({ flags, config }) {
  return (
    <div className="board" style={{ marginTop: 12 }}>
      <div className="board-title">Feature flags</div>
      <div className="admin-tiers">
        {flags.map((f) => <span key={f.name} className={`chip flag-state ${f.enabled ? "on" : "off"}`}>{f.label}: {f.enabled ? "on" : "off"}</span>)}
      </div>
      <div className="board-title" style={{ marginTop: 12 }}>Operational config (env / keys — read-only)</div>
      <div className="admin-tiers">
        {Object.entries(config).map(([k, v]) => <span key={k} className={`chip flag-state ${v.enabled ? "on" : "off"}`}>{k}: {v.enabled ? "connected" : "off"}</span>)}
      </div>
    </div>
  );
}

function Moderation() {
  const [d, setD] = useState(null);
  const [busy, setBusy] = useState(null);
  const load = () => { setD(null); adminModeration().then(setD).catch(() => setD({ queue: [], error: true })); };
  useEffect(load, []);
  const act = async (item, action) => {
    setBusy(`${item.target_type}:${item.target_id}`);
    await adminResolve(item.target_type, item.target_id, action).catch(() => {});
    setBusy(null); load();
  };
  if (!d) return <div className="skel" style={{ width: "60%", marginTop: 14 }} />;
  if (!d.queue.length) return <div className="empty" style={{ marginTop: 14 }}>Nothing in the moderation queue — no open reports. 🎉</div>;
  return (
    <div>
      <div className="meta" style={{ marginTop: 10 }}>Content auto-hides at {d.reports_to_hide} distinct reports, pending your review. Resolving stamps the report (non-destructive) and resets the counter.</div>
      {d.queue.map((item) => {
        const key = `${item.target_type}:${item.target_id}`;
        return (
          <div key={key} className="mod-card">
            <div className="mod-head">
              <span className="chip">{item.target_type}</span>
              <span className="mod-author">@{item.author}</span>
              <span className="mod-reports">{item.reports} report{item.reports > 1 ? "s" : ""}</span>
              {item.hidden ? <span className="chip flag-chip">hidden</span> : <span className="chip flag-state on">visible</span>}
            </div>
            <div className="mod-content">{item.content}</div>
            {item.reasons.length > 0 && <div className="mod-reasons">reasons: {item.reasons.join(" · ")}</div>}
            <div className="mod-actions">
              {!item.hidden && <button disabled={busy === key} onClick={() => act(item, "hide")}>Hide</button>}
              {item.hidden && <button disabled={busy === key} onClick={() => act(item, "unhide")}>Unhide</button>}
              <button className="ghost" disabled={busy === key} onClick={() => act(item, "dismiss")}>Dismiss reports</button>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function Users() {
  const [q, setQ] = useState("");
  const [d, setD] = useState(null);
  const [busy, setBusy] = useState(null);
  const load = (query = "") => { setD(null); adminUsers(query).then(setD).catch(() => setD({ users: [], tiers: [] })); };
  useEffect(() => { load(""); }, []);
  const changeTier = async (u, tier) => {
    if (tier === u.tier) return;
    setBusy(u.id);
    const r = await adminSetTier(u.id, tier).catch(() => ({ error: "failed" }));
    setBusy(null);
    if (r.error) alert(r.error); else load(q);
  };
  const toggleBan = async (u) => {
    setBusy(u.id);
    const r = await adminSetBanned(u.id, !u.banned).catch(() => ({ error: "failed" }));
    setBusy(null);
    if (r.error) alert(r.error); else load(q);
  };
  return (
    <div>
      <div className="user-search">
        <input className="search" placeholder="search email or handle…" value={q}
               onChange={(e) => setQ(e.target.value)}
               onKeyDown={(e) => { if (e.key === "Enter") load(q); }} />
        <button onClick={() => load(q)}>search</button>
      </div>
      {!d ? <div className="skel" style={{ width: "60%", marginTop: 14 }} />
        : !d.users.length ? <div className="empty" style={{ marginTop: 14 }}>No users match.</div>
          : (
            <table className="clusters admin-users" style={{ marginTop: 12 }}>
              <thead><tr><th>email</th><th>handle</th><th>joined</th><th>trades</th><th>reports</th><th>tier</th><th></th></tr></thead>
              <tbody>
                {d.users.map((u) => (
                  <tr key={u.id} className={u.banned ? "banned-row" : ""}>
                    <td>{u.email}{u.banned && <span className="chip flag-chip" style={{ marginLeft: 6 }}>banned</span>}</td>
                    <td>{u.handle ? `@${u.handle}` : <span className="muted">—</span>}</td>
                    <td className="muted">{u.joined}</td>
                    <td className="num">{u.trades}</td>
                    <td className="num">{u.open_reports || 0}</td>
                    <td>
                      {u.tier === "admin" ? <span className="chip">admin</span> : (
                        <select value={u.tier} disabled={busy === u.id} onChange={(e) => changeTier(u, e.target.value)}>
                          {(d.tiers || ["free", "retail", "pro"]).map((t) => <option key={t} value={t}>{t}</option>)}
                        </select>
                      )}
                    </td>
                    <td>{u.tier !== "admin" && (
                      <button className={u.banned ? "" : "ghost danger"} disabled={busy === u.id} onClick={() => toggleBan(u)}>
                        {u.banned ? "unban" : "ban"}
                      </button>
                    )}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
      <div className="disc" style={{ marginTop: 14 }}>Banning drops the account's sessions and hides its public trades. Admin accounts are provisioned via the CLI (they require TOTP), so they can't be re-tiered or banned here.</div>
    </div>
  );
}

function Flags() {
  const [d, setD] = useState(null);
  const [busy, setBusy] = useState(null);
  const load = () => adminFlags().then(setD).catch(() => setD({ flags: [], config: {} }));
  useEffect(() => { load(); }, []);
  const toggle = async (f) => {
    setBusy(f.name);
    await adminSetFlag(f.name, !f.enabled).catch(() => {});
    setBusy(null); load();
  };
  if (!d) return <div className="skel" style={{ width: "60%", marginTop: 14 }} />;
  return (
    <div>
      <div className="meta" style={{ marginTop: 10 }}>These toggles change real server behaviour immediately.</div>
      {d.flags.map((f) => (
        <div key={f.name} className="flag-row">
          <div className="flag-info">
            <div className="flag-name">{f.label}</div>
            <div className="flag-desc">{f.description}</div>
          </div>
          <button className={`toggle ${f.enabled ? "on" : "off"}`} disabled={busy === f.name} onClick={() => toggle(f)}>
            <span className="knob" />{f.enabled ? "on" : "off"}
          </button>
        </div>
      ))}
      <div className="board" style={{ marginTop: 16 }}>
        <div className="board-title">Operational config (controlled by deployment env / keys — read-only)</div>
        {Object.entries(d.config).map(([k, v]) => (
          <div key={k} className="flag-row readonly">
            <div className="flag-info"><div className="flag-name">{k}</div><div className="flag-desc">{v.controlled_by}</div></div>
            <span className={`chip flag-state ${v.enabled ? "on" : "off"}`}>{v.enabled ? "connected" : "off"}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function Audit() {
  const [d, setD] = useState(null);
  const [action, setAction] = useState("");
  const load = (a = "") => { setD(null); adminAudit(a).then(setD).catch(() => setD({ entries: [], actions: [] })); };
  useEffect(() => { load(""); }, []);
  return (
    <div>
      <div className="user-search" style={{ marginTop: 10 }}>
        <select value={action} onChange={(e) => { setAction(e.target.value); load(e.target.value); }}>
          <option value="">all actions</option>
          {(d?.actions || []).map((a) => <option key={a} value={a}>{a}</option>)}
        </select>
        <span className="meta">Append-only — this log cannot be edited or deleted.</span>
      </div>
      {!d ? <div className="skel" style={{ width: "60%", marginTop: 14 }} />
        : !d.entries.length ? <div className="empty" style={{ marginTop: 14 }}>No audit entries.</div>
          : (
            <table className="clusters admin-audit" style={{ marginTop: 12 }}>
              <thead><tr><th>when</th><th>actor</th><th>action</th><th>object</th><th>detail</th></tr></thead>
              <tbody>
                {d.entries.map((e) => (
                  <tr key={e.id}>
                    <td className="muted">{e.at.slice(0, 19).replace("T", " ")}</td>
                    <td>{e.actor || <span className="muted">—</span>}</td>
                    <td><span className="chip">{e.action}</span></td>
                    <td className="muted">{e.object || "—"}</td>
                    <td className="mono">{e.detail ? JSON.stringify(e.detail) : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
    </div>
  );
}
