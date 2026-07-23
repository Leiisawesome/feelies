"""Sizer-tilt deployment warning tests.

``sizer_tilt_drive`` is the one platform-level switch that can size a
SIGNAL-path order *above* the single-factor baseline.  It is off by
default and promoting it is meant to be a conscious, per-deployment
choice.  ``build_platform`` logs a one-shot WARNING when it reaches
PAPER/LIVE so an accidental carry-over from a research config is visible
rather than silent.
"""

from __future__ import annotations

import logging
import textwrap
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest

from feelies.bootstrap import build_platform
from feelies.core.events import NBBOQuote
from feelies.core.platform_config import OperatingMode, PlatformConfig
from feelies.sensors.impl.ofi_ewma import OFIEwmaSensor
from feelies.sensors.impl.spread_z_30d import SpreadZScoreSensor
from feelies.sensors.spec import SensorSpec

_TEST_SENSOR_SPECS: tuple[SensorSpec, ...] = (
    SensorSpec(
        sensor_id="ofi_ewma",
        sensor_version="1.1.0",
        cls=OFIEwmaSensor,
        subscribes_to=(NBBOQuote,),
    ),
    SensorSpec(
        sensor_id="spread_z_30d",
        sensor_version="1.1.0",
        cls=SpreadZScoreSensor,
        subscribes_to=(NBBOQuote,),
    ),
)

_SIGNAL_ALPHA_YAML = textwrap.dedent(
    """\
    schema_version: "1.1"
    layer: SIGNAL
    alpha_id: sizer_tilt_warning_alpha
    version: "1.0.0"
    author: test
    description: minimal signal fixture for sizer-tilt deployment warning tests
    hypothesis: test
    falsification_criteria:
      - test criterion
    symbols:
      - AAPL
    parameters: {}
    risk_budget:
      max_position_per_symbol: 100
      max_gross_exposure_pct: 5.0
      max_drawdown_pct: 1.0
      capital_allocation_pct: 10.0
    horizon_seconds: 300
    depends_on_sensors:
      - ofi_ewma
      - spread_z_30d
    regime_gate:
      regime_engine: hmm_3state_fractional
      on_condition: "P(normal) > 0.7"
      off_condition: "P(normal) < 0.5"
    cost_arithmetic:
      edge_estimate_bps: 9.0
      half_spread_bps: 2.0
      impact_bps: 2.0
      fee_bps: 1.0
      margin_ratio: 1.8
    signal: |
      def evaluate(snapshot, regime, params):
          return None
    """
)


def _paper_config(tmp_path: Path, **overrides: object) -> PlatformConfig:
    (tmp_path / "test.alpha.yaml").write_text(_SIGNAL_ALPHA_YAML, encoding="utf-8")
    defaults: dict[str, object] = {
        "symbols": frozenset({"AAPL"}),
        "mode": OperatingMode.PAPER,
        "alpha_spec_dir": tmp_path,
        "account_equity": 100_000.0,
        "sensor_specs": _TEST_SENSOR_SPECS,
        "enforce_trend_mechanism": False,
        "ib_host": "127.0.0.1",
        "ib_port": 4002,
        "ib_client_id": 7,
        "massive_ws_url": "wss://test.example/stocks",
    }
    defaults.update(overrides)
    return PlatformConfig(**defaults)  # type: ignore[arg-type]


def _build_in_paper_mode(config: PlatformConfig) -> None:
    with patch(
        "feelies.execution.paper_backend.build_paper_backend",
        return_value=(object(), object(), object()),
    ):
        build_platform(config)


class TestSizerTiltDeploymentWarning:
    def test_warns_when_tilt_drive_enabled_in_paper_mode(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        monkeypatch.setenv("MASSIVE_API_KEY", "fake_key")
        config = replace(
            _paper_config(tmp_path),
            sizer_tilt_drive=True,
            sizer_edge_weighting_enabled=True,
        )
        with caplog.at_level(logging.WARNING, logger="feelies.bootstrap"):
            _build_in_paper_mode(config)

        warnings = [r for r in caplog.records if "sizer_tilt_drive" in r.getMessage()]
        assert len(warnings) == 1
        assert "PAPER" in warnings[0].getMessage()

    def test_no_warning_when_tilt_drive_disabled_in_paper_mode(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        monkeypatch.setenv("MASSIVE_API_KEY", "fake_key")
        config = _paper_config(tmp_path)
        assert config.sizer_tilt_drive is False

        with caplog.at_level(logging.WARNING, logger="feelies.bootstrap"):
            _build_in_paper_mode(config)

        warnings = [r for r in caplog.records if "sizer_tilt_drive" in r.getMessage()]
        assert warnings == []

    def test_no_warning_when_tilt_drive_enabled_in_backtest_mode(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Research/backtest configs may legitimately drive the tilt
        without triggering a deployment-facing warning."""
        (tmp_path / "test.alpha.yaml").write_text(_SIGNAL_ALPHA_YAML, encoding="utf-8")
        config = PlatformConfig(
            symbols=frozenset({"AAPL"}),
            mode=OperatingMode.BACKTEST,
            alpha_spec_dir=tmp_path,
            account_equity=100_000.0,
            sensor_specs=_TEST_SENSOR_SPECS,
            enforce_trend_mechanism=False,
            sizer_tilt_drive=True,
            sizer_edge_weighting_enabled=True,
        )
        with caplog.at_level(logging.WARNING, logger="feelies.bootstrap"):
            build_platform(config)

        warnings = [r for r in caplog.records if "sizer_tilt_drive" in r.getMessage()]
        assert warnings == []
