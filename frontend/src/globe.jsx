// The globe — and the flat map that stands in for it.
//
// Two rules from the brief shape this file, and both cost more than they look:
//
//   * "lazy load the entire globe bundle so it never delays initial load" — three.js and globe.gl
//     are ~60MB of source and a large chunk built. So the 3D renderer lives behind a dynamic
//     import() and is fetched only when a reader actually opens this surface with motion allowed.
//     Everything else here, including the whole 2D fallback, ships in the main bundle.
//
//   * "anything reachable only through the globe must also be reachable without it" — so the flat
//     map is not a degraded consolation. It renders the same countries, the same corridors and the
//     same selection behaviour, and it is what you get under prefers-reduced-motion.
//
// The honesty rule that matters most here: an unlit country must never read as a quiet one. It
// almost always means this product has no coverage there yet, and the legend says so.
import { Suspense, lazy, useEffect, useMemo, useState } from "react";
import { fetchGlobe, saveProfileFrame } from "./api";
import { Icon } from "./icons.jsx";
import { EmptyState, LoadError } from "./shell.jsx";

const Globe3D = lazy(() => import("./globe3d.jsx"));

const prefersReduced = () =>
  typeof window !== "undefined" && window.matchMedia
  && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/** Can this device actually render a globe?
 *
 *  Asking rather than assuming. Plenty of real machines cannot: older hardware, locked-down
 *  enterprise browsers, remote sessions, and anything with GPU acceleration disabled. Without this
 *  check they get an empty box and a stack of WebGL errors in the console — found exactly that way,
 *  in a headless browser with no GPU. A feature that fails silently on someone's machine is worse
 *  than one that never claimed to work. */
const webglAvailable = () => {
  if (typeof document === "undefined") return false;
  try {
    const canvas = document.createElement("canvas");
    const gl = canvas.getContext("webgl2") || canvas.getContext("webgl")
      || canvas.getContext("experimental-webgl");
    if (!gl) return false;
    // Chromium can hand back a context that fails on first real use, so confirm it is live.
    return typeof gl.getParameter === "function" && !!gl.getParameter(gl.VERSION);
  } catch {
    return false;
  }
};

// Approximate centroids for the countries this product can currently speak about. Enough to place
// a marker; deliberately not a geometry dataset, which would be a megabyte to say the same thing.
const CENTROIDS = {
  US: [39.8, -98.6], CA: [56.1, -106.3], MX: [23.6, -102.6], BR: [-14.2, -51.9],
  AR: [-38.4, -63.6], CL: [-35.7, -71.5], CO: [4.6, -74.3],
  GB: [55.4, -3.4], DE: [51.2, 10.5], FR: [46.2, 2.2], IT: [41.9, 12.6], ES: [40.5, -3.7],
  NL: [52.1, 5.3], CH: [46.8, 8.2], SE: [60.1, 18.6], NO: [60.5, 8.5], PL: [51.9, 19.1],
  RU: [61.5, 105.3], UA: [48.4, 31.2], TR: [39.0, 35.2],
  CN: [35.9, 104.2], JP: [36.2, 138.3], KR: [35.9, 127.8], TW: [23.7, 121.0],
  IN: [20.6, 79.0], PK: [30.4, 69.3], SG: [1.35, 103.8], ID: [-0.8, 113.9],
  TH: [15.9, 101.0], VN: [14.1, 108.3], MY: [4.2, 101.98], HK: [22.3, 114.2],
  AE: [23.4, 53.8], SA: [23.9, 45.1], QA: [25.4, 51.2], KW: [29.3, 47.5],
  IL: [31.0, 34.9], IR: [32.4, 53.7], IQ: [33.2, 43.7], EG: [26.8, 30.8],
  ZA: [-30.6, 22.9], NG: [9.1, 8.7], KE: [-0.02, 37.9],
  AU: [-25.3, 133.8], NZ: [-40.9, 174.9],
};

const intensity = (n, max) => (max <= 0 ? 0 : Math.min(1, n / max));

