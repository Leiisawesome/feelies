"""Tests for PlatformConfig — YAML loading, validation, and snapshot."""

from __future__ import annotations

from pathlib import Path

import pytest

from feelies.core.config import ConfigSnapshot
from feelies.core.errors import ConfigurationError
from feelies.core.platform_config import OperatingMode, PlatformConfig


# ── Construction and defaults ───────────────────────────────────────


class TestDefaults:
    def test_default_mode_is_backtest(self) -> None:
        cfg = PlatformConfig(symbols=frozenset({"AAPL"}), alpha_specs=[Path("x.yaml")])
        assert cfg.mode == OperatingMode.BACKTEST

    def test_default_regime_engine(self) -> None:
        cfg = PlatformConfig(symbols=frozenset({"AAPL"}), alpha_specs=[Path("x.yaml")])
        assert cfg.regime_engine == "hmm_3state_fractional"

    def test_default_risk_params(self) -> None:
        cfg = PlatformConfig(symbols=frozenset({"AAPL"}), alpha_specs=[Path("x.yaml")])
        assert cfg.risk_max_position_per_symbol == 1000
        assert cfg.risk_max_gross_exposure_pct == 20.0
        assert cfg.risk_max_drawdown_pct == 5.0

    def test_default_account_equity(self) -> None:
        cfg = PlatformConfig(symbols=frozenset({"AAPL"}), alpha_specs=[Path("x.yaml")])
        assert cfg.account_equity == 1_000_000.0


# ── Validation ──────────────────────────────────────────────────────


class TestValidation:
    def test_empty_symbols_raises(self) -> None:
        cfg = PlatformConfig(symbols=frozenset(), alpha_specs=[Path("x.yaml")])
        with pytest.raises(ConfigurationError, match="symbols must be non-empty"):
            cfg.validate()

    def test_no_alpha_source_raises(self) -> None:
        cfg = PlatformConfig(symbols=frozenset({"AAPL"}))
        with pytest.raises(ConfigurationError, match="alpha_spec_dir or alpha_specs"):
            cfg.validate()

    def test_alpha_spec_dir_not_exist_raises(self, tmp_path: Path) -> None:
        bogus = tmp_path / "nonexistent"
        cfg = PlatformConfig(symbols=frozenset({"AAPL"}), alpha_spec_dir=bogus)
        with pytest.raises(ConfigurationError, match="alpha_spec_dir does not exist"):
            cfg.validate()

    def test_valid_with_alpha_spec_dir(self, tmp_path: Path) -> None:
        cfg = PlatformConfig(symbols=frozenset({"AAPL"}), alpha_spec_dir=tmp_path)
        cfg.validate()

    def test_valid_with_alpha_specs(self) -> None:
        cfg = PlatformConfig(
            symbols=frozenset({"AAPL"}),
            alpha_specs=[Path("some.alpha.yaml")],
        )
        cfg.validate()

    def test_zero_position_limit_raises(self) -> None:
        cfg = PlatformConfig(
            symbols=frozenset({"AAPL"}),
            alpha_specs=[Path("x.yaml")],
            risk_max_position_per_symbol=0,
        )
        with pytest.raises(ConfigurationError, match="risk_max_position_per_symbol"):
            cfg.validate()

    def test_zero_equity_raises(self) -> None:
        cfg = PlatformConfig(
            symbols=frozenset({"AAPL"}),
            alpha_specs=[Path("x.yaml")],
            account_equity=0.0,
        )
        with pytest.raises(ConfigurationError, match="account_equity"):
            cfg.validate()


# ── Snapshot (invariant 13) ─────────────────────────────────────────


