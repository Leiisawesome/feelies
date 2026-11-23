"""Report-only diff of one tape run in two exit arms (D-249)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from decimal import Decimal

from feelies.core.events import (
    NBBOQuote,
    OrderAck,
    OrderAckStatus,
    OrderRequest,
    PositionClosed,
    PositionExtreme,
    PositionFillLeg,
    RiskAction,
    RiskVerdict,
    Side,
    Signal,
    SignalDirection,
)
from feelies.kernel.signal_order_trace import SignalOrderTraceRow


class AttributionError(Exception):
    """The two arms cannot be compared."""


@dataclass(frozen=True, slots=True)
class Fill:
    """One positive fill, projected from ``OrderAck``."""

    fill_price: Decimal
    filled_quantity: int
    timestamp_ns: int
    fees: Decimal
    sequence: int


@dataclass(frozen=True, slots=True)
class ArmEvents:
    """One arm's events for a single tape."""

    signals: Sequence[Signal]
    order_requests: Sequence[OrderRequest]
    order_acks: Sequence[OrderAck]
    risk_verdicts: Sequence[RiskVerdict]
    quotes: Sequence[NBBOQuote]
    position_closed: Sequence[PositionClosed] = field(default_factory=tuple)
    signal_order_traces: Sequence[SignalOrderTraceRow] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class ArmEpisode:
    """One flat-to-flat episode in one arm."""

    symbol: str
    strategy_id: str
    entry_signal: Signal
    side: str
    entry_fills: tuple[Fill, ...]
    exit_fills: tuple[Fill, ...]
    net_after_fees: Decimal
    holding_time_ns: int


@dataclass(frozen=True, slots=True)
class EpisodeDiff:
    """One matched episode. ``episode_class`` is the D-249 class."""

    episode_class: str
    engine_reason: str
    legacy_reason: str
    explanation: str
    legacy: ArmEpisode | None
    engine: ArmEpisode | None
    legacy_mae: Decimal | None
    engine_mae: Decimal | None
    engine_worst: PositionExtreme | None


@dataclass(frozen=True, slots=True)
class ClassTotals:
    """Count and per-arm net for one class."""

    episode_class: str
    count: int
    legacy_net: Decimal
    engine_net: Decimal


@dataclass(frozen=True, slots=True)
class AttributionReport:
    """Descriptive diff. ``diffs`` are ordered by symbol, strategy_id, entry signal."""

    diffs: tuple[EpisodeDiff, ...]
    totals: tuple[ClassTotals, ...]
    day_count: int
    label: str


_FILL_STATUSES = frozenset({OrderAckStatus.FILLED, OrderAckStatus.PARTIALLY_FILLED})
_CLASS_RANK = (
    "SAME",
    "EXIT_CHANGED",
    "ENTRY_CHANGED",
    "LEGACY_ONLY",
    "ENGINE_ONLY",
    "UNEXPLAINED",
)
_LABEL = "descriptive"
_LegKey = tuple[tuple[int, int, int, int], ...]


@dataclass(slots=True)
class _Open:
    signal: Signal
    side: str
    entries: list[Fill]
    exits: list[Fill]
    exit_orders: list[OrderRequest]


@dataclass(frozen=True, slots=True)
class _Episode:
    symbol: str
    strategy_id: str
    entry_signal: Signal
    side: str
    entry_fills: tuple[Fill, ...]
    exit_fills: tuple[Fill, ...]
    exit_order: OrderRequest | None
    engine_reason: str
    engine_worst: PositionExtreme | None


def _metadata_key(sig: Signal) -> tuple[tuple[str, object], ...]:
    """Signal metadata with ``manifest_hash`` removed (D-249 G1)."""
    kept: list[tuple[str, object]] = []
    for key in sorted(sig.metadata):
        if key == "manifest_hash":
            continue
        kept.append((key, sig.metadata[key]))
    return tuple(kept)


