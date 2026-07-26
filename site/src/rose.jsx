// The signature element: a portolan wind rose and its rhumb-line net.
//
// A rhumb line is a real navigational object — a course that crosses every meridian at a constant
// angle. On the portolan charts of the 14th to 16th centuries those lines were drawn as a
// radiating net from compass roses placed around the sheet, and that net is the single most
// recognisable thing about those charts. It is also, literally, what the product is named after.
//
// So this is where the page spends its boldness, and nothing else on the page competes with it.
// Drawn as inline SVG rather than canvas or an image: it is a few hundred bytes of geometry, it
// scales to any viewport without a second asset request, and it costs nothing on first paint.
//
// The 32 points are the historical compass card (four winds, halved five times), not an arbitrary
// count that happened to look nice.

const POINTS = 32;
const DEG = 360 / POINTS;

// Portolan roses vary line weight by order: the eight principal winds are drawn heaviest, the
// eight half-winds lighter, the sixteen quarter-winds lightest. Reproducing that hierarchy is the
// difference between a wind rose and a bicycle wheel.
function order(i) {
  if (i % 4 === 0) return "principal";
  if (i % 2 === 0) return "half";
  return "quarter";
}

const WEIGHT = { principal: 0.9, half: 0.55, quarter: 0.35 };
const OPACITY = { principal: 0.5, half: 0.3, quarter: 0.17 };

// The rose sits low and left of centre, under the headline rather than behind the live panel.
// A wind rose whose eye is hidden is just a texture; the eye is the thing that makes it read as an
// instrument, so it has to land in open space.
export function Rose({ cx = 470, cy = 470, r = 880 }) {
  const lines = [];
  for (let i = 0; i < POINTS; i++) {
    const k = order(i);
    const a = (i * DEG - 90) * (Math.PI / 180);
    lines.push(
      <line
        key={i}
        x1={cx}
        y1={cy}
        x2={cx + Math.cos(a) * r}
        y2={cy + Math.sin(a) * r}
        stroke={k === "principal" ? "var(--magenta)" : "var(--verdigris)"}
        strokeWidth={WEIGHT[k]}
        opacity={OPACITY[k]}
      />,
    );
  }

  // Concentric bearing rings, thinning outward — the distance scale on a chart, not decoration.
  const rings = [0.1, 0.19, 0.32, 0.5, 0.72].map((f, i) => (
    <circle
      key={f}
      cx={cx}
      cy={cy}
      r={r * f}
      fill="none"
      stroke="var(--verdigris)"
      strokeWidth="0.5"
      opacity={0.24 - i * 0.035}
    />
  ));

  return (
    <svg
      className="rose-field"
      viewBox="0 0 1320 800"
      preserveAspectRatio="xMidYMid slice"
      aria-hidden="true"
      focusable="false"
    >
      {rings}
      {lines}
      {/* The rose's own eye. Small, magenta, the one saturated point in the whole backdrop. */}
      <circle cx={cx} cy={cy} r="3" fill="var(--magenta)" opacity="0.85" />
      <circle cx={cx} cy={cy} r="13" fill="none" stroke="var(--magenta)" strokeWidth="0.7" opacity="0.5" />
    </svg>
  );
}
