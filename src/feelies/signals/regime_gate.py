"""Safe expression evaluator and hysteresis latch for regime gates.

The types live in :mod:`feelies.core.regime_gate` so alpha can construct a
gate and compile the DSL without importing the signals package. This
module re-exports them; Engine 4 keeps importing from here.
"""

from __future__ import annotations

from feelies.core.regime_gate import (
    Bindings,
    RegimeGate,
    RegimeGateError,
    UnsafeExpressionError,
    UnknownIdentifierError,
    UnknownRegimeStateError,
    compile_expression,
    evaluate,
)

__all__ = [
    "Bindings",
    "RegimeGate",
    "RegimeGateError",
    "UnsafeExpressionError",
    "UnknownIdentifierError",
    "UnknownRegimeStateError",
    "compile_expression",
    "evaluate",
]
