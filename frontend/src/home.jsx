// "Smart Money Today" — the consumer home feed. Big score, plain-language story, the real
// people and funds behind it (named straight from the filings), and honest freshness +
// backtested framing on every card. Nothing here promises returns; it shows who is converging.
import { useEffect, useState } from "react";
import { addFollow, addWatchlist, fetchHome, fetchLeaderboards, shadowSymbol } from "./api";
import { Backtested, Freshness } from "./components.jsx";

const BAND = { high: "band-high", medium: "band-med", low: "band-low" };

function ScoreMedallion({ score, bucket }) {
  return (
    <div className={`medallion ${BAND[bucket] || "band-low"}`}>
      <div className="med-score num">{score}</div>
      <div className="med-label">SCORE</div>
    </div>
  );
}

function Avatar({ name }) {
  const initials = (name || "?").split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join("").toUpperCase();
  let h = 0;
  for (let i = 0; i < (name || "").length; i++) h = (h * 31 + name.charCodeAt(i)) % 360;
  return <span className="avatar" style={{ background: `hsl(${h} 45% 28%)`, borderColor: `hsl(${h} 45% 42%)` }}>{initials}</span>;
}

function Protagonists({ people, onOpenProfile }) {
  if (!people || people.length === 0) return null;
  return (
    <div className="protags">
      {people.map((p, i) => (
        <button key={i} className="protag" title={`${p.role} — open profile`}
                onClick={(e) => { e.stopPropagation(); onOpenProfile(p.kind === "insider" ? "insider" : "institution", p.id); }}>
          <Avatar name={p.name} />
          <span className="protag-name">{p.name}</span>
          <span className="protag-role">{p.role}</span>
        </button>
      ))}
    </div>
  );
}

function ScoreCard({ c, calibration, horizon, user, onLogin, onOpenSymbol, onOpenDetail, onOpenProfile }) {
  const [followed, setFollowed] = useState(false);
  const [shadowed, setShadowed] = useState(false);
  const [shared, setShared] = useState(false);
  const cal = calibration?.per_bucket?.[c.confidence_bucket]?.[String(horizon)];
  const open = () => (c.symbol ? onOpenSymbol(c.symbol) : onOpenDetail(c.issuer_entity));
  const follow = async (e) => {
    e.stopPropagation();
    if (!c.symbol) return;
    if (user) await addFollow("symbol", c.symbol, c.name);   // real follow → drives alerts
    else await addWatchlist(c.symbol);                        // logged-out: keep a local watch
    setFollowed(true);
  };
  const share = async (e) => {
    e.stopPropagation();
    const url = `${location.origin}/s/${encodeURIComponent(c.symbol || "")}`;
    try { await navigator.clipboard.writeText(url); } catch { /* clipboard may be blocked */ }
    setShared(true); setTimeout(() => setShared(false), 1600);
  };
  const shadow = async (e) => {
    e.stopPropagation();
    if (!user) return onLogin && onLogin();
    if (!c.symbol) return;
    const r = await shadowSymbol(c.symbol);
    if (!r.error) setShadowed(true);
  };
  return (
    <div className="card" onClick={open}>
      <ScoreMedallion score={c.smart_money_score} bucket={c.confidence_bucket} />
      <div className="card-body">
        <div className="card-head">
          <span className="card-sym">{c.symbol || "—"}</span>
          <span className="card-name">{c.name}</span>
          <span className={`pill pill-${c.confidence_bucket}`}>{c.confidence_bucket}</span>
        </div>
        <div className="card-story">{c.headline || "converging smart-money activity"}</div>
        <Protagonists people={c.story?.protagonists} onOpenProfile={onOpenProfile} />
        <div className="card-foot">
          <Backtested cal={cal} />
          <Freshness iso={c.freshest_contributing_knowable} />
          <span className="spacer" />
          <button className={`act ${followed ? "act-on" : ""}`} onClick={follow} disabled={!c.symbol}>
            {followed ? "following ✓" : "+ follow"}
          </button>
          <button className={`act ${shadowed ? "act-on" : ""}`} onClick={shadow} disabled={!c.symbol}>
            {shadowed ? "shadowing ✓" : "shadow"}
          </button>
          <button className="act" onClick={share}>{shared ? "link copied ✓" : "share"}</button>
        </div>
      </div>
    </div>
  );
}

