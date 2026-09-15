import { useEffect, useState } from "react";
import { BRAND } from "./brand.js";
import { authLogout, authMe, fetchCalibration, fetchClusters, fetchClusterDetail, fetchDefinitions, fetchExplanation, fetchFeeds, fetchNotifications } from "./api";
import { Methodology } from "./components.jsx";
import { AssetView, AuthPanel, LibraryEntry, LibraryView, ProfileView, Screener, WatchlistView } from "./views.jsx";
import { SmartMoneyView, IssuerDetail } from "./smartmoney.jsx";
import { JournalView } from "./journal.jsx";
import { AssistantView } from "./assistant.jsx";
import { SocialView } from "./social.jsx";
import { CommunityView, TraderView } from "./community.jsx";
import { AlertsView, NotificationsView } from "./alerts.jsx";
import { BriefView } from "./brief.jsx";
import { NewsView } from "./news.jsx";
import { EventsView } from "./events.jsx";
import { PortfoliosView } from "./portfolios.jsx";
import { PricingView } from "./pricing.jsx";
import { CryptoView } from "./crypto.jsx";
import { SearchView } from "./discover.jsx";
import { AdminView } from "./admin.jsx";
import { Dashboard } from "./dashboard.jsx";
import { IntegrationsView } from "./integrations.jsx";
import { RadarView } from "./radar.jsx";
import { OnboardingCard } from "./onboarding.jsx";

// Surfaces the first-run Radar setup must not cover. `auth` because a signup screen with a
// configuration card on it is absurd; the Receipts surfaces because the card is about a different
// product and it was taking their entire first screen on a phone.
const ONBOARDING_SUPPRESSED = new Set(["auth", "publish", "record", "board", "call", "methodology"]);
import { ResetView, VerifyView } from "./account.jsx";
import { GlobeView } from "./globe.jsx";
import { ExposureView } from "./exposure.jsx";
import { CalendarView } from "./calendar.jsx";
import { LedgerView } from "./ledger.jsx";
import { BoardView } from "./board.jsx";
import { RecordView, MyRecord } from "./record.jsx";
import { PublishView } from "./publish.jsx";
import { CallDetailView } from "./calldetail.jsx";
import { ReceiptsMethodologyView } from "./methodology.jsx";
import { ErrorBoundary, useRoute } from "./shell.jsx";
import { Icon } from "./icons.jsx";

// Receipts is the product; everything else is supporting research. The rail says so.
//
// Radar, The World, Exposure, Library and Community are deliberately absent. Their code is still
// here and still imported, and they can come back the day they have something to show — but they
// are empty or thin right now, and a rail that leads a reader to an empty page has spent the one
// thing this product is selling. See docs/state.md for what each of them is waiting on.
const NAV_LABELS = {
  // RECEIPTS
  board: "The Board", publish: "Publish a call", record: "My record", methodology: "Methodology",
  // RESEARCH
  home: "Smart Money", ledger: "Ledger", events: "Calendar", crypto: "Crypto", news: "News",
  journal: "Journal", watchlist: "Watchlist", "signal-methodology": "Signal methodology",
  // SYSTEM
  integrations: "Integrations", assistant: "AI Assistant", search: "Search",
  // Reachable, but not on the rail. Everything here has a real surface behind it; they are in
  // ROUTES and in the command palette so no door is bricked up.
  dashboard: "Dashboard", brief: "Morning Brief", trending: "Social", alerts: "Alerts",
  screener: "Screener", portfolios: "Shadow portfolios",
};
const NAV_ICONS = {
  board: "target", publish: "signal", record: "shield", methodology: "book",
  home: "signal", ledger: "activity", events: "calendar", crypto: "crypto", news: "news",
  journal: "journal", watchlist: "star", "signal-methodology": "book",
  integrations: "plug", assistant: "compass", search: "search",
  dashboard: "grid", brief: "sparkles", trending: "trending", alerts: "bell",
  screener: "filter", portfolios: "briefcase",
};
const SIDEBAR = [
  { label: "Receipts", items: ["board", "publish", "record", "methodology"] },
  { label: "Research", items: ["home", "ledger", "events", "crypto", "news", "journal", "watchlist"] },
  { label: "System", items: ["integrations", "assistant", "search"] },
];
const MORE = ["dashboard", "brief", "trending", "alerts", "screener", "portfolios", "signal-methodology"];
// Everything reachable from the ⌘K command palette. Every route with a nav label appears here, so
// a surface that is off the rail is still one keystroke away rather than lost.
const CMD_ITEMS = [
  ...Object.keys(NAV_LABELS).map((v) => ({ v, label: NAV_LABELS[v], icon: NAV_ICONS[v], group: "Go to" })),
  { v: "pricing", label: "Upgrade plan", icon: "sparkles", group: "Actions" },
  { v: "notifications", label: "Notifications", icon: "bell", group: "Actions" },
];

