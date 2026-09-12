"""Per-symbol data-stream health, halt store, and kernel health Protocol.

Kernel names DataHealth, the halt store, and the health/all_health
surface without importing the ingestion package. Implementations stay
on the ingestion MarketDataNormalizer Protocol.
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import Enum, auto
from typing import Any, Protocol

from feelies.core.exception_taxonomy import KernelFault
from feelies.core.gate_registry import record_verdict
from feelies.core.state_machine import StateMachine


class DataHealth(Enum):
    """Per-symbol data stream health.

    ``CORRUPTED`` is a terminal state by design: once a symbol stream is
    corrupted, the only recovery path is a manual restart.  The operator
    runbook should restart the normalizer for affected symbols.

    ``HALTED`` is a recoverable trading suspension surfaced from
    the tape (LULD / regulatory halt condition codes).  Unlike CORRUPTED
    it does not escalate the macro state machine to DEGRADED — the symbol
    resumes to HEALTHY when the halt-off marker arrives.  Consumers treat
    HALTED as "suppress fills for this symbol" (fail-safe, Inv-11).
    """

    HEALTHY = auto()
    GAP_DETECTED = auto()
    HALTED = auto()
    CORRUPTED = auto()


class HaltSignal(Enum):
    """Classification of a tape event's halt-status condition codes."""

    HALT_ON = auto()
    HALT_OFF = auto()


def classify_halt_status(
    conditions: Iterable[int],
    halt_on_codes: frozenset[int],
    halt_off_codes: frozenset[int],
) -> HaltSignal | None:
    """Map tape condition codes to a :class:`HaltSignal`, or ``None``.

    Pure function shared by the normalizer (DataHealth transitions) and
    the orchestrator (backtest fill gating) so the halt-code grammar has
    a single source of truth.  When a single event carries *both* a
    halt-on and a halt-off code (degenerate / contradictory tape),
    halt-on wins — staying suspended is the fail-safe reading (Inv-11).
    """
    if not halt_on_codes and not halt_off_codes:
        return None
    present = set(conditions)
    if present & halt_on_codes:
        record_verdict("RT.DATA_HEALTH", "FAIL", HaltSignal.HALT_ON.name)
        return HaltSignal.HALT_ON
    if present & halt_off_codes:
        record_verdict("RT.DATA_HEALTH", "PASS", HaltSignal.HALT_OFF.name)
        return HaltSignal.HALT_OFF
    record_verdict("RT.DATA_HEALTH", "PASS")
    return None


class _HaltTradeability:
    """Engine-1 store for LULD halt tradeability (G33).

    Orchestrator and MassiveNormalizer hold a reference and read. Tape
    updates, config, and reset write here. ``KernelFault(SESSION_HALT)``
    on a missing owner or a second codebook that disagrees.
    """

    def __init__(self) -> None:
        self.halted_symbols: set[str] = set()
        self.blackout_until_ns: dict[str, int] = {}
        self.on_codes: frozenset[int] = frozenset()
        self.off_codes: frozenset[int] = frozenset()
        self.blackout_ns: int = 0
        self.forensic_open: set[str] = set()

    def configure(
        self,
        on_codes: frozenset[int],
        off_codes: frozenset[int],
        blackout_ns: int,
        *,
        peer_on: frozenset[int] | None = None,
        peer_off: frozenset[int] | None = None,
    ) -> None:
        if peer_on is not None and peer_off is not None:
            if (peer_on, peer_off) != (on_codes, off_codes):
                raise KernelFault(
                    "halt codebook conflict between session/halt authorities",
                    kind=KernelFault.Kind.SESSION_HALT,
                )
        self.on_codes = on_codes
        self.off_codes = off_codes
        self.blackout_ns = blackout_ns

    def reset(self) -> None:
        self.halted_symbols.clear()
        self.blackout_until_ns.clear()
        self.forensic_open.clear()

    def in_blackout(self, symbol: str, now_ns: int) -> bool:
        deadline = self.blackout_until_ns.get(symbol)
        return deadline is not None and now_ns < deadline


def _require_halt_authority(self: Any) -> _HaltTradeability:
    """Return the engine-1 halt store, or raise ``KernelFault(SESSION_HALT)``."""
    authority = getattr(self, "_halt_tradeability", None)
    if not isinstance(authority, _HaltTradeability):
        raise KernelFault(
            "session/halt tradeability authority is missing",
            kind=KernelFault.Kind.SESSION_HALT,
        )
    return authority


def _bound_trade_feed_health_sm(
    self: Any,
    symbol: str,
    *,
    ensure: bool,
) -> StateMachine[DataHealth] | None:
    """Return the trade-feed health SM if a normalizer that owns one is bound."""
    normalizer: Any = self
    machines = getattr(normalizer, "_health_machines", None)
    feed = getattr(normalizer, "_FEED_TRADE", None)
    if machines is None or feed is None:
        normalizer = getattr(self, "_normalizer", None)
        if normalizer is None:
            return None
        machines = getattr(normalizer, "_health_machines", None)
        feed = getattr(normalizer, "_FEED_TRADE", None)
        if machines is None or feed is None:
            return None
    sm = machines.get((symbol, feed))
    if sm is None and ensure:
        ensure_fn = getattr(normalizer, "_ensure_health_machine", None)
        if ensure_fn is None:
            return None
        sm = ensure_fn(symbol, feed)
    if not isinstance(sm, StateMachine):
        return None
    return sm


def _sync_halt_store_and_health(
    self: Any,
    symbol: str,
    conditions: Iterable[int],
    *,
    timestamp_ns: int | None = None,
) -> HaltSignal | None:
    """Update ``_HaltTradeability`` and the trade-feed health SM together."""
    authority = _require_halt_authority(self)
    if not authority.on_codes and not authority.off_codes:
        return None
    status = classify_halt_status(
        conditions,
        authority.on_codes,
        authority.off_codes,
    )
    if status is None:
        return None
    sm = _bound_trade_feed_health_sm(self, symbol, ensure=True)
    if status is HaltSignal.HALT_ON:
        if symbol not in authority.halted_symbols:
            authority.halted_symbols.add(symbol)
            authority.blackout_until_ns.pop(symbol, None)
        if (
            sm is not None
            and sm.state != DataHealth.HALTED
            and sm.can_transition(DataHealth.HALTED)
        ):
            sm.transition(DataHealth.HALTED, trigger="luld_halt_on")
    else:
        was_in = symbol in authority.halted_symbols
        health_was_halted = sm is not None and sm.state == DataHealth.HALTED
        if was_in:
            authority.halted_symbols.discard(symbol)
        if (was_in or health_was_halted) and timestamp_ns is not None:
            authority.blackout_until_ns[symbol] = timestamp_ns + authority.blackout_ns
        if sm is not None and health_was_halted and sm.can_transition(DataHealth.HEALTHY):
            sm.transition(DataHealth.HEALTHY, trigger="luld_halt_off")
    return status


class MarketDataNormalizer(Protocol):
    """Health surface kernel names. Implementations stay on the ingestion Protocol."""

    def health(self, symbol: str) -> DataHealth:
        """Current data integrity state for a symbol."""
        ...

    def all_health(self) -> dict[str, DataHealth]:
        """Data integrity state for all tracked symbols."""
        ...
