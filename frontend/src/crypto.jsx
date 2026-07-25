// Crypto — market STRUCTURE first, prices second.
//
// This surface used to be a price table: price, 24h, market cap, sparkline. Every number real, and
// every one available free elsewhere in five seconds. That is the definition of a mirror, and a
// mirror adds nothing — which was the owner's criticism, and it was correct.
//
// What leads now is positioning: who is leveraged which way, what it costs them to stay there, and
// whether that crowd is building or unwinding. It is equally free (Binance's public futures
// endpoints, no key) and almost nobody surfaces it, because it takes a paragraph to explain rather
// than a number to print.
//
// Every reading carries the condition that would BREAK it. A reading you cannot be wrong about is
// worthless, and this product scores itself.
import { useEffect, useMemo, useState } from "react";
import { fetchCryptoMarkets, fetchCryptoStructure, fetchCryptoTrending } from "./api";
import { Icon } from "./icons.jsx";
import { LoadError } from "./shell.jsx";

const BAND = (state) => (state.startsWith("extremely") ? "high"
  : state.startsWith("crowded") ? "high"
  : state.startsWith("leaning") ? "medium" : "low");

function Positioning({ d }) {
  if (!d) return <div className="skel" style={{ width: "60%", height: 70, marginTop: 14 }} />;
  if (!d.available) {
    return <div className="empty" style={{ marginTop: 14 }}>{d.note}</div>;
  }
  return (
    <>
      <div className="cx-summary">
        <div className="pulse-kicker"><span className="live-dot" /> Market structure</div>
        <div className="cx-line">{d.summary.line}</div>
        {d.liquidity?.available && (
          <div className="cx-liq">
            <b>Liquidity: {d.liquidity.state}</b> — {d.liquidity.mechanism}
          </div>
        )}
      </div>

      {d.positioning.map((r) => (
        <div key={r.symbol} className="cx-card">
          <div className="cx-top">
            <span className="cx-sym">{r.symbol}</span>
            <span className={`rd-conf band-${BAND(r.state)}`}>{r.state}</span>
            <span className="cx-fund">
              {r.funding_annualised_pct >= 0 ? "+" : ""}{r.funding_annualised_pct}%/yr funding
            </span>
            {r.funding_direction !== "flat" && <span className="cx-dir">{r.funding_direction}</span>}
            {r.attention_driven && <span className="cx-meme">attention-driven</span>}
            <span className="spacer" />
            <span className="name">{r.confidence} confidence</span>
          </div>
          <p className="cx-mech">{r.mechanism}</p>
          {r.notes.map((n, i) => <div key={i} className="cx-note">· {n}</div>)}
          <div className="cx-invalid">
            <Icon name="alert" size={13} /> {r.invalidation}
          </div>
        </div>
      ))}

      {d.narrative?.length > 0 && (
        <div className="sec" style={{ marginTop: 14 }}>
          <div className="sec-head"><div className="sec-title">What this product has interpreted</div></div>
          {d.narrative.map((n) => (
            <div key={n.id} className="cx-narr">
              <span className="rd-conf band-medium">{Math.round(n.confidence * 100)}%</span>
              <span>{n.mechanism}</span>
            </div>
          ))}
        </div>
      )}

      <div className="disc" style={{ marginTop: 14 }}>{d.disclaimer}</div>
      <div className="cx-src">Positioning: {d.source}. Prices: CoinGecko free tier.</div>
    </>
  );
}

