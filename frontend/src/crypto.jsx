// Slice I: real crypto market data from CoinGecko (free, keyless). Prices, 24h moves, volume, and
// search-trending coins, with unmissable risk labels. Market data + attention, never advice — and an
// honest "temporarily unavailable" on upstream failure rather than a stale/fabricated price.
import { useEffect, useState } from "react";
import { fetchCryptoMarkets, fetchCryptoTrending } from "./api";

const RISK = { high_volatility: "⚡ volatile", microcap: "microcap", thin_volume: "thin volume" };
const usd = (v) => (v == null ? "—" : v >= 1 ? `$${v.toLocaleString(undefined, { maximumFractionDigits: 2 })}` : `$${v.toPrecision(3)}`);
const cap = (v) => (v == null ? "—" : v >= 1e9 ? `$${(v / 1e9).toFixed(1)}B` : v >= 1e6 ? `$${(v / 1e6).toFixed(1)}M` : `$${v.toLocaleString()}`);
const chgCls = (v) => (v == null ? "" : v >= 0 ? "pos-pos" : "pos-neg");

export function CryptoView() {
  const [markets, setMarkets] = useState(null);
  const [trending, setTrending] = useState(null);
  useEffect(() => {
    fetchCryptoMarkets(25).then(setMarkets).catch(() => setMarkets({ markets: [], error: "unavailable" }));
    fetchCryptoTrending().then((d) => setTrending(d.trending || [])).catch(() => setTrending([]));
  }, []);

  return (
    <div className="detail">
      <h2>₿ Crypto</h2>
      <div className="meta">Live market data from CoinGecko — prices, 24-hour moves, and what's trending in search. Crypto is high-risk and volatile; this is market data and attention, never advice.</div>

      {trending && trending.length > 0 && (
        <div className="board" style={{ marginTop: 12 }}>
          <div className="board-title">🔥 Trending in search (24h)</div>
          <div className="trending-coins">
            {trending.map((c) => <span key={c.id || c.symbol} className="coin-chip">{c.symbol}<span className="name"> {c.name}</span></span>)}
          </div>
        </div>
      )}

      {markets === null ? <div className="skel" style={{ width: "50%", marginTop: 14 }} />
        : markets.error || !markets.markets?.length ? <div className="empty" style={{ marginTop: 14 }}>Crypto data is temporarily unavailable. It's live from CoinGecko and will return shortly.</div>
          : (
            <table className="clusters" style={{ marginTop: 12 }}>
              <thead><tr><th>#</th><th>Coin</th><th>Price</th><th>24h</th><th>Market cap</th><th>Volume</th><th>Risk</th></tr></thead>
              <tbody>
                {markets.markets.map((c) => (
                  <tr key={c.id}>
                    <td className="board-rank">{c.rank ?? "—"}</td>
                    <td><span className="sym">{c.symbol}</span><div className="name">{c.name}</div></td>
                    <td className="num">{usd(c.price)}</td>
                    <td className={`num ${chgCls(c.change_24h)}`}>{c.change_24h == null ? "—" : `${c.change_24h >= 0 ? "+" : ""}${c.change_24h.toFixed(1)}%`}</td>
                    <td className="num">{cap(c.market_cap)}</td>
                    <td className="num">{cap(c.volume)}</td>
                    <td>{c.risk.map((r) => <span key={r} className="chip flag-chip" style={{ marginRight: 4 }}>{RISK[r] || r}</span>)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
      <div className="disc" style={{ marginTop: 16 }}>Data: CoinGecko. Prices are for information only — not investment advice. Crypto assets are highly volatile and can lose all value.</div>
    </div>
  );
}
