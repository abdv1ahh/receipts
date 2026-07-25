// The 3D globe, isolated in its own module so Vite splits it into a separate chunk.
//
// NOTHING else may import this file statically. It pulls in three.js and globe.gl, which together
// are the largest dependency in the project by a wide margin; a static import anywhere would put
// them in the main bundle and delay first paint for every reader, including the ones who never
// open this surface. `globe.jsx` reaches it through React.lazy + dynamic import() only.
//
// The base globe is kept deliberately plain. The data is the thing worth looking at, and a
// textured, glowing, star-fielded ball competes with it.
import { useEffect, useRef } from "react";
import Globe from "react-globe.gl";

const BG = "rgba(0,0,0,0)";
const LAND = "#1b2333";
const OCEAN = "#0b0e15";

export default function Globe3D({ countries, corridors, centroids, selected, onSelect }) {
  const ref = useRef();

  // A slow drift reads as "live" without demanding attention. Anyone who asked for reduced motion
  // never reaches this component — globe.jsx renders the flat map for them instead.
  useEffect(() => {
    const g = ref.current;
    if (!g) return;
    g.controls().autoRotate = true;
    g.controls().autoRotateSpeed = 0.35;
    g.controls().enableDamping = true;
    g.pointOfView({ lat: 22, lng: 20, altitude: 2.4 }, 0);
  }, []);

  const max = Math.max(1, ...countries.map((c) => c.events));

  const points = countries
    .filter((c) => centroids[c.country])
    .map((c) => ({
      lat: centroids[c.country][0],
      lng: centroids[c.country][1],
      iso: c.country,
      name: c.name,
      events: c.events,
      size: 0.18 + (c.events / max) * 0.7,
      colour: c.country === selected ? "#8fb3ff" : "#4cd9a0",
    }));

  const arcs = corridors
    .filter((k) => centroids[k.from] && centroids[k.to])
    .map((k) => ({
      startLat: centroids[k.from][0], startLng: centroids[k.from][1],
      endLat: centroids[k.to][0], endLng: centroids[k.to][1],
      weight: k.weight,
      label: `${k.from} → ${k.to} (${k.direction} #${k.rank})`,
    }));

  return (
    <Globe
      ref={ref}
      backgroundColor={BG}
      showAtmosphere
      atmosphereColor="#6c94ff"
      atmosphereAltitude={0.13}
      globeMaterial={{ color: OCEAN }}
      hexPolygonColor={() => LAND}
      pointsData={points}
      pointLat="lat"
      pointLng="lng"
      pointColor="colour"
      pointAltitude={(p) => p.size * 0.35}
      pointRadius={(p) => 0.28 + p.size * 0.5}
      pointLabel={(p) => `${p.name}: ${p.events} interpretation${p.events === 1 ? "" : "s"}`}
      onPointClick={(p) => onSelect(p.iso)}
      arcsData={arcs}
      arcColor={() => ["rgba(108,148,255,0.05)", "rgba(108,148,255,0.45)"]}
      arcStroke={(a) => 0.12 + a.weight * 0.35}
      arcAltitude={(a) => 0.08 + a.weight * 0.18}
      arcLabel="label"
      arcDashLength={0.5}
      arcDashGap={0.2}
      // The propagation feel: a corridor pulses along the direction goods actually travel.
      arcDashAnimateTime={(a) => 4000 - a.weight * 2000}
    />
  );
}
