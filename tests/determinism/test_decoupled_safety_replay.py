"""Replay parity for the Stage-0 decoupled event stream (design rev 5).

Promoting a SIGNAL alpha to ``decouple_caps_only`` changes the *shape* of its
gate-close event stream, and this module locks that shape end-to-end:

SIGNAL→RISK stream migration
----------------------------
Today (non-promoted) a regime gate ON→OFF force-close rides one ``Signal`` FLAT
on the **SIGNAL** stream.  For a **promoted** (``decouple_gate_close``) alpha the
same gate close instead:

* **removes** the gate-close FLAT from the ``Signal`` stream (proven here: the
  decoupled engine emits 3 signals where the non-decoupled one emits 4), and
* **publishes** a typed ``SafetyStateChange`` on the SIGNAL layer's dedicated
  safety sequence stream carrying the *identical* Inv-13 provenance the FLAT
  carried, which a **RISK**-layer author converts into a flatten ``OrderRequest``
  at a new sequence — the :class:`~feelies.risk.exit_composer.ExitComposer` on the
  fail-closed error paths, and the
  :class:`~feelies.risk.deferral_cap.DeferralCapController` at the bounded-
  deferral ``min()`` deadline.

Two locked baselines are registered in ``parity_manifest`` for the two genuinely
new cross-layer streams the decoupling introduces:

* ``decoupled_safety_state_change`` — the engine's ``SafetyStateChange`` stream
  (real :class:`HorizonSignalEngine` + :class:`RegimeGate`, driven through a
  clean ON→OFF).
* ``decoupled_risk_flatten_order`` — the risk-layer flatten ``OrderRequest``
  stream (composer fail-closed EXIT + deferral MAX_HOLD EXIT), driven with
  synthetic ``SafetyStateChange`` / ``Trade`` inputs and a strategy-slice
  position store, mirroring ``test_hazard_exit_replay``.

The FLAT-migration itself (non-promoted WITH FLAT vs promoted WITHOUT) is pinned
by module-local Signal-stream hashes and a structural + provenance assertion so a
future change that silently re-couples the streams fails loudly.  Non-promoted
default alphas stay **bit-identical** — the dedicated ``_safety_seq`` never
perturbs the ``Signal`` stream's sequence allocation (Inv-5).

Every stream is hashed with integer-ns math, content-derived order IDs, and
lex-sorted iteration, so replays are reproducible under ``PYTHONHASHSEED=0``.
"""

from __future__ import annotations

import hashlib
from decimal import Decimal
from typing import Any, Mapping

from feelies.alpha.cost_arithmetic import CostArithmetic
from feelies.bus.event_bus import EventBus
from feelies.core.events import (
    HorizonFeatureSnapshot,
    OrderRequest,
    OrderType,
    SafetyStateChange,
    Side,
    Signal,
    SignalDirection,
    Trade,
    TrendMechanism,
)
from feelies.core.identifiers import SequenceGenerator
from feelies.forensics.gate_close_attribution import (
    from_gate_close_flat,
    reconstruct_from_safety_flatten,
)
from feelies.portfolio.strategy_position_store import StrategyPositionStore
from feelies.risk.deferral_cap import (
    DEFERRAL_REASON_MAX_HOLD,
    DeferralCapController,
    DeferralPolicy,
)
from feelies.risk.exit_composer import (
    EXIT_COMPOSER_REASON_SAFETY_FAIL_CLOSED,
    EXIT_COMPOSER_SOURCE_LAYER,
    ExitComposer,
    ExitComposerPolicy,
)
from feelies.signals.horizon_engine import HorizonSignalEngine, RegisteredSignal
from feelies.signals.regime_gate import RegimeGate
from tests.determinism.test_signal_replay import _hash_signal_stream

# ── Shared fixture constants ─────────────────────────────────────────────
_ALPHA_ID = "sig_decouple_probe_v1"
_SYMBOL = "AAPL"
_SECOND_SYMBOL = "MSFT"
_HORIZON_S = 300
_BASE_TS = 1_700_000_000_000_000_000
_NS_PER_SECOND = 1_000_000_000

