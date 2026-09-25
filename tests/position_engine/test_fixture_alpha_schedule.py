"""Schedule of sig_position_fixture_v1.

Build path of tests/position_engine/test_p10_contract_surface.py:
InMemoryEventLog, build_platform, subscribe_all, boot, run_backtest.
"""

from __future__ import annotations

from pathlib import Path

from feelies.bootstrap import build_platform
from feelies.core.events import (
    MarkRailUpdate,
    OrderAck,
    OrderAckStatus,
    OrderRequest,
    RiskVerdict,
    Signal,
    SignalDirection,
    SlicePositionUpdate,
)
from feelies.core.platform_config import OperatingMode, PlatformConfig
from feelies.storage.memory_event_log import InMemoryEventLog
from tests.fixtures.event_logs._generate import SESSION_OPEN_NS
from tests.position_engine.tapes import make_tape

_FIXTURE = Path("tests/position_engine/fixtures/sig_position_fixture_v1.alpha.yaml")
_HORIZON_NS = 120 * 1_000_000_000
_NEEDED_SENSORS = frozenset({"ofi_ewma", "book_imbalance", "spread_z_30d", "realized_vol_30s"})


def _sensor_specs() -> tuple[object, ...]:
    """Same four specs as test_p15_exit_policy._platform (bt_netting_contest.yaml)."""
    contra = PlatformConfig.from_yaml(Path("configs/bt_netting_contest.yaml"))
    return tuple(spec for spec in contra.sensor_specs if spec.sensor_id in _NEEDED_SENSORS)


def _replay(seed: int) -> list[object]:
    tape = make_tape(seed=seed, n=6000, symbol="SYN")
    log = InMemoryEventLog()
    log.append_batch(tape)
    config = PlatformConfig(
        symbols=frozenset({"SYN"}),
        mode=OperatingMode.BACKTEST,
        alpha_specs=[_FIXTURE],
        sensor_specs=_sensor_specs(),
        regime_engine=None,
        enforce_trend_mechanism=False,
        session_open_ns=SESSION_OPEN_NS,
    )
    orchestrator, resolved = build_platform(config, event_log=log)
    seen: list[object] = []
    orchestrator._bus.subscribe_all(seen.append)
    orchestrator.boot(resolved)
    orchestrator.run_backtest()
    return seen


def _boundaries(seen: list[object]) -> dict[int, Signal]:
    out: dict[int, Signal] = {}
    for event in seen:
        if type(event) is not Signal:
            continue
        boundary = (event.timestamp_ns - SESSION_OPEN_NS) // _HORIZON_NS
        out[boundary] = event
    return out


def test_s1_odd_boundaries_only() -> None:
    got = _boundaries(_replay(1))
    assert set(got) == {1, 3}, sorted(got)
    assert got[1].direction is SignalDirection.LONG
    assert got[3].direction is SignalDirection.SHORT


def test_s2_strategy_id() -> None:
    for signal in _boundaries(_replay(1)).values():
        assert signal.strategy_id == "sig_position_fixture_v1"


def test_s3_seed_independent() -> None:
    got = _boundaries(_replay(2))
    assert set(got) == {1, 3}, sorted(got)
    assert got[1].direction is SignalDirection.LONG
    assert got[3].direction is SignalDirection.SHORT


def test_s4_order_counts() -> None:
    """Report only. Counts are printed; this test does not assert them."""
    seen = _replay(1)
    orders = [e for e in seen if type(e) is OrderRequest]
    fills = [e for e in seen if type(e) is OrderAck and e.status is OrderAckStatus.FILLED]
    slices = [e for e in seen if type(e) is SlicePositionUpdate]
    rails = [e for e in seen if type(e) is MarkRailUpdate]
    verdicts = [e for e in seen if type(e) is RiskVerdict]
    reasons = sorted({v.reason for v in verdicts})
    print(
        f"S4 OrderRequest={len(orders)} FILLED={len(fills)} "
        f"SlicePositionUpdate={len(slices)} MarkRailUpdate={len(rails)} "
        f"verdicts={reasons}"
    )
