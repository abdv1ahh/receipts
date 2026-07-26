// Same-origin API. The dashboard only ever renders numbers the backend computed from real
// records — it never fabricates or interpolates a value.
async function get(path) {
  const res = await fetch(path, { headers: { Accept: "application/json" } });
  if (!res.ok) throw new Error(`${path} -> ${res.status}`);
  return res.json();
}

export const fetchHome = (minConfidence = "medium") =>
  get(`/api/home?min_confidence=${encodeURIComponent(minConfidence)}`);
export const fetchLeaderboards = () => get("/api/leaderboards");
export const fetchClusters = (minConfidence) =>
  get(`/api/clusters?as_of=latest&min_confidence=${encodeURIComponent(minConfidence)}`);
export const fetchClusterDetail = (issuerId) => get(`/api/clusters/${issuerId}?as_of=latest`);
export const fetchExplanation = (issuerId, horizon) =>
  get(`/api/clusters/${issuerId}/explanation?horizon=${horizon}`);
export const fetchFeeds = () => get("/api/feeds");
// Integration status (brief §4): every external source, its state, what it powers, and its health.
export const fetchIntegrations = () => get("/api/integrations");
// Radar + Ledger (Phases 3-4): interpretations ranked by personal relevance, and the accuracy record.
export const fetchClaims = ({ hours = 336, limit = 60 } = {}) => get(`/api/claims?hours=${hours}&limit=${limit}`);
export const fetchLedger = () => get("/api/ledger");
export const fetchCountries = () => get("/api/countries");
export const fetchGlobe = () => get("/api/globe");
export const fetchExposure = () => get("/api/exposure");
export const saveProfileFrame = (frame) =>
  fetch("/api/profile/frame", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(frame) }).then((r) => r.json());
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