/** Equirectangular projection into a 0..100 viewBox. The same centroids the globe uses, so the
 *  two views cannot disagree about where a country is. */
const project = ([lat, lon]) => ({ x: ((lon + 180) / 360) * 100, y: ((90 - lat) / 180) * 100 });

function FlatMap({ countries, corridors, selected, onSelect }) {
  const max = Math.max(1, ...countries.map((c) => c.events));
  const placed = countries.filter((c) => CENTROIDS[c.country]);
  return (
    <svg className="globe-flat" viewBox="0 0 100 50" preserveAspectRatio="xMidYMid meet"
         role="img" aria-label="World map of events by country">
      {corridors.map((k, i) => {
        const a = CENTROIDS[k.from], b = CENTROIDS[k.to];
        if (!a || !b) return null;
        const p1 = project(a), p2 = project(b);
        return (
          <line key={i} x1={p1.x} y1={p1.y / 2} x2={p2.x} y2={p2.y / 2}
                className="globe-arc" strokeWidth={0.06 + k.weight * 0.14}
                opacity={0.1 + k.weight * 0.25} />
        );
      })}
      {placed.map((c) => {
        const p = project(CENTROIDS[c.country]);
        const t = intensity(c.events, max);
        return (
          <g key={c.country} onClick={() => onSelect(c.country)} className="globe-dot"
             role="button" tabIndex={0} aria-label={`${c.name}, ${c.events} interpretations`}
             onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onSelect(c.country); } }}>
            <circle cx={p.x} cy={p.y / 2} r={0.5 + t * 1.6}
                    className={selected === c.country ? "on" : ""} />
            <title>{c.name}: {c.events} interpretation{c.events === 1 ? "" : "s"}</title>
          </g>
        );
      })}
    </svg>
  );
}

function CountryPanel({ iso, data, onSetFrame, isFrame }) {
  const country = data.countries.find((c) => c.country === iso);
  const exposure = data.exposure?.[iso];
  const linked = data.corridors.filter((k) => k.from === iso || k.to === iso);
  if (!country && !exposure) {
    return (
      <div className="globe-panel">
        <div className="globe-panel-head">{iso}</div>
        <p className="gate-note">
          No coverage here yet. That is a gap in what this product reads, not a quiet country.
        </p>
      </div>
    );
  }
  return (
    <div className="globe-panel">
      <div className="globe-panel-head">
        {country?.name || exposure?.name || iso}
        <span className="spacer" />
        <button className={`act ${isFrame ? "" : "act-on"}`} onClick={() => onSetFrame(iso)} disabled={isFrame}>
          {isFrame ? "your frame" : "read from here"}
        </button>
      </div>

      {exposure && (
        <div className="globe-exposure">
          <div><span>Currency</span> <b>{exposure.currency}</b>
            {exposure.pegged_to && <em> pegged to {exposure.pegged_to}</em>}</div>
          {exposure.main_index && <div><span>Index</span> <b>{exposure.main_index}</b></div>}
          {exposure.key_exports?.length > 0 && <div><span>Exports</span> {exposure.key_exports.join(", ")}</div>}
          {exposure.key_imports?.length > 0 && <div><span>Imports</span> {exposure.key_imports.join(", ")}</div>}
        </div>
      )}

      {linked.length > 0 && (
        <div className="globe-corridors">
          <div className="an-title">Trade corridors</div>
          {linked.slice(0, 8).map((k, i) => (
            <div key={i} className="globe-corridor">
              <b>{k.from === iso ? k.to : k.from}</b>
              <span>{k.from === iso ? k.direction : (k.direction === "export" ? "supplies" : "buys from")}</span>
              <em>#{k.rank}</em>
            </div>
          ))}
        </div>
      )}

      {country?.claims?.length > 0 ? (
        <div className="globe-claims">
          <div className="an-title">Live interpretations here</div>
          {country.claims.map((c) => (
            <div key={c.claim_id} className="globe-claim">
              <span className="rd-conf band-medium">{Math.round(c.confidence * 100)}%</span>
              <span>{c.mechanism}</span>
            </div>
          ))}
        </div>
      ) : (
        <p className="gate-note" style={{ marginTop: 10 }}>
          Nothing interpreted here in the last two weeks.
        </p>
      )}
    </div>
  );
}

