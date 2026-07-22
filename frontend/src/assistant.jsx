// Slice G: AI Market Assistant — grounded, guarded chat over REAL platform data (smart-money
// signals, the intelligence library, your own logged trades). It answers only from what it can
// retrieve, never gives advice, and is honest about data it doesn't have yet (live social sentiment,
// intraday price-move reasons) instead of fabricating it.
import { useEffect, useRef, useState } from "react";
import { askAssistant } from "./api";

const SUGGESTIONS = [
  "What's the smart-money signal on NVDA?",
  "Explain what a convergence cluster means",
  "How are my trades doing?",
  "What are the strongest signals right now?",
];

export function AssistantView({ user }) {
  const [msgs, setMsgs] = useState([]);   // {role:'user'|'ai', text, sources, model}
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const endRef = useRef(null);
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth" }); }, [msgs, busy]);

  const send = async (text) => {
    const question = (text ?? q).trim();
    if (!question || busy) return;
    setMsgs((m) => [...m, { role: "user", text: question }]);
    setQ(""); setBusy(true);
    try {
      const r = await askAssistant(question);
      setMsgs((m) => [...m, { role: "ai", text: r.answer, sources: r.sources || [], model: r.used_template ? "TradeOS" : r.model_id }]);
    } catch {
      setMsgs((m) => [...m, { role: "ai", text: "Something went wrong reaching the assistant. Try again in a moment.", sources: [], model: "TradeOS" }]);
    }
    setBusy(false);
  };

  return (
    <div className="detail assistant-wrap">
      <h2>🧠 AI Market Assistant</h2>
      <div className="meta">Ask about a ticker's smart-money signal, a concept from the library, or your own logged trades. Answers are grounded in real platform data and never give advice. Live social sentiment and price-move reasons aren't connected yet — it will say so rather than guess.</div>

      <div className="chat">
        {msgs.length === 0 && (
          <div className="chat-empty">
            <div className="name" style={{ marginBottom: 8 }}>Try:</div>
            <div className="suggestions">{SUGGESTIONS.map((s) => <button key={s} className="act" onClick={() => send(s)}>{s}</button>)}</div>
          </div>
        )}
        {msgs.map((m, i) => (
          <div key={i} className={`bubble ${m.role}`}>
            <div className="bubble-text">{m.text}</div>
            {m.role === "ai" && (m.sources?.length > 0 || m.model) && (
              <div className="bubble-foot">
                {m.sources?.map((s) => <span key={s} className="src-chip">{s}</span>)}
                <span className="src-model">· {m.model}</span>
              </div>
            )}
          </div>
        ))}
        {busy && <div className="bubble ai"><div className="bubble-text typing">thinking…</div></div>}
        <div ref={endRef} />
      </div>

      <div className="chat-input">
        <input placeholder={user ? "Ask about a ticker, a concept, or your trades…" : "Ask about a ticker or a concept…"} value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === "Enter" && send()} />
        <button className="act act-on" disabled={busy} onClick={() => send()}>ask</button>
      </div>
      <div className="disc" style={{ marginTop: 12 }}>The assistant describes disclosed smart-money activity and your own records for education. It is not investment advice and never tells you what to buy, sell, or hold.</div>
    </div>
  );
}