const RISK = { high_volatility: "⚡ volatile", microcap: "microcap", thin_volume: "thin volume" };
const usd = (v) => (v == null ? "—" : v >= 1 ? `$${v.toLocaleString(undefined, { maximumFractionDigits: 2 })}` : `$${v.toPrecision(3)}`);
const cap = (v) => (v == null ? "—" : v >= 1e12 ? `$${(v / 1e12).toFixed(2)}T` : v >= 1e9 ? `$${(v / 1e9).toFixed(1)}B` : v >= 1e6 ? `$${(v / 1e6).toFixed(1)}M` : `$${v.toLocaleString()}`);
const chgCls = (v) => (v == null ? "" : v >= 0 ? "pos-pos" : "pos-neg");
const chg = (v) => (v == null ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(1)}%`);
const TONE = { risk_on: "Risk-on", mixed: "Mixed", risk_off: "Risk-off" };

function Spark({ data, up }) {
  if (!data || data.length < 2) return <span className="coin-spark-na">—</span>;
  const min = Math.min(...data), max = Math.max(...data), span = max - min || 1, n = data.length;
  const pts = data.map((v, i) => `${(i / (n - 1)) * 100},${20 - ((v - min) / span) * 18}`).join(" ");
  return (
    <svg className="coin-spark" viewBox="0 0 100 20" preserveAspectRatio="none">
      <polyline points={pts} fill="none" stroke={up ? "var(--green)" : "var(--red)"} strokeWidth="1.4" vectorEffect="non-scaling-stroke" strokeLinejoin="round" />
    </svg>
  );
}

function MiniBoard({ icon, title, coins, kind }) {
  return (
    <div className="crypto-mini">
      <div className="crypto-mini-h">{icon} {title}</div>
      {coins.length === 0 ? <div className="coach-empty">—</div> : coins.map((c) => (
        <div key={c.id} className="crypto-mini-row">
          <span className="crypto-mini-sym">{c.symbol}</span>
          {kind === "trend" ? <span className="crypto-mini-name">{c.name}</span>
            : <><span className="crypto-mini-price num">{usd(c.price)}</span>
                <span className={`crypto-mini-chg num ${chgCls(c.change_24h)}`}>{chg(c.change_24h)}</span></>}
        </div>
      ))}
    </div>
  );
}

export function CryptoView() {
  const [markets, setMarkets] = useState(null);
  const [trending, setTrending] = useState(null);
  const [structure, setStructure] = useState(null);
  const [tab, setTab] = useState("structure");
  useEffect(() => {
    fetchCryptoMarkets(40).then(setMarkets).catch(() => setMarkets({ markets: [], error: "unavailable" }));
    fetchCryptoTrending().then((d) => setTrending(d.trending || [])).catch(() => setTrending([]));
    fetchCryptoStructure().then(setStructure)
      .catch(() => setStructure({ available: false, note: "Positioning data is temporarily unavailable." }));
  }, []);

  const rows = markets?.markets || [];
  const pulse = useMemo(() => {
    const withChg = rows.filter((c) => c.change_24h != null);
    if (!withChg.length) return null;
    const up = withChg.filter((c) => c.change_24h > 0).length;
    const down = withChg.filter((c) => c.change_24h < 0).length;
    const avg = withChg.reduce((a, c) => a + c.change_24h, 0) / withChg.length;
    const ratio = up / (up + down || 1);
    const tone = ratio >= 0.6 ? "risk_on" : ratio <= 0.4 ? "risk_off" : "mixed";
    const find = (s) => rows.find((c) => c.symbol === s);
    return { up, down, n: withChg.length, avg, tone, btc: find("BTC"), eth: find("ETH") };
  }, [rows]);

  const gainers = useMemo(() => [...rows].filter((c) => c.change_24h != null).sort((a, b) => b.change_24h - a.change_24h).slice(0, 4), [rows]);
  const losers = useMemo(() => [...rows].filter((c) => c.change_24h != null).sort((a, b) => a.change_24h - b.change_24h).slice(0, 4), [rows]);

  return (
    <div>
      <div className="page-head">
        <div>
          <h1 className="page-title">Crypto</h1>
          <div className="page-sub">
            Who is positioned which way, what it costs them to stay there, and whether money is
            entering the system. Prices are the second question, not the first.
          </div>
        </div>
        <div className="sm-filter">
          <button className={tab === "structure" ? "on" : ""} onClick={() => setTab("structure")}>Structure</button>
          <button className={tab === "prices" ? "on" : ""} onClick={() => setTab("prices")}>Prices</button>
        </div>
      </div>

      {tab === "structure" && <Positioning d={structure} />}

      {tab !== "prices" ? null
        : markets === null ? <div className="skel" style={{ width: "50%", marginTop: 14, height: 90 }} />
        : markets.error || !rows.length ? (
          <div className="empty" style={{ marginTop: 14 }}>Crypto data is temporarily unavailable. It's live from CoinGecko and will return shortly — we never show a stale or fabricated price.</div>
        ) : (
          <>
            {pulse && (
              <div className="soc-pulse crypto-pulse">
                <div className="soc-pulse-l">
                  <div className="pulse-kicker"><span className="live-dot" /> Crypto Market Pulse</div>
                  <div className={`pulse-tone ${pulse.tone}`} style={{ fontSize: 26, marginTop: 6 }}>{TONE[pulse.tone]}</div>
                  <div className="soc-pulse-sub">{pulse.up} of {pulse.n} top coins up over 24h · avg move {chg(pulse.avg)}</div>
                </div>
                <div className="soc-stats">
                  {pulse.btc && <div className="soc-stat"><b className={chgCls(pulse.btc.change_24h)}>{chg(pulse.btc.change_24h)}</b><span>BTC 24h</span></div>}
                  {pulse.eth && <div className="soc-stat"><b className={chgCls(pulse.eth.change_24h)}>{chg(pulse.eth.change_24h)}</b><span>ETH 24h</span></div>}
                  <div className="soc-stat"><b className="pos-pos">{pulse.up}</b><span>advancing</span></div>
                  <div className="soc-stat"><b className="pos-neg">{pulse.down}</b><span>declining</span></div>
                </div>
              </div>
            )}

            <div className="crypto-boards">
              <MiniBoard icon="📈" title="Top gainers (24h)" coins={gainers} />
              <MiniBoard icon="📉" title="Top losers (24h)" coins={losers} />
              <MiniBoard icon="🔥" title="Trending in search" coins={(trending || []).slice(0, 5)} kind="trend" />
            </div>

            <div className="sec" style={{ marginTop: 14, padding: "8px 6px" }}>
              <div className="coin-row coin-head">
                <span>#</span><span>Coin</span><span className="col-r">Price</span><span className="col-r">24h</span>
                <span className="col-r col-hide">7d</span><span className="col-c col-hide">7-day</span><span className="col-r">Market cap</span>
              </div>
              {rows.map((c) => (
                <div key={c.id} className="coin-row">
                  <span className="coin-rank">{c.rank ?? "—"}</span>
                  <span className="coin-id">
                    <span className="coin-sym">{c.symbol}</span>
                    <span className="coin-name">{c.name}</span>
                    {c.risk.map((r) => <span key={r} className="chip flag-chip coin-risk">{RISK[r] || r}</span>)}
                  </span>
                  <span className="col-r num coin-price">{usd(c.price)}</span>
                  <span className={`col-r num ${chgCls(c.change_24h)}`}>{chg(c.change_24h)}</span>
                  <span className={`col-r col-hide num ${chgCls(c.change_7d)}`}>{chg(c.change_7d)}</span>
                  <span className="col-c col-hide"><Spark data={c.sparkline} up={(c.change_7d ?? c.change_24h ?? 0) >= 0} /></span>
                  <span className="col-r num coin-cap">{cap(c.market_cap)}</span>
                </div>
              ))}
            </div>
          </>
        )}

      <div className="disc" style={{ marginTop: 16 }}>
        Data: CoinGecko (prices, moves, market cap, volume, search-trending) and Binance's public
        futures endpoints (funding, open interest, account positioning) — both free and keyless.
        Still not connected: on-chain flows, whale activity, liquidation cascades and ETF flows,
        which need paid feeds. We show what's real and never fabricate the rest. Crypto assets are
        highly volatile and can lose all value. Not investment advice.
      </div>
    </div>
  );
}
