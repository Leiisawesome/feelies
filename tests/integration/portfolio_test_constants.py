"""Shared knobs for PORTFOLIO integration tests.

Reference ``src/feelies/storage/reference/factor_loadings/loadings.json``
embeds deterministic ``_meta.as_of_ns``, so staleness is reproducible across
checkouts. The reference end-to-end session
(``SESSION_OPEN_NS`` = 2026-01-15) is one trading day after that anchor, so a
realistic operator window covers it — the suites no longer need a
century-long ceiling to dodge mtime drift.
"""

from __future__ import annotations

# 7 days — the platform-default operator window.  The embedded
# ``_meta.as_of_ns`` anchor sits one trading day before the reference
# session, well inside this window.
FACTOR_LOADINGS_MAX_AGE_SECONDS_FIXTURE = 7 * 24 * 3600
