"""Acceptance-sweep tests — close §18.2 / §18.3 / §20.12.2 / §20.12.3.

These tests are *meta*: they assert that the platform satisfies the
acceptance checkboxes declared in
``docs/three_layer_architecture.md`` and mirrored by the
normative status table in ``docs/acceptance/v02_v03_matrix.md``.

Each test in this package is intentionally narrow and redundant with
respect to the lower-layer suites it inspects.  The redundancy is
load-bearing: if a Phase-1–5 test silently regresses or is removed,
the matching acceptance test breaks loudly, surfacing the gap in the
matrix file rather than silently lowering the platform's compliance
floor.

Slow variants (mypy strict-scope subprocess, perf baseline pinning)
are marked ``pytest.mark.slow`` and excluded from the default
``pytest tests/`` invocation.  CI's slow-lane / nightly job runs the
full set.
"""
