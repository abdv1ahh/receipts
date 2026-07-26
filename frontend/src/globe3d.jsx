// The 3D globe, isolated in its own module so Vite splits it into a separate chunk.
//
// NOTHING else may import this file statically. It pulls in three.js and globe.gl, which together
// are the largest dependency in the project by a wide margin; a static import anywhere would put
// them in the main bundle and delay first paint for every reader, including the ones who never
// open this surface. `globe.jsx` reaches it through React.lazy + dynamic import() only.
//
// The base globe is kept deliberately plain. The data is the thing worth looking at, and a
// textured, glowing, star-fielded ball competes with it.
import { useEffect, useMemo, useRef } from "react";
import Globe from "react-globe.gl";
import { MeshPhongMaterial } from "three";
import WORLD from "./world-110m.geo.json";

// Land is drawn from vendored Natural Earth 110m geometry (public domain), stripped to iso + name
// + coordinates and rounded to 2dp — ~1km, far finer than a globe at this scale can show, for a
// third of the original bytes. It is vendored rather than read from node_modules because the copy
// that ships inside globe.gl lives in an `example/` directory: not a public API, and not something
// a reinstall is obliged to keep. It rides in this lazy chunk, so it costs nothing until opened.
//
// Without it there is no land layer at all, and globe.gl's own documentation is explicit about the
// result: with no globeImageUrl "the globe is represented as a black sphere". A black sphere on a
// near-black page is invisible, which is exactly how this surface used to render — the previous
// version set hexPolygonColor but never hexPolygonsData, so the accessor had nothing to colour.
const COUNTRIES = WORLD.features;

const BG = "rgba(0,0,0,0)";
const LAND = "#33455f";
const LAND_SELECTED = "#8fb3ff";
const OCEAN = "#0b1220";

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

  // The globeMaterial prop takes a THREE.Material INSTANCE, not a spec to build one from — the
  // previous `{ color: OCEAN }` was a plain object, so it was quietly ignored and the ocean stayed
  // at the default black. Built once: a new material each render would reupload to the GPU on
  // every state change. `three` is a direct import here, so it is a direct dependency; it was
  // always installed as react-globe.gl's peer, this only stops that being implicit.
  const globeMaterial = useMemo(
    () => new MeshPhongMaterial({ color: OCEAN, shininess: 3 }),  // matte: a specular highlight
    [],                                                          // on the ocean competes with data
  );

  const max = Math.max(1, ...countries.map((c) => c.events));

  // Singapore and Hong Kong are smaller than the 110m dataset resolves, so they carry an event
  // marker but no land polygon. The marker is what makes them selectable, so nothing is lost.
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
      globeMaterial={globeMaterial}
      // Land. Hexed rather than solid: it reads as an instrument rather than an atlas, and the
      // gaps let the ocean through so the sphere keeps its form at every zoom.
      hexPolygonsData={COUNTRIES}
      hexPolygonGeoJsonGeometry={(d) => d.geometry}
      hexPolygonResolution={3}
      hexPolygonMargin={0.32}
      hexPolygonAltitude={0.006}
      hexPolygonColor={(d) => (d.properties.iso && d.properties.iso === selected ? LAND_SELECTED : LAND)}
      hexPolygonLabel={(d) => d.properties.name}
      // Selecting the landmass does the same thing as selecting its marker. Countries with no
      // events have no marker, so without this they could only be chosen from the list — and
      // picking a quiet country is exactly how a reader checks whether it is quiet.
      onHexPolygonClick={(d) => d.properties.iso && onSelect(d.properties.iso)}
      pointsData={points}
      pointLat="lat"
      pointLng="lng"
      pointColor="colour"
      // Kept short and wide: tall thin spikes tangle into each other wherever several active
      // countries sit close together, which is precisely where the reader most needs to count them.
      pointAltitude={(p) => 0.01 + p.size * 0.14}
      pointRadius={(p) => 0.3 + p.size * 0.42}
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
