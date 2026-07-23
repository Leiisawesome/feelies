"""Tests for BACKTEST sensor-closure pruning (hot-path perf)."""

from __future__ import annotations

from pathlib import Path

import pytest

from feelies.bootstrap import _maybe_prune_unused_sensors
from feelies.core.errors import ConfigurationError
from feelies.core.events import NBBOQuote
from feelies.core.platform_config import OperatingMode, PlatformConfig
from feelies.sensors.impl.book_imbalance import BookImbalanceSensor
from feelies.sensors.impl.ofi_ewma import OFIEwmaSensor
from feelies.sensors.impl.spread_z_30d import SpreadZScoreSensor
from feelies.sensors.spec import SensorSpec


def _specs(*ids: str) -> tuple[SensorSpec, ...]:
    cls_map = {
        "ofi_ewma": OFIEwmaSensor,
        "book_imbalance": BookImbalanceSensor,
        "spread_z_30d": SpreadZScoreSensor,
    }
    out: list[SensorSpec] = []
    for sid in ids:
        out.append(
            SensorSpec(
                sensor_id=sid,
                sensor_version="1.0.0",
                cls=cls_map[sid],
                params={},
                subscribes_to=(NBBOQuote,),
            )
        )
    return tuple(out)


class _FakeSignalAlpha:
    def __init__(self, depends: tuple[str, ...]) -> None:
        self.depends_on_sensors = depends


class _FakeRegistry:
    def __init__(self, depends: tuple[str, ...]) -> None:
        self._depends = depends

    def signal_alphas(self) -> list[_FakeSignalAlpha]:
        return [_FakeSignalAlpha(self._depends)]


def test_prune_opt_in_for_backtest() -> None:
    cfg = PlatformConfig(
        symbols=frozenset({"APP"}),
        alpha_specs=[Path("x.yaml")],
        mode=OperatingMode.BACKTEST,
        sensor_specs=_specs("ofi_ewma", "book_imbalance", "spread_z_30d"),
        prune_unused_sensors=True,
    )
    registry = _FakeRegistry(("ofi_ewma", "book_imbalance"))
    pruned = _maybe_prune_unused_sensors(cfg, registry)
    assert [s.sensor_id for s in pruned.sensor_specs] == ["ofi_ewma", "book_imbalance"]


def test_prune_off_by_default() -> None:
    cfg = PlatformConfig(
        symbols=frozenset({"APP"}),
        alpha_specs=[Path("x.yaml")],
        mode=OperatingMode.BACKTEST,
        sensor_specs=_specs("ofi_ewma", "book_imbalance", "spread_z_30d"),
    )
    registry = _FakeRegistry(("ofi_ewma",))
    out = _maybe_prune_unused_sensors(cfg, registry)
    assert len(out.sensor_specs) == 3


def test_prune_fails_closed_on_missing_required_sensor() -> None:
    cfg = PlatformConfig(
        symbols=frozenset({"APP"}),
        alpha_specs=[Path("x.yaml")],
        mode=OperatingMode.BACKTEST,
        sensor_specs=_specs("ofi_ewma"),
        prune_unused_sensors=True,
    )
    registry = _FakeRegistry(("ofi_ewma", "missing_sensor"))
    with pytest.raises(ConfigurationError, match="missing_sensor"):
        _maybe_prune_unused_sensors(cfg, registry)


def test_prune_preserves_registration_order() -> None:
    cfg = PlatformConfig(
        symbols=frozenset({"APP"}),
        alpha_specs=[Path("x.yaml")],
        mode=OperatingMode.BACKTEST,
        sensor_specs=_specs("spread_z_30d", "ofi_ewma", "book_imbalance"),
        prune_unused_sensors=True,
    )
    registry = _FakeRegistry(("book_imbalance", "spread_z_30d"))
    pruned = _maybe_prune_unused_sensors(cfg, registry)
    assert [s.sensor_id for s in pruned.sensor_specs] == [
        "spread_z_30d",
        "book_imbalance",
    ]
