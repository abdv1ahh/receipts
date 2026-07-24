// Crypto — real market data from CoinGecko (free, keyless): prices, 1h/24h/7d moves, market cap,
// volume, 7-day sparklines, and what's trending in search — with a breadth-based market pulse and
// unmissable risk labels. Honest by construction: on a fetch failure it says "temporarily unavailable"
// rather than showing a stale/fabricated price, and it is explicit that on-chain flows / whales /
// funding / OI / liquidations / ETF flows need specialized feeds that aren't wired. Never advice.
import { useEffect, useMemo, useState } from "react";
import { fetchCryptoMarkets, fetchCryptoTrending } from "./api";
import { Icon } from "./icons.jsx";

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
  useEffect(() => {
    fetchCryptoMarkets(40).then(setMarkets).catch(() => setMarkets({ markets: [], error: "unavailable" }));
    fetchCryptoTrending().then((d) => setTrending(d.trending || [])).catch(() => setTrending([]));
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
          <div className="page-sub">Live market data and search attention from CoinGecko. Crypto is highly volatile — this is market data, never advice.</div>
        </div>
      </div>

      {markets === null ? <div className="skel" style={{ width: "50%", marginTop: 14, height: 90 }} />
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
        Data: CoinGecko (prices, moves, market cap, volume, search-trending). On-chain flows, whale activity,
        funding &amp; open interest, liquidations, and ETF flows need specialized data feeds that aren't connected yet —
        we show what's real and never fabricate the rest. Crypto assets are highly volatile and can lose all value. Not investment advice.
      </div>
    </div>
  );
}
