"""Aggressive-fill constants shared by both routers.

Currently exports the canonical ``STOP_EXIT_REASONS`` set consumed by
``market_fill.append_market_fill_acks`` so panic-slippage classification
stays bit-identical across the backtest and passive-limit fill paths.
"""

from __future__ import annotations


STOP_EXIT_REASONS: frozenset[str] = frozenset(
    {
        "STOP_EXIT",
        "HARD_EXIT_AGE",
        "HAZARD_SPIKE",
        "FORCE_FLATTEN",
    }
)


__all__ = ["STOP_EXIT_REASONS"]
