"""The backtest runner's --emit-edge-calibration writes realization factors."""

from __future__ import annotations

from decimal import Decimal

from feelies.core.events import Side
from feelies.forensics.edge_calibration import EdgeCalibrationStore
from feelies.harness.backtest_runner import _emit_edge_calibration
from feelies.storage.trade_journal import TradeRecord

_SEQ = 0


def _tr(strategy_id: str, realized_pnl: float, *, qty: int = 50, price: float = 100.0) -> TradeRecord:
    global _SEQ
    _SEQ += 1
    return TradeRecord(
        order_id=f"o{_SEQ}",
        symbol="APP",
        strategy_id=strategy_id,
        side=Side.BUY,
        requested_quantity=qty,
        filled_quantity=qty,
        fill_price=Decimal(str(price)),
        signal_timestamp_ns=_SEQ * 1000,
        submit_timestamp_ns=_SEQ * 1000 + 1,
        fill_timestamp_ns=_SEQ * 1000 + 2,
        cost_bps=Decimal("2"),
        fees=Decimal("0.1"),
        realized_pnl=Decimal(str(realized_pnl)),
        correlation_id=f"c{_SEQ}",
    )


class _FakeJournal:
    def __init__(self, records: list[TradeRecord]) -> None:
        self._records = records

    def query(self, **_kw: object):
        return iter(self._records)


class _FakeRegistry:
    def __init__(self, disclosed: dict[str, float]) -> None:
        self._modules = {
            aid: type("M", (), {"cost": type("C", (), {"edge_estimate_bps": edge})()})()
            for aid, edge in disclosed.items()
        }

    def alpha_ids(self):
        return frozenset(self._modules)

    def get(self, alpha_id: str):
        return self._modules[alpha_id]


class _FakeOrchestrator:
    def __init__(self, journal: _FakeJournal, registry: _FakeRegistry) -> None:
        self.trade_journal = journal
        self.alpha_registry = registry


def test_emit_writes_realization_factors(tmp_path) -> None:
    # kyle: 40 fills, zero realized edge -> lcb_factor 0; good: realized 10 bps
    # (pnl 5 / notional 5000) vs disclosed 10 -> factor ~1.0.
    records = [_tr("kyle", 0.0) for _ in range(40)] + [_tr("good", 5.0) for _ in range(40)]
    orch = _FakeOrchestrator(
        _FakeJournal(records), _FakeRegistry({"kyle": 11.7, "good": 10.0})
    )
    path = tmp_path / "edge_cal.json"

    _emit_edge_calibration(orch, str(path), version="2026-03-26")

    factors = EdgeCalibrationStore(path).factors()
    assert factors["kyle"] == 0.0  # zero realized edge -> gated out next run
    assert factors["good"] == 1.0  # realized >= disclosed -> no haircut


def test_emit_with_insufficient_fills_keeps_factor_one(tmp_path) -> None:
    # Single sparse session: < 30 fills -> factor 1.0 (no haircut), matching
    # the 'no improvement on one day' behaviour.
    records = [_tr("kyle", 0.0) for _ in range(6)]
    orch = _FakeOrchestrator(_FakeJournal(records), _FakeRegistry({"kyle": 11.7}))
    path = tmp_path / "edge_cal.json"
    _emit_edge_calibration(orch, str(path), version="day1")
    assert EdgeCalibrationStore(path).factors()["kyle"] == 1.0
