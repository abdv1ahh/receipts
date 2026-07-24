// Event & Macro Intelligence (Milestone 4): the forward calendar. Upcoming EARNINGS (with consensus
// EPS + cross-plane flags when the name also has a smart-money signal or an attention spike) and US
// MACRO releases (each with a deterministic, educational read on which sectors/assets it tends to move).
// "What's coming" to complement the brief's "what changed." Never advice.
import { useEffect, useState } from "react";
import { fetchEvents } from "./api";

const KIND_LABEL = { fomc: "FOMC", cpi: "CPI", jobs: "Jobs", gdp: "GDP", pce: "PCE", retail: "Retail", ppi: "PPI", macro: "Macro", earnings: "Earnings" };
const dayLabel = (iso) => {
  const d = new Date(iso + "T00:00:00");
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const diff = Math.round((d - today) / 86400000);
  const wd = d.toLocaleDateString(undefined, { weekday: "long", month: "short", day: "numeric" });
  return diff === 0 ? `Today · ${wd}` : diff === 1 ? `Tomorrow · ${wd}` : wd;
};

function CrossPlane({ flags }) {
  if (!flags?.length) return null;
  return flags.map((f) => (
    <span key={f} className={`xp xp-${f}`}>{f === "smart_money" ? "⚡ smart money" : "🔥 attention"}</span>
  ));
}

function EventRow({ e, onOpenSymbol }) {
  const imp = `imp-${e.importance}`;
  if (e.scope === "macro") {
    return (
      <div className="ev-row">
        <span className={`ev-kind ${imp}`}>{KIND_LABEL[e.kind] || "Macro"}</span>
        <div className="ev-body">
          <div className="ev-title">{e.title}</div>
          <div className="ev-why"><b>{e.what}</b> {e.moves}</div>
        </div>
      </div>
    );
  }
  const eps = e.meta?.eps_forecast;
  return (
    <div className="ev-row">
      <span className={`ev-kind ${imp}`}>Earnings</span>
      <div className="ev-body">
        <div className="ev-title">
          <button className="tkr" onClick={() => onOpenSymbol(e.symbol)}>{e.symbol}</button>
          <span className="ev-name">{e.title.replace(/ earnings$/, "")}</span>
          {e.time && <span className="ev-time">{e.time}</span>}
          <CrossPlane flags={e.cross_plane} />
        </div>
        <div className="ev-why">
          {eps ? <>consensus EPS <b>{eps}</b>{e.meta?.last_year_eps ? <> · yr-ago {e.meta.last_year_eps}</> : null}</> : "reports results"}
          {e.attention_velocity ? <> · attention {e.attention_velocity}× usual</> : null}
        </div>
      </div>
    </div>
  );
}

function SourceStrip({ sources }) {
  if (!sources) return null;
  return (
    <div className="src-strip">
      {sources.map((s) => <span key={s.key} className={`src-dot ${s.state === "connected" ? "on" : "off"}`}><i /> {s.label}</span>)}
    </div>
  );
}

export function EventsView({ onOpenSymbol }) {
  const [data, setData] = useState(null);
  const [days, setDays] = useState(10);
  const [err, setErr] = useState(null);
  useEffect(() => { setData(null); fetchEvents(days).then(setData).catch((e) => setErr(String(e))); }, [days]);

  return (
    <div>
      <div className="page-head">
        <div>
          <h1 className="page-title">Events &amp; Macro Calendar</h1>
          <div className="page-sub">What's coming — upcoming earnings and US macro releases, with why each one matters.</div>
        </div>
        <div className="seg">
          {[7, 10, 21].map((d) => <button key={d} className={days === d ? "on" : ""} onClick={() => setDays(d)}>{d}d</button>)}
        </div>
      </div>
      {data && <SourceStrip sources={data.sources} />}
      {err && <div className="err">error: {err}</div>}
      {data === null ? (
        [...Array(4)].map((_, i) => <div key={i} className="ev-day"><div className="skel" style={{ width: `${50 - i * 6}%` }} /></div>)
      ) : data.calendar.length === 0 ? (
        <div className="empty">No scheduled events in this window yet. The calendar fills in as the worker pulls the earnings + macro feeds.</div>
      ) : (
        data.calendar.map((day) => (
          <div key={day.date} className="ev-day">
            <div className="ev-day-head">{dayLabel(day.date)} <span className="ev-count">{day.events.length}</span></div>
            {day.events.slice(0, 24).map((e) => <EventRow key={e.id} e={e} onOpenSymbol={onOpenSymbol} />)}
            {day.events.length > 24 && <div className="ev-more">+{day.events.length - 24} more</div>}
          </div>
        ))
      )}
      <div className="disc" style={{ marginTop: 16 }}>Earnings dates and consensus estimates are third-party scheduled data and can change. Macro reads describe typical transmission channels — educational, not advice.</div>
    </div>
  );
}
