// Publishing a call, and claiming a handle to publish under.
//
// The design problem here is not the form, it is the consent. Submitting seals a row that can
// never be edited and never be deleted, and a person who did not understand that at the moment
// they clicked has been badly served no matter how good the record looks afterwards. So the
// consequences are stated in plain language on the button's own panel rather than in terms of
// service, and the scoreability of the symbol is answered live rather than after the fact.
import { useEffect, useState } from "react";
import {
  claimHandle, fetchMyCaller, fetchScoreability, publishCall, verifyConfirm, verifyStart,
} from "./api";
import { Icon } from "./icons.jsx";
import { EmptyState, LoadError } from "./shell.jsx";
import { Disclaimer, shortHash } from "./receiptsui.jsx";

const HORIZONS = [7, 30, 90];
const CONFIDENCES = ["low", "medium", "high"];
const MIN_THESIS = 40;

function ClaimHandle({ onClaimed }) {
  const [form, setForm] = useState({ handle: "", display_name: "", bio: "", audience_url: "" });
  const [attested, setAttested] = useState(false);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  const submit = async () => {
    setBusy(true);
    setError(null);
    const res = await claimHandle({ ...form, jurisdiction_attested: attested });
    setBusy(false);
    if (res.error) setError(res.error);
    else onClaimed(res.caller);
  };

  return (
    <div className="pb-claim">
      <h1 className="rc-name">Claim a handle</h1>
      <p className="rc-lede">
        Your record lives at a permanent address. Pick the name your audience already knows you by.
      </p>

      <label className="pb-field">
        <span>handle</span>
        <input className="pb-input num" value={form.handle} onChange={set("handle")}
               placeholder="your-handle" maxLength={30} />
        <small>lower case letters, digits and hyphens. This becomes the address of your record.</small>
      </label>

      <label className="pb-field">
        <span>display name</span>
        <input className="pb-input" value={form.display_name} onChange={set("display_name")}
               placeholder="what to call you" maxLength={80} />
      </label>

      <label className="pb-field">
        <span>where your audience already is</span>
        <input className="pb-input" value={form.audience_url} onChange={set("audience_url")}
               placeholder="https://your-newsletter.example" />
        <small>optional now, and the thing you will verify later.</small>
      </label>

      <label className="pb-field">
        <span>about</span>
        <textarea className="pb-input" rows={3} value={form.bio} onChange={set("bio")}
                  maxLength={500} placeholder="one or two lines" />
      </label>

      {/* Not defaulted to checked, and the form refuses without it. This platform measures public
          statements; it does not license anyone to make them, and it must not read as though it
          does. See the disclaimer copy and callers.jurisdiction_attested. */}
      <label className="pb-attest">
        <input type="checkbox" checked={attested} onChange={(e) => setAttested(e.target.checked)} />
        <span>
          I confirm that my own regulatory and registration status in my jurisdiction is my
          responsibility, and that this platform measures what I publish rather than authorising
          me to publish it.
        </span>
      </label>

      {error && <div className="pb-error">{error}</div>}
      <button className="act act-on" disabled={busy} onClick={submit}>
        {busy ? "claiming…" : "Claim this handle"}
      </button>
    </div>
  );
}