def _signal_identity(sig: Signal) -> tuple[object, ...]:
    return (
        sig.timestamp_ns,
        sig.correlation_id,
        sig.sequence,
        sig.source_layer,
        sig.schema_version,
        sig.symbol,
        sig.strategy_id,
        sig.direction,
        sig.strength,
        sig.edge_estimate_bps,
        sig.disclosed_cost_total_bps,
        sig.disclosed_margin_ratio,
        _metadata_key(sig),
        sig.layer,
        sig.horizon_seconds,
        sig.regime_gate_state,
        sig.consumed_features,
        sig.trend_mechanism,
        sig.expected_half_life_seconds,
        sig.boundary_ts_ns,
    )


def _dedup(signals: Sequence[Signal]) -> tuple[Signal, ...]:
    kept: list[Signal] = []
    for sig in signals:
        if sig in kept:
            continue
        kept.append(sig)
    return tuple(kept)


def _require_same_signals(legacy: tuple[Signal, ...], engine: tuple[Signal, ...]) -> None:
    left = tuple(_signal_identity(sig) for sig in legacy)
    right = tuple(_signal_identity(sig) for sig in engine)
    if left != right:
        raise AttributionError("signal streams differ")


def _correlated(signals: tuple[Signal, ...], order: OrderRequest) -> tuple[Signal, ...]:
    return tuple(
        sig
        for sig in signals
        if sig.correlation_id == order.correlation_id
        and sig.symbol == order.symbol
        and sig.strategy_id == order.strategy_id
    )


def _submitted_rows(arm: ArmEvents, order: OrderRequest) -> tuple[SignalOrderTraceRow, ...]:
    return tuple(
        row
        for row in arm.signal_order_traces
        if row.outcome == "ORDER_SUBMITTED"
        and row.quote_correlation_id == order.correlation_id
        and row.symbol == order.symbol
        and row.strategy_id == order.strategy_id
    )


def _signals_for_row(signals: tuple[Signal, ...], row: SignalOrderTraceRow) -> tuple[Signal, ...]:
    return tuple(
        sig
        for sig in signals
        if sig.sequence == row.signal_sequence
        and sig.symbol == row.symbol
        and sig.strategy_id == row.strategy_id
    )


def _verdict_signals(
    signals: tuple[Signal, ...],
    order: OrderRequest,
    verdicts: Sequence[RiskVerdict],
) -> tuple[Signal, ...]:
    linked: list[Signal] = []
    seen: list[tuple[object, ...]] = []
    for verdict in verdicts:
        if verdict.timestamp_ns != order.timestamp_ns or verdict.symbol != order.symbol:
            continue
        for sig in signals:
            if sig.correlation_id != verdict.correlation_id:
                continue
            if sig.symbol != order.symbol or sig.strategy_id != order.strategy_id:
                continue
            identity = _signal_identity(sig)
            if identity in seen:
                continue
            seen.append(identity)
            linked.append(sig)
    return tuple(linked)


def _opening_signal(arm: ArmEvents, signals: tuple[Signal, ...], order: OrderRequest) -> Signal:
    """Entry signal for an opening order (D-249, D-252)."""
    if arm.signal_order_traces:
        rows = _submitted_rows(arm, order)
        if len(rows) != 1:
            raise AttributionError("opening order signal count")
        found = _signals_for_row(signals, rows[0])
        if len(found) != 1:
            raise AttributionError("opening order signal count")
        return found[0]
    matched = _correlated(signals, order)
    if len(matched) > 1:
        raise AttributionError("opening order signal count")
    if len(matched) == 1:
        return matched[0]
    linked = _verdict_signals(signals, order, arm.risk_verdicts)
    if len(linked) != 1:
        raise AttributionError("opening order signal count")
    return linked[0]


def _positive_fills(arm: ArmEvents) -> list[tuple[OrderRequest, OrderAck]]:
    by_id = {order.order_id: order for order in arm.order_requests}
    found: list[tuple[OrderRequest, OrderAck]] = []
    for ack in arm.order_acks:
        if ack.filled_quantity <= 0 or ack.status not in _FILL_STATUSES:
            continue
        if ack.fill_price is None:
            raise AttributionError("fill without a price")
        order = by_id.get(ack.order_id)
        if order is None:
            raise AttributionError("fill without an order")
        found.append((order, ack))
    found.sort(key=lambda pair: (pair[1].timestamp_ns, pair[1].sequence))
    return found


