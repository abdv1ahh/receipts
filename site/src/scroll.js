// The scroll engine for the whole page. One listener, one rAF, transforms only.
//
// The brief offers GSAP ScrollTrigger with Lenis, or Framer Motion. None of them is here, and the
// reason is the performance target set two paragraphs later in the same brief: first contentful
// paint under 1.5s and Lighthouse above ninety. The smallest of those libraries is several times
// the weight of this entire page's JavaScript, to do something the platform now does natively on
// the compositor. So:
//
//   * where the browser supports scroll-driven animations (`animation-timeline`), the parallax is
//     pure CSS and never touches the main thread at all;
//   * everywhere else this driver writes two custom properties on <html> once per frame, and the
//     same CSS reads them. One listener for the page, not one per element.
//
// Smooth-scroll hijacking (Lenis' actual job) is deliberately NOT done. It takes the scroll away
// from the operating system, breaks trackpad and keyboard feel, fights every accessibility tool,
// and on a page whose argument is "we do not blur things together" it would be the wrong kind of
// clever.

/** True when the visitor has asked for less motion. Checked once per call site, not cached, so a
 *  change in system settings is respected without a reload. */
export const wantsMotion = () =>
  typeof window !== "undefined"
  && window.matchMedia
  && !window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/** Does the browser drive animations from scroll position itself? Chrome/Edge 115+, Safari 26+.
 *  Where true, every `animation-timeline` rule in styles.css runs off the main thread and this
 *  module's per-frame work is not needed for those effects. */
export const nativeScrollTimeline = () =>
  typeof CSS !== "undefined" && CSS.supports && CSS.supports("animation-timeline: view()");

/** Start the page-level driver. Returns a teardown.
 *
 *  Writes:
 *    --sy  scroll offset in pixels, for depth layers that track the viewport
 *    --sp  progress through the whole document, 0..1
 *
 *  Both are written to the documentElement so any rule anywhere can read them, and both are
 *  written inside a rAF so a burst of scroll events collapses into one style write per frame. */
export function startScrollDriver() {
  if (typeof window === "undefined" || !wantsMotion()) return () => {};
  // Where the browser drives scroll animations itself, the CSS in the @supports block takes over
  // completely and these properties are read by nothing. Running the listener anyway would be a
  // per-frame style write on the main thread for no output at all.
  if (nativeScrollTimeline()) return () => {};

  const root = document.documentElement;
  let ticking = false;

  const write = () => {
    ticking = false;
    const y = window.scrollY || 0;
    const span = Math.max(1, root.scrollHeight - window.innerHeight);
    root.style.setProperty("--sy", `${y}`);
    root.style.setProperty("--sp", `${Math.min(1, y / span)}`);
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
}

/** Per-element scroll progress, 0 as the element enters the viewport, 1 as it leaves.
 *
 *  Only runs while the element is actually on screen — an IntersectionObserver gates the rAF, so a
 *  page with a dozen of these costs nothing for the eleven that are scrolled past. Writes `--ep`
 *  on the element itself, which CSS then reads; nothing here touches React state, because a
 *  setState per frame is exactly how a scroll effect becomes a stutter.
 *
 *  Skipped entirely under reduced motion and where the browser can do it natively in CSS. */
export function trackElementProgress(el) {
  if (!el || !wantsMotion() || nativeScrollTimeline()) return () => {};

  let visible = false;
  let raf = 0;

  const frame = () => {
    if (!visible) return;
    const r = el.getBoundingClientRect();
    const span = window.innerHeight + r.height;
    const p = span > 0 ? (window.innerHeight - r.top) / span : 0;
    el.style.setProperty("--ep", `${Math.max(0, Math.min(1, p))}`);
    raf = requestAnimationFrame(frame);
  };

  const io = new IntersectionObserver(([e]) => {
    visible = e.isIntersecting;
    if (visible && !raf) raf = requestAnimationFrame(frame);
    if (!visible && raf) { cancelAnimationFrame(raf); raf = 0; }
  }, { threshold: 0 });

  io.observe(el);
  return () => { io.disconnect(); if (raf) cancelAnimationFrame(raf); };
}
