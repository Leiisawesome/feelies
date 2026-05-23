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

    def test_default_regime_engine_options_empty(self) -> None:
        cfg = PlatformConfig(symbols=frozenset({"AAPL"}), alpha_specs=[Path("x.yaml")])
        assert cfg.regime_engine_options == {}

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

    def test_regime_engine_options_non_str_key_raises(self) -> None:
        cfg = PlatformConfig(
            symbols=frozenset({"AAPL"}),
            alpha_specs=[Path("x.yaml")],
            regime_engine_options={1: True},  # type: ignore[arg-type, dict-item]
        )
        with pytest.raises(ConfigurationError, match="regime_engine_options keys"):
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

    def test_regime_engine_options_from_yaml(self, tmp_path: Path) -> None:
        yaml_content = """\
symbols: [AAPL]
alpha_specs: [x.yaml]
regime_engine_options:
  transition_time_scaling_enabled: true
  transition_dt_reference_seconds: 0.1
"""
        (tmp_path / "config.yaml").write_text(yaml_content)
        cfg = PlatformConfig.from_yaml(tmp_path / "config.yaml")
        assert cfg.regime_engine_options["transition_time_scaling_enabled"] is True
        assert cfg.regime_engine_options["transition_dt_reference_seconds"] == 0.1

    def test_regime_engine_options_must_be_mapping_in_yaml(
        self, tmp_path: Path
    ) -> None:
        yaml_content = """\
symbols: [AAPL]
alpha_specs: [x.yaml]
regime_engine_options: not_a_mapping
"""
        (tmp_path / "bad.yaml").write_text(yaml_content)
        with pytest.raises(ConfigurationError, match="regime_engine_options"):
            PlatformConfig.from_yaml(tmp_path / "bad.yaml")

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

    def test_promotion_ledger_path_default_is_none(self, tmp_path: Path) -> None:
        # Workstream F-1: omitted key defaults to None (preserves bit-identical
        # snapshot for legacy configs that never set the field).
        yaml_content = """\
symbols: [AAPL]
alpha_specs: [x.yaml]
"""
        (tmp_path / "config.yaml").write_text(yaml_content)
        cfg = PlatformConfig.from_yaml(tmp_path / "config.yaml")
        assert cfg.promotion_ledger_path is None
        assert cfg.snapshot().data["promotion_ledger_path"] is None

    def test_promotion_ledger_path_from_yaml(self, tmp_path: Path) -> None:
        yaml_content = """\
symbols: [AAPL]
alpha_specs: [x.yaml]
promotion_ledger_path: data/promotion/ledger.jsonl
"""
        (tmp_path / "config.yaml").write_text(yaml_content)
        cfg = PlatformConfig.from_yaml(tmp_path / "config.yaml")
        assert cfg.promotion_ledger_path == Path("data/promotion/ledger.jsonl")

    def test_promotion_ledger_path_basename_in_snapshot(self) -> None:
        # Path-based fields are normalised to their basename in the
        # snapshot to keep config checksums stable across machines
        # (audit A-DET-02 / B-PROMO-04).
        cfg = PlatformConfig(
            symbols=frozenset({"AAPL"}),
            alpha_specs=[Path("x.yaml")],
            promotion_ledger_path=Path("/tmp/abs/path/promotion/ledger.jsonl"),
        )
        snap = cfg.snapshot()
        assert snap.data["promotion_ledger_path"] == "ledger.jsonl"


# ── Risk regime scales + disk-cache manifest health ─────────────────


class TestRiskRegimeScales:
    def test_regime_scale_must_be_positive(self) -> None:
        cfg = PlatformConfig(
            symbols=frozenset({"AAPL"}),
            alpha_specs=[Path("x.yaml")],
            risk_regime_vol_breakout_scale=0.0,
        )
        with pytest.raises(ConfigurationError, match="risk_regime_vol_breakout_scale"):
            cfg.validate()


class TestDiskCacheManifestHealth:
    def test_require_healthy_accepts_all_healthy_rows(self) -> None:
        cfg = PlatformConfig(
            symbols=frozenset({"AAPL"}),
            alpha_specs=[Path("x.yaml")],
            require_healthy_disk_cache_manifests=True,
            disk_cache_ingestion_health_rows=(
                ("AAPL", "2024-01-02", "HEALTHY"),
            ),
        )
        cfg.validate()

    def test_require_healthy_empty_rows_raises(self) -> None:
        cfg = PlatformConfig(
            symbols=frozenset({"AAPL"}),
            alpha_specs=[Path("x.yaml")],
            require_healthy_disk_cache_manifests=True,
            disk_cache_ingestion_health_rows=(),
        )
        with pytest.raises(ConfigurationError, match="non-empty"):
            cfg.validate()

    def test_require_healthy_rejects_non_healthy_row(self) -> None:
        cfg = PlatformConfig(
            symbols=frozenset({"AAPL"}),
            alpha_specs=[Path("x.yaml")],
            require_healthy_disk_cache_manifests=True,
            disk_cache_ingestion_health_rows=(
                ("AAPL", "2024-01-02", "GAP_DETECTED"),
            ),
        )
        with pytest.raises(ConfigurationError, match="not HEALTHY"):
            cfg.validate()


