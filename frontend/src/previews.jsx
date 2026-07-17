// Roadmap preview surfaces (Decision 8). These render ONLY bundled static fixtures — they
// never call /api and never touch the database. The banner + diagonal watermark are built into
// the layout so a screenshot can never be mistaken for the live product.
import cryptoData from "./previews/fixtures/crypto.json";
import optionsData from "./previews/fixtures/options.json";

const BANNER = "PREVIEW — illustrative design, not live data. Options and on-chain feeds arrive post-funding.";

function PreviewLayout({ title, note, children, onBack }) {
  return (
    <div className="preview">
      <div className="preview-banner">{BANNER}</div>
      <div className="preview-body">
        <div className="preview-watermark" aria-hidden="true">PREVIEW · NOT LIVE DATA</div>
        <button className="back" onClick={onBack}>← back to dashboard</button>
        <h2>{title}</h2>
        <div className="meta">{note}</div>
        {children}
      </div>
    </div>
  );
}

export function OptionsPreview({ onBack }) {
  return (
    <PreviewLayout title="Options flow — roadmap preview" note={optionsData.note} onBack={onBack}>
      <table className="clusters">
        <thead><tr><th>Ticker</th><th>Pattern</th><th>Premium</th><th>Call/Put</th><th>Unusual</th><th>Confidence</th></tr></thead>
        <tbody>
          {optionsData.clusters.map((c, i) => (
            <tr key={i}>
              <td><div className="sym">{c.symbol}</div><div className="name">{c.name}</div></td>
              <td>{c.pattern}</td>
              <td className="num">${c.premium_usd.toLocaleString()}</td>
              <td className="num">{c.call_put_ratio}</td>
              <td className="num">{c.unusual_score}</td>
              <td><span className={`bucket ${c.confidence}`}>{c.confidence.toUpperCase()}</span></td>
            </tr>
          ))}
        </tbody>
      </table>
    </PreviewLayout>
  );
}

export function CryptoPreview({ onBack }) {
  return (
    <PreviewLayout title="On-chain smart money — roadmap preview" note={cryptoData.note} onBack={onBack}>
      <table className="clusters">
        <thead><tr><th>Asset</th><th>Pattern</th><th>Wallets</th><th>Net inflow</th><th>Cohort</th><th>Confidence</th></tr></thead>
        <tbody>
          {cryptoData.clusters.map((c, i) => (
            <tr key={i}>
              <td><div className="sym">{c.asset}</div><div className="name">{c.name}</div></td>
              <td>{c.pattern}</td>
              <td className="num">{c.wallets}</td>
              <td className="num">${c.net_inflow_usd.toLocaleString()}</td>
              <td className="name">{c.cohort}</td>
              <td><span className={`bucket ${c.confidence}`}>{c.confidence.toUpperCase()}</span></td>
            </tr>
          ))}
        </tbody>
      </table>
    </PreviewLayout>
  );
}
