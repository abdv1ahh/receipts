// Presentational components. Staleness is a first-class visual system: never render a
// signal figure without a <Freshness> beside it.

export function Freshness({ iso, quarterly }) {
  if (!iso) return <span className="fresh s">—</span>;
  const days = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 86400000));
  const cls = days < 14 ? "g" : days < 90 ? "a" : "s";
  let label;
  if (quarterly) label = `Quarterly · ${iso.slice(0, 10)}`;
  else if (days < 21) label = `${days}d ago`;
  else if (days < 90) label = `${Math.round(days / 7)}w ago`;
  else label = `${Math.round(days / 30)}mo ago`;
  return (
    <span className={`fresh ${quarterly ? "s" : cls}`} title={iso}>
      {label}
    </span>
  );
}

export function Bucket({ bucket }) {
  return (
    <div>
      <span className={`bucket ${bucket}`}>{bucket.toUpperCase()}</span>
    </div>
  );
}

export function Backtested({ cal }) {
  // cal = calibration for one bucket at one horizon: {episodes, sufficient, hit_rate, ci95}
  if (!cal || cal.episodes === 0)
    return <span className="bt bt-pending" title="No resolved episodes yet">Backtested · pending</span>;
  if (!cal.sufficient)
    return (
      <span className="bt bt-insuff" title={`${cal.episodes} resolved episodes (min ${cal.min_episodes_for_display})`}>
        Backtested · insufficient sample (n={cal.episodes})
      </span>
    );
  const pct = Math.round(cal.hit_rate * 100);
  const ci = cal.ci95 ? cal.ci95.map((x) => Math.round(x * 100) + "%").join("–") : "";
  return (
    <span className="bt bt-ok" title={`Wilson 95% CI ${ci}`}>
      Backtested · {pct}% hit · n={cal.episodes}
    </span>
  );
}

export function Classes({ classes }) {
  return (
    <div className="chips">
      {classes.map((c) => (
        <span key={c} className={`chip ${c}`}>
          {c.replace(/_/g, " ")}
        </span>
      ))}
    </div>
  );
}

export function StatusStrip({ feeds }) {
  if (!feeds) return null;
  return (
    <div className="strip">
      {feeds.feeds.map((f) => (
        <div className="feed" key={f.source}>
          <div className="src">{f.source}</div>
          <div className="metrics">
            <div className="metric">
              <b className="num">{f.records_total.toLocaleString()}</b>
              <span>records</span>
            </div>
            <div className={`metric ${f.rejects_total ? "rej-n" : "rej-0"}`}>
              <b className="num">{f.rejects_total}</b>
              <span>rejects</span>
            </div>
            <div className="metric">
              <b><Freshness iso={f.freshest_record_knowable} /></b>
              <span>freshest</span>
            </div>
          </div>
        </div>
      ))}
      <div className="feed">
        <div className="src">resolution</div>
        <div className="metrics">
          <div className="metric">
            <b className="num">{feeds.unresolved.fund_holdings.toLocaleString()}</b>
            <span>13F unresolved</span>
          </div>
        </div>
      </div>
    </div>
  );
}

export function Disclaimer() {
  return (
    <div className="disclaimer">
      TradeOSS is an analytics and education platform. Nothing here is investment advice.
      Signals describe disclosed activity by third parties, with delays as labeled.
      Confidence buckets show a backtested hit rate wherever the resolved-episode sample is
      sufficient, and read “insufficient sample” otherwise. Higher-conviction buckets remain
      sample-limited by historical price coverage (free-tier data); those rates are pending, not claimed.
    </div>
  );
}

