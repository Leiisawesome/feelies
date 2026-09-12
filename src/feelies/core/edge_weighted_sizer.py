"""EdgeWeightedSizer protocol and SizeDivergence.

The Protocol and dataclass live in core so kernel can name them
without importing the risk package.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from feelies.core.alpha_risk_budget import AlphaRiskBudget
from feelies.core.events import Signal
from feelies.core.position_sizer import PositionSizer


class _SizerConfig(Protocol):
    @property
    def any_enabled(self) -> bool: ...


class _TiltBreakdown(Protocol):
    @property
    def combined(self) -> float: ...

    @property
    def edge(self) -> float: ...

    @property
    def vol(self) -> float: ...

    @property
    def inventory(self) -> float: ...

    @property
    def inventory_qty(self) -> int: ...


class EdgeWeightedSizer(Protocol):
    """Named surface: config, base, tilt_breakdown."""

    @property
    def config(self) -> _SizerConfig: ...

    @property
    def base(self) -> PositionSizer: ...

    def tilt_breakdown(
        self, signal: Signal, risk_budget: AlphaRiskBudget
    ) -> _TiltBreakdown: ...


@dataclass(frozen=True)
class SizeDivergence:
    """Record a difference between tilted and base position targets."""

    symbol: str
    signal_sequence: int
    strategy_id: str
    edge_bps: float
    base_target_qty: int
    tilted_target_qty: int
    edge_factor: float
    vol_factor: float
    inventory_factor: float
    combined_tilt: float
    inventory_qty: int
    timestamp_ns: int = 0
    detail: str = ""
