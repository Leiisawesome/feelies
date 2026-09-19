"""RegimeEngine / RegimeHazardDetector — injected regime protocols.

The Protocols and Shannon-entropy helper live in core so kernel can
name them without importing the services package.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Protocol

from feelies.core.events import NBBOQuote, RegimeHazardSpike, RegimeState


class RegimeEngine(Protocol):
    """Injected regime filter. Kernel names restore, posterior, state_names, checkpoint."""

    @property
    def state_names(self) -> Sequence[str]:
        """Human-readable names for each regime state."""
        ...

    def posterior(self, quote: NBBOQuote) -> list[float]:
        """Update state and return posterior probabilities for the quote's symbol."""
        ...

    def checkpoint(self) -> bytes:
        """Serialize per-symbol state to an opaque blob."""
        ...

    def restore(self, data: bytes) -> None:
        """Restore internal state from a blob produced by ``checkpoint()``."""
        ...


class RegimeHazardDetector(Protocol):
    """Injected hazard detector. Kernel names reset and detect."""

    def reset(self) -> None:
        """Clear suppression state at a session boundary."""
        ...

    def detect(
        self,
        prev: RegimeState | None,
        curr: RegimeState,
    ) -> RegimeHazardSpike | None:
        """Return a hazard spike description, or ``None``."""
        ...


def regime_posterior_entropy_nats(posteriors: Sequence[float]) -> float:
    """Shannon entropy (nats) of a categorical posterior ``p``.

    Non-finite and negative components are treated as zero mass, then
    the vector is renormalized to a simplex before computing ``H``.
    ``0`` is returned when there is no positive mass (degenerate /
    empty input).  A peaked distribution has entropy near ``0``; a
    diffuse distribution has higher entropy.
    """
    cleaned: list[float] = []
    for p in posteriors:
        x = float(p)
        if math.isnan(x) or math.isinf(x):
            cleaned.append(0.0)
        else:
            cleaned.append(max(0.0, x))
    total = sum(cleaned)
    if total <= 0.0:
        return 0.0
    h = 0.0
    for p in cleaned:
        q = p / total
        if q > 0.0:
            h -= q * math.log(q)
    return h
