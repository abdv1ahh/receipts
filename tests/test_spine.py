"""Offline tests for the event spine: classification, title normalisation, and the novelty and
velocity arithmetic. No network, no database — the pure core, which is also what makes
reprocessing stored payloads possible.

Two regressions here are from bugs found while building this phase against real data:
  * `classify` matched cues as substrings, so a story about Fed governor Kevin *Warsh* was tagged
    `conflict` because "war" is inside "Warsh";
  * cluster matching on title similarity alone merged eight different companies' 8-K filings,
    because SEC headlines are templated and the trigram match found the template.
"""
from datetime import UTC, datetime, timedelta

import pytest

from tradeos import spine

# ------------------------------------------------------------------ classification

@pytest.mark.parametrize("text,expected", [
    ("Fed holds interest rate steady at 4.25%", "monetary_policy"),
    ("ECB signals further rate cut in September", "monetary_policy"),
    ("Israel and Hamas agree ceasefire terms", "conflict"),
    ("Trump's new global tariff draws rebukes from trade partners", "trade_policy"),
    ("Suez Canal traffic halted after vessel grounding", "supply_chain"),
    ("Nvidia reported results of operations", "earnings"),
    ("Magnitude 7.1 earthquake strikes off Japan", "disaster"),
    ("OPEC agrees to cut crude output", "energy"),
    ("Ethereum completes protocol upgrade on mainnet", "protocol_upgrade"),
    ("Dockworkers begin strike at three ports", "supply_chain"),
    ("Random corporate press release about nothing", "other"),
])
def test_classify_assigns_the_expected_category(text, expected):
    assert spine.classify(text) == expected


@pytest.mark.parametrize("text", [
    "Kevin Warsh has homed in on three key phrases",   # "war" inside "Warsh"
    "Software warehouse issues a warning to customers",  # "war" inside warehouse/warning
    "Investors are fed up with the delay",               # bare "fed"
])
def test_classify_does_not_match_cues_inside_other_words(text):
    """Substring matching tagged a Fed-governor story as `conflict`. Cues are word-bounded now."""
    assert spine.classify(text) != "conflict"


def test_classify_returns_other_rather_than_guessing():
    assert spine.classify("") == "other"
    assert spine.classify("aaaa bbbb cccc") == "other"


def test_every_cue_category_is_a_declared_category():
    """A typo in the cue table would otherwise produce a category nothing downstream knows."""
    for category, _cues in spine._CATEGORY_CUES:
        assert category in spine.CATEGORIES


# ------------------------------------------------------------------ order is behaviour
#
# First match wins, so the table is sorted by how UNAMBIGUOUS each vocabulary is. `trade_policy`
# used to sit ninth behind `conflict` ("war", which is inside "trade war") and `regulation`
# ("sanction") — the two categories most likely to hold a trade-policy story were both checked
# first. 20 events in the corpus were mislabelled that way, every one a tariff story.

def _order() -> list[str]:
    return [c for c, _ in spine._CATEGORY_CUES]


@pytest.mark.parametrize("earlier,later", [
    ("trade_policy", "conflict"),      # "trade war" contains "war"
    ("trade_policy", "regulation"),    # a trade sanction is a trade instrument first
    ("trade_policy", "election"),      # tariff politics is trade policy, not campaign coverage
    ("supply_chain", "labour"),        # a dock strike is a supply story here
    ("protocol_upgrade", "technology"),
])
def test_a_specific_vocabulary_is_checked_before_one_that_would_steal_from_it(earlier, later):
    order = _order()
    assert order.index(earlier) < order.index(later), \
        f"{earlier} must be checked before {later}, or {later} claims its stories"


def test_the_most_collidable_vocabulary_is_checked_last():
    """"ai" is two letters and "chip" is a snack. Whatever else moves, technology stays last."""
    assert _order()[-1] == "technology"


