// Integration status — one screen listing every external source, whether it is connected, what it
// powers, when it last succeeded, and the last error if any.
//
// This exists so the owner never again has to guess why a panel is empty. Everything here comes
// from the server's source registry joined to real feed and job health; nothing is hardcoded in
// the client, so this page cannot drift from what the app is actually doing.
import { useEffect, useState } from "react";
import { fetchIntegrations } from "./api";
import { Icon } from "./icons.jsx";
import { LoadError } from "./shell.jsx";

const STATE = {
  connected: { label: "Connected", cls: "ok" },
  needs_key: { label: "Needs a free key", cls: "warn" },
  unavailable: { label: "No free access", cls: "off" },
};

const ago = (iso) => {
  if (!iso) return "never";
  const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  if (mins < 1440) return `${Math.round(mins / 60)}h ago`;
  return `${Math.round(mins / 1440)}d ago`;
};

const n = (v) => (v == null ? "—" : Number(v).toLocaleString());

function Source({ s }) {
  const st = STATE[s.state] || STATE.unavailable;
  const stale = s.state === "connected" && s.last_success_at &&
    Date.now() - new Date(s.last_success_at).getTime() > 3 * 86400000;
  return (
    <div className={`intg intg-${st.cls}`}>
      <div className="intg-top">
        <span className={`intg-dot ${st.cls}`} />
        <b className="intg-name">{s.label}</b>
        <span className="intg-kind">{s.kind}</span>
        <span className={`intg-state ${st.cls}`}>{st.label}</span>
        <span className="spacer" />
        {/* "connected · last ok never" reads as a contradiction. A source we fetch on demand
            (CoinGecko, Tiingo) has no scheduled run to report, so say that instead. */}
        <span className="intg-when" title={s.last_success_at || "fetched on demand; no scheduled run"}>
          {s.state !== "connected" ? "—"
            : s.last_success_at ? `last ok ${ago(s.last_success_at)}`
            : "on demand"}
        </span>
      </div>

      <div className="intg-powers">Powers: {s.powers}</div>
      {s.note && <div className="intg-note">{s.note}</div>}

      {stale && (
        <div className="intg-warn">
          Connected, but nothing new in over three days. Check the worker logs for this source.
        </div>
      )}
      {/* The error TEXT is admin-only server-side (it can carry a request URL). Everyone else
          still learns the run failed, which is what explains an empty panel. */}
      {s.last_error ? <div className="intg-err">Last error: {s.last_error}</div>
        : s.failing ? <div className="intg-err">Its last scheduled run failed. Check the worker logs.</div>
        : null}

      {s.state === "needs_key" && s.signup_url && (
        <div className="intg-connect">
          <a className="act act-on" href={s.signup_url} target="_blank" rel="noreferrer noopener">
            Get a free key <Icon name="arrow" size={13} />
          </a>
          <span className="intg-env">
            then set {s.env.map((e, i) => <span key={e}>{i > 0 && " and "}<code>{e}</code></span>)} in <code>.env</code>
          </span>
        </div>
      )}

      {(s.records != null || s.feeds?.length > 0) && (
        <div className="intg-stats">
          {s.records != null && <span><b>{n(s.records)}</b> records</span>}
          {s.rejects != null && s.rejects > 0 && <span><b>{n(s.rejects)}</b> rejected</span>}
          {s.feeds?.map((f) => (
            <span key={f.source} title={`freshest record ${f.freshest || "—"}`}>
              {f.source} · {ago(f.last_success_at)}
            </span>
          ))}
          {s.jobs?.map((j) => (
            <span key={j.job} className={j.status === "error" ? "bad" : ""}>
              job {j.job} · {j.status}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

export function IntegrationsView({ onLogin }) {
  const [d, setD] = useState(undefined);   // undefined loading · null failed
  const load = () => { setD(undefined); fetchIntegrations().then(setD).catch(() => setD(null)); };
  useEffect(load, []);

  if (d === null) return <LoadError what="the integration status" onRetry={load} />;
  if (d && d.authenticated === false) {
    return (
      <div>
        <div className="page-head"><h1 className="page-title">Integrations</h1></div>
        <div className="empty" style={{ marginTop: 14 }}>
          Log in to see which data sources are connected and how they are behaving.
          <div style={{ marginTop: 10 }}><button className="act" onClick={onLogin}>log in</button></div>
        </div>
      </div>
    );
  }

  return (
    <div>
      <div className="page-head">
        <div>
          <h1 className="page-title">Integrations</h1>
          <p className="page-sub">
            Every external source this product reads, and exactly what state it is in. Nothing here
            is inferred — it is the live registry joined to real feed and job health.
          </p>
        </div>
      </div>

      {d === undefined ? (
        [0, 1, 2].map((i) => <div key={i} className="intg"><div className="skel" style={{ width: `${70 - i * 10}%` }} /></div>)
      ) : (
        <>
          <div className="intg-summary">
            <div className="intg-sum ok"><b>{d.counts.connected}</b><span>connected</span></div>
            <div className="intg-sum warn"><b>{d.counts.needs_key}</b><span>need a free key</span></div>
            <div className="intg-sum off"><b>{d.counts.unavailable}</b><span>no free access</span></div>
          </div>
          {d.sources.map((s) => <Source key={s.key} s={s} />)}
        </>
      )}

      <div className="disc" style={{ marginTop: 16 }}>
        A source with no free path is left disconnected rather than faked. A source that needs a key
        keeps everything else working and tells you where to get one. Neither ever produces a number.
      </div>
    </div>
  );
}
