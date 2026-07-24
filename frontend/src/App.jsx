import { useEffect, useState } from "react";
import { authLogout, authMe, fetchCalibration, fetchClusters, fetchClusterDetail, fetchDefinitions, fetchExplanation, fetchFeeds, fetchNotifications } from "./api";
import { ClusterDetail, Methodology, StatusStrip } from "./components.jsx";
import { AssetView, AuthPanel, LibraryEntry, LibraryView, ProfileView, Screener, WatchlistView } from "./views.jsx";
import { Home } from "./home.jsx";
import { JournalView } from "./journal.jsx";
import { AssistantView } from "./assistant.jsx";
import { ScannerView } from "./scanner.jsx";
import { AlertsView, NotificationsView } from "./alerts.jsx";
import { BriefView } from "./brief.jsx";
import { NewsView } from "./news.jsx";
import { EventsView } from "./events.jsx";
import { PortfoliosView } from "./portfolios.jsx";
import { PricingView } from "./pricing.jsx";
import { CryptoView } from "./crypto.jsx";
import { LandingView, SearchView } from "./discover.jsx";
import { AdminView } from "./admin.jsx";
import { Icon } from "./icons.jsx";

const NAV_LABELS = { brief: "Morning Brief", news: "News", events: "Calendar", home: "Smart Money", trending: "Social", crypto: "Crypto", journal: "Journal", portfolios: "Portfolios", watchlist: "Watchlist", alerts: "Alerts", assistant: "Assistant", screener: "Screener", library: "Library", methodology: "Methodology" };
const NAV_ICONS = { brief: "sparkles", news: "news", events: "calendar", home: "signal", trending: "trending", crypto: "crypto", journal: "journal", portfolios: "briefcase", watchlist: "star", alerts: "bell", assistant: "compass", screener: "filter", library: "book", methodology: "target" };
const SIDEBAR = [
  { label: "Intelligence", items: ["brief", "news", "events", "home", "trending", "crypto"] },
  { label: "Your desk", items: ["journal", "portfolios", "watchlist", "alerts", "assistant"] },
  { label: "Research", items: ["screener", "library", "methodology"] },
];

