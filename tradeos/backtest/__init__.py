"""Backtest + calibration: the platform's central honesty claim, made measurable.

The scoring of forward returns, episode de-duplication, and calibration statistics are pure
functions over price series and cluster lists (engine.py), kept separate from the DB drivers
(run.py) so they are deterministic and offline-testable with clearly-fictional price paths.
Look-ahead is structurally impossible: forward returns only read prices on/after entry, and
entry is always the first trading day AFTER the signal's as_of.
"""
