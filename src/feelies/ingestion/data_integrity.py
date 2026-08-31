"""Per-symbol data integrity state machine (Section VII of the system diagram).

Each symbol stream maintains its own health state.
If CORRUPTED during PAPER_TRADING_MODE, the global macro state
transitions to DEGRADED — execution stops.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from enum import Enum, auto
from typing import Any

from feelies.core.clock import Clock
from feelies.core.events import AlertSeverity, SymbolHalted, Trade
from feelies.core.gate_registry import record_verdict
from feelies.core.state_machine import StateMachine
from feelies.kernel.exception_taxonomy import KernelFault
from feelies.kernel.macro import MacroState

logger = logging.getLogger(__name__)


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


_DATA_TRANSITIONS: dict[DataHealth, frozenset[DataHealth]] = {
    DataHealth.HEALTHY: frozenset(
        {
            DataHealth.GAP_DETECTED,
            DataHealth.HALTED,
            DataHealth.CORRUPTED,
        }
    ),
    DataHealth.GAP_DETECTED: frozenset(
        {
            DataHealth.HEALTHY,  # gap resolved
            DataHealth.HALTED,  # halt declared mid-gap
            DataHealth.CORRUPTED,  # gap unresolvable
        }
    ),
    DataHealth.HALTED: frozenset(
        {
            DataHealth.HEALTHY,  # halt resolved (resume marker)
            DataHealth.CORRUPTED,  # stream corrupted during halt
        }
    ),
    DataHealth.CORRUPTED: frozenset(),  # terminal — restart required
}


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


def _bind_halt_tradeability(
    halt_tradeability: _HaltTradeability | None,
    normalizer: object | None,
) -> _HaltTradeability:
    """Single engine-1 store: the injected one, or the normalizer's, or new."""
    inherited = getattr(normalizer, "_halt_tradeability", None) if normalizer is not None else None
    if halt_tradeability is not None:
        if inherited is not None and inherited is not halt_tradeability:
            raise KernelFault(
                "halt tradeability authority conflict: orchestrator and "
                "normalizer disagree",
                kind=KernelFault.Kind.SESSION_HALT,
            )
        return halt_tradeability
    if isinstance(inherited, _HaltTradeability):
        return inherited
    return _HaltTradeability()


def _configure_halt_from_config(self: Any, cfg: Any) -> None:
    """Copy halt codes and blackout duration from boot config onto the store."""
    authority = _require_halt_authority(self)
    on_codes = frozenset(cfg.halt_on_condition_codes)
    off_codes = frozenset(cfg.halt_off_condition_codes)
    blackout_ns = cfg.halt_resolution_blackout_seconds * 1_000_000_000
    peer_on: frozenset[int] | None = None
    peer_off: frozenset[int] | None = None
    normalizer = getattr(self, "_normalizer", None)
    if normalizer is not None:
        peer = getattr(normalizer, "_halt_tradeability", None)
        if peer is not None and peer is not authority:
            peer_on = peer.on_codes
            peer_off = peer.off_codes
    authority.configure(
        on_codes,
        off_codes,
        blackout_ns,
        peer_on=peer_on,
        peer_off=peer_off,
    )


def _reset_halt_state(self: Any) -> None:
    """Clear halted symbols and blackout deadlines; keep the codebook."""
    _require_halt_authority(self).reset()


def create_data_integrity_machine(
    symbol: str,
    clock: Clock,
    *,
    channel: str | None = None,
) -> StateMachine[DataHealth]:
    """Create a data integrity tracker for a single symbol (and optional channel).

    ``channel`` distinguishes quote vs trade sequence spaces on the same symbol
    so gap / recovery on one feed does not false-clear the other.
    """
    label = f"{symbol}:{channel}" if channel else symbol
    return StateMachine(
        name=f"data_integrity:{label}",
        initial_state=DataHealth.HEALTHY,
        transitions=_DATA_TRANSITIONS,
        clock=clock,
    )


def _update_halt_state(self: Any, trade: Trade) -> None:
    """Register halt and resume edges from the trade tape.

    On halt-on for a symbol not already halted: mark it halted, cancel
    any resting orders (Inv-11), and emit ``SymbolHalted``.  On resume:
    clear the halt, open the entry blackout window, and emit the resume
    ``SymbolHalted``.  Inert when no halt codes are configured.
    """
    _require_halt_authority(self)
    if not self._halt_on_codes and not self._halt_off_codes:
        return
    status = classify_halt_status(
        trade.conditions,
        self._halt_on_codes,
        self._halt_off_codes,
    )
    if status is None:
        return
    symbol = trade.symbol
    if status is HaltSignal.HALT_ON:
        if symbol not in self._halted_symbols:
            self._halted_symbols.add(symbol)
            self._halt_blackout_until_ns.pop(symbol, None)
            self._cancel_resting_for_symbol(symbol, trade.correlation_id)
            _emit_symbol_halted(
                self,
                symbol,
                halted=True,
                reason="LULD_HALT",
                ts=trade.timestamp_ns,
                correlation_id=trade.correlation_id,
                blackout_until_ns=0,
            )
    elif symbol in self._halted_symbols:
        self._halted_symbols.discard(symbol)
        deadline = trade.timestamp_ns + self._halt_blackout_ns
        self._halt_blackout_until_ns[symbol] = deadline
        _emit_symbol_halted(
            self,
            symbol,
            halted=False,
            reason="LULD_RESUME",
            ts=trade.timestamp_ns,
            correlation_id=trade.correlation_id,
            blackout_until_ns=deadline,
        )


