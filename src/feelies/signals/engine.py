"""Signal engine protocol — pure functions from features to signals.

Signal evaluation has NO side effects.  Given identical FeatureVector
inputs, must produce identical Signal outputs (invariant 5).
No internal mutable state, no I/O, no dependency on wall-clock time.
"""

from __future__ import annotations

from typing import Protocol

from feelies.core.events import FeatureVector, Signal


class SignalEngine(Protocol):
    """Evaluates features into trading signals.

    Must be a pure function: deterministic, no side effects,
    no state mutation, no I/O.
    """

    def evaluate(self, features: FeatureVector) -> Signal:
        """Compute signal from feature vector."""
        ...
