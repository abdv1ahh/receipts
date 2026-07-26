// Community — public trades, follows, reactions, comments, and a track-record leaderboard.
//
// The backend for this (community.py, Slice F) has been complete and tested the whole time; what it
// lost was its surface, when the discovery hub that linked to it was deleted as dead code. This is
// that surface, rebuilt deliberately rather than restored — the old one was a row of chips inside a
// page about something else.
//
// Two honesty rules carry over from the rest of the product and are the reason this reads the way
// it does. The leaderboard ranks by WIN RATE over a trader's public closed trades and never by a
// return figure, because a return figure rewards position size and luck; and a trader below the
// sample floor is not ranked at all rather than ranked on four trades. Both are stated on the
// surface, not buried in a tooltip.
import { useCallback, useEffect, useState } from "react";
import {
  addComment, deleteComment, fetchComments, fetchCommunityFeed, fetchProfile,
  fetchTraderLeaderboard, followUser, reactTrade, setProfile, unfollowUser, unreactTrade,
} from "./api";
import { ago, cls, money, pct } from "./format.js";
import { Icon } from "./icons.jsx";
import { EmptyState, LoadError } from "./shell.jsx";


/** Writes are gated behind a login and behind the community_writes admin flag. Rather than hiding
 *  the controls, they stay visible and say why they did not work — a disabled button with no
 *  explanation is the failure this product is built to avoid. */
function useWriteGuard(user) {
  const [notice, setNotice] = useState(null);
  const guard = useCallback(async (fn) => {
    if (!user) { setNotice("Log in to join the conversation."); return null; }
    const res = await fn();
    if (res?.error) { setNotice(res.error); return null; }
    setNotice(null);
    return res;
  }, [user]);
  return { notice, guard };
}

function Comments({ tradeId, user, guard, onCountChange }) {
  const [data, setData] = useState(null);
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState(false);
  const load = useCallback(() => {
    fetchComments(tradeId).then(setData).catch(() => setData({ found: false, comments: [] }));
  }, [tradeId]);
  useEffect(load, [load]);

  const submit = async () => {
    if (!body.trim() || busy) return;
    setBusy(true);
    const res = await guard(() => addComment(tradeId, body.trim()));
    setBusy(false);
    if (res) { setBody(""); load(); onCountChange?.(+1); }
  };
  const remove = async (cid) => {
    const res = await guard(() => deleteComment(cid));
    if (res) { load(); onCountChange?.(-1); }
  };

  if (!data) return <div className="cm-list"><span className="name">loading…</span></div>;
  return (
    <div className="cm-list">
      {data.comments.length === 0 && <div className="cm-empty">No replies yet.</div>}
      {data.comments.map((c) => (
        <div key={c.id} className="cm-row">
          <b className="cm-author">@{c.author}</b>
          <span className="cm-body">{c.body}</span>
          <span className="cm-when">{ago(c.created_at)}</span>
          {c.mine && <button className="linkish" onClick={() => remove(c.id)}>delete</button>}
        </div>
      ))}
      <div className="cm-compose">
        <input className="search" placeholder={user ? "Add a reply…" : "Log in to reply"}
               value={body} maxLength={1000} onChange={(e) => setBody(e.target.value)}
               onKeyDown={(e) => { if (e.key === "Enter") submit(); }} />
        <button className="act act-on" disabled={busy || !body.trim()} onClick={submit}>reply</button>
      </div>
    </div>
  );
}

function FeedCard({ t, user, guard, onOpenTrader }) {
  const [likes, setLikes] = useState(t.likes);
  const [liked, setLiked] = useState(false);
  const [comments, setComments] = useState(t.comments);
  const [open, setOpen] = useState(false);

  const toggleLike = async () => {
    const res = await guard(() => (liked ? unreactTrade(t.id, "like") : reactTrade(t.id, "like")));
    if (res) { setLiked(!liked); setLikes((n) => n + (liked ? -1 : 1)); }
  };

  return (
    <div className="cfeed-card">
      <div className="cfeed-top">
        <button className="cfeed-author" onClick={() => onOpenTrader(t.author)}>@{t.author}</button>
        <span className="cfeed-when">{ago(t.created_at)}</span>
      </div>
      <div className="cfeed-trade">
        <span className="tcard-sym">{t.symbol || "idea"}</span>
        <span className={`chip chip-${t.direction}`}>{t.direction}</span>
        <span className={`chip s-${t.status}`}>{t.status}</span>
        {t.strategy && <span className="cfeed-strat">{t.strategy}</span>}
      </div>
      <div className="cfeed-stats">
        <span>entry <b>{money(t.entry_price)}</b></span>
        <span>R:R <b>{t.reward_risk != null ? `${t.reward_risk}:1` : "—"}</b></span>
        {t.status === "closed" && <span>P&amp;L <b className={cls(t.realized_pnl_pct)}>{pct(t.realized_pnl_pct)}</b></span>}
      </div>
      <div className="cfeed-actions">
        <button className={`cfeed-act ${liked ? "on" : ""}`} onClick={toggleLike}>
          <Icon name="star" size={14} /> {likes}
        </button>
        <button className="cfeed-act" onClick={() => setOpen((o) => !o)}>
          <Icon name="users" size={14} /> {comments}
        </button>
      </div>
      {open && <Comments tradeId={t.id} user={user} guard={guard}
                         onCountChange={(d) => setComments((n) => Math.max(0, n + d))} />}
    </div>
  );
}

