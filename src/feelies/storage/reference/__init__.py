"""Versioned reference data shipped with the platform.

YAML / JSON fixtures live under this package (alongside Python modules)
— see :mod:`feelies.storage.reference.paths` for canonical ``Path`` constants.

Reference artefacts (event calendars, factor loadings, sector maps) are
deterministic inputs whose hashes are folded into the bootstrap provenance
bundle (Invariant 13).  Replays must use the *same* reference snapshot the
strategy was tagged against, regardless of wall-clock date, otherwise
``Inv-5`` (replay parity) is violated.
"""
