// The sign-in and sign-up screen. All that is left of what was a five-surface research file.
//
// It kept its filename because nothing is gained by renaming a file every importer already points
// at, and lost everything else: the asset deep-dive, the screener, the watchlist, the library and
// the filer profile went with the research plane they belonged to.
import { useEffect, useState } from "react";
import { ForgotPassword } from "./account.jsx";
import { authLogin, authRegister, fetchRegistrationState } from "./api";
import { Disclaimer } from "./receiptsui.jsx";

const AUTH_ERRORS = {
  cancelled: "Google sign-in was cancelled.",
  no_code: "Google sign-in did not complete — no authorization code came back. Please try again.",
  failed: "Google sign-in could not be completed. You can sign in with your email and password instead.",
};


export function AuthPanel({ onAuthed, onBack, initialInvite }) {
  const [forgot, setForgot] = useState(false);
  const [mode, setMode] = useState(initialInvite ? "register" : "login");
  const [email, setEmail] = useState("");
  const [pw, setPw] = useState("");
  const [invite, setInvite] = useState(initialInvite || "");
  const [totp, setTotp] = useState("");
  // A failed Google sign-in redirects here carrying a CODE, and the wording lives here rather than
  // in the URL. Nothing used to read this at all, so the handler's promise that a failure "lands
  // the user on a page that says what went wrong" was false — the reader saw a blank login form.
  // Making it true meant putting text on the login screen, which is why only recognised codes
  // render: otherwise anyone could hand a victim a link to this real page carrying whatever
  // official-sounding sentence they liked.
  const [err, setErr] = useState(() => AUTH_ERRORS[
    new URLSearchParams(window.location.search).get("auth_error")] || null);
  // Asked, not assumed. Null while unknown, so the screen says nothing about its own rules until
  // it has an answer rather than briefly showing the wrong one.
  const [reg, setReg] = useState(null);
  useEffect(() => { fetchRegistrationState().then(setReg).catch(() => setReg(null)); }, []);
  const inviteRequired = reg?.invite_required === true;
  const submit = async () => {
    setErr(null);
    const r = mode === "login" ? await authLogin(email, pw, totp) : await authRegister(email, pw, invite);
    if (r.error) { setErr(r.error); return; }
    onAuthed(r.user);
  };
  return (
    <div className="detail" style={{ maxWidth: 440 }}>
      <button className="back" onClick={onBack}>← back</button>
      <h2>{mode === "login" ? "Log in" : "Create account"}</h2>
      <div className="meta">
        {mode === "register" && reg
          ? `${reg.note} Free tier sees signals on a 48-hour delay; paid tiers see them live.`
          : "Free tier sees signals on a 48-hour delay; paid tiers see them live."}
      </div>
      {initialInvite && mode === "register" && <div className="warn" style={{ borderColor: "#2f4a2f", color: "var(--green)", background: "#0f2417" }}>You were referred — register to start a 14-day Pro trial free.</div>}
      <div className="auth-form">
        <input className="search" style={{ width: "100%" }} placeholder="email" value={email} onChange={(e) => setEmail(e.target.value)} />
        <input className="search" style={{ width: "100%" }} type="password" placeholder="password (10+ chars)" value={pw} onChange={(e) => setPw(e.target.value)} />
        {mode === "register" && (
          <input className="search" style={{ width: "100%" }} value={invite}
                 placeholder={inviteRequired ? "invite or referral code" : "referral code (optional)"}
                 onChange={(e) => setInvite(e.target.value)} />
        )}
        {mode === "login" && <input className="search" style={{ width: "100%" }} placeholder="TOTP code (admins only)" value={totp} onChange={(e) => setTotp(e.target.value)} />}
        <button className="shot-btn" onClick={submit}>{mode === "login" ? "log in" : "register"}</button>
        {err && <div className="warn">{err}</div>}
        <button className="linkish" onClick={() => { setMode(mode === "login" ? "register" : "login"); setErr(null); }}>
          {mode === "login"
            ? (inviteRequired ? "have an invite? create an account" : "create an account")
            : "already have an account? log in"}
        </button>
        {/* Without this, a forgotten password was unrecoverable from the interface: the reset API
            existed but nothing on the login screen pointed at it. */}
        {mode === "login" && !forgot && (
          <button className="linkish" onClick={() => setForgot(true)}>forgot your password?</button>
        )}
        {mode === "login" && forgot && <ForgotPassword onBack={() => setForgot(false)} />}
      </div>
      <Disclaimer />
    </div>
  );
}
