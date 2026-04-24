"""Per-host pinned perf baselines consumed by the perf-gate tests.

The JSON files in this package are *opt-in* per host (matched by the
``host_label`` field).  Operators record a baseline by running:

    CI_BENCHMARK=1 python scripts/record_perf_baseline.py \\
        --host-label <stable_host_id>

Tests that consume these baselines fall back to the ratio-only
v0.2 assertion when no entry exists for the running host's label.
This keeps the gates non-flaky on machines whose owners have not
yet recorded a baseline, while still allowing tighter gates on
machines that have.
"""
