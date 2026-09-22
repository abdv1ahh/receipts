"""No raw price from the market-data vendor reaches any screen. The whole surface, swept.

WHY THIS FILE EXISTS. Alpaca's published answer to "Can I redistribute Alpaca API data via my
platform?" is one sentence with no qualification of any kind: *"Unfortunately, you cannot
redistribute Alpaca API data."* There is no personal/commercial split in it and no exception for
display, and their terms additionally incorporate the NASDAQ display-service agreements by
reference. Putting an entry close on a page anyone can read is redistribution on the ordinary
meaning of the word. So the product publishes the MEASUREMENT and never the prices it was measured
from, and a self-hoster running their own key is in exactly the same position — which is why this
lives in the product rather than in a note to the operator.

WHY A SWEEP RATHER THAN SIX ASSERTIONS. The leak that actually happened was not a field somebody
chose to print. `/api/calls/{id}` returned `calls._row()` wholesale and the four price columns came
along with it, invisibly, because they were NULL on all 474 sealed rows and nothing had resolved
through the scorer yet. The first call to resolve would have started publishing them, on a public
route, with no code change and no review. A test that names the six fields it knows about would
have passed that whole time. This one plants distinctive numbers, renders EVERY route the app
serves, and reads the bytes back — so a seventh field, a new route, or a debug echo is caught by
construction rather than by remembering.

TWO KINDS OF PRICE, because they leak by different paths:

  a CALL's sealed prices    `calls.entry_price` and the three beside it, written by
                            `scoring._write` at resolution. Planted here on a scratch call.
  the FEED's last close     `prices_eod.close`, read live by the publish screen's commitment
                            panel. Planted here on a scratch symbol nothing else touches.

What a reader IS shown, and what this test must therefore leave alone: the ticker, the direction,
the window, the entry session DATE, the exit session DATE, the excess return, and the verdict.
Dates are not prices, and they are the thing that makes the measurement checkable from a feed of
the reader's own choosing.

Skips cleanly with no database, like the other integrity tests.
"""
from __future__ import annotations

import secrets

import pytest

try:
    from fastapi.testclient import TestClient

    from tradeos import authn, db
    from tradeos.app import app
    from tradeos.receipts import calls as receipts_calls
    _IMPORTS_OK = True
except Exception:                                             # pragma: no cover
    _IMPORTS_OK = False


def _db_reachable() -> bool:
    if not _IMPORTS_OK:
        return False
    try:
        with db.connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT to_regclass('calls')")
            return cur.fetchone()[0] is not None
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _db_reachable(), reason="no database reachable; the price-redistribution sweep needs one")


# The planted values. Chosen to be impossible to produce by accident: six significant figures past
# the decimal point, and nothing in this codebase rounds to six except the two return columns.
CALL_PRICES = {
    "entry_price": "123.456789",
    "exit_price": "234.567891",
    "benchmark_entry": "345.678912",
    "benchmark_exit": "456.789123",
    "subject_return": "0.898989",
    "benchmark_return": "-0.787878",
}
FEED_CLOSE = "567.891234"
SCRATCH_SYMBOL = "ZZGUARD"

# What the sweep hunts for in a response body. Both the literal spelling and the float repr, since
# JSON serialises a psycopg Decimal through `float()` and `0.898989` and `0.898989` agree but
# `123.456789` could in principle come back as `123.45678900000001`. Checking the leading
# significant digits catches that without matching anything real.
NEEDLES = sorted({v.lstrip("-") for v in CALL_PRICES.values()} | {FEED_CLOSE})

# The six columns themselves, by name. A response that renamed `entry_price` to `entry` and kept
# the number would be caught by NEEDLES; a response that kept the name and nulled the number is
# still a payload shaped to carry prices, and the next resolution fills it in.
FORBIDDEN_KEYS = ("entry_price", "exit_price", "benchmark_entry", "benchmark_exit",
                  "subject_return", "benchmark_return",
                  # The publish screen's two. Gone from `preview` entirely; the date fields that
                  # used to share these names are now `last_session` / `benchmark_last_session`,
                  # because a field called `last_close` holding "2026-09-22" is a name that lies.
                  "last_close", "benchmark_last_close", "last_close_day")

