"""Acceptance checks for performance-baseline plumbing.

The recorder, baseline JSON, and host lookup must remain usable without running
the opt-in benchmark suite. Unpinned hosts fall back to ratio-only gates.
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
        assert hasattr(module, "main"), "scripts/record_perf_baseline.py missing main() entrypoint"
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
        assert isinstance(payload, dict), f"host {host_label!r} payload must be an object"
        # New baselines require the active decay-weighting section.
        required = "phase4_1_decay_weighting"
        assert required in payload, f"host {host_label!r} missing required section {required!r}"


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
        "PERF_HOST_LABEL",
        "definitely_not_a_recorded_host_label_xyz_123",
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


def test_record_perf_baseline_referenced_harness_is_collectable() -> None:
    """The recorder's fixed pytest node id must remain collectable."""
    mod_name = "_record_perf_baseline_node_id_under_test"
    spec = importlib.util.spec_from_file_location(mod_name, _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    try:
        spec.loader.exec_module(module)
        node_id = getattr(module, "_PHASE4_1_TEST", None)
    finally:
        sys.modules.pop(mod_name, None)

    assert isinstance(node_id, str) and "::" in node_id, (
        "record_perf_baseline must expose its target node id as "
        f"_PHASE4_1_TEST = '<file>::<func>'; got {node_id!r}"
    )
    path_str, _, func_name = node_id.partition("::")
    assert func_name, f"malformed perf-test node id (no function): {node_id!r}"

    test_path = _REPO_ROOT / path_str
    assert test_path.is_file(), (
        f"record_perf_baseline references {path_str!r} which does not exist; "
        "the recorder would error and no baseline could ever be recorded "
        "(the v0.2 dead-guard this test exists to prevent)"
    )

    dotted = path_str.replace("/", ".").removesuffix(".py")
    test_mod = importlib.import_module(dotted)
    assert hasattr(test_mod, func_name), (
        f"{path_str!r} exists but defines no {func_name!r}; the recorder's "
        "node id would collect zero tests"
    )
