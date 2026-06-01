"""Paper-RTH perf regression gate (opt-in via PERF_HOST_LABEL)."""

from __future__ import annotations

import os

import pytest

from tests.perf._pinned_baseline import load_paper_rth_baseline


@pytest.mark.skipif(
    not os.environ.get("PERF_HOST_LABEL", "").strip(),
    reason="Set PERF_HOST_LABEL to run pinned paper-RTH perf gate",
)
def test_paper_rth_baseline_present() -> None:
    baseline = load_paper_rth_baseline()
    if baseline is None:
        pytest.skip("No paper_rth baseline recorded for this host")
    assert baseline["tick_processing_p99_s"] > 0.0
    assert baseline["drain_p99_s"] >= 0.0
