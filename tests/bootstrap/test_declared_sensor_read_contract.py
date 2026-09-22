"""build_platform rejects a SIGNAL alpha that reads outside its sensors.

Ownership is a build contract: every name ``evaluate`` or the regime
gate reads must be a feature of a sensor in ``depends_on_sensors``.
An unresolvable body scan is not proof that the read is inside that
set. A declared sensor the platform does not register is already
``UnresolvedDependencyError`` from ``resolve_signal_dependencies``.
PORTFOLIO specs have no signal body and stay exempt.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from feelies.alpha.registry import UnresolvedDependencyError
from feelies.bootstrap import build_platform
from feelies.core.errors import ConfigurationError
from feelies.core.events import NBBOQuote, Trade
from feelies.core.platform_config import OperatingMode, PlatformConfig
from feelies.sensors.impl.ofi_ewma import OFIEwmaSensor
from feelies.sensors.impl.snr_drift_diffusion import SNRDriftDiffusionSensor
from feelies.sensors.impl.spread_z_30d import SpreadZScoreSensor
from feelies.sensors.impl.vpin_50bucket import VPIN50BucketSensor
from feelies.sensors.spec import SensorSpec

_SESSION_OPEN_NS = 1_768_532_400_000_000_000


def _ofi() -> SensorSpec:
    return SensorSpec(
        sensor_id="ofi_ewma",
        sensor_version="1.1.0",
        cls=OFIEwmaSensor,
        params={"alpha": 0.1, "warm_after": 5},
        subscribes_to=(NBBOQuote,),
    )


def _spread() -> SensorSpec:
    return SensorSpec(
        sensor_id="spread_z_30d",
        sensor_version="1.1.0",
        cls=SpreadZScoreSensor,
        subscribes_to=(NBBOQuote,),
    )


def _vpin() -> SensorSpec:
    return SensorSpec(
        sensor_id="vpin_50bucket",
        sensor_version="1.1.0",
        cls=VPIN50BucketSensor,
        params={},
        subscribes_to=(Trade,),
    )


def _snr() -> SensorSpec:
    return SensorSpec(
        sensor_id="snr_drift_diffusion",
        sensor_version="1.3.0",
        cls=SNRDriftDiffusionSensor,
        params={},
        subscribes_to=(NBBOQuote,),
    )


def _signal(
    *,
    alpha_id: str,
    depends: list[str],
    read: str,
    on_condition: str = "P(normal) > 0.5",
) -> str:
    depends_literal = "[" + ", ".join(depends) + "]"
    return f"""
schema_version: "1.1"
layer: SIGNAL
alpha_id: {alpha_id}
version: "1.0.0"
description: read-contract probe
hypothesis: read-contract probe
falsification_criteria:
  - read-contract probe
depends_on_sensors: {depends_literal}
parameters: {{}}
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
      {read}
"""


def _portfolio() -> str:
    return """
schema_version: "1.1"
layer: PORTFOLIO
alpha_id: pro_read_contract
version: "1.0.0"
description: portfolio has no signal body
hypothesis: portfolio exemption probe
falsification_criteria:
  - portfolio exemption probe
horizon_seconds: 30
universe:
  - AAPL
depends_on_signals:
  - declared_owner
factor_neutralization: false
parameters: {}
risk_budget:
  max_position_per_symbol: 1
  max_gross_exposure_pct: 0.1
  max_drawdown_pct: 0.1
  capital_allocation_pct: 0.1
cost_arithmetic:
  edge_estimate_bps: 10.0
  half_spread_bps: 1.0
  impact_bps: 0.5
  fee_bps: 0.5
  margin_ratio: 5.0