export function GlobeView({ user, onLogin }) {
  const [d, setD] = useState(undefined);
  const [selected, setSelected] = useState(null);
  const [frame, setFrame] = useState(null);
  // Two independent reasons to draw the flat map, and the interface has to tell them apart:
  // a stated PREFERENCE (reduced motion) versus a hard CAPABILITY limit (no WebGL). The first is
  // reversible by the reader; the second is not, so the 3D toggle is disabled and says why.
  const [canWebgl] = useState(webglAvailable);
  const [flat, setFlat] = useState(() => prefersReduced() || !webglAvailable());

  const load = () => { setD(undefined); fetchGlobe().then(setD).catch(() => setD(null)); };
  useEffect(load, []);

  const setAsFrame = async (iso) => {
    if (!user) { onLogin(); return; }
    const res = await saveProfileFrame({ country: iso });
    if (!res.error) setFrame(iso);
  };

  const corridors = useMemo(() => d?.corridors || [], [d]);

  if (d === null) return <LoadError what="the map" onRetry={load} />;

  return (
    <div>
      <div className="page-head">
        <div>
          <h1 className="page-title">The World</h1>
          <p className="page-sub">
            Where the events this product has interpreted actually landed, and the trade corridors
            that carry them. Pick a country to read the world from there.
          </p>
        </div>
        <div className="sm-filter">
          <button className={flat ? "" : "on"} onClick={() => setFlat(false)} disabled={!canWebgl}
                  title={canWebgl ? "" : "This browser cannot render 3D graphics (no WebGL)"}>
            Globe
          </button>
          <button className={flat ? "on" : ""} onClick={() => setFlat(true)}>Flat</button>
        </div>
      </div>

      {d === undefined ? (
        <div className="skel" style={{ width: "100%", height: 360, marginTop: 14 }} />
      ) : d.countries.length === 0 ? (
        <EmptyState title="Nothing placed on the map yet">
          Countries light up once the engine has interpreted an event it can attribute to them.
          Geography comes from what a claim <b>affects</b>, not from who published it.
        </EmptyState>
      ) : (
        <>
          <div className="globe-wrap">
            {flat ? (
              <FlatMap countries={d.countries} corridors={corridors} selected={selected} onSelect={setSelected} />
            ) : (
              <Suspense fallback={<div className="globe-loading">Loading the globe…</div>}>
                <Globe3D countries={d.countries} corridors={corridors} centroids={CENTROIDS}
                         selected={selected} onSelect={setSelected} />
              </Suspense>
            )}
          </div>

          {!canWebgl && (
            <div className="globe-note">
              <Icon name="alert" size={14} /> This browser cannot render 3D graphics, so the flat
              map is shown. It carries the same countries, corridors and selection — nothing here
              is only reachable through the globe.
            </div>
          )}

          <div className="globe-legend">
            <span><i className="dot-lit" /> lit by interpretations placed there</span>
            <span><i className="dot-arc" /> a sourced trade corridor</span>
            <span className="globe-coverage">{d.coverage.note}</span>
          </div>

          {selected && (
            <CountryPanel iso={selected} data={d} onSetFrame={setAsFrame}
                          isFrame={frame === selected} />
          )}

          <div className="globe-stats">
            <div><b>{d.coverage.countries_with_activity}</b><span>countries with activity</span></div>
            <div><b>{d.coverage.countries_with_exposure_data}</b><span>with exposure data</span></div>
            <div><b>{corridors.length}</b><span>trade corridors</span></div>
          </div>
        </>
      )}

      <div className="disc" style={{ marginTop: 16 }}>
        Corridors come from published trade-partner data, each row sourced in
        <code> country_exposure</code>. They are relationships, not live shipment tracking.
      </div>
    </div>
  );
}
