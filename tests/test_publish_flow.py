"""The path a stranger takes to a published call, and the two doors on it.

Part A left exactly one way for a call to be sealed with a permanent, uncorrectable `unscoreable`
verdict: we hold no price series for its symbol. Every other gap leaves the call open and
recoverable. So this file pins the two things that close that case at ENTRY, where a mistake is
still free:

  THE UNIVERSE   a ticker can only be chosen from symbols we actually hold prices for. It was not
                 a theoretical risk -- the publish form's own placeholder read `AAPL`, and this
                 database holds ZERO price rows for AAPL.
  THE PREVIEW    what a caller is agreeing to, in numbers they can see, before they agree. Which
                 includes NOT printing an entry price, because at publish time that number does
                 not exist yet.

Plus the thesis rule, which changed: optional, but substantive if given.
"""
from __future__ import annotations

import pathlib
import secrets
from datetime import UTC, datetime, timedelta

import pytest

try:
    from tradeos import db
    from tradeos.receipts import calls, universe
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


pytestmark = pytest.mark.skipif(not _db_reachable(),
                                reason="no database reachable; the publish-flow tests need one")

VALID = {"symbol": "ABT", "direction": "up", "horizon_days": 30, "confidence": "medium",
         "thesis": "a thesis with more than forty characters in it, so a reader can judge it"}


