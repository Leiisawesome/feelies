"""Determinism / parity tests.

Tests in this package validate platform-level determinism guarantees
that cut across layers — most importantly the Level-1 trade-sequence
parity hash and the Level-2/3/4/5/6 layer-replay parity hashes mandated
by §11.1 of ``docs/three_layer_architecture.md``.

Locked baselines are registered in :mod:`tests.determinism.parity_manifest`
and checked by :mod:`tests.determinism.test_parity_manifest`. Re-baseline
with ``scripts/rebaseline_parity_hashes.py``.
"""
