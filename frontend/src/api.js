// Same-origin API. Every function here answers one route that exists; nothing is fabricated or
// interpolated on this side, and a number a surface renders was computed by the server from a
// stored record.
//
// This file was 209 lines and 129 exports across the research plane. It is now the Receipts
// surface and the account screens, and nothing else — an api.js holding a `fetchCryptoTrending`
// against a route that no longer exists is a trap for the next person, not a spare part.
async function get(path) {
  const res = await fetch(path, { headers: { Accept: "application/json" } });
  if (!res.ok) throw new Error(`${path} -> ${res.status}`);
  return res.json();
}

// A 404 from a record or a call is an ANSWER, not a failure: nobody holds that handle. `get`
// throws on any non-2xx, which turned "no such record" into a generic error panel with a Retry
// button that could never succeed — on the two routes most likely to be reached by a shared link
// with a typo in it. These two resolve the body instead, so the surface can render the empty state
// it already has. Every other status still throws.
async function getOr404(path) {
  const res = await fetch(path, { headers: { Accept: "application/json" } });
  if (res.status === 404) return res.json();
  if (!res.ok) throw new Error(`${path} -> ${res.status}`);
  return res.json();
}

const post = (path, body) =>
  fetch(path, { method: "POST", headers: { "Content-Type": "application/json" },
                body: JSON.stringify(body) }).then((r) => r.json());

// ------------------------------------------------------------------ accounts

export const authMe = () => get("/api/auth/me");
export const authLogin = (email, password, totp_code) =>
  post("/api/auth/login", { email, password, totp_code: totp_code || null });
export const authRegister = (email, password, invite_code) =>
  post("/api/auth/register", { email, password, invite_code });
export const authLogout = () => fetch("/api/auth/logout", { method: "POST" }).then((r) => r.json());
// Whether an account can be created at all, and whether a code is needed. The auth screen used to
// print "Invite-only." as a hardcoded string; once the flag is runtime-settable that sentence is a
// guess, and a signup screen is the worst place in the product to guess wrong about itself.
export const fetchRegistrationState = () => get("/api/auth/registration");
export const confirmEmail = (token) => post("/api/auth/verify/confirm", { token });
export const requestReset = (email) => post("/api/auth/reset/request", { email });
export const confirmReset = (token, password) => post("/api/auth/reset/confirm", { token, password });

// ------------------------------------------------------------------ Receipts
//
// The public reads take no session on purpose: a stranger following a shared record link has to be
// able to check a caller without an account, which is the whole argument.

export const fetchBoard = () => get("/api/board");
export const fetchRecord = (handle) => getOr404(`/api/receipts/${encodeURIComponent(handle)}`);
export const verifyChain = (handle) => get(`/api/receipts/${encodeURIComponent(handle)}/verify`);
export const fetchReceiptsMethodology = () => get("/api/receipts/methodology");
export const fetchCall = (id) => getOr404(`/api/calls/${encodeURIComponent(id)}`);
export const fetchMyCaller = () => get("/api/callers/me");

// Ticker autocomplete, restricted to symbols we hold prices for. "No price series" is the one
// remaining route to a permanent unscoreable verdict, so the form offers the universe rather than
// letting a caller type their way into it.
export const fetchSymbols = (q) => get(`/api/calls/symbols?q=${encodeURIComponent(q)}`);
// What a caller is committing to, before they commit. Deliberately returns NO PRICE: entry is the
// close of the first session after publication and does not exist yet, and our copy of any close
// is the vendor's data (see receipts/record.py NO_PRICES).
export const fetchPreview = (symbol, horizon_days) =>
  get(`/api/calls/preview?symbol=${encodeURIComponent(symbol)}&horizon_days=${horizon_days}`);

export const claimHandle = (payload) => post("/api/callers", payload);
export const publishCall = (payload) => post("/api/calls", payload);
export const verifyStart = (method) => post("/api/callers/verify/start", { method });
export const verifyConfirm = (evidence_url) => post("/api/callers/verify/confirm", { evidence_url });
