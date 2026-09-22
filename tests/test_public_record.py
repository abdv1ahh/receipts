"""The signed-out record page at /r/{handle}: what a stranger sees after tapping a shared link.

This is the page the whole distribution loop lands on. The visitor has no account, no context and
no patience, so the rules it has to hold are narrow and they are all about not asking anything of
them:

  NOTHING BUT THE RECORD.      No sidebar, no research rail, no search field, no upgrade button, no
                               notification bell. A stranger following a caller's link was landing
                               inside eleven surfaces that 401 for them.
  LOSSES IN THE OPEN.          Misses render in the markup, above the breakdowns, with no toggle
                               and no disclosure element around them.
  THE GATE TRAVELS.            Below 25 resolved calls the page shows counts and says why, and no
                               percentage appears anywhere in the document.
  THE CHECK IS THE VISITOR'S.  `/api/receipts/{handle}/chain` hands over the sealed fields and
                               states no verdict; the browser recomputes the hashes itself. A
                               server that answers "intact: true" is the operator asking to be
                               trusted, on the one page whose argument is that you need not.

The last of those is why `tradeos/receipts/verify.js` exists as a file rather than as an inline
script: `script-src 'self'` means an inline one is refused by the browser silently, which would
leave the flagship interaction of the product dead on the page with nothing in the logs.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import re
import secrets
import shutil
import subprocess

import pytest

try:
    from fastapi.testclient import TestClient

    from tradeos import db
    from tradeos.app import app
    from tradeos.receipts import calls as receipts_calls
    from tradeos.receipts import chain as receipts_chain
    from tradeos.receipts import record as receipts_record
    _IMPORTS_OK = True
except Exception:                                             # pragma: no cover
    _IMPORTS_OK = False

VERIFY_JS = pathlib.Path(__file__).resolve().parents[1] / "tradeos" / "receipts" / "verify.js"

# Absent inside the API image, which carries no node — the frontend is built in a separate stage.
# So the two cross-language tests below SKIP under `make test` and run from a checkout, where node
# is already a prerequisite for `make web`. They are the only guard against the sealed wire format
# drifting between `chain.py` and `verify.js`, so run them from the host after touching either.
NODE = shutil.which("node")


def _run_node(source: str, tmp_path: pathlib.Path) -> dict:
    """Run one ES module under node and return the JSON it prints on its last line."""
    harness = tmp_path / "run.mjs"
    harness.write_text(source)
    proc = subprocess.run(                                    # noqa: S603 - our own file, no shell
        [NODE, str(harness)], capture_output=True, text=True, timeout=60, check=False)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


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
                                reason="no database reachable; the public record page needs one")

HOUSE = "convergence-v3"
VALID = {"symbol": "ABT", "direction": "up", "horizon_days": 30, "confidence": "medium",
         "thesis": "a thesis with more than forty characters in it, so a reader can judge it"}


def _visible_text(html: str) -> str:
    """The words on the page, with the stylesheet, the script and every tag removed."""
    stripped = re.sub(r"<(style|script)\b[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    return re.sub(r"<[^>]+>", " ", stripped)


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def thin_caller():
    """A real caller with one real call: the gated case, which cannot be faked into existence."""
    handle = f"test-{secrets.token_hex(6)}"
    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO callers (handle, display_name, kind, jurisdiction_attested)
                           VALUES (%s, 'Thin Record', 'human', true) RETURNING id""", (handle,))
            caller_id = cur.fetchone()[0]
        conn.commit()
        receipts_calls.publish(caller_id, VALID, conn)
        yield caller_id, handle
        conn.rollback()
        with conn.cursor() as cur:
            cur.execute("ALTER TABLE calls DISABLE TRIGGER calls_append_only_trg")
            cur.execute("DELETE FROM calls WHERE caller_id = %s", (caller_id,))
            cur.execute("ALTER TABLE calls ENABLE TRIGGER calls_append_only_trg")
            cur.execute("DELETE FROM callers WHERE id = %s", (caller_id,))
        conn.commit()


# ------------------------------------------------------------------ the page is the record