export function ClusterTable({ clusters, onSelect, pulseKey, calibration, horizon }) {
  const calFor = (bucket) => calibration?.per_bucket?.[bucket]?.[String(horizon)];
  return (
    <table className="clusters">
      <thead>
        <tr>
          <th>Ticker</th>
          <th>Score</th>
          <th>Confidence</th>
          <th>Backtested ({horizon}d)</th>
          <th>Voices</th>
          <th>Sources</th>
          <th>Freshest input</th>
        </tr>
      </thead>
      <tbody>
        {clusters.map((c, i) => (
          <tr
            className="row"
            key={c.issuer_entity}
            style={{ animationDelay: `${i * 35}ms` }}
            onClick={() => onSelect(c.issuer_entity)}
          >
            <td>
              <div className="sym">{c.symbol || "—"}</div>
              <div className="name">{c.name}</div>
            </td>
            <td>
              <span className="score num pulse" key={`${pulseKey}-${c.issuer_entity}`}>
                {c.score.toFixed(2)}
              </span>
            </td>
            <td>
              <Bucket bucket={c.confidence_bucket} />
            </td>
            <td>
              <Backtested cal={calFor(c.confidence_bucket)} />
            </td>
            <td className="num">{c.voices}</td>
            <td>
              <Classes classes={c.source_classes} />
            </td>
            <td>
              <Freshness iso={c.freshest_contributing_knowable} />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function ClusterDetail({ detail, onBack, calibration, horizon, explanation, onOpenLibrary }) {
  const inp = detail.inputs || {};
  const contributions = inp.contributions || [];
  const context = inp.context || [];
  const cal = calibration?.per_bucket?.[detail.confidence_bucket]?.[String(horizon)];
  return (
    <div className="detail">
      <button className="back" onClick={onBack}>
        ← back to clusters
      </button>
      <h2>
        {detail.symbol || "—"} · {detail.name}
      </h2>
      <div className="meta">
        CIK {detail.cik} · score <b className="num">{detail.score.toFixed(2)}</b> ·{" "}
        <span className={`bucket ${detail.confidence_bucket}`}>
          {detail.confidence_bucket.toUpperCase()}
        </span>{" "}
        · {detail.voices} voices · definition v{detail.definition_version} · as of{" "}
        {detail.as_of.slice(0, 19).replace("T", " ")} UTC
      </div>
      <div className="calib">{detail.calibration}</div>
      <div style={{ marginTop: 8 }}>
        <Backtested cal={cal} /> <span className="name">(base rate for the {horizon}-day horizon)</span>
      </div>

      {detail.library_links && detail.library_links.length > 0 && onOpenLibrary && (
        <div style={{ marginTop: 8 }}>
          <span className="name">Understand this pattern: </span>
          {detail.library_links.map((l, i) => (
            <span key={l.slug}>
              <button className="linkish" onClick={() => onOpenLibrary(l.slug)}>{l.title}</button>
              {i < detail.library_links.length - 1 ? <span className="name"> · </span> : null}
            </span>
          ))}
        </div>
      )}

      {explanation && (
        <div className="explain">
          <div className="section">Plain-language explanation</div>
          <p className="explain-prose">{explanation.prose}</p>
          <div className="name">
            generated by {explanation.model_id}
            {explanation.from_cache ? " · cached" : ""}
            {explanation.used_template ? " · guard fallback" : ""}
          </div>
        </div>
      )}
      <div style={{ marginTop: 8 }}>
        Liquidity floor:{" "}
        {inp.liquidity_floor?.ok ? (
          <span className="floor-ok">above floor ({inp.liquidity_floor.basis})</span>
        ) : (
          <span className="floor-no">below floor — excluded from default feed</span>
        )}
      </div>

      <div className="section">Contributing events (scored)</div>
      <table>
        <thead>
          <tr>
            <th>Class</th>
            <th>Subtype</th>
            <th>Voice</th>
            <th>Knowable</th>
            <th>Magnitude</th>
            <th>Decayed weight</th>
          </tr>
        </thead>
        <tbody>
          {contributions.map((e, i) => (
            <tr key={i}>
              <td>
                <span className={`chip ${e.source_class}`}>{e.source_class.replace(/_/g, " ")}</span>
              </td>
              <td>{e.subtype}</td>
              <td className="num">{e.voice}</td>
              <td>
                <Freshness iso={e.knowable_time} />
              </td>
              <td className="num">{e.magnitude != null ? Number(e.magnitude).toLocaleString() : "—"}</td>
              <td className="num">{Number(e.decayed_weight).toFixed(3)}</td>
            </tr>
          ))}
        </tbody>
      </table>

      {context.length > 0 && (
        <>
          <div className="section">Context (shown, not scored)</div>
          <table>
            <thead>
              <tr>
                <th>Class</th>
                <th>Subtype</th>
                <th>Knowable</th>
              </tr>
            </thead>
            <tbody>
              {context.map((e, i) => (
                <tr key={i}>
                  <td>
                    <span className={`chip ${e.source_class}`}>
                      {e.source_class.replace(/_/g, " ")}
                    </span>
                  </td>
                  <td>{e.subtype}</td>
                  <td>
                    <Freshness
                      iso={e.knowable_time}
                      quarterly={e.source_class === "institutional_holding"}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
      <Disclaimer />
    </div>
  );
}

export function Methodology({ calibration, definitions, onBack }) {
  const horizons = calibration?.horizons || [30, 90, 180];
  const buckets = ["high", "medium", "low"];
  const conv = calibration?.conventions || {};
  return (
    <div className="detail">
      <button className="back" onClick={onBack}>
        ← back to dashboard
      </button>
      <h2>Methodology</h2>
      <div className="meta">The definition is public. Numbers here are computed from real filings and prices — nothing is illustrative.</div>

      <div className="section">Backtested calibration — hit rate (excess vs SPY &gt; 0) by confidence &amp; horizon</div>
      <table>
        <thead>
          <tr>
            <th>Bucket</th>
            {horizons.map((h) => (
              <th key={h}>{h}d</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {buckets.map((b) => (
            <tr key={b}>
              <td>
                <span className={`bucket ${b}`}>{b.toUpperCase()}</span>
              </td>
              {horizons.map((h) => (
                <td key={h}>
                  <Backtested cal={calibration?.per_bucket?.[b]?.[String(h)]} />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>

      <div className="section">Sample &amp; exclusions (honest coverage)</div>
      <div className="meta">
        {calibration ? (
          <>
            {calibration.episodes_total} episodes total · {calibration.episodes_priced} priced ·{" "}
            <span className="floor-no">{calibration.episodes_excluded_missing_prices} excluded (no price history)</span> ·{" "}
            {calibration.episodes_too_recent_to_enter} too recent to enter ·{" "}
            {calibration.episodes_excluded_no_symbol} unresolved ticker · raw clusters {calibration.raw_cluster_count}
            <div style={{ marginTop: 4 }}>
              horizons still open: {horizons.map((h) => `${h}d ${calibration.horizons_open?.[String(h)] ?? 0}`).join("   ")}
            </div>
          </>
        ) : "loading…"}
        <div style={{ marginTop: 6 }}>Price data: {calibration?.price_grade}</div>
      </div>

      <div className="section">Conventions</div>
      <table>
        <tbody>
          {Object.entries(conv).map(([k, v]) => (
            <tr key={k}>
              <td className="name" style={{ width: 220 }}>{k.replace(/_/g, " ")}</td>
              <td>{String(v)}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <div className="section">Signal definitions (version history)</div>
      <table>
        <thead>
          <tr>
            <th>Version</th>
            <th>Code hash</th>
            <th>Changelog</th>
          </tr>
        </thead>
        <tbody>
          {(definitions?.definitions || []).map((d) => (
            <tr key={d.version}>
              <td className="num">v{d.version}</td>
              <td className="num">{d.code_hash.slice(0, 12)}</td>
              <td style={{ fontSize: "12px" }}>{d.changelog}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <div className="disclaimer" style={{ marginTop: 20 }}>
        {calibration?.live_commitment}
      </div>
      <Disclaimer />
    </div>
  );
}