def _fill(ack: OrderAck, qty: int, fee: Decimal) -> Fill:
    if ack.fill_price is None:
        raise AttributionError("fill without a price")
    return Fill(
        fill_price=ack.fill_price,
        filled_quantity=qty,
        timestamp_ns=ack.timestamp_ns,
        fees=fee,
        sequence=ack.sequence,
    )


def _portion(fee: Decimal, part: int, total: int) -> Decimal:
    return fee * Decimal(part) / Decimal(total)


def _finish(symbol: str, strategy_id: str, current: _Open) -> _Episode:
    return _Episode(
        symbol=symbol,
        strategy_id=strategy_id,
        entry_signal=current.signal,
        side=current.side,
        entry_fills=tuple(current.entries),
        exit_fills=tuple(current.exits),
        exit_order=current.exit_orders[-1] if current.exit_orders else None,
        engine_reason="",
        engine_worst=None,
    )


def _apply_reducing(
    current: _Open,
    order: OrderRequest,
    ack: OrderAck,
    pos: int,
) -> tuple[int, _Open | None, _Episode | None, tuple[OrderAck, int, Decimal] | None]:
    qty = ack.filled_quantity
    reducing = min(abs(pos), qty)
    excess = qty - reducing
    close_fee = ack.fees if excess == 0 else _portion(ack.fees, reducing, qty)
    current.exits.append(_fill(ack, reducing, close_fee))
    current.exit_orders.append(order)
    pos = pos - reducing if pos > 0 else pos + reducing
    closed: _Episode | None = None
    still: _Open | None = current
    if pos == 0:
        closed = _finish(order.symbol, order.strategy_id, current)
        still = None
    reopen = None if excess == 0 else (ack, excess, ack.fees - close_fee)
    return pos, still, closed, reopen


def _episodes(arm: ArmEvents, signals: tuple[Signal, ...]) -> tuple[_Episode, ...]:
    grouped: dict[tuple[str, str], list[tuple[OrderRequest, OrderAck]]] = {}
    for order, ack in _positive_fills(arm):
        grouped.setdefault((order.symbol, order.strategy_id), []).append((order, ack))
    built: list[_Episode] = []
    for fills in grouped.values():
        pos = 0
        current: _Open | None = None
        for order, ack in fills:
            qty = ack.filled_quantity
            signed = qty if order.side == Side.BUY else -qty
            if pos == 0 or current is None:
                signal = _opening_signal(arm, signals, order)
                side = "LONG" if signed > 0 else "SHORT"
                current = _Open(signal, side, [_fill(ack, qty, ack.fees)], [], [])
                pos = signed
                continue
            same_way = (pos > 0 and signed > 0) or (pos < 0 and signed < 0)
            if same_way:
                current.entries.append(_fill(ack, qty, ack.fees))
                pos += signed
                continue
            pos, current, closed, reopen = _apply_reducing(current, order, ack, pos)
            if closed is not None:
                built.append(closed)
            if reopen is not None:
                reopen_ack, excess, fee = reopen
                signal = _opening_signal(arm, signals, order)
                side = "LONG" if signed > 0 else "SHORT"
                current = _Open(signal, side, [_fill(reopen_ack, excess, fee)], [], [])
                pos = excess if signed > 0 else -excess
        if current is not None:
            built.append(_finish(current.signal.symbol, current.signal.strategy_id, current))
    return tuple(built)


def _leg_key(fills: tuple[Fill, ...]) -> _LegKey:
    return tuple(
        (int(item.fill_price * 100), item.filled_quantity, item.timestamp_ns, item.sequence)
        for item in fills
    )


def _closed_legs(legs: tuple[PositionFillLeg, ...]) -> _LegKey:
    return tuple((leg.price_cents, leg.quantity, leg.timestamp_ns, leg.sequence) for leg in legs)


