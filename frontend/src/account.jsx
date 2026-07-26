// Email verification and password reset — the two surfaces someone reaches from an email.
//
// The token arrives in the URL FRAGMENT (`/reset#token=…`), never the query string. A fragment is
// not transmitted to the server, so it cannot land in an access log, a proxy log, or a Referer
// header; a query string lands in all three, and a reset token in a log file is a working account.
// It is read here and sent in a POST body.
//
// Both screens are deliberately plain. Someone arriving here is either finishing a signup or
// locked out, and neither is a moment for chrome.
import { useEffect, useState } from "react";
import { confirmEmail, confirmReset, requestReset } from "./api";

function tokenFromHash() {
  const m = /(?:^|[#&])token=([^&]+)/.exec(window.location.hash || "");
  return m ? decodeURIComponent(m[1]) : "";
}

/** Clear the token from the address bar once read, so it is not left in browser history or
 *  shoulder-surfable. The capability is already in memory by then. */
function scrubHash() {
  if (window.location.hash) {
    window.history.replaceState({}, "", window.location.pathname);
  }
}

function Shell({ title, children }) {
  return (
    <div className="acct">
      <h1 className="acct-h">{title}</h1>
      {children}
    </div>
  );
}

export function VerifyView({ onDone }) {
  const [state, setState] = useState({ status: "working" });

  useEffect(() => {
    const token = tokenFromHash();
    scrubHash();
    // Verification is idempotent from the user's side — a second link just re-runs the check.
    if (!token) { setState({ status: "error", msg: "This link is missing its token." }); return; }
    confirmEmail(token)
      .then((r) => setState(r.ok ? { status: "ok" } : { status: "error", msg: r.error }))
      .catch(() => setState({ status: "error", msg: "Could not reach the server." }));
  }, []);

  return (
    <Shell title="Confirm your email">
      {state.status === "working" && <p className="acct-p">Checking that link…</p>}
      {state.status === "ok" && (
        <>
          <p className="acct-p">Done — this address is confirmed.</p>
          <button className="act act-on" onClick={() => onDone("radar")}>Go to the Radar</button>
        </>
      )}
      {state.status === "error" && (
        <>
          <p className="acct-p acct-err">{state.msg}</p>
          <p className="acct-note">
            Verification links last 24 hours and work once. Request a new one from your account
            settings — nothing is lost, and an unverified address does not limit anything today.
          </p>
        </>
      )}
    </Shell>
  );
}

export function ResetView({ onDone }) {
  // Read once on mount, then again on `hashchange`. Opening a SECOND reset link while this page is
  // already open is a fragment-only navigation, which does not reload the document — so without
  // this the screen keeps the first token and rejects a link the user just clicked. Found by
  // driving the flow twice in a browser rather than once.
  const [token, setToken] = useState(tokenFromHash);
  const [pw, setPw] = useState("");
  const [pw2, setPw2] = useState("");
  const [state, setState] = useState({ status: token ? "form" : "notoken" });

  useEffect(() => {
    scrubHash();
    const onHash = () => { const t = tokenFromHash(); if (t) { setToken(t); setState({ status: "form" }); scrubHash(); } };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  const submit = async (e) => {
    e.preventDefault();
    if (pw !== pw2) { setState({ status: "form", msg: "Those two passwords do not match." }); return; }
    setState({ status: "working" });
    try {
      const r = await confirmReset(token, pw);
      setState(r.ok ? { status: "ok" } : { status: "form", msg: r.error });
    } catch {
      setState({ status: "form", msg: "Could not reach the server." });
    }
  };

  if (state.status === "notoken") {
    return (
      <Shell title="Reset your password">
        <p className="acct-p acct-err">This link is missing its token.</p>
        <p className="acct-note">Open the link from the email exactly as it was sent.</p>
      </Shell>
    );
  }
  if (state.status === "ok") {
    return (
      <Shell title="Password changed">
        <p className="acct-p">
          Done. Every other session on this account has been signed out, including any you did not
          recognise — sign in again with the new password.
        </p>
        <button className="act act-on" onClick={() => onDone("auth")}>Sign in</button>
      </Shell>
    );
  }

  return (
    <Shell title="Choose a new password">
      <form onSubmit={submit} className="acct-form">
        <label className="ob-field">
          <span className="ob-l">New password</span>
          <input type="password" value={pw} onChange={(e) => setPw(e.target.value)}
                 autoComplete="new-password" autoFocus />
        </label>
        <label className="ob-field">
          <span className="ob-l">Again</span>
          <input type="password" value={pw2} onChange={(e) => setPw2(e.target.value)}
                 autoComplete="new-password" />
        </label>
        {state.msg && <p className="acct-p acct-err">{state.msg}</p>}
        <button className="act act-on" type="submit" disabled={state.status === "working" || !pw}>
          {state.status === "working" ? "saving…" : "Set the new password"}
        </button>
        <p className="acct-note">
          Setting a new password signs out every other session on the account.
        </p>
      </form>
    </Shell>
  );
}

/** The "I forgot" form. Its answer is identical whether or not the address has an account —
 *  anything else turns this into a free membership check. */
export function ForgotPassword({ onBack }) {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(null);

  const submit = async (e) => {
    e.preventDefault();
    const r = await requestReset(email).catch(() => null);
    setSent(r?.message || "If that address has an account, a message is on its way.");
  };

  if (sent) return <p className="acct-note" style={{ marginTop: 10 }}>{sent}</p>;
  return (
    <form onSubmit={submit} className="acct-form" style={{ marginTop: 10 }}>
      <label className="ob-field">
        <span className="ob-l">Your email</span>
        <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
      </label>
      <div className="controls">
        <button className="act act-on" type="submit">Send a reset link</button>
        <button className="act" type="button" onClick={onBack}>Back</button>
      </div>
    </form>
  );
}
