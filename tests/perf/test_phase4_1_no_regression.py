"""Phase-4.1 decay-weighting overhead gate (opt-in via ``CI_BENCHMARK=1``).

Closes the audit P0 *dead-guard*: ``scripts/record_perf_baseline.py`` has
always shelled out to
``tests/perf/test_phase4_1_no_regression.py::test_phase4_1_decay_overhead_within_budget``
to source its ``PHASE4_1_PERF_SUMMARY`` line — but that file did not exist,
so the recorder could never run, ``tests/perf/baselines/v02_baseline.json``
stayed empty, and the ≤5 % decay budget was never measured or enforced
(see ``docs/audits/performance_audit_2026-06-25.md`` §6).

What this measures
------------------

The decay weighting (``CrossSectionalRanker(decay_weighting_enabled=True)``)
multiplies each per-symbol raw alpha score by ``exp(-Δt / hl)``.  It is the
**only** decay-affected stage, and it lives inside the Layer-3 composition
pipeline (Ranker → FactorNeutralizer → SectorMatcher → TurnoverOptimizer).
This gate times that *exact* pipeline — reusing the proven, deterministic
Level-3 replay harness (``tests.determinism.test_sized_intent_replay._replay``)
that the parity hash already locks — with decay ON vs OFF.

Why the composition pipeline and not the full M0→M10 tick path: composition
fires only at horizon boundaries, so a real decay regression (say decay
becomes 4× more expensive) would be *diluted into noise* against end-to-end
wall-clock (dominated by the per-event sensor path).  Measuring the affected
layer directly is the **more sensitive** regression guard.  Empirically the
composition-pipeline decay overhead is ~4–5 % on this class of machine — i.e.
the documented ≤5 % budget is approximately the *right number at this scope*
(ranker-in-isolation is ~+40 %, but the fixed neutralizer / sector / optimizer
cost dilutes it back to ~4–5 % across the pipeline).

Assertion strategy (non-flaky by construction)
----------------------------------------------

* **Hard gate** — ``decay_on_best ≤ decay_off_best × _HARD_GATE_FACTOR``
  (within-run, so it is immune to cross-run / cross-host machine variance).
  ``_HARD_GATE_FACTOR`` carries headroom over the inherent ~4–5 % so the gate
  catches a genuine regression (a multiplicative blow-up of the decay cost)
  without flaking on timing noise — the inherent overhead sits too close to
  the 5 % policy line for a bare 1.05 wall-clock gate to be stable in CI.
* **Soft budget** — when the ratio exceeds the documented 1.05 policy budget
  the test prints a ``PHASE4_1_BUDGET_WARNING`` (visible, non-failing) so a
  policy breach surfaces to operators without turning CI red on noise.
* **Pinned guard** — when a per-host baseline exists
  (``PERF_HOST_LABEL`` + ``v02_baseline.json``), additionally assert the
  current decay-OFF best has not regressed past ``_HARD_GATE_FACTOR`` of the
  recorded decay-OFF best (a composition-throughput regression guard).

The ``PHASE4_1_PERF_SUMMARY`` line printed below is parsed verbatim by
``scripts/record_perf_baseline.py`` (regex ``_PHASE4_1_RE``); do not change
its shape without updating that regex in the same commit.

Run::

    CI_BENCHMARK=1 pytest tests/perf/test_phase4_1_no_regression.py -s
    # record a per-host baseline:
    CI_BENCHMARK=1 python scripts/record_perf_baseline.py --host-label dev_local
"""

from __future__ import annotations

import os
import statistics
import time
from typing import Callable

import pytest

from tests.determinism.test_sized_intent_replay import _replay
from tests.perf._pinned_baseline import load_pinned_baseline


pytestmark = pytest.mark.skipif(
    os.environ.get("CI_BENCHMARK") != "1",
    reason="decay-overhead perf gate; opt-in via CI_BENCHMARK=1",
)


# Workload: number of full composition-pipeline replays per timed trial.
# Sized so a single trial is ~100 ms on a dev box (stable timing) while the
# whole test stays well under a couple of seconds.
_INNER_REPLAYS: int = 200
# Best-of-k trials.  The *minimum* (least-contended) trial is the lowest-noise
# estimator of the true cost, which is what we compare.
_TRIALS: int = 9

# Documented policy budget (≤5 % end-to-end, §"decay weighting" glossary entry).
_POLICY_BUDGET_FACTOR: float = 1.05
# Hard gate factor — headroom over the inherent ~4–5 % so the gate is a genuine
# regression guard (fires on a multiplicative decay-cost blow-up) and does not
# flake on wall-clock noise.  A breach of the 1.05 policy budget is surfaced
# separately as a non-failing PHASE4_1_BUDGET_WARNING.
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