class TestSnapshot:
    def test_returns_config_snapshot(self) -> None:
        cfg = PlatformConfig(symbols=frozenset({"AAPL"}), alpha_specs=[Path("x.yaml")])
        snap = cfg.snapshot()
        assert isinstance(snap, ConfigSnapshot)

    def test_snapshot_contains_symbols(self) -> None:
        cfg = PlatformConfig(symbols=frozenset({"AAPL", "MSFT"}), alpha_specs=[Path("x.yaml")])
        snap = cfg.snapshot()
        assert snap.data["symbols"] == ["AAPL", "MSFT"]

    def test_snapshot_contains_mode(self) -> None:
        cfg = PlatformConfig(
            symbols=frozenset({"AAPL"}),
            alpha_specs=[Path("x.yaml")],
            mode=OperatingMode.BACKTEST,
        )
        snap = cfg.snapshot()
        assert snap.data["mode"] == "BACKTEST"

    def test_snapshot_checksum_is_deterministic(self) -> None:
        cfg = PlatformConfig(symbols=frozenset({"AAPL"}), alpha_specs=[Path("x.yaml")])
        snap1 = cfg.snapshot()
        snap2 = cfg.snapshot()
        assert snap1.checksum == snap2.checksum

    def test_different_configs_different_checksums(self) -> None:
        cfg_a = PlatformConfig(symbols=frozenset({"AAPL"}), alpha_specs=[Path("x.yaml")])
        cfg_b = PlatformConfig(symbols=frozenset({"MSFT"}), alpha_specs=[Path("x.yaml")])
        assert cfg_a.snapshot().checksum != cfg_b.snapshot().checksum

    def test_snapshot_version_matches(self) -> None:
        cfg = PlatformConfig(
            symbols=frozenset({"AAPL"}),
            alpha_specs=[Path("x.yaml")],
            version="2.0.0",
        )
        assert cfg.snapshot().version == "2.0.0"

    def test_snapshot_is_frozen(self) -> None:
        cfg = PlatformConfig(symbols=frozenset({"AAPL"}), alpha_specs=[Path("x.yaml")])
        snap = cfg.snapshot()
        with pytest.raises(AttributeError):
            snap.version = "hacked"  # type: ignore[misc]


# ── YAML loading ────────────────────────────────────────────────────