# WHOSE PRICES THESE ARE, which is the whole question. The rule is about redistributing a
# MARKET-DATA VENDOR's data. A number a user typed into their own trade journal is their own, is
# not Alpaca's, and carrying it back to them is not redistribution of anything — so `/api/trades`
# and `/api/community/feed` legitimately hold `entry_price` keys and always will.
#
# The key check therefore runs over the Receipts surfaces, which are the ones that show a score
# derived from vendor closes. Stated as a positive list rather than an exclusion list on purpose:
# once section B of the release plan lands, these ARE the whole application, and the distinction
# this list draws stops needing to be drawn at all. The VALUE sweep has no such scoping — it runs
# over every route in the app, because a vendor close is a vendor close wherever it surfaces.
SCORE_SURFACES = ("/api/calls", "/api/receipts", "/api/board", "/api/card", "/r/", "/health")


@pytest.fixture(scope="module")
def planted():
    """A resolved call carrying every price column, and one scratch symbol in the feed.

    The call is resolved by direct UPDATE rather than through `scoring.resolve_call`, because the
    scorer needs a real price series over a real horizon and this test is about what the HTTP
    surface prints, not about how a verdict is reached. The trigger from migration 035 refuses to
    change a resolved call, so the resolution happens in one statement while `resolved_at` is
    still NULL — the same order `scoring._write` uses.
    """
    handle = f"guard-{secrets.token_hex(6)}"
    email = f"guard-{secrets.token_hex(6)}@test.invalid"
    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO callers (handle, display_name, kind, jurisdiction_attested)
                           VALUES (%s, 'Price Guard', 'human', true) RETURNING id""", (handle,))
            caller_id = cur.fetchone()[0]
            cur.execute("INSERT INTO users (email, password_hash, tier) "
                        "VALUES (%s, %s, 'pro') RETURNING id",
                        (email, authn.hash_password(secrets.token_urlsafe(24))))
            uid = cur.fetchone()[0]
            session = authn._create_session(cur, uid, "127.0.0.1", "pytest")
            cur.execute("""INSERT INTO prices_eod (symbol, day, open, high, low, close, volume,
                                                   source)
                           VALUES (%s, CURRENT_DATE, %s, %s, %s, %s, 1000, 'test:price-guard')
                           ON CONFLICT (symbol, day) DO UPDATE SET close = EXCLUDED.close""",
                        (SCRATCH_SYMBOL, FEED_CLOSE, FEED_CLOSE, FEED_CLOSE, FEED_CLOSE))
        conn.commit()

        call = receipts_calls.publish(caller_id, {
            "symbol": "ABT", "direction": "up", "horizon_days": 7, "confidence": "medium",
            "thesis": "a thesis long enough to be worth holding somebody to, forty plus characters",
        }, conn)

        sets = ", ".join(f"{k} = %s" for k in CALL_PRICES)
        with conn.cursor() as cur:
            cur.execute(f"UPDATE calls SET verdict = 'miss', verdict_note = 'planted', "  # noqa: S608
                        f"excess_return = 0.111111, entry_session = '2026-01-05', "
                        f"exit_session = '2026-01-12', resolved_at = now(), {sets} "
                        f"WHERE id = %s", (*CALL_PRICES.values(), call["id"]))
        conn.commit()

        yield {"caller_id": caller_id, "handle": handle, "call_id": call["id"],
               "session": session, "uid": uid}

        conn.rollback()
        with conn.cursor() as cur:
            cur.execute("ALTER TABLE calls DISABLE TRIGGER calls_append_only_trg")
            cur.execute("DELETE FROM calls WHERE caller_id = %s", (caller_id,))
            cur.execute("ALTER TABLE calls ENABLE TRIGGER calls_append_only_trg")
            cur.execute("DELETE FROM callers WHERE id = %s", (caller_id,))
            cur.execute("DELETE FROM sessions WHERE user_id = %s", (uid,))
            cur.execute("DELETE FROM users WHERE id = %s", (uid,))
            cur.execute("DELETE FROM prices_eod WHERE symbol = %s", (SCRATCH_SYMBOL,))
        conn.commit()


def _paths(planted: dict) -> list[str]:
    """Every GET route the app serves, with its path parameters filled in.

    Read off `app.routes` rather than listed here on purpose: a route added tomorrow is swept
    tomorrow, with no edit to this file. That is the property the leak this test exists for
    actually needed.
    """
    fill = {
        "handle": planted["handle"],
        "call_id": str(planted["call_id"]),
        "symbol": SCRATCH_SYMBOL,
        "caller_id": str(planted["caller_id"]),
    }
    out = []
    for route in app.routes:
        path = getattr(route, "path", None)
        if not path or "GET" not in (getattr(route, "methods", None) or set()):
            continue
        for name, value in fill.items():
            path = path.replace("{" + name + "}", value)
        if "{" in path:                       # an id this test has no meaningful value for
            path = path.split("{")[0] + "1"
        out.append(path)
    # The query strings that reach code a bare path cannot. The commitment panel is the one that
    # matters: it is the screen a caller reads before sealing, and it held two live feed closes.
    out += [f"/api/calls/preview?symbol={SCRATCH_SYMBOL}&horizon_days=7",
            f"/api/calls/scoreability?symbol={SCRATCH_SYMBOL}",
            f"/api/calls/symbols?q={SCRATCH_SYMBOL[:3]}",
            f"/api/asset/{SCRATCH_SYMBOL}",
            f"/api/search?q={SCRATCH_SYMBOL}"]
    return sorted(set(out))


def _sweep(client: TestClient, paths: list[str]) -> list[tuple[str, str]]:
    """(path, what leaked) for everything that came back carrying a planted value or a price key."""
    found = []
    for path in paths:
        r = client.get(path)
        body = r.content.decode("utf-8", "replace")
        for needle in NEEDLES:
            if needle in body:
                found.append((path, needle))
        if path.startswith(SCORE_SURFACES):
            for key in FORBIDDEN_KEYS:
                if f'"{key}"' in body:
                    found.append((path, f"key {key}"))
    return found


def test_no_price_reaches_a_stranger(planted):
    """The public surface. Every route, no session, nothing in the bytes."""
    leaks = _sweep(TestClient(app, raise_server_exceptions=False), _paths(planted))
    assert not leaks, ("a raw vendor price reached an unauthenticated reader:\n" +
                       "\n".join(f"  {p} -> {w}" for p, w in leaks))


def test_no_price_reaches_a_signed_in_caller(planted):
    """The signed-in surface, which is where the commitment panel lives.

    A session is not a licence. Alpaca's sentence does not distinguish who is reading, and every
    registered account on a self-hosted instance is someone other than the operator.
    """
    client = TestClient(app, raise_server_exceptions=False)
    client.cookies.set("tos_session", planted["session"])
    leaks = _sweep(client, _paths(planted))
    assert not leaks, ("a raw vendor price reached a signed-in caller:\n" +
                       "\n".join(f"  {p} -> {w}" for p, w in leaks))


def test_the_prices_are_still_stored(planted):
    """The other half of the rule, and the reason this is not simply a schema change.

    The columns stay. They are the audit trail, migration 035 seals them, and the operator needs
    them to answer a challenge to a verdict. What changes is that they never leave the database.
    """
    with db.connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT entry_price, exit_price, benchmark_entry, benchmark_exit "
                    "FROM calls WHERE id = %s", (planted["call_id"],))
        row = cur.fetchone()
    assert [str(v) for v in row] == [CALL_PRICES["entry_price"], CALL_PRICES["exit_price"],
                                     CALL_PRICES["benchmark_entry"], CALL_PRICES["benchmark_exit"]]


def test_the_dates_a_reader_recomputes_from_are_still_published(planted):
    """The measurement has to stay checkable, or removing the prices has removed the argument.

    A reader who cannot see the entry price and cannot see the entry DATE has been handed a number
    to trust. With both session dates they can price the call from any feed they like and get the
    same answer, which is the whole point of showing the dates instead.
    """
    r = TestClient(app).get(f"/api/calls/{planted['call_id']}")
    assert r.status_code == 200
    call = r.json()["call"]
    assert call["entry_session"] == "2026-01-05"
    assert call["exit_session"] == "2026-01-12"
    assert call["excess_return"] == pytest.approx(0.111111)
    assert call["verdict"] == "miss"
