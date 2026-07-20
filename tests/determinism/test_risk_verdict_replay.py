"""Pin the risk engine's verdict stream directly.

An evolving position store exercises every ``RiskAction``:

1.  **ALLOW** — flat book, well within every limit.
2.  **SCALE_DOWN** — a seeded $17,000 position lands gross exposure inside the
    ``scale_down_threshold_pct`` band (80-100% of the $20,000 cap).
3.  **REJECT** — a second seeded position pushes gross exposure past the cap
    outright.
4.  **FORCE_FLATTEN** — crashing the first position's mark breaches the
    drawdown guard against the high-water-mark set in step 1.

Each step targets a different symbol so per-symbol position checks do not
interfere with the exposure and drawdown cascade.
"""

from __future__ import annotations

import hashlib
from decimal import Decimal

from feelies.core.events import RiskVerdict, Signal, SignalDirection
from feelies.portfolio.memory_position_store import MemoryPositionStore
from feelies.risk.basic_risk import BasicRiskEngine, RiskConfig

_BASE_TS = 1_000_000_000


def _signal(sequence: int, symbol: str) -> Signal:
    return Signal(
        timestamp_ns=_BASE_TS * sequence,
        correlation_id=f"c{sequence}",
        sequence=sequence,
        symbol=symbol,
        strategy_id="probe",
        direction=SignalDirection.LONG,
        strength=1.0,
        edge_estimate_bps=10.0,
    )


def _replay() -> tuple[str, int]:
    risk = BasicRiskEngine(
        RiskConfig(
            max_position_per_symbol=1000,
            max_gross_exposure_pct=20.0,
            max_drawdown_pct=5.0,
            account_equity=Decimal("100000"),
            scale_down_threshold_pct=0.8,
        )
    )
    store = MemoryPositionStore()
    verdicts: list[RiskVerdict] = []

    # 1. ALLOW: flat book, no exposure.
    verdicts.append(risk.check_signal(_signal(1, "AAPL"), store))

    # 2. SCALE_DOWN: seed $17,000 exposure (80-100% of the $20,000 cap).
    store.update(
        symbol="AAPL",
        quantity_delta=100,
        fill_price=Decimal("170.00"),
        timestamp_ns=2 * _BASE_TS,
    )
    store.update_mark("AAPL", Decimal("170.00"), bid=Decimal("169.99"), ask=Decimal("170.01"))
    verdicts.append(risk.check_signal(_signal(2, "MSFT"), store))

    # 3. REJECT: a second position pushes gross exposure past the cap.
    store.update(
        symbol="MSFT",
        quantity_delta=50,
        fill_price=Decimal("200.00"),
        timestamp_ns=3 * _BASE_TS,
    )
    store.update_mark("MSFT", Decimal("200.00"), bid=Decimal("199.99"), ask=Decimal("200.01"))
    verdicts.append(risk.check_signal(_signal(3, "GOOG"), store))

    # 4. FORCE_FLATTEN: crashing AAPL's mark breaches the drawdown guard
    # against the high-water-mark recorded at step 1.
    store.update_mark("AAPL", Decimal("0.01"), bid=Decimal("0.01"), ask=Decimal("0.01"))
    verdicts.append(risk.check_signal(_signal(4, "NVDA"), store))

    return _hash_verdict_stream(verdicts), len(verdicts)


def _hash_verdict_stream(verdicts: list[RiskVerdict]) -> str:
    lines = [
        f"{v.sequence}|{v.symbol}|{v.action.name}|{v.reason}|{v.scaling_factor:.6f}|"
        f"{v.timestamp_ns}|{v.correlation_id}"
        for v in verdicts
    ]
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def test_two_replays_produce_identical_verdict_hash() -> None:
    hash_a, count_a = _replay()
    hash_b, count_b = _replay()
    assert count_a == count_b
    assert hash_a == hash_b


# Locked baseline.  Re-baseline only with an intentional change to
# BasicRiskEngine's action-selection cascade, justified in the commit.
EXPECTED_RISK_VERDICT_HASH = "b388a2c57da691c45eb8f3c3d041e74831390d29214e0f39d6881ae21e0cae7b"
EXPECTED_RISK_VERDICT_COUNT = 4


def test_risk_verdict_stream_matches_locked_baseline() -> None:
    actual_hash, actual_count = _replay()
    assert actual_count == EXPECTED_RISK_VERDICT_COUNT, (
        f"RiskVerdict count drift: expected {EXPECTED_RISK_VERDICT_COUNT}, got {actual_count}"
    )
    assert actual_hash == EXPECTED_RISK_VERDICT_HASH, (
        "RiskVerdict hash drift!\n"
        f"  Expected: {EXPECTED_RISK_VERDICT_HASH}\n"
        f"  Actual:   {actual_hash}\n"
        "If intentional (risk-cascade change), update the constant in the "
        "same commit and justify in the commit message."
    )


def test_scenario_exercises_all_four_risk_actions() -> None:
    """Guard against a vacuous baseline: all four RiskAction members must
    actually appear, each for a distinct reason."""
    from feelies.core.events import RiskAction

    risk = BasicRiskEngine(
        RiskConfig(
            max_position_per_symbol=1000,
            max_gross_exposure_pct=20.0,
            max_drawdown_pct=5.0,
            account_equity=Decimal("100000"),
            scale_down_threshold_pct=0.8,
        )
    )
    store = MemoryPositionStore()
    verdicts: list[RiskVerdict] = []
    verdicts.append(risk.check_signal(_signal(1, "AAPL"), store))
    store.update(symbol="AAPL", quantity_delta=100, fill_price=Decimal("170.00"))
    store.update_mark("AAPL", Decimal("170.00"), bid=Decimal("169.99"), ask=Decimal("170.01"))
    verdicts.append(risk.check_signal(_signal(2, "MSFT"), store))
    store.update(symbol="MSFT", quantity_delta=50, fill_price=Decimal("200.00"))
    store.update_mark("MSFT", Decimal("200.00"), bid=Decimal("199.99"), ask=Decimal("200.01"))
    verdicts.append(risk.check_signal(_signal(3, "GOOG"), store))
    store.update_mark("AAPL", Decimal("0.01"), bid=Decimal("0.01"), ask=Decimal("0.01"))
    verdicts.append(risk.check_signal(_signal(4, "NVDA"), store))

    actions = [v.action for v in verdicts]
    assert actions == [
        RiskAction.ALLOW,
        RiskAction.SCALE_DOWN,
        RiskAction.REJECT,
        RiskAction.FORCE_FLATTEN,
    ], f"scenario did not exercise all four actions in order: {actions}"
