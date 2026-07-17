"""Signals: versioned, hash-locked computations over the point-in-time store.

A signal never silently changes meaning — the computing module is fingerprinted and the
compute command refuses to run unless the fingerprint matches a registered definition.
"""
