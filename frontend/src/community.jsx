// Slice F: Community & social. A feed of PUBLIC trades, follows between traders, likes/saves,
// comments, and an honest trader leaderboard (ranked by win rate above a real sample floor — never a
// raw-return number that would invite pumping). UGC is React-escaped; report -> auto-hide moderates it.
import { useEffect, useState } from "react";
import {
  addComment, deleteComment, fetchComments, fetchCommunityFeed, fetchProfile, fetchTraderLeaderboard,
  followUser, getTrade, reactTrade, reportContent, setProfile, unfollowUser, unreactTrade,
} from "./api";
import { AnalysisPanel } from "./journal.jsx";

const pct = (v) => (v == null ? "—" : `${v >= 0 ? "+" : ""}${(v * 100).toFixed(1)}%`);
const cls = (v) => (v == null ? "" : v > 0 ? "pos-pos" : v < 0 ? "pos-neg" : "");
const money = (v) => (v == null ? "—" : `$${(+v).toLocaleString(undefined, { maximumFractionDigits: 2 })}`);

function FeedCard({ t, onOpen, onOpenProfile }) {
  const named = t.author && t.author !== "trader";
  return (
    <div className="trade-card" onClick={() => onOpen(t.id)} role="button">
      <div className="tc-top">
        <span className="tc-sym">{t.symbol || "idea"}</span>
        <span className={`chip chip-${t.direction}`}>{t.direction}</span>
        <span className={`chip s-${t.status}`}>{t.status}</span>
        <span className="tc-flags">{t.has_image ? "📎" : ""}</span>
      </div>
      <div className="name tc-strat">
        by <span className={named ? "linkish" : ""} onClick={(e) => { if (named) { e.stopPropagation(); onOpenProfile(t.author); } }}>@{t.author}</span>
        {t.strategy ? ` · ${t.strategy}` : ""}
      </div>
      <div className="tc-stats">
        <span>entry <b>{money(t.entry_price)}</b></span>
        {t.status === "closed"
          ? <span>P&amp;L <b className={cls(t.realized_pnl_pct)}>{pct(t.realized_pnl_pct)}</b></span>
          : <span>R:R <b>{t.reward_risk != null ? `${t.reward_risk}:1` : "—"}</b></span>}
        <span>♥ {t.likes}</span><span>💬 {t.comments}</span>
      </div>
    </div>
  );
}

function Comments({ tradeId, user, onLogin }) {
  const [data, setData] = useState(null);
  const [body, setBody] = useState("");
  const load = () => fetchComments(tradeId).then(setData).catch(() => {});
  useEffect(() => { load(); }, [tradeId]);
  const submit = async () => {
    if (!body.trim()) return;
    const r = await addComment(tradeId, body.trim());
    if (r.error) { alert(r.error); return; }
    setBody(""); load();
  };
  const del = async (cid) => { await deleteComment(cid); load(); };
  const report = async (cid) => { const why = prompt("Report this comment — reason (optional):"); if (why !== null) { await reportContent("comment", cid, why); alert("Thanks — reported."); } };
  if (!data) return <div className="skel" style={{ width: "50%", marginTop: 10 }} />;
  return (
    <div className="comments">
      <div className="an-title" style={{ marginTop: 14 }}>Discussion ({data.comments.length})</div>
      {data.comments.map((c) => (
        <div key={c.id} className="comment">
          <div className="comment-head"><b>@{c.author}</b><span className="name"> · {c.created_at.slice(0, 10)}</span>
            <span className="comment-actions">
              {c.mine && <button className="linkish" onClick={() => del(c.id)}>delete</button>}
              {!c.mine && <button className="linkish" style={{ color: "var(--muted)" }} onClick={() => report(c.id)}>report</button>}
            </span>
          </div>
          <div className="comment-body">{c.body}</div>
        </div>
      ))}
      {user ? (
        <div className="comment-add">
          <input placeholder="Add to the discussion…" value={body} maxLength={1000} onChange={(e) => setBody(e.target.value)} onKeyDown={(e) => e.key === "Enter" && submit()} />
          <button className="act" onClick={submit}>post</button>
        </div>
      ) : <div className="name" style={{ marginTop: 8 }}>· <button className="linkish" onClick={onLogin}>log in</button> to join the discussion</div>}
    </div>
  );
}

