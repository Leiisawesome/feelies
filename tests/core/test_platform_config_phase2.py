"""Tests for Phase-2 fields on PlatformConfig (validation + YAML)."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from feelies.core.errors import ConfigurationError
from feelies.core.events import NBBOQuote, Trade
from feelies.core.platform_config import PlatformConfig
from feelies.sensors.spec import SensorSpec
from tests.sensors._helpers import CountingSensor


def _base_config(**overrides) -> PlatformConfig:
    base = dict(
        symbols=frozenset({"AAPL"}),
        alpha_specs=[Path("dummy.alpha.yaml")],
    )
    base.update(overrides)
    return PlatformConfig(**base)


class TestDefaults:
    def test_phase2_defaults_are_backward_compatible(self) -> None:
        cfg = _base_config()
        assert cfg.session_open_ns is None
        assert cfg.sensor_specs == ()
        assert cfg.event_calendar_path is None
        assert cfg.market_id == "US_EQUITY"
        assert cfg.session_kind == "RTH"
        assert cfg.horizons_seconds == frozenset({30, 120, 300, 900, 1800})

    def test_default_config_validates(self) -> None:
        _base_config().validate()


class TestValidation:
    def test_negative_session_open_rejected(self) -> None:
        cfg = _base_config(session_open_ns=-1)
        with pytest.raises(ConfigurationError, match="session_open_ns"):
            cfg.validate()

    def test_zero_horizon_rejected(self) -> None:
        cfg = _base_config(horizons_seconds=frozenset({0, 30}))
        with pytest.raises(ConfigurationError, match="horizons_seconds"):
            cfg.validate()

    def test_empty_market_id_rejected(self) -> None:
        cfg = _base_config(market_id="")
        with pytest.raises(ConfigurationError, match="market_id"):
            cfg.validate()

    def test_empty_session_kind_rejected(self) -> None:
        cfg = _base_config(session_kind="")
        with pytest.raises(ConfigurationError, match="session_kind"):
            cfg.validate()

    def test_missing_event_calendar_file_rejected(self, tmp_path: Path) -> None:
        cfg = _base_config(event_calendar_path=tmp_path / "missing.yaml")
        with pytest.raises(ConfigurationError, match="event_calendar_path"):
            cfg.validate()


class TestSensorSpecValidation:
    def test_duplicate_sensor_spec_rejected(self) -> None:
        spec = SensorSpec(
            sensor_id="x", sensor_version="1.0.0", cls=CountingSensor,
            subscribes_to=(NBBOQuote,), params={"sensor_id": "x"},
        )
        cfg = _base_config(sensor_specs=(spec, spec))
        with pytest.raises(ConfigurationError, match="duplicate|already"):
            cfg.validate()

    def test_unknown_input_sensor_id_rejected(self) -> None:
        spec = SensorSpec(
            sensor_id="downstream", sensor_version="1.0.0", cls=CountingSensor,
            subscribes_to=(NBBOQuote,), input_sensor_ids=("upstream",),
            params={"sensor_id": "downstream"},
        )
        cfg = _base_config(sensor_specs=(spec,))
        with pytest.raises(ConfigurationError, match="upstream"):
            cfg.validate()

    def test_topological_misorder_rejected(self) -> None:
        upstream = SensorSpec(
            sensor_id="upstream", sensor_version="1.0.0", cls=CountingSensor,
            subscribes_to=(NBBOQuote,), params={"sensor_id": "upstream"},
        )
        downstream = SensorSpec(
            sensor_id="downstream", sensor_version="1.0.0", cls=CountingSensor,
            subscribes_to=(NBBOQuote,), input_sensor_ids=("upstream",),
            params={"sensor_id": "downstream"},
        )
        cfg = _base_config(sensor_specs=(downstream, upstream))
        with pytest.raises(ConfigurationError, match="reorder|topological|precede"):
            cfg.validate()

    def test_correct_topological_order_accepted(self) -> None:
        upstream = SensorSpec(
            sensor_id="upstream", sensor_version="1.0.0", cls=CountingSensor,
            subscribes_to=(NBBOQuote,), params={"sensor_id": "upstream"},
        )
        downstream = SensorSpec(
            sensor_id="downstream", sensor_version="1.0.0", cls=CountingSensor,
            subscribes_to=(NBBOQuote,), input_sensor_ids=("upstream",),
            params={"sensor_id": "downstream"},
        )
        cfg = _base_config(sensor_specs=(upstream, downstream))
        cfg.validate()


class TestSnapshot:
    def test_snapshot_includes_phase2_fields(self) -> None:
        cfg = _base_config(
            session_open_ns=1_768_532_400_000_000_000,
            market_id="US_EQUITY",
            session_kind="RTH",
            horizons_seconds=frozenset({30, 120}),
        )
        snap = cfg.snapshot()
        assert "session_open_ns" in snap.data
        assert "horizons_seconds" in snap.data
        assert snap.data["horizons_seconds"] == [30, 120]
        assert snap.data["market_id"] == "US_EQUITY"

    def test_snapshot_serializes_sensor_specs_deterministically(self) -> None:
        spec = SensorSpec(
            sensor_id="x", sensor_version="1.0.0", cls=CountingSensor,
            subscribes_to=(NBBOQuote, Trade), params={"sensor_id": "x"},
        )
        cfg = _base_config(sensor_specs=(spec,))
        snap_a = cfg.snapshot()
        snap_b = cfg.snapshot()
        assert snap_a.checksum == snap_b.checksum
        # The sensor entry must mention class as a dotted path string.
        assert "tests.sensors._helpers.CountingSensor" in str(snap_a.data)


class TestYamlLoader:
    def test_yaml_loads_phase2_fields(self, tmp_path: Path) -> None:
        yaml_text = dedent("""
            version: "0.2.0"
            author: tests
            symbols: ["AAPL"]
            mode: BACKTEST
            alpha_specs: ["dummy.alpha.yaml"]
            session_open_ns: 1768532400000000000
            horizons_seconds: [30, 120]
            market_id: US_EQUITY
            session_kind: RTH
        """).strip()
        path = tmp_path / "cfg.yaml"
        path.write_text(yaml_text, encoding="utf-8")
        cfg = PlatformConfig.from_yaml(path)
        assert cfg.session_open_ns == 1_768_532_400_000_000_000
        assert cfg.horizons_seconds == frozenset({30, 120})
        assert cfg.market_id == "US_EQUITY"
        assert cfg.session_kind == "RTH"

    def test_yaml_omits_phase2_fields_uses_defaults(self, tmp_path: Path) -> None:
        yaml_text = dedent("""
            version: "0.1.0"
            author: tests
            symbols: ["AAPL"]
            mode: BACKTEST
            alpha_specs: ["dummy.alpha.yaml"]
        """).strip()
        path = tmp_path / "cfg.yaml"
        path.write_text(yaml_text, encoding="utf-8")
        cfg = PlatformConfig.from_yaml(path)
        assert cfg.session_open_ns is None
        assert cfg.sensor_specs == ()
        assert cfg.market_id == "US_EQUITY"
