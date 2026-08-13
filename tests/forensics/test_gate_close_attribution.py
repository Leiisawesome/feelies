"""Gate-close forensic attribution survives the SIGNAL→RISK stream migration.

Design rev 5 §3.1.6 / Inv-13: when an alpha is promoted to ``decouple_caps_only``
the gate-close ``Signal`` FLAT disappears, but "forensics keyed on the
SIGNAL-layer FLAT migrates to the composer's reason code + this provenance."
These tests prove that concretely end to end:

1. The legacy FLAT and the decoupled ``SafetyStateChange`` yield the **identical**
   provenance key (:func:`from_gate_close_flat` vs
   :func:`reconstruct_from_safety_flatten`).
2. Both risk-layer authors reconstruct: the composer flatten (joined on
   ``correlation_id``) and the deferral-cap flatten (joined on the
   ``(strategy_id, symbol)`` episode, since it carries the trade's
   ``correlation_id`` instead).
3. Mis-joins fail loudly rather than fabricating attribution.
"""

from __future__ import annotations

import pytest

from feelies.core.events import (
    OrderRequest,
    OrderType,
    SafetyStateChange,
    Side,
    SignalDirection,
    TrendMechanism,
)
from feelies.forensics.gate_close_attribution import (
    GateCloseAttributionError,
    from_gate_close_flat,
    reconstruct_from_safety_flatten,
)
from feelies.risk.deferral_cap import DEFERRAL_REASON_MAX_HOLD, DEFERRAL_REASON_SESSION_FLATTEN
from feelies.risk.exit_composer import (
    EXIT_COMPOSER_REASON_DECOUPLING_REVOKED,
    EXIT_COMPOSER_REASON_SAFETY_FAIL_CLOSED,
    EXIT_COMPOSER_SOURCE_LAYER,
)
from tests.determinism.test_decoupled_safety_replay import _drive_engine

_ALPHA_ID = "sig_decouple_probe_v1"
_SYMBOL = "AAPL"


def _legacy_flat_attribution():
    """Drive the non-promoted engine and extract the gate-close FLAT attribution."""
    nd_signals, _ = _drive_engine(decouple=False)
    flat = next(s for s in nd_signals if s.direction is SignalDirection.FLAT)
    return from_gate_close_flat(flat), flat


def _promoted_safety_event() -> SafetyStateChange:
    """The promoted engine's SafetyStateChange for the same gate close."""
    _signals, safety = _drive_engine(decouple=True)
    assert len(safety) == 1
    return safety[0]


def _composer_order(safety: SafetyStateChange, *, reason: str) -> OrderRequest:
    """A composer flatten that copies the safety event's correlation_id."""
    return OrderRequest(
        timestamp_ns=safety.timestamp_ns,
        correlation_id=safety.correlation_id,
        sequence=0,
        source_layer=EXIT_COMPOSER_SOURCE_LAYER,
        order_id="probe-composer",
        symbol=safety.symbol,
        side=Side.SELL,
        order_type=OrderType.MARKET,
        quantity=100,
        strategy_id=safety.strategy_id,
        reason=reason,
    )


# ── Provenance identity across the migration ─────────────────────────────


def test_composer_flatten_reconstructs_legacy_flat_provenance() -> None:
    legacy, _flat = _legacy_flat_attribution()
    safety = _promoted_safety_event()
    order = _composer_order(safety, reason=EXIT_COMPOSER_REASON_SAFETY_FAIL_CLOSED)

    migrated = reconstruct_from_safety_flatten(order, safety)

    assert migrated.provenance_key == legacy.provenance_key
    # Every Inv-13 field is present and equal (not merely the tuple).
    assert migrated.trend_mechanism is legacy.trend_mechanism is TrendMechanism.KYLE_INFO
    assert migrated.regime_gate_state == legacy.regime_gate_state == "OFF"
    assert migrated.consumed_features == legacy.consumed_features == ("ofi_ewma",)
    assert migrated.expected_half_life_seconds == legacy.expected_half_life_seconds
    assert migrated.disclosed_cost_total_bps == legacy.disclosed_cost_total_bps
    assert migrated.disclosed_margin_ratio == legacy.disclosed_margin_ratio


def test_actuation_lineage_records_the_migration() -> None:
    legacy, _flat = _legacy_flat_attribution()
    safety = _promoted_safety_event()
    migrated = reconstruct_from_safety_flatten(
        _composer_order(safety, reason=EXIT_COMPOSER_REASON_SAFETY_FAIL_CLOSED),
        safety,
    )
    # The attribution is provenance-equal but the lineage records WHERE it moved.
    assert legacy.actuation == "SIGNAL_FLAT"
    assert legacy.source_layer == "SIGNAL"
    assert legacy.reason == ""  # the FLAT never carried a SafetyReason
    assert migrated.actuation == "RISK_FLATTEN"
    assert migrated.source_layer == "RISK"
    assert migrated.reason == "clean_transition"  # recovered from SafetyStateChange