def _bind_closed(
    episodes: tuple[_Episode, ...],
    closed: Sequence[PositionClosed],
) -> tuple[_Episode, ...]:
    if len(episodes) != len(closed):
        raise AttributionError("engine cross-check count")
    remaining = list(closed)
    bound: list[_Episode] = []
    for episode in episodes:
        key = (
            episode.symbol,
            episode.strategy_id,
            _leg_key(episode.entry_fills),
            _leg_key(episode.exit_fills),
        )
        match_at: int | None = None
        for index, item in enumerate(remaining):
            item_key = (
                item.symbol,
                item.strategy_id,
                _closed_legs(item.entry_fills),
                _closed_legs(item.exit_fills),
            )
            if item_key == key:
                match_at = index
                break
        if match_at is None:
            raise AttributionError("engine cross-check mismatch")
        found = remaining.pop(match_at)
        bound.append(replace(episode, engine_reason=found.exit_reason, engine_worst=found.worst))
    return tuple(bound)


def _quantity(fills: tuple[Fill, ...]) -> int:
    total = 0
    for item in fills:
        total += item.filled_quantity
    return total


def _direction_reason(direction: SignalDirection, opposite: SignalDirection) -> str:
    if direction == SignalDirection.FLAT:
        return "SIGNAL_FLAT"
    if direction == opposite:
        return "SIGNAL_REVERSE"
    return "UNATTRIBUTED"


def _legacy_reason(episode: _Episode, signals: tuple[Signal, ...], arm: ArmEvents) -> str:
    if _quantity(episode.entry_fills) != _quantity(episode.exit_fills):
        return "END_OF_TAPE"
    order = episode.exit_order
    if order is None:
        raise AttributionError("exit fill without an order")
    if order.reason:
        return order.reason
    opposite = SignalDirection.SHORT if episode.side == "LONG" else SignalDirection.LONG
    if arm.signal_order_traces:
        rows = _submitted_rows(arm, order)
        if len(rows) != 1:
            return "UNATTRIBUTED"
        found = _signals_for_row(signals, rows[0])
        if len(found) != 1:
            return "UNATTRIBUTED"
        return _direction_reason(found[0].direction, opposite)
    matched = _correlated(signals, order)
    if any(sig.direction == SignalDirection.FLAT for sig in matched):
        return "SIGNAL_FLAT"
    if any(sig.direction == opposite for sig in matched):
        return "SIGNAL_REVERSE"
    if matched:
        return "UNATTRIBUTED"
    linked = _verdict_signals(signals, order, arm.risk_verdicts)
    if len(linked) != 1:
        return "UNATTRIBUTED"
    return _direction_reason(linked[0].direction, opposite)


def _position_before(arm: ArmEvents, symbol: str, strategy_id: str, timestamp_ns: int) -> int:
    pos = 0
    for order, ack in _positive_fills(arm):
        if order.symbol != symbol or order.strategy_id != strategy_id:
            continue
        if ack.timestamp_ns >= timestamp_ns:
            continue
        qty = ack.filled_quantity
        pos += qty if order.side == Side.BUY else -qty
    return pos


def _reject_reason(arm: ArmEvents, signal: Signal) -> str | None:
    for verdict in arm.risk_verdicts:
        if verdict.action != RiskAction.REJECT:
            continue
        if verdict.correlation_id != signal.correlation_id or verdict.symbol != signal.symbol:
            continue
        return verdict.reason
    return None


def _no_order_reason(arm: ArmEvents, signal: Signal) -> str | None:
    for row in arm.signal_order_traces:
        if row.outcome != "NO_ORDER":
            continue
        if (
            row.signal_sequence != signal.sequence
            or row.symbol != signal.symbol
            or row.strategy_id != signal.strategy_id
        ):
            continue
        return row.reasons[0]
    return None


def _one_arm_explanation(other: ArmEvents, signal: Signal, label: str) -> str:
    held = _position_before(other, signal.symbol, signal.strategy_id, signal.timestamp_ns)
    if held != 0:
        return label
    reason = _reject_reason(other, signal)
    if reason is not None:
        return f"RISK:{reason}"
    no_order = _no_order_reason(other, signal)
    if no_order is not None:
        return f"NO_ORDER:{no_order}"
    return ""


