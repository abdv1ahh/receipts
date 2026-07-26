// Two hooks the whole page is built from.
import { useEffect, useRef, useState } from "react";

/** Load once on mount. `undefined` while in flight, `null` on failure — the three states every
 *  section on this page renders explicitly, because "no data yet" and "could not reach it" are
 *  different sentences and the product's whole argument is that it does not blur them. */
export function useLoad(fn, deps = []) {
  const [data, setData] = useState(undefined);
  useEffect(() => {
    let live = true;
    setData(undefined);
    fn().then((d) => live && setData(d ?? null));
    return () => { live = false; };
  }, deps); // eslint-disable-line react-hooks/exhaustive-deps
  return data;
}

/** Reveal on scroll, in twenty lines of IntersectionObserver.
 *
 *  The brief offers GSAP + Lenis or Framer Motion. Neither earns its bytes for "fade a section in
 *  once": the smallest of them is heavier than this entire page's JavaScript, and a marketing site
 *  whose first paint waits on an animation library fails the performance target set two paragraphs
 *  later in the same brief.
 *
 *  `once: true` — re-animating on the way back up is the thing that makes scroll effects read as
 *  cheap. Reduced motion is handled centrally in shared/tokens.css: the transition collapses to
 *  nothing and the element still lands visible. */
export function useReveal() {
  const ref = useRef(null);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof IntersectionObserver === "undefined") {
      el?.classList.add("in");
      return;
    }
    const io = new IntersectionObserver(
      ([e]) => {
        if (e.isIntersecting) { el.classList.add("in"); io.disconnect(); }
      },
      { rootMargin: "0px 0px -12% 0px", threshold: 0.05 },
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);
  return ref;
}