function Verify({ caller, onChanged }) {
  const [started, setStarted] = useState(null);
  const [url, setUrl] = useState("");
  const [msg, setMsg] = useState(null);

  if (caller.verified_at) {
    return (
      <div className="pb-verified">
        <Icon name="shield" size={15} /> verified by{" "}
        {String(caller.verification_method).replace("_", " ")}
      </div>
    );
  }

  return (
    <div className="pb-verify">
      <div className="pb-verify-head">
        Your record is live and sealed. What is not yet proved is that this handle belongs to
        whoever publishes at your newsletter or your site.
      </div>
      {!started ? (
        <div className="pb-verify-methods">
          <button className="act" onClick={() => verifyStart("public_post").then(setStarted)}>
            Post a code publicly
          </button>
          <button className="act" onClick={() => verifyStart("meta_tag").then(setStarted)}>
            Add a tag to my site
          </button>
        </div>
      ) : (
        <>
          <pre className="pb-code">{started.instructions}</pre>
          <div className="pb-verify-row">
            <input className="pb-input" value={url} onChange={(e) => setUrl(e.target.value)}
                   placeholder="https://the page where you published it" />
            <button className="act act-on" onClick={() =>
              verifyConfirm(url).then((r) => { setMsg(r.error || r.note); onChanged(); })}>
              Submit
            </button>
          </div>
          {msg && <div className="pb-note">{msg}</div>}
        </>
      )}
    </div>
  );
}

function Receipt({ call, onOpenCall }) {
  return (
    <div className="pb-receipt">
      <div className="pb-receipt-head">
        <Icon name="shield" size={16} /> Sealed
      </div>
      <div className="pb-receipt-grid">
        <div><span>call</span><b className="num">#{call.seq}</b></div>
        <div><span>symbol</span><b className="num">{call.symbol}</b></div>
        <div><span>published at</span><b className="num">{call.published_at}</b></div>
        <div><span>chains from</span><b className="num" title={call.prev_hash}>{shortHash(call.prev_hash)}</b></div>
        <div className="wide"><span>content hash</span><b className="num">{call.content_hash}</b></div>
      </div>
      {call.verdict === "unscoreable" && (
        <p className="pb-unscoreable">
          Published and sealed as unscoreable: {call.verdict_note}
        </p>
      )}
      <button className="act" onClick={() => onOpenCall(call.id)}>Open the proof panel</button>
    </div>
  );
}

