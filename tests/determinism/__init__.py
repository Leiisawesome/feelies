"""Determinism / parity tests.

Tests in this package validate platform-level determinism guarantees
that cut across layers — most importantly the Level-1 trade-sequence
parity hash and the Level-2/3/4/5/6 layer-replay parity hashes mandated
by §11.1 of ``docs/three_layer_architecture.md``.

Locked baselines are registered in :mod:`tests.determinism.parity_manifest`
and checked by :mod:`tests.determinism.test_parity_manifest`. Re-baseline
with ``scripts/rebaseline_parity_hashes.py``.

Stage-0 dual-permission decoupling (design rev 5) introduced a SIGNAL→RISK
event-stream migration: promoting an alpha to ``decouple_caps_only`` moves its
gate-close FLAT off the SIGNAL ``Signal`` stream onto a typed
``SafetyStateChange`` that a RISK-layer author converts into a flatten
``OrderRequest``. The two new cross-layer baselines
(``decoupled_safety_state_change``, ``decoupled_risk_flatten_order``) and the
migration proof live in :mod:`tests.determinism.test_decoupled_safety_replay`;
non-promoted alphas stay bit-identical, so no pre-existing baseline moved.
"""
