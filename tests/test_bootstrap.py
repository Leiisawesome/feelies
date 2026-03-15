"""Unit tests for build_platform bootstrap."""

from __future__ import annotations

from pathlib import Path

import pytest

from feelies.bootstrap import build_platform
from feelies.core.clock import SimulatedClock
from feelies.core.errors import ConfigurationError
from feelies.core.platform_config import OperatingMode, PlatformConfig
from feelies.kernel.orchestrator import Orchestrator

ALPHA_SPEC_YAML = """\
alpha_id: test_alpha
version: "1.0"
author: test
description: test alpha
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
features:
  - feature_id: mid
    version: "1.0"
    description: mid price
    depends_on: []
    warm_up:
      min_events: 1
    computation: |
      def initial_state():
          return {}
      def update(quote, state, params):
          return float((quote.bid + quote.ask) / 2)
signal: |
  def evaluate(features, params):
      return None
"""


def _write_alpha_spec(directory: Path, filename: str = "test.alpha.yaml") -> Path:
    spec_file = directory / filename
    spec_file.write_text(ALPHA_SPEC_YAML, encoding="utf-8")
    return spec_file


def _make_config(tmp_path: Path, **overrides) -> PlatformConfig:
    defaults = dict(
        symbols=frozenset({"AAPL"}),
        mode=OperatingMode.BACKTEST,
        alpha_spec_dir=tmp_path,
        account_equity=100_000.0,
    )
    defaults.update(overrides)
    return PlatformConfig(**defaults)


class TestBuildPlatform:

    def test_returns_orchestrator_with_valid_config(self, tmp_path: Path) -> None:
        _write_alpha_spec(tmp_path)
        config = _make_config(tmp_path)
        orchestrator, returned_config = build_platform(config)
        assert isinstance(orchestrator, Orchestrator)
        assert returned_config is config

    def test_regime_engine_wired_when_configured(self, tmp_path: Path) -> None:
        _write_alpha_spec(tmp_path)
        config = _make_config(tmp_path, regime_engine="hmm_3state_fractional")
        orchestrator, _ = build_platform(config)
        assert orchestrator._regime_engine is not None

    def test_regime_engine_none_when_not_configured(self, tmp_path: Path) -> None:
        _write_alpha_spec(tmp_path)
        config = _make_config(tmp_path, regime_engine=None)
        orchestrator, _ = build_platform(config)
        assert orchestrator._regime_engine is None

    def test_backtest_mode_creates_simulated_clock(self, tmp_path: Path) -> None:
        _write_alpha_spec(tmp_path)
        config = _make_config(tmp_path, regime_engine=None)
        orchestrator, _ = build_platform(config)
        assert isinstance(orchestrator._clock, SimulatedClock)

    def test_invalid_config_raises_configuration_error(self) -> None:
        config = PlatformConfig(symbols=frozenset(), mode=OperatingMode.BACKTEST)
        with pytest.raises(ConfigurationError, match="symbols must be non-empty"):
            build_platform(config)

    def test_unknown_regime_engine_treated_as_none(self, tmp_path: Path) -> None:
        _write_alpha_spec(tmp_path)
        config = _make_config(tmp_path, regime_engine="nonexistent_engine")
        orchestrator, _ = build_platform(config)
        assert orchestrator._regime_engine is None
