// The whole application: four Receipts surfaces and the account screens.
//
// WHAT WAS HERE BEFORE. Twenty-one surfaces across a three-section rail, a ⌘K palette, a ticker
// search field, an "Ask AI" button and an upgrade prompt — a research terminal that Receipts was
// one section of. All of it is gone, with the plane it belonged to. What that buys is not smaller
// code: it is that every door on this rail opens onto something a stranger can use, which was the
// standard the old rail had already failed (see the Radar, The World, Exposure, Library and
// Community, taken off it for exactly that reason and then deleted).
//
// There is no command palette and no search box now. Four destinations do not need a fuzzy finder,
// and a search field with nothing behind it is worse than none.
import { useEffect, useState } from "react";
import { BRAND } from "./brand.js";
import { authLogout, authMe } from "./api";
import { AuthPanel } from "./views.jsx";
import { ResetView, VerifyView } from "./account.jsx";
import { BoardView } from "./board.jsx";
import { RecordView, MyRecord } from "./record.jsx";
import { ClaimView, PublishView } from "./publish.jsx";
import { CallDetailView } from "./calldetail.jsx";
import { ReceiptsMethodologyView } from "./methodology.jsx";
import { ErrorBoundary, useRoute } from "./shell.jsx";
import { Icon } from "./icons.jsx";

const NAV_LABELS = {
  board: "The Board", publish: "Publish a call", record: "My record",
  methodology: "How this works",
};
const NAV_ICONS = { board: "target", publish: "signal", record: "shield", methodology: "book" };

// Which surfaces are reachable by URL. Anything not listed falls back to the Board, so a stale
// bookmark lands somewhere sensible instead of a blank page.
//
// `claim` and `call` are ADDRESSABLE but not on the rail, and that is the same rule the old app
// followed: claiming a handle is a one-time act, so a permanent nav item for it is dead weight for
// everyone who has done it — but it needs a URL, because it is the one thing this product ever
// asks a stranger to do. `verify` and `reset` are reached from an email; without them the link
// falls through to the catch-all and lands on the Board with the token ignored.
//
// THERE IS NO ADMIN SURFACE. `GET /api/admin/callers/pending` and `POST
// /api/admin/callers/{id}/verify` exist, are admin-only and are tested, and nothing in this bundle
// calls them — the caller-verification queue has never had a screen. That is recorded in
// docs/known_gaps.md §2 rather than papered over with a rail item leading to an empty page, which
// is the mistake this rail was rebuilt to stop making. The old admin.jsx was not that queue: it
// was the moderation, users, flags and audit dashboard, and its five routes went with the
// community plane.
const ROUTES = new Set([...Object.keys(NAV_LABELS), "auth", "claim", "call", "verify", "reset"]);

