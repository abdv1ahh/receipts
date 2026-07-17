"""Slice 5 offline tests for the Gemini provider: it degrades to None (→ template) with no key,
and the payload it would send contains only computed facts — never a fabricated number. The
live guard behavior (rejecting an invented number or a directive) is covered in test_explain."""
from tradeos.explain import gemini


def test_generate_returns_none_without_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    # no key -> None so base.explain falls back to the deterministic template (no network call)
    assert gemini.generate({"name": "X", "inputs": {}}, None, 30) is None


def test_payload_only_contains_computed_facts():
    detail = {
        "name": "Elanco Animal Health Inc", "symbol": "ELAN", "score": 4.95,
        "confidence_bucket": "medium", "voices": 8, "source_classes": ["activist", "insider"],
        "inputs": {"window_days": 90, "freshest_knowable": "2026-07-14T20:00:00+00:00",
                   "stalest_knowable": "2026-07-07T13:00:00+00:00",
                   "contributions": [{"source_class": "insider"}, {"source_class": "activist"}]},
    }
    cal = {"episodes": 36, "sufficient": True, "hit_rate": 0.39}
    p = gemini._payload(detail, cal, 30)
    assert p["symbol"] == "ELAN" and p["voices"] == 8 and p["convergence_score"] == 4.95
    assert p["composition"] == {"insider": 1, "activist": 1}
    assert p["backtested"]["hit_rate_pct"] == 39 and p["backtested"]["episodes"] == 36
    assert p["freshest_knowable"] == "2026-07-14"  # trimmed to date, no fabricated precision