def _symbol_quotes(quotes: Sequence[NBBOQuote], symbol: str) -> tuple[NBBOQuote, ...]:
    return tuple(quote for quote in quotes if quote.symbol == symbol)


def _window_end(episode: _Episode, quotes: Sequence[NBBOQuote]) -> int:
    if episode.exit_fills and _quantity(episode.entry_fills) == _quantity(episode.exit_fills):
        return episode.exit_fills[-1].timestamp_ns
    symbol_quotes = _symbol_quotes(quotes, episode.symbol)
    if not symbol_quotes:
        raise AttributionError("no quote for an open episode")
    return max(quote.timestamp_ns for quote in symbol_quotes)


def _holding(episode: _Episode, quotes: Sequence[NBBOQuote]) -> int:
    return _window_end(episode, quotes) - episode.entry_fills[0].timestamp_ns


def _mae(episode: _Episode, quotes: Sequence[NBBOQuote]) -> Decimal:
    start = episode.entry_fills[0].timestamp_ns
    end = _window_end(episode, quotes)
    window = tuple(
        quote
        for quote in _symbol_quotes(quotes, episode.symbol)
        if start <= quote.timestamp_ns <= end
    )
    if not window:
        raise AttributionError("no quote inside the excursion window")
    events: list[tuple[int, int, bool, Fill]] = [
        (fill.timestamp_ns, fill.sequence, False, fill) for fill in episode.entry_fills
    ]
    events.extend((fill.timestamp_ns, fill.sequence, True, fill) for fill in episode.exit_fills)
    events.sort(key=lambda item: (item[0], item[1], item[2]))
    worst = Decimal(0)
    for quote in window:
        average = Decimal(0)
        held = 0
        for timestamp_ns, _sequence, is_exit, fill in events:
            if timestamp_ns > quote.timestamp_ns:
                break
            if is_exit:
                held -= fill.filled_quantity
                continue
            held += fill.filled_quantity
            average = (
                average * (held - fill.filled_quantity) + fill.fill_price * fill.filled_quantity
            ) / Decimal(held)
        excursion = average - quote.bid if episode.side == "LONG" else quote.ask - average
        if excursion > worst:
            worst = excursion
    return worst


def _money(values: Sequence[Decimal]) -> Decimal:
    total = Decimal(0)
    for value in values:
        total += value
    return total


def _net(episode: _Episode) -> Decimal:
    fees = _money(tuple(item.fees for item in episode.entry_fills))
    fees += _money(tuple(item.fees for item in episode.exit_fills))
    if not episode.exit_fills:
        return -_money(tuple(item.fees for item in episode.entry_fills))
    sign = Decimal(1) if episode.side == "LONG" else Decimal(-1)
    entry_notional = _money(
        tuple(item.fill_price * item.filled_quantity for item in episode.entry_fills)
    )
    exit_notional = _money(
        tuple(item.fill_price * item.filled_quantity for item in episode.exit_fills)
    )
    entered = _quantity(episode.entry_fills)
    exited = _quantity(episode.exit_fills)
    if entered == exited:
        cost = entry_notional
    else:
        cost = entry_notional * Decimal(exited) / Decimal(entered)
    return sign * (exit_notional - cost) - fees


def _arm_episode(episode: _Episode, quotes: Sequence[NBBOQuote]) -> ArmEpisode:
    return ArmEpisode(
        symbol=episode.symbol,
        strategy_id=episode.strategy_id,
        entry_signal=episode.entry_signal,
        side=episode.side,
        entry_fills=episode.entry_fills,
        exit_fills=episode.exit_fills,
        net_after_fees=_net(episode),
        holding_time_ns=_holding(episode, quotes),
    )


def _episode_key(episode: _Episode) -> tuple[object, ...]:
    return (episode.symbol, episode.strategy_id, _signal_identity(episode.entry_signal))


def _unique(episodes: tuple[_Episode, ...]) -> tuple[_Episode, ...]:
    seen: list[tuple[object, ...]] = []
    for episode in episodes:
        key = _episode_key(episode)
        if key in seen:
            raise AttributionError("duplicate episode")
        seen.append(key)
    return episodes


