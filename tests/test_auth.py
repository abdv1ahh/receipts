"""Slice 6 offline tests for the auth primitives and the entitlement rule. Register/login flows
and the free-tier bypass are verified live (they need the DB); these lock the pure logic:
argon2id hashing, the breached-password check, session-token hashing, and the tier->delay map
that no client parameter can weaken (decision #36)."""
from tradeos import authn


def test_password_hash_roundtrip():
    h = authn.hash_password("correct horse battery staple")
    assert h != "correct horse battery staple"  # never store plaintext
    assert authn.verify_password(h, "correct horse battery staple") is True
    assert authn.verify_password(h, "wrong password entirely") is False


def test_weak_password_rejected():
    assert authn.is_weak_password("short") is True            # too short
    assert authn.is_weak_password("password123") is True      # on the common list
    assert authn.is_weak_password("tradeos123") is True
    assert authn.is_weak_password("a-long-unique-passphrase-9") is False


def test_session_token_is_hashed_not_stored_raw():
    t = "some-session-token"
    assert authn._hash_token(t) != t and len(authn._hash_token(t)) == 64
    assert authn._hash_token(t) == authn._hash_token(t)  # deterministic


def test_free_tier_is_delayed_paid_is_live():
    assert authn.delay_hours("free") == 48
    assert authn.delay_hours(None) == 48        # unauthenticated is treated as free (most restrictive)
    assert authn.delay_hours("retail") == 0
    assert authn.delay_hours("pro") == 0
    assert authn.delay_hours("admin") == 0
