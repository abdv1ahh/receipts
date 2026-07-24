"""AI chart analysis (Milestone 6) — the interpretive plane applied to a user's OWN chart screenshot.

Where the Signal plane's vision use is deliberately minimal (extract ticker symbols only, decision #32),
this reads a chart into an EDUCATIONAL analysis: the visible price structure, any classic pattern, the
risk/reward framing (against the trade's recorded levels when present), and coaching observations a
trading mentor would offer. It stays on the right side of the line by construction:

  * it DESCRIBES what is visible and teaches — it never tells the user what to do (directive_guard on
    every text field; the whole thing is framed "educational, not advice");
  * with no vision model (or a guard trip, or exhausted quota) it FALLS BACK to the deterministic
    level-based analysis from the trade record — honest, never fabricated.
"""
from __future__ import annotations

import base64
import json
import logging
import os

from .. import llm
from ..explain.guards import directive_guard

log = logging.getLogger("tradeos.intelligence.vision")

INSTRUCTION = (
    "You are a trading-education analyst reviewing a chart screenshot a user uploaded of their OWN "
    "trade or setup. Read what is VISIBLE and turn it into a short educational review. Rules, exactly:\n"
    "- Describe the visible price structure: trend direction, notable support/resistance, and any classic "
    "pattern you can see (range, breakout, pullback, double top, head-and-shoulders, etc.). Describe, "
    "do not predict.\n"
    "- If entry/stop/target levels are visible or given in the context, comment factually on the "
    "risk/reward structure and where the risk sits.\n"
    "- Give 2-4 coaching observations a trading mentor would (position sizing, discipline, what to "
    "journal), framed as education.\n"
    "- NEVER give advice or say what to do. Never use buy, sell, hold, should, recommend, enter, exit, "
    "target price, take profit, add, trim. This is post-hoc education, not a call.\n"
    "- If the image is not a price chart, set is_chart false and leave the analysis fields brief.\n"
    "- ALSO extract, to help pre-fill a trade log, ONLY what is CLEARLY readable on the chart: the "
    "ticker `symbol` shown, the `timeframe` if a timeframe label is visible (e.g. 5m, 1h, 1D), the "
    "`direction` (long or short) if obvious, and `entry`/`stop`/`target` numeric prices ONLY if a "
    "labeled line or a clear axis value shows them. If a field is NOT clearly visible, use null — never "
    "guess a ticker or invent a price.\n"
    "Return ONLY JSON with keys: pattern (string), structure (string), risk_reward (string), "
    "observations (array of strings), psychology (string), is_chart (boolean), symbol (string|null), "
    "timeframe (string|null), direction (\"long\"|\"short\"|null), entry (number|null), stop (number|null), "
    "target (number|null).\n"
    "TRADE CONTEXT (JSON):\n"
)


def _num(x):
    """A number the model read off the chart, or None — never coerce junk into a value."""
    try:
        return float(x) if x is not None and str(x).strip() != "" else None
    except (ValueError, TypeError):
        return None


def _detected(out: dict) -> dict:
    """The structured pre-fill fields, passed through honestly: only what the model reported as visible,
    nulls left as nulls (the UI marks these 'detected — verify')."""
    sym = out.get("symbol")
    direction = out.get("direction")
    return {
        "symbol": (str(sym).upper().strip() or None) if sym else None,
        "timeframe": (str(out.get("timeframe")).strip() or None) if out.get("timeframe") else None,
        "direction": direction if direction in ("long", "short") else None,
        "entry": _num(out.get("entry")), "stop": _num(out.get("stop")), "target": _num(out.get("target")),
    }
_TEXT_FIELDS = ("pattern", "structure", "risk_reward", "psychology")


def _guarded(out: dict) -> bool:
    """Every prose field (and each observation) must be advice-free, or the model output is discarded."""
    fields = [out.get(k) or "" for k in _TEXT_FIELDS] + list(out.get("observations") or [])
    return all(directive_guard(str(f)) for f in fields)


def _context(trade: dict | None) -> dict:
    if not trade:
        return {}
    return {"recorded_levels": {k: trade.get(k) for k in
            ("symbol", "direction", "entry_price", "stop_price", "target_price", "strategy", "timeframe")}}


def _parse(raw: str | None) -> dict | None:
    """Parse the model's JSON chart read (tolerating a ```json fence), or None."""
    if not raw:
        return None
    s = raw.strip()
    if s.startswith("```"):
        s = s.strip("`").split("\n", 1)[-1].rsplit("```", 1)[0]
    try:
        parsed = json.loads(s)
        return parsed if isinstance(parsed, dict) else None
    except (ValueError, TypeError):
        return None


def _fallback(trade: dict | None) -> dict:
    """Deterministic, honest fallback: for a logged trade, the level-based analysis; otherwise a plain
    'connect a vision model' note. Never fabricates a chart read."""
    base = {"source": "levels", "model_id": "template", "used_template": True,
            "pattern": None, "risk_reward": None, "psychology": None, "is_chart": None, "detected": {}}
    if trade and trade.get("entry_price"):
        from .. import trades
        a = trades.analyze_trade(trade)
        rr = a.get("reward_risk")
        return {**base, "ok": True,
                "structure": "AI chart reading isn't available (no vision model connected) — here is the "
                             "analysis from your recorded levels instead.",
                "risk_reward": f"Planned reward:risk is {rr}." if rr is not None else None,
                "observations": a.get("observations", []), "risk_flags": a.get("risk_flags", [])}
    return {**base, "ok": False, "source": "none",
            "structure": "Connect a vision model (set EXPLAIN_PROVIDER + a key) to get an AI read of the chart.",
            "observations": [], "risk_flags": []}


def analyze_chart(image_bytes: bytes, mime: str, trade: dict | None = None,
                  provider: str | None = None) -> dict:
    """Educational analysis of a chart image, via any configured vision model (llm.vision). Model output
    is guarded (no advice); anything that fails a guard, or any absence of a vision model, falls back to
    the deterministic level-based analysis."""
    provider = (provider or os.environ.get("EXPLAIN_PROVIDER", "template")).lower()
    out = _parse(llm.vision(INSTRUCTION + json.dumps(_context(trade)), image_bytes, mime,
                            max_tokens=800, json_mode=True, provider=provider))
    if out and _guarded(out):
        return {"ok": True, "source": "ai", "used_template": False, "model_id": llm.model_id(provider),
                "pattern": out.get("pattern"), "structure": out.get("structure"),
                "risk_reward": out.get("risk_reward"), "observations": out.get("observations") or [],
                "psychology": out.get("psychology"), "is_chart": out.get("is_chart"),
                "detected": _detected(out),
                "disclaimer": "An educational read of your chart, not advice."}
    if out:
        log.warning("chart analysis guard tripped; using deterministic fallback")
    return _fallback(trade)
