"""Per-host pinned-baseline lookup used by the perf-gate tests.

Closes acceptance gap **G-G**.  Centralised so the two perf gates
(:mod:`tests.perf.test_signal_layer_no_regression` and
:mod:`tests.perf.test_phase4_1_no_regression`) read the same JSON
file in the same way.

Behaviour
---------

* The baseline file is ``tests/perf/baselines/v02_baseline.json``.
* Each host opts in by recording an entry under
  ``hosts[<host_label>]`` via ``scripts/record_perf_baseline.py``.
* ``host_label`` is taken from the ``PERF_HOST_LABEL`` env var
  (operators set this on perf-relevant hosts).  If unset, the
  helper returns ``None`` and the perf test falls back to the
  ratio-only assertion.
* If the env var *is* set but no entry matches, the helper still
  returns ``None`` and prints a single ``PERF_BASELINE_MISS`` line
  to stdout so it is greppable in CI logs.  This is intentional:
  a missing entry is a benign condition that should not flip the
  test red — we don't want a perf gate to start failing solely
  because someone's first run on a new host has not yet recorded
  a baseline.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


_BASELINE_PATH = (
    Path(__file__).resolve().parent / "baselines" / "v02_baseline.json"
)


@dataclass(frozen=True)
class PinnedBaseline:
    host_label: str
    baseline_best_seconds: float
    secondary_best_seconds: float
    """Phase-4.1 calls this 'extended'.

    Workstream-D update — the original generic shape served two perf
    gates: Phase-3 (``mixed_best_seconds``) and Phase-4.1
    (``extended_best_seconds``).  The Phase-3 gate
    (``test_signal_layer_no_regression``) was retired with the
    ``trade_cluster_drift`` reference alpha (D.2); the field is kept
    generic so a future perf gate can re-use the helper without
    schema churn.
    """


def _load_json() -> dict[str, dict[str, dict[str, float | str]]]:
    if not _BASELINE_PATH.is_file():
        return {"hosts": {}}
    try:
        data = json.loads(_BASELINE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"hosts": {}}
    if not isinstance(data, dict) or "hosts" not in data:
        return {"hosts": {}}
    if not isinstance(data["hosts"], dict):
        return {"hosts": {}}
    return data  # type: ignore[return-value]


def load_pinned_baseline(
    *, section: str, secondary_key: str,
) -> PinnedBaseline | None:
    """Look up the pinned baseline for the running host, or return ``None``.

    Parameters
    ----------
    section :
        ``'phase4_1_decay_weighting'`` — the per-test-section key
        written by ``record_perf_baseline.py``.  Workstream-D retired
        ``'phase3_signal_layer'`` together with the
        ``trade_cluster_drift`` reference alpha; legacy entries on
        disk are still loadable.
    secondary_key :
        ``'extended_best_seconds'`` for the phase-4.1 gate.
    """
    host_label = os.environ.get("PERF_HOST_LABEL", "").strip()
    if not host_label:
        return None
    data = _load_json()
    host_blob = data["hosts"].get(host_label)
    if host_blob is None:
        # Greppable miss line so CI logs can show "we tried but
        # found nothing" without flipping the test red.
        print(
            f"PERF_BASELINE_MISS host_label={host_label!r} "
            f"section={section!r} reason=host_not_in_baseline_file"
        )
        return None
    section_blob = host_blob.get(section)
    if not isinstance(section_blob, dict):
        print(
            f"PERF_BASELINE_MISS host_label={host_label!r} "
            f"section={section!r} reason=section_missing"
        )
        return None
    try:
        return PinnedBaseline(
            host_label=host_label,
            baseline_best_seconds=float(
                section_blob["baseline_best_seconds"]  # type: ignore[arg-type]
            ),
            secondary_best_seconds=float(
                section_blob[secondary_key]  # type: ignore[arg-type]
            ),
        )
    except (KeyError, TypeError, ValueError) as exc:
        print(
            f"PERF_BASELINE_MISS host_label={host_label!r} "
            f"section={section!r} reason=malformed:{exc}"
        )
        return None


__all__ = ["PinnedBaseline", "load_pinned_baseline"]
