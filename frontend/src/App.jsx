import { useEffect, useRef, useState } from "react";
import { authLogout, authMe, fetchCalibration, fetchClusters, fetchClusterDetail, fetchDefinitions, fetchExplanation, fetchFeeds } from "./api";
import { ClusterDetail, ClusterTable, Disclaimer, Methodology, StatusStrip } from "./components.jsx";
import { AssetView, AuthPanel, LibraryEntry, LibraryView, ProfileView, Screener, WatchlistView } from "./views.jsx";
import { CryptoPreview, OptionsPreview } from "./previews.jsx";

export default function App() {
  const [minC, setMinC] = useState("medium");
  const [horizon, setHorizon] = useState(90);
  const [view, setView] = useState("dashboard"); // 'dashboard' | 'methodology'
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
  const hero = useRef(null);

  useEffect(() => {
    fetchFeeds().then(setFeeds).catch((e) => setErr(String(e)));
    fetchCalibration().then(setCalibration).catch((e) => setErr(String(e)));
    fetchDefinitions().then(setDefinitions).catch((e) => setErr(String(e)));
    authMe().then((d) => setUser(d.user)).catch(() => {});
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
      .catch((e) => setErr(String(e)));
  }, [minC, user]);

  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const onScroll = () => {
      if (hero.current) hero.current.style.transform = `translateY(${Math.min(window.scrollY * 0.06, 6)}px)`;
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  const openDetail = (id) => {
    setDetail("loading");
    setExplanation(null);
    fetchClusterDetail(id).then(setDetail).catch((e) => setErr(String(e)));
    fetchExplanation(id, horizon).then(setExplanation).catch(() => {});
  };
  const openSymbol = (sym) => { setAssetSymbol(sym.toUpperCase()); setDetail(null); setView("asset"); };
  const openProfile = (kind, id) => { setProfile({ kind, id }); setDetail(null); setView("profile"); };
  const openLibrary = (slug) => { setLibrarySlug(slug); setDetail(null); setView("library-entry"); };
  const onAuthed = (u) => { setUser(u); setView("dashboard"); };
  const doLogout = async () => { await authLogout(); setUser(null); setView("dashboard"); };

  return (
    <div className="app">
      <div className="hero" ref={hero}>
        <div className="glow" />
        <div className="hero-row">
          <div>
            <h1>TRADEOS · CONVERGENCE</h1>
            <div className="sub">
              Independent smart-money disclosures clustering on one issuer, computed strictly
              point-in-time. {defVer && `Signal definition v${defVer}.`}
            </div>
          </div>
          <nav className="nav">
            <input
              className="search"
              placeholder="ticker…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && search.trim()) openSymbol(search.trim()); }}
            />
            {["dashboard", "watchlist", "screener", "library", "methodology"].map((v) => (
              <button key={v} className={(view === v || (v === "library" && view === "library-entry")) ? "on" : ""} onClick={() => { setView(v); setDetail(null); }}>{v}</button>
            ))}
            <span className="nav-sep">roadmap</span>
            {["options", "crypto"].map((v) => (
              <button key={v} className={`preview-nav ${view === v ? "on" : ""}`} onClick={() => { setView(v); setDetail(null); }}>{v}▹</button>
            ))}
            {user ? (
              <>
                <span className="nav-sep">{user.email.split("@")[0]} · {user.tier}</span>
                <button onClick={doLogout}>log out</button>
              </>
            ) : (
              <button className={view === "auth" ? "on" : ""} onClick={() => { setView("auth"); setDetail(null); }}>log in</button>
            )}
          </nav>
        </div>
      </div>

      <StatusStrip feeds={feeds} />
      {err && <div className="err">error: {err}</div>}

      {view === "methodology" ? (
        <Methodology calibration={calibration} definitions={definitions} onBack={() => setView("dashboard")} />
      ) : view === "asset" ? (
        <AssetView symbol={assetSymbol} calibration={calibration} horizon={horizon}
                   onOpenProfile={openProfile} onBack={() => setView("dashboard")} />
      ) : view === "profile" ? (
        <ProfileView kind={profile.kind} id={profile.id} onOpenSymbol={openSymbol} onBack={() => setView("dashboard")} />
      ) : view === "screener" ? (
        <Screener onOpenSymbol={openSymbol} />
      ) : view === "watchlist" ? (
        <WatchlistView onOpenSymbol={openSymbol} />
      ) : view === "auth" ? (
        <AuthPanel onAuthed={onAuthed} onBack={() => setView("dashboard")} />
      ) : view === "library" ? (
        <LibraryView onOpenEntry={openLibrary} />
      ) : view === "library-entry" ? (
        <LibraryEntry slug={librarySlug} onBack={() => setView("library")} onOpenLibrary={openLibrary} />
      ) : view === "options" ? (
        <OptionsPreview onBack={() => setView("dashboard")} />
      ) : view === "crypto" ? (
        <CryptoPreview onBack={() => setView("dashboard")} />
      ) : detail ? (
        detail === "loading" ? (
          <div className="detail"><div className="skel" style={{ width: 220 }} /></div>
        ) : detail.found === false ? (
          <div className="detail">
            <button className="back" onClick={() => setDetail(null)}>← back to clusters</button>
            <div>No cluster for that issuer at the latest as-of.</div>
          </div>
        ) : (
          <ClusterDetail detail={detail} onBack={() => setDetail(null)} calibration={calibration} horizon={horizon} explanation={explanation} onOpenLibrary={openLibrary} />
        )
      ) : (
        <>
          <div className="controls">
            <div className="seg">
              {["low", "medium", "high"].map((b) => (
                <button key={b} className={minC === b ? "on" : ""} onClick={() => setMinC(b)}>{b}+</button>
              ))}
            </div>
            <div className="seg">
              {[30, 90, 180].map((h) => (
                <button key={h} className={horizon === h ? "on" : ""} onClick={() => setHorizon(h)}>{h}d</button>
              ))}
            </div>
            <div className="asof">
              {feed.delayed_hours > 0
                ? <span className="fresh a" title="Free/unauthenticated: signals shown on a 48-hour delay">48h DELAYED · {feed.tier}</span>
                : <span className="fresh g" title="Live signals (paid tier)">LIVE · {feed.tier}</span>}
              {asOf ? `  as of ${asOf.slice(0, 19).replace("T", " ")} UTC` : ""}
            </div>
          </div>

          {clusters === null ? (
            <table className="clusters">
              <tbody>
                {[...Array(5)].map((_, i) => (
                  <tr key={i}><td colSpan={7}><div className="skel" style={{ width: `${70 - i * 6}%` }} /></td></tr>
                ))}
              </tbody>
            </table>
          ) : clusters.length === 0 ? (
            <div className="err" style={{ color: "var(--muted)" }}>
              No {minC}+ clusters at this as-of. Lower the threshold, or ingest a wider window and recompute.
            </div>
          ) : (
            <ClusterTable clusters={clusters} onSelect={openDetail} pulseKey={pulseKey} calibration={calibration} horizon={horizon} />
          )}
          <Disclaimer />
        </>
      )}
    </div>
  );
}
