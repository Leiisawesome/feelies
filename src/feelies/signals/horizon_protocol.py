"""Layer-2 horizon signal contract.

The Protocol lives in :mod:`feelies.core.horizon_protocol` so alpha can
name it without importing the signals package. This module re-exports it;
Engine 4 implementations keep importing from here.
"""

from __future__ import annotations

from feelies.core.horizon_protocol import HorizonSignal

__all__ = ["HorizonSignal"]
