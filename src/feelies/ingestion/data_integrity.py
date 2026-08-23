"""Per-symbol data integrity state machine (Section VII of the system diagram).

Each symbol stream maintains its own health state.
If CORRUPTED during PAPER_TRADING_MODE, the global macro state
transitions to DEGRADED — execution stops.
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import Enum, auto
from typing import Any

from feelies.core.clock import Clock
from feelies.core.events import Trade
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
            self._emit_symbol_halted(
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
        self._emit_symbol_halted(
            symbol,
            halted=False,
            reason="LULD_RESUME",
            ts=trade.timestamp_ns,
            correlation_id=trade.correlation_id,
            blackout_until_ns=deadline,
        )