class TestFromYAML:
    def test_loads_basic_yaml(self, tmp_path: Path) -> None:
        yaml_content = """\
symbols:
  - AAPL
  - MSFT
mode: BACKTEST
alpha_spec_dir: .
account_equity: 500000
"""
        (tmp_path / "config.yaml").write_text(yaml_content)
        cfg = PlatformConfig.from_yaml(tmp_path / "config.yaml")
        assert cfg.symbols == frozenset({"AAPL", "MSFT"})
        assert cfg.mode == OperatingMode.BACKTEST
        assert cfg.account_equity == 500_000.0

    def test_unknown_mode_raises(self, tmp_path: Path) -> None:
        yaml_content = "symbols: [AAPL]\nmode: INVALID_MODE\nalpha_specs: [x.yaml]\n"
        (tmp_path / "bad.yaml").write_text(yaml_content)
        with pytest.raises(ConfigurationError, match="Unknown mode"):
            PlatformConfig.from_yaml(tmp_path / "bad.yaml")

    def test_missing_file_raises(self) -> None:
        with pytest.raises(ConfigurationError, match="Failed to read"):
            PlatformConfig.from_yaml("/nonexistent/config.yaml")

    def test_non_mapping_raises(self, tmp_path: Path) -> None:
        (tmp_path / "bad.yaml").write_text("just a string")
        with pytest.raises(ConfigurationError, match="root must be a YAML mapping"):
            PlatformConfig.from_yaml(tmp_path / "bad.yaml")

    def test_paper_mode_parses(self, tmp_path: Path) -> None:
        yaml_content = "symbols: [AAPL]\nmode: PAPER\nalpha_specs: [x.yaml]\n"
        (tmp_path / "config.yaml").write_text(yaml_content)
        cfg = PlatformConfig.from_yaml(tmp_path / "config.yaml")
        assert cfg.mode == OperatingMode.PAPER

    def test_live_mode_parses(self, tmp_path: Path) -> None:
        yaml_content = "symbols: [AAPL]\nmode: LIVE\nalpha_specs: [x.yaml]\n"
        (tmp_path / "config.yaml").write_text(yaml_content)
        cfg = PlatformConfig.from_yaml(tmp_path / "config.yaml")
        assert cfg.mode == OperatingMode.LIVE

    def test_case_insensitive_mode(self, tmp_path: Path) -> None:
        yaml_content = "symbols: [AAPL]\nmode: backtest\nalpha_specs: [x.yaml]\n"
        (tmp_path / "config.yaml").write_text(yaml_content)
        cfg = PlatformConfig.from_yaml(tmp_path / "config.yaml")
        assert cfg.mode == OperatingMode.BACKTEST

    def test_risk_params_from_yaml(self, tmp_path: Path) -> None:
        yaml_content = """\
symbols: [AAPL]
alpha_specs: [x.yaml]
risk_max_position_per_symbol: 500
risk_max_gross_exposure_pct: 10.0
risk_max_drawdown_pct: 2.5
"""
        (tmp_path / "config.yaml").write_text(yaml_content)
        cfg = PlatformConfig.from_yaml(tmp_path / "config.yaml")
        assert cfg.risk_max_position_per_symbol == 500
        assert cfg.risk_max_gross_exposure_pct == 10.0
        assert cfg.risk_max_drawdown_pct == 2.5

    def test_parameter_overrides_from_yaml(self, tmp_path: Path) -> None:
        yaml_content = """\
symbols: [AAPL]
alpha_specs: [x.yaml]
parameter_overrides:
  my_alpha:
    window: 20
    threshold: 0.5
"""
        (tmp_path / "config.yaml").write_text(yaml_content)
        cfg = PlatformConfig.from_yaml(tmp_path / "config.yaml")
        assert cfg.parameter_overrides["my_alpha"]["window"] == 20
        assert cfg.parameter_overrides["my_alpha"]["threshold"] == 0.5

    def test_backtest_fill_latency_ns_from_yaml(self, tmp_path: Path) -> None:
        yaml_content = """\
symbols: [AAPL]
alpha_specs: [x.yaml]
backtest_fill_latency_ns: 5000
"""
        (tmp_path / "config.yaml").write_text(yaml_content)
        cfg = PlatformConfig.from_yaml(tmp_path / "config.yaml")
        assert cfg.backtest_fill_latency_ns == 5000

    def test_backtest_fill_latency_ns_defaults_to_zero(self, tmp_path: Path) -> None:
        yaml_content = """\
symbols: [AAPL]
alpha_specs: [x.yaml]
"""
        (tmp_path / "config.yaml").write_text(yaml_content)
        cfg = PlatformConfig.from_yaml(tmp_path / "config.yaml")
        assert cfg.backtest_fill_latency_ns == 0

    def test_backtest_fill_latency_ns_in_snapshot(self) -> None:
        cfg = PlatformConfig(
            symbols=frozenset({"AAPL"}),
            alpha_specs=[Path("x.yaml")],
            backtest_fill_latency_ns=1234,
        )
        snap = cfg.snapshot()
        assert snap.data["backtest_fill_latency_ns"] == 1234

    def test_backtest_fill_latency_ns_yaml_roundtrip(self, tmp_path: Path) -> None:
        yaml_content = """\
symbols: [AAPL]
alpha_specs: [x.yaml]
backtest_fill_latency_ns: 9999
"""
        (tmp_path / "config.yaml").write_text(yaml_content)
        cfg = PlatformConfig.from_yaml(tmp_path / "config.yaml")
        snap = cfg.snapshot()
        assert snap.data["backtest_fill_latency_ns"] == 9999


# ── Configuration protocol compliance ──────────────────────────────


class TestProtocolCompliance:
    def test_satisfies_configuration_protocol(self) -> None:
        from feelies.core.config import Configuration

        cfg = PlatformConfig(symbols=frozenset({"AAPL"}), alpha_specs=[Path("x.yaml")])
        assert hasattr(cfg, "version")
        assert hasattr(cfg, "symbols")
        assert hasattr(cfg, "snapshot")
        assert hasattr(cfg, "validate")

        assert isinstance(cfg.version, str)
        assert isinstance(cfg.symbols, frozenset)
        assert isinstance(cfg.snapshot(), ConfigSnapshot)
