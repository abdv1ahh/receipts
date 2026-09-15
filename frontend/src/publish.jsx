// Publishing a call, and claiming a handle to publish under. PHONE FIRST.
//
// The design problem here is not the form, it is the consent. Submitting seals a row that can
// never be edited and never be deleted, and a person who did not understand that at the moment
// they tapped has been badly served no matter how good the record looks afterwards.
//
// Rebuilt for a phone, because a caller who needs a laptop stops within a week. What that changed:
//
//   ONE COLUMN.          The old form put symbol beside direction and horizon beside confidence,
//                        which at 375px stacked into four rows anyway with the horizon buttons
//                        wrapping 2+1 so a three-way choice read as two.
//   THE UNIVERSE.        The symbol field was free text with the placeholder `AAPL`, and this
//                        database holds ZERO price rows for AAPL: a caller following the form's
//                        own example sealed a permanent unscoreable on their first call. It is now
//                        chosen from what we can actually score.
//   NO DEFAULT ON THE    Direction and window used to arrive preselected ("up", 30 days), so a
//   TWO REAL DECISIONS.  caller could seal a permanent call in the wrong direction by not
//                        noticing. Both must now be tapped. That is two taps bought back for the
//                        one thing on this screen that cannot be corrected.
//   THE COMMITMENT       Numbers, not adjectives: the last close we hold and its date, the
//   PANEL.               benchmark beside it, the date the window closes, and the entry rule in
//                        words. Visible before the tap, because it IS the confirmation step --
//                        a separate review screen would be one more tap and one more thing to skim.
//
// What is deliberately NOT here: a confirmation checkbox. A checkbox converts reading into a tap
// and teaches people to tap. The permanence sentence sits immediately above the button with
// nothing between them instead.
import { useEffect, useMemo, useState } from "react";
import {
  claimHandle, fetchMyCaller, fetchPreview, fetchSymbols, publishCall, verifyConfirm, verifyStart,
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
    // The finally is the point: a rejected fetch used to skip setBusy(false) and leave the button
    // reading "claiming…" forever, which looks exactly like a request still in flight.
    try {
      const res = await claimHandle({ ...form, jurisdiction_attested: attested });
      if (res.error) setError(res.error);
      else onClaimed(res.caller);
    } catch {
      setError("That did not reach us. Nothing was claimed, so it is safe to try again.");
    } finally {
      setBusy(false);
    }
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

  const start = async (method) => {
    setMsg(null);
    try {
      const res = await verifyStart(method);
      if (res.code) setStarted(res);
      else setMsg(res.error || "No code came back. Nothing has changed, so try again.");
    } catch {
      setMsg("That did not reach us. Nothing has changed, so try again.");
    }
  };

  const confirm = async () => {
    try {
      const r = await verifyConfirm(url);
      setMsg(r.error || r.note);
      onChanged();
    } catch {
      setMsg("That did not reach us. Your link was not submitted.");
    }
  };

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
          {/* `start` only advances on a code actually coming back. Without that check a failed
              request still flipped to the next panel and rendered an empty code box, telling the
              caller to publish a code that had never been issued, with no way back here. */}
          <button className="act" onClick={() => start("public_post")}>Post a code publicly</button>
          <button className="act" onClick={() => start("meta_tag")}>Add a tag to my site</button>
          {msg && <div className="pb-error">{msg}</div>}
        </div>
      ) : (
        <>
          <pre className="pb-code">{started.instructions}</pre>
          <div className="pb-verify-row">
            <input className="pb-input" value={url} onChange={(e) => setUrl(e.target.value)}
                   placeholder="https://the page where you published it" />
            <button className="act act-on" onClick={confirm}>Submit</button>
          </div>
          {msg && <div className="pb-note">{msg}</div>}
        </>
      )}
    </div>
  );
}

