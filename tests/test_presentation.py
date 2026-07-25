"""Offline tests for the presentation layer: the 0-100 Smart Money Score transform and the
plain-language cluster story. No network, no database.

The Score is display only, so these tests pin its shape (monotonic, continuous, anchored to
the real bucket edges) rather than any predictive claim. The story tests assert it states
facts and names real actors — and never emits a directive (the advice line)."""
from tradeos import presentation as pr

# --------------------------------------------------------------- Smart Money Score

def test_score_anchors_to_bucket_edges():
    assert pr.smart_money_score(0) == 0
    assert pr.smart_money_score(3) == 50    # medium begins
    assert pr.smart_money_score(6) == 75    # high-conviction begins
    assert pr.smart_money_score(-5) == 0    # clamped
    assert pr.smart_money_score(10_000) == 100


def test_score_is_monotonic_and_bounded():
    prev = -1
    x = 0.0
    while x <= 40:
        s = pr.smart_money_score(x)
        assert 0 <= s <= 100
        assert s >= prev, f"score dropped at raw={x}"
        prev = s
        x += 0.1


def test_score_high_end_is_rare():
    # a huge convergence approaches but does not cheaply hit 100
    assert 85 <= pr.smart_money_score(9) <= 90
    assert pr.smart_money_score(12) < 96


# --------------------------------------------------------------------- story

def _c(subtype, voice, magnitude=None):
    return {"subtype": subtype, "voice": voice, "magnitude": magnitude}


def test_story_names_marquee_actors_and_counts_the_rest():
    contribs = [
        _c("stake_13d_new", "filer:900", 8.0),
        _c("insider_purchase", "insider:111", 5_000_000),
        _c("insider_purchase", "insider:222", None),
        _c("insider_purchase", "insider:333", None),
        _c("holding_13f", "filer:500", 1_000_000),
    ]
    names = {"filer:900": "Elliott Management", "filer:500": "Berkshire Hathaway"}
    story = pr.cluster_story(contribs, names)

    # activist leads (named), insiders counted (unnamed), fund named
    assert story["bullets"][0]["text"] == "Elliott Management filed a new 13D activist stake"
    assert any(b["text"] == "3 insiders bought on the open market" for b in story["bullets"])
    assert any("Berkshire Hathaway" in b["text"] for b in story["bullets"])
    # headline is the two most salient facts
    assert story["headline"].startswith("Elliott Management filed a new 13D")

    # protagonists carry profile references the UI can link to
    prot = {p["name"]: p for p in story["protagonists"]}
    assert prot["Elliott Management"]["kind"] == "institution"
    assert prot["Elliott Management"]["id"] == 900
    assert prot["Elliott Management"]["role"] == "Activist"


def test_story_distinct_voices_not_double_counted():
    # one insider filing three purchase lines is still one buyer
    contribs = [_c("insider_purchase", "insider:111") for _ in range(3)]
    story = pr.cluster_story(contribs, {})
    assert any("1 insider" in b["text"] for b in story["bullets"])


def test_score_card_svg_renders_and_escapes():
    svg = pr.score_card_svg("NVDA", "NVIDIA Corp", 87, "high", "4 insiders bought & <Elliott> filed")
    assert svg.startswith("<svg") and svg.rstrip().endswith("</svg>")
    assert ">NVDA<" in svg and ">87<" in svg
    assert "Not investment advice" in svg          # non-removable honesty footer
    assert "<Elliott>" not in svg and "&lt;Elliott&gt;" in svg   # XML-escaped, no injection


def test_score_card_svg_handles_no_signal():
    svg = pr.score_card_svg("ZZZ", "", None, None, "No active convergence right now")
    assert ">—<" in svg and "NO ACTIVE SIGNAL" in svg


def test_story_is_descriptive_never_a_directive():
    contribs = [
        _c("stake_13d_new", "filer:900"),
        _c("insider_purchase", "insider:111"),
        _c("stake_13g", "filer:700"),
        _c("holding_13f", "filer:500"),
    ]
    story = pr.cluster_story(contribs, {})
    blob = (story["headline"] + " " + " ".join(b["text"] for b in story["bullets"])).lower()
    for banned in ("buy ", "sell", "should", "recommend", "target", "will ", "guaranteed"):
        assert banned not in blob, f"story emitted a directive-ish word: {banned!r}"