// First-run setup (Phase 8): the reader's FRAME — country, currency, starting watchlist — without
// which relevance cannot rank. Named for the frame rather than for "onboarding", because
// `fetchOnboarding` below is the older activation checklist and two of those would shadow.
// Verification and reset. The token travels in a POST body, never a URL — see mail.py.
export const requestVerify = (email) => post("/api/auth/verify/request", { email });
export const confirmEmail = (token) => post("/api/auth/verify/confirm", { token });
export const requestReset = (email) => post("/api/auth/reset/request", { email });
export const confirmReset = (token, password) => post("/api/auth/reset/confirm", { token, password });
export const fetchFrameSetup = () => get("/api/profile/onboarding");
export const saveFrameSetup = (body) => post("/api/profile/onboarding", body);
export const snoozeFrameSetup = () => post("/api/profile/onboarding/skip", {});
export const fetchFollows = () => get("/api/follows");
export const addFollow = (kind, ref, label) => post("/api/follows", { kind, ref, label });
export const removeFollow = (id) => fetch(`/api/follows/${id}`, { method: "DELETE" }).then((r) => r.json());
export const fetchNotifications = () => get("/api/notifications");
export const markNotificationsRead = () => fetch("/api/notifications/read", { method: "POST" }).then((r) => r.json());
export const fetchAlertPrefs = () => get("/api/alert-prefs");
export const saveAlertPrefs = (prefs) => fetch("/api/alert-prefs", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(prefs) }).then((r) => r.json());
export const fetchBrief = () => get("/api/brief");
export const fetchDashboard = () => get("/api/dashboard");
// News Intelligence (Milestone 1): impact-ranked, cited market news + the analyst's "why it matters".
export const fetchNews = ({ symbol, category, hours, limit } = {}) => {
  const p = new URLSearchParams();
  if (symbol) p.set("symbol", symbol);
  if (category) p.set("category", category);
  if (hours) p.set("hours", hours);
  if (limit) p.set("limit", limit);
  const q = p.toString();
  return get(`/api/news${q ? `?${q}` : ""}`);
};
export const fetchNewsItem = (id) => get(`/api/news/${id}`);
// Source comparison (Phase 6): how differently outlets frame one event, and where coverage is thin.
export const fetchNewsCoverage = (hours = 96) => get(`/api/news/coverage?hours=${hours}`);
export const fetchJobs = () => get("/api/jobs");
export const fetchEvents = (days = 10) => get(`/api/events?days=${days}`);
export const fetchPortfolios = () => get("/api/portfolios");
export const getPortfolio = (id) => get(`/api/portfolios/${id}`);
export const createPortfolio = (name, kind, buckets) => post("/api/portfolios", { name, kind, buckets: buckets || null });
export const addPosition = (id, symbol, opened_on) => post(`/api/portfolios/${id}/positions`, { symbol, opened_on: opened_on || null });
export const deletePortfolio = (id) => fetch(`/api/portfolios/${id}`, { method: "DELETE" }).then((r) => r.json());
export const removePosition = (id, posId) => fetch(`/api/portfolios/${id}/positions/${posId}`, { method: "DELETE" }).then((r) => r.json());
export const fetchTrackRecord = () => get("/api/track-record");
// Quick-shadow one name into a default "My shadows" portfolio (create it if needed).
export async function shadowSymbol(symbol) {
  const d = await fetchPortfolios();
  if (d.authenticated === false) return { error: "login" };
  let p = (d.portfolios || []).find((x) => x.name === "My shadows");
  if (!p) { const c = await createPortfolio("My shadows", "manual"); p = { id: c.id }; }
  return addPosition(p.id, symbol);
}
// Trade journal (Slice E). The analysis is guarded server-side; the UI renders only what it returns.
export const fetchTrades = () => get("/api/trades");
export const fetchPublicTrades = (userId) => get(`/api/trades?user_id=${userId}`);
export const getTrade = (id) => get(`/api/trades/${id}`);
export const createTrade = (t) => post("/api/trades", t);
export const updateTrade = (id, t) => fetch(`/api/trades/${id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(t) }).then((r) => r.json());
export const deleteTrade = (id) => fetch(`/api/trades/${id}`, { method: "DELETE" }).then((r) => r.json());
export const fetchTradeAnalysis = (id) => get(`/api/trades/${id}/analysis`);
export const uploadTradeImage = (id, file) => fetch(`/api/trades/${id}/image`, { method: "POST", headers: { "Content-Type": file.type }, body: file }).then((r) => r.json());
export const fetchPerformance = () => get("/api/performance");
// AI chart analysis (Milestone 6): educational read of the trade's chart screenshot; refresh re-runs it.
export const fetchChartAnalysis = (id, refresh = false) => get(`/api/trades/${id}/chart-analysis${refresh ? "?refresh=1" : ""}`);
export const analyzeChartImage = (file) => fetch("/api/analyze-chart", { method: "POST", headers: { "Content-Type": file.type }, body: file }).then((r) => r.json());
// Advanced AI (Slice L): similar-trade finder, scenario simulator, auto journal report.
export const fetchSimilarTrades = (id) => get(`/api/trades/${id}/similar`);
export const simulateTrade = (params) => post("/api/simulate", params);
export const fetchJournalReport = () => get("/api/journal/report");
// World context frozen at trade time (Phase 6). Owner-only — the ranking exposes the owner's frame.
export const fetchTradeContext = (id) => get(`/api/trades/${id}/context`);
export const askAssistant = (message) => post("/api/assistant", { message });
export const fetchTrending = (hours = 48) => get(`/api/trending?hours=${hours}`);
export const fetchSymbolSentiment = (symbol) => get(`/api/sentiment/${encodeURIComponent(symbol)}`);
// Community (Slice F)
export const fetchCommunityFeed = (scope = "public", beforeId) => get(`/api/community/feed?scope=${scope}${beforeId ? `&before_id=${beforeId}` : ""}`);
export const fetchProfile = (handle) => get(`/api/u/${encodeURIComponent(handle)}`);
export const setProfile = (handle, bio) => fetch("/api/profile", { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ handle, bio }) }).then((r) => r.json());
export const followUser = (handle) => post("/api/users/follow", { handle });
export const unfollowUser = (handle) => fetch(`/api/users/follow/${encodeURIComponent(handle)}`, { method: "DELETE" }).then((r) => r.json());
export const reactTrade = (id, kind) => post(`/api/trades/${id}/react`, { kind });
export const unreactTrade = (id, kind) => fetch(`/api/trades/${id}/react/${kind}`, { method: "DELETE" }).then((r) => r.json());
export const fetchComments = (id) => get(`/api/trades/${id}/comments`);
export const addComment = (id, body) => post(`/api/trades/${id}/comments`, { body });
export const deleteComment = (cid) => fetch(`/api/comments/${cid}`, { method: "DELETE" }).then((r) => r.json());
export const reportContent = (target_type, target_id, reason) => post("/api/report", { target_type, target_id, reason });
export const fetchTraderLeaderboard = () => get("/api/leaderboard/traders");
export const fetchCryptoMarkets = (limit = 25) => get(`/api/crypto/markets?limit=${limit}`);
export const fetchCryptoTrending = () => get("/api/crypto/trending");
// Market structure (Phase 6): positioning and liquidity, not another price table.
export const fetchCryptoStructure = () => get("/api/crypto/structure");
export const fetchSearch = (q) => get(`/api/search?q=${encodeURIComponent(q)}`);
// Admin dashboard (Slice K) — every route is admin-only server-side (tier=admin, TOTP at login).
export const adminOverview = () => get("/api/admin/overview");
export const adminModeration = () => get("/api/admin/moderation");
export const adminResolve = (target_type, target_id, action) => post("/api/admin/moderation/resolve", { target_type, target_id, action });
export const adminUsers = (q = "") => get(`/api/admin/users?q=${encodeURIComponent(q)}`);
export const adminSetTier = (uid, tier) => post(`/api/admin/users/${uid}/tier`, { tier });
export const adminSetBanned = (uid, banned) => post(`/api/admin/users/${uid}/ban`, { banned });
export const adminFlags = () => get("/api/admin/flags");
export const adminSetFlag = (name, enabled) => post(`/api/admin/flags/${encodeURIComponent(name)}`, { enabled });
export const adminAudit = (action = "", limit = 100) => get(`/api/admin/audit?limit=${limit}${action ? `&action=${encodeURIComponent(action)}` : ""}`);

export const fetchOnboarding = () => get("/api/onboarding");
export const fetchReferral = () => get("/api/referral");
export const fetchPlans = () => get("/api/billing/plans");
export const checkout = (plan) => post("/api/billing/checkout", { plan });
export const testActivate = (plan) => post("/api/billing/test-activate", { plan });
export const cancelSub = () => fetch("/api/billing/cancel", { method: "POST" }).then((r) => r.json());
export const fetchKeys = () => get("/api/keys");
export const createKey = (name) => post("/api/keys", { name });
export const revokeKey = (id) => fetch(`/api/keys/${id}`, { method: "DELETE" }).then((r) => r.json());
export const authMe = () => get("/api/auth/me");
export const authLogin = (email, password, totp_code) => post("/api/auth/login", { email, password, totp_code: totp_code || null });
export const authRegister = (email, password, invite_code) => post("/api/auth/register", { email, password, invite_code });
export const authLogout = () => fetch("/api/auth/logout", { method: "POST" }).then((r) => r.json());
