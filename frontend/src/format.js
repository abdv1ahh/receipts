// Display formatters shared by every surface that renders a trade or a timestamp.
//
// These lived as near-identical copies in journal.jsx, portfolios.jsx and community.jsx — three
// call sites, which is the bar this repo sets for extracting something. Copy four was where it
// stopped being harmless: the community feed's `pct` was missing the ×100, so a +10% trade was
// published to other people's screens as "+0.1%". A formatter that disagrees with itself between
// two pages showing THE SAME NUMBER is worse than a duplicated one.
//
// The unit convention, stated once so the next copy cannot get it wrong: the API returns returns
// as FRACTIONS (`trades.realized_pnl_pct` — 0.1 means +10%). `pct` does the conversion. Anything
// already expressed in percent must not be passed through here.

/** A signed percentage from a FRACTION. 0.1 -> "+10.0%". */
export const pct = (v) => (v == null ? "—" : `${v >= 0 ? "+" : ""}${(v * 100).toFixed(1)}%`);

/** The CSS class that colours a signed number. Zero is neither green nor red. */
export const cls = (v) => (v == null ? "" : v > 0 ? "pos-pos" : v < 0 ? "pos-neg" : "");

/** A price. Locale-grouped, at most 2dp, never scientific notation. */
export const money = (v) =>
  (v == null ? "—" : `$${(+v).toLocaleString(undefined, { maximumFractionDigits: 2 })}`);

/** Coarse relative time. `empty` is what an absent timestamp reads as, which differs by surface:
 *  a feed item says nothing, a source-health row says "never". */
export const ago = (iso, empty = "") => {
  if (!iso) return empty;
  const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  if (mins < 1440) return `${Math.round(mins / 60)}h ago`;
  return `${Math.round(mins / 1440)}d ago`;
};