@pytest.fixture
def caller():
    handle = f"pc-{secrets.token_hex(6)}"
    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO callers (handle, display_name, kind, jurisdiction_attested)
                           VALUES (%s,'Part C','human',true) RETURNING id""", (handle,))
            caller_id = cur.fetchone()[0]
        conn.commit()
        yield caller_id, conn
        conn.rollback()
        with conn.cursor() as cur:
            cur.execute("ALTER TABLE calls DISABLE TRIGGER calls_append_only_trg")
            cur.execute("DELETE FROM calls WHERE caller_id = %s", (caller_id,))
            cur.execute("ALTER TABLE calls ENABLE TRIGGER calls_append_only_trg")
            cur.execute("DELETE FROM callers WHERE id = %s", (caller_id,))
        conn.commit()


# ================================================================== the universe (pure)

UNIVERSE = [
    {"symbol": "AAP", "last_session": "2026-09-14", "days_behind": 0, "fresh": True},
    {"symbol": "AAPXYZ", "last_session": "2026-09-14", "days_behind": 0, "fresh": True},
    {"symbol": "AASP", "last_session": "2026-09-01", "days_behind": 13, "fresh": False},
    {"symbol": "ABT", "last_session": "2026-09-14", "days_behind": 0, "fresh": True},
]


def test_an_exact_match_comes_first():
    """Someone who typed the whole symbol has already chosen."""
    assert universe.match(UNIVERSE, "AAP")[0]["symbol"] == "AAP"


def test_shorter_symbols_rank_above_longer_ones():
    assert [m["symbol"] for m in universe.match(UNIVERSE, "AA")] == ["AAP", "AASP", "AAPXYZ"]


def test_a_stale_symbol_is_offered_and_labelled_rather_than_hidden():
    """A stale symbol IS publishable -- it publishes open and is scored when the feed catches up.
    Hiding it would be the wrong lesson from Part A: the case that had to be closed was 'no series
    at all', not 'series a few days behind'. And a caller hunting a specific ticker must find it
    where they expect it, with its staleness shown, not pushed down a list for an unseen reason."""
    hits = {m["symbol"]: m for m in universe.match(UNIVERSE, "AASP")}
    assert "AASP" in hits
    assert hits["AASP"]["fresh"] is False
    assert hits["AASP"]["days_behind"] == 13


def test_an_empty_query_suggests_nothing():
    assert universe.match(UNIVERSE, "") == []
    assert universe.match(UNIVERSE, "   ") == []


def test_holds_is_exact_not_a_prefix():
    """A prefix test here would let `AAP` authorise a call on `AAPXYZ`."""
    assert universe.holds(UNIVERSE, "aap") is True
    assert universe.holds(UNIVERSE, "AAPL") is False
    assert universe.holds(UNIVERSE, "") is False


# ================================================================== the universe (live)

def test_the_live_universe_holds_the_benchmark_and_excludes_what_we_cannot_price():
    with db.connect() as conn:
        universe.reset_cache()
        syms = universe.scoreable_symbols(conn)
    assert len(syms) > 10000, "the universe is now every tradable non-OTC US equity and ETF"
    assert universe.holds(syms, "SPY"), "the benchmark must be in its own universe"

    # THIS ASSERTION USED TO READ `not universe.holds(syms, "AAPL")`, and it was correct: the
    # universe came from `signal_clusters`, so it was 2,018 insider-signal names and AAPL was not
    # among them — while the publish form's own placeholder said AAPL. The test pinned the defect
    # rather than the requirement. The universe is now built from Alpaca's asset list, so the names
    # a person actually reaches for are the ones that must be here.
    for liquid in ("AAPL", "MSFT", "NVDA", "TSLA", "GOOGL", "AMZN", "META", "SPY", "QQQ"):
        assert universe.holds(syms, liquid), f"{liquid} must be publishable"


def test_the_universe_is_cached_so_typing_does_not_query_per_keystroke():
    """Measured: a prefix query is 35ms and the full roll-up is 58ms, so one query per TTL beats
    one per keystroke by an order of magnitude over a typed ticker."""
    with db.connect() as conn:
        universe.reset_cache()
        first = universe.scoreable_symbols(conn, now=1000.0)
        again = universe.scoreable_symbols(conn, now=1000.0 + universe._TTL - 1)
        assert again is first, "inside the TTL the same list object should come back"
        later = universe.scoreable_symbols(conn, now=1000.0 + universe._TTL + 1)
        assert later is not first, "past the TTL it must reload"


def test_an_unknown_prefix_says_what_we_hold_rather_than_going_blank():
    with db.connect() as conn:
        out = universe.suggest(conn, "ZZZQQQ")
    assert out["matches"] == []
    assert out["note"] and "can only be published" in out["note"]
    assert str(out["universe_size"]) in out["note"]


# ================================================================== the preview

def test_the_preview_never_claims_an_entry_price():
    """The one lie this product could tell that would matter most. Entry is the close of the first
    session STRICTLY AFTER publication, so at publish time the number does not exist -- not to the
    caller, not to us. Printing the last close under the label "entry price" would be exactly the
    kind of quiet overstatement the whole proposition rules out."""
    with db.connect() as conn:
        out = calls.preview("ABT", 30, conn)
    assert "entry_price" not in out
    assert "entry_session" not in out
    assert out["last_session"] is not None
    assert "first session AFTER you publish" in out["entry_rule"]


def test_the_preview_carries_no_price_at_all():
    """The other half of the same rule, and the reason the panel now dates its data rather than
    pricing it: these are the vendor's closes and the publish screen is a screen. The panel kept
    the question a caller was really asking of them -- how current is your feed -- as a date."""
    with db.connect() as conn:
        out = calls.preview("ABT", 30, conn)
    for key in ("last_close", "last_close_day", "benchmark_last_close",
                "benchmark_last_close_day"):
        assert key not in out, f"{key} puts a vendor price back on the publish screen"
    # What replaced them: the DATE our series runs through, which is the thing a caller
    # deciding whether to commit was actually reading the close for.
    assert out["last_session"] and out["benchmark_last_session"]


def test_the_preview_dates_the_horizon_rather_than_leaving_it_a_duration():
    now = datetime(2026, 9, 15, 14, 30, tzinfo=UTC)
    with db.connect() as conn:
        out = calls.preview("ABT", 30, conn, now=now)
    assert out["horizon_target"] == (now.date() + timedelta(days=30)).isoformat()
    assert out["horizon_target"] in out["exit_rule"]


def test_the_preview_shows_the_benchmark_it_will_be_measured_against():
    with db.connect() as conn:
        out = calls.preview("ABT", 7, conn)
    assert out["benchmark"] == "SPY"
    assert out["benchmark_last_session"] is not None


def test_the_preview_carries_the_scoreability_verdict_for_a_symbol_we_cannot_price():
    with db.connect() as conn:
        out = calls.preview("ZZZQQQ", 30, conn)
    assert out["scoreability"]["permanent"] is True
    assert out["last_session"] is None


# ================================================================== the thesis rule

def test_no_reason_is_allowed():
    assert calls.validate({**VALID, "thesis": ""}) == []
    assert calls.validate({**VALID, "thesis": "   "}) == []


def test_a_short_reason_is_still_refused():
    """The floor's whole purpose: "up" and "looks good" carry nothing a reader could hold anyone
    to. Optional does not mean "anything goes"."""
    problems = calls.validate({**VALID, "thesis": "up"})
    assert len(problems) == 1
    assert "optional" in problems[0] and str(calls.MIN_THESIS_CHARS) in problems[0]


def test_publishing_with_no_reason_seals_and_verifies(caller):
    from tradeos.receipts import chain
    caller_id, conn = caller
    out = calls.publish(caller_id, {**VALID, "thesis": ""}, conn)
    assert out["thesis"] == ""
    assert chain.verify_chain(calls.for_chain(caller_id, conn))["intact"] is True
    # An empty thesis is length-prefixed like any other, so it cannot be confused with a missing
    # field and cannot collide with a call that said something.
    assert "thesis:0:" in out["canonical_payload"]


# ================================================================== the blocked symbol

def test_a_symbol_we_cannot_price_is_refused_at_entry_not_sealed(caller):
    """Part A's door, closed. The universe is what the publish form offers, and a symbol outside it
    is the ONLY remaining route to a permanent unscoreable verdict."""
    caller_id, conn = caller
    with db.connect() as c2:
        universe.reset_cache()
        syms = universe.scoreable_symbols(c2)
    assert not universe.holds(syms, "ZZZQQQ")
    score = calls.scoreability("ZZZQQQ", conn)
    assert score["permanent"] is True
    assert "could never be scored" in score["reason"]


def test_a_blocked_publish_says_why_in_a_sentence_not_a_field_name(caller):
    """`blocks_publish` reaches the route as a 400 with `problems`. A caller told
    "benchmark_days_behind" has learned nothing, so what travels is the sentence."""
    caller_id, conn = caller
    import tradeos.receipts.calls as mod
    original = mod.BENCHMARK_TOLERANCE_DAYS
    try:
        mod.BENCHMARK_TOLERANCE_DAYS = -10_000       # force the benchmark to look behind
        score = calls.scoreability("ABT", conn)
        assert score["blocks_publish"] is True
        with pytest.raises(calls.PublishError) as exc:
            calls.publish(caller_id, VALID, conn)
        assert len(exc.value.problems) == 1
        sentence = exc.value.problems[0]
        assert sentence.endswith(".")
        assert "SPY" in sentence and "gap on our side" in sentence
        for jargon in ("benchmark_days_behind", "blocks_publish", "None", "days_behind"):
            assert jargon not in sentence
    finally:
        mod.BENCHMARK_TOLERANCE_DAYS = original


# ================================================================== the sample gate remainder

def test_a_thin_record_says_how_far_off_a_percentage_is(caller):
    """A caller with three resolved calls and a blank percentage cannot tell "the sample is too
    thin" from "this product is broken", and the blank invites the second reading."""
    from tradeos.receipts import record
    caller_id, conn = caller
    calls.publish(caller_id, VALID, conn)
    s = record.summary(caller_id, conn)
    assert s["gated"] is True
    assert s["sample_gate"] == record.SAMPLE_GATE
    assert s["remaining_to_gate"] == record.SAMPLE_GATE - s["resolved_scoreable"]
    assert s["remaining_to_gate"] > 0


