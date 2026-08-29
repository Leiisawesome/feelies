"""Kernel-owned decision-path exception taxonomy.

Remaining fail-quiet handlers have nothing typed to fail into (G36).
This module is that type. S-30a raises and catches ``TICK_PIPELINE`` on
the tick path. S-30b–S-30f raise the other ``Kind`` members; this step
does not. Inv-11: fail into reduced exposure, never increased.
"""

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
