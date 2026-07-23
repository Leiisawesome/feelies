"""Opt-in decay-weighting performance gate.

The test times the affected composition pipeline with decay enabled and
disabled. A within-run hard limit catches large regressions; the 5% policy
budget emits a warning because wall-clock noise makes it unsuitable as a hard
CI limit. A host baseline, when configured, also guards decay-off throughput.

``scripts/record_perf_baseline.py`` parses the ``PHASE4_1_PERF_SUMMARY`` line,
so its shape is an interface.

Run::

    CI_BENCHMARK=1 pytest tests/perf/test_phase4_1_no_regression.py -s
    # record a per-host baseline:
    CI_BENCHMARK=1 python scripts/record_perf_baseline.py --host-label dev_local
"""

from __future__ import annotations

import os
import statistics
import time

import pytest

from tests.determinism.test_sized_intent_replay import _replay
from tests.perf._pinned_baseline import load_pinned_baseline


pytestmark = pytest.mark.skipif(
    os.environ.get("CI_BENCHMARK") != "1",
    reason="decay-overhead perf gate; opt-in via CI_BENCHMARK=1",
)


# Full composition replays per timed trial.
_INNER_REPLAYS: int = 200
# The least-contended trial is the lowest-noise estimate.
_TRIALS: int = 9

# Documented 5% policy budget.
_POLICY_BUDGET_FACTOR: float = 1.05
# Headroom keeps the hard gate stable under wall-clock noise.
_HARD_GATE_FACTOR: float = 1.25


def _time_replay(*, decay: bool) -> tuple[float, float]:
    """Return (best_seconds, median_seconds) over ``_TRIALS`` trials.

    Each trial runs ``_INNER_REPLAYS`` deterministic composition replays.  The
    work is identical every trial (Inv-5: same inputs, same outputs); only the
    wall-clock varies, which is exactly what a perf gate measures.
    """
    trials: list[float] = []
    for _ in range(_TRIALS):
        t0 = time.perf_counter()
        for _ in range(_INNER_REPLAYS):
            _replay(decay=decay)
        trials.append(time.perf_counter() - t0)
    return min(trials), statistics.median(trials)


def test_phase4_1_decay_overhead_within_budget() -> None:
    # NOTE: deliberately no ``capsys`` — ``scripts/record_perf_baseline.py``
    # runs this node with ``pytest -q -s`` and greps the real subprocess
    # stdout for ``PHASE4_1_PERF_SUMMARY``; consuming the output via
    # ``capsys.readouterr()`` would hide the line from the recorder.

    # Warm both paths so import / first-touch costs do not skew trial 1.
    for _ in range(50):
        _replay(decay=False)
        _replay(decay=True)

    off_best, off_median = _time_replay(decay=False)
    on_best, on_median = _time_replay(decay=True)

    ratio = on_best / off_best if off_best > 0 else float("inf")
    overhead_pct = (ratio - 1.0) * 100.0

    # Parsed verbatim by scripts/record_perf_baseline.py (_PHASE4_1_RE).
    print(
        "PHASE4_1_PERF_SUMMARY "
        f"baseline_best={off_best:.6f}s "
        f"baseline_median={off_median:.6f}s "
        f"extended_best={on_best:.6f}s "
        f"extended_median={on_median:.6f}s "
        f"ratio={ratio:.4f} "
        f"overhead_pct={overhead_pct:.2f} "
        f"inner={_INNER_REPLAYS} trials={_TRIALS}"
    )

    # Soft policy budget — surface a ≤5 % breach without failing CI on noise.
    if ratio > _POLICY_BUDGET_FACTOR:
        print(
            "PHASE4_1_BUDGET_WARNING "
            f"decay overhead {overhead_pct:.2f}% exceeds the {(_POLICY_BUDGET_FACTOR - 1) * 100:.0f}% "
            f"policy budget (ratio={ratio:.4f}); hard gate is "
            f"{(_HARD_GATE_FACTOR - 1) * 100:.0f}%."
        )

    # Hard within-run regression gate.
    assert ratio <= _HARD_GATE_FACTOR, (
        f"decay-weighting overhead regressed: decay-ON best {on_best:.6f}s is "
        f"{overhead_pct:.1f}% over decay-OFF best {off_best:.6f}s "
        f"(ratio={ratio:.4f} > hard gate {_HARD_GATE_FACTOR:.2f}). "
        "Decay weighting only adds an exp() per active symbol in "
        "CrossSectionalRanker; a regression this large means the decay path "
        "is doing materially more work than a single transcendental per name."
    )

    # Pinned per-host guard (opt-in): composition decay-OFF throughput must not
    # regress beyond the hard gate vs the recorded baseline for this host.
    pinned = load_pinned_baseline(
        section="phase4_1_decay_weighting",
        secondary_key="extended_best_seconds",
    )
    if pinned is not None:
        print(
            "PHASE4_1_PINNED_COMPARE "
            f"host={pinned.host_label!r} "
            f"recorded_baseline_best={pinned.baseline_best_seconds:.6f}s "
            f"recorded_extended_best={pinned.secondary_best_seconds:.6f}s "
            f"current_baseline_best={off_best:.6f}s "
            f"current_extended_best={on_best:.6f}s"
        )
        assert off_best <= pinned.baseline_best_seconds * _HARD_GATE_FACTOR, (
            f"composition decay-OFF throughput regressed vs the recorded "
            f"baseline for host {pinned.host_label!r}: current best "
            f"{off_best:.6f}s > {_HARD_GATE_FACTOR:.2f}× recorded "
            f"{pinned.baseline_best_seconds:.6f}s. Re-record only after "
            "confirming the slowdown is intentional."
        )
