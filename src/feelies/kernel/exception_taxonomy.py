"""Kernel-owned decision-path exception taxonomy.

Remaining fail-quiet handlers have nothing typed to fail into (G36).
This module is that type. S-30a raises and catches ``TICK_PIPELINE`` on
the tick path. S-30b–S-30f raise the other ``Kind`` members; this step
does not. Inv-11: fail into reduced exposure, never increased.
"""

from __future__ import annotations

from feelies.core.exception_taxonomy import KernelFault as KernelFault