def test_the_share_page_is_the_record_and_not_a_link_to_it(client):
    """It used to be a card image and an "open the full record" link, which asked a stranger to
    click twice before seeing anything they could judge."""
    html = client.get(f"/r/{HOUSE}").text
    assert "323" in html, "the number of sealed calls belongs on the page"
    # Every call, with its outcome, in the document itself.
    assert html.count("rc-call-row") >= 300, "every call has to be on the page, not a sample"
    for word in ("hit", "miss", "inconclusive", "unscoreable"):
        assert word in html


def test_the_share_page_shows_losses_with_no_interaction_needed(client):
    """Not behind a toggle, not inside a <details>, not below the breakdowns."""
    html = client.get(f"/r/{HOUSE}").text
    assert "<details" not in html.lower(), "a visitor must not have to open anything to see a loss"
    # Ordering asserted over the visible text, not the markup: the stylesheet carries comments
    # that name the sections, and matching one of those reports an ordering that no reader sees.
    text = _visible_text(html).lower()
    losses, calibration = text.find("the losses"), text.find("calibration")
    assert 0 < losses < calibration, "losses come before the breakdowns"


def test_the_share_page_carries_no_app_chrome(client):
    """GAP 5. A signed-out visitor was landing inside the research terminal."""
    html = client.get(f"/r/{HOUSE}").text
    for chrome in ("side-nav", "topsearch", "upgrade-btn", "ask-ai", "bell-badge", "nav-item"):
        assert chrome not in html, f"{chrome} is app chrome and does not belong on a shared page"


def test_the_share_page_asks_for_exactly_one_thing(client):
    """A visitor who is impressed wants their own record. That is the only ask on the page, so it
    is the only link back into the product: no sign-in, no pricing, no board, no methodology page.
    A caller's own audience link is not one of ours and is not counted."""
    html = client.get(f"/r/{HOUSE}").text
    internal = re.findall(r'href="(/[^"]*)"', html)
    assert internal == ["/claim"], f"expected only /claim, found {internal}"


def test_the_share_page_states_the_identity_note_from_its_one_definition(client, thin_caller):
    """A visitor must not assume the handle belongs to who it says.

    The sentence is `record.identity_note`, byte for byte — the same words the API and the in-app
    record surface print. Two copies of a claim about what we have and have not verified would
    drift, and the copy that drifts is the one that overstates.
    """
    _caller_id, handle = thin_caller
    with db.connect() as conn:
        caller = receipts_record.caller(handle, conn)
    assert "Nobody has verified" in caller["identity_note"]     # the fixture is unverified
    assert caller["identity_note"] in client.get(f"/r/{handle}").text


def test_a_house_record_says_it_is_ours(client):
    """The one exemption from the note above, and it has to say something stronger rather than
    nothing: a house record that reads like anyone else's is the one dishonest thing here."""
    html = client.get(f"/r/{HOUSE}").text
    assert "our own signal engine" in html
    assert "not a person" in html


def test_a_gated_share_page_shows_counts_and_says_what_is_missing(client, thin_caller):
    """Below the gate the page shows the counts, the distance to the gate and the reason, and none
    of the language that only exists when a rate has been earned.

    Not "the page contains no % sign": the scoring rules on this page legitimately name the 2%
    noise floor, which is a constant rather than anything about this caller, and an assertion loose
    enough to allow that is loose enough to allow a hit rate through. The rate itself is pinned one
    level down, on the only function that could print one.
    """
    _caller_id, handle = thin_caller
    html = client.get(f"/r/{handle}").text
    text = _visible_text(html)

    assert "rate is not shown" in html          # the link preview says so too
    assert "too few to rate" in text
    assert str(receipts_record.SAMPLE_GATE) in text
    for earned in ("right on", "average excess per call", "95% interval", "coin flip"):
        assert earned not in text, f"{earned!r} belongs to a record that has cleared the gate"

    # The preview travels furthest from its own context, so it is the worst possible place to
    # print a rate the sample cannot support.
    og = re.search(r'property="og:description" content="([^"]*)"', html).group(1)
    assert not re.search(r"\d+(\.\d+)?\s*%", og), og


