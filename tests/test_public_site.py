"""Offline tests for the marketing site's public API (Phase 7).

These endpoints are the only ones a stranger or a crawler will ever reach, and they answer without
a session. Two properties therefore have to hold mechanically rather than by inspection:

  * nothing user-scoped is readable through them, and
  * nothing here can be tuned to flatter the product.

The second matters as much as the first on this particular site. The Ledger's argument is that the
record is unedited; a walkthrough that quietly picked its best day would make that a lie by
omission, and it is the kind of change that looks harmless in a diff.
"""
import inspect
import re
from datetime import date

from tradeos import public_site

# ------------------------------------------------------------------ the public boundary

def test_the_public_module_reads_nothing_user_scoped():
    """No session, no user tables. Asserted against the source because the failure mode is a
    helpful-looking join added later that quietly widens what an anonymous caller can see."""
    src = inspect.getsource(public_site)
    for table in ("users", "trades", "watchlists", "user_profiles", "trade_context",
                  "sessions", "portfolios", "api_keys"):
        assert not re.search(rf"\b(FROM|JOIN|INTO|UPDATE)\s+{table}\b", src, re.I), \
            f"public_site reads {table}"
    assert "tos_session" not in src and "session_user" not in src


def test_no_public_route_accepts_a_session_or_a_user_identifier():
    """A public route that takes a cookie is one refactor away from personalising for a stranger,
    and a public route that takes a user id is an enumeration surface."""
    from tradeos import app as app_module

    src = inspect.getsource(app_module)
    for match in re.finditer(r"@app\.get\(\"/api/public/[^\"]*\"\)\s*\ndef (\w+)\((.*?)\)\s*->", src, re.S):
        name, params = match.group(1), match.group(2)
        assert "tos_session" not in params, f"{name} reads a session"
        assert "user" not in params, f"{name} takes a user identifier"


def test_every_public_route_is_a_read():
    from tradeos import app as app_module

    src = inspect.getsource(app_module)
    assert not re.search(r"@app\.(post|put|patch|delete)\(\"/api/public/", src), \
        "public surface must be read-only"


# ------------------------------------------------------------------ nothing may be cherry-picked

def test_the_settled_example_is_not_filtered_to_hits():
    """The one already-marked call shown beside the walkthrough is drawn newest-first. If it were
    ever filtered by verdict, the section proving 'the loop closes' would only ever prove it
    closes well."""
    src = inspect.getsource(public_site._settled)
    assert "verdict IN ('hit', 'miss')" in src
    assert "verdict = 'hit'" not in src
    assert "ORDER BY c.resolved_at DESC" in src


def test_the_walkthrough_rotates_by_date_rather_than_by_quality():
    """Selection must be a function of the day and nothing else — any rule that could be tuned
    toward a good example eventually will be."""
    src = inspect.getsource(public_site.walkthrough)
    # Scoped to the line that actually chooses, not the whole function — `max(0, days)` elsewhere
    # clamps a countdown and is not a selection rule.
    picks = [ln.strip() for ln in src.splitlines() if re.match(r"\s*c\s*=\s*pool\[", ln)]
    assert len(picks) == 1, "expected exactly one selection statement"
    assert picks[0] == "c = pool[today.toordinal() % len(pool)]"

    # And the pool it draws from is ordered by recency alone.
    assert "ORDER BY c.created_at DESC" in public_site._LIVE_SQL
    for tuned in ("confidence DESC", "verdict", "hit_rate", "excess_return"):
        assert tuned not in public_site._LIVE_SQL, f"the pool is ordered by {tuned!r}"


def test_rotation_is_stable_within_a_day_and_moves_between_days():
    pool_size = 7
    pick = lambda d: d.toordinal() % pool_size            # noqa: E731 — mirrors the module
    assert pick(date(2026, 7, 26)) == pick(date(2026, 7, 26))
    assert pick(date(2026, 7, 26)) != pick(date(2026, 7, 27))


def test_the_hero_shows_only_event_derived_interpretations():
    """"Watch it interpret something that happened this morning" is the hero's promise. A 13F
    filing is a real claim and is scored like any other, but it is not that."""
    assert "JOIN events e" in public_site._LIVE_SQL          # inner join, not left
    assert "c.status = 'open'" in public_site._LIVE_SQL


# ------------------------------------------------------------------ honest degradation

def test_an_unknown_country_is_refused_rather_than_approximated():
    """The exposure set is small and hand-checked on purpose. Offering a visitor a country with no
    sourced figures would be inventing a perspective in order to demonstrate one."""
    class _Cur:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def execute(self, *a): pass
        def fetchall(self): return [("AE", "United Arab Emirates", "AED", "ADX")]
        def fetchone(self): return None

    class _Conn:
        def cursor(self): return _Cur()

    out = public_site.frame_preview(_Conn(), "ZZ")
    assert out["country"] is None
    assert "ZZ" in out["error"]
    assert "claims" not in out                                # no ranking against a made-up frame
    assert out["countries"] == [{"country": "AE", "name": "United Arab Emirates",
                                 "currency": "AED", "main_index": "ADX"}]


def test_an_empty_store_says_so_rather_than_returning_a_shell():
    class _Cur:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def execute(self, *a): pass
        def fetchall(self): return []
        def fetchone(self): return None

    class _Conn:
        def cursor(self): return _Cur()

    out = public_site.walkthrough(_Conn(), date(2026, 7, 26))
    assert out["available"] is False and out["reason"]