function Leaderboard() {
  const [data, setData] = useState(null);
  const [failed, setFailed] = useState(false);
  const load = () => { setFailed(false); fetchTraderLeaderboard().then(setData).catch(() => setFailed(true)); };
  useEffect(load, []);
  if (failed) return <LoadError what="the leaderboard" onRetry={load} />;
  if (!data) return <div className="skel" style={{ width: "60%" }} />;
  if (!data.leaderboard.length) {
    return (
      <EmptyState title="Nobody qualifies yet">
        Traders appear here once they have <b>{data.min_closed} closed public trades</b>. Ranking
        someone on a handful of trades would say more about luck than about them, so the table stays
        empty until the sample is real.
      </EmptyState>
    );
  }
  return (
    <>
      <div className="cm-note">
        Ranked by <b>win rate over public closed trades</b>, then by sample size — never by a return
        figure, which rewards position size as much as judgement. Minimum {data.min_closed} closed
        trades to appear.
      </div>
      <table className="clusters" style={{ marginTop: 10 }}>
        <thead><tr><th>#</th><th>trader</th><th>win rate</th><th>closed</th><th>avg R:R</th></tr></thead>
        <tbody>
          {data.leaderboard.map((r, i) => (
            <tr key={r.handle}>
              <td className="num">{i + 1}</td>
              <td>@{r.handle}</td>
              <td className="num">{r.win_rate != null ? `${r.win_rate}%` : "—"}</td>
              <td className="num">{r.n_closed}</td>
              <td className="num">{r.avg_reward_risk != null ? `${r.avg_reward_risk}:1` : "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

function ProfileEditor({ user, onSaved }) {
  const [handle, setHandle] = useState("");
  const [bio, setBio] = useState("");
  const [msg, setMsg] = useState(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    if (!user?.handle) { setLoaded(true); return; }
    fetchProfile(user.handle)
      .then((p) => { if (p.found) { setHandle(p.handle || ""); setBio(p.bio || ""); } })
      .catch(() => {})
      .finally(() => setLoaded(true));
  }, [user]);

  if (!user) return <EmptyState title="Log in to claim a handle">A handle is what other traders see instead of your email address. Your email is never shown here.</EmptyState>;
  if (!loaded) return <div className="skel" style={{ width: "40%" }} />;

  const save = async () => {
    const res = await setProfile(handle, bio);
    setMsg(res.error || "Saved.");
    if (!res.error) onSaved?.();
  };
  return (
    <div className="cm-profile">
      <div className="cm-note">
        Your handle is public. Only trades you explicitly mark public ever appear in the feed — the
        journal stays private by default, and nothing you log is shared unless you say so.
      </div>
      <label className="cm-field">
        <span>handle</span>
        <input className="search" value={handle} maxLength={30} placeholder="e.g. rangetrader"
               onChange={(e) => setHandle(e.target.value)} />
      </label>
      <label className="cm-field">
        <span>bio</span>
        <input className="search" value={bio} maxLength={280} placeholder="One line about how you trade"
               onChange={(e) => setBio(e.target.value)} />
      </label>
      <div className="cm-compose">
        <button className="act act-on" onClick={save}>save profile</button>
        {msg && <span className="cm-msg">{msg}</span>}
      </div>
    </div>
  );
}

/** A trader's public page: their record, and the trades behind it. Addressable by handle so it can
 *  be linked to, because a track record nobody can point at is not a track record. */
export function TraderView({ handle, user, onBack }) {
  const [p, setP] = useState(null);
  const [failed, setFailed] = useState(false);
  const load = useCallback(() => {
    setFailed(false); setP(null);
    fetchProfile(handle).then(setP).catch(() => setFailed(true));
  }, [handle]);
  useEffect(load, [load]);
  const { notice, guard } = useWriteGuard(user);

  if (failed) return <LoadError what={`@${handle}`} onRetry={load} />;
  if (!p) return <div className="detail"><div className="skel" style={{ width: "50%" }} /></div>;
  if (!p.found) {
    return (
      <div className="detail">
        <button className="back" onClick={onBack}>← back</button>
        <EmptyState title={`No trader called @${handle}`}>That handle has not been claimed.</EmptyState>
      </div>
    );
  }

  const toggleFollow = async () => {
    const res = await guard(() => (p.is_following ? unfollowUser(p.handle) : followUser(p.handle)));
    if (res) load();
  };
  const perf = p.performance || {};
  return (
    <div className="detail">
      <button className="back" onClick={onBack}>← back</button>
      <div className="cm-phead">
        <div>
          <h2 style={{ margin: 0 }}>@{p.handle}</h2>
          {p.bio && <div className="page-sub">{p.bio}</div>}
          <div className="meta">joined {p.joined} · {p.followers} follower{p.followers === 1 ? "" : "s"} · {p.following} following</div>
        </div>
        {!p.is_me && (
          <button className={`act ${p.is_following ? "" : "act-on"}`} onClick={toggleFollow}>
            {p.is_following ? "unfollow" : "follow"}
          </button>
        )}
      </div>
      {notice && <div className="warn">{notice}</div>}

      <div className="cm-note" style={{ marginTop: 12 }}>
        {perf.sufficient
          ? <>Win rate over <b>{perf.n_closed} closed public trades</b>. Descriptive history, not a prediction — and not every trade they took, only the ones they chose to publish.</>
          : <>Not enough public closed trades to state a win rate ({perf.n_closed || 0} logged; {p.public_trades} public in total). A rate from a small sample would be noise, so none is shown.</>}
      </div>
      {perf.sufficient && (
        <div className="cm-stats">
          <div className="stat"><div className="stat-v">{perf.win_rate}%</div><div className="stat-l">win rate</div></div>
          <div className="stat"><div className="stat-v">{perf.n_closed}</div><div className="stat-l">closed</div></div>
          <div className="stat"><div className="stat-v">{perf.avg_reward_risk != null ? `${perf.avg_reward_risk}:1` : "—"}</div><div className="stat-l">avg R:R</div></div>
        </div>
      )}

      <h3 style={{ marginTop: 20 }}>Public trades</h3>
      {(p.trades || []).length === 0
        ? <EmptyState title="No public trades">This trader has not published any trades yet.</EmptyState>
        : (
          <table className="clusters" style={{ marginTop: 8 }}>
            <thead><tr><th>symbol</th><th>side</th><th>status</th><th>entry</th><th>R:R</th><th>P&amp;L</th></tr></thead>
            <tbody>
              {p.trades.map((t) => (
                <tr key={t.id}>
                  <td>{t.symbol || "idea"}</td>
                  <td><span className={`chip chip-${t.direction}`}>{t.direction}</span></td>
                  <td>{t.status}</td>
                  <td className="num">{money(t.entry_price)}</td>
                  <td className="num">{t.reward_risk != null ? `${t.reward_risk}:1` : "—"}</td>
                  <td className={`num ${cls(t.realized_pnl_pct)}`}>{t.status === "closed" ? pct(t.realized_pnl_pct) : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
    </div>
  );
}

const TABS = [
  { k: "public", label: "Feed" },
  { k: "following", label: "Following" },
  { k: "leaderboard", label: "Track records" },
  { k: "profile", label: "Your profile" },
];

export function CommunityView({ user, onOpenTrader }) {
  const [tab, setTab] = useState("public");
  const [feed, setFeed] = useState(null);
  const [failed, setFailed] = useState(false);
  const { notice, guard } = useWriteGuard(user);

  const load = useCallback(() => {
    if (tab !== "public" && tab !== "following") return;
    setFeed(null); setFailed(false);
    fetchCommunityFeed(tab).then((d) => setFeed(d.feed || [])).catch(() => setFailed(true));
  }, [tab]);
  useEffect(load, [load]);

  return (
    <div>
      <div className="page-head">
        <div>
          <h1 className="page-title">Community</h1>
          <div className="page-sub">
            Trades other people chose to make public, and the records behind them. Ranked by win
            rate, never by returns.
          </div>
        </div>
      </div>

      <div className="j-tabs" style={{ marginTop: 14 }}>
        {TABS.map((t) => (
          <button key={t.k} className={`j-tab ${tab === t.k ? "on" : ""}`} onClick={() => setTab(t.k)}>{t.label}</button>
        ))}
      </div>

      {notice && <div className="warn" style={{ marginTop: 12 }}>{notice}</div>}

      {tab === "leaderboard" && <Leaderboard />}
      {tab === "profile" && <ProfileEditor user={user} onSaved={load} />}

      {(tab === "public" || tab === "following") && (
        failed ? <LoadError what="the community feed" onRetry={load} />
        : !feed ? <div className="skel" style={{ width: "70%", marginTop: 14 }} />
        : feed.length === 0 ? (
          <EmptyState title={tab === "following" ? "Nothing from the people you follow" : "No public trades yet"}>
            {tab === "following"
              ? <>Follow a trader from the feed or from their profile and their public trades appear here. Following nobody yet shows nothing rather than quietly falling back to everyone.</>
              : <>When someone marks a journal trade public it appears here with its entry, reward-to-risk and outcome. Nothing is published from your journal unless you mark it yourself.</>}
          </EmptyState>
        ) : (
          <div className="cfeed">
            {feed.map((t) => (
              <FeedCard key={t.id} t={t} user={user} guard={guard} onOpenTrader={onOpenTrader} />
            ))}
          </div>
        )
      )}
    </div>
  );
}
