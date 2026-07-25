// The Calendar — a calendar.
//
// It previously rendered ten days of earnings as one continuous scroll roughly ten thousand pixels
// tall, grouped by day heading. That is a list. A list cannot answer the question people open a
// calendar to ask, which is "what does my week look like" — you cannot see shape in a column.
//
// So: month, week and day views over the same data, with importance encoded as weight rather than
// hidden in a chip, and a filter that actually reduces what you see.
import { useEffect, useMemo, useState } from "react";
import { fetchEvents } from "./api";
import { Icon } from "./icons.jsx";
import { EmptyState, LoadError } from "./shell.jsx";

const DAY_MS = 86400000;
const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const IMPORTANCE = { high: 3, medium: 2, low: 1 };

const iso = (d) => d.toISOString().slice(0, 10);
const parse = (s) => new Date(`${s}T00:00:00`);
const monthLabel = (d) => d.toLocaleDateString(undefined, { month: "long", year: "numeric" });

/** Monday-first week index, because a trading week is not Sunday-first anywhere this product runs. */
const weekday = (d) => (d.getDay() + 6) % 7;

function startOfWeek(d) {
  const out = new Date(d);
  out.setDate(out.getDate() - weekday(out));
  out.setHours(0, 0, 0, 0);
  return out;
}

function monthGrid(anchor) {
  const first = new Date(anchor.getFullYear(), anchor.getMonth(), 1);
  const start = startOfWeek(first);
  return Array.from({ length: 42 }, (_, i) => new Date(start.getTime() + i * DAY_MS));
}

function EventPill({ e, onOpenSymbol }) {
  const imp = e.importance || "low";
  const label = e.scope === "macro" ? e.title : `${e.symbol || e.title}`;
  return (
    <button className={`cal-pill imp-${imp}`} title={`${e.title}${e.time ? ` · ${e.time}` : ""}`}
            onClick={() => e.symbol && onOpenSymbol(e.symbol)}>
      {e.scope === "macro" ? <Icon name="activity" size={10} /> : <Icon name="signal" size={10} />}
      <span>{label}</span>
      {(e.cross_plane || []).includes("smart_money") && <em title="a live smart-money signal here">⚡</em>}
    </button>
  );
}

function MonthView({ anchor, byDay, onOpenSymbol, onPickDay }) {
  const cells = monthGrid(anchor);
  const thisMonth = anchor.getMonth();
  const today = iso(new Date());
  return (
    <div className="cal-month">
      {WEEKDAYS.map((w) => <div key={w} className="cal-wd">{w}</div>)}
      {cells.map((d) => {
        const key = iso(d);
        const events = byDay[key] || [];
        return (
          <button key={key} onClick={() => onPickDay(d)}
                  className={`cal-cell ${d.getMonth() === thisMonth ? "" : "muted"} ${key === today ? "today" : ""}`}>
            <span className="cal-daynum">{d.getDate()}</span>
            <span className="cal-cell-events">
              {events.slice(0, 3).map((e) => <EventPill key={e.id} e={e} onOpenSymbol={onOpenSymbol} />)}
              {events.length > 3 && <span className="cal-more">+{events.length - 3} more</span>}
            </span>
          </button>
        );
      })}
    </div>
  );
}

function WeekView({ anchor, byDay, onOpenSymbol }) {
  const start = startOfWeek(anchor);
  const days = Array.from({ length: 7 }, (_, i) => new Date(start.getTime() + i * DAY_MS));
  const today = iso(new Date());
  return (
    <div className="cal-week">
      {days.map((d) => {
        const key = iso(d);
        const events = byDay[key] || [];
        return (
          <div key={key} className={`cal-wcol ${key === today ? "today" : ""}`}>
            <div className="cal-wcol-head">
              <b>{WEEKDAYS[weekday(d)]}</b>
              <span>{d.getDate()} {d.toLocaleDateString(undefined, { month: "short" })}</span>
            </div>
            {events.length === 0
              ? <div className="cal-wcol-empty">—</div>
              : events.map((e) => <EventPill key={e.id} e={e} onOpenSymbol={onOpenSymbol} />)}
          </div>
        );
      })}
    </div>
  );
}