function Receipt({ call, caller, onOpenCall }) {
  const [shared, setShared] = useState(null);
  const url = `${window.location.origin}/r/${caller.handle}`;

  // `navigator.share` is the phone answer and the reason this button exists at all: on a phone it
  // opens the same sheet every other app shares through, so the call goes where the caller's
  // audience already is. Everywhere else it falls back to the clipboard and SAYS it did, rather
  // than doing nothing and looking broken. Both paths are wrapped, because a share sheet the user
  // dismisses rejects, and an unhandled rejection here would leave the button dead.
  const share = async () => {
    const text = `${call.symbol} ${call.direction} over ${call.horizon_days} days. Sealed, scored against SPY, and on the record whichever way it goes.`;
    try {
      if (navigator.share) {
        await navigator.share({ title: `@${caller.handle} on ${call.symbol}`, text, url });
        setShared("shared");
        return;
      }
      await navigator.clipboard.writeText(url);
      setShared("copied");
    } catch {
      setShared("manual");
    }
  };

  return (
    <div className="pb-receipt">
      <div className="pb-receipt-head">
        <Icon name="shield" size={16} /> Sealed
      </div>
      <div className="pb-receipt-grid">
        <div><span>call</span><b className="num">#{call.seq}</b></div>
        <div><span>symbol</span><b className="num">{call.symbol} {call.direction}</b></div>
        <div><span>window</span><b className="num">{call.horizon_days} days</b></div>
        <div><span>published at</span><b className="num">{call.published_at}</b></div>
        <div><span>chains from</span><b className="num" title={call.prev_hash}>{shortHash(call.prev_hash)}</b></div>
        <div className="wide"><span>content hash</span><b className="num">{call.content_hash}</b></div>
      </div>
      {call.verdict === "unscoreable" && (
        <p className="pb-unscoreable">
          Published and sealed as unscoreable: {call.verdict_note}
        </p>
      )}
      <div className="pb-done-acts">
        <button className="act act-on" onClick={share}>
          Share this call
        </button>
        <button className="act" onClick={() => onOpenCall(call.id)}>The proof panel</button>
      </div>
      {shared === "copied" && <div className="pb-note">Link copied: {url}</div>}
      {shared === "manual" && <div className="pb-note">Copy this link: {url}</div>}
    </div>
  );
}

/** The ticker field. Chosen from what we can score, never typed into. */
function SymbolPicker({ value, onPick }) {
  const [text, setText] = useState(value || "");
  const [res, setRes] = useState(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const q = text.trim().toUpperCase();
    if (q.length < 1) { setRes(null); return undefined; }
    if (q === value) return undefined;                  // already chosen; do not re-query
    // Debounced, because this is a request per keystroke otherwise and the answer for "A" is never
    // the answer anybody wanted. The universe itself is cached server side, so the round trip is
    // the only cost.
    const t = setTimeout(() => {
      fetchSymbols(q).then((r) => { setRes(r); setOpen(true); }).catch(() => setRes(null));
    }, 200);
    return () => clearTimeout(t);
  }, [text, value]);

  const pick = (sym) => { onPick(sym); setText(sym); setOpen(false); };

  return (
    <div className="pb-field pb-sym">
      <span>ticker</span>
      <input className="pb-input pb-input-lg num" value={text} maxLength={12}
             inputMode="text" autoCapitalize="characters" autoCorrect="off" spellCheck={false}
             placeholder="start typing"
             onFocus={() => setOpen(true)}
             onChange={(e) => { setText(e.target.value); onPick(""); }} />
      {open && res && res.matches.length > 0 && (
        <div className="pb-sugg">
          {res.matches.map((m) => (
            <button key={m.symbol} className="pb-sugg-row" onClick={() => pick(m.symbol)}>
              <span className="num pb-sugg-sym">{m.symbol}</span>
              {m.fresh ? (
                <span className="pb-sugg-ok">priced to {m.last_close}</span>
              ) : (
                <span className="pb-sugg-stale">
                  our prices stop at {m.last_close}, {m.days_behind} days behind
                </span>
              )}
            </button>
          ))}
        </div>
      )}
      {/* The blocked path, in plain language. A blank dropdown tells a caller nothing; "we hold
          2,018 symbols and none of them start with that" tells them what to do next. */}
      {open && res && res.matches.length === 0 && res.note && (
        <div className="pb-blocked">
          <Icon name="alert" size={14} />
          <span>{res.note}</span>
        </div>
      )}
      {!value && <small>Pick one from the list. A call can only be published on a symbol we hold
        prices for, because anything else could never be scored.</small>}
    </div>
  );
}

