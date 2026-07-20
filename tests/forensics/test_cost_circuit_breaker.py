"""Unit + integration tests for the cost circuit-breaker (automate layer)."""

from __future__ import annotations

import logging
from decimal import Decimal

from feelies.alpha.lifecycle import (
    AlphaLifecycle,
    AlphaLifecycleState,
    GateRequirements,
    PromotionEvidence,
)
from feelies.alpha.promotion_evidence import (
    QuarantineTriggerEvidence,
    metadata_to_evidence,
)
from feelies.alpha.promotion_ledger import PromotionLedger
from feelies.core.clock import SimulatedClock
from feelies.core.events import Side
from feelies.forensics.cost_circuit_breaker import (
    ACTION_INSUFFICIENT,
    ACTION_OK,
    ACTION_QUARANTINE,
    ACTION_WATCH,
    CircuitBreakerDecision,
    CircuitBreakerPolicy,
    apply_cost_circuit_breaker,
    evaluate_cost_circuit_breaker,
)
from feelies.storage.trade_journal import TradeRecord

_SEQ = 0


def _tr(
    strategy_id: str,
    realized_pnl: float,
    fees: float,
    *,
    cost_bps: float = 2.0,
    qty: int = 50,
    price: float = 100.0,
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
        cost_bps=Decimal(str(cost_bps)),
        fees=Decimal(str(fees)),
        realized_pnl=Decimal(str(realized_pnl)),
        correlation_id=f"c{_SEQ}",
    )


def _by_id(records: list[TradeRecord]) -> dict[str, CircuitBreakerDecision]:
    return {d.strategy_id: d for d in evaluate_cost_circuit_breaker(records)}


# ── evaluate (pure) ─────────────────────────────────────────────────────


def test_persistent_bleed_quarantines() -> None:
    fills = [_tr("bleeder", 0.0, 1.0) for _ in range(40)]  # net negative, 40 fills
    d = _by_id(fills)["bleeder"]
    assert d.action == ACTION_QUARANTINE
    assert "no edge" in d.reason or "<= 0" in d.reason


def test_thin_window_is_insufficient_not_quarantine() -> None:
    # The exact APP 2026-03-26 shape: every alpha has < 30 fills, so the
    # breaker must abstain rather than demote on one thin day.
    fills = (
        [_tr("sig_inventory_revert_v1", 49.0, 4.3) for _ in range(3)]
        + [_tr("sig_benign_midcap_v1", 4.4, 6.3) for _ in range(9)]
        + [_tr("sig_kyle_drift_v1", 0.0, 5.8) for _ in range(6)]
    )
    decisions = _by_id(fills)
    assert all(d.action == ACTION_INSUFFICIENT for d in decisions.values())


def test_strong_survivor_is_ok() -> None:
    # edge ~10 bps vs cost 2 bps (margin 5), 40 fills, net positive.
    fills = [_tr("good", 5.0, 0.5, cost_bps=2.0) for _ in range(40)]
    assert _by_id(fills)["good"].action == ACTION_OK


def test_profitable_but_fragile_is_watch() -> None:
    # edge ~2.5 bps vs cost 2 bps (margin 1.25: covers cost, under 1.5x), net +.
    fills = [_tr("thin", 1.25, 0.1, cost_bps=2.0) for _ in range(40)]
    assert _by_id(fills)["thin"].action == ACTION_WATCH


def test_does_not_cover_cost_quarantines_even_if_net_positive() -> None:
    # Net positive (fees tiny) but realized edge 0.5 bps < cost 2 bps.
    fills = [_tr("undercover", 0.25, 0.01, cost_bps=2.0) for _ in range(40)]
    d = _by_id(fills)["undercover"]
    assert d.action == ACTION_QUARANTINE
    assert "does not cover cost" in d.reason


def test_policy_min_fills_is_respected() -> None:
    fills = [_tr("bleeder", 0.0, 1.0) for _ in range(25)]
    pol = CircuitBreakerPolicy(min_fills=50)
    d = {x.strategy_id: x for x in evaluate_cost_circuit_breaker(fills, policy=pol)}["bleeder"]
    assert d.action == ACTION_INSUFFICIENT


# ── apply (drives the real lifecycle) ───────────────────────────────────


def _live_lifecycle(
    alpha_id: str,
    clock: SimulatedClock,
    ledger: PromotionLedger | None = None,
) -> AlphaLifecycle:
    lc = AlphaLifecycle(
        alpha_id=alpha_id,
        clock=clock,
        gate_requirements=GateRequirements(paper_min_days=1),
        ledger=ledger,
    )
    lc.promote_to_paper(
        PromotionEvidence(
            schema_valid=True,
            determinism_test_passed=True,
            feature_values_finite=True,
        )
    )
    lc.promote_to_live(
        PromotionEvidence(
            paper_days=10,
            paper_sharpe=1.0,
            paper_hit_rate=0.55,
            cost_model_validated=True,
        )
    )
    assert lc.is_live is True
    return lc


