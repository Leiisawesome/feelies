"""build_platform rejects a parameter shadowed by a published id.

The validator cannot know what a platform publishes. This check runs
after horizon features are built and compares parameter names to the
registered sensor ids plus the feature ids actually constructed.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from feelies.bootstrap import build_platform
from feelies.core.errors import ConfigurationError
from feelies.core.events import NBBOQuote
from feelies.core.platform_config import OperatingMode, PlatformConfig
from feelies.sensors.impl.ofi_ewma import OFIEwmaSensor
from feelies.sensors.spec import SensorSpec

_SESSION_OPEN_NS = 1_768_532_400_000_000_000


def _spec(
    *,
    alpha_id: str,
    parameter: str,
    on_condition: str,
    reads_no_sensor: bool,
    depends_on_sensors: list[str],
) -> str:
    flag = "true" if reads_no_sensor else "false"
    depends = "[" + ", ".join(depends_on_sensors) + "]"
    return f"""
schema_version: "1.1"
layer: SIGNAL
alpha_id: {alpha_id}
version: "1.0.0"
description: collision probe
hypothesis: collision probe
falsification_criteria:
  - collision probe
reads_no_sensor: {flag}
depends_on_sensors: {depends}
parameters:
  {parameter}:
    type: float
    default: 0.5
    description: probe parameter
horizon_seconds: 30
risk_budget:
  max_position_per_symbol: 1
  max_gross_exposure_pct: 0.1
  max_drawdown_pct: 0.1
  capital_allocation_pct: 0.1
regime_gate:
  regime_engine: hmm_3state_fractional
  on_condition: "{on_condition}"
  off_condition: "False"
cost_arithmetic:
  edge_estimate_bps: 9.0
  half_spread_bps: 2.0
  impact_bps: 2.0
  fee_bps: 1.0
  margin_ratio: 1.8
  cost_basis: one_way
signal: |
  def evaluate(snapshot, regime, params):
      return None
"""


def _build(spec_text: str) -> None:
    tmp = Path(tempfile.mkdtemp(prefix="o03b-"))
    path = tmp / "probe.alpha.yaml"
    path.write_text(spec_text, encoding="utf-8")
    config = PlatformConfig(
        symbols=frozenset({"AAPL"}),
        mode=OperatingMode.BACKTEST,
        alpha_specs=[path],
        regime_engine="hmm_3state_fractional",
        sensor_specs=(
            SensorSpec(
                sensor_id="ofi_ewma",
                sensor_version="1.1.0",
                cls=OFIEwmaSensor,
                params={"alpha": 0.1, "warm_after": 5},
                subscribes_to=(NBBOQuote,),
            ),
        ),
        horizons_seconds=frozenset({30}),
        session_open_ns=_SESSION_OPEN_NS,
        account_equity=1_000_000.0,
        enforce_trend_mechanism=False,
    )
    build_platform(config)


def test_build_rejects_reads_no_sensor_parameter_named_ofi_ewma() -> None:
    """FIX-1 publishes ofi_ewma; a no-sensor spec must not name that parameter."""
    spec = _spec(
        alpha_id="collision_probe",
        parameter="ofi_ewma",
        on_condition="ofi_ewma > 0",
        reads_no_sensor=True,
        depends_on_sensors=[],
    )
    with pytest.raises(ConfigurationError, match="ofi_ewma"):
        _build(spec)


def test_build_rejects_parameter_named_ofi_ewma_without_reads_no_sensor() -> None:
    spec = _spec(
        alpha_id="collision_with_deps",
        parameter="ofi_ewma",
        on_condition="ofi_ewma > 0",
        reads_no_sensor=False,
        depends_on_sensors=["ofi_ewma"],
    )
    with pytest.raises(ConfigurationError, match="collision_with_deps"):
        _build(spec)


def test_build_rejects_parameter_named_ofi_ewma_zscore() -> None:
    """The ofi_ewma factory publishes feature id ofi_ewma_zscore."""
    spec = _spec(
        alpha_id="zscore_collision",
        parameter="ofi_ewma_zscore",
        on_condition="ofi_ewma_zscore > 0",
        reads_no_sensor=True,
        depends_on_sensors=[],
    )
    with pytest.raises(ConfigurationError, match="ofi_ewma_zscore"):
        _build(spec)


def test_build_accepts_parameter_named_like_an_unregistered_sensor() -> None:
    """spread_z_30d is a real sensor id, and this platform does not publish it."""
    spec = _spec(
        alpha_id="unpublished_name",
        parameter="spread_z_30d",
        on_condition="spread_z_30d > 0",
        reads_no_sensor=True,
        depends_on_sensors=[],
    )
    _build(spec)