/** What is being agreed to, in numbers, before it is agreed to. */
function Commitment({ preview, horizon }) {
  if (!preview) return null;
  const s = preview.scoreability;
  return (
    <div className="pb-commit">
      <div className="pb-commit-rows">
        <div>
          <span>measured from</span>
          {/* NOT an entry price, and it must never be labelled as one. Entry is the close of the
              first session after publication: at this moment that number does not exist, for the
              caller or for us. Printing the last close as "entry" would be the most damaging
              small lie this product could tell. */}
          <b>the next session's close</b>
        </div>
        <div>
          <span>last close we hold</span>
          <b className="num">
            {preview.last_close == null ? "—" : preview.last_close}
            <small> {preview.last_close_day}</small>
          </b>
        </div>
        <div>
          <span>{preview.benchmark} at that close</span>
          <b className="num">
            {preview.benchmark_last_close == null ? "—" : preview.benchmark_last_close}
          </b>
        </div>
        <div>
          <span>scored on or after</span>
          <b className="num">{preview.horizon_target}<small> {horizon} days</small></b>
        </div>
      </div>
      <p className="pb-commit-rule">{preview.entry_rule}</p>
      {!s.scoreable && (
        <p className={`pb-commit-warn ${s.permanent ? "bad" : "warn"}`}>{s.reason}</p>
      )}
    </div>
  );
}

