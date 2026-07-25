"""Tests for the assistant's tool surface.

These are mostly about what the tools CANNOT do. The model calling them is the same one reading
arbitrary text ingested from the internet, so the tool registry is a security boundary: read-only,
parameterised, and with no way to reach the network.
"""
import inspect

from tradeos import assistant_tools as T

# ------------------------------------------------------------------ the boundary

def test_no_tool_can_write():
    """There is deliberately no write tool, and no generic query escape hatch."""
    for name, (fn, _desc) in T.TOOLS.items():
        src = inspect.getsource(fn).lower()
        for verb in ("insert into", "update ", "delete from", "drop ", "alter ", "truncate"):
            assert verb not in src, f"{name} contains a write: {verb!r}"


def test_no_tool_composes_sql_from_its_arguments():
    """The model picks a tool and fills in blanks; it never composes a query. An f-string around
    SQL in here would hand it one."""
    for name, (fn, _desc) in T.TOOLS.items():
        for line in inspect.getsource(fn).splitlines():
            stripped = line.strip()
            if "SELECT" in stripped.upper() or "FROM" in stripped.upper():
                assert not stripped.startswith('f"'), f"{name} builds SQL with an f-string"


def test_no_tool_reaches_the_network():
    """An injected instruction telling the assistant to fetch an address must have nothing to call."""
    for name, (fn, _desc) in T.TOOLS.items():
        src = inspect.getsource(fn)
        for net in ("httpx", "requests", "urlopen", "socket", "fetch("):
            assert net not in src, f"{name} can reach the network via {net}"


def test_no_tool_accepts_a_url_or_a_table_name():
    for name, (fn, _desc) in T.TOOLS.items():
        params = set(inspect.signature(fn).parameters) - {"conn"}
        for forbidden in ("url", "uri", "endpoint", "table", "column", "sql", "query_sql"):
            assert forbidden not in params, f"{name} takes {forbidden!r}"


# ------------------------------------------------------------------ dispatch

def test_an_unknown_tool_is_refused_not_guessed():
    out = T.call(None, "drop_everything")
    assert "error" in out and "available" in out


def test_unexpected_arguments_are_dropped_rather_than_passed_through():
    """A model that hallucinates an argument name must not reach the function with it."""
    captured = {}

    def fake(conn, query="", days=14, limit=8):
        captured.update({"query": query, "days": days, "limit": limit})
        return {"ok": True}

    T.TOOLS["_fake"] = (fake, "test only")
    try:
        T.call(None, "_fake", {"query": "oil", "conn": "hijack", "rm_rf": True, "days": 3})
        assert captured == {"query": "oil", "days": 3, "limit": 8}
    finally:
        del T.TOOLS["_fake"]


def test_a_failing_tool_returns_an_error_rather_than_raising():
    """The assistant must be able to say a lookup failed without the whole answer failing."""
    def boom(conn):
        raise RuntimeError("nope")

    T.TOOLS["_boom"] = (boom, "test only")
    try:
        assert "error" in T.call(None, "_boom")
    finally:
        del T.TOOLS["_boom"]


# ------------------------------------------------------------------ argument clamping

def test_numeric_arguments_are_clamped_not_trusted():
    assert T._clamp(9999, 1, 90, 14) == 90
    assert T._clamp(-5, 1, 90, 14) == 1
    assert T._clamp("not a number", 1, 90, 14) == 14
    assert T._clamp(None, 1, 90, 14) == 14


def test_every_tool_is_described_for_the_model():
    described = T.describe()
    for name in T.TOOLS:
        assert name in described
