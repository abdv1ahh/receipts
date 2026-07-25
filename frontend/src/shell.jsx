// Shell primitives every surface depends on: routing, failure containment, and the one honest
// way to render a feature that is thin because a data source is missing.
//
// Three problems this file exists to solve, all found in the Phase 0 audit:
//   * navigation lived in useState, so nothing had a URL — no deep links, no back button, and
//     nothing a marketing site could ever index;
//   * a render-time throw anywhere unmounted the whole app and left a blank page;
//   * a missing API key surfaced as the string "N/A" with no explanation and no way forward.
import { Component, useCallback, useEffect, useState } from "react";
import { Icon } from "./icons.jsx";

// ------------------------------------------------------------------ routing

// Deliberately not react-router: this app needs a path, a query string, and a back button, and
// that is ~40 lines over the History API. Revisit if nested or lazy routes ever appear.
export function useRoute() {
  const read = () => ({
    path: window.location.pathname.replace(/^\/+|\/+$/g, ""),
    query: new URLSearchParams(window.location.search),
  });
  const [route, setRoute] = useState(read);

  useEffect(() => {
    const onPop = () => setRoute(read());
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const go = useCallback((path, query) => {
    const qs = query ? `?${new URLSearchParams(query)}` : "";
    const url = `/${String(path).replace(/^\/+/, "")}${qs}`;
    if (url !== window.location.pathname + window.location.search) {
      window.history.pushState({}, "", url);
    }
    setRoute(read());
    window.scrollTo(0, 0);
  }, []);

  // Replace without adding a history entry — for redirects and canonicalisation.
  const replace = useCallback((path, query) => {
    const qs = query ? `?${new URLSearchParams(query)}` : "";
    window.history.replaceState({}, "", `/${String(path).replace(/^\/+/, "")}${qs}`);
    setRoute(read());
  }, []);

  return { ...route, go, replace };
}

// ------------------------------------------------------------------ failure containment

export class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { err: null };
  }

  static getDerivedStateFromError(err) {
    return { err };
  }

  componentDidCatch(err, info) {
    // The console is where a developer looks; the user gets the panel below, not a stack trace.
    console.error(`[${this.props.surface || "app"}] render failed`, err, info);
  }

  render() {
    if (!this.state.err) return this.props.children;
    return (
      <div className="failbox" role="alert">
        <div className="failbox-head">
          <Icon name="alert" size={16} /> This section could not be displayed
        </div>
        <p className="failbox-body">
          The rest of the page still works. If it keeps happening, the details are in the browser
          console.
        </p>
        <button className="act" onClick={() => this.setState({ err: null })}>try again</button>
      </div>
    );
  }
}

// ------------------------------------------------------------------ honest empty + failure states

/** A panel whose data request failed. Says what failed, in words, and offers a retry — never a
 *  raw Error string, and never a silent blank. */
export function LoadError({ what, onRetry }) {
  return (
    <div className="failbox" role="alert">
      <div className="failbox-head"><Icon name="alert" size={16} /> Couldn’t load {what}</div>
      <p className="failbox-body">
        The request didn’t come back. This is usually temporary.
      </p>
      {onRetry && <button className="act" onClick={onRetry}>retry</button>}
    </div>
  );
}

/** A panel with nothing in it yet. Explains what will appear here and why it is empty — the
 *  brief's rule that an empty state must teach, not just occupy space. */
export function EmptyState({ title, children, action }) {
  return (
    <div className="emptybox">
      <div className="emptybox-head">{title}</div>
      <div className="emptybox-body">{children}</div>
      {action}
    </div>
  );
}

// ------------------------------------------------------------------ the source gate

const STATE_LABEL = { connected: "connected", needs_key: "needs a free key", unavailable: "no free access" };

/**
 * Rendered wherever a feature is thin because a source is not connected. It never blocks: it says
 * what the source would add, exactly how to connect it, and lets whatever else is working keep
 * working. `gate` comes from the server's source registry, so this can never drift from reality.
 *
 * Compact mode is the inline chip used in a source strip; full mode is the explanatory card.
 */
export function SourceGate({ gate, compact }) {
  if (!gate || gate.state === "connected") return null;
  const needsKey = gate.state === "needs_key";

  if (compact) {
    return (
      <span className={`src-dot ${needsKey ? "warn" : "off"}`} title={gate.note || ""}>
        <i /> {gate.label}
        {needsKey && gate.signup_url && (
          <>
            {" · "}
            <a href={gate.signup_url} target="_blank" rel="noreferrer noopener">connect</a>
          </>
        )}
        {!needsKey && " · unavailable"}
      </span>
    );
  }

  return (
    <div className={`gate gate-${gate.state}`}>
      <div className="gate-head">
        <span className={`gate-dot ${needsKey ? "warn" : "off"}`} />
        <b>{gate.label}</b>
        <span className="gate-state">{STATE_LABEL[gate.state] || gate.state}</span>
      </div>
      <p className="gate-powers">Would add: {gate.powers}</p>
      {gate.note && <p className="gate-note">{gate.note}</p>}
      {needsKey && gate.signup_url && (
        <div className="gate-steps">
          <ol>
            <li>
              Create a free app at{" "}
              <a href={gate.signup_url} target="_blank" rel="noreferrer noopener">
                {new URL(gate.signup_url).hostname}
              </a>
            </li>
            <li>
              Put its credentials in <code>.env</code> as{" "}
              {(gate.env || []).map((e, i) => (
                <span key={e}>{i > 0 && ", "}<code>{e}</code></span>
              ))}{" "}
              and restart.
            </li>
          </ol>
        </div>
      )}
    </div>
  );
}