def test_revocation_flatten_reconstructs_provenance() -> None:
    legacy, _flat = _legacy_flat_attribution()
    safety = _promoted_safety_event()
    order = _composer_order(safety, reason=EXIT_COMPOSER_REASON_DECOUPLING_REVOKED)
    migrated = reconstruct_from_safety_flatten(order, safety)
    assert migrated.provenance_key == legacy.provenance_key
    assert migrated.reason == "clean_transition"


def test_deferral_flatten_reconstructs_on_episode_join() -> None:
    """A deferral-cap flatten carries the *trade's* correlation_id, so it joins on
    the ``(strategy_id, symbol)`` episode, not correlation_id — yet still recovers
    the full provenance from the safety event."""
    legacy, _flat = _legacy_flat_attribution()
    safety = _promoted_safety_event()
    # Deferral flatten: correlation_id is the triggering trade's, NOT the safety's.
    deferral_order = OrderRequest(
        timestamp_ns=safety.timestamp_ns + 60_000_000_000,
        correlation_id="trade:AAPL:2",  # deliberately != safety.correlation_id
        sequence=0,
        source_layer="RISK",
        order_id="probe-deferral",
        symbol=safety.symbol,
        side=Side.SELL,
        order_type=OrderType.MARKET,
        quantity=100,
        strategy_id=safety.strategy_id,
        reason=DEFERRAL_REASON_MAX_HOLD,
    )
    migrated = reconstruct_from_safety_flatten(deferral_order, safety)
    assert migrated.provenance_key == legacy.provenance_key
    assert migrated.reason == "clean_transition"


# ── Join validation: mis-joins must fail loudly ──────────────────────────


def test_from_gate_close_flat_rejects_non_flat() -> None:
    nd_signals, _ = _drive_engine(decouple=False)
    entry = next(s for s in nd_signals if s.direction is SignalDirection.LONG)
    with pytest.raises(GateCloseAttributionError):
        from_gate_close_flat(entry)


def test_reconstruct_rejects_non_safety_order() -> None:
    safety = _promoted_safety_event()
    ordinary = _composer_order(safety, reason="PORTFOLIO")
    with pytest.raises(GateCloseAttributionError):
        reconstruct_from_safety_flatten(ordinary, safety)


def test_reconstruct_rejects_safe_true_event() -> None:
    safety = _promoted_safety_event()
    rearm = SafetyStateChange(
        timestamp_ns=safety.timestamp_ns,
        correlation_id=safety.correlation_id,
        sequence=1,
        source_layer="SIGNAL",
        symbol=safety.symbol,
        strategy_id=safety.strategy_id,
        safe=True,
        reason="clean_transition",
        regime_gate_state="ON",
    )
    with pytest.raises(GateCloseAttributionError):
        reconstruct_from_safety_flatten(
            _composer_order(rearm, reason=EXIT_COMPOSER_REASON_SAFETY_FAIL_CLOSED),
            rearm,
        )


def test_reconstruct_rejects_slice_mismatch() -> None:
    safety = _promoted_safety_event()
    other_symbol = _composer_order(safety, reason=EXIT_COMPOSER_REASON_SAFETY_FAIL_CLOSED)
    mismatched = OrderRequest(
        timestamp_ns=other_symbol.timestamp_ns,
        correlation_id=other_symbol.correlation_id,
        sequence=0,
        source_layer="RISK",
        order_id="x",
        symbol="MSFT",  # != safety.symbol
        side=Side.SELL,
        order_type=OrderType.MARKET,
        quantity=100,
        strategy_id=safety.strategy_id,
        reason=EXIT_COMPOSER_REASON_SAFETY_FAIL_CLOSED,
    )
    with pytest.raises(GateCloseAttributionError):
        reconstruct_from_safety_flatten(mismatched, safety)


def test_reconstruct_rejects_composer_correlation_mismatch() -> None:
    """A composer reason MUST share the safety event's correlation_id."""
    safety = _promoted_safety_event()
    wrong_corr = OrderRequest(
        timestamp_ns=safety.timestamp_ns,
        correlation_id="unrelated-correlation",
        sequence=0,
        source_layer="RISK",
        order_id="x",
        symbol=safety.symbol,
        side=Side.SELL,
        order_type=OrderType.MARKET,
        quantity=100,
        strategy_id=safety.strategy_id,
        reason=EXIT_COMPOSER_REASON_SAFETY_FAIL_CLOSED,
    )
    with pytest.raises(GateCloseAttributionError):
        reconstruct_from_safety_flatten(wrong_corr, safety)


def test_reconstruct_tolerates_deferral_correlation_mismatch() -> None:
    """A deferral reason (session flatten) is exempt from the correlation match."""
    safety = _promoted_safety_event()
    order = OrderRequest(
        timestamp_ns=safety.timestamp_ns,
        correlation_id="trade-derived-id",
        sequence=0,
        source_layer="RISK",
        order_id="x",
        symbol=safety.symbol,
        side=Side.SELL,
        order_type=OrderType.MARKET,
        quantity=100,
        strategy_id=safety.strategy_id,
        reason=DEFERRAL_REASON_SESSION_FLATTEN,
    )
    # Does not raise despite the correlation_id differing.
    migrated = reconstruct_from_safety_flatten(order, safety)
    assert migrated.reason == "clean_transition"