export default function App() {
  const [minC, setMinC] = useState("medium");
  const [horizon, setHorizon] = useState(90);
  const [view, setView] = useState("landing"); // marketing landing for logged-out; flips to home when authed
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
  const [err, setErr] = useState(null);
  const [pulseKey, setPulseKey] = useState(0);
  const [unread, setUnread] = useState(0);
  const [navOpen, setNavOpen] = useState(false);
  const [refCode] = useState(() => new URLSearchParams(window.location.search).get("ref") || "");

  const refreshUnread = () => fetchNotifications().then((d) => setUnread(d.unread || 0)).catch(() => {});
  const refreshUser = () => authMe().then((d) => setUser(d.user)).catch(() => {});

  useEffect(() => {
    fetchFeeds().then(setFeeds).catch((e) => setErr(String(e)));
    fetchCalibration().then(setCalibration).catch((e) => setErr(String(e)));
    fetchDefinitions().then(setDefinitions).catch((e) => setErr(String(e)));
    authMe().then((d) => { setUser(d.user); if (d.user) setView((v) => (v === "landing" ? "brief" : v)); }).catch(() => {});
    const params = new URLSearchParams(window.location.search);
    if (params.get("symbol")) { setAssetSymbol(params.get("symbol").toUpperCase()); setView("asset"); }
    if (params.get("upgraded")) setView("pricing");   // returned from Stripe Checkout
    if (params.get("ref")) setView("auth");           // arrived via a referral link
  }, []);

  useEffect(() => { if (user) refreshUnread(); else setUnread(0); }, [user]);

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
      .catch((e) => setErr(String(e)));
  }, [minC, user]);

  const go = (v) => { setView(v); setDetail(null); setNavOpen(false); };
  const openDetail = (id) => {
    setDetail("loading");
    setExplanation(null);
    fetchClusterDetail(id).then(setDetail).catch((e) => setErr(String(e)));
    fetchExplanation(id, horizon).then(setExplanation).catch(() => {});
  };
  const openSymbol = (sym) => { setAssetSymbol(sym.toUpperCase()); setDetail(null); setView("asset"); };
  const openProfile = (kind, id) => { setProfile({ kind, id }); setDetail(null); setView("profile"); };
  const openLibrary = (slug) => { setLibrarySlug(slug); setDetail(null); setView("library-entry"); };
  const onAuthed = (u) => { setUser(u); setView("brief"); };
  const doLogout = async () => { await authLogout(); setUser(null); setView("landing"); };
  const submitSearch = () => { if (search.trim()) { setView("search"); setDetail(null); setNavOpen(false); } };

  const navBtn = (v) => (
    <button key={v} className={`nav-item ${view === v || (v === "library" && view === "library-entry") ? "on" : ""}`} onClick={() => go(v)}>
      <Icon name={NAV_ICONS[v]} /><span>{NAV_LABELS[v]}</span>
    </button>
  );

  return (
    <div className="shell">
      <aside className={`sidebar ${navOpen ? "open" : ""}`}>
        <div className="brand" onClick={() => go(user ? "brief" : "landing")}>
          <span className="brand-mark">◆</span><span className="brand-name">TradeOS</span>
        </div>
        <nav className="side-nav">
          {SIDEBAR.map((section) => (
            <div className="nav-section" key={section.label}>
              <div className="nav-section-label">{section.label}</div>
              {section.items.map(navBtn)}
            </div>
          ))}
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
          <div className="search-wrap">
            <Icon name="search" size={16} />
            <input className="topsearch" placeholder="Search issuers, institutions, traders…" value={search}
              onChange={(e) => setSearch(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") submitSearch(); }} />
          </div>
          <div className="topbar-right">
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

        <main className="content">
          {view !== "landing" && view !== "auth" && <StatusStrip feeds={feeds} />}
          {err && <div className="err">error: {err}</div>}

          {view === "landing" ? (
            <LandingView onGetStarted={() => go("auth")} onExplore={() => go("news")} />
          ) : view === "search" ? (
            <SearchView query={search} onOpenSymbol={openSymbol} onOpenProfile={openProfile} onOpenLibrary={openLibrary} onOpenTrader={() => {}} />
          ) : view === "home" ? (
            detail ? (
              detail === "loading" ? (
                <div className="detail"><div className="skel" style={{ width: 220 }} /></div>
              ) : detail.found === false ? (
                <div className="detail"><button className="back" onClick={() => setDetail(null)}>← back</button><div>No cluster for that issuer at the latest as-of.</div></div>
              ) : (
                <ClusterDetail detail={detail} onBack={() => setDetail(null)} calibration={calibration} horizon={horizon} explanation={explanation} onOpenLibrary={openLibrary} />
              )
            ) : (
              <Home calibration={calibration} horizon={horizon} minC={minC} user={user}
                    onLogin={() => go("auth")} onNav={go} onOpenSymbol={openSymbol}
                    onOpenDetail={openDetail} onOpenProfile={openProfile} />
            )
          ) : view === "brief" ? (
            <BriefView user={user} onOpenSymbol={openSymbol} onOpenProfile={openProfile} onNav={go} />
          ) : view === "news" ? (
            <NewsView onOpenSymbol={openSymbol} />
          ) : view === "events" ? (
            <EventsView onOpenSymbol={openSymbol} />
          ) : view === "alerts" ? (
            <AlertsView onLogin={() => go("auth")} onOpenSymbol={openSymbol} />
          ) : view === "portfolios" ? (
            <PortfoliosView user={user} onLogin={() => go("auth")} onOpenSymbol={openSymbol} />
          ) : view === "journal" ? (
            <JournalView user={user} onLogin={() => go("auth")} onOpenSymbol={openSymbol} onOpenLibrary={openLibrary} />
          ) : view === "assistant" ? (
            <AssistantView user={user} />
          ) : view === "trending" ? (
            <ScannerView onOpenSymbol={openSymbol} />
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
            <WatchlistView onOpenSymbol={openSymbol} />
          ) : view === "auth" ? (
            <AuthPanel onAuthed={onAuthed} onBack={() => go(user ? "home" : "landing")} initialInvite={refCode} />
          ) : view === "library" ? (
            <LibraryView onOpenEntry={openLibrary} />
          ) : view === "library-entry" ? (
            <LibraryEntry slug={librarySlug} onBack={() => go("library")} onOpenLibrary={openLibrary} />
          ) : view === "crypto" ? (
            <CryptoView />
          ) : view === "admin" ? (
            <AdminView user={user} />
          ) : (
            <Home calibration={calibration} horizon={horizon} minC={minC} user={user}
                  onLogin={() => go("auth")} onNav={go} onOpenSymbol={openSymbol}
                  onOpenDetail={openDetail} onOpenProfile={openProfile} />
          )}
        </main>
      </div>

      {navOpen && <div className="scrim" onClick={() => setNavOpen(false)} />}
    </div>
  );
}
