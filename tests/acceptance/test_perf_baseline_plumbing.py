"""Acceptance — perf-baseline plumbing exists and is well-formed (G-G).

This test runs on every standard ``pytest`` invocation (no
``CI_BENCHMARK`` gate) so the plumbing introduced for acceptance gap
**G-G** cannot rot silently between perf-job runs.  It does **not**
execute the perf harness itself — that is what the existing
``tests/perf/test_*_no_regression.py`` gates do under
``CI_BENCHMARK=1``.

What is asserted
----------------

* ``scripts/record_perf_baseline.py`` exists and is importable.
* ``tests/perf/baselines/v02_baseline.json`` exists and is valid JSON
  with the documented top-level shape (``{"hosts": {...}}``).
* ``tests/perf/_pinned_baseline.py`` exposes the helper used by the
  two perf gates and returns ``None`` when ``PERF_HOST_LABEL`` is
  unset (the guaranteed-safe fallback path documented in matrix
  rows §18.2 #4 and §20.12.3 #4).

Together these guarantee that a perf job which sets
``PERF_HOST_LABEL`` (and previously recorded a baseline for that
label) gets a tightened gate, while every other host transparently
keeps the v0.2 ratio-only behaviour.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO_ROOT / "scripts" / "record_perf_baseline.py"
_BASELINE_JSON = _REPO_ROOT / "tests" / "perf" / "baselines" / "v02_baseline.json"


def test_record_perf_baseline_script_exists_and_imports() -> None:
    assert _SCRIPT.is_file(), f"missing helper script: {_SCRIPT}"
    mod_name = "_record_perf_baseline_under_test"
    spec = importlib.util.spec_from_file_location(mod_name, _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Register before exec so dataclass introspection (which walks
    # ``sys.modules[cls.__module__]``) works on Python 3.14+.
    sys.modules[mod_name] = module
    try:
        spec.loader.exec_module(module)
        assert hasattr(module, "main"), (
            "scripts/record_perf_baseline.py missing main() entrypoint"
        )
    finally:
        sys.modules.pop(mod_name, None)


def test_v02_baseline_json_is_well_formed() -> None:
    assert _BASELINE_JSON.is_file(), f"missing baseline file: {_BASELINE_JSON}"
    blob = json.loads(_BASELINE_JSON.read_text(encoding="utf-8"))
    assert isinstance(blob, dict), "baseline JSON must be an object"
    assert "hosts" in blob and isinstance(blob["hosts"], dict), (
        "baseline JSON must have a top-level 'hosts' object"
    )
    for host_label, payload in blob["hosts"].items():
        assert isinstance(host_label, str) and host_label, (
            f"host_label keys must be non-empty strings, got {host_label!r}"
        )
        assert isinstance(payload, dict), (
            f"host {host_label!r} payload must be an object"
        )
        # Workstream-D update — the prior ``phase3_signal_layer``
        # section was anchored on ``test_signal_layer_no_regression``
        # which was retired with the ``trade_cluster_drift`` LEGACY
        # reference alpha (D.2).  Only ``phase4_1_decay_weighting`` is
        # required of newly-recorded hosts; legacy entries on disk
        # remain valid and are simply not enforced here.
        required = "phase4_1_decay_weighting"
        assert required in payload, (
            f"host {host_label!r} missing required section "
            f"{required!r}"
        )


def test_pinned_baseline_helper_returns_none_when_label_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.perf._pinned_baseline import load_pinned_baseline

    monkeypatch.delenv("PERF_HOST_LABEL", raising=False)
    result = load_pinned_baseline(
        section="phase4_1_decay_weighting",
        secondary_key="extended_best_seconds",
    )
    assert result is None, (
        "load_pinned_baseline must return None when PERF_HOST_LABEL is "
        "unset (the documented safe-fallback path)"
    )


def test_pinned_baseline_helper_returns_none_for_unknown_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.perf._pinned_baseline import load_pinned_baseline

    monkeypatch.setenv(
        "PERF_HOST_LABEL", "definitely_not_a_recorded_host_label_xyz_123",
    )
    result = load_pinned_baseline(
        section="phase4_1_decay_weighting",
        secondary_key="extended_best_seconds",
    )
    assert result is None, (
        "load_pinned_baseline must return None when the running host "
        "is not in the JSON file (so perf gates do not flip red on "
        "first-run hosts)"
    )
