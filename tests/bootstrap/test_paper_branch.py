"""Bootstrap PAPER-mode branch tests.

These tests exercise ``_create_backend`` and ``build_platform`` for
``OperatingMode.PAPER`` without ever connecting to a real IB Gateway
or a real Massive WebSocket — both endpoints are stubbed at the
``build_paper_backend`` boundary.

What's covered:
    - PAPER without ``MASSIVE_API_KEY`` raises ``ConfigurationError``
      *before* attempting any network I/O.
    - Whitespace-only ``MASSIVE_API_KEY`` is rejected.
    - PAPER with a valid API key composes a ``_BackendBundle`` whose
      ``live_feed`` and ``ib_connection`` handles are populated and
      ``backtest_router`` is ``None``.
    - The PAPER backend forwards the configured ``ib_host``,
      ``ib_port``, ``ib_client_id``, and ``massive_ws_url`` from
      ``PlatformConfig`` to ``build_paper_backend``.
    - When the caller does not supply a normalizer, bootstrap
      auto-constructs a ``MassiveNormalizer`` and threads the *same*
      instance into the live feed and the orchestrator (Inv-13: single
      provenance source).
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from feelies.bootstrap import _BackendBundle, _create_backend, build_platform
from feelies.core.clock import SimulatedClock
from feelies.core.errors import ConfigurationError
from feelies.core.platform_config import OperatingMode, PlatformConfig
from feelies.execution.cost_model import DefaultCostModel
from feelies.ingestion.massive_normalizer import MassiveNormalizer
from feelies.sensors.impl.ofi_ewma import OFIEwmaSensor
from feelies.sensors.impl.spread_z_30d import SpreadZScoreSensor
from feelies.sensors.spec import SensorSpec
from feelies.storage.memory_event_log import InMemoryEventLog
from feelies.core.events import NBBOQuote

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

_PAPER_SIGNAL_ALPHA_YAML = textwrap.dedent(
    """\
    schema_version: "1.1"
    layer: SIGNAL
    alpha_id: paper_bootstrap_alpha
    version: "1.0.0"
    author: test
    description: minimal signal fixture for PAPER bootstrap tests
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


def _minimal_paper_config(**overrides: Any) -> PlatformConfig:
    defaults: dict[str, Any] = {
        "symbols": frozenset({"AAPL", "MSFT"}),
        "alpha_specs": [Path("alpha.yaml")],
        "mode": OperatingMode.PAPER,
        "ib_host": "127.0.0.1",
        "ib_port": 4002,
        "ib_client_id": 7,
        "massive_ws_url": "wss://test.example/stocks",
    }
    defaults.update(overrides)
    return PlatformConfig(**defaults)