export default function App() {
  const route = useRoute();
  const [user, setUser] = useState(null);
  const [view, setViewState] = useState(() => (ROUTES.has(route.path) ? route.path : "board"));
  const [navOpen, setNavOpen] = useState(false);
  // A record and a call both live at an address, because a record nobody can point at is not much
  // of a record. Both read their parameter from the URL on first load, so a shared link works.
  const [recordHandle, setRecordHandle] = useState(
    () => new URLSearchParams(window.location.search).get("handle") || null);
  const [callId, setCallId] = useState(
    () => new URLSearchParams(window.location.search).get("id") || null);
  const [refCode] = useState(() => new URLSearchParams(window.location.search).get("ref") || "");

  const refreshUser = () => authMe().then((d) => setUser(d.user)).catch(() => {});
  useEffect(() => { refreshUser(); }, []);

  // Browser back/forward: the URL is the source of truth, so a popstate re-selects the surface AND
  // its parameter. Keying only on `route.path` was not enough — a record page linking to another
  // record leaves the path at "record" and moves only the query, so Back changed the URL and left
  // the previous record on screen.
  useEffect(() => {
    if (ROUTES.has(route.path) && route.path !== view) setViewState(route.path);
    setRecordHandle(route.query.get("handle") || null);
    setCallId(route.query.get("id") || null);
  }, [route.path, route.query.toString()]);

  // Surfaces that are addressable but not on the rail have no NAV_LABELS entry, so this used to
  // fall back to the brand and render "Receipts · Receipts" in the tab. Caught on /auth, which is
  // the first screen a stranger who wants to publish ever sees.
  const TITLES = { auth: "Sign in", claim: "Claim a handle", call: "One call",
                   verify: "Confirm your email", reset: "Reset your password" };
  useEffect(() => {
    const name = NAV_LABELS[view] || TITLES[view];
    document.title = name ? `${name} · ${BRAND}` : BRAND;
  }, [view]);

  // One place that changes the surface, so the URL and the rendered view can never disagree.
  const setView = (v, query) => { setViewState(v); route.go(v, query); };
  const go = (v) => { setView(v); setNavOpen(false); };
  const openRecord = (handle) => { setRecordHandle(handle); setView("record", { handle }); };
  const openCall = (id) => { setCallId(String(id)); setView("call", { id }); };
  const onAuthed = (u) => { setUser(u); setView("board"); };
  // Signing out lands on the Board, not on a marketing page: the Board is the product's
  // front door now and it is public, so a signed-out reader sees the thing they came for.
  const doLogout = async () => { await authLogout(); setUser(null); go("board"); };

  // "My record" is the signed-in caller's own. Reading somebody else's record uses the same route
  // with a handle, so highlighting the rail item there would tell the reader they are looking at
  // their own record when they are looking at ours.
  const navBtn = (v) => (
    <button key={v} className={`nav-item ${(view === v && !(v === "record" && recordHandle)) ? "on" : ""}`}
            onClick={() => go(v)}>
      <Icon name={NAV_ICONS[v]} /><span>{NAV_LABELS[v]}</span>
    </button>
  );

  return (
    <div className="shell">
      <aside className={`sidebar ${navOpen ? "open" : ""}`}>
        <div className="brand" onClick={() => go("board")}>
          <span className="brand-mark">&#9670;</span><span className="brand-name">{BRAND}</span>
        </div>
        <nav className="side-nav">
          <div className="nav-section">{Object.keys(NAV_LABELS).map(navBtn)}</div>
        </nav>
        <div className="side-foot">
          <div className="side-ver">A public record of market calls</div>
        </div>
      </aside>

      <div className="main">
        <header className="topbar">
          <button className="icon-btn menu-btn" onClick={() => setNavOpen((o) => !o)} title="menu">
            <Icon name="menu" />
          </button>
          <div className="topbar-right">
            {user ? (
              <>
                <div className="account">
                  <span className="account-av">{user.email[0].toUpperCase()}</span>
                  <span className="account-meta"><b>{user.email.split("@")[0]}</b></span>
                </div>
                <button className="icon-btn" onClick={doLogout} title="log out"><Icon name="logout" /></button>
              </>
            ) : (
              <button className="act act-on" onClick={() => go("auth")}>Log in</button>
            )}
          </div>
        </header>

        {/* One boundary per surface, keyed by view: a throw inside a surface shows a contained
            failure panel with the chrome intact, and switching surfaces resets it. */}
        <main className="content">
          <ErrorBoundary key={view} surface={view}>
          {view === "verify" ? (
            <VerifyView onDone={go} />
          ) : view === "reset" ? (
            <ResetView onDone={go} />
          ) : view === "auth" ? (
            <AuthPanel onAuthed={onAuthed}
                       onBack={() => go("board")}
                       initialInvite={refCode} />
          ) : view === "record" ? (
            // "My record" with no handle resolves to the signed-in caller's own; PublishView is
            // the surface that knows how to claim one, so it handles the not-yet-a-caller case.
            recordHandle ? (
              <RecordView handle={recordHandle} onOpenCall={openCall} onNav={go} />
            ) : (
              <MyRecord user={user} onLogin={() => go("auth")} onOpenRecord={openRecord} onNav={go} />
            )
          ) : view === "publish" ? (
            <PublishView user={user} onLogin={() => go("auth")} onOpenCall={openCall}
                         onOpenRecord={openRecord} />
          ) : view === "claim" ? (
            <ClaimView user={user} onLogin={() => go("auth")} onOpenRecord={openRecord} onNav={go} />
          ) : view === "call" ? (
            <CallDetailView callId={callId} onBack={() => window.history.back()}
                            onOpenRecord={openRecord} />
          ) : view === "methodology" ? (
            <ReceiptsMethodologyView />
          ) : (
            <BoardView onOpenRecord={openRecord} onNav={go} />
          )}
          </ErrorBoundary>
        </main>
      </div>

      {navOpen && <div className="scrim" onClick={() => setNavOpen(false)} />}
    </div>
  );
}
