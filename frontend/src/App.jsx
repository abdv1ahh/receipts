import { useEffect, useState } from "react";
import { authLogout, authMe, fetchCalibration, fetchClusters, fetchClusterDetail, fetchDefinitions, fetchExplanation, fetchFeeds, fetchNotifications } from "./api";
import { Methodology } from "./components.jsx";
import { AssetView, AuthPanel, LibraryEntry, LibraryView, ProfileView, Screener, WatchlistView } from "./views.jsx";
import { SmartMoneyView, IssuerDetail } from "./smartmoney.jsx";
import { JournalView } from "./journal.jsx";
import { AssistantView } from "./assistant.jsx";
import { SocialView } from "./social.jsx";
import { AlertsView, NotificationsView } from "./alerts.jsx";
import { BriefView } from "./brief.jsx";
import { NewsView } from "./news.jsx";
import { EventsView } from "./events.jsx";
import { PortfoliosView } from "./portfolios.jsx";
import { PricingView } from "./pricing.jsx";
import { CryptoView } from "./crypto.jsx";
import { LandingView, SearchView } from "./discover.jsx";
import { AdminView } from "./admin.jsx";
import { Dashboard } from "./dashboard.jsx";
import { IntegrationsView } from "./integrations.jsx";
import { RadarView } from "./radar.jsx";
import { OnboardingCard } from "./onboarding.jsx";
import { GlobeView } from "./globe.jsx";
import { ExposureView } from "./exposure.jsx";
import { CalendarView } from "./calendar.jsx";
import { LedgerView } from "./ledger.jsx";
import { ErrorBoundary, useRoute } from "./shell.jsx";
import { Icon } from "./icons.jsx";

