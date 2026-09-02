"""Receipts: a permanent, chained, public record of market calls.

Five modules, drawn along the boundary between what must be pure and what must touch the database:

    chain.py         the hash chain. No database, no clock, no randomness — so it can be tested
                     exhaustively and reimplemented by a sceptic from the published fields alone.
    calls.py         publishing. Validation, scoreability, sealing, insertion, frozen context.
    scoring.py       resolution against end-of-day prices, benchmarked to SPY.
    record.py        composition of the public record: counts, intervals, calibration, the board.
    verification.py  proving a caller controls the audience they claim.

The product thesis is one sentence: a track record is worth nothing if the person holding it can
edit it. Everything here exists to make editing impossible and checking easy.
"""
