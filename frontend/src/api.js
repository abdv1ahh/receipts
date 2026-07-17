// Same-origin API. The dashboard only ever renders numbers the backend computed from real
// records — it never fabricates or interpolates a value.
async function get(path) {
  const res = await fetch(path, { headers: { Accept: "application/json" } });
  if (!res.ok) throw new Error(`${path} -> ${res.status}`);
  return res.json();
}

export const fetchClusters = (minConfidence) =>
  get(`/api/clusters?as_of=latest&min_confidence=${encodeURIComponent(minConfidence)}`);
export const fetchClusterDetail = (issuerId) => get(`/api/clusters/${issuerId}?as_of=latest`);
export const fetchExplanation = (issuerId, horizon) =>
  get(`/api/clusters/${issuerId}/explanation?horizon=${horizon}`);
export const fetchFeeds = () => get("/api/feeds");
export const fetchDefinitions = () => get("/api/definitions");
export const fetchCalibration = () => get("/api/calibration");
export const fetchAsset = (symbol) => get(`/api/asset/${encodeURIComponent(symbol)}`);
export const fetchActivity = (symbol) => get(`/api/activity?symbol=${encodeURIComponent(symbol)}`);
export const fetchInstitution = (id) => get(`/api/institution/${id}`);
export const fetchInsider = (cik) => get(`/api/insider/${encodeURIComponent(cik)}`);
export const fetchScreener = (minC, sourceClass) =>
  get(`/api/clusters?as_of=latest&min_confidence=${minC}${sourceClass ? `&source_class=${sourceClass}` : ""}`);
export const fetchLibrary = () => get("/api/library");
export const fetchLibraryEntry = (slug) => get(`/api/library/${slug}`);
export const fetchWatchlist = () => get("/api/watchlist");
export const addWatchlist = (sym) => fetch(`/api/watchlist/${encodeURIComponent(sym)}`, { method: "POST" }).then((r) => r.json());
export const removeWatchlist = (sym) => fetch(`/api/watchlist/${encodeURIComponent(sym)}`, { method: "DELETE" }).then((r) => r.json());
export async function extractTickers(file) {
  const res = await fetch("/api/extract-tickers", { method: "POST", headers: { "Content-Type": file.type }, body: file });
  return res.json();
}
const post = (path, body) => fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }).then((r) => r.json());
export const authMe = () => get("/api/auth/me");
export const authLogin = (email, password, totp_code) => post("/api/auth/login", { email, password, totp_code: totp_code || null });
export const authRegister = (email, password, invite_code) => post("/api/auth/register", { email, password, invite_code });
export const authLogout = () => fetch("/api/auth/logout", { method: "POST" }).then((r) => r.json());
