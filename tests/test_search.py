"""Offline test for the search query cleaner: trims, caps length, and escapes LIKE wildcards so a
stray '%' or '_' is treated literally rather than as a match-all. No network, no database."""
from tradeos import search as S


def test_clean_query_trims_caps_and_escapes_wildcards():
    assert S.clean_query("  NVDA  ") == "NVDA"
    assert S.clean_query("100%") == "100\\%"           # % escaped -> literal, not match-all
    assert S.clean_query("a_b") == "a\\_b"             # _ escaped -> literal single-char
    assert S.clean_query("back\\slash") == "back\\\\slash"
    assert len(S.clean_query("x" * 200)) == 64         # length-capped
    assert S.clean_query("") == "" and S.clean_query(None) == ""
