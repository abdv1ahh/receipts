"""Slice 5: enforce Decision 8 mechanically — the preview surfaces (options, crypto) must
render ONLY bundled static fixtures and never call the backend. Anything else could let a
watermarked mockup be mistaken for measured, live data. This test fails if the preview module
ever imports the API layer or calls fetch/XHR."""
from pathlib import Path

FRONTEND = Path(__file__).resolve().parent.parent / "frontend" / "src"


def test_preview_module_never_touches_backend():
    src = (FRONTEND / "previews.jsx").read_text()
    lowered = src.lower()
    assert "./api" not in src, "previews must not import the API layer"
    assert "fetch(" not in lowered, "previews must not call fetch()"
    assert "/api/" not in src, "previews must not reference any /api route"
    assert "xmlhttprequest" not in lowered
    # it must import its bundled fixtures instead
    assert "fixtures/options.json" in src and "fixtures/crypto.json" in src


def test_preview_fixtures_are_marked_illustrative():
    for name in ("options.json", "crypto.json"):
        text = (FRONTEND / "previews" / "fixtures" / name).read_text().lower()
        assert "illustrative" in text and "not live data" in text
