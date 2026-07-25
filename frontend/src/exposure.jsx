// Exposure — replaces the position tracker.
//
// A broker already shows what you own and what it is worth, better and with real prices. Building
// a worse version of that was the honest criticism of the old Portfolio surface. This answers the
// question a broker cannot: given what I hold, which live events actually reach me, and how?
//
// Every link on this page names its path. "You are exposed to Asia" is worthless; "two of your
// holdings have live claims naming Asia, here they are" is a statement you can disagree with.
import { useEffect, useState } from "react";
import { fetchExposure } from "./api";
import { Icon } from "./icons.jsx";
import { EmptyState, LoadError } from "./shell.jsx";

const pct = (v) => `${Math.round((v || 0) * 100)}%`;

function Summary({ s, home }) {
  return (
    <div className="exp-summary">
      <div className="exp-line">{s.line}.</div>
      <div className="exp-stats">
        <div><b>{s.holdings}</b><span>holdings watched</span></div>
        <div><b>{s.with_live_claims}</b><span>with a live claim</span></div>
        <div><b>{s.countries_reached}</b><span>countries reached</span></div>
        <div><b>{s.upcoming_events}</b><span>scheduled events ahead</span></div>
      </div>
      {!home && (
        <div className="exp-hint">
          <Icon name="compass" size={13} /> Set a country on the Radar or the map to see which
          trade corridors connect you to what your holdings touch.
        </div>
      )}
    </div>
  );
}

function TouchingClaims({ claims }) {
  if (!claims.length) {
    return (
      <EmptyState title="No live interpretation names anything you hold">
        That is a real answer, not an empty one — nothing the engine has interpreted in the last
        three weeks reaches your list.
      </EmptyState>
    );
  }
  return (
    <div className="sec">
      <div className="sec-head"><div className="sec-title">
        <span className="ico"><Icon name="zap" size={15} /></span> What reaches you, and how
      </div></div>
      {claims.map((c) => (
        <div key={c.id} className="exp-claim">
          <div className="exp-claim-top">
            <span className="rd-conf band-medium">{pct(c.confidence)}</span>
            {c.your_holdings.map((h) => (
              <span key={h.symbol} className={`rd-chip dir-${h.direction}`}>
                <b>{h.direction === "up" ? "▲" : "▼"}</b> {h.symbol}<em>{h.magnitude}</em>
              </span>
            ))}
            <span className="spacer" />
            <span className="rd-horizon">over {c.horizon}</span>
          </div>
          <p className="exp-mech">{c.mechanism}</p>
          {c.url && (
            <a className="rd-src" href={c.url} target="_blank" rel="noreferrer noopener">
              {c.headline || "source"} ↗
            </a>
          )}
        </div>
      ))}
    </div>
  );
}

function Reach({ reach }) {
  if (!reach.length) return null;
  return (
    <div className="sec">
      <div className="sec-head"><div className="sec-title">Where your holdings reach</div></div>
      {reach.map((r) => (
        <div key={r.country} className="exp-reach">
          <span className="exp-iso">{r.country}</span>
          <span className="exp-name">{r.name}</span>
          <span className="exp-via">via {r.via.join(", ")}</span>
          <span className="spacer" />
          <span className="name">{r.claims} claim{r.claims === 1 ? "" : "s"}</span>
        </div>
      ))}
    </div>
  );
}

function Corridors({ corridors, home }) {
  if (!home) return null;
  if (!corridors.length) {
    return (
      <div className="sec">
        <div className="sec-head"><div className="sec-title">Corridors from {home}</div></div>
        <div className="sec-empty">
          None of the places your holdings reach is a top trade partner of {home}.
        </div>
      </div>
    );
  }
  return (
    <div className="sec">
      <div className="sec-head"><div className="sec-title">Corridors from {home}</div></div>
      {corridors.map((k, i) => (
        <div key={i} className="exp-reach">
          <span className="exp-iso">{k.from === home ? k.to : k.from}</span>
          <span className="exp-via">{k.role}</span>
          <span className="spacer" />
          <span className="name">#{k.rank} partner</span>
        </div>
      ))}
    </div>
  );
}

function Concentration({ rows }) {
  if (!rows.length) return null;
  return (
    <div className="sec">
      <div className="sec-head">
        <div className="sec-title">Where the claims cluster</div>
        <span className="lg-misses-why">a fact about your list, not a verdict on it</span>
      </div>
      {rows.map((r) => (
        <div key={r.label} className="exp-conc">
          <span className="exp-conc-label">{r.label.replace(/_/g, " ")}</span>
          <span className="exp-conc-bar"><i style={{ width: `${r.share * 100}%` }} /></span>
          <span className="exp-conc-n">{r.count} · {pct(r.share)}</span>
          {r.notable && <span className="exp-conc-flag">concentrated</span>}
        </div>
      ))}
    </div>
  );
}

export function ExposureView({ user, onLogin, onNav }) {
  const [d, setD] = useState(undefined);
  const load = () => { setD(undefined); fetchExposure().then(setD).catch(() => setD(null)); };
  useEffect(load, [user]);

  if (d === null) return <LoadError what="your exposure" onRetry={load} />;

  return (
    <div>
      <div className="page-head">
        <div>
          <h1 className="page-title">Exposure</h1>
          <p className="page-sub">
            Not what you own — what it is exposed to. Which live events reach your names, through
            which holding, and by what mechanism.
          </p>
        </div>
      </div>

      {d === undefined ? (
        <div className="skel" style={{ width: "70%", height: 90, marginTop: 14 }} />
      ) : d.authenticated === false ? (
        <div className="empty" style={{ marginTop: 14 }}>
          Log in to see what your holdings are exposed to.
          <div style={{ marginTop: 10 }}><button className="act" onClick={onLogin}>log in</button></div>
        </div>
      ) : d.empty ? (
        <EmptyState
          title="Add a few names first"
          action={<button className="act act-on" onClick={() => onNav("watchlist")}>Open watchlist</button>}
        >
          Exposure works from the names you watch and hold. Add a handful and this becomes a map of
          what actually reaches them.
        </EmptyState>
      ) : (
        <>
          <Summary s={d.summary} home={d.home} />
          <TouchingClaims claims={d.claims} />
          <div className="dash-grid">
            <Reach reach={d.reach} />
            <Corridors corridors={d.corridors} home={d.home} />
          </div>
          <Concentration rows={d.concentration} />
          {d.upcoming?.length > 0 && (
            <div className="sec">
              <div className="sec-head"><div className="sec-title">Scheduled, on your names</div></div>
              {d.upcoming.map((e) => (
                <div key={e.id} className="exp-reach">
                  <span className="exp-iso">{e.symbol}</span>
                  <span className="exp-via">{e.title}</span>
                  <span className="spacer" />
                  <span className="name">{e.date}</span>
                </div>
              ))}
            </div>
          )}
          <div className="disc" style={{ marginTop: 16 }}>{d.note}</div>
        </>
      )}
    </div>
  );
}