def test_the_cue_table_cannot_produce_the_adapter_only_categories():
    """`macro` (ECB and Fed feeds) and `corporate` (8-K item codes) are supplied by adapters that
    know more than the cue table does — no cue anywhere spells either word. That is exactly why a
    blanket reclassify must not touch them: it would replace 65 correct labels with `other`. If a
    cue for one is ever added, the reprocess guard in cli.py needs revisiting at the same time."""
    producible = {c for c, _ in spine._CATEGORY_CUES}
    assert "macro" not in producible
    assert "corporate" not in producible
    assert spine.classify("US economy grows 2% in the quarter") != "macro"


@pytest.mark.parametrize("text,expected", [
    ("U.S. to slap 50% tariffs on Canadian goods, deepening North America trade war", "trade_policy"),
    ("Trump threatens EU with 'substantial' tariffs over fines of US tech giants", "trade_policy"),
    ("New Republican ads slam Democrats opposed to Trump's tariffs", "trade_policy"),
    ("What would 200% US tariffs on generic drugs mean for China's pharma industry?", "trade_policy"),
])
def test_real_headlines_the_old_order_mislabelled(text, expected):
    """Verbatim from the corpus. These were conflict, regulation, election and supply_chain."""
    assert spine.classify(text) == expected


def test_reordering_did_not_cost_the_categories_it_overtook():
    """A genuine war story must still be conflict, and a genuine antitrust story still regulation —
    moving trade_policy up must not have hollowed either one out."""
    assert spine.classify("Ten killed in Russian missile attack near Kyiv") == "conflict"
    assert spine.classify("Israel and Hamas agree ceasefire terms") == "conflict"
    assert spine.classify("Regulators open an antitrust lawsuit against the firm") == "regulation"
    assert spine.classify("Voters head to the polls in a referendum") == "election"


# ------------------------------------------------------------------ plurals
#
# `\btariff\b` cannot match "tariffs", so every plural fell to `other`. The corpus proved it: 37
# events containing "tariffs" sat in `other` against ZERO containing "tariff". The table had been
# patched once, by listing both "port" and "ports", and never generalised.

@pytest.mark.parametrize("singular,plural,expected", [
    ("Tariff on steel announced", "Tariffs on steel announced", "trade_policy"),
    ("Import duty raised", "Import duties raised", "trade_policy"),           # y -> ies
    ("Quota on imports set", "Quotas on imports set", "trade_policy"),        # plural on word ONE
    ("New sanction on Russia", "New sanctions on Russia", "regulation"),
    ("Investigation into the firm", "Investigations into the firm", "regulation"),
    ("Interest rate decision due", "Interest rates held steady", "monetary_policy"),
    ("Wildfire spreads in Spain", "Wildfires spread in Spain", "disaster"),
    ("Supply chain disruption worsens", "Supply chains disrupted", "supply_chain"),
    ("Export ban imposed", "Export bans imposed", "supply_chain"),
    ("Ship blocked at the port", "Ships blocked at three ports", "supply_chain"),
    ("Missile strikes a depot", "Missiles strike a depot", "conflict"),
])
def test_classify_matches_singular_and_plural_alike(singular, plural, expected):
    """Both numbers, from one cue. The plural half of each pair returned 'other' before."""
    assert spine.classify(singular) == expected
    assert spine.classify(plural) == expected


def test_the_cue_table_no_longer_lists_a_word_twice_for_its_plural():
    """"port" and "ports" were both listed — the author hit this once, patched that single word,
    and never generalised. Inflection is the general fix, so the manual pair must be gone."""
    for _category, cues in spine._CATEGORY_CUES:
        for cue in cues:
            assert spine._plural(cue) not in cues, f"{cue!r} is listed alongside its own plural"


def test_no_cue_is_a_prefix_that_word_boundaries_can_never_match():
    """"insurgen" was written as a prefix and matched NOTHING for its whole life, for exactly the
    same reason "tariff" could not match "tariffs" — the trailing \\b needs a non-word character."""
    for _category, pattern in _patterns():
        assert pattern.search("insurgen") is None or pattern.search("insurgent") is not None
    assert spine.classify("Insurgents attack a convoy") == "conflict"
    assert spine.classify("Insurgency spreads in the north") == "conflict"


