// The deep layer of the hero: a chart graticule for the wind rose to sit on.
//
// Parallax needs something to have parallax AGAINST. The rose alone drifting over a flat field
// reads as a moving picture; the rose drifting over a meridian net reads as a chart being crossed,
// which is the whole idea the product is named for. This is the far layer, so it is drawn faintest
// and moves least — depth is carried by rate, not by blur.
//
// Meridians converge toward the top of the frame rather than running parallel: a graticule with
// evenly spaced vertical lines is graph paper, and the convergence is what makes it read as a
// projection of a sphere. Parallels bow for the same reason.

const MERIDIANS = 15;
const PARALLELS = 8;

export function Graticule() {
  const lines = [];

  // Meridians: fanned from a vanishing point above the frame, so they splay as they descend.
  const apexX = 660;
  const apexY = -520;
  for (let i = 0; i <= MERIDIANS; i++) {
    const t = i / MERIDIANS;
    const x = t * 1320;
    // Extend the line well past the bottom edge so it never terminates inside the mask.
    const dx = x - apexX;
    const dy = 800 - apexY;
    lines.push(
      <line key={`m${i}`} x1={apexX + dx * 0.18} y1={apexY + dy * 0.18}
            x2={apexX + dx * 1.25} y2={apexY + dy * 1.25}
            stroke="var(--verdigris)" strokeWidth="0.4"
            opacity={i % 3 === 0 ? 0.13 : 0.07} />,
    );
  }

  // Parallels: shallow arcs, spaced wider toward the bottom the way latitude does on a
  // Mercator-like sheet.
  for (let i = 0; i <= PARALLELS; i++) {
    const t = i / PARALLELS;
    const y = 40 + t * t * 760;
    const bow = 26 * (1 - t * 0.55);
    lines.push(
      <path key={`p${i}`} d={`M -60 ${y} Q 660 ${y - bow} 1380 ${y}`}
            fill="none" stroke="var(--verdigris)" strokeWidth="0.4"
            opacity={i % 2 === 0 ? 0.12 : 0.06} />,
    );
  }

  return (
    <svg className="graticule-field" viewBox="0 0 1320 800"
         preserveAspectRatio="xMidYMid slice" aria-hidden="true" focusable="false">
      {lines}
    </svg>
  );
}