function TradeThread({ id, user, onBack, onOpenSymbol, onOpenProfile, onLogin }) {
  const [d, setD] = useState(null);
  const load = () => getTrade(id).then(setD);
  useEffect(() => { load(); }, [id]);
  if (!d) return <div className="skel" style={{ width: "50%" }} />;
  if (!d.found) return <><button className="back" onClick={onBack}>← feed</button><div className="empty" style={{ marginTop: 12 }}>This trade is private or was removed.</div></>;
  const t = d.trade;
  const liked = d.my_reactions?.includes("like");
  const saved = d.my_reactions?.includes("save");
  const toggle = async (kind, on) => { if (!user) return onLogin(); on ? await unreactTrade(id, kind) : await reactTrade(id, kind); load(); };
  const report = async () => { const why = prompt("Report this trade — reason (optional):"); if (why !== null) { await reportContent("trade", id, why); alert("Thanks — reported."); } };
  return (
    <>
      <button className="back" onClick={onBack}>← feed</button>
      <div className="td-head">
        <button className="linkish sym td-sym" onClick={() => t.symbol && onOpenSymbol(t.symbol)}>{t.symbol || "idea"}</button>
        <span className={`chip chip-${t.direction}`}>{t.direction}</span>
        <span className={`chip s-${t.status}`}>{t.status}</span>
        {d.author && d.author !== "trader" && <button className="linkish" onClick={() => onOpenProfile(d.author)}>@{d.author}</button>}
      </div>
      {t.has_image && <img className="td-img" src={`/api/trades/${id}/image`} alt="trade screenshot" />}
      <div className="kv-grid">
        <div className="kv"><span className="kv-l">Entry</span><span className="kv-v">{money(t.entry_price)}</span></div>
        <div className="kv"><span className="kv-l">Exit</span><span className="kv-v">{money(t.exit_price)}</span></div>
        <div className="kv"><span className="kv-l">Reward : Risk</span><span className="kv-v">{t.reward_risk != null ? `${t.reward_risk} : 1` : "—"}</span></div>
        {t.status === "closed" && <div className="kv"><span className="kv-l">Realized P&amp;L</span><span className={`kv-v ${cls(t.realized_pnl_pct)}`}>{pct(t.realized_pnl_pct)}</span></div>}
        {t.strategy && <div className="kv"><span className="kv-l">Strategy</span><span className="kv-v">{t.strategy}</span></div>}
      </div>
      {(t.reason_entry || t.reason_exit) && (
        <div className="reasons">
          {t.reason_entry && <p><b>Why entered:</b> {t.reason_entry}</p>}
          {t.reason_exit && <p><b>Why exited:</b> {t.reason_exit}</p>}
        </div>
      )}
      <div className="social-bar">
        <button className={`act ${liked ? "act-on" : ""}`} onClick={() => toggle("like", liked)}>♥ {d.likes}{liked ? " liked" : " like"}</button>
        <button className={`act ${saved ? "act-on" : ""}`} onClick={() => toggle("save", saved)}>{saved ? "★ saved" : "☆ save"}</button>
        <button className="act" style={{ marginLeft: "auto", color: "var(--muted)" }} onClick={report}>report</button>
      </div>
      <AnalysisPanel id={id} />
      <Comments tradeId={id} user={user} onLogin={onLogin} />
    </>
  );
}

function ProfilePanel({ handle, user, onBack, onOpenTrade, onOpenSymbol, refreshUser }) {
  const [p, setP] = useState(null);
  const load = () => fetchProfile(handle).then(setP);
  useEffect(() => { load(); }, [handle]);
  if (!p) return <div className="skel" style={{ width: "50%" }} />;
  if (!p.found) return <><button className="back" onClick={onBack}>← back</button><div className="empty" style={{ marginTop: 12 }}>No trader with that handle.</div></>;
  const s = p.performance;
  const toggleFollow = async () => { p.is_following ? await unfollowUser(handle) : await followUser(handle); load(); };
  return (
    <>
      <button className="back" onClick={onBack}>← back</button>
      <div className="profile-head">
        <div>
          <h2 style={{ margin: 0 }}>@{p.handle}</h2>
          {p.bio && <div className="meta" style={{ marginTop: 4 }}>{p.bio}</div>}
          <div className="name" style={{ marginTop: 6 }}>{p.followers} followers · {p.following} following · joined {p.joined}</div>
        </div>
        {!p.is_me && user && <button className={`act ${p.is_following ? "" : "act-on"}`} onClick={toggleFollow}>{p.is_following ? "following" : "+ follow"}</button>}
      </div>
      <div className="perf-row" style={{ marginTop: 12 }}>
        <div className="stat"><div className="stat-v">{p.public_trades}</div><div className="stat-l">public trades</div></div>
        {s.sufficient ? (
          <>
            <div className="stat"><div className="stat-v">{Math.round(s.win_rate * 100)}%</div><div className="stat-l">win rate ({s.n_closed})</div></div>
            <div className="stat"><div className="stat-v">{s.avg_reward_risk != null ? `${s.avg_reward_risk}:1` : "—"}</div><div className="stat-l">avg R:R</div></div>
          </>
        ) : <div className="stat" style={{ flex: 2 }}><div className="stat-v" style={{ fontSize: 14 }}>track record builds at {10} closed trades</div><div className="stat-l">honest sample floor</div></div>}
      </div>
      <div className="trade-grid" style={{ marginTop: 14 }}>
        {(p.trades || []).map((t) => <FeedCard key={t.id} t={{ ...t, author: p.handle, likes: t.likes || 0, comments: t.comments || 0 }} onOpen={onOpenTrade} onOpenProfile={() => {}} />)}
      </div>
      {(p.trades || []).length === 0 && <div className="name" style={{ marginTop: 12 }}>No public trades yet.</div>}
    </>
  );
}

