"""G-7 — edge-weighted / vol-targeted sizing with an inventory penalty.

The default ``BudgetBasedSizer`` is single-factor: ``equity × capital_pct ×
strength × regime / price``, capped.  It ignores three things an
institutional sizer would not:

  * **edge magnitude** — a 2-bps and a 40-bps signal of equal ``strength``
    take the same size, even though their expected value differs 20×;
  * **realized volatility** — a calm name and a turbulent one are sized
    identically, so risk-per-position is uncontrolled;
  * **current inventory** — size does not taper as the book fills toward
    the per-symbol cap, so the last add is as large as the first.

``EdgeWeightedSizer`` wraps a base :class:`PositionSizer` and applies a
deterministic multiplicative *tilt* — ``edge × vol × inventory`` — on top
of the base target, then re-caps at the alpha's per-symbol budget.

Parity (Inv-5).  Every factor is **disabled by default**.  With the
default :class:`SizerTiltConfig`, each factor is exactly ``1.0``, the
combined tilt is ``1.0``, and ``floor(base × 1.0) == base`` — so the
sizer is byte-identical to its base until a factor is explicitly enabled.
This lets G-7 ship dark and be measured in shadow before any flip,
matching the B5 / G-1…G-6 rollout pattern.

Inv-11 (fail-safe).  The factors here *can* amplify (edge-weighting a
high-conviction signal is the point of G-7), so amplification is a
deliberate, config-gated behaviour — distinct from the regime factor,
which still only ever shrinks.  Each factor is independently clamped, the
combined tilt is clamped to ``[tilt_floor, tilt_cap]``, and the result is
always re-capped at ``max_position_per_symbol`` and floored at 0.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal

from feelies.alpha.module import AlphaRiskBudget
from feelies.core.events import Signal
from feelies.risk.position_sizer import PositionSizer


@dataclass(frozen=True)
class SizerTiltConfig:
    """Feature flags + parameters for the three sizing factors.

    Defaults disable every factor, so the tilt is exactly ``1.0`` and the
    wrapped sizer reproduces its base byte-for-byte.
    """

    # ── Edge factor: scale by edge relative to a reference. ────────────
    edge_enabled: bool = False
    edge_ref_bps: float = 20.0  # edge == ref → factor 1.0
    edge_floor: float = 0.25  # never shrink an entry below 25% on edge
    edge_cap: float = 2.0  # never amplify beyond 2× on edge

    # ── Vol factor: target_vol / realized_vol (vol targeting). ─────────
    vol_enabled: bool = False
    vol_target_bps: float = 100.0  # realized == target → factor 1.0
    vol_floor: float = 0.25
    vol_cap: float = 2.0

    # ── Inventory factor: taper as |inventory| nears the cap. ──────────
    inventory_enabled: bool = False
    inventory_floor: float = 0.0  # at the cap, factor floors here

    # ── Combined-tilt clamp (applied after the product). ───────────────
    tilt_floor: float = 0.10
    tilt_cap: float = 3.0

    @property
    def any_enabled(self) -> bool:
        return self.edge_enabled or self.vol_enabled or self.inventory_enabled


@dataclass(frozen=True)
class TiltBreakdown:
    """Per-factor decomposition of a sizing tilt (for the shadow stream)."""

    edge: float
    vol: float
    inventory: float
    combined: float  # clamped product of the enabled factors
    inventory_qty: int  # signed inventory observed (0 when no provider)
    realized_vol_bps: float | None  # observed realized vol (None when absent)


@dataclass(frozen=True)
class SizeDivergence:
    """G-7 S1 shadow record: the tilted target differs from the base target.

    Emitted when the edge/vol/inventory-tilted size for a sized signal
    disagrees with the live single-factor budget target — the measurement
    that quantifies how much G-7 sizing would change the order book before
    any flip.  ``magnitude = tilted - base``.
    """

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


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def edge_factor(edge_bps: float, *, ref_bps: float, floor: float, cap: float) -> float:
    """Linear edge tilt: ``edge / ref``, clamped to ``[floor, cap]``.

    ``edge == ref`` → ``1.0``.  A negative or zero reference is treated as
    a no-op (``1.0``) so a misconfiguration can't divide by zero or flip
    the sign of the size.
    """
    if ref_bps <= 0.0:
        return 1.0
    return _clamp(edge_bps / ref_bps, floor, cap)


def vol_factor(
    realized_vol_bps: float | None, *, target_vol_bps: float, floor: float, cap: float
) -> float:
    """Vol-targeting tilt: ``target / realized``, clamped to ``[floor, cap]``.

    A higher realized vol shrinks the size; a calmer name grows it.  A
    missing or non-positive realized vol is a no-op (``1.0``) — we never
    upsize on absent data.
    """
    if realized_vol_bps is None or realized_vol_bps <= 0.0 or target_vol_bps <= 0.0:
        return 1.0
    return _clamp(target_vol_bps / realized_vol_bps, floor, cap)


def inventory_factor(current_qty: int, max_position: int, *, floor: float) -> float:
    """Inventory taper: ``1 - |inventory| / max_position``, clamped ``[floor, 1.0]``.

    A flat book → ``1.0`` (full size); a book at the cap → ``floor``.  This
    factor never amplifies — it only tapers adds as the book fills.  A
    non-positive cap is a no-op (``1.0``).
    """
    if max_position <= 0:
        return 1.0
    used = abs(current_qty) / max_position
    return _clamp(1.0 - used, floor, 1.0)


class EdgeWeightedSizer:
    """Wrap a base sizer; tilt its target by edge × vol × inventory.

    Implements the :class:`PositionSizer` protocol, so it is a drop-in for
    ``BudgetBasedSizer``.  Volatility and inventory are sourced through
    optional provider callables (keyed by symbol), mirroring how
    ``BudgetBasedSizer`` takes an optional ``regime_engine`` — when a
    provider is absent its factor is a no-op, preserving parity.
    """

    def __init__(
        self,
        base: PositionSizer,
        config: SizerTiltConfig | None = None,
        *,
        realized_vol_provider: Callable[[str], float | None] | None = None,
        inventory_provider: Callable[[str], int] | None = None,
    ) -> None:
        self._base = base
        self._config = config or SizerTiltConfig()
        self._realized_vol_provider = realized_vol_provider
        self._inventory_provider = inventory_provider

    @property
    def config(self) -> SizerTiltConfig:
        return self._config

    @property
    def base(self) -> PositionSizer:
        return self._base

    def tilt_breakdown(self, signal: Signal, risk_budget: AlphaRiskBudget) -> TiltBreakdown:
        """Per-factor decomposition + clamped combined tilt for a signal.

        Exposed for the shadow harness so the measurement stream can record
        each factor alongside the base and tilted targets without
        recomputing.  All-off → unit factors and ``combined == 1.0``.
        """
        cfg = self._config
        ef = vf = invf = 1.0
        inv_qty = 0
        rv: float | None = None

        if cfg.edge_enabled:
            ef = edge_factor(
                signal.edge_estimate_bps,
                ref_bps=cfg.edge_ref_bps,
                floor=cfg.edge_floor,
                cap=cfg.edge_cap,
            )
        if cfg.vol_enabled:
            rv = (
                self._realized_vol_provider(signal.symbol)
                if self._realized_vol_provider is not None
                else None
            )
            vf = vol_factor(
                rv,
                target_vol_bps=cfg.vol_target_bps,
                floor=cfg.vol_floor,
                cap=cfg.vol_cap,
            )
        if cfg.inventory_enabled:
            inv_qty = (
                self._inventory_provider(signal.symbol)
                if self._inventory_provider is not None
                else 0
            )
            invf = inventory_factor(
                inv_qty,
                risk_budget.max_position_per_symbol,
                floor=cfg.inventory_floor,
            )

        combined = (
            1.0 if not cfg.any_enabled else _clamp(ef * vf * invf, cfg.tilt_floor, cfg.tilt_cap)
        )
        return TiltBreakdown(
            edge=ef,
            vol=vf,
            inventory=invf,
            combined=combined,
            inventory_qty=inv_qty,
            realized_vol_bps=rv,
        )

    def tilt_for(self, signal: Signal, risk_budget: AlphaRiskBudget) -> float:
        """Deterministic combined tilt for a signal (1.0 when all-off)."""
        return self.tilt_breakdown(signal, risk_budget).combined

    def compute_target_quantity(
        self,
        signal: Signal,
        risk_budget: AlphaRiskBudget,
        symbol_price: Decimal,
        account_equity: Decimal,
    ) -> int:
        base_target = self._base.compute_target_quantity(
            signal=signal,
            risk_budget=risk_budget,
            symbol_price=symbol_price,
            account_equity=account_equity,
        )
        # Parity short-circuit: all factors off → byte-identical to base.
        if base_target <= 0 or not self._config.any_enabled:
            return base_target

        tilt = self.tilt_for(signal, risk_budget)
        return apply_tilt(base_target, tilt, risk_budget.max_position_per_symbol)


def apply_tilt(base_target: int, tilt: float, max_position: int) -> int:
    """Floor ``base × tilt`` deterministically, re-cap, and floor at 0."""
    tilted = int(Decimal(base_target) * Decimal(str(tilt)))  # floor
    return max(0, min(tilted, max_position))