const BRAND = "Rhumb";
const NAV_LABELS = { radar: "Radar", globe: "The World", ledger: "Ledger", dashboard: "Dashboard", brief: "Morning Brief", news: "News", events: "Calendar", home: "Smart Money", trending: "Social", crypto: "Crypto", journal: "Journal", exposure: "Exposure", watchlist: "Watchlist", alerts: "Alerts", assistant: "AI Assistant", screener: "Screener", library: "Library", methodology: "Methodology", integrations: "Integrations" };
const NAV_ICONS = { radar: "radar", globe: "layers", ledger: "target", dashboard: "grid", brief: "sparkles", news: "news", events: "calendar", home: "signal", trending: "trending", crypto: "crypto", journal: "journal", exposure: "briefcase", watchlist: "star", alerts: "bell", assistant: "compass", screener: "filter", library: "book", methodology: "target", integrations: "plug" };
// A calmer rail: the essentials up front, utilities tucked into a collapsible "More".
const SIDEBAR = [
  { label: "Overview", items: ["radar", "globe", "dashboard", "brief"] },
  { label: "Intelligence", items: ["ledger", "home", "trending", "news", "crypto", "events"] },
  { label: "Your desk", items: ["journal", "exposure", "watchlist", "assistant", "alerts"] },
];
const MORE = ["screener", "library", "integrations", "methodology"];
// Everything reachable from the ⌘K command palette.
const CMD_ITEMS = [
  ...["radar", "globe", "ledger", "dashboard", "brief", "home", "trending", "news", "crypto", "events", "journal", "exposure", "watchlist", "assistant", "alerts", "screener", "library", "integrations", "methodology"]
    .map((v) => ({ v, label: NAV_LABELS[v], icon: NAV_ICONS[v], group: "Go to" })),
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
const ROUTES = new Set([...Object.keys(NAV_LABELS), "landing", "auth", "pricing", "notifications",
                        "search", "asset", "profile", "library-entry", "admin"]);

export default function App() {
  const route = useRoute();
  const [minC, setMinC] = useState("medium");
  const [horizon, setHorizon] = useState(90);
  const [view, setViewState] = useState(() => (ROUTES.has(route.path) ? route.path : "landing"));
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
    authMe().then((d) => { setUser(d.user); if (d.user) setViewState((v) => (v === "landing" ? "radar" : v)); }).catch(() => {});
    const params = route.query;
    if (params.get("symbol")) { setAssetSymbol(params.get("symbol").toUpperCase()); setViewState("asset"); }
    if (params.get("upgraded")) setViewState("pricing");   // returned from Stripe Checkout
    if (params.get("ref")) setViewState("auth");           // arrived via a referral link
  }, []);

  // Browser back/forward: the URL is the source of truth, so a popstate re-selects the surface.
  useEffect(() => {
    if (ROUTES.has(route.path) && route.path !== view) setViewState(route.path);
    else if (!route.path && view !== "landing" && !user) setViewState("landing");
  }, [route.path]);

  useEffect(() => {
    document.title = view === "landing" ? `${BRAND} — world events, and what they mean for you`
                                        : `${NAV_LABELS[view] || BRAND} · ${BRAND}`;
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
  const setView = (v, query) => { setViewState(v); route.go(v === "landing" ? "" : v, query); };
  const go = (v) => { setView(v); setDetail(null); setNavOpen(false); };
  const openDetail = (id) => {
    setDetail("loading");
    setExplanation(null);
    fetchClusterDetail(id).then(setDetail).catch(() => setDetail({ found: false }));
    fetchExplanation(id, horizon).then(setExplanation).catch(() => {});
  };
  const openSymbol = (sym) => { setAssetSymbol(sym.toUpperCase()); setDetail(null); setView("asset", { symbol: sym.toUpperCase() }); };
  const openProfile = (kind, id) => { setProfile({ kind, id }); setDetail(null); setView("profile", { kind, id }); };
  const openLibrary = (slug) => { setLibrarySlug(slug); setDetail(null); setView("library-entry", { slug }); };
  const onAuthed = (u) => { setUser(u); setView("radar"); };
  const doLogout = async () => { await authLogout(); setUser(null); setView("landing"); };
  const submitSearch = () => { if (search.trim()) { setView("search", { q: search.trim() }); setDetail(null); setNavOpen(false); } };

  const navBtn = (v) => (
    <button key={v} className={`nav-item ${view === v || (v === "library" && view === "library-entry") ? "on" : ""}`} onClick={() => go(v)}>
      <Icon name={NAV_ICONS[v]} /><span>{NAV_LABELS[v]}</span>
    </button>
  );

  return (
    <div className="shell">
      <aside className={`sidebar ${navOpen ? "open" : ""}`}>
        <div className="brand" onClick={() => go(user ? "dashboard" : "landing")}>
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
              someone else re-asks the question for them. */}
          {user && view !== "landing" && view !== "auth" && (
            <OnboardingCard key={user.id} onDone={refreshUser} />
          )}
          <ErrorBoundary key={view} surface={view}>
          {view === "landing" ? (
            <LandingView onGetStarted={() => go("auth")} onExplore={() => go("news")} />
          ) : view === "dashboard" ? (
            <Dashboard user={user} onOpenSymbol={openSymbol} onNav={go} />
          ) : view === "search" ? (
            <SearchView query={search} onOpenSymbol={openSymbol} onOpenProfile={openProfile} onOpenLibrary={openLibrary} onOpenTrader={() => {}} />
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
            <SocialView onOpenSymbol={openSymbol} />
          ) : view === "pricing" ? (
            <PricingView user={user} onUpgraded={refreshUser} onLogin={() => go("auth")} />
          ) : view === "notifications" ? (
            <NotificationsView onOpenSymbol={openSymbol} onLogin={() => go("auth")} onChanged={refreshUnread} />
          ) : view === "methodology" ? (
            <Methodology calibration={calibration} definitions={definitions} onBack={() => go("home")} />
          ) : view === "asset" ? (
            <AssetView symbol={assetSymbol} calibration={calibration} horizon={horizon}
                       onOpenProfile={openProfile} onBack={() => go("home")} />
          ) : view === "profile" ? (
            <ProfileView kind={profile.kind} id={profile.id} user={user} onOpenSymbol={openSymbol} onBack={() => go("home")} />
          ) : view === "screener" ? (
            <Screener onOpenSymbol={openSymbol} />
          ) : view === "watchlist" ? (
            <WatchlistView onOpenSymbol={openSymbol} onLogin={() => go("auth")} />
          ) : view === "auth" ? (
            <AuthPanel onAuthed={onAuthed} onBack={() => go(user ? "home" : "landing")} initialInvite={refCode} />
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
          ) : view === "integrations" ? (
            <IntegrationsView onLogin={() => go("auth")} />
          ) : view === "admin" ? (
            <AdminView user={user} />
          ) : (
            <Dashboard user={user} onOpenSymbol={openSymbol} onNav={go} />
          )}
          </ErrorBoundary>
        </main>
      </div>

      {navOpen && <div className="scrim" onClick={() => setNavOpen(false)} />}
      {cmdOpen && <CommandPalette onGo={go} onClose={() => setCmdOpen(false)} />}
    </div>
  );
}