class TestBacktestIngestTerminalHealth:
    def test_validate_passes_when_enforce_true_but_rows_not_attached_yet(self) -> None:
        cfg = PlatformConfig(
            symbols=frozenset({"AAPL"}),
            alpha_specs=[Path("x.yaml")],
            backtest_enforce_ingest_terminal_health=True,
            ingest_terminal_symbol_health=(),
        )
        cfg.validate()

    def test_enforce_requires_every_symbol_present(self) -> None:
        cfg = PlatformConfig(
            symbols=frozenset({"AAPL", "MSFT"}),
            alpha_specs=[Path("x.yaml")],
            backtest_enforce_ingest_terminal_health=True,
            ingest_terminal_symbol_health=(("AAPL", "HEALTHY"),),
        )
        with pytest.raises(ConfigurationError, match="missing"):
            cfg.validate()

    def test_enforce_rejects_non_healthy_terminal(self) -> None:
        cfg = PlatformConfig(
            symbols=frozenset({"AAPL"}),
            alpha_specs=[Path("x.yaml")],
            backtest_enforce_ingest_terminal_health=True,
            ingest_terminal_symbol_health=(("AAPL", "GAP_DETECTED"),),
        )
        with pytest.raises(ConfigurationError, match="terminal health"):
            cfg.validate()

    def test_enforce_only_in_backtest_mode(self) -> None:
        cfg = PlatformConfig(
            symbols=frozenset({"AAPL"}),
            alpha_specs=[Path("x.yaml")],
            mode=OperatingMode.LIVE,
            backtest_enforce_ingest_terminal_health=True,
            ingest_terminal_symbol_health=(("AAPL", "HEALTHY"),),
        )
        with pytest.raises(ConfigurationError, match="BACKTEST"):
            cfg.validate()

    def test_enforce_succeeds_when_all_healthy(self) -> None:
        cfg = PlatformConfig(
            symbols=frozenset({"AAPL", "msft"}),
            alpha_specs=[Path("x.yaml")],
            backtest_enforce_ingest_terminal_health=True,
            ingest_terminal_symbol_health=(
                ("AAPL", "HEALTHY"),
                ("MSFT", "HEALTHY"),
            ),
        )
        cfg.validate()


# ── PAPER mode connection settings ─────────────────────────────────


class TestPaperConnectionSettings:
    def test_default_ib_paper_settings(self) -> None:
        cfg = PlatformConfig(
            symbols=frozenset({"AAPL"}), alpha_specs=[Path("x.yaml")],
        )
        assert cfg.ib_host == "127.0.0.1"
        assert cfg.ib_port == 4002
        assert cfg.ib_client_id == 1
        assert cfg.massive_ws_url == "wss://socket.massive.com/stocks"

    def test_paper_block_lifted_to_top_level(self, tmp_path: Path) -> None:
        yaml_content = """\
symbols: [AAPL]
mode: PAPER
alpha_specs: [x.yaml]
paper:
  ib_host: 10.0.0.5
  ib_port: 4003
  ib_client_id: 42
  massive_ws_url: wss://test.example/stocks
"""
        (tmp_path / "config.yaml").write_text(yaml_content)
        cfg = PlatformConfig.from_yaml(tmp_path / "config.yaml")
        assert cfg.ib_host == "10.0.0.5"
        assert cfg.ib_port == 4003
        assert cfg.ib_client_id == 42
        assert cfg.massive_ws_url == "wss://test.example/stocks"

    def test_flat_keys_also_supported(self, tmp_path: Path) -> None:
        yaml_content = """\
symbols: [AAPL]
mode: PAPER
alpha_specs: [x.yaml]
ib_host: 1.2.3.4
ib_port: 4001
ib_client_id: 7
"""
        (tmp_path / "config.yaml").write_text(yaml_content)
        cfg = PlatformConfig.from_yaml(tmp_path / "config.yaml")
        assert cfg.ib_host == "1.2.3.4"
        assert cfg.ib_port == 4001
        assert cfg.ib_client_id == 7

    def test_flat_keys_win_over_paper_block(self, tmp_path: Path) -> None:
        yaml_content = """\
symbols: [AAPL]
mode: PAPER
alpha_specs: [x.yaml]
ib_port: 5000
paper:
  ib_port: 4002
  ib_host: 192.168.1.1
"""
        (tmp_path / "config.yaml").write_text(yaml_content)
        cfg = PlatformConfig.from_yaml(tmp_path / "config.yaml")
        assert cfg.ib_port == 5000  # flat key wins
        assert cfg.ib_host == "192.168.1.1"  # falls through to paper block

    def test_paper_block_non_mapping_raises(self, tmp_path: Path) -> None:
        yaml_content = """\
symbols: [AAPL]
mode: PAPER
alpha_specs: [x.yaml]
paper: not_a_mapping
"""
        (tmp_path / "bad.yaml").write_text(yaml_content)
        with pytest.raises(ConfigurationError, match="'paper' must be a mapping"):
            PlatformConfig.from_yaml(tmp_path / "bad.yaml")

    def test_paper_settings_folded_into_snapshot(self) -> None:
        cfg = PlatformConfig(
            symbols=frozenset({"AAPL"}),
            alpha_specs=[Path("x.yaml")],
            ib_host="2.3.4.5",
            ib_port=4001,
            ib_client_id=99,
            massive_ws_url="wss://prod.example/stocks",
        )
        snap = cfg.snapshot()
        assert snap.data["ib_host"] == "2.3.4.5"
        assert snap.data["ib_port"] == 4001
        assert snap.data["ib_client_id"] == 99
        assert snap.data["massive_ws_url"] == "wss://prod.example/stocks"


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