# Same latch drive as test_signal_fires_replay: +2 OFF→ON, +1 stays ON,
# -2 ON→OFF (gate close), +3 OFF→ON.  Non-decoupled → 4 signals
# (LONG, LONG, FLAT, LONG); decoupled → 3 (LONG, LONG, LONG) + 1 SafetyStateChange.
_OFI_BY_BOUNDARY: tuple[float, ...] = (2.0, 1.0, -2.0, 3.0)

# Deferral-cap timing for the RISK-flatten replay (seconds from _BASE_TS).
_OPENED_OFFSET_S = 0
_SAFE_OFF_OFFSET_S = 10
_MAX_HOLD_S = 60  # → MAX_HOLD deadline at +70s
_HARD_AGE_S = 3600  # → HARD_AGE deadline at +3600s (never the min here)
_TRADE_BEFORE_S = 40  # < +70s → no exit
_TRADE_AFTER_S = 100  # ≥ +70s → MAX_HOLD exit
_UNIVERSE: tuple[str, ...] = (_SECOND_SYMBOL, _SYMBOL)


# ── Real-engine driver (SafetyStateChange + Signal migration) ────────────


class _ProbeSignal:
    """Minimal real HorizonSignal: LONG when ofi_ewma is positive."""

    signal_id = "probe_ofi"
    signal_version = "1.0.0"

    def evaluate(
        self,
        snapshot: HorizonFeatureSnapshot,
        regime: Any,
        params: Mapping[str, Any],
    ) -> Signal | None:
        v = float(snapshot.values.get("ofi_ewma", 0.0))
        if v <= 0.0:
            return None
        return Signal(
            timestamp_ns=0,
            correlation_id="",
            sequence=0,
            symbol=snapshot.symbol,
            strategy_id="",
            direction=SignalDirection.LONG,
            strength=round(abs(v) * 0.1, 6),
            edge_estimate_bps=8.0,
        )


def _cost_arithmetic() -> CostArithmetic:
    # cost_total_bps = 2+1+1 = 4.0; margin_ratio = 2.5 (permissive constructor).
    return CostArithmetic(
        edge_estimate_bps=10.0,
        half_spread_bps=2.0,
        impact_bps=1.0,
        fee_bps=1.0,
        margin_ratio=2.5,
    )


def _build_engine(*, decouple: bool) -> tuple[EventBus, list[Signal], list[SafetyStateChange]]:
    bus = EventBus()
    signals: list[Signal] = []
    safety: list[SafetyStateChange] = []
    bus.subscribe(Signal, signals.append)  # type: ignore[arg-type]
    bus.subscribe(SafetyStateChange, safety.append)  # type: ignore[arg-type]

    gate = RegimeGate(
        alpha_id=_ALPHA_ID,
        on_condition="ofi_ewma > 0.0",
        off_condition="ofi_ewma < 0.0",
        engine_name=None,
    )
    engine = HorizonSignalEngine(bus=bus, signal_sequence_generator=SequenceGenerator())
    engine.register(
        RegisteredSignal(
            alpha_id=_ALPHA_ID,
            horizon_seconds=_HORIZON_S,
            signal=_ProbeSignal(),
            params={},
            gate=gate,
            cost_arithmetic=_cost_arithmetic(),
            trend_mechanism=TrendMechanism.KYLE_INFO,
            expected_half_life_seconds=600,
            consumed_features=("ofi_ewma",),
            decouple_gate_close=decouple,
        )
    )
    engine.attach()
    return bus, signals, safety


def _snapshot(boundary_index: int, ofi: float) -> HorizonFeatureSnapshot:
    return HorizonFeatureSnapshot(
        timestamp_ns=_BASE_TS + boundary_index * _HORIZON_S * _NS_PER_SECOND,
        correlation_id=f"snap:{_SYMBOL}:{boundary_index}",
        sequence=boundary_index,
        symbol=_SYMBOL,
        horizon_seconds=_HORIZON_S,
        boundary_index=boundary_index,
        values={"ofi_ewma": ofi},
        warm={"ofi_ewma": True},
        stale={"ofi_ewma": False},
    )