class TestCreateBackendPaperBranch:
    def test_missing_api_key_raises_configuration_error(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("MASSIVE_API_KEY", raising=False)
        config = _minimal_paper_config()
        clock = SimulatedClock()
        normalizer = MassiveNormalizer(clock=clock)
        with pytest.raises(ConfigurationError, match="MASSIVE_API_KEY"):
            _create_backend(
                OperatingMode.PAPER,
                InMemoryEventLog(),
                clock,
                config=config,
                normalizer=normalizer,
                cost_model=DefaultCostModel(),
            )

    def test_missing_normalizer_raises_configuration_error(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("MASSIVE_API_KEY", "k")
        config = _minimal_paper_config()
        with pytest.raises(ConfigurationError, match="MassiveNormalizer"):
            _create_backend(
                OperatingMode.PAPER,
                InMemoryEventLog(),
                SimulatedClock(),
                config=config,
                normalizer=None,
                cost_model=DefaultCostModel(),
            )

    def test_missing_config_raises_configuration_error(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("MASSIVE_API_KEY", "k")
        clock = SimulatedClock()
        with pytest.raises(ConfigurationError, match="PlatformConfig"):
            _create_backend(
                OperatingMode.PAPER,
                InMemoryEventLog(),
                clock,
                config=None,
                normalizer=MassiveNormalizer(clock=clock),
                cost_model=DefaultCostModel(),
            )

    def test_returns_populated_backend_bundle(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("MASSIVE_API_KEY", "fake_key")
        config = _minimal_paper_config()
        clock = SimulatedClock()
        normalizer = MassiveNormalizer(clock=clock)

        with patch("feelies.execution.paper_backend.build_paper_backend") as mock_build:
            sentinel_backend = object()
            sentinel_feed = object()
            sentinel_ib = object()
            mock_build.return_value = (
                sentinel_backend,
                sentinel_feed,
                sentinel_ib,
            )
            bundle = _create_backend(
                OperatingMode.PAPER,
                InMemoryEventLog(),
                clock,
                config=config,
                normalizer=normalizer,
                cost_model=DefaultCostModel(),
            )

        assert isinstance(bundle, _BackendBundle)
        assert bundle.backend is sentinel_backend
        assert bundle.live_feed is sentinel_feed
        assert bundle.ib_connection is sentinel_ib
        assert bundle.backtest_router is None

    def test_forwards_config_fields_to_paper_backend(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("MASSIVE_API_KEY", "fake_key_xyz")
        config = _minimal_paper_config(
            ib_host="10.20.30.40",
            ib_port=4001,
            ib_client_id=99,
            massive_ws_url="wss://prod.example.com/stocks",
            symbols=frozenset({"NVDA", "TSLA"}),
        )
        clock = SimulatedClock()
        normalizer = MassiveNormalizer(clock=clock)

        with patch("feelies.execution.paper_backend.build_paper_backend") as mock_build:
            mock_build.return_value = (object(), object(), object())
            _create_backend(
                OperatingMode.PAPER,
                InMemoryEventLog(),
                clock,
                config=config,
                normalizer=normalizer,
                cost_model=DefaultCostModel(),
            )

        kwargs = mock_build.call_args.kwargs
        assert kwargs["massive_api_key"] == "fake_key_xyz"
        assert sorted(kwargs["symbols"]) == ["NVDA", "TSLA"]
        assert kwargs["clock"] is clock
        assert kwargs["normalizer"] is normalizer
        assert kwargs["ib_host"] == "10.20.30.40"
        assert kwargs["ib_port"] == 4001
        assert kwargs["ib_client_id"] == 99
        assert kwargs["massive_ws_url"] == "wss://prod.example.com/stocks"

    def test_whitespace_only_api_key_raises_configuration_error(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("MASSIVE_API_KEY", "   ")
        config = _minimal_paper_config()
        clock = SimulatedClock()
        with pytest.raises(ConfigurationError, match="MASSIVE_API_KEY"):
            _create_backend(
                OperatingMode.PAPER,
                InMemoryEventLog(),
                clock,
                config=config,
                normalizer=MassiveNormalizer(clock=clock),
                cost_model=DefaultCostModel(),
            )


def _write_paper_alpha(directory: Path) -> None:
    (directory / "paper.alpha.yaml").write_text(
        _PAPER_SIGNAL_ALPHA_YAML,
        encoding="utf-8",
    )


def _paper_platform_config(tmp_path: Path) -> PlatformConfig:
    return PlatformConfig(
        symbols=frozenset({"AAPL"}),
        mode=OperatingMode.PAPER,
        alpha_spec_dir=tmp_path,
        account_equity=100_000.0,
        sensor_specs=_TEST_SENSOR_SPECS,
        enforce_trend_mechanism=False,
        ib_host="127.0.0.1",
        ib_port=4002,
        ib_client_id=7,
        massive_ws_url="wss://test.example/stocks",
    )


class TestBuildPlatformPaperBranch:
    def test_auto_normalizer_shared_with_orchestrator_and_feed(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setenv("MASSIVE_API_KEY", "fake_key")
        _write_paper_alpha(tmp_path)
        config = _paper_platform_config(tmp_path)
        captured: dict[str, object] = {}

        def _fake_build(**kwargs: object) -> tuple[object, object, object]:
            captured["normalizer"] = kwargs["normalizer"]
            return (object(), object(), object())

        with patch("feelies.execution.paper_backend.build_paper_backend", side_effect=_fake_build):
            orchestrator, _ = build_platform(config)

        assert isinstance(orchestrator._normalizer, MassiveNormalizer)
        assert orchestrator._normalizer is captured["normalizer"]
        assert orchestrator.live_feed is not None  # type: ignore[attr-defined]
        assert orchestrator.ib_connection is not None  # type: ignore[attr-defined]

    def test_paper_without_session_open_ns_auto_anchors(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setenv("MASSIVE_API_KEY", "fake_key")
        _write_paper_alpha(tmp_path)
        config = _paper_platform_config(tmp_path)
        assert config.session_open_ns is None

        with patch(
            "feelies.execution.paper_backend.build_paper_backend",
            return_value=(object(), object(), object()),
        ):
            _, out_config = build_platform(config)

        assert out_config.session_open_ns is not None
        assert out_config.session_open_ns > 0

    def test_nested_paper_yaml_block_parses_connection_fields(
        self,
        tmp_path: Path,
    ) -> None:
        yaml_path = tmp_path / "platform.yaml"
        yaml_path.write_text(
            textwrap.dedent(
                """\
                symbols: [SPY]
                mode: PAPER
                alpha_specs: [alpha.yaml]
                paper:
                  ib_host: 10.0.0.1
                  ib_port: 4002
                  ib_client_id: 55
                  massive_ws_url: wss://example.test/stocks
                """
            ),
            encoding="utf-8",
        )
        config = PlatformConfig.from_yaml(yaml_path)
        assert config.ib_host == "10.0.0.1"
        assert config.ib_port == 4002
        assert config.ib_client_id == 55
        assert config.massive_ws_url == "wss://example.test/stocks"

    def test_top_level_ib_port_overrides_nested_paper_block(
        self,
        tmp_path: Path,
    ) -> None:
        yaml_path = tmp_path / "platform.yaml"
        yaml_path.write_text(
            textwrap.dedent(
                """\
                symbols: [SPY]
                mode: PAPER
                alpha_specs: [alpha.yaml]
                ib_port: 4002
                paper:
                  ib_port: 4001
                """
            ),
            encoding="utf-8",
        )
        config = PlatformConfig.from_yaml(yaml_path)
        assert config.ib_port == 4002


class TestPaperIbPortWarning:
    def test_paper_mode_ib_port_4001_emits_warning(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        import logging
        from dataclasses import replace

        monkeypatch.setenv("MASSIVE_API_KEY", "fake_key")
        _write_paper_alpha(tmp_path)
        config = replace(_paper_platform_config(tmp_path), ib_port=4001)

        with caplog.at_level(logging.WARNING):
            with patch(
                "feelies.execution.paper_backend.build_paper_backend",
                return_value=(object(), object(), object()),
            ):
                build_platform(config)

        assert any("ib_port=4001" in rec.message for rec in caplog.records)


# Note: end-to-end ``build_platform(PAPER)`` session lifecycle is
# exercised by ``scripts/run_paper.py`` smoke-tests; here we lock the
# internal composition contract of ``_create_backend`` and the
# orchestrator plumbing emitted by ``build_platform``.
