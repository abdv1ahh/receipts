// How differently outlets frame the same event — and where coverage is thin.
//
// Both halves fall out of the spine's clustering for free, but the view is only MEANINGFUL because
// the feed list deliberately spans outlets in different countries. Before those were added this
// screen would have compared two CNBC feeds agreeing with each other, which is not two
// perspectives, and shipping it would have been a demo of a missing capability.
//
// The thin-coverage half is the more interesting one and carries a caveat it must not lose: a
// story only one outlet carries may be early, or simply outside what the connected feeds cover.
// Coverage breadth measures this product's reach at least as much as an event's significance.
import { useEffect, useState } from "react";
import { fetchNewsCoverage } from "./api";
import { Icon } from "./icons.jsx";
import { EmptyState, LoadError } from "./shell.jsx";

const outlet = (source) => (source || "").replace(/^rss\//, "").replace(/-/g, " ");

export function CoverageView() {
  const [d, setD] = useState(undefined);
  const load = () => { setD(undefined); fetchNewsCoverage(240).then(setD).catch(() => setD(null)); };
  useEffect(load, []);

  if (d === null) return <LoadError what="coverage comparison" onRetry={load} />;
  if (d === undefined) return <div className="skel" style={{ width: "60%", height: 80, marginTop: 14 }} />;

  return (
    <div>
      <div className="cov-head">
        <span className="pulse-kicker"><Icon name="layers" size={13} /> Coverage</span>
        <span className="name">{d.distinct_outlets} outlets connected</span>
      </div>

      {d.compared.length === 0 ? (
        <EmptyState title="No story is being carried by more than one outlet right now">
          Comparison needs the same event reported twice. With {d.distinct_outlets} outlets
          connected that happens for major stories, not routine ones.
        </EmptyState>
      ) : (
        d.compared.map((c) => (
          <div key={c.id} className="cov-story">
            <div className="cov-story-head">
              <b>{c.title}</b>
              <span className="spacer" />
              <span className="name">{c.category?.replace(/_/g, " ")}</span>
            </div>
            <div className="cov-frames">
              {c.reports.map((r, i) => (
                <a key={i} className="cov-frame" href={r.url} target="_blank" rel="noreferrer noopener">
                  <span className="cov-outlet">
                    {outlet(r.source)}
                    {r.geo?.length > 0 && <em>{r.geo[0]}</em>}
                  </span>
                  <span className="cov-title">{r.title}</span>
                </a>
              ))}
            </div>
          </div>
        ))
      )}

      {d.thin_coverage.length > 0 && (
        <div className="sec" style={{ marginTop: 16 }}>
          <div className="sec-head">
            <div className="sec-title">Carried by one outlet only</div>
            <span className="lg-misses-why">early, or overlooked — the view cannot tell you which</span>
          </div>
          {d.thin_coverage.map((t) => (
            <a key={t.id} className="cov-thin" href={t.url} target="_blank" rel="noreferrer noopener">
              <span className="cov-nov">{Math.round((t.novelty || 0) * 100)}</span>
              <span className="cov-thin-title">{t.title}</span>
              <span className="spacer" />
              <span className="cov-outlet">{outlet(t.only_source)}</span>
            </a>
          ))}
        </div>
      )}

      <div className="disc" style={{ marginTop: 14 }}>{d.note}</div>
    </div>
  );
}