def _drive_engine(*, decouple: bool) -> tuple[list[Signal], list[SafetyStateChange]]:
    bus, signals, safety = _build_engine(decouple=decouple)
    for k, ofi in enumerate(_OFI_BY_BOUNDARY, start=1):
        bus.publish(_snapshot(k, ofi))
    return signals, safety


def _hash_safety_stream(events: list[SafetyStateChange]) -> str:
    """Canonicalize a ``SafetyStateChange`` stream, pinning Inv-13 provenance."""
    lines: list[str] = []
    for e in events:
        lines.append(
            f"{e.sequence}|{e.symbol}|{e.strategy_id}|safe={e.safe}|{e.reason}|"
            f"{e.regime_gate_state}|"
            f"CF={','.join(e.consumed_features)}|"
            f"TM={e.trend_mechanism.name if e.trend_mechanism else '-'}|"
            f"HL={e.expected_half_life_seconds}|"
            f"CT={e.disclosed_cost_total_bps:.6f}|"
            f"MR={e.disclosed_margin_ratio:.6f}|"
            f"{e.timestamp_ns}|{e.correlation_id}|src={e.source_layer}"
        )
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def _replay_safety_state_change() -> tuple[str, int]:
    """Engine-driven ``SafetyStateChange`` stream for the promoted probe alpha."""
    _signals, safety = _drive_engine(decouple=True)
    return _hash_safety_stream(safety), len(safety)


# ── Risk-layer flatten driver (composer + deferral cap) ──────────────────


def _make_safety(*, symbol: str, reason: str, ts_offset_s: int) -> SafetyStateChange:
    """A synthetic gate-close ``SafetyStateChange`` carrying full provenance."""
    return SafetyStateChange(
        timestamp_ns=_BASE_TS + ts_offset_s * _NS_PER_SECOND,
        correlation_id=f"safety:{symbol}:{reason}:{ts_offset_s}",
        sequence=0,
        source_layer="SIGNAL",
        symbol=symbol,
        strategy_id=_ALPHA_ID,
        safe=False,
        reason=reason,  # type: ignore[arg-type]
        trend_mechanism=TrendMechanism.KYLE_INFO,
        regime_gate_state="OFF",
        consumed_features=("ofi_ewma",),
        expected_half_life_seconds=600,
        disclosed_cost_total_bps=4.0,
        disclosed_margin_ratio=2.5,
    )


def _make_trade(*, symbol: str, ts_offset_s: int, seq: int) -> Trade:
    return Trade(
        timestamp_ns=_BASE_TS + ts_offset_s * _NS_PER_SECOND,
        sequence=seq,
        correlation_id=f"trade:{symbol}:{seq}",
        source_layer="MARKET",
        symbol=symbol,
        price=Decimal("150.00"),
        size=10,
        exchange_timestamp_ns=_BASE_TS + ts_offset_s * _NS_PER_SECOND,
    )


def _seed_open_book(store: StrategyPositionStore) -> None:
    """Open one long slice per universe symbol for the decoupled strategy."""
    for symbol in sorted(_UNIVERSE):
        store.update(
            _ALPHA_ID,
            symbol,
            quantity_delta=100,
            fill_price=Decimal("150.00"),
            timestamp_ns=_BASE_TS + _OPENED_OFFSET_S * _NS_PER_SECOND,
        )


def _build_risk_authors(
    store: StrategyPositionStore,
    bus: EventBus,
) -> None:
    composer = ExitComposer(
        bus=bus,
        sequence_generator=SequenceGenerator(),
        position_store=store,
        policies={
            _ALPHA_ID: ExitComposerPolicy(
                strategy_id=_ALPHA_ID,
                universe=_UNIVERSE,
                story_configured=False,
            )
        },
    )
    deferral = DeferralCapController(
        bus=bus,
        sequence_generator=SequenceGenerator(),
        position_store=store,
        policies={
            _ALPHA_ID: DeferralPolicy(
                strategy_id=_ALPHA_ID,
                max_hold_after_safe_off_seconds=_MAX_HOLD_S,
                hard_exit_age_seconds=_HARD_AGE_S,
                universe=_UNIVERSE,
            )
        },
        # Disabled so the deterministic exit is the MAX_HOLD ceiling, not a
        # session-clock-anchored backstop (session flatten is exercised in the
        # dedicated deferral-cap tests / the Phase-6 economic check).
        session_flatten_enabled=False,
    )
    composer.attach()
    deferral.attach()


