"""Position store interface — shared across backtest and live (invariant 9).

This is the PositionStore interface defined by the system-architect skill.
Mode-specific implementations (broker-backed live, simulated backtest)
live behind ExecutionBackend.

PnL decomposition and attribution: risk-engine skill.
Capital allocation and risk budgets: risk-engine (portfolio governor).

The dataclass and Protocol live in :mod:`feelies.core.position` so execution
can name them without importing the portfolio package.  This module re-exports
them; Engine 7 implementations keep importing from here.
"""

from __future__ import annotations

from feelies.core.position import Position, PositionStore

__all__ = ["Position", "PositionStore"]
