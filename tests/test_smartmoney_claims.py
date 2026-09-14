"""Tests for expressing convergence signals as scoreable claims.

The point of care here is that this is the one place in the product where importing history could
look like manufacturing a track record. These tests pin down why it is not.
"""
from tradeos import ledger
from tradeos import smartmoney_claims as SMC


def test_the_mechanism_names_a_channel_not_a_direction():
    """Same bar as the impact engine: a mechanism has to say HOW, not just which way."""
    from tradeos.claims import mechanism_is_specific
    m = SMC.mechanism(5, ["insider", "13d"], "NVDA")
    assert mechanism_is_specific(m)
    assert "informational asymmetry" in m


def test_the_mechanism_explains_why_clustering_matters():
    """A single filing can be a liquidity event; several independent ones are harder to explain.
    That distinction IS the signal, so it has to be in the prose."""
    m = SMC.mechanism(4, ["insider"], "AAPL")
    assert "liquidity event" in m and "independent" in m


def test_the_mechanism_names_who_actually_filed():
    insiders = SMC.mechanism(3, ["insider"], "X")
    activists = SMC.mechanism(3, ["activist"], "X")
    assert "insiders buying on the open market" in insiders
    assert "activist stakes" in activists


def test_the_mechanism_sets_expectations_over_weeks_not_instantly():
    """Claiming an immediate effect would be contradicted by our own backtest."""
    assert "not immediately" in SMC.mechanism(3, ["insider"], "X")


# ------------------------------------------------------------------ not flattering itself

def test_stated_confidence_is_consistent_with_the_published_backtest():
    """The backtest shows ~42% at 30 days. Claiming high confidence would be contradicted by the
    Ledger the moment anyone looked at it, which is worse than claiming nothing."""
    for bucket, conf in SMC.BUCKET_CONFIDENCE.items():
        assert 0.3 <= conf <= 0.6, f"{bucket} confidence {conf} overstates a ~42% hit rate"
    assert SMC.BUCKET_CONFIDENCE["high"] > SMC.BUCKET_CONFIDENCE["low"]


def test_the_reporting_lag_is_stated_and_quantified():
    """"Some delay" is not a disclosure. The number is the disclosure."""
    assert "45 days" in SMC.LAG_NOTE
    assert "Form 4" in SMC.LAG_NOTE


# ------------------------------------------------------------------ the same yardstick

def test_imported_outcomes_use_the_ledger_s_own_verdict_rule():
    """Importing a signal's outcome must not smuggle in a second definition of "right". These
    call the same function the Ledger uses for model claims."""
    assert ledger.verdict_for("up", 0.09)[0] == "hit"
    assert ledger.verdict_for("up", -0.09)[0] == "miss"
    assert ledger.verdict_for("up", 0.001)[0] == "inconclusive"


def test_horizons_map_to_the_backtests_measurement_windows():
    assert set(SMC.HORIZON_DAYS) == {30, 90}


def test_provenance_never_appears_in_user_facing_prose():
    """An earlier version appended the dedup key to the mechanism text, which put an internal
    identifier like [convergence:43684:30] in front of every reader on the Ledger. Provenance
    belongs in a column."""
    m = SMC.mechanism(3, ["insider"], "NVDA")
    assert "convergence:" not in m and "[" not in m


def test_the_import_writes_its_key_to_a_column_not_the_mechanism():
    import inspect
    src = inspect.getsource(SMC.build)
    assert "source_ref" in src
    assert 'f"{body}' not in src, "the dedup key is being concatenated into the mechanism again"


def test_model_version_comes_from_the_cluster_not_from_max_version():
    """A claim must be stamped with the definition that PRODUCED its cluster.

    `_definition_version()` used to answer `SELECT max(version) FROM signal_definitions` with no
    name filter, and the scheduler calls this every cycle. Registering any definition numbered 5 —
    under any name at all — would therefore have restamped new claims `convergence-v5` when v3
    logic produced them, and these claims are the rows `seed-house-records` imports into `calls`,
    which the append-only trigger seals permanently. A mislabelled claim is recoverable; a
    mislabelled sealed call is not.

    The fix is provenance, not a name filter: each cluster already records its definition, so the
    query joins it.
    """
    import inspect
    src = inspect.getsource(SMC.build)
    assert "max(version)" not in src, "the version is being guessed globally again"
    assert "JOIN signal_definitions d ON d.id = c.definition_id" in src
    assert 'f"{defn_name}-v{defn_version}"' in src
    assert not hasattr(SMC, "_definition_version"), \
        "the global max(version) helper is back; it cannot see which definition made a cluster"


def test_the_import_reports_every_version_it_actually_wrote():
    """With more than one signal definition registered, a single `model_version` in the return
    value would have to pick one and be wrong about the rest. It reports the set instead, and the
    set is built from claims actually inserted rather than from what was available to insert."""
    import inspect
    src = inspect.getsource(SMC.build)
    assert "versions_written.add(model_version)" in src
    assert '"model_versions": sorted(versions_written)' in src
