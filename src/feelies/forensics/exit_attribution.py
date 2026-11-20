"""Report-only diff of one tape run in two exit arms (D-249)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal

from feelies.core.events import (
    NBBOQuote,
    OrderAck,
    OrderRequest,
    PositionClosed,
    PositionExtreme,
    RiskVerdict,
    Signal,
)


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


def attribute(
    legacy: ArmEvents,
    engine: ArmEvents,
    *,
    day_count: int,
) -> AttributionReport:
    """Diff ``legacy`` against ``engine``. ``day_count`` is recorded, not interpreted."""
    raise NotImplementedError("P-95 stub")
