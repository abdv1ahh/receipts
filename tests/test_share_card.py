"""The share card and the tags that carry it — the whole distribution model, which had never worked.

`docs/receipts_gap_analysis.md` §Finding 2: `og:image` pointed at a RELATIVE URL, and the image was
an SVG. Either defect alone produces a bare text link — the Open Graph protocol requires an
absolute URL, and no major platform renders SVG as a preview image — and both were present, on
`/r/{handle}` and on `/s/{symbol}` alike. So "checkers arrive for free when callers share their
page" was false from the day it was written.

These are the properties that must not regress:

  THE GATE      no percentage below 25 resolved calls, in EITHER renderer. A card travels further
                from its own context than anything else in this product, so it is the worst place
                to print a rate the sample cannot support.
  ABSOLUTE      every URL in the tag block, built from PUBLIC_BASE_URL and never from the Host
                header, which a client controls and which would be written into a cached public
                meta tag.
  LOSSES        as large as wins. A card that only ever showed good numbers would be an
                advertisement rather than a receipt.
  NO TOFU       the resolved font has real glyphs for the characters a caller's own name can
                contain. Measured, because Pillow's embedded face renders e-acute as a box.
"""
from __future__ import annotations

import io
import pathlib

import pytest

try:
    from PIL import Image

    from tradeos import config
    from tradeos.receipts import card
    _IMPORTS_OK = True
except Exception:                                             # pragma: no cover
    _IMPORTS_OK = False

pytestmark = pytest.mark.skipif(not _IMPORTS_OK, reason="Pillow or the package is unavailable")

ARGS = {"handle": "a-caller", "display_name": "A Caller", "links": 30, "brand": "Rhumb",
        "counts": {"hit": 12, "miss": 14, "inconclusive": 4, "unscoreable": 1, "open": 3}}


def _png(**over) -> bytes:
    base = {**ARGS, "hit_rate": None, "hit_rate_ci": None, "resolved_scoreable": 26}
    return card.receipt_card_png(**{**base, **over})


def _svg(**over) -> str:
    base = {**ARGS, "hit_rate": None, "hit_rate_ci": None, "resolved_scoreable": 26}
    return card.receipt_card_svg(**{**base, **over})


# ================================================================== the gate

def test_a_gated_record_shows_the_count_and_never_a_percentage():
    """`hit_rate is None` IS the gated case: `record.summary` refuses to return a rate below the
    gate, so a percentage cannot reach either renderer without having cleared it upstream."""
    svg = _svg(resolved_scoreable=7)
    assert "LOW N" in svg
    assert "7 resolved" in svg
    assert "%" not in svg.replace("100%", ""), "a gated SVG card printed a percentage"


def test_the_gated_png_says_low_n_and_how_far_off_it_is():
    png = _png(resolved_scoreable=7, sample_gate=25)
    assert _ink_present(png), "the card rendered blank"
    # The words are drawn, not markup, so the assertion is on the pixels differing from a card
    # rendered with a rate: same inputs, one of them gated, must not produce the same image.
    rated = _png(resolved_scoreable=40, hit_rate=0.55, hit_rate_ci=[0.4, 0.7])
    assert png != rated


def test_a_rate_is_always_accompanied_by_its_interval():
    """CLAUDE.md 0a2: never quote a rate from this ledger without the interval beside it. A share
    card is the furthest those numbers travel from their own context."""
    svg = _svg(resolved_scoreable=282, hit_rate=0.408, hit_rate_ci=[0.352, 0.466])
    assert "40.8%" in svg
    assert "95% interval" in svg and "35.2%" in svg and "46.6%" in svg


def test_the_two_renderers_agree_about_being_gated():
    """They share `_receipt_card_args` in the route so they cannot show different records, and the
    gate is the one thing that must hold in both regardless."""
    assert "LOW N" in _svg(resolved_scoreable=3)
    assert _png(resolved_scoreable=3) != _png(resolved_scoreable=3, hit_rate=0.9,
                                              hit_rate_ci=[0.8, 1.0])


# ================================================================== the image itself

def _ink_present(png: bytes) -> bool:
    img = Image.open(io.BytesIO(png)).convert("L")
    return len({*img.get_flattened_data()}) > 8        # more than a flat background


def test_the_png_is_the_open_graph_size_and_a_real_png():
    png = _png()
    img = Image.open(io.BytesIO(png))
    assert img.format == "PNG"
    assert img.size == (1200, 630) == (card.WIDTH, card.HEIGHT)


def test_the_png_is_well_inside_every_platform_byte_limit():
    """X caps a card image at 5MB, LinkedIn at 5MB, Facebook at 8MB. This is measured in the tens
    of kilobytes, and a card that ever approached those numbers would be a rendering bug."""
    assert len(_png(resolved_scoreable=282, hit_rate=0.408, hit_rate_ci=[0.352, 0.466])) < 500_000


def test_losses_are_drawn_as_large_as_wins():
    """Swapping the hit and miss counts must change the image. If the losses were smaller, or
    omitted, a mirrored record would render identically and the card would be an advertisement."""
    a = _png(counts={**ARGS["counts"], "hit": 30, "miss": 2})
    b = _png(counts={**ARGS["counts"], "hit": 2, "miss": 30})
    assert a != b


def test_a_record_with_nothing_resolved_leads_with_the_open_commitment():
    """Three zeros read as a record that has failed to produce. What is true is that a commitment
    was sealed before the outcome was known and is pending -- which is also the only part worth
    posting at that stage. The gate still refuses a percentage."""
    empty = _png(counts={"hit": 0, "miss": 0, "inconclusive": 0, "unscoreable": 0, "open": 1},
                 resolved_scoreable=0, links=1)
    assert _ink_present(empty)
    two = _png(counts={"hit": 0, "miss": 0, "inconclusive": 0, "unscoreable": 0, "open": 2},
               resolved_scoreable=0, links=2)
    assert empty != two, "the open count is not on the card"