def test_the_rate_block_cannot_print_a_rate_the_sample_did_not_earn():
    """`record.summary` withholds every percentage below the gate, and this is the one function on
    the public page that renders them. Asserted directly so no future caller can pass a rate around
    the gate by handing this one in."""
    from tradeos.receipts import page as receipts_page
    gated = {"gated": True, "resolved_scoreable": 4, "sample_gate": 25, "remaining_to_gate": 21,
             "gate_reason": "four calls is not a sample.", "hit_rate": None, "hit_rate_ci": None,
             "expectancy": None, "expectancy_ci": None, "z_vs_coinflip": None,
             "sample_needed_1pct": None}
    block = receipts_page._rate(gated)
    assert "%" not in re.sub(r'style="[^"]*"', "", block)
    assert "4" in block and "21" in block and "25" in block


def test_an_open_call_says_why_it_is_still_open(client, thin_caller):
    _caller_id, handle = thin_caller
    html = client.get(f"/r/{handle}").text
    assert "Open calls" in html
    assert "ABT" in html


# ------------------------------------------------------------------ the check is the visitor's

def test_the_chain_endpoint_answers_without_a_session(client):
    assert client.get(f"/api/receipts/{HOUSE}/chain").status_code == 200
    assert client.get("/api/receipts/nobody-holds-this/chain").status_code == 404


def test_the_chain_endpoint_states_no_verdict_of_its_own(client):
    """The server hands over the sealed bytes and stops. Anything else is "trust me"."""
    body = client.get(f"/api/receipts/{HOUSE}/chain").json()
    for verdict_key in ("intact", "broken_at_seq", "checked"):
        assert verdict_key not in body, f"{verdict_key} is the browser's answer to compute"
    assert body["fields"] == list(receipts_chain.SEALED_FIELDS)
    assert body["genesis"] == receipts_chain.GENESIS_HASH


def test_the_chain_endpoint_sends_exactly_what_the_browser_must_hash(client):
    """The wire contract, pinned. Each link's rendered field values, re-framed with the documented
    rule, must reproduce the stored content_hash — otherwise a browser doing it correctly would
    report a healthy record as broken."""
    body = client.get(f"/api/receipts/{HOUSE}/chain").json()
    prev = receipts_chain.GENESIS_HASH
    for link in body["links"]:
        payload = "\n".join(
            f"{name}:{len(str(link['values'][name]).encode('utf-8'))}:{link['values'][name]}"
            for name in body["fields"])
        digest = hashlib.sha256((prev + payload).encode("utf-8")).hexdigest()
        assert link["prev_hash"] == prev, f"link {link['seq']} does not chain from the one before"
        assert digest == link["content_hash"], f"link {link['seq']} does not reproduce its hash"
        prev = digest


def test_the_chain_endpoint_matches_the_modules_own_canonical_payload(client):
    """Belt and braces on the above: the rendered values must frame up to the byte-identical
    payload `chain.canonical_payload` produces from the database row, so the two can never drift
    into agreeing with each other and disagreeing with what was sealed."""
    body = client.get(f"/api/receipts/{HOUSE}/chain").json()
    with db.connect() as conn:
        caller = receipts_record.caller(HOUSE, conn)
        sealed = receipts_calls.for_chain(caller["id"], conn)
    by_seq = {c["seq"]: c for c in sealed}
    for link in body["links"][:25]:
        expected = receipts_chain.canonical_payload(by_seq[link["seq"]])
        got = "\n".join(
            f"{name}:{len(str(link['values'][name]).encode('utf-8'))}:{link['values'][name]}"
            for name in body["fields"])
        assert got == expected


# ------------------------------------------------------------------ the script that does it

def test_the_verifier_is_served_as_a_file_because_an_inline_script_is_refused(client):
    """`script-src 'self'`. An inline script would be blocked by the browser with nothing in our
    logs, leaving the flagship interaction dead on the page."""
    res = client.get("/receipt-verify.js")
    assert res.status_code == 200
    assert "javascript" in res.headers["content-type"]
    html = client.get(f"/r/{HOUSE}").text
    assert "/receipt-verify.js" in html
    inline = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", html, re.S)
    assert not [s for s in inline if s.strip()], "an inline script cannot run under this CSP"


@pytest.mark.skipif(NODE is None, reason="node is not on PATH; `make test-js` is the guard that "
                                         "always runs — see tests/verify_js_check.mjs")
