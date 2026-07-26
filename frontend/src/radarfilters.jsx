// Saved filter sets and their subscriptions (the Phase 4 remainder).
//
// "A user watching Gulf energy policy and one watching crypto regulation want entirely different
// streams." A filter is five dimensions; saving one is a name and a button; subscribing to one is
// a separate, deliberate second decision, because turning a view into email is not the same act as
// making the view.
//
// The live match count is shown while editing. A filter that matches nothing should be obvious
// before it is saved, not after a week of silence.
import { useEffect, useState } from "react";
import { deleteRadarFilter, fetchRadarFilters, previewRadarFilter, saveRadarFilter } from "./api";
import { Icon } from "./icons.jsx";

const HORIZONS = ["hours", "days", "weeks", "months"];
const EMPTY = { categories: [], geo: [], horizons: [], sources: [], min_confidence: 0 };

function Chip({ on, onClick, children }) {
  return (
    <button type="button" className={`chip ${on ? "chip-on" : "chip-off"}`} onClick={onClick}>
      {children}
    </button>
  );
}

function SpecEditor({ spec, setSpec, categories, geos, sources }) {
  const toggle = (key, val) => {
    const cur = spec[key] || [];
    setSpec({ ...spec, [key]: cur.includes(val) ? cur.filter((x) => x !== val) : [...cur, val] });
  };
  const row = (label, key, values, hint) => (
    values.length > 0 && (
      <div className="rf-row">
        <span className="rf-l">{label}</span>
        <div className="rf-chips">
          {values.map((v) => (
            <Chip key={v} on={(spec[key] || []).includes(v)} onClick={() => toggle(key, v)}>
              {String(v).replace(/_/g, " ")}
            </Chip>
          ))}
        </div>
        {hint && <span className="rf-hint">{hint}</span>}
      </div>
    )
  );

  return (
    <div className="rf-spec">
      {row("Category", "categories", categories)}
      {row("Horizon", "horizons", HORIZONS)}
      {row("Affects", "geo", geos, "Where the claim LANDS, not where it was published.")}
      {row("Source", "sources", sources)}
      <div className="rf-row">
        <span className="rf-l">Confidence floor</span>
        <input type="range" min="0" max="0.9" step="0.05" value={spec.min_confidence || 0}
               onChange={(e) => setSpec({ ...spec, min_confidence: Number(e.target.value) })} />
        <span className="rf-hint">
          {spec.min_confidence > 0
            ? `at least ${Math.round(spec.min_confidence * 100)}% confident`
            : "any confidence"}
        </span>
      </div>
    </div>
  );
}

