"""Shared knobs for PORTFOLIO integration tests.

Reference ``data/reference/factor_loadings/loadings.json`` is committed with a
real file mtime.  Operator default ``factor_loadings_max_age_seconds`` (7 days)
is appropriate for live configs but makes tests fail once the checkout ages
past that window.  Integration suites pin a generous ceiling so Inv-5 replay
and structural wiring — not artefact freshness — are what fail.
"""

from __future__ import annotations

# ~100 years — effectively “ignore mtime drift” for committed reference json.
FACTOR_LOADINGS_MAX_AGE_SECONDS_FIXTURE = 100 * 365 * 24 * 3600