def _replay_risk_flatten() -> tuple[str, int]:
    """Composer + deferral flatten ``OrderRequest`` stream from one decoupled log.

    Clean transition on ``_SYMBOL`` → composer HOLDs, deferral anchors the clock
    and fires ``MAX_HOLD_AFTER_SAFE_OFF`` on the first trade past the deadline.
    A fail-closed ``gate_error`` on ``_SECOND_SYMBOL`` → composer emits an
    immediate ``SAFETY_FAIL_CLOSED`` exit.  One log, both authors, both streams.
    """
    bus = EventBus()
    captured: list[OrderRequest] = []
    bus.subscribe(OrderRequest, captured.append)  # type: ignore[arg-type]

    store = StrategyPositionStore()
    _seed_open_book(store)
    _build_risk_authors(store, bus)

    # 1. Clean gate close on _SYMBOL → composer HOLD; deferral anchors first-off.
    bus.publish(
        _make_safety(symbol=_SYMBOL, reason="clean_transition", ts_offset_s=_SAFE_OFF_OFFSET_S)
    )
    # 2. Fail-closed gate error on _SECOND_SYMBOL → composer SAFETY_FAIL_CLOSED.
    bus.publish(
        _make_safety(symbol=_SECOND_SYMBOL, reason="gate_error", ts_offset_s=_SAFE_OFF_OFFSET_S)
    )
    # 3. Trade before the deferral deadline → no exit yet.
    bus.publish(_make_trade(symbol=_SYMBOL, ts_offset_s=_TRADE_BEFORE_S, seq=1))
    # 4. Trade at/after the deadline → deferral MAX_HOLD_AFTER_SAFE_OFF exit.
    bus.publish(_make_trade(symbol=_SYMBOL, ts_offset_s=_TRADE_AFTER_S, seq=2))

    return _hash_order_stream(captured), len(captured)


def _hash_order_stream(orders: list[OrderRequest]) -> str:
    lines: list[str] = []
    for o in orders:
        lines.append(
            f"{o.sequence}|{o.timestamp_ns}|{o.order_id}|{o.symbol}|"
            f"{o.side.name}|{o.order_type.name}|{o.quantity}|"
            f"{o.strategy_id}|{o.reason}|{o.correlation_id}|"
            f"src={o.source_layer}"
        )
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


# ── Locked baselines ─────────────────────────────────────────────────────
# Registered in tests/determinism/parity_manifest.py.  Re-baseline only with an
# intentional change to the decoupled event-stream shape, justified in the commit
# message and reflected in EXPECTED_MANIFEST_FINGERPRINT.
EXPECTED_DECOUPLED_SAFETY_STATE_CHANGE_HASH = (
    "a18589d8e966170bedceb2e0156b49d440441eb5999d537605eb2d7c13749a32"
)
EXPECTED_DECOUPLED_SAFETY_STATE_CHANGE_COUNT = 1

EXPECTED_DECOUPLED_RISK_FLATTEN_ORDER_HASH = (
    "87445b362a294c75abc6c63f2318e99c2d3da359501222b5b281efba4a62ac14"
)
EXPECTED_DECOUPLED_RISK_FLATTEN_ORDER_COUNT = 2

# Module-local Signal-stream migration goldens (underscore-prefixed so the
# manifest-completeness scanner treats them as assertions, not cross-layer parity
# baselines).  Non-promoted retains the gate-close FLAT (4 signals); promoted
# migrates it off the Signal stream (3 signals).
_NON_PROMOTED_SIGNAL_HASH = "3fcbe3b815ac84d3e0dc333a7feb4eff69079bf06a9dab45f57f7ebb933477c7"
_NON_PROMOTED_SIGNAL_COUNT = 4
_PROMOTED_SIGNAL_HASH = "c8e3d0036cf652eed763e6524b90290a94564671eb08d064c17c0738be921a5e"
_PROMOTED_SIGNAL_COUNT = 3


# ── SafetyStateChange stream ─────────────────────────────────────────────