function Form({ onPublished, onOpenCall }) {
  const [spec, setSpec] = useState({ symbol: "", direction: "up", horizon_days: 30,
                                     confidence: "medium", thesis: "" });
  const [score, setScore] = useState(null);
  const [problems, setProblems] = useState([]);
  const [busy, setBusy] = useState(false);
  const [receipt, setReceipt] = useState(null);

  // Live scoreability as the symbol is typed. Debounced, because this is a database read on every
  // keystroke otherwise, and the answer for "A" is never the answer anybody wanted.
  useEffect(() => {
    const sym = spec.symbol.trim().toUpperCase();
    if (sym.length < 1) { setScore(null); return undefined; }
    const t = setTimeout(() => { fetchScoreability(sym).then(setScore).catch(() => setScore(null)); }, 320);
    return () => clearTimeout(t);
  }, [spec.symbol]);

  const submit = async () => {
    setBusy(true);
    setProblems([]);
    const res = await publishCall({ ...spec, symbol: spec.symbol.trim().toUpperCase() });
    setBusy(false);
    if (res.error) { setProblems(res.problems || [res.error]); return; }
    setReceipt(res.call);
    onPublished();
  };

  if (receipt) {
    return (
      <div className="pb-done">
        <Receipt call={receipt} onOpenCall={onOpenCall} />
        <button className="act" onClick={() => { setReceipt(null); setSpec({ ...spec, symbol: "", thesis: "" }); }}>
          Publish another
        </button>
      </div>
    );
  }

  const thesisShort = spec.thesis.trim().length < MIN_THESIS;

  return (
    <div className="pb-form">
      <div className="pb-row">
        <label className="pb-field">
          <span>symbol</span>
          <input className="pb-input num" value={spec.symbol} maxLength={12}
                 onChange={(e) => setSpec({ ...spec, symbol: e.target.value })} placeholder="AAPL" />
        </label>
        <label className="pb-field">
          <span>direction</span>
          <div className="pb-seg">
            {["up", "down"].map((d) => (
              <button key={d} className={spec.direction === d ? "on" : ""}
                      onClick={() => setSpec({ ...spec, direction: d })}>{d}</button>
            ))}
          </div>
        </label>
      </div>

      {score && (
        <div className={`pb-score ${score.scoreable ? "ok" : score.permanent ? "bad" : "warn"}`}>
          <Icon name={score.scoreable ? "target" : "alert"} size={14} />
          <span>{score.reason}</span>
        </div>
      )}

      <div className="pb-row">
        <label className="pb-field">
          <span>horizon</span>
          <div className="pb-seg">
            {HORIZONS.map((h) => (
              <button key={h} className={spec.horizon_days === h ? "on" : ""}
                      onClick={() => setSpec({ ...spec, horizon_days: h })}>{h} days</button>
            ))}
          </div>
        </label>
        <label className="pb-field">
          <span>confidence</span>
          <div className="pb-seg">
            {CONFIDENCES.map((c) => (
              <button key={c} className={spec.confidence === c ? "on" : ""}
                      onClick={() => setSpec({ ...spec, confidence: c })}>{c}</button>
            ))}
          </div>
        </label>
      </div>

      <label className="pb-field">
        <span>thesis</span>
        <textarea className="pb-input" rows={5} value={spec.thesis}
                  onChange={(e) => setSpec({ ...spec, thesis: e.target.value })}
                  placeholder="why you think this, in your own words" />
        <small className={thesisShort ? "short" : ""}>
          {spec.thesis.trim().length} of at least {MIN_THESIS} characters. This is the part a reader
          judges, and it is sealed with everything else.
        </small>
      </label>

      {/* The consent panel. Stated here, in these words, rather than in terms nobody opens. */}
      <div className="pb-consent">
        <b>Read this before you publish.</b>
        <ul>
          <li>This call is sealed the moment you submit it.</li>
          <li>It cannot be edited afterwards, by you or by us.</li>
          <li>It cannot be deleted afterwards, by you or by us.</li>
          <li>The horizon cannot be changed, and neither can the direction or the thesis.</li>
          <li>
            When the horizon closes it is scored against SPY and the result appears on your public
            record whichever way it goes.
          </li>
        </ul>
      </div>

      {problems.length > 0 && (
        <div className="pb-error">
          <b>This call was not published.</b>
          <ul>{problems.map((p) => <li key={p}>{p}</li>)}</ul>
        </div>
      )}

      <button className="act act-on pb-submit" disabled={busy} onClick={submit}>
        {busy ? "sealing…" : "Seal and publish"}
      </button>
    </div>
  );
}

export function PublishView({ user, onLogin, onOpenCall, onOpenRecord }) {
  const [state, setState] = useState(null);
  const [failed, setFailed] = useState(false);

  const load = () => {
    setFailed(false);
    fetchMyCaller().then(setState).catch(() => setFailed(true));
  };
  useEffect(() => { if (user) load(); }, [user]);

  if (!user) {
    return (
      <EmptyState title="Sign in to publish"
                  action={<button className="act act-on" onClick={onLogin}>Sign in</button>}>
        Reading every record is free and needs no account. Publishing one needs a handle, so that
        what you say is attached to a name that keeps it.
      </EmptyState>
    );
  }
  if (failed) return <LoadError what="your record" onRetry={load} />;
  if (!state) return <div className="rc-skel"><div className="skel" style={{ width: 300, height: 44 }} /></div>;
  if (!state.caller) return <ClaimHandle onClaimed={load} />;

  return (
    <div className="pb-page">
      <header className="pb-head">
        <div>
          <h1 className="rc-name">Publish a call</h1>
          <div className="rc-handle num">@{state.caller.handle}</div>
        </div>
        <button className="act" onClick={() => onOpenRecord(state.caller.handle)}>
          See my record
        </button>
      </header>

      <Verify caller={state.caller} onChanged={load} />
      <Form onPublished={load} onOpenCall={onOpenCall} />
      {/* From the server, never typed here: one sentence, one source, no copy to drift. */}
      <Disclaimer text={state.disclaimer} />
    </div>
  );
}
