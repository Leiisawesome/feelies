"""``edge_calibration_path`` must reach the B4 gate from configuration.

The forensics -> gate feedback loop is the platform's only mechanism for
shrinking a disclosed edge toward the edge actually realised.  It was
unreachable from config: bootstrap probed ``getattr(config,
"edge_calibration_path", None)`` against a ``PlatformConfig`` that had no such
field, and ``from_yaml`` rejects unrecognised keys — so the branch was dead and
putting the key in a YAML file was a hard error.

Only ``harness/backtest_runner.py`` could supply factors, via its
``--edge-calibration`` flag.  A calibrated backtest therefore gated on a haircut
edge while paper and live gated on the full disclosed edge, admitting strictly
more trades than the run that validated them — an Inv-9 divergence resolving
toward *more* exposure.
"""

from __future__ import annotations

import json
from pathlib import Path

from feelies.core.platform_config import PlatformConfig
from feelies.forensics.edge_calibration import EdgeCalibrationStore
from feelies.harness.backtest_report import edge_calibration_version

_PLATFORM_YAML = Path(__file__).resolve().parents[2] / "platform.yaml"


def _write_calibration(tmp_path: Path, factors: dict[str, float]) -> Path:
    """Write a calibration artifact in the store's on-disk schema."""
    path = tmp_path / "edge_calibration.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "edge_calibration/1",
                "version": "2026-01-15",
                "factors": {
                    sid: {
                        "strategy_id": sid,
                        "n_fills": 50,
                        "realized_edge_bps_mean": 4.0,
                        "realized_edge_bps_std": 1.0,
                        "realized_edge_bps_lcb": 3.5,
                        "disclosed_edge_bps": 9.0,
                        "haircut_factor": factor,
                        "lcb_factor": factor,
                    }
                    for sid, factor in factors.items()
                },
            }
        )
    )
    return path


def test_edge_calibration_path_is_a_real_config_field(tmp_path: Path) -> None:
    """It must survive ``from_yaml``, which rejects unrecognised keys."""
    cal = _write_calibration(tmp_path, {"sig_demo_v1": 0.5})
    cfg_path = tmp_path / "run.yaml"
    cfg_path.write_text(f"extends: {_PLATFORM_YAML}\nedge_calibration_path: {cal}\n")

    config = PlatformConfig.from_yaml(str(cfg_path))

    assert config.edge_calibration_path == cal


def test_edge_calibration_path_defaults_to_none() -> None:
    """Absent key ⇒ no haircut, so existing deployments are unaffected."""
    assert PlatformConfig.from_yaml(str(_PLATFORM_YAML)).edge_calibration_path is None


def test_edge_calibration_path_is_recorded_in_the_config_snapshot(tmp_path: Path) -> None:
    """Inv-13 provenance is split across two records, deliberately.

    The config snapshot carries the artifact's *name* only — matching the sibling
    calendar paths, because hashing absolute paths would make config checksums
    host-dependent and break cross-host parity.  Which *factors* were actually
    applied is identified separately by ``edge_calibration_version``, a content
    hash that feeds the run report's ``artifact_id``.  Neither record alone
    identifies the gate's inputs; together they do.
    """
    cal = _write_calibration(tmp_path, {"sig_demo_v1": 0.5})
    cfg_path = tmp_path / "run.yaml"
    cfg_path.write_text(f"extends: {_PLATFORM_YAML}\nedge_calibration_path: {cal}\n")

    snapshot = PlatformConfig.from_yaml(str(cfg_path)).snapshot(ts_ns=0)

    assert snapshot.data["edge_calibration_path"] == cal.name
    # Host-independent: no absolute path leaks into the hashed snapshot.
    assert str(tmp_path) not in json.dumps(snapshot.data)


def test_applied_factors_are_identified_by_content_not_filename() -> None:
    """Two calibrations sharing a filename must not look like the same run.

    This is the half of provenance the config snapshot cannot carry, since it
    records the name only.
    """
    a = edge_calibration_version({"sig_demo_v1": 0.5})
    b = edge_calibration_version({"sig_demo_v1": 0.25})

    assert a != b
    # The uncalibrated case stays a stable sentinel so runs that never use the
    # flag keep their existing artifact_id.
    assert edge_calibration_version(None) == "none"
    assert edge_calibration_version({}) == "none"


def test_store_round_trips_the_factors_the_gate_reads(tmp_path: Path) -> None:
    """The B4 gate multiplies disclosed edge by these factors."""
    cal = _write_calibration(tmp_path, {"sig_a_v1": 0.5, "sig_b_v1": 0.25})

    factors = EdgeCalibrationStore(str(cal)).factors()

    assert factors == {"sig_a_v1": 0.5, "sig_b_v1": 0.25}
    # A haircut only ever shrinks disclosed edge — it must never license a trade
    # the uncalibrated gate would refuse (Inv-11).
    assert all(0.0 <= f <= 1.0 for f in factors.values())
