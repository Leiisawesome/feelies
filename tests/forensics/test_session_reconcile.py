"""Tests for the session-end reconciliation boundary job (close-the-loop)."""

from __future__ import annotations

from decimal import Decimal

from feelies.alpha.lifecycle import (
    AlphaLifecycle,
    AlphaLifecycleState,
    GateRequirements,
    PromotionEvidence,
)
from feelies.core.clock import SimulatedClock
from feelies.core.events import Side
from feelies.forensics.edge_calibration import EdgeCalibrationStore
from feelies.forensics.session_reconcile import (
    disclosed_edges_from_registry,
    reconcile_session,
)
from feelies.storage.trade_journal import TradeRecord

_SEQ = 0


def _tr(
    strategy_id: str, realized_pnl: float, fees: float, *, qty: int = 50, price: float = 100.0
) -> TradeRecord:
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
        fees=Decimal(str(fees)),
        realized_pnl=Decimal(str(realized_pnl)),
        correlation_id=f"c{_SEQ}",
    )


def _live(alpha_id: str, clock: SimulatedClock) -> AlphaLifecycle:
    lc = AlphaLifecycle(
        alpha_id=alpha_id,
        clock=clock,
        gate_requirements=GateRequirements(paper_min_days=1),
    )
    lc.promote_to_paper(
        PromotionEvidence(
            schema_valid=True, determinism_test_passed=True, feature_values_finite=True
        )
    )
    lc.promote_to_live(
        PromotionEvidence(
            paper_days=10, paper_sharpe=1.0, paper_hit_rate=0.55, cost_model_validated=True
        )
    )
    assert lc.is_live is True
    return lc


def test_reconcile_quarantines_bleeder_and_writes_calibration(tmp_path) -> None:
    clock = SimulatedClock(start_ns=0)
    lc = _live("bleeder", clock)
    store = EdgeCalibrationStore(tmp_path / "edge_cal.json")

    # 40 fills, zero realized edge, fee bleed -> net negative.
    records = [_tr("bleeder", 0.0, 1.0) for _ in range(40)]

    result = reconcile_session(
        records,
        disclosed_edges={"bleeder": 10.0},
        lifecycles={"bleeder": lc},
        calibration_store=store,
        calibration_version="2026-06-16",
        correlation_id="eod1",
    )

    # Automate: the LIVE bleeder was quarantined.
    assert [d.strategy_id for d in result.quarantined] == ["bleeder"]
    assert lc.state == AlphaLifecycleState.QUARANTINED

    # Calibrate: the store now carries a realization factor the next run's
    # gate will read — zero realized edge -> factor 0.
    factors = store.factors()
    assert factors["bleeder"] == 0.0
    assert result.calibrations["bleeder"].realized_edge_bps_mean == 0.0


def test_reconcile_without_lifecycles_computes_but_does_not_demote(tmp_path) -> None:
    records = [_tr("x", 0.0, 1.0) for _ in range(40)]
    result = reconcile_session(
        records,
        disclosed_edges={"x": 10.0},
        calibration_store=EdgeCalibrationStore(tmp_path / "c.json"),
    )
    assert result.quarantined == []
    assert any(d.strategy_id == "x" for d in result.decisions)
    assert result.calibrations["x"].lcb_factor == 0.0


def test_reconcile_skips_store_write_when_none() -> None:
    records = [_tr("x", 5.0, 0.1) for _ in range(40)]
    result = reconcile_session(records, disclosed_edges={"x": 10.0})
    # No store -> no persistence, but calibrations are still returned.
    assert "x" in result.calibrations


class _FakeModule:
    def __init__(self, alpha_id: str, edge: float) -> None:
        self.manifest = type("M", (), {"alpha_id": alpha_id})()
        self.cost = type("C", (), {"edge_estimate_bps": edge})()


def test_disclosed_edges_from_registry_iterable() -> None:
    modules = [_FakeModule("a", 8.8), _FakeModule("b", 12.0)]
    edges = disclosed_edges_from_registry(modules)
    assert edges == {"a": 8.8, "b": 12.0}