function HandleClaim({ user, refreshUser }) {
  const [handle, setHandle] = useState("");
  const [msg, setMsg] = useState("");
  if (!user || user.handle) return null;
  const claim = async () => {
    const r = await setProfile(handle, null);
    if (r.error) { setMsg(r.error); return; }
    setMsg(""); refreshUser?.();
  };
  return (
    <div className="empty" style={{ marginTop: 12 }}>
      Claim a public handle to post trades to the community and appear on the leaderboard.
      <div className="comment-add" style={{ marginTop: 10 }}>
        <input placeholder="your_handle" value={handle} onChange={(e) => setHandle(e.target.value)} />
        <button className="act act-on" onClick={claim}>claim</button>
      </div>
      {msg && <div className="name" style={{ marginTop: 6 }}>{msg}</div>}
    </div>
  );
}

function Leaderboard({ onOpenProfile }) {
  const [d, setD] = useState(null);
  useEffect(() => { fetchTraderLeaderboard().then(setD).catch(() => {}); }, []);
  if (!d) return <div className="skel" style={{ width: "50%", marginTop: 14 }} />;
  if (!d.leaderboard.length) return <div className="empty" style={{ marginTop: 14 }}>No ranked traders yet — the board ranks traders with at least {d.min_closed} closed public trades, by win rate. Honest track records only.</div>;
  return (
    <table className="clusters" style={{ marginTop: 12 }}>
      <thead><tr><th>#</th><th>Trader</th><th>Win rate</th><th>Closed</th><th>Avg R:R</th></tr></thead>
      <tbody>
        {d.leaderboard.map((r, i) => (
          <tr className="row" key={r.handle} onClick={() => onOpenProfile(r.handle)}>
            <td className="board-rank">{i + 1}</td>
            <td><span className="sym">@{r.handle}</span></td>
            <td className="num">{Math.round(r.win_rate * 100)}%</td>
            <td className="num">{r.n_closed}</td>
            <td className="num">{r.avg_reward_risk != null ? `${r.avg_reward_risk}:1` : "—"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function CommunityView({ user, onLogin, onOpenSymbol, refreshUser }) {
  const [tab, setTab] = useState("explore");
  const [scope, setScope] = useState("public");
  const [feed, setFeed] = useState(null);
  const [openTradeId, setOpenTradeId] = useState(null);
  const [openHandle, setOpenHandle] = useState(null);

  useEffect(() => {
    if (tab !== "explore" || openTradeId || openHandle) return;
    setFeed(null);
    fetchCommunityFeed(scope).then((d) => setFeed(d.feed || [])).catch(() => setFeed([]));
  }, [tab, scope, openTradeId, openHandle]);

  if (openTradeId) return <div className="detail"><TradeThread id={openTradeId} user={user} onLogin={onLogin} onBack={() => setOpenTradeId(null)} onOpenSymbol={onOpenSymbol} onOpenProfile={(h) => { setOpenTradeId(null); setOpenHandle(h); }} /></div>;
  if (openHandle) return <div className="detail"><ProfilePanel handle={openHandle} user={user} refreshUser={refreshUser} onOpenSymbol={onOpenSymbol} onOpenTrade={(id) => { setOpenHandle(null); setOpenTradeId(id); }} onBack={() => setOpenHandle(null)} /></div>;

  return (
    <div className="detail">
      <div className="j-head">
        <h2>👥 Community</h2>
        <div className="seg">
          <button className={tab === "explore" ? "on" : ""} onClick={() => setTab("explore")}>explore</button>
          <button className={tab === "leaderboard" ? "on" : ""} onClick={() => setTab("leaderboard")}>leaderboard</button>
        </div>
      </div>
      <div className="meta">Traders sharing real, logged trades — with reasoning, levels, and outcomes. Learn from track records, not hype: the leaderboard ranks by honest win rate over a real sample, and every post keeps its “not advice” framing.</div>
      <HandleClaim user={user} refreshUser={refreshUser} />

      {tab === "explore" ? (
        <>
          <div className="controls" style={{ marginTop: 10 }}>
            <div className="seg">
              <button className={scope === "public" ? "on" : ""} onClick={() => setScope("public")}>all</button>
              <button className={scope === "following" ? "on" : ""} onClick={() => { if (!user) return onLogin(); setScope("following"); }}>following</button>
            </div>
          </div>
          {feed === null ? <div className="skel" style={{ width: "40%", marginTop: 14 }} />
            : feed.length === 0 ? <div className="name" style={{ marginTop: 14 }}>{scope === "following" ? "Follow some traders to see their trades here." : "No public trades yet. Log a trade and publish it to start the feed."}</div>
              : <div className="trade-grid" style={{ marginTop: 12 }}>{feed.map((t) => <FeedCard key={t.id} t={t} onOpen={setOpenTradeId} onOpenProfile={setOpenHandle} />)}</div>}
        </>
      ) : <Leaderboard onOpenProfile={setOpenHandle} />}
      <div className="disc" style={{ marginTop: 16 }}>Shared trades are personal journal entries for education and discussion — not signals, recommendations, or advice. Report anything that looks like coordinated promotion.</div>
    </div>
  );
}