"""


def _build(
    specs: list[tuple[str, str]],
    sensors: tuple[SensorSpec, ...],
    *,
    symbols: frozenset[str] = frozenset({"AAPL"}),
) -> None:
    tmp = Path(tempfile.mkdtemp(prefix="o05-"))
    paths = []
    for name, text in specs:
        path = tmp / name
        path.write_text(text, encoding="utf-8")
        paths.append(path)
    config = PlatformConfig(
        symbols=symbols,
        mode=OperatingMode.BACKTEST,
        alpha_specs=paths,
        regime_engine="hmm_3state_fractional",
        sensor_specs=sensors,
        horizons_seconds=frozenset({30}),
        session_open_ns=_SESSION_OPEN_NS,
        account_equity=1_000_000.0,
        enforce_trend_mechanism=False,
    )
    build_platform(config)


def test_build_rejects_read_of_an_undeclared_sensor() -> None:
    """(A) ofi_ewma_zscore is published here, and this alpha did not declare ofi_ewma."""
    spec = _signal(
        alpha_id="undeclared_owner",
        depends=["spread_z_30d"],
        read='return snapshot.values.get("ofi_ewma_zscore")',
    )
    with pytest.raises(ConfigurationError, match="undeclared_owner"):
        _build([("probe.alpha.yaml", spec)], (_spread(), _ofi()))


def test_declared_unregistered_sensor_raises_unresolved_dependency() -> None:
    """(B) pin. A declared sensor the platform does not register already fails.

    The error is UnresolvedDependencyError from resolve_signal_dependencies,
    naming the sensor, and it is raised before the read contract.
    """
    spec = _signal(
        alpha_id="unpublished_owner",
        depends=["book_imbalance"],
        read='return snapshot.values.get("book_imbalance_mean")',
    )
    with pytest.raises(UnresolvedDependencyError, match="book_imbalance"):
        _build([("probe.alpha.yaml", spec)], (_ofi(),))


def test_build_rejects_params_only_read_key() -> None:
    """(C) a key that resolves only through params is not a resolved read set."""
    spec = _signal(
        alpha_id="params_only_read",
        depends=["ofi_ewma"],
        read='return snapshot.values.get(params["k"])',
    )
    with pytest.raises(ConfigurationError, match="params_only_read"):
        _build([("probe.alpha.yaml", spec)], (_ofi(),))


def test_build_accepts_a_read_of_a_declared_sensor() -> None:
    spec = _signal(
        alpha_id="declared_owner",
        depends=["spread_z_30d"],
        read='return snapshot.values.get("spread_z_30d")',
    )
    _build([("probe.alpha.yaml", spec)], (_spread(),))


_RAW_GATE_UNSUPPORTED = (
    "publishes no horizon feature at horizon 30s, and a regime-gate read of a "
    "raw sensor id is not supported because sensor emission shape is not declared"
)


def test_build_rejects_gate_read_of_declared_raw_sensor() -> None:
    """A declared raw id with no horizon feature is not a supported gate read."""
    spec = _signal(
        alpha_id="gate_raw_declared",
        depends=["vpin_50bucket"],
        read="return None",
        on_condition="vpin_50bucket > 0.5",
    )
    with pytest.raises(ConfigurationError, match=_RAW_GATE_UNSUPPORTED):
        _build([("probe.alpha.yaml", spec)], (_vpin(),))


def test_build_rejects_body_read_of_declared_raw_sensor() -> None:
    """evaluate sees snapshot.values only. The same raw id reads None forever."""
    spec = _signal(
        alpha_id="body_raw_declared",
        depends=["vpin_50bucket"],
        read='return snapshot.values["vpin_50bucket"]',
    )
    with pytest.raises(
        ConfigurationError,
        match="read 'vpin_50bucket' is not a feature of declared sensors",
    ):
        _build([("probe.alpha.yaml", spec)], (_vpin(),))


def test_build_rejects_gate_read_of_undeclared_raw_sensor() -> None:
    """An undeclared raw sensor id is still outside the declared set."""
    spec = _signal(
        alpha_id="gate_raw_undeclared",
        depends=["spread_z_30d"],
        read="return None",
        on_condition="vpin_50bucket > 0.5",
    )
    with pytest.raises(
        ConfigurationError,
        match="read 'vpin_50bucket' is not a feature of declared sensors",
    ):
        _build([("probe.alpha.yaml", spec)], (_spread(), _vpin()))


def test_build_rejects_gate_read_of_declared_tuple_sensor() -> None:
    """Bugbot: snr_drift_diffusion emits a tuple and is not cached under its id."""
    spec = _signal(
        alpha_id="gate_tuple_declared",
        depends=["snr_drift_diffusion"],
        read="return None",
        on_condition="snr_drift_diffusion > 0.5",
    )
    with pytest.raises(ConfigurationError, match=_RAW_GATE_UNSUPPORTED):
        _build([("probe.alpha.yaml", spec)], (_snr(),))


def test_portfolio_spec_builds() -> None:
    """PORTFOLIO has no signal body. The read contract does not apply."""
    signal = _signal(
        alpha_id="declared_owner",
        depends=["spread_z_30d"],
        read="return None",
    )
    _build(
        [
            ("declared_owner.alpha.yaml", signal),
            ("pro_read_contract.alpha.yaml", _portfolio()),
        ],
        (_spread(),),
    )