def test_safety_state_change_stream_matches_locked_baseline() -> None:
    actual_hash, actual_count = _replay_safety_state_change()
    assert actual_count == EXPECTED_DECOUPLED_SAFETY_STATE_CHANGE_COUNT, (
        f"SafetyStateChange count drift: expected "
        f"{EXPECTED_DECOUPLED_SAFETY_STATE_CHANGE_COUNT}, got {actual_count}"
    )
    assert actual_hash == EXPECTED_DECOUPLED_SAFETY_STATE_CHANGE_HASH, (
        "Decoupled SafetyStateChange hash drift!\n"
        f"  Expected: {EXPECTED_DECOUPLED_SAFETY_STATE_CHANGE_HASH}\n"
        f"  Actual:   {actual_hash}\n"
        "If intentional, update the constant + EXPECTED_MANIFEST_FINGERPRINT in "
        "the same commit and justify in the message."
    )


def test_two_replays_produce_identical_safety_hash() -> None:
    hash_a, count_a = _replay_safety_state_change()
    hash_b, count_b = _replay_safety_state_change()
    assert count_a == count_b
    assert hash_a == hash_b, (
        f"SafetyStateChange hash drift across identical replays!\n  a: {hash_a}\n  b: {hash_b}"
    )


# ── RISK-layer flatten OrderRequest stream ───────────────────────────────


def test_risk_flatten_stream_matches_locked_baseline() -> None:
    actual_hash, actual_count = _replay_risk_flatten()
    assert actual_count == EXPECTED_DECOUPLED_RISK_FLATTEN_ORDER_COUNT, (
        f"risk-flatten order count drift: expected "
        f"{EXPECTED_DECOUPLED_RISK_FLATTEN_ORDER_COUNT}, got {actual_count}"
    )
    assert actual_hash == EXPECTED_DECOUPLED_RISK_FLATTEN_ORDER_HASH, (
        "Decoupled RISK-flatten OrderRequest hash drift!\n"
        f"  Expected: {EXPECTED_DECOUPLED_RISK_FLATTEN_ORDER_HASH}\n"
        f"  Actual:   {actual_hash}\n"
        "If intentional, update the constant + EXPECTED_MANIFEST_FINGERPRINT in "
        "the same commit and justify in the message."
    )


def test_two_replays_produce_identical_risk_flatten_hash() -> None:
    hash_a, count_a = _replay_risk_flatten()
    hash_b, count_b = _replay_risk_flatten()
    assert count_a == count_b
    assert hash_a == hash_b, (
        f"RISK-flatten hash drift across identical replays!\n  a: {hash_a}\n  b: {hash_b}"
    )


def test_risk_flatten_stream_reasons_and_authors() -> None:
    """Sanity guard: composer SAFETY_FAIL_CLOSED + deferral MAX_HOLD, slice-scoped."""
    bus = EventBus()
    captured: list[OrderRequest] = []
    bus.subscribe(OrderRequest, captured.append)  # type: ignore[arg-type]
    store = StrategyPositionStore()
    _seed_open_book(store)
    _build_risk_authors(store, bus)

    bus.publish(
        _make_safety(symbol=_SYMBOL, reason="clean_transition", ts_offset_s=_SAFE_OFF_OFFSET_S)
    )
    bus.publish(
        _make_safety(symbol=_SECOND_SYMBOL, reason="gate_error", ts_offset_s=_SAFE_OFF_OFFSET_S)
    )
    bus.publish(_make_trade(symbol=_SYMBOL, ts_offset_s=_TRADE_BEFORE_S, seq=1))
    bus.publish(_make_trade(symbol=_SYMBOL, ts_offset_s=_TRADE_AFTER_S, seq=2))

    assert [(o.symbol, o.reason) for o in captured] == [
        (_SECOND_SYMBOL, EXIT_COMPOSER_REASON_SAFETY_FAIL_CLOSED),
        (_SYMBOL, DEFERRAL_REASON_MAX_HOLD),
    ]
    # Every mandated exit is a raw RISK-layer flatten (non-vetoable routing).
    assert all(o.source_layer == "RISK" and o.strategy_id == _ALPHA_ID for o in captured)