@pytest.mark.parametrize("word,expected", [
    ("tariff", "tariffs"), ("duty", "duties"), ("tax", "taxes"), ("watch", "watches"),
    ("gas", "gases"), ("port", "ports"), ("day", "days"),          # vowel before y keeps the s
])
def test_plural_applies_the_three_productive_rules(word, expected):
    assert spine._plural(word) == expected


@pytest.mark.parametrize("word,expected", [
    ("ports", "port"), ("duties", "duty"), ("troops", "troop"),
    ("basis", None), ("crisis", None),        # -is words are singular already
    ("loss", None), ("gas", None),            # -ss, and too short to strip
    ("tariff", None),
])
def test_singular_only_strips_what_is_actually_a_plural(word, expected):
    assert spine._singular(word) == expected


def test_an_ambiguous_cue_can_opt_out_of_inflection():
    """Bare "strikes" is military 33 times to 2 in the corpus, and `conflict` owns only the
    compounds, so pluralising labour's "strike" would move 30 war stories into `labour`. `other` is
    the honest answer there; a wrong label is not. The opt-out must be justified, so it is asserted
    to stay small."""
    assert ("labour", "strike") in spine._NO_INFLECTION
    assert len(spine._NO_INFLECTION) <= 2, "an inflection opt-out needs a measurement, not a habit"
    assert spine.classify("Dockworkers begin strike at three ports") == "supply_chain"
    assert spine.classify("Teachers begin strike over pay") == "labour"
    assert spine.classify("Ukraine strikes Iranian vessels in the Caspian Sea") != "labour"
    assert spine.classify("US pauses strikes on Iran") != "labour"


@pytest.mark.parametrize("text", [
    "Porting the app to Linux",              # port + ing, not the plural
    "Portsmouth wins at home",               # ports inside a place name
    "Reporting season begins",
])
def test_inflection_does_not_widen_cues_into_neighbouring_words(text):
    """Inflection adds spellings; it must not soften the word boundary that stops "war" matching
    "warehouse". These would all match if a plural were implemented as a bare `s?` suffix."""
    assert spine.classify(text) == "other"


def _patterns():
    if not spine._CUE_PATTERNS:
        spine._compile_cues()
    return spine._CUE_PATTERNS


# ------------------------------------------------------------------ title normalisation

def test_normalise_strips_wire_prefixes_and_outlet_suffixes():
    """Without this, the same story from two outlets never matches."""
    assert spine.normalise_title("UPDATE 2-Fed holds rates steady") == "Fed holds rates steady"
    assert spine.normalise_title("BREAKING: Fed holds rates steady") == "Fed holds rates steady"
    assert spine.normalise_title("Fed holds rates steady - Reuters") == "Fed holds rates steady"
    assert spine.normalise_title("Fed holds rates steady | CNBC") == "Fed holds rates steady"


def test_normalise_collapses_whitespace_and_survives_junk():
    assert spine.normalise_title("  Fed   holds\n rates  ") == "Fed holds rates"
    assert spine.normalise_title("") == ""


# ------------------------------------------------------------------ novelty

def test_novelty_rewards_independent_corroboration():
    """The brief's rule: a story appearing across many sources within an hour matters."""
    broad = spine.novelty(source_count=6, event_count=6, age_hours=1, prior_similar=0)
    narrow = spine.novelty(source_count=1, event_count=6, age_hours=1, prior_similar=0)
    assert broad > narrow


def test_novelty_punishes_the_tenth_rewrite():
    """Ten reports from one source is repetition, not information."""
    fresh = spine.novelty(source_count=3, event_count=3, age_hours=1, prior_similar=0)
    rehash = spine.novelty(source_count=3, event_count=30, age_hours=1, prior_similar=0)
    assert fresh > rehash


def test_novelty_falls_for_a_story_already_running():
    new_topic = spine.novelty(source_count=4, event_count=4, age_hours=1, prior_similar=0)
    ongoing = spine.novelty(source_count=4, event_count=4, age_hours=1, prior_similar=8)
    assert new_topic > ongoing


