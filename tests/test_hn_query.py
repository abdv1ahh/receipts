"""Offline tests for the Hacker News mention query (bug B-02).

The old query sent a bare company name to Algolia, which does a fuzzy OR match. "BALL Corp" matched
every HN discussion of a ball, scoring 6,757 mentions in a window where Nvidia scored 5,303 — so a
packaging company topped the attention board and the whole surface read as noise. The fix is an
exact quoted phrase with advancedSyntax, plus keeping the legal suffix on names that are ordinary
English words. No network."""
from tradeos.ingestion.sentiment_hn import search_phrase


def test_legal_suffixes_are_stripped_so_the_phrase_matches_how_people_write():
    assert search_phrase("NVIDIA CORP", "NVDA") == '"NVIDIA"'
    assert search_phrase("Salesforce, Inc.", "CRM") == '"Salesforce"'
    assert search_phrase("Alphabet Inc.", "GOOG") == '"Alphabet"'
    assert search_phrase("Artiva Biotherapeutics, Inc.", "ARTV") == '"Artiva Biotherapeutics"'
    assert search_phrase("UNION PACIFIC CORP", "UNP") == '"UNION PACIFIC"'


def test_names_that_are_ordinary_words_keep_their_suffix():
    """Bare "Ball" counts every HN post about a ball. "BALL Corp" counts the company."""
    assert search_phrase("BALL Corp", "BALL") == '"BALL Corp"'
    assert search_phrase("POOL CORP", "POOL") == '"POOL CORP"'
    assert search_phrase("DOVER Corp", "DOV") == '"DOVER Corp"'


def test_punctuation_and_whitespace_are_normalised():
    assert search_phrase("STAR GROUP, L.P.", "SGU") == '"STAR GROUP L.P"'
    assert search_phrase("  Acme   Widgets,  Inc.  ", "ACME") == '"Acme Widgets"'


def test_falls_back_to_the_ticker_and_never_returns_an_empty_phrase():
    assert search_phrase(None, "ZZZZ") == '"ZZZZ"'
    assert search_phrase("", "ZZZZ") == '"ZZZZ"'
    assert search_phrase(None, None) is None
    assert search_phrase("Corp", "X") == '"Corp"'      # nothing left after stripping -> use it raw