function Form({ caller, onPublished, onOpenCall }) {
  // Every setter below uses the FUNCTIONAL form, `setSpec((s) => ...)`, and that is not style.
  // With `setSpec({ ...spec, direction: d })` each handler closes over the `spec` from its own
  // render, so two taps inside one React batch both read the same stale object and the second
  // silently overwrites the first — tapping a direction and then a window lost the direction.
  // Found by driving this form from a script at 375px, which taps faster than a thumb can. On a
  // screen where the fields define a permanently sealed call, a dropped field is not a glitch.
  const [spec, setSpec] = useState({ symbol: "", direction: "", horizon_days: 0,
                                     confidence: "medium", thesis: "" });
  const [preview, setPreview] = useState(null);
  const [problems, setProblems] = useState([]);
  const [busy, setBusy] = useState(false);
  const [receipt, setReceipt] = useState(null);

  // The preview arrives as soon as both real decisions are made, so the commitment panel is
  // already populated when the caller reaches the button. No separate review screen: that would be
  // one more tap and one more thing to skim past.
  useEffect(() => {
    if (!spec.symbol || !spec.horizon_days) { setPreview(null); return undefined; }
    let live = true;
    fetchPreview(spec.symbol, spec.horizon_days)
      .then((p) => { if (live) setPreview(p.error ? null : p); })
      .catch(() => { if (live) setPreview(null); });
    return () => { live = false; };
  }, [spec.symbol, spec.horizon_days]);

  const thesis = spec.thesis.trim();
  const thesisShort = thesis.length > 0 && thesis.length < MIN_THESIS;
  const ready = useMemo(
    () => Boolean(spec.symbol && spec.direction && spec.horizon_days) && !thesisShort,
    [spec.symbol, spec.direction, spec.horizon_days, thesisShort]);

  const submit = async () => {
    setBusy(true);
    setProblems([]);
    try {
      const res = await publishCall({ ...spec, symbol: spec.symbol.trim().toUpperCase() });
      if (res.error) { setProblems(res.problems || [res.error]); return; }
      setReceipt(res.call);
      onPublished();
    } catch {
      // Deliberately careful wording. A publish that failed to REACH us sealed nothing, and a
      // caller who believes a call might have been published when it was not is worse off than one
      // told plainly to check their record.
      setProblems(["That did not reach us. Check your record before publishing again, in case it "
                   + "arrived and the reply did not."]);
    } finally {
      setBusy(false);
    }
  };

  if (receipt) {
    return (
      <div className="pb-done">
        <Receipt call={receipt} caller={caller} onOpenCall={onOpenCall} />
        <button className="act" onClick={() => {
          setReceipt(null);
          setSpec({ symbol: "", direction: "", horizon_days: 0, confidence: "medium", thesis: "" });
        }}>
          Publish another
        </button>
      </div>
    );
  }

  return (
    <div className="pb-form">
      <SymbolPicker value={spec.symbol} onPick={(sym) => setSpec((s) => ({ ...s, symbol: sym }))} />

      {/* No default. Both of these define the call and neither can be corrected afterwards, so
          they are tapped rather than accepted. Two taps bought back for the one irreversible
          thing on this screen. */}
      <div className="pb-field">
        <span>which way</span>
        <div className="pb-seg pb-seg-lg">
          {["up", "down"].map((d) => (
            <button key={d} className={spec.direction === d ? "on" : ""}
                    onClick={() => setSpec((s) => ({ ...s, direction: d }))}>{d}</button>
          ))}
        </div>
      </div>

      <div className="pb-field">
        <span>over how long</span>
        <div className="pb-seg pb-seg-lg pb-seg-3">
          {HORIZONS.map((h) => (
            <button key={h} className={spec.horizon_days === h ? "on" : ""}
                    onClick={() => setSpec((s) => ({ ...s, horizon_days: h }))}>{h} days</button>
          ))}
        </div>
        <small>Three windows and no others, so every record on the board is comparable.</small>
      </div>

      <div className="pb-field">
        <span>how sure</span>
        <div className="pb-seg">
          {CONFIDENCES.map((c) => (
            <button key={c} className={spec.confidence === c ? "on" : ""}
                    onClick={() => setSpec((s) => ({ ...s, confidence: c }))}>{c}</button>
          ))}
        </div>
        <small>Your record compares this against what happened, so a caller who is right more
          often when they said they were sure is visible as one.</small>
      </div>

      <label className="pb-field">
        <span>why — optional</span>
        <textarea className="pb-input" rows={2} value={spec.thesis}
                  onChange={(e) => setSpec((s) => ({ ...s, thesis: e.target.value }))}
                  placeholder="one line, in your own words" />
        <small className={thesisShort ? "short" : ""}>
          {thesisShort
            ? `${thesis.length} characters. Either leave this empty or write at least ${MIN_THESIS} — a short reason is worse than none.`
            : "Leave it blank if you are in a hurry. If you write one it is sealed with the call."}
        </small>
      </label>

      <Commitment preview={preview} horizon={spec.horizon_days} />

      {problems.length > 0 && (
        <div className="pb-error">
          <b>This call was not published.</b>
          <ul>{problems.map((p) => <li key={p}>{p}</li>)}</ul>
        </div>
      )}

      {/* THE SENTENCE. Nothing between it and the button, on purpose.
          No checkbox: a checkbox converts reading into a tap and teaches people to tap. */}
      <div className="pb-permanent">
        <b>Once you publish, this cannot be undone.</b>
        <span>
          Not by you, and not by us. The ticker, the direction, the window and your reason are
          sealed exactly as they are now, and when the window closes this is scored against{" "}
          {preview?.benchmark || "SPY"} and the result appears on your public record whichever way
          it goes.
        </span>
      </div>

      <button className="act act-on pb-submit" disabled={busy || !ready} onClick={submit}>
        {busy ? "sealing…" : !spec.symbol ? "Pick a ticker"
          : !spec.direction ? "Choose a direction"
            : !spec.horizon_days ? "Choose a window"
              : `Seal and publish ${spec.symbol} ${spec.direction}`}
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

      {/* The form first. Verification is a task about IDENTITY and it used to sit above the
          form, so a caller whose whole intent was "publish a call" met an identity chore first.
          It is still on this page, below, because it is the cheapest credibility a caller can
          earn -- just not before the thing they came to do. */}
      <Form caller={state.caller} onPublished={load} onOpenCall={onOpenCall} />
      <Verify caller={state.caller} onChanged={load} />
      {/* From the server, never typed here: one sentence, one source, no copy to drift. */}
      <Disclaimer text={state.disclaimer} />
    </div>
  );
}