def test_novelty_is_bounded_and_handles_the_empty_case():
    assert spine.novelty(0, 0, 0, 0) == 0.0
    assert 0.0 <= spine.novelty(99, 99, 0, 0) <= 1.0
    assert 0.0 <= spine.novelty(1, 1, 999, 99) <= 1.0


# ------------------------------------------------------------------ velocity + amplification

def _curve(points):
    """[(hours_ago, events, sources)] -> the stored curve shape."""
    now = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)
    return [{"at": (now - timedelta(hours=h)).isoformat(), "events": e, "sources": s}
            for h, e, s in points]


def test_amplification_measures_rate_not_total():
    """Fifty reports over a week must not outrank ten in an hour."""
    slow = spine.amplification(_curve([(48, 40, 6), (0, 50, 6)]))
    fast = spine.amplification(_curve([(1, 0, 4), (0, 10, 4)]))
    assert fast > slow


def test_amplification_needs_two_points():
    assert spine.amplification([]) == 0.0
    assert spine.amplification(_curve([(0, 5, 2)])) == 0.0


def test_amplification_is_bounded():
    assert 0.0 <= spine.amplification(_curve([(1, 0, 20), (0, 500, 20)])) <= 1.0


def test_trend_names_the_direction_a_single_number_hides():
    accelerating = _curve([(2, 1, 1), (1, 3, 2), (0, 9, 4)])
    fading = _curve([(2, 1, 1), (1, 9, 4), (0, 10, 4)])
    steady = _curve([(2, 1, 1), (1, 3, 2), (0, 5, 3)])
    assert spine.trend(accelerating) == "accelerating"
    assert spine.trend(fading) == "fading"
    assert spine.trend(steady) == "steady"
    assert spine.trend(_curve([(0, 1, 1)])) == "steady"      # not enough history to claim a trend


# ------------------------------------------------------------------ entity identity

def test_entity_values_are_normalised_for_comparison():
    """Cluster matching compares these; case drift would split a company from itself."""
    assert spine._entity_values([{"kind": "ticker", "value": "nvda"},
                                 {"kind": "ticker", "value": "NVDA"}]) == ["NVDA"]
    assert spine._entity_values([]) == []
    assert spine._entity_values([{"kind": "ticker"}]) == []   # no value -> not an identity


def test_no_cue_carries_padding_whitespace():
    """Cues are word-bounded, so a cue like "port " compiles to a pattern that can never match.
    This silently disabled supply-chain detection until a test caught it."""
    for _category, cues in spine._CATEGORY_CUES:
        for cue in cues:
            assert cue == cue.strip(), f"cue {cue!r} has padding whitespace"


# ------------------------------------------------------------------ cross-outlet matching

def test_distinctive_words_keeps_proper_nouns_and_drops_topic_vocabulary():
    """The distinction that makes weak-band clustering safe. Measured on real pairs: two reports of
    one event share WHO and WHERE; two unrelated stories share only subject vocabulary."""
    same_a = spine.distinctive_words("Four Palestinians and two Israelis killed in West Bank")
    same_b = spine.distinctive_words("Funerals held for four Palestinians killed in raid")
    assert same_a & same_b                                    # shares "Palestinians"

    diff_a = spine.distinctive_words("AI is 'not smart' so what's next in artificial intelligence")
    diff_b = spine.distinctive_words("Amazon cuts jobs in its artificial general intelligence unit")
    assert not (diff_a & diff_b)                              # "artificial intelligence" is lowercase


def test_a_headline_leading_with_its_subject_still_yields_it():
    """Skipping the first word outright lost the proper noun headlines most often lead with."""
    assert "india" in spine.distinctive_words("India's youth call off protest")


def test_possessives_are_normalised():
    assert spine.distinctive_words("India's minister") == spine.distinctive_words("India minister")


def test_common_headline_openers_are_not_treated_as_subjects():
    for opener in ("Four killed in blast", "These are the winners", "Why markets fell"):
        words = spine.distinctive_words(opener)
        assert not (words & {"four", "these", "why"})


def test_the_weak_band_sits_below_the_strong_one():
    assert 0 < spine.WEAK_SIMILARITY < spine.SIMILARITY
