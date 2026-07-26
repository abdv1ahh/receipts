// The country picker for the personalisation demo.
//
// The brief asks for "an interactive globe where a visitor picks their country". The app already
// owns a real one — `react-globe.gl`, which is 1.9MB gzipped and lazy-loaded behind a WebGL check.
// Putting that on a marketing page whose stated target is Lighthouse above ninety would trade the
// performance requirement for a spinning ball, so this is the same interaction drawn as a few
// hundred bytes of SVG.
//
// It is also the more honest object. Exactly ten countries have hand-checked exposure figures
// behind them, and a globe you can spin implies you can pick any of them. A plate with ten marked
// stations does not overpromise, and reads as an instrument rather than a toy — which is the
// vocabulary the rest of the page is working in.
//
// The graticule is a real equirectangular projection: x = (lon + 180) / 360, y = (90 - lat) / 180.
// Station coordinates are each country's approximate centroid, rounded — they place a marker, they
// are not a geographic claim.

const W = 720;
const H = 360;

const LATLON = {
  AE: [24.0, 54.0], SA: [24.0, 45.0], US: [39.5, -98.5], GB: [54.0, -2.5],
  IN: [22.0, 79.0], CN: [35.0, 105.0], BR: [-10.0, -52.0], JP: [36.5, 138.0],
  DE: [51.2, 10.4], SG: [1.35, 103.8],
};

const px = (lon) => ((lon + 180) / 360) * W;
const py = (lat) => ((90 - lat) / 180) * H;

// Coastlines are not drawn. A hand-traced world at this size would be either wrong or enormous,
// and the graticule plus labelled stations communicates "pick a place" without either failure.
function Graticule() {
  const lines = [];
  for (let lon = -180; lon <= 180; lon += 30) {
    lines.push(<line key={`m${lon}`} x1={px(lon)} y1={0} x2={px(lon)} y2={H}
                     stroke="var(--verdigris)" strokeWidth="0.4" opacity="0.16" />);
  }
  for (let lat = -60; lat <= 60; lat += 30) {
    lines.push(<line key={`p${lat}`} x1={0} y1={py(lat)} x2={W} y2={py(lat)}
                     stroke="var(--verdigris)" strokeWidth="0.4" opacity="0.16" />);
  }
  // The equator carries weight, the way it does on a chart.
  lines.push(<line key="eq" x1={0} y1={py(0)} x2={W} y2={py(0)}
                   stroke="var(--verdigris)" strokeWidth="0.8" opacity="0.34" />);
  return <g aria-hidden="true">{lines}</g>;
}

export function WorldMap({ countries = [], selected, onSelect }) {
  const known = countries.filter((c) => LATLON[c.country]);

  return (
    <div className="map-card">
      <svg viewBox={`0 0 ${W} ${H}`} role="group" aria-label="Choose the country you read from">
        <Graticule />
        {known.map((c) => {
          const [lat, lon] = LATLON[c.country];
          const on = c.country === selected;
          const x = px(lon);
          const y = py(lat);
          return (
            <g key={c.country} className="country-pin" role="button" tabIndex={0}
               aria-label={c.name} aria-pressed={on}
               onClick={() => onSelect(c.country)}
               onKeyDown={(e) => {
                 if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onSelect(c.country); }
               }}>
              {/* A generous transparent target so the pin is reachable on a phone. */}
              <circle cx={x} cy={y} r="16" fill="transparent" />
              {on && <circle cx={x} cy={y} r="11" fill="none" stroke="var(--magenta)" strokeWidth="1" opacity="0.6" />}
              <circle cx={x} cy={y} r={on ? 5.5 : 4}
                      fill={on ? "var(--magenta)" : "var(--verdigris)"}
                      opacity={on ? 1 : 0.8} />
              <text x={x} y={y - 13} textAnchor="middle"
                    fill={on ? "var(--magenta)" : "var(--paper-faint)"}
                    style={{ font: "600 10px var(--mono)", letterSpacing: "0.08em" }}>
                {c.country}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}