function DayView({ anchor, byDay, onOpenSymbol }) {
  const events = byDay[iso(anchor)] || [];
  if (!events.length) {
    return <EmptyState title={`Nothing scheduled on ${anchor.toDateString()}`}>
      Quiet days are information too.
    </EmptyState>;
  }
  return (
    <div className="cal-day">
      {events.map((e) => (
        <div key={e.id} className={`cal-row imp-${e.importance || "low"}`}>
          <span className="cal-row-time">{e.time || "—"}</span>
          <span className={`radar-kind imp-${e.importance || "low"}`}>{e.kind || e.scope}</span>
          <span className="cal-row-body">
            <button className="cal-row-title" onClick={() => e.symbol && onOpenSymbol(e.symbol)}>
              {e.scope === "macro" ? e.title : `${e.symbol || ""} ${e.title}`.trim()}
            </button>
            {(e.what || e.moves) && <span className="cal-row-why">{e.moves || e.what}</span>}
            {/* Consensus and previous are what make a release readable before it lands. */}
            {e.meta && (e.meta.consensus || e.meta.previous) && (
              <span className="cal-row-meta">
                {e.meta.consensus?.trim() && <span>consensus <b>{e.meta.consensus}</b></span>}
                {e.meta.previous?.trim() && <span>previous <b>{e.meta.previous}</b></span>}
                {e.meta.actual?.trim() && <span>actual <b>{e.meta.actual}</b></span>}
              </span>
            )}
          </span>
          {(e.cross_plane || []).includes("smart_money") && <span className="radar-xp sm">⚡ smart money</span>}
          {(e.cross_plane || []).includes("attention") && <span className="radar-xp attn">🔥 attention</span>}
        </div>
      ))}
    </div>
  );
}

const VIEWS = ["month", "week", "day"];

export function CalendarView({ onOpenSymbol }) {
  const [d, setD] = useState(undefined);
  const [view, setView] = useState("month");
  const [anchor, setAnchor] = useState(() => new Date());
  const [minImportance, setMinImportance] = useState(1);

  const load = () => { setD(undefined); fetchEvents(45).then(setD).catch(() => setD(null)); };
  useEffect(load, []);

  // The API returns days; the views want a lookup, and each view wants the same filter applied.
  const byDay = useMemo(() => {
    const out = {};
    for (const day of d?.calendar || []) {
      const kept = (day.events || [])
        .filter((e) => (IMPORTANCE[e.importance] || 1) >= minImportance)
        .sort((a, b) => (IMPORTANCE[b.importance] || 1) - (IMPORTANCE[a.importance] || 1));
      if (kept.length) out[day.date] = kept;
    }
    return out;
  }, [d, minImportance]);

  const total = useMemo(() => Object.values(byDay).reduce((n, e) => n + e.length, 0), [byDay]);

  const shift = (dir) => {
    const next = new Date(anchor);
    if (view === "month") next.setMonth(next.getMonth() + dir);
    else if (view === "week") next.setDate(next.getDate() + dir * 7);
    else next.setDate(next.getDate() + dir);
    setAnchor(next);
  };

  if (d === null) return <LoadError what="the calendar" onRetry={load} />;

  return (
    <div>
      <div className="page-head">
        <div>
          <h1 className="page-title">Calendar</h1>
          <p className="page-sub">
            Earnings and macro releases, with what the market expects and what it last was.
          </p>
        </div>
        <div className="sm-filter">
          {VIEWS.map((v) => (
            <button key={v} className={view === v ? "on" : ""} onClick={() => setView(v)}>{v}</button>
          ))}
        </div>
      </div>

      <div className="cal-bar">
        <button className="act mini" onClick={() => shift(-1)} aria-label="previous">←</button>
        <button className="act mini" onClick={() => setAnchor(new Date())}>today</button>
        <button className="act mini" onClick={() => shift(1)} aria-label="next">→</button>
        <span className="cal-anchor">
          {view === "day" ? anchor.toDateString() : monthLabel(anchor)}
        </span>
        <span className="spacer" />
        <select value={minImportance} onChange={(e) => setMinImportance(Number(e.target.value))}
                className="rd-cat-filter">
          <option value={1}>everything</option>
          <option value={2}>medium and high</option>
          <option value={3}>high impact only</option>
        </select>
        <span className="name">{total} shown</span>
      </div>

      {d === undefined ? (
        <div className="skel" style={{ width: "100%", height: 320, marginTop: 14 }} />
      ) : view === "month" ? (
        <MonthView anchor={anchor} byDay={byDay} onOpenSymbol={onOpenSymbol}
                   onPickDay={(day) => { setAnchor(day); setView("day"); }} />
      ) : view === "week" ? (
        <WeekView anchor={anchor} byDay={byDay} onOpenSymbol={onOpenSymbol} />
      ) : (
        <DayView anchor={anchor} byDay={byDay} onOpenSymbol={onOpenSymbol} />
      )}

      <div className="disc" style={{ marginTop: 16 }}>
        Consensus and previous figures come from the source calendar where it publishes them; a
        blank means the source did not state one, never that it is zero.
      </div>
    </div>
  );
}
