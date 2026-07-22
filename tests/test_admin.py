"""Offline tests for the admin layer's pure logic (Slice K): the self-safety guardrails on tier
changes and bans, the allowed moderation actions, the LIKE-escaping used in user search, and the
feature-flag state merge (defaults + DB overrides, unknown rows ignored). No network, no database."""
from tradeos import admin as A
from tradeos import flags as F


def test_validate_tier_change_guardrails():
    assert A.validate_tier_change(1, 2, "retail") == (True, None)
    assert A.validate_tier_change(1, 2, "pro")[0] is True
    assert A.validate_tier_change(1, 2, "free")[0] is True
    # cannot change your own tier (no self-lockout)
    ok, err = A.validate_tier_change(7, 7, "free")
    assert ok is False and "own tier" in err
    # 'admin' is never a web grant; unknown tiers rejected
    assert A.validate_tier_change(1, 2, "admin")[0] is False
    assert A.validate_tier_change(1, 2, "superuser")[0] is False


def test_can_ban_rejects_self():
    assert A.can_ban(1, 2) == (True, None)
    ok, err = A.can_ban(5, 5)
    assert ok is False and "yourself" in err


def test_resolution_ok():
    assert all(A.resolution_ok(a) for a in ("hide", "unhide", "dismiss"))
    assert not A.resolution_ok("delete")
    assert not A.resolution_ok("")


def test_like_escapes_wildcards():
    # a stray % or _ in a search term must be neutralised so it can't match-all
    assert A._like("50%_off") == "%50\\%\\_off%"
    assert A._like("abc") == "%abc%"


def test_flags_resolve_states_defaults_overrides_and_unknowns():
    # with no DB rows, every known flag falls back to its default (all True today)
    states = F.resolve_states({})
    assert [s["name"] for s in states] == list(F.FLAGS)          # stable order
    assert all(s["enabled"] for s in states)
    assert all(s["label"] and s["description"] for s in states)  # console-ready metadata

    # a DB override flips exactly that flag; unknown rows are ignored
    states = F.resolve_states({"ai_assistant": False, "not_a_flag": True})
    by_name = {s["name"]: s["enabled"] for s in states}
    assert by_name["ai_assistant"] is False
    assert by_name["registration"] is True
    assert "not_a_flag" not in by_name