def _classify(
    legacy: _Episode | None,
    engine: _Episode | None,
    explanation: str,
) -> str:
    if legacy is not None and engine is not None:
        if legacy.entry_fills == engine.entry_fills and legacy.exit_fills == engine.exit_fills:
            return "SAME"
        if legacy.entry_fills == engine.entry_fills:
            return "EXIT_CHANGED"
        return "ENTRY_CHANGED"
    if explanation == "":
        return "UNEXPLAINED"
    if legacy is not None:
        return "LEGACY_ONLY"
    return "ENGINE_ONLY"


def _totals(diffs: tuple[EpisodeDiff, ...]) -> tuple[ClassTotals, ...]:
    rows: list[ClassTotals] = []
    for name in _CLASS_RANK:
        members = tuple(item for item in diffs if item.episode_class == name)
        if not members:
            continue
        legacy_net = Decimal(0)
        engine_net = Decimal(0)
        for item in members:
            if item.legacy is not None:
                legacy_net += item.legacy.net_after_fees
            if item.engine is not None:
                engine_net += item.engine.net_after_fees
        rows.append(ClassTotals(name, len(members), legacy_net, engine_net))
    return tuple(rows)


def _diff_sort_key(item: EpisodeDiff) -> tuple[str, str, int, int]:
    episode = item.legacy if item.legacy is not None else item.engine
    if episode is None:
        raise AttributionError("empty diff")
    signal = episode.entry_signal
    return (episode.symbol, episode.strategy_id, signal.timestamp_ns, signal.sequence)


def attribute(
    legacy: ArmEvents,
    engine: ArmEvents,
    *,
    day_count: int,
) -> AttributionReport:
    """Diff ``legacy`` against ``engine``. ``day_count`` is recorded, not interpreted."""
    legacy_signals = _dedup(legacy.signals)
    engine_signals = _dedup(engine.signals)
    _require_same_signals(legacy_signals, engine_signals)
    legacy_eps = _unique(_episodes(legacy, legacy_signals))
    engine_eps = _unique(_bind_closed(_episodes(engine, engine_signals), engine.position_closed))
    keys: list[tuple[object, ...]] = []
    for episode in (*legacy_eps, *engine_eps):
        key = _episode_key(episode)
        if key not in keys:
            keys.append(key)
    diffs: list[EpisodeDiff] = []
    for key in keys:
        legacy_ep = next((item for item in legacy_eps if _episode_key(item) == key), None)
        engine_ep = next((item for item in engine_eps if _episode_key(item) == key), None)
        explanation = ""
        if legacy_ep is not None and engine_ep is None:
            explanation = _one_arm_explanation(
                engine, legacy_ep.entry_signal, "ENGINE_IN_POSITION"
            )
        elif engine_ep is not None and legacy_ep is None:
            explanation = _one_arm_explanation(
                legacy, engine_ep.entry_signal, "LEGACY_IN_POSITION"
            )
        present = legacy_ep if legacy_ep is not None else engine_ep
        if present is None:
            raise AttributionError("empty episode key")
        diffs.append(
            EpisodeDiff(
                episode_class=_classify(legacy_ep, engine_ep, explanation),
                engine_reason="" if engine_ep is None else engine_ep.engine_reason,
                legacy_reason=""
                if legacy_ep is None
                else _legacy_reason(legacy_ep, legacy_signals, legacy),
                explanation=explanation,
                legacy=None if legacy_ep is None else _arm_episode(legacy_ep, legacy.quotes),
                engine=None if engine_ep is None else _arm_episode(engine_ep, engine.quotes),
                legacy_mae=None if legacy_ep is None else _mae(legacy_ep, legacy.quotes),
                engine_mae=None if engine_ep is None else _mae(engine_ep, engine.quotes),
                engine_worst=None if engine_ep is None else engine_ep.engine_worst,
            )
        )
    ordered = tuple(sorted(diffs, key=_diff_sort_key))
    return AttributionReport(
        diffs=ordered,
        totals=_totals(ordered),
        day_count=day_count,
        label=_LABEL,
    )