def _update_ssr_state(self: Any, trade: Trade) -> None:
    """Activate sticky session SSR state from trade condition codes."""
    if not self._ssr_codes:
        return
    if not (set(trade.conditions) & self._ssr_codes):
        return
    symbol = trade.symbol.upper()
    if symbol in self._ssr_active:
        return
    self._ssr_active.add(symbol)
    self._publish_alert(
        timestamp_ns=trade.timestamp_ns,
        correlation_id=trade.correlation_id,
        severity=AlertSeverity.INFO,
        alert_name="ssr_triggered",
        message=f"SSR became active intraday for {symbol} (Reg-SHO 201).",
        context={"symbol": symbol},
    )


def _data_health_blocks_trading(self: Any, symbol: str, correlation_id: str) -> str | None:
    """Return a fail-safe block reason for the symbol, or None when healthy.

    Corruption degrades the platform; configured gaps do likewise."""
    if self._normalizer is None:
        return None
    health: DataHealth = self._normalizer.health(symbol)
    cfg_syms = (
        {s.upper() for s in self._config.symbols} if self._config is not None else frozenset()
    )
    if self._config is not None and self._config.strict_normalizer_symbol_coverage:
        if symbol.upper() in cfg_syms:
            tracked = {k.upper() for k in self._normalizer.all_health()}
            if symbol.upper() not in tracked:
                if self._macro.can_transition(MacroState.DEGRADED):
                    self._macro.transition(
                        MacroState.DEGRADED,
                        trigger=f"DATA_SYMBOL_UNTRACKED:{symbol}",
                        correlation_id=correlation_id,
                    )
                return "SYMBOL_UNTRACKED"
    if health == DataHealth.CORRUPTED:
        # Force-flatten the affected symbol before transitioning macro.
        # CORRUPTED is terminal — leaving an open position to mark at
        # the last-known quote would carry stale risk through DEGRADED.
        self._force_flatten_symbol_on_degrade(
            symbol,
            correlation_id,
            reason="DATA_CORRUPTED",
        )
        if self._macro.can_transition(MacroState.DEGRADED):
            self._macro.transition(
                MacroState.DEGRADED,
                trigger=f"DATA_CORRUPTED:{symbol}",
                correlation_id=correlation_id,
            )
        return health.name
    if health == DataHealth.HALTED:
        # A recoverable LULD halt blocks the symbol without degrading macro state.
        return health.name
    degrade_gap = self._config is not None and self._config.degrade_on_data_gap
    if degrade_gap and health == DataHealth.GAP_DETECTED:
        # GAP_DETECTED can recover to HEALTHY, but the macro DEGRADED
        # transition is sticky (requires explicit operator command).
        # Unwind the affected symbol at the last-known mark so the
        # book doesn't carry stale exposure through the gap window.
        self._force_flatten_symbol_on_degrade(
            symbol,
            correlation_id,
            reason="DATA_GAP_DETECTED",
        )
        if self._macro.can_transition(MacroState.DEGRADED):
            self._macro.transition(
                MacroState.DEGRADED,
                trigger=f"DATA_GAP_DETECTED:{symbol}",
                correlation_id=correlation_id,
            )
        return health.name
    return None


def _verify_data_integrity(self: Any) -> bool:
    """Verify data integrity for all configured symbols.

    If a normalizer is available, checks that every configured
    symbol is tracked and reports HEALTHY.

    Without a normalizer (cached replay / offline logs), optional
    ``PlatformConfig.require_healthy_disk_cache_manifests`` enforces
    per-day ``ingestion_health`` rows supplied by the ingest/replay path.
    """
    if self._config is None:
        return True

    if self._normalizer is not None:
        health = self._normalizer.all_health()
        for symbol in self._config.symbols:
            if symbol not in health or health[symbol] != DataHealth.HEALTHY:
                return False
        return True

    if self._config.require_healthy_disk_cache_manifests:
        rows = self._config.disk_cache_ingestion_health_rows
        if not rows:
            logger.warning(
                "require_healthy_disk_cache_manifests=True but "
                "disk_cache_ingestion_health_rows is empty — integrity fail"
            )
            return False
        for sym, day, h in rows:
            if h != "HEALTHY":
                logger.warning(
                    "disk cache ingestion_health=%s for %s/%s — integrity fail",
                    h,
                    sym,
                    day,
                )
                return False
    return True


def _emit_symbol_halted(
    self: Any,
    symbol: str,
    *,
    halted: bool,
    reason: str,
    ts: int,
    correlation_id: str,
    blackout_until_ns: int,
) -> None:
    """Publish the forensic ``SymbolHalted`` marker."""
    self._bus.publish(
        SymbolHalted(
            timestamp_ns=ts,
            correlation_id=correlation_id,
            sequence=self._seq.next(),
            source_layer="kernel",
            symbol=symbol,
            halted=halted,
            reason=reason,
            blackout_until_ns=blackout_until_ns,
        )
    )