# ── SIGNAL→RISK FLAT migration + non-promoted bit-identical ──────────────


def test_non_promoted_signal_stream_bit_identical() -> None:
    """A non-decoupled alpha keeps today's gate-close FLAT on the Signal stream.

    The dedicated ``_safety_seq`` must not perturb Signal sequence allocation
    (Inv-5): the emitted Signal sequences are contiguous 0..3, and the FLAT
    carries full entry provenance exactly as before decoupling existed.
    """
    signals, safety = _drive_engine(decouple=False)
    assert len(signals) == _NON_PROMOTED_SIGNAL_COUNT
    dispositions = [(s.direction.name, s.regime_gate_state) for s in signals]
    assert ("LONG", "ON") in dispositions
    assert ("FLAT", "OFF") in dispositions, "non-promoted alpha must still FLAT on gate close"
    # Contiguous, gap-free Signal sequence allocation — the safety seq is isolated.
    assert [s.sequence for s in signals] == [0, 1, 2, 3]
    # The gate-close FLAT still carries the full Inv-13 provenance.
    flat = next(s for s in signals if s.direction is SignalDirection.FLAT)
    assert flat.trend_mechanism is TrendMechanism.KYLE_INFO
    assert flat.consumed_features == ("ofi_ewma",)
    assert flat.expected_half_life_seconds == 600
    assert flat.disclosed_cost_total_bps == 4.0
    assert flat.disclosed_margin_ratio == 2.5
    # The event stream is byte-identical to the locked golden.
    assert _hash_signal_stream(signals) == _NON_PROMOTED_SIGNAL_HASH
    # A SafetyStateChange is still emitted (harmless without a subscriber) so a
    # later promotion needs no new SIGNAL-layer wiring.
    assert len(safety) == 1 and safety[0].reason == "clean_transition"


def test_promotion_migrates_flat_from_signal_to_safety_stream() -> None:
    """Promotion removes the gate-close FLAT from the Signal stream and replaces
    it with a provenance-identical ``SafetyStateChange`` (§3.1, Inv-13)."""
    nd_signals, nd_safety = _drive_engine(decouple=False)
    p_signals, p_safety = _drive_engine(decouple=True)

    # Promoted stream drops exactly the gate-close FLAT.
    assert len(p_signals) == _PROMOTED_SIGNAL_COUNT == len(nd_signals) - 1
    assert not any(s.direction is SignalDirection.FLAT for s in p_signals), (
        "promoted alpha must NOT emit a gate-close FLAT on the Signal stream"
    )
    assert _hash_signal_stream(p_signals) == _PROMOTED_SIGNAL_HASH
    # The migration is provenance-preserving: the promoted SafetyStateChange
    # reconstructs the *identical* attribution the non-promoted FLAT carried.
    assert len(p_safety) == 1 == len(nd_safety)
    nd_flat = next(s for s in nd_signals if s.direction is SignalDirection.FLAT)
    legacy_attr = from_gate_close_flat(nd_flat)
    # A composer flatten joined to the promoted SafetyStateChange (same slice +
    # correlation_id) rebuilds the attribution the FLAT used to carry.
    safety_evt = p_safety[0]
    composer_order = OrderRequest(
        timestamp_ns=safety_evt.timestamp_ns,
        correlation_id=safety_evt.correlation_id,
        sequence=0,
        source_layer=EXIT_COMPOSER_SOURCE_LAYER,
        order_id="probe",
        symbol=safety_evt.symbol,
        side=Side.SELL,
        order_type=OrderType.MARKET,
        quantity=100,
        strategy_id=safety_evt.strategy_id,
        reason=EXIT_COMPOSER_REASON_SAFETY_FAIL_CLOSED,
    )
    migrated_attr = reconstruct_from_safety_flatten(composer_order, safety_evt)
    assert migrated_attr.provenance_key == legacy_attr.provenance_key, (
        "SIGNAL→RISK migration must preserve Inv-13 gate-close provenance"
    )
    # Actuation lineage legitimately differs (that IS what promotion changes).
    assert legacy_attr.actuation == "SIGNAL_FLAT"
    assert migrated_attr.actuation == "RISK_FLATTEN"