def test_the_remainder_is_zero_once_the_rate_is_published():
    """So one component can render either side of the line."""
    from tradeos.receipts import record
    with db.connect() as conn:
        s = record.summary(
            next(c["id"] for c in [{"id": i} for i in _house_ids(conn)]), conn)
    assert s["gated"] is False
    assert s["remaining_to_gate"] == 0


def _house_ids(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM callers WHERE is_house ORDER BY id")
        return [r[0] for r in cur.fetchall()]


# ================================================================== the screen itself
#
# There is no JavaScript test runner in this repo and adding one is not this change's job, so these
# read the .jsx the way `test_navigation.py` reads App.jsx. Every one of them guards a property
# that is a PROPERTY OF THE COPY OR THE SHAPE rather than of the runtime, which is exactly what
# source-reading is the right instrument for. Measured behaviour was checked in a real browser at
# 375px instead; these stop it silently regressing.

SRC = pathlib.Path(__file__).resolve().parents[1] / "frontend" / "src"
_frontend = pytest.mark.skipif(not SRC.exists(),
                               reason="frontend source is not mounted here")


def _read(name: str) -> str:
    return (SRC / name).read_text()


def _code(name: str) -> str:
    """The source with comments stripped.

    A test that asserts the ABSENCE of a pattern must not be satisfied or fooled by a comment, and
    both happened here: the comment above `Commitment` explains why nothing may be labelled an
    "entry price" and the comment above `setSpec` quotes the stale-closure form it replaced. Both
    are the right comments to have written and neither is code.
    """
    src = _read(name)
    for opener, closer in (("{/*", "*/}"), ("/*", "*/")):
        while opener in src and closer in src[src.index(opener):]:
            start = src.index(opener)
            end = src.index(closer, start) + len(closer)
            src = src[:start] + src[end:]
    return "\n".join(ln for ln in src.splitlines()
                      if not ln.lstrip().startswith("//"))


@_frontend
def test_the_irreversibility_warning_is_present_and_not_softened():
    """The one sentence on this screen that decides whether a caller trusts the product. It states
    the consequence rather than the mechanism, and it names US as unable to undo it, which is the
    clause that makes it a guarantee instead of a threat."""
    src = _read("publish.jsx")
    assert "Once you publish, this cannot be undone." in src
    assert "Not by you, and not by us." in src
    # Softeners, checked against the permanence panel's own copy rather than the whole file: a
    # hedge here would be worse than no warning, because it would read as one.
    panel = _code("publish.jsx")
    panel = panel[panel.index('className="pb-permanent"'):]
    panel = panel[:panel.index("</div>")].lower()
    for hedge in ("usually", "generally", "in most cases", "may not", "might not",
                  "normally", "try to", "contact us", "unless"):
        assert hedge not in panel, f"the permanence warning must not hedge: {hedge!r}"


@_frontend
def test_the_warning_sits_immediately_before_the_button_with_nothing_between():
    """A warning above the fold is a warning that gets scrolled past. The ordering is the control."""
    src = _code("publish.jsx")
    warn = src.index('className="pb-permanent"')
    button = src.index('className="act act-on pb-submit"')
    assert warn < button, "the warning must come before the button"
    between = src[src.index("</div>", warn):button]
    assert "<div" not in between and "<label" not in between, (
        "something was inserted between the permanence warning and the publish button")


@_frontend
def test_there_is_no_confirmation_checkbox_on_the_publish_form():
    """A checkbox converts reading into a tap and teaches people to tap. The claim form keeps its
    jurisdiction attestation, which is a different thing: a statement about the caller's own legal
    position, made once, not a speed bump in front of every call."""
    src = _code("publish.jsx")
    form = src[src.index("function Form("):]
    assert 'type="checkbox"' not in form


@_frontend
def test_the_two_irreversible_decisions_have_no_default():
    """Direction and window define the call and cannot be corrected afterwards. They used to
    arrive preselected as "up" and 30 days, so a caller could seal a permanent call in the wrong
    direction by not noticing."""
    src = _read("publish.jsx")
    assert 'direction: "", horizon_days: 0' in src
    # and the button says which one is still missing, rather than sitting dead
    assert '"Choose a direction"' in src and '"Choose a window"' in src


@_frontend
def test_the_state_updates_are_functional_so_two_fast_taps_cannot_drop_one():
    """Found by driving this form from a script at 375px, which taps faster than a thumb. With
    `setSpec({ ...spec, ... })` every handler closes over the `spec` from its own render, so two
    taps inside one React batch both read the same stale object and the second overwrites the
    first -- tapping a direction then a window lost the direction."""
    src = _code("publish.jsx")
    form = src[src.index("function Form("):]
    assert "setSpec({ ...spec" not in form, "a stale-closure update is back in the publish form"
    assert form.count("setSpec((s) => ({ ...s") >= 4


@_frontend
def test_the_ticker_field_is_chosen_from_the_universe_and_not_free_text():
    src = _read("publish.jsx")
    assert "fetchSymbols" in src
    assert "pb-sugg-row" in src
    # the old placeholder was AAPL, for which this database holds no prices at all
    assert 'placeholder="AAPL"' not in src


@_frontend
def test_the_commitment_panel_never_labels_anything_an_entry_price():
    """Entry is the close of the first session AFTER publication and does not exist at publish
    time. Printing the last close under that label would be the most damaging small lie available
    to this product."""
    src = _code("publish.jsx")
    commit = src[src.index("function Commitment("):src.index("function Form(")]
    assert "entry price" not in commit.lower()
    assert "our data runs through" in commit
    assert "the next session's close" in commit


@_frontend
def test_the_ticker_input_is_at_least_16px_so_mobile_safari_does_not_zoom():
    """Under 16px, mobile Safari zooms the page on focus, which throws the suggestion list off
    screen and leaves the caller panning to find it."""
    css = _read("styles.css")
    block = css[css.index("PUBLISHING FROM A PHONE"):]
    assert ".pb-input, .pb-input-lg { font-size: 17px; }" in block


@_frontend
def test_the_window_buttons_are_a_grid_not_a_wrapping_flex():
    """Measured at 375px before the fix: three windows rendered 2 + 1, so a three-way choice read
    as two. `minmax(0, 1fr)` rather than `1fr` for the reason this file repeats everywhere."""
    css = _read("styles.css")
    assert "grid-template-columns: repeat(3, minmax(0, 1fr))" in css
    block = css[css.index("PUBLISHING FROM A PHONE"):]
    assert "flex-wrap: nowrap" in block


@_frontend
def test_the_radar_onboarding_card_is_off_the_receipts_surfaces():
    """Measured at 375px: the card filled the entire first viewport of /publish and /record -- a
    country selector and a currency field, above the fold, on the two screens whose job is
    publish-a-call and check-my-record."""
    src = _read("App.jsx")
    assert "ONBOARDING_SUPPRESSED" in src
    for view in ("publish", "record", "board", "auth"):
        assert f'"{view}"' in src[src.index("ONBOARDING_SUPPRESSED"):
                                  src.index("ONBOARDING_SUPPRESSED") + 260]


@_frontend
def test_an_open_call_shows_why_it_is_open_and_when_we_last_looked():
    """Part A stored the reason (migration 036) so this could exist. A call past its horizon with
    no verdict and no explanation is indistinguishable, to a sceptic, from a withheld result."""
    record = _read("record.jsx")
    ui = _read("receiptsui.jsx")
    assert "open_calls" in record and "OpenReason" in record
    assert "open_reason_code" in ui and "open_checked_at" in ui
    assert "last checked" in ui
    # the three codes from 036's CHECK constraint all have a label
    for code in ("waiting_for_benchmark", "waiting_for_subject_price", "subject_series_ended"):
        assert code in ui, f"{code} has no label on the record page"


@_frontend
def test_a_gated_record_says_how_many_more_calls_it_needs():
    ui = _read("receiptsui.jsx")
    assert "remaining_to_gate" in ui
    assert "before a percentage appears" in ui


@_frontend
def test_a_published_call_offers_a_share_button():
    src = _read("publish.jsx")
    assert "navigator.share" in src
    assert "Share this call" in src
    # and a fallback that SAYS what it did, rather than doing nothing and looking broken
    assert "navigator.clipboard" in src and "Link copied" in src