def test_the_browsers_verifier_agrees_with_the_server_on_the_real_chain(client, tmp_path):
    """The two implementations, over 323 real links rather than a fixture.

    The routine guard against `chain.py` and `verify.js` drifting is `make test-js`, which checks
    both against one committed fixture and runs everywhere node does. This adds the thing a fixture
    cannot: the actual published record, with the actual text callers and importers wrote in it.
    It skips under `make test` because the API image carries no node, so run it from a checkout
    after touching either side of the wire format.
    """
    body = client.get(f"/api/receipts/{HOUSE}/chain").json()
    data = tmp_path / "chain.json"
    data.write_text(json.dumps(body))
    out = _run_node(
        f'import {{ verifyChain }} from "{VERIFY_JS}";\n'
        'import { readFileSync } from "node:fs";\n'
        f'const body = JSON.parse(readFileSync("{data}", "utf8"));\n'
        "const out = await verifyChain(body);\n"
        "console.log(JSON.stringify({ intact: out.intact, checked: out.checked, head: out.head }));\n",
        tmp_path)
    with db.connect() as conn:
        caller = receipts_record.caller(HOUSE, conn)
        server = receipts_chain.verify_chain(receipts_calls.for_chain(caller["id"], conn))
    assert out["intact"] is server["intact"] is True
    assert out["checked"] == server["checked"] == 323
    assert out["head"] == server["head"], "the two implementations disagree about the chain head"


# ------------------------------------------------------------------ what a caller can type

def test_every_string_a_caller_controls_is_escaped():
    """A thesis renders on this page only on a resolved miss, so it is tested where it is reached:
    against the renderer, with no database in the way.

    Pure rather than end-to-end on purpose. The display name and the bio are covered against a
    real row in `test_receipts_api.py`; the point of this one is that the remaining two caller
    strings cannot put markup on a page whose whole purpose is to be posted everywhere.
    """
    from tradeos.receipts import page as receipts_page

    hostile = '</style><script>alert(1)</script><img src=x onerror="alert(2)">'
    losses = receipts_page._losses(
        [{"symbol": "AAPL", "direction": "up", "excess_return": -0.11,
          "thesis": hostile, "published_at": "2026-01-01T00:00:00Z"}], total=1)
    # The dangerous forms, not the substrings: once the angle brackets and the quotes are escaped
    # the words `script` and `onerror` survive as inert text, which is correct — a caller is
    # allowed to write about them.
    assert "<script" not in losses and "<img" not in losses and 'onerror="' not in losses
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in losses

    # `verdict_note` is written by the scorer rather than by a caller, and is escaped anyway: the
    # cost is one function call and the alternative is a rule about which server strings are safe.
    listed = receipts_page._all_calls(
        [{"seq": 1, "symbol": "AAPL", "direction": "up", "horizon_days": 30,
          "verdict": "unscoreable", "verdict_note": hostile, "excess_return": None,
          "published_at": "2026-01-01T00:00:00Z"}])
    assert "<script" not in listed and "<img" not in listed and 'onerror="' not in listed


# ------------------------------------------------------------------ an interval that does not exist

def test_a_record_past_the_gate_with_no_measurable_return_has_no_interval():
    """`[None, None]` is not an interval and must never be returned as one.

    `mean_ci([])` reports lo and hi as None, and `_compute` wrapped them in a list regardless. A
    caller past the sample gate whose resolved calls all carry a NULL excess return therefore got
    `expectancy_ci: [None, None]` — which crashed the public page with a TypeError on
    `eci[0] < 0 < eci[1]`, and which the React surface treated as truthy and rendered as "this
    sample does show an effect of not scored per call".

    One is a 500 on the page a stranger lands on and the other is a false statement about somebody
    else's record. Fixed at the source, in `record._compute`, so neither surface has to guard it.
    """
    from tradeos.receipts import page as receipts_page
    from tradeos.receipts import record as receipts_rec

    summary = receipts_rec._compute((20, 6, 0, 0, 0), [])
    assert summary["gated"] is False, "26 resolved calls is past the gate; the setup is the point"
    assert summary["expectancy"] is None
    assert summary["expectancy_ci"] is None, "an absent interval is None, never [None, None]"
    assert "not scored" in receipts_page._rate(summary)      # renders, and says what is missing