function CommandPalette({ onGo, onClose }) {
  const [q, setQ] = useState("");
  const [sel, setSel] = useState(0);
  const items = CMD_ITEMS.filter((it) => it.label.toLowerCase().includes(q.trim().toLowerCase()));
  useEffect(() => { setSel(0); }, [q]);
  const choose = (it) => { if (it) { onGo(it.v); onClose(); } };
  const onKey = (e) => {
    if (e.key === "ArrowDown") { e.preventDefault(); setSel((x) => Math.min(items.length - 1, x + 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setSel((x) => Math.max(0, x - 1)); }
    else if (e.key === "Enter") { e.preventDefault(); choose(items[sel]); }
    else if (e.key === "Escape") { e.preventDefault(); onClose(); }
  };
  const groups = [];
  items.forEach((it, idx) => {
    let g = groups.find((x) => x.label === it.group);
    if (!g) { g = { label: it.group, items: [] }; groups.push(g); }
    g.items.push({ ...it, idx });
  });
  return (
    <div className="cmdk-scrim" onMouseDown={onClose}>
      <div className="cmdk" onMouseDown={(e) => e.stopPropagation()}>
        <div className="cmdk-input-wrap">
          <Icon name="search" size={18} />
          <input autoFocus className="cmdk-input" placeholder="Jump to…" value={q}
                 onChange={(e) => setQ(e.target.value)} onKeyDown={onKey} />
          <span className="kbd">esc</span>
        </div>
        <div className="cmdk-list">
          {items.length === 0 ? (
            <div className="cmdk-group-label">No matches</div>
          ) : groups.map((g) => (
            <div key={g.label}>
              <div className="cmdk-group-label">{g.label}</div>
              {g.items.map((it) => (
                <button key={it.v} className={`cmdk-item ${it.idx === sel ? "on" : ""}`}
                        onMouseEnter={() => setSel(it.idx)} onClick={() => choose(it)}>
                  <Icon name={it.icon} size={16} /><span>{it.label}</span><span className="spacer" />
                  <span className="go">↵</span>
                </button>
              ))}
            </div>
          ))}
        </div>
        <div className="cmdk-foot">
          <span><span className="kbd">↑↓</span> navigate</span>
          <span><span className="kbd">↵</span> open</span>
          <span><span className="kbd">esc</span> close</span>
        </div>
      </div>
    </div>
  );
}

// Which surfaces are reachable by URL. Anything not listed falls back to the dashboard, so a
// stale bookmark lands somewhere sensible instead of a blank page.
const ROUTES = new Set([...Object.keys(NAV_LABELS), "auth", "pricing", "notifications",
                        "asset", "profile", "admin", "call",
                        // Reached from an email. Without these the link fell through to the SPA
                        // catch-all and landed on the marketing page with the token ignored.
                        "verify", "reset",
                        // OFF THE RAIL BUT STILL ADDRESSABLE. These are gone from NAV_LABELS and
                        // from the command palette, so they cannot be reached from navigation,
                        // which is what taking them off the rail was for. They stay in ROUTES
                        // because in-app links to them still exist — the Morning Brief and the
                        // Dashboard both link to the Radar, and four surfaces link to library
                        // entries — and dropping them here would turn every one of those into a
                        // silent redirect to the Board. A door that opens onto the wrong room is
                        // worse than a door that is not advertised.
                        "radar", "globe", "exposure", "library", "library-entry",
                        "community", "trader"]);

export default function App() {
  const route = useRoute();
  const [minC, setMinC] = useState("medium");
  const [horizon, setHorizon] = useState(90);
  // The Board is the product's landing surface, so an unrecognised path lands there. It is also
  // the one surface guaranteed to have something on it from a cold start, because our own record
  // is always on it. A signed-out stranger never reaches this: the server redirects "/" to the
  // marketing site before the bundle is served.
  const [view, setViewState] = useState(() => (ROUTES.has(route.path) ? route.path : "board"));
  const [clusters, setClusters] = useState(null);
  const [asOf, setAsOf] = useState(null);
  const [defVer, setDefVer] = useState(null);
  const [user, setUser] = useState(null);
  const [feed, setFeed] = useState({ tier: "free", delayed_hours: 48 });
  const [feeds, setFeeds] = useState(null);
  const [calibration, setCalibration] = useState(null);
  const [definitions, setDefinitions] = useState(null);
  const [detail, setDetail] = useState(null);
  const [explanation, setExplanation] = useState(null);
  const [assetSymbol, setAssetSymbol] = useState(null);
  const [traderHandle, setTraderHandle] = useState(
    () => new URLSearchParams(window.location.search).get("handle") || null);
  // A record and a call both live at an address, because a record nobody can point at is not much
  // of a record. Both read their parameter from the URL on first load, so a shared link works.
  const [recordHandle, setRecordHandle] = useState(
    () => new URLSearchParams(window.location.search).get("handle") || null);
  const [callId, setCallId] = useState(
    () => new URLSearchParams(window.location.search).get("id") || null);
  const [profile, setProfile] = useState(null); // {kind, id}
  const [librarySlug, setLibrarySlug] = useState(null);
  const [search, setSearch] = useState("");
  const [pulseKey, setPulseKey] = useState(0);
  const [unread, setUnread] = useState(0);
  const [navOpen, setNavOpen] = useState(false);
  const [cmdOpen, setCmdOpen] = useState(false);
  const [moreOpen, setMoreOpen] = useState(false);
  const [refCode] = useState(() => new URLSearchParams(window.location.search).get("ref") || "");

  const refreshUnread = () => fetchNotifications().then((d) => setUnread(d.unread || 0)).catch(() => {});
  const refreshUser = () => authMe().then((d) => setUser(d.user)).catch(() => {});

  // These three feed the chrome (methodology, freshness, definitions). A failure degrades those
  // panels; it must not paint an error over whatever surface the user is actually looking at.
  useEffect(() => {
    fetchFeeds().then(setFeeds).catch(() => setFeeds(null));
    fetchCalibration().then(setCalibration).catch(() => setCalibration(null));
    fetchDefinitions().then(setDefinitions).catch(() => setDefinitions(null));
    authMe().then((d) => setUser(d.user)).catch(() => {});
    const params = route.query;
    if (params.get("symbol")) { setAssetSymbol(params.get("symbol").toUpperCase()); setViewState("asset"); }
    if (params.get("upgraded")) setViewState("pricing");   // returned from Stripe Checkout
    if (params.get("ref")) setViewState("auth");           // arrived via a referral link
  }, []);

  // Browser back/forward: the URL is the source of truth, so a popstate re-selects the surface AND
  // its parameter. Keying only on `route.path` was not enough: a record page linking to another
  // record leaves the path at "record" and moves only the query, so Back changed the URL and left
  // the previous record on screen. The call detail's Back button makes that the normal way through
  // this feature rather than an edge case.
  useEffect(() => {
    if (ROUTES.has(route.path) && route.path !== view) setViewState(route.path);
    setRecordHandle(route.query.get("handle") || null);
    setCallId(route.query.get("id") || null);
  }, [route.path, route.query.toString()]);

  useEffect(() => {
    document.title = `${NAV_LABELS[view] || BRAND} · ${BRAND}`;
  }, [view]);

  useEffect(() => { if (user) refreshUnread(); else setUnread(0); }, [user]);

  // ⌘K / Ctrl-K opens the command palette from anywhere.
  useEffect(() => {
    const onKey = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setCmdOpen((o) => !o); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    setClusters(null);
    fetchClusters(minC)
      .then((d) => {
        setClusters(d.clusters);
        setAsOf(d.as_of);
        setDefVer(d.definition_version);
        setFeed({ tier: d.tier, delayed_hours: d.delayed_hours });
        setPulseKey((k) => k + 1);
      })
      .catch(() => setClusters([]));      // the Smart Money surface renders its own empty state
  }, [minC, user]);

  // One place that changes the surface, so the URL and the rendered view can never disagree.
  const setView = (v, query) => { setViewState(v); route.go(v, query); };
  // The rail item for "My record" navigates to /record with no handle, and the effect above reads
  // the parameter back out of the URL, so there is one mechanism here rather than two that have to
  // agree with each other.
  const go = (v) => { setView(v); setDetail(null); setNavOpen(false); };
  const openDetail = (id) => {
    setDetail("loading");
    setExplanation(null);
    fetchClusterDetail(id).then(setDetail).catch(() => setDetail({ found: false }));
    fetchExplanation(id, horizon).then(setExplanation).catch(() => {});
  };
  const openSymbol = (sym) => { setAssetSymbol(sym.toUpperCase()); setDetail(null); setView("asset", { symbol: sym.toUpperCase() }); };
  // The handle goes in the URL so a track record can be linked to. A record nobody can point at
  // is not much of a record.
  const openTrader = (handle) => { setTraderHandle(handle); setView("trader", { handle }); };
  const openRecord = (handle) => { setRecordHandle(handle); setView("record", { handle }); };
  const openCall = (id) => { setCallId(String(id)); setView("call", { id }); };
  const openProfile = (kind, id) => { setProfile({ kind, id }); setDetail(null); setView("profile", { kind, id }); };
  const openLibrary = (slug) => { setLibrarySlug(slug); setDetail(null); setView("library-entry", { slug }); };
  const onAuthed = (u) => { setUser(u); setView("board"); };
  const doLogout = async () => { await authLogout(); setUser(null); window.location.assign("/site/"); };
  const submitSearch = () => { if (search.trim()) { setView("search", { q: search.trim() }); setDetail(null); setNavOpen(false); } };

  // "My record" is the signed-in caller's own. Reading somebody else's record uses the same route
  // with a handle, so highlighting the rail item there would tell the reader they are looking at
  // their own record when they are looking at ours.
  const navBtn = (v) => (
    <button key={v} className={`nav-item ${(view === v && !(v === "record" && recordHandle)) ? "on" : ""}`} onClick={() => go(v)}>
      <Icon name={NAV_ICONS[v]} /><span>{NAV_LABELS[v]}</span>
    </button>
  );

  return (
    <div className="shell">
      <aside className={`sidebar ${navOpen ? "open" : ""}`}>
        <div className="brand" onClick={() => (user ? go("dashboard") : window.location.assign("/site/"))}>
          <span className="brand-mark">◆</span><span className="brand-name">{BRAND}</span>
        </div>
        <nav className="side-nav">
          {SIDEBAR.map((section) => (
            <div className="nav-section" key={section.label}>
              <div className="nav-section-label">{section.label}</div>
              {section.items.map(navBtn)}
            </div>
          ))}
          <div className="nav-section">
            <button className={`nav-more-toggle ${moreOpen ? "open" : ""}`} onClick={() => setMoreOpen((o) => !o)}>
              More <span className="chev"><Icon name="chevron" size={12} /></span>
            </button>
            {moreOpen && MORE.map(navBtn)}
          </div>
          {user?.tier === "admin" && (
            <div className="nav-section">
              <div className="nav-section-label">Admin</div>
              <button className={`nav-item admin ${view === "admin" ? "on" : ""}`} onClick={() => go("admin")}>
                <Icon name="shield" /><span>Admin</span>
              </button>
            </div>
          )}
        </nav>
        <div className="side-foot">
          <div className="side-ver">{defVer ? `Signal v${defVer} · SEC-derived` : "SEC-derived intelligence"}</div>
        </div>
      </aside>

      <div className="main">
        <header className="topbar">
          <button className="icon-btn menu-btn" onClick={() => setNavOpen((o) => !o)} title="menu"><Icon name="menu" /></button>
          <div className="search-wrap" onClick={() => document.getElementById("topsearch")?.focus()}>
            <Icon name="search" size={16} />
            <input id="topsearch" className="topsearch" placeholder="Search tickers, institutions, insiders…" value={search}
              onChange={(e) => setSearch(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") submitSearch(); }} />
            <span className="kbd">⌘K</span>
          </div>
          {/* Narrow screens have no room for the search field and no ⌘K to reach the palette with,
              so search would be unreachable rather than merely cramped. This button replaces the
              field below 720px and is hidden above it. */}
          <button className="icon-btn search-btn" onClick={() => go("search")} title="search"><Icon name="search" /></button>
          <div className="topbar-right">
            <button className="ask-ai" onClick={() => go("assistant")} title="Ask the AI mentor"><Icon name="compass" size={16} /><span>Ask AI</span></button>
            <button className="upgrade-btn" onClick={() => go("pricing")}>⚡ {user && user.tier !== "free" ? user.tier : "Upgrade"}</button>
            <button className="icon-btn" onClick={() => go("notifications")} title="notifications">
              <Icon name="bell" />{unread > 0 && <span className="bell-badge">{unread > 9 ? "9+" : unread}</span>}
            </button>
            {user ? (
              <>
                <div className="account">
                  <span className="account-av">{user.email[0].toUpperCase()}</span>
                  <span className="account-meta"><b>{user.email.split("@")[0]}</b><span>{user.tier}</span></span>
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
          {/* First-run frame setup. Renders nothing unless the server says this reader is due, so
              it costs one request and never blocks a surface. Keyed by user so signing in as
              someone else re-asks the question for them.

              NOT on the Receipts surfaces. Measured at 375px: this card filled the entire first
              viewport of /publish and /record — a country selector, a currency field and a follow
              list, above the fold, on the two screens whose whole job is publish-a-call and
              check-my-record. It configures the RADAR, which is not even on the navigation rail
              any more, and none of the Receipts code paths read `relevance`. So a caller arriving
              to publish met a minute of setup for a surface they will never open, with a "not now"
              link wrapping onto two lines in the corner as the only way past it. It still shows
              everywhere it is relevant. */}
          {user && !ONBOARDING_SUPPRESSED.has(view) && (
            <OnboardingCard key={user.id} onDone={refreshUser} />
          )}
          <ErrorBoundary key={view} surface={view}>
          {view === "verify" ? (
            <VerifyView onDone={go} />
          ) : view === "reset" ? (
            <ResetView onDone={go} />
          ) : view === "dashboard" ? (
            <Dashboard user={user} onOpenSymbol={openSymbol} onNav={go} />
          ) : view === "search" ? (
            <SearchView query={search} onOpenSymbol={openSymbol} onOpenProfile={openProfile} onOpenLibrary={openLibrary} onOpenTrader={openTrader} />
          ) : view === "home" ? (
            detail ? (
              detail === "loading" ? (
                <div className="issuer"><div className="issuer-hero"><div className="skel" style={{ width: 220, height: 60 }} /></div></div>
              ) : detail.found === false ? (
                <div className="issuer"><button className="issuer-back" onClick={() => setDetail(null)}>← back</button><div>No cluster for that issuer at the latest as-of.</div></div>
              ) : (
                <IssuerDetail detail={detail} onBack={() => setDetail(null)} calibration={calibration} horizon={horizon}
                              explanation={explanation} onOpenLibrary={openLibrary} onOpenSymbol={openSymbol} onOpenProfile={openProfile} />
              )
            ) : (
              <SmartMoneyView calibration={calibration} horizon={horizon} minC={minC} user={user}
                    onLogin={() => go("auth")} onNav={go} onOpenSymbol={openSymbol}
                    onOpenDetail={openDetail} onOpenProfile={openProfile} />
            )
          ) : view === "brief" ? (
            <BriefView user={user} onOpenSymbol={openSymbol} onOpenProfile={openProfile} onNav={go} />
          ) : view === "news" ? (
            <NewsView onOpenSymbol={openSymbol} />
          ) : view === "events" ? (
            <CalendarView onOpenSymbol={openSymbol} />
          ) : view === "alerts" ? (
            <AlertsView onLogin={() => go("auth")} onOpenSymbol={openSymbol} />
          ) : view === "exposure" ? (
            <ExposureView user={user} onLogin={() => go("auth")} onNav={go} />
          ) : view === "portfolios" ? (
            <PortfoliosView user={user} onLogin={() => go("auth")} onOpenSymbol={openSymbol} />
          ) : view === "journal" ? (
            <JournalView user={user} onLogin={() => go("auth")} onOpenSymbol={openSymbol} onOpenLibrary={openLibrary} />
          ) : view === "assistant" ? (
            <AssistantView user={user} onLogin={() => go("auth")} />
          ) : view === "trending" ? (
            <SocialView onOpenSymbol={openSymbol} onNav={go} />
          ) : view === "pricing" ? (
            <PricingView user={user} onUpgraded={refreshUser} onLogin={() => go("auth")} onNav={go} />
          ) : view === "notifications" ? (
            <NotificationsView onOpenSymbol={openSymbol} onLogin={() => go("auth")} onChanged={refreshUnread} />
          ) : view === "asset" ? (
            <AssetView symbol={assetSymbol} calibration={calibration} horizon={horizon}
                       onOpenProfile={openProfile} onBack={() => go("home")} />
          ) : view === "profile" ? (
            <ProfileView kind={profile.kind} id={profile.id} user={user} onOpenSymbol={openSymbol} onBack={() => go("home")} />
          ) : view === "community" ? (
            <CommunityView user={user} onOpenTrader={openTrader} />
          ) : view === "trader" ? (
            <TraderView handle={traderHandle} user={user} onBack={() => go("community")} />
          ) : view === "screener" ? (
            <Screener onOpenSymbol={openSymbol} />
          ) : view === "watchlist" ? (
            <WatchlistView onOpenSymbol={openSymbol} onLogin={() => go("auth")} />
          ) : view === "auth" ? (
            <AuthPanel onAuthed={onAuthed} onBack={() => (user ? go("home") : window.location.assign("/site/"))} initialInvite={refCode} />
          ) : view === "library" ? (
            <LibraryView onOpenEntry={openLibrary} />
          ) : view === "library-entry" ? (
            <LibraryEntry slug={librarySlug} onBack={() => go("library")} onOpenLibrary={openLibrary} />
          ) : view === "crypto" ? (
            <CryptoView />
          ) : view === "radar" ? (
            <RadarView user={user} onLogin={() => go("auth")} />
          ) : view === "globe" ? (
            <GlobeView user={user} onLogin={() => go("auth")} />
          ) : view === "ledger" ? (
            <LedgerView />
          ) : view === "board" ? (
            <BoardView onOpenRecord={openRecord} onNav={go} />
          ) : view === "record" ? (
            // "My record" with no handle resolves to the signed-in caller's own; PublishView is
            // the surface that knows how to claim one, so it handles the not-yet-a-caller case.
            recordHandle ? (
              <RecordView handle={recordHandle} onOpenCall={openCall} onNav={go} />
            ) : (
              <MyRecord user={user} onLogin={() => go("auth")} onOpenRecord={openRecord}
                        onNav={go} />
            )
          ) : view === "publish" ? (
            <PublishView user={user} onLogin={() => go("auth")} onOpenCall={openCall}
                         onOpenRecord={openRecord} />
          ) : view === "call" ? (
            <CallDetailView callId={callId} onBack={() => window.history.back()}
                            onOpenRecord={openRecord} />
          ) : view === "methodology" ? (
            <ReceiptsMethodologyView />
          ) : view === "signal-methodology" ? (
            <Methodology calibration={calibration} definitions={definitions} onBack={() => go("home")} />
          ) : view === "integrations" ? (
            <IntegrationsView onLogin={() => go("auth")} />
          ) : view === "admin" ? (
            <AdminView user={user} />
          ) : (
            <BoardView onOpenRecord={openRecord} onNav={go} />
          )}
          </ErrorBoundary>
        </main>
      </div>

      {navOpen && <div className="scrim" onClick={() => setNavOpen(false)} />}
      {cmdOpen && <CommandPalette onGo={go} onClose={() => setCmdOpen(false)} />}
    </div>
  );
}
