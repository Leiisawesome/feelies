"""Record the per-host perf baseline JSON consumed by the perf gates.

Closes acceptance gap **G-G** (matrix rows §18.2 #4 and §20.12.3 #4).

Usage
-----

    CI_BENCHMARK=1 python scripts/record_perf_baseline.py \
        --host-label dev_local \
        --out tests/perf/baselines/v02_baseline.json

The script invokes the *existing* perf-test harness through pytest
(``test_phase4_1_no_regression``) and parses its structured
``PHASE4_1_PERF_SUMMARY`` line from stdout.  The harness is the
canonical source of timings — this script *does not* re-implement
timing logic; that would be a trust gap if the asserting test later
disagreed.

Workstream-D update — the prior ``phase3_signal_layer`` baseline
section was anchored on the now-deleted
``test_signal_layer_no_regression`` harness (LEGACY-vs-SIGNAL
regression check, retired with the ``trade_cluster_drift``
reference alpha).  Re-recording an existing baseline file with
this version of the script preserves any historical
``phase3_signal_layer`` entries on disk (``_merge_into_file``
overwrites the host blob, not a key-by-key merge); operators who
want a clean file should hand-edit or delete the stale section.

The output JSON is then matched per-host inside the perf tests (see
their ``_load_pinned_baseline`` helper).  The matching key is
``host_label`` — operators record one baseline per
performance-relevant host (e.g. ``ci_linux_x64``, ``dev_local``) so a
laptop's number does not gate a CI runner and vice-versa.

If the requested ``--host-label`` is missing from the JSON file when
the perf test reads it, the test silently falls back to the
ratio-only assertion (the v0.2 behaviour).  This means landing a new
baseline is opt-in per host and never introduces flakiness for
hosts that have not opted in.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


_REPO_ROOT = Path(__file__).resolve().parents[1]

_PHASE4_1_TEST = (
    "tests/perf/test_phase4_1_no_regression.py"
    "::test_phase4_1_decay_overhead_within_budget"
)


_PHASE4_1_RE = re.compile(
    r"PHASE4_1_PERF_SUMMARY\s+"
    r"baseline_best=(?P<baseline>[0-9.]+)s\s+"
    r"baseline_median=[0-9.]+s\s+"
    r"extended_best=(?P<extended>[0-9.]+)s\s+"
)


@dataclass(frozen=True)
class _PerfMeasurement:
    baseline_best_seconds: float
    extended_best_seconds: float


def _run_pytest_capture(test_id: str) -> str:
    """Run a single pytest node id with ``CI_BENCHMARK=1`` and return stdout."""
    env = dict(os.environ)
    env["CI_BENCHMARK"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-s", test_id],
        cwd=str(_REPO_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if proc.returncode != 0:
        raise SystemExit(
            f"perf test {test_id} did not pass (rc={proc.returncode}); "
            f"refusing to record a baseline from a failing run.\n"
            f"--- last 60 lines ---\n"
            + "\n".join(proc.stdout.splitlines()[-60:])
        )
    return proc.stdout


def _parse_phase4_1(stdout: str) -> _PerfMeasurement:
    m = _PHASE4_1_RE.search(stdout)
    if not m:
        raise SystemExit(
            "could not find PHASE4_1_PERF_SUMMARY line in phase-4.1 "
            "perf-test stdout"
        )
    return _PerfMeasurement(
        baseline_best_seconds=float(m.group("baseline")),
        extended_best_seconds=float(m.group("extended")),
    )


def _build_payload(
    *,
    host_label: str,
    phase4_1: _PerfMeasurement,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "host_label": host_label,
        "python_version": sys.version.split()[0],
        "platform": sys.platform,
        "phase4_1_decay_weighting": {
            "test_id": _PHASE4_1_TEST,
            "baseline_best_seconds": phase4_1.baseline_best_seconds,
            "extended_best_seconds": phase4_1.extended_best_seconds,
            "max_overhead_factor": 1.05,
        },
    }


def _merge_into_file(out_path: Path, payload: dict[str, Any]) -> None:
    existing: dict[str, Any] = {"schema_version": "1.0.0", "hosts": {}}
    if out_path.is_file():
        try:
            existing = json.loads(out_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise SystemExit(
                f"existing baseline file {out_path} is not valid JSON: {exc}"
            ) from exc
    if not isinstance(existing, dict) or "hosts" not in existing:
        existing = {"schema_version": "1.0.0", "hosts": {}}
    hosts = existing["hosts"]
    if not isinstance(hosts, dict):
        raise SystemExit(
            f"existing baseline file {out_path} has malformed 'hosts' field"
        )
    hosts[payload["host_label"]] = payload
    existing["schema_version"] = "1.0.0"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(existing, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--host-label",
        required=True,
        help=(
            "Stable identifier for this host (e.g. 'ci_linux_x64', "
            "'dev_local'). The perf tests look up this label when "
            "deciding whether to apply a pinned-baseline assertion."
        ),
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=_REPO_ROOT / "tests" / "perf" / "baselines" / "v02_baseline.json",
        help="Output JSON path (default: tests/perf/baselines/v02_baseline.json)",
    )
    args = parser.parse_args()

    print(f"[record_perf_baseline] running {_PHASE4_1_TEST}")
    phase4_1_stdout = _run_pytest_capture(_PHASE4_1_TEST)
    phase4_1 = _parse_phase4_1(phase4_1_stdout)
    print(
        f"[record_perf_baseline]   phase4.1 baseline_best="
        f"{phase4_1.baseline_best_seconds:.4f}s "
        f"extended_best={phase4_1.extended_best_seconds:.4f}s"
    )

    payload = _build_payload(
        host_label=args.host_label, phase4_1=phase4_1,
    )
    _merge_into_file(args.out, payload)
    print(
        f"[record_perf_baseline] wrote baseline for host_label="
        f"{args.host_label!r} → {args.out}"
    )


if __name__ == "__main__":
    main()
