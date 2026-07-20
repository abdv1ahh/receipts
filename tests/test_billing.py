"""Offline tests for billing entitlements and API-key primitives: tiers never over-grant, the
canary trace is deterministic and day-scoped, keys hash opaquely, and the per-key rate limit
blocks. No network, no database (Stripe is never called here)."""
from tradeos import apikeys, billing


def test_entitlements_scale_by_tier_and_never_overgrant():
    assert billing.entitlements("free")["live_signals"] is False
    assert billing.entitlements("free")["api"] is False
    assert billing.entitlements("retail")["live_signals"] is True
    assert billing.entitlements("retail")["api"] is False
    assert billing.entitlements("pro")["api"] is True
    assert billing.entitlements(None) == billing.ENTITLEMENTS["free"]
    assert billing.entitlements("not-a-tier")["api"] is False   # unknown -> free, never over-grant


def test_plans_map_to_tiers():
    assert billing.PLANS["retail"]["tier"] == "retail"
    assert billing.PLANS["pro"]["tier"] == "pro"


def test_provider_unconfigured_is_test_mode(monkeypatch):
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    assert billing.provider_configured() is False


def test_canary_trace_deterministic_and_day_scoped():
    a = apikeys.canary_trace("seed123", "2026-07-20")
    assert a == apikeys.canary_trace("seed123", "2026-07-20")
    assert a != apikeys.canary_trace("seed123", "2026-07-21")   # rotates per day
    assert a != apikeys.canary_trace("other", "2026-07-20")     # per key
    assert len(a) == 16


def test_api_key_hash_is_stable_and_opaque():
    h = apikeys._hash("tos_live_abc")
    assert h == apikeys._hash("tos_live_abc") and len(h) == 64
    assert "tos_live_abc" not in h                              # raw never recoverable from the hash


def test_rate_limit_blocks_after_limit():
    kid = -999
    apikeys._hits.pop(kid, None)
    assert [apikeys.rate_ok(kid, limit=3, window=60) for _ in range(4)] == [True, True, True, False]
