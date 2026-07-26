// AI Trading Mentor — a grounded, guarded chat over REAL platform data: the smart-money signals, the
// intelligence library, and (signed in) your own trades, watchlist and open positions. It answers only
// from what it can retrieve, never gives advice, and is honest about data it doesn't have yet (live
// social sentiment, intraday price-move reasons) instead of fabricating it. Not a generic chatbot.
import { useEffect, useRef, useState } from "react";
import { askAssistant } from "./api";
import { Icon } from "./icons.jsx";
import { BRAND } from "./brand.js";

const GROUNDING = [
  { icon: "journal", label: "Your journal & performance" },
  { icon: "star", label: "Your watchlist & positions" },
  { icon: "signal", label: "Smart-money signals" },
  { icon: "book", label: "Intelligence library" },
];

const SUGGESTIONS = [
  { q: "What are the strongest smart-money signals right now?", tag: "Signals" },
  { q: "How are my trades doing?", tag: "Your desk" },
  { q: "What's the smart-money signal on NVDA?", tag: "A ticker" },
  { q: "What risks am I missing across my watchlist?", tag: "Your desk" },
  { q: "Explain convergence clusters in simple terms", tag: "Learn" },
  { q: "Find setups that match my strategy", tag: "Your desk" },
];

// Friendly labels for the retrieval sources the answer cites (so grounding is visible, not hidden).
function srcLabel(s) {
  if (s.startsWith("signal:")) return `⚡ ${s.slice(7)} signal`;
  if (s.startsWith("activity:")) return `${s.slice(9)} activity`;
  if (s.startsWith("attention:")) return `${s.slice(10)} attention`;
  if (s.startsWith("library:")) return "📖 library";
  if (s.startsWith("gap:")) return "honest gap";
  return { your_performance: "your performance", your_watchlist: "your watchlist",
           your_positions: "your positions", top_signals: "top signals", trending: "trending" }[s] || s;
}

export function AssistantView({ user, onLogin }) {
  const [msgs, setMsgs] = useState([]);   // {role, text, sources, model, grounded}
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const endRef = useRef(null);
  const inputRef = useRef(null);
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth" }); }, [msgs, busy]);
  useEffect(() => { inputRef.current?.focus(); }, []);

  const send = async (text) => {
    const question = (text ?? q).trim();
    if (!question || busy) return;
    setMsgs((m) => [...m, { role: "user", text: question }]);
    setQ(""); setBusy(true);
    try {
      const r = await askAssistant(question);
      setMsgs((m) => [...m, { role: "ai", text: r.answer, sources: r.sources || [],
                              model: r.used_template ? BRAND : r.model_id, grounded: r.grounded }]);
    } catch {
      setMsgs((m) => [...m, { role: "ai", text: "Something went wrong reaching the mentor. Try again in a moment.", sources: [], model: BRAND }]);
    }
    setBusy(false);
  };

  return (
    <div className="assistant-wrap">
      <div className="page-head">
        <div>
          <h1 className="page-title">AI Trading Mentor</h1>
          <div className="page-sub">Grounded in real platform data — never a generic chatbot. It answers only from what it can verify, and says so when it can't. Never advice.</div>
        </div>
      </div>

      <div className="chat mentor-chat">
        {msgs.length === 0 ? (
          <div className="mentor-intro">
            <div className="mentor-avatar"><Icon name="compass" size={26} /></div>
            <div className="mentor-hi">Ask me anything about the market or your desk.</div>
            <div className="mentor-grounds">
              <span className="mentor-grounds-l">I can see, and cite:</span>
              {GROUNDING.map((g) => <span key={g.label} className="ground-chip"><Icon name={g.icon} size={13} /> {g.label}</span>)}
            </div>
            <div className="mentor-sugs">
              {SUGGESTIONS.map((s) => (
                <button key={s.q} className="sug-card" onClick={() => send(s.q)}>
                  <span className="sug-tag">{s.tag}</span>
                  <span className="sug-q">{s.q}</span>
                </button>
              ))}
            </div>
            {!user && <div className="mentor-note">Sign in and I can also ground answers in your own trades, watchlist and open positions. <button className="linkish" onClick={onLogin}>Log in →</button></div>}
          </div>
        ) : msgs.map((m, i) => (
          <div key={i} className={`bubble ${m.role}`}>
            {m.role === "ai" && <span className="bubble-badge"><Icon name="compass" size={13} /></span>}
            <div className="bubble-text">{m.text}</div>
            {m.role === "ai" && (m.sources?.length > 0 || m.model) && (
              <div className="bubble-foot">
                {m.sources?.map((s) => <span key={s} className="src-chip">{srcLabel(s)}</span>)}
                <span className="spacer" style={{ flex: 1 }} />
                <span className={`ground-dot ${m.grounded ? "on" : ""}`}>{m.grounded ? "grounded in data" : "general"}</span>
                <span className="src-model">· {m.model}</span>
              </div>
            )}
          </div>
        ))}
        {busy && <div className="bubble ai"><span className="bubble-badge"><Icon name="compass" size={13} /></span><div className="bubble-text typing">thinking through the data…</div></div>}
        <div ref={endRef} />
      </div>

      <div className="chat-input">
        <input ref={inputRef} placeholder="Ask about a ticker, a concept, your trades, or the market…" value={q}
               onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === "Enter" && send()} />
        <button className="act act-on" disabled={busy} onClick={() => send()}>Ask</button>
      </div>
      <div className="disc" style={{ marginTop: 12 }}>The mentor describes disclosed smart-money activity, public data, and your own records for education. It is not investment advice and never tells you what to buy, sell, or hold.</div>
    </div>
  );
}