export function SavedFilters({ claims, activeSpec, onApply }) {
  const [d, setD] = useState(undefined);
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState("");
  const [spec, setSpec] = useState(EMPTY);
  const [sub, setSub] = useState({ subscribed: false, channel: "email", webhook_url: "", throttle_mins: 360 });
  const [match, setMatch] = useState(null);
  const [err, setErr] = useState(null);

  const load = () => fetchRadarFilters().then(setD).catch(() => setD(null));
  useEffect(() => { load(); }, []);

  // Preview against the server, not the loaded page: a filter is evaluated over the whole recent
  // store, and matching only what happens to be on screen would overstate how quiet it is.
  useEffect(() => {
    if (!editing) return;
    const t = setTimeout(() => {
      previewRadarFilter({ name: name || "preview", spec }).then((r) => setMatch(r?.matched ?? null))
        .catch(() => setMatch(null));
    }, 350);
    return () => clearTimeout(t);
  }, [spec, editing, name]);

  if (!d?.authenticated) return null;

  const categories = [...new Set((claims || []).map((c) => c.category).filter(Boolean))].sort();
  const geos = [...new Set((claims || []).flatMap((c) => c.geo || []).filter(Boolean))].sort().slice(0, 24);
  const sources = [...new Set((claims || []).map((c) => c.source).filter(Boolean))].sort();

  const save = async () => {
    setErr(null);
    const r = await saveRadarFilter({ name, spec, ...sub }).catch(() => ({ error: "could not save" }));
    if (r.error) { setErr(r.error); return; }
    setEditing(false); setName(""); setSpec(EMPTY); setSub({ ...sub, subscribed: false });
    load();
  };

  return (
    <div className="rf">
      <div className="rf-head">
        <Icon name="filter" size={15} />
        <span className="rf-title">Saved filters</span>
        <div className="rf-saved">
          {(d.filters || []).map((f) => {
            const on = JSON.stringify(f.spec) === JSON.stringify(activeSpec);
            return (
              <span key={f.id} className={`rf-pill ${on ? "on" : ""}`}>
                <button onClick={() => onApply(on ? null : f.spec)}>
                  {f.name}
                  {f.subscribed && <Icon name="bell" size={11} style={{ marginLeft: 5 }} />}
                </button>
                <button className="rf-x" title="delete"
                        onClick={async () => { await deleteRadarFilter(f.id); load(); }}>×</button>
              </span>
            );
          })}
          {(d.filters || []).length === 0 && !editing && (
            <span className="rf-empty">None yet — build one and it becomes a one-click stream.</span>
          )}
        </div>
        <button className="act" style={{ marginLeft: "auto" }} onClick={() => setEditing(!editing)}>
          {editing ? "cancel" : "new filter"}
        </button>
      </div>

      {editing && (
        <div className="rf-editor">
          <SpecEditor spec={spec} setSpec={setSpec} categories={categories} geos={geos} sources={sources} />

          <div className="rf-row">
            <span className="rf-l">Name</span>
            <input className="rf-name" value={name} onChange={(e) => setName(e.target.value)}
                   placeholder="Gulf energy policy" />
            <span className="rf-hint">
              {match == null ? "" : match === 0
                ? "matches nothing in the last two weeks — loosen it, or it will stay silent"
                : `matches ${match} of the last two weeks' interpretations`}
            </span>
          </div>

          <div className="rf-row">
            <label className="rf-sub">
              <input type="checkbox" checked={sub.subscribed}
                     onChange={(e) => setSub({ ...sub, subscribed: e.target.checked })} />
              Alert me when something new matches
            </label>
            {sub.subscribed && (
              <>
                <select value={sub.channel} onChange={(e) => setSub({ ...sub, channel: e.target.value })}>
                  <option value="email">by email</option>
                  <option value="webhook">to a webhook</option>
                </select>
                {sub.channel === "webhook" && (
                  <input className="rf-name" placeholder="https://…" value={sub.webhook_url}
                         onChange={(e) => setSub({ ...sub, webhook_url: e.target.value })} />
                )}
                <select value={sub.throttle_mins}
                        onChange={(e) => setSub({ ...sub, throttle_mins: Number(e.target.value) })}>
                  <option value={60}>at most hourly</option>
                  <option value={360}>at most every 6 hours</option>
                  <option value={1440}>at most daily</option>
                </select>
              </>
            )}
          </div>
          {sub.subscribed && (
            <p className="rf-hint" style={{ marginTop: 2 }}>
              Nothing is sent when nothing matches — an alert that says “no news” is the noise a
              throttle exists to prevent.
            </p>
          )}

          {err && <div className="warn" style={{ marginTop: 8 }}>{err}</div>}
          <div className="controls" style={{ marginTop: 10 }}>
            <button className="act act-on" onClick={save} disabled={!name.trim()}>save filter</button>
          </div>
        </div>
      )}
    </div>
  );
}

/** The interpretation history on a threaded card — how the reading changed as the story developed.
 *  Collapsed by default: the current reading is the answer, the history is the evidence that the
 *  system will change its mind in public. */
export function ThreadHistory({ claim }) {
  const [open, setOpen] = useState(false);
  if (!claim.revisions) return null;
  const when = (iso) => new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });

  return (
    <div className="rd-thread">
      <button className="rd-thread-head" onClick={() => setOpen(!open)}>
        <Icon name="layers" size={13} />
        <b>Updated as this developed</b>
        <span className="rd-thread-sum">{claim.changed?.summary}</span>
        <span className="rd-thread-tog">{open ? "hide" : `${claim.revisions} earlier reading${claim.revisions === 1 ? "" : "s"}`}</span>
      </button>
      {open && (
        <ol className="rd-thread-list">
          {(claim.history || []).map((h) => (
            <li key={h.id}>
              <span className="rd-thread-when">{when(h.created_at)}</span>
              <span className="rd-thread-conf">{Math.round((h.confidence || 0) * 100)}% confident</span>
              <p>{h.mechanism}</p>
              <span className="rd-thread-note">
                Still scored in the Ledger — a revised call is not a withdrawn one.
              </span>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