def test_the_card_renders_for_a_handle_with_no_calls_at_all():
    """The 404 path builds one of these, so it must not divide by a zero denominator."""
    assert _ink_present(_png(counts={}, resolved_scoreable=0, links=0))


# ================================================================== no tofu

@pytest.mark.parametrize("ch", ["é", "ö", "å", "ñ", "ü", "ç"])
def test_the_card_font_has_real_glyphs_for_accented_latin(ch):
    """Measured, not assumed. Pillow 12's embedded face (Aileron) renders U+00E9 as a BOX, so a
    caller named Jose with an accent would have seen tofu where their own name should be, on the
    one asset this product asks them to post. The image installs `fonts-dejavu-core` for this."""
    assert card.font_covers(ch), f"{ch!r} renders as tofu; the card font regressed"


def test_every_face_the_card_uses_resolves():
    for face in ("sans", "bold", "mono", "serif"):
        assert card._font(40, face) is not None


def test_the_cards_own_copy_is_ascii_so_the_fallback_face_cannot_tofu_it():
    """Our words, not the caller's. `load_default` is the fallback when DejaVu is absent and it has
    no em dash, bullet, check mark or arrow, so the copy this module writes stays inside what the
    weakest available face can draw. A caller's display name is their own and is rendered as given."""
    import ast
    import inspect
    fn = ast.parse(inspect.getsource(card.receipt_card_png).lstrip()).body[0]
    # The STRING LITERALS ONLY, via the AST. A docstring and a comment are not drawn, and reading
    # the raw source made this fail on the docstring's own em dashes -- which are correct prose.
    # The docstring is `fn.body[0]`; skipping it by POSITION rather than by comparing against
    # `ast.get_docstring`, which returns the cleaned and dedented text and so never equals the raw
    # constant it came from.
    body = fn.body[1:] if (fn.body and isinstance(fn.body[0], ast.Expr)
                           and isinstance(fn.body[0].value, ast.Constant)) else fn.body
    drawn = [n.value for stmt in body for n in ast.walk(stmt)
             if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    for ch in "\u2014\u2013\u2022\u2713\u2192":
        for lit in drawn:
            assert ch not in lit, (f"{ch!r} in the card's own copy will tofu on the fallback face: "
                                   f"{lit[:60]!r}")


# ================================================================== the tags

def test_public_base_url_defaults_to_localhost_and_never_raises_for_development(monkeypatch):
    monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)
    assert config.public_base_url() == "http://localhost:8000"
    assert config.public_base_url_configured() is False


def test_public_base_url_strips_a_trailing_slash(monkeypatch):
    """Otherwise every URL built from it carries a double slash, which some scrapers normalise and
    others fetch verbatim and miss."""
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://rhumb.example/")
    assert config.public_base_url() == "https://rhumb.example"


def test_public_base_url_refuses_a_schemeless_value(monkeypatch):
    """Refused rather than coerced: guessing `http://` for a TLS site emits a mixed-content image
    URL, which is not fetched at all."""
    monkeypatch.setenv("PUBLIC_BASE_URL", "rhumb.example")
    with pytest.raises(config.ConfigError):
        config.public_base_url()


# ================================================================== the surfaces around it
#
# Read from the front end's own source, the way `test_navigation.py` does, because these guard
# properties that ARE the shape of the code. Behaviour was checked in a real browser at 375px.

SRC = pathlib.Path(__file__).resolve().parents[1] / "frontend" / "src"
_frontend = pytest.mark.skipif(not SRC.exists(), reason="frontend source is not mounted here")


@_frontend
def test_claiming_a_handle_has_its_own_route():
    """GAP 11. There was no route: the only path was to open "Publish a call", discover you had no
    handle, and meet a claim form where the publish form should have been. It is also the one thing
    this product ever asks a stranger to do, and it could not be linked to."""
    app = (SRC / "App.jsx").read_text()
    assert '"claim",' in app, "claim is not in ROUTES"
    assert 'view === "claim"' in app, "nothing renders the claim route"
    assert "ClaimView" in app
    # Off the rail on purpose: a one-time act does not earn a permanent nav item.
    nav = app[app.index("const NAV_LABELS"):app.index("const NAV_ICONS")]
    assert "claim:" not in nav


@_frontend
def test_the_claim_view_reuses_the_publish_form_rather_than_copying_it():
    """Two copies of the jurisdiction attestation and the https-only audience rule is how one of
    them ends up missing a check."""
    pub = (SRC / "publish.jsx").read_text()
    assert pub.count("function ClaimHandle(") == 1
    assert "<ClaimHandle onClaimed=" in pub
    assert pub.count("<ClaimHandle onClaimed=") == 2, "both surfaces should render the same form"


@_frontend
def test_the_verification_panel_waits_until_something_is_published():
    """GAP 3. The panel opens "Your record is live and sealed", which on a screen with zero calls
    is a sentence contradicting itself. It is also the wrong order of business: proving who you are
    matters once there is something to attach it to."""
    pub = (SRC / "publish.jsx").read_text()
    assert "state.published > 0 && <Verify" in pub


@_frontend
def test_the_record_page_prefers_the_png_card_in_its_tags():
    """The SVG stays in the page BODY, where a browser renders it sharper than any raster; the tags
    get the PNG, because a scraper will not render SVG at all."""
    app = (SRC.parents[1] / "tradeos" / "app.py").read_text()
    share = app[app.index('def receipt_share_page('):]
    share = share[:share.index("# ----")]
    assert 'image_path=png' in share
    assert '.png"' in share and '.svg"' in share, "the body should still use the SVG"
