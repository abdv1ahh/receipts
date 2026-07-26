// First-run setup: the sixty seconds that make relevance work (Phase 8).
//
// The brief calls this out specifically — relevance scoring is worthless without a country, and
// nothing ever asked for one, so almost every profile is empty and every reader has been getting
// the same ordering. It is deliberately three questions on one screen rather than a wizard: a
// stepper for three fields is theatre, and it makes a sixty-second job feel like a form.
//
// "Skippable but gently persistent" is the server's rule, not this component's — `snooze` sets a
// few days and the prompt comes back. There is no permanent dismissal, and there is also no way to
// get stuck: every field is optional, and finishing with nothing chosen is a valid answer that
// still counts as answered.
import { useEffect, useState } from "react";
import { fetchFrameSetup, saveFrameSetup, snoozeFrameSetup } from "./api";
import { Icon } from "./icons.jsx";

export function OnboardingCard({ onDone }) {
  const [d, setD] = useState(null);
  const [country, setCountry] = useState("");
  const [currency, setCurrency] = useState("");
  const [raw, setRaw] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    fetchFrameSetup().then((r) => { if (r?.authenticated && r.due) setD(r); }).catch(() => {});
  }, []);
  if (!d) return null;

  const meta = (d.countries || []).find((c) => c.country === country);
  // Proposed, never assumed silently: a reader in Singapore may well account in USD, and quietly
  // deciding that for them is the sort of small wrong answer that erodes trust in the large ones.
  const proposed = meta?.currency || "";
  const symbols = raw.split(/[\s,]+/).map((s) => s.trim().toUpperCase()).filter(Boolean).slice(0, 12);

  const finish = async () => {
    setBusy(true);
    await saveFrameSetup({ country: country || null, base_currency: currency || proposed || null, symbols })
      .catch(() => {});
    setBusy(false);
    setD(null);
    onDone?.();
  };
  const later = async () => { setBusy(true); await snoozeFrameSetup().catch(() => {}); setD(null); onDone?.(); };

  return (
    <div className="ob">
      <div className="ob-head">
        <span className="ob-badge"><Icon name="compass" size={16} /></span>
        <div>
          <div className="ob-title">Set your frame — about a minute</div>
          <div className="ob-why">{d.why}</div>
        </div>
        <button className="linkish" style={{ marginLeft: "auto" }} onClick={later} disabled={busy}>
          not now
        </button>
      </div>

      <div className="ob-grid">
        <label className="ob-field">
          <span className="ob-l">Where do you read from</span>
          <select value={country} onChange={(e) => { setCountry(e.target.value); setCurrency(""); }}>
            <option value="">Choose a country…</option>
            {(d.countries || []).map((c) => (
              <option key={c.country} value={c.country}>{c.name}</option>
            ))}
          </select>
          <span className="ob-hint">
            {meta
              ? `Benchmark index ${meta.main_index}. Exposure figures from ${meta.source}.`
              : "Ten countries, each with hand-checked trade and currency exposure behind it."}
          </span>
        </label>

        <label className="ob-field">
          <span className="ob-l">What you account in</span>
          <input value={currency || proposed} onChange={(e) => setCurrency(e.target.value.toUpperCase())}
                 placeholder="USD" maxLength={3} />
          <span className="ob-hint">
            {proposed && !currency
              ? `Proposed from your country — change it if you account in something else.`
              : "Three-letter code. A claim about a currency yours is pegged to is not foreign news."}
          </span>
        </label>

        <label className="ob-field ob-wide">
          <span className="ob-l">Anything you already follow</span>
          <input value={raw} onChange={(e) => setRaw(e.target.value)}
                 placeholder="NVDA, PBR, VALE…" />
          <span className="ob-hint">
            {symbols.length > 0
              ? `${symbols.length} symbol${symbols.length === 1 ? "" : "s"}: ${symbols.join(" · ")}`
              : "Optional. Events touching these get pushed up your Radar. You can add more later."}
          </span>
        </label>
      </div>

      <div className="ob-actions">
        <button className="act act-on ob-go" onClick={finish} disabled={busy}>
          {busy ? "saving…" : "Save and continue"}
        </button>
        <span className="ob-note">Nothing here is required, and none of it unlocks anything —
          it only decides what reaches the top of your feed.</span>
      </div>
    </div>
  );
}