def test_apply_quarantines_live_alpha_and_records_ledger(tmp_path) -> None:
    clock = SimulatedClock(start_ns=0)
    ledger = PromotionLedger(tmp_path / "ledger.jsonl")
    lc = _live_lifecycle("bleeder", clock, ledger)

    decision = CircuitBreakerDecision(
        strategy_id="bleeder",
        action=ACTION_QUARANTINE,
        reason="net -50.00 <= 0 over 40 fills (paying fees for no edge)",
        n_fills=40,
        net=-50.0,
        mean_edge_bps=0.0,
        mean_cost_bps=2.0,
        realized_margin_ratio=0.0,
        decay_z=None,
    )
    applied = apply_cost_circuit_breaker([decision], {"bleeder": lc}, correlation_id="cb1")

    assert [d.strategy_id for d in applied] == ["bleeder"]
    assert lc.state == AlphaLifecycleState.QUARANTINED
    entry = ledger.latest_for("bleeder")
    assert entry is not None
    assert "cost-circuit-breaker" in entry.metadata.get("reason", "")


def test_apply_skips_non_live_alpha() -> None:
    clock = SimulatedClock(start_ns=0)
    # RESEARCH lifecycle — cannot be quarantined.
    lc = AlphaLifecycle(alpha_id="research_only", clock=clock)
    assert lc.is_live is False

    decision = CircuitBreakerDecision(
        strategy_id="research_only",
        action=ACTION_QUARANTINE,
        reason="net -10 <= 0",
        n_fills=40,
        net=-10.0,
        mean_edge_bps=0.0,
        mean_cost_bps=2.0,
        realized_margin_ratio=0.0,
        decay_z=None,
    )
    applied = apply_cost_circuit_breaker([decision], {"research_only": lc})
    assert applied == []
    assert lc.state == AlphaLifecycleState.RESEARCH


def test_apply_ignores_non_quarantine_decisions() -> None:
    clock = SimulatedClock(start_ns=0)
    lc = _live_lifecycle("good", clock)

    ok = CircuitBreakerDecision(
        strategy_id="good",
        action=ACTION_OK,
        reason="net +100, margin 5.00",
        n_fills=40,
        net=100.0,
        mean_edge_bps=10.0,
        mean_cost_bps=2.0,
        realized_margin_ratio=5.0,
        decay_z=None,
    )
    applied = apply_cost_circuit_breaker([ok], {"good": lc})
    assert applied == []
    assert lc.state == AlphaLifecycleState.LIVE


def test_apply_records_structured_quarantine_evidence(tmp_path) -> None:
    """The auto-trigger records ``QuarantineTriggerEvidence`` on the
    ledger (Inv-13), round-trippable, not only a free-text reason."""
    clock = SimulatedClock(start_ns=0)
    ledger = PromotionLedger(tmp_path / "ledger.jsonl")
    lc = _live_lifecycle("bleeder", clock, ledger)

    decision = CircuitBreakerDecision(
        strategy_id="bleeder",
        action=ACTION_QUARANTINE,
        reason="net -50.00 <= 0 over 40 fills (paying fees for no edge)",
        n_fills=40,
        net=-50.0,
        mean_edge_bps=0.0,
        mean_cost_bps=2.0,
        realized_margin_ratio=0.0,
        decay_z=None,
    )
    apply_cost_circuit_breaker([decision], {"bleeder": lc}, correlation_id="cb1")

    entry = ledger.latest_for("bleeder")
    assert entry is not None
    assert "cost-circuit-breaker" in entry.metadata.get("reason", "")
    evs = metadata_to_evidence(entry.metadata)
    assert len(evs) == 1
    ev = evs[0]
    assert isinstance(ev, QuarantineTriggerEvidence)
    assert "net_negative_over_window" in ev.crowding_symptoms
    # A genuine cost bleed maps to compression 0.0 → crosses the documented
    # threshold, so it is NOT mislabelled spurious.
    assert ev.pnl_compression_ratio_5d == 0.0


def test_spurious_trigger_still_commits_and_warns(caplog) -> None:
    """A quarantine whose evidence trips no
    documented threshold still commits; the validator only logs a WARNING."""
    clock = SimulatedClock(start_ns=0)
    lc = _live_lifecycle("borderline", clock)

    spurious = QuarantineTriggerEvidence()  # all nominal → flagged spurious
    with caplog.at_level(logging.WARNING):
        lc.quarantine("manual demotion", structured_evidence=[spurious])

    assert lc.state == AlphaLifecycleState.QUARANTINED  # committed anyway
    assert any("suspicious" in r.getMessage().lower() for r in caplog.records)
