// A live bearing readout in the navigation bar.
//
// A rhumb line is a course held at a CONSTANT BEARING — that is the definition, and it is what the
// product is named after. So the one piece of chrome that follows you down the page is a compass
// reading, sweeping as you travel. It agrees with the wind rose behind the hero, because both are
// driven by the same page progress: the card you can see turning and the number reporting it are
// the same instrument, not two decorations that happen to move.
//
// This is the one effect that cannot be pure CSS — text content is not animatable from a scroll
// timeline — so it is written by hand, once per frame, and only while the page is actually being
// scrolled. Cost: one textContent write on an element with tabular figures, so it never reflows.

import { useEffect, useRef } from "react";
import { wantsMotion } from "./scroll.js";

/** Degrees swept across the full document. 60° reads as a real course change without ever
 *  wrapping past a cardinal point, which would make the readout look like it was spinning. */
const SWEEP = 60;

const CARDINALS = ["N", "NNE", "NE", "ENE", "E"];

function label(deg) {
  const i = Math.min(CARDINALS.length - 1, Math.round((deg / 90) * (CARDINALS.length - 1)));
  return CARDINALS[i];
}

export function Bearing() {
  const ref = useRef(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    // Under reduced motion the readout is still CORRECT, it just stops tracking: it renders the
    // course once and holds it, rather than disappearing. A missing instrument is worse than a
    // still one.
    if (!wantsMotion()) {
      el.textContent = `N 000° — held`;
      return;
    }

    let ticking = false;
    const write = () => {
      ticking = false;
      const root = document.documentElement;
      const span = Math.max(1, root.scrollHeight - window.innerHeight);
      const p = Math.min(1, Math.max(0, (window.scrollY || 0) / span));
      const deg = p * SWEEP;
      el.textContent = `${label(deg)} ${String(Math.round(deg)).padStart(3, "0")}°`;
    };
    const onScroll = () => {
      if (ticking) return;
      ticking = true;
      requestAnimationFrame(write);
    };

    write();
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll, { passive: true });
    return () => {
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onScroll);
    };
  }, []);

  return (
    <span className="bearing" aria-hidden="true" title="Bearing — a rhumb line is a course held at a constant angle">
      <span className="bearing-tick" />
      <span className="bearing-v" ref={ref}>N 000°</span>
    </span>
  );
}
