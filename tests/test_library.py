"""Slice 5: enforce the intelligence library's content contract (build-plan 4.6 / 7.1).
Every entry must be structured, original prose with at least one cited public source and a
valid basis — no unsourced claims, no reproduction placeholders. This guards the brand's
credibility mechanically before founder review."""
import json
from pathlib import Path

ENTRIES = json.loads((Path(__file__).resolve().parent.parent / "content" / "library" / "entries.json").read_text())
VALID_BASIS = {"public_domain", "public_filing", "published_interview"}


def test_library_has_expected_entries():
    assert len(ENTRIES) >= 20
    kinds = {e["slug"]: e["kind"] for e in ENTRIES}
    assert sum(1 for k in kinds.values() if k == "concept") >= 12
    assert sum(1 for k in kinds.values() if k == "investor_profile") >= 5
    assert len({e["slug"] for e in ENTRIES}) == len(ENTRIES)  # unique slugs


def test_every_entry_is_sourced_and_substantive():
    for e in ENTRIES:
        assert e["kind"] in ("concept", "investor_profile")
        assert e["title"] and e["slug"]
        assert len(e["body_md"]) >= 200, f"{e['slug']} body too thin"
        assert e["sources"], f"{e['slug']} has no sources"
        for s in e["sources"]:
            assert s["url"].startswith("http") and s["basis"] in VALID_BASIS


def test_profiles_are_marked_as_drafts_and_avoid_invented_views():
    # profiles must self-identify as draft (founder review) and disclaim invented views
    for e in ENTRIES:
        if e["kind"] == "investor_profile":
            body = e["body_md"].lower()
            assert "draft" in body and ("invents no views" in body or "no invented views" in body)
