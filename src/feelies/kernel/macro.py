"""Global stack state machine (Section I–II of the system diagram).

The entire system exists in one and only one of these macro states
at any time.  States are mutually exclusive and deterministic.
Transitions are event-triggered and logged.  No silent transitions.

SHUTDOWN is terminal — no outbound edges.
"""

from __future__ import annotations

from enum import Enum, auto

from feelies.core.clock import Clock
from feelies.core.state_machine import StateMachine


class MacroState(Enum):
    """System-wide macro states.  Exactly one active at any time."""

    INIT = auto()
    DATA_SYNC = auto()
    READY = auto()
    RESEARCH_MODE = auto()
    BACKTEST_MODE = auto()
    PAPER_TRADING_MODE = auto()
    LIVE_TRADING_MODE = auto()
    DEGRADED = auto()
    RISK_LOCKDOWN = auto()
    SHUTDOWN = auto()


_MACRO_TRANSITIONS: dict[MacroState, frozenset[MacroState]] = {
    # ── INIT ────────────────────────────────────────────────────
    MacroState.INIT: frozenset({
        MacroState.DATA_SYNC,   # configuration loaded successfully
        MacroState.SHUTDOWN,    # configuration failure
    }),
    # ── DATA_SYNC ───────────────────────────────────────────────
    MacroState.DATA_SYNC: frozenset({
        MacroState.READY,       # historical data integrity verified
        MacroState.DEGRADED,    # data gap / schema violation
    }),
    # ── READY (hub state — dispatches to operational modes) ─────
    MacroState.READY: frozenset({
        MacroState.RESEARCH_MODE,       # CMD_RESEARCH
        MacroState.BACKTEST_MODE,       # CMD_BACKTEST
        MacroState.PAPER_TRADING_MODE,  # CMD_PAPER_DEPLOY
        MacroState.LIVE_TRADING_MODE,   # CMD_LIVE_DEPLOY
        MacroState.SHUTDOWN,            # CMD_SHUTDOWN
    }),
    # ── Operational modes ───────────────────────────────────────
    MacroState.RESEARCH_MODE: frozenset({
        MacroState.READY,       # JOB_COMPLETE
        MacroState.DEGRADED,    # CRITICAL_ERROR
    }),
    MacroState.BACKTEST_MODE: frozenset({
        MacroState.READY,       # reproducibility verified
        MacroState.DEGRADED,    # integrity violation
    }),
    MacroState.PAPER_TRADING_MODE: frozenset({
        MacroState.READY,       # performance validation / manual halt
        MacroState.RISK_LOCKDOWN,  # risk breach
        MacroState.DEGRADED,    # execution drift anomaly
    }),
    MacroState.LIVE_TRADING_MODE: frozenset({
        MacroState.READY,       # manual halt
        MacroState.RISK_LOCKDOWN,  # risk breach
        MacroState.DEGRADED,    # data drift
    }),
    # ── Recovery / terminal states ──────────────────────────────
    MacroState.DEGRADED: frozenset({
        MacroState.READY,       # recovery validation passed
        MacroState.SHUTDOWN,    # critical failure
    }),
    MacroState.RISK_LOCKDOWN: frozenset({
        MacroState.READY,       # forced flatten + audit pass (human authorized)
    }),
    MacroState.SHUTDOWN: frozenset(),  # terminal — no outbound edges
}

# States in which the micro-state tick pipeline runs
TRADING_MODES: frozenset[MacroState] = frozenset({
    MacroState.BACKTEST_MODE,
    MacroState.PAPER_TRADING_MODE,
    MacroState.LIVE_TRADING_MODE,
})


def create_macro_state_machine(clock: Clock) -> StateMachine[MacroState]:
    """Create the global stack state machine, starting in INIT."""
    return StateMachine(
        name="global_stack",
        initial_state=MacroState.INIT,
        transitions=_MACRO_TRANSITIONS,
        clock=clock,
    )
