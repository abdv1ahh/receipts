// Every network call the marketing site makes. All of it is public, unauthenticated, GET-only —
// the site never sends credentials and has nothing to send them to.
//
// Failures resolve to `null` rather than throwing. A marketing page whose hero disappears because
// one endpoint was slow is worse than one that says "the live feed is not reachable right now",
// and every caller here is written to render that honestly rather than to fake data.

const get = (path) =>
  fetch(path, { credentials: "omit", headers: { Accept: "application/json" } })
    .then((r) => (r.ok ? r.json() : null))
    .catch(() => null);

export const fetchLive = (limit = 5) => get(`/api/public/live?limit=${limit}`);
export const fetchWalkthrough = () => get("/api/public/walkthrough");
export const fetchFrame = (country, limit = 5) =>
  get(`/api/public/frame?limit=${limit}${country ? `&country=${encodeURIComponent(country)}` : ""}`);
export const fetchLedger = () => get("/api/ledger");