function Board({ title, children }) {
  return <div className="board"><div className="board-title">{title}</div>{children}</div>;
}

function Leaderboards({ data, onOpenSymbol, onOpenProfile }) {
  if (!data) return null;
  return (
    <div className="boards">
      <Board title="🔥 Most bought this month">
        {data.most_bought.length === 0 ? <div className="name">—</div> : data.most_bought.map((m, i) => (
          <button key={i} className="board-row" onClick={() => m.symbol && onOpenSymbol(m.symbol)}>
            <span className="board-rank">{i + 1}</span>
            <span className="board-sym">{m.symbol || m.name.slice(0, 14)}</span>
            <span className="board-val">{m.buyers} insiders</span>
          </button>
        ))}
      </Board>
      <Board title="⚔️ New activist stakes">
        {data.new_activist_stakes.length === 0 ? <div className="name">—</div> : data.new_activist_stakes.slice(0, 8).map((a, i) => (
          <button key={i} className="board-row" onClick={() => onOpenProfile("institution", a.filer_entity)}>
            <span className="board-sym">{a.symbol || a.issuer.slice(0, 10)}</span>
            <span className="board-actor">{a.filer}</span>
          </button>
        ))}
      </Board>
      <Board title="📈 Top convergence now">
        {data.top_convergence.length === 0 ? <div className="name">—</div> : data.top_convergence.slice(0, 8).map((t, i) => (
          <button key={i} className="board-row" onClick={() => t.symbol && onOpenSymbol(t.symbol)}>
            <span className="board-rank">{i + 1}</span>
            <span className="board-sym">{t.symbol || t.name.slice(0, 14)}</span>
            <span className={`board-score band-${t.confidence_bucket}`}>{t.smart_money_score}</span>
          </button>
        ))}
      </Board>
    </div>
  );
}

export function Home({ calibration, horizon, minC, user, onLogin, onOpenSymbol, onOpenDetail, onOpenProfile }) {
  const [data, setData] = useState(null);
  const [boards, setBoards] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    setData(null);
    fetchHome(minC).then(setData).catch((e) => setErr(String(e)));
    fetchLeaderboards().then(setBoards).catch(() => {});
  }, [minC]);

  if (err) return <div className="err">error: {err}</div>;
  return (
    <div className="home">
      <div className="feed-col">
        <div className="feed-head">
          <h2>Smart Money Today</h2>
          {data && (
            <span className="feed-sub">
              {data.delayed_hours > 0
                ? <span className="fresh a">{data.delayed_hours}h delayed · {data.tier}</span>
                : <span className="fresh g">live · {data.tier}</span>}
              {data.as_of ? ` · as of ${data.as_of.slice(0, 10)}` : ""}
            </span>
          )}
        </div>
        {data === null ? (
          [...Array(4)].map((_, i) => <div key={i} className="card card-skel"><div className="skel" style={{ width: `${60 - i * 6}%` }} /></div>)
        ) : data.feed.length === 0 ? (
          <div className="empty">No convergences at this threshold right now. Smart money isn’t clustering on a name today — that’s an honest signal too.</div>
        ) : (
          data.feed.map((c) => (
            <ScoreCard key={c.issuer_entity} c={c} calibration={calibration} horizon={horizon} user={user} onLogin={onLogin}
                       onOpenSymbol={onOpenSymbol} onOpenDetail={onOpenDetail} onOpenProfile={onOpenProfile} />
          ))
        )}
      </div>
      <div className="rail">
        <Leaderboards data={boards} onOpenSymbol={onOpenSymbol} onOpenProfile={onOpenProfile} />
      </div>
    </div>
  );
}
