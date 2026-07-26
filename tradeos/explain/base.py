"""Explanation orchestration: cache → provider → guards → template fallback.

With no key configured (EXPLAIN_PROVIDER unset or 'template'), the deterministic template is
returned directly. For 'gemini'/'anthropic', the model output must clear both guards or the
template renders instead. Results are cached per (cluster, provider); a definition version
bump invalidates stale prose.
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import asdict, dataclass

import psycopg

from . import template
from .guards import allowed_numbers, base_rate_integrity_guard, directive_guard, numbers_guard

log = logging.getLogger("tradeos.explain")


@dataclass
class Explanation:
    prose: str
    provider: str            # provider requested
    model_id: str            # what actually produced the prose (shown to the user)
    used_template: bool      # true when the template was used (default or guard fallback)
    from_cache: bool
    definition_version: int | None


def _cal_for(detail: dict, calibration: dict | None, horizon: int) -> dict | None:
    bucket = detail.get("confidence_bucket")
    return ((calibration or {}).get("per_bucket", {}).get(bucket, {}) or {}).get(str(horizon))


def _try_llm(provider: str, detail: dict, cal: dict | None, horizon: int) -> str | None:
    """Dispatch to the configured model provider (gemini, or any OpenAI-compatible endpoint via llm.py).
    Returns prose, or None if unavailable (no key, in cooldown, or call failed) — caller uses template."""
    from .. import llm
    if llm.wants_model(provider):
        try:
            from . import gemini
            return gemini.generate(detail, cal, horizon)
        except Exception as exc:  # missing key / API error -> template
            log.warning("explanation provider %s unavailable (%s); using template", provider, type(exc).__name__)
    return None


def _read_cache(conn, cluster_id: int, provider: str, version: int | None) -> Explanation | None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT prose, model_id, used_template, definition_version FROM explanation_cache WHERE cluster_id=%s AND provider=%s",
            (cluster_id, provider),
        )
        r = cur.fetchone()
    if r and r[3] == version:  # version match: cached prose still describes this definition
        return Explanation(r[0], provider, r[1], r[2], True, r[3])
    return None


def _write_cache(conn, cluster_id: int, exp: Explanation) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO explanation_cache (cluster_id, provider, definition_version, prose, model_id, used_template)
               VALUES (%s,%s,%s,%s,%s,%s)
               ON CONFLICT (cluster_id, provider) DO UPDATE SET
                   definition_version=EXCLUDED.definition_version, prose=EXCLUDED.prose,
                   model_id=EXCLUDED.model_id, used_template=EXCLUDED.used_template, created_at=now()""",
            (cluster_id, exp.provider, exp.definition_version, exp.prose, exp.model_id, exp.used_template),
        )
    conn.commit()


def explain(conn: psycopg.Connection, detail: dict, calibration: dict | None,
            provider: str | None = None, horizon: int = 30) -> Explanation:
    provider = (provider or os.environ.get("EXPLAIN_PROVIDER", "template")).lower()
    cluster_id = detail.get("cluster_id")
    version = detail.get("definition_version")

    # the template is deterministic and cheap, so it is regenerated, never cached (which would
    # risk serving stale prose after a template change); model prose IS cached to survive outages.
    if cluster_id is not None and provider != "template":
        cached = _read_cache(conn, cluster_id, provider, version)
        if cached is not None:
            return cached

    cal = _cal_for(detail, calibration, horizon)
    template_prose = template.render(detail, cal, horizon)

    # No provider gate here: `_try_llm` owns that decision and returns None for the template path.
    # There used to be one, testing the provider name against a literal tuple, and it disagreed
    # with the transport about what `gemini,openai` means — see llm.wants_model().
    result: Explanation | None = None
    prose = _try_llm(provider, detail, cal, horizon)
    if prose is not None:
        allowed = allowed_numbers(detail, calibration or {})
        if directive_guard(prose) and numbers_guard(prose, allowed) and base_rate_integrity_guard(prose, cal):
            result = Explanation(prose, provider, _model_id(provider), False, False, version)
        else:
            log.warning("explanation guard tripped (provider=%s cluster=%s); using template",
                        provider, cluster_id)

    if result is None:
        # template path: default (provider == 'template') or a fallback from a model provider
        is_fallback = provider != "template"
        model_id = f"template ({provider} unavailable)" if is_fallback else "template"
        result = Explanation(template_prose, provider, model_id, is_fallback, False, version)

    # cache only a genuine model success — never a template fallback, so a transient model
    # outage does not poison the cache and the next request can retry the model.
    if cluster_id is not None and provider != "template" and not result.used_template:
        _write_cache(conn, cluster_id, result)
    return result


def _model_id(provider: str) -> str:
    from .. import llm
    return llm.model_id(provider)


def to_dict(exp: Explanation) -> dict:
    return asdict(exp)


_TICKER = re.compile(r"^[A-Z.]{1,6}$")


def extract_tickers(image_bytes: bytes, mime: str, provider: str | None = None) -> list[str]:
    """Return de-duplicated candidate tickers from an image — symbols ONLY (Feature Spec 5.5,
    decision #32). The output guard is mechanical: only bare ticker-pattern strings survive, so
    a sentence, a number, a comment about a position, or an injected instruction is discarded.
    With no vision key configured this returns [] and the caller routes to manual entry."""
    provider = (provider or os.environ.get("EXPLAIN_PROVIDER", "template")).lower()
    candidates: list = []
    try:
        from .. import llm
        if llm.wants_model(provider):
            from . import gemini
            candidates = gemini.extract_tickers(image_bytes, mime)
    except Exception as exc:  # any provider failure -> manual entry
        log.warning("ticker extraction provider %s failed (%s)", provider, type(exc).__name__)
        candidates = []
    out, seen = [], set()
    for c in candidates:
        s = str(c).strip().upper()
        if _TICKER.match(s) and s not in seen:
            seen.add(s)
            out.append(s)
    return out
