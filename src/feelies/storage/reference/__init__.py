"""Versioned reference data shipped with the platform.

Reference artefacts under this package (event calendars, holiday
schedules, exchange-tier symbol classifications) are deterministic
inputs whose hashes are folded into the bootstrap provenance bundle
(Invariant 13).  Replays must use the *same* reference snapshot the
strategy was tagged against, regardless of wall-clock date, otherwise
``Inv-5`` (replay parity) is violated.
"""
