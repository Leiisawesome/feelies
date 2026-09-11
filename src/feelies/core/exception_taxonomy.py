"""Decision-path exception taxonomy."""

from __future__ import annotations

from enum import Enum
from typing import ClassVar

from feelies.core.errors import FailureMode, FeeliesError


class KernelFault(FeeliesError):
    """Decision-path fault the kernel contains or degrades on.

    ``kind`` names the authority that failed. Construct with a ``Kind``
    member; do not subclass for each §F item.
    """

    class Kind(Enum):
        TICK_PIPELINE = "tick_pipeline"
        SESSION_HALT = "session_halt"
        UNIVERSE = "universe"
        HORIZON_GRID = "horizon_grid"
        INGRESS_ADMIT = "ingress_admit"
        SYMBOL_IDENTITY = "symbol_identity"

    failure_mode: ClassVar[FailureMode] = FailureMode.DEGRADE

    def __init__(self, message: str, *, kind: Kind) -> None:
        super().__init__(message)
        self.kind = kind
