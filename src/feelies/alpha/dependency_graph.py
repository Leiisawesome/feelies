"""Static feature-dependency graph for SIGNAL alphas.

Alpha Governance owns the question "which Layer-2 features does this alpha
actually consume, and which must be warm before it may enter?".  Answering it
means parsing the compiled ``signal:`` body — static analysis of alpha source, a
governance concern that had no business living in the composition root.

The conservative direction matters throughout: whenever the consumed set cannot
be resolved statically, every function here widens to *all* features of every
depended sensor.  A wider warm-set suppresses entries; a narrower one would let
an alpha trade on a cold feature (Inv-11).
"""

from __future__ import annotations

import ast
import logging
from collections.abc import Sequence
from dataclasses import replace

from feelies.alpha.registry import AlphaRegistry
from feelies.core.platform_config import PlatformConfig
from feelies.core.errors import ConfigurationError
from feelies.features.protocol import HorizonFeature
from feelies.signals.regime_gate import RegimeGate

logger = logging.getLogger(__name__)


def feature_ids_for_sensor_at_horizon(
    sensor_id: str,
    horizon_seconds: int,
    horizon_features: Sequence[HorizonFeature],
) -> frozenset[str]:
    """Layer-2 ``feature_id`` keys at one horizon driven by a sensor."""
    out: set[str] = set()
    for f in horizon_features:
        if f.horizon_seconds != horizon_seconds:
            continue
        if sensor_id in f.input_sensor_ids:
            out.add(f.feature_id)
    return frozenset(out)


def consumed_value_keys_from_signal_source(source: str | None) -> frozenset[str] | None:
    """Statically extract the ``snapshot.values`` keys a signal body reads.

    ``required_warm`` gates only features the alpha actually consumes. We
    parse the compiled ``signal:`` source and collect the string-literal keys
    used in ``snapshot.values.get("…")`` and ``snapshot.values["…"]``.

    Returns:

    - ``frozenset[str]`` of literal keys when **every** ``.values`` access in
      the body is a recognised literal get/subscript (so the consumed set is
      fully known), **or**
    - ``None`` when the source is absent, unparseable, or contains any
      ``.values`` access we cannot resolve to a string literal (a dynamic key,
      ``.values.items()``, an aliased ``v = snapshot.values``, …).  ``None`` is
      the conservative signal: the caller requires every feature of every
      depended sensor.
    """
    if not source:
        return None
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

    keys: set[str] = set()
    recognised: set[int] = set()  # id() of ``X.values`` Attribute nodes resolved

    for node in ast.walk(tree):
        # snapshot.values.get("KEY"[, default])
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and isinstance(node.func.value, ast.Attribute)
            and node.func.value.attr == "values"
        ):
            recognised.add(id(node.func.value))
            if (
                node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                keys.add(node.args[0].value)
            else:
                return None  # dynamic key — cannot determine the consumed set
        # snapshot.values["KEY"]
        elif (
            isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Attribute)
            and node.value.attr == "values"
        ):
            recognised.add(id(node.value))
            sl = node.slice
            if isinstance(sl, ast.Constant) and isinstance(sl.value, str):
                keys.add(sl.value)
            else:
                return None  # dynamic subscript key

    # Any ``.values`` access that was not one of the recognised literal forms
    # (e.g. ``snapshot.values.items()``, ``v = snapshot.values``) means we
    # cannot be sure we captured every consumed key → fall back conservatively.
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and node.attr == "values"
            and id(node) not in recognised
        ):
            return None

    return frozenset(keys)


def required_warm_feature_ids_for_signal_alpha(
    *,
    depends_on_sensors: Sequence[str],
    horizon_seconds: int,
    horizon_features: Sequence[HorizonFeature],
    gate: RegimeGate,
    signal_source: str | None = None,
) -> frozenset[str]:
    """Snapshot ``warm`` / ``stale`` keys an alpha must satisfy to enter.

    When ``snapshot.values`` keys can be determined statically, gate only on
    those keys intersected with
    the features registered at this horizon).  This stops an alpha from being
    suppressed on a feature it never reads — e.g. an auxiliary ``*_zscore`` /
    ``*_integrated`` view added to a sensor it depends on.  When the body's
    feature access cannot be resolved (``signal_source is None`` or it contains
    a dynamic ``.values`` access), fall back to the conservative set
    (every feature of every depended sensor).  Either way the regime-gate
    identifiers are added, since the gate must also resolve from warm features.
    """
    req: set[str] = set()

    consumed = consumed_value_keys_from_signal_source(signal_source)
    if consumed is None:
        # Conservative fallback: every feature of every depended sensor.
        for sid in sorted(depends_on_sensors):
            req.update(
                feature_ids_for_sensor_at_horizon(sid, horizon_seconds, horizon_features),
            )
    else:
        # Consume-driven: only the feature_ids the body reads that a feature
        # actually produces at this horizon.  (The engine additionally filters
        # by presence in ``snapshot.warm``, so a consumed key with no producing
        # feature is harmless either way; intersecting keeps the set auditable.)
        available = {
            f.feature_id for f in horizon_features if f.horizon_seconds == horizon_seconds
        }
        req.update(k for k in consumed if k in available)

    available = {f.feature_id for f in horizon_features if f.horizon_seconds == horizon_seconds}
    for name in sorted(gate.binding_identifier_names()):
        if name.endswith("_percentile") or name.endswith("_zscore"):
            req.add(name)
            continue
        if name in available:
            req.add(name)
            continue
        req.update(
            feature_ids_for_sensor_at_horizon(name, horizon_seconds, horizon_features),
        )
    return frozenset(req)


def warn_unread_sensor_dependencies(
    *,
    alpha_id: str,
    depends_on_sensors: Sequence[str],
    horizon_seconds: int,
    horizon_features: Sequence[HorizonFeature],
    warm_ids: frozenset[str],
) -> None:
    """Warn when a declared sensor dependency is never actually read.

    G16 only checks that ``l1_signature_sensors`` is a subset of
    ``depends_on_sensors``. It cannot detect a declared sensor whose features
    are never referenced by ``evaluate()`` or the regime gate. ``warm_ids``
    holds the union of every feature the body's statically-resolved
    ``snapshot.values`` accesses and the regime gate's bound identifiers
    require, so a declared sensor whose *entire* horizon feature set is
    disjoint from it contributes nothing to this alpha's actual behaviour.

    A sensor producing zero features at this horizon is not flagged — there
    is nothing to compare against, and that gap is already covered by the
    H3/M2 "uncovered dependency" check above. When the signal body's
    ``.values`` access could not be resolved statically, 2P-1's conservative
    fallback already seeds ``warm_ids`` with every feature of every declared
    sensor, so this check cannot produce a false positive in that case — it
    just loses sensitivity, matching 2P-1's own conservative philosophy.
    """
    for sid in depends_on_sensors:
        produced = feature_ids_for_sensor_at_horizon(sid, horizon_seconds, horizon_features)
        if produced and produced.isdisjoint(warm_ids):
            logger.warning(
                "sensor_audit_2026-07-02 P1: alpha %r declares "
                "depends_on_sensors entry %r, but none of the feature(s) it "
                "produces at horizon %ds (%s) are read by evaluate() or the "
                "regime gate — this looks like a cosmetic/unused dependency. "
                "Either wire evaluate()/the gate to read one of these "
                "features, or drop %r from depends_on_sensors (and from "
                "trend_mechanism.l1_signature_sensors if declared there as a "
                "G16 fingerprint).",
                alpha_id,
                sid,
                horizon_seconds,
                sorted(produced),
                sid,
            )


def consumed_features_for_signal_registration(
    *,
    declared_consumed_features: Sequence[str],
    required_warm_feature_ids: frozenset[str],
) -> tuple[str, ...]:
    """Feature identifiers to stamp on bootstrapped SIGNAL emissions.

    Loader-era ``consumed_features`` historically mirrors
    ``depends_on_sensors``.  At bootstrap time we know the exact warm feature
    set used by the signal body and regime gate, so prefer that feature-level
    provenance.  If no horizon features are available, preserve the declared
    identifiers as a compatibility fallback.
    """

    if required_warm_feature_ids:
        return tuple(sorted(required_warm_feature_ids))
    return tuple(declared_consumed_features)


def maybe_prune_unused_sensors(
    config: PlatformConfig,
    registry: AlphaRegistry,
) -> PlatformConfig:
    """Drop sensor specs not required by loaded SIGNAL alphas.

    When ``prune_unused_sensors`` is True (or ``None`` in BACKTEST mode),
    intersect ``config.sensor_specs`` with the union of every SIGNAL
    alpha's ``depends_on_sensors``.  Missing required sensors fail closed.
    Spec order is preserved (topological registration order).
    """
    # Opt-in only.  Research configs (e.g. bt_sig_benign_midcap) set
    # ``prune_unused_sensors: true``; leaving the default ``None``/False
    # preserves locked Inv-5 baselines that register the full reference
    # sensor stack under BACKTEST.
    prune = bool(config.prune_unused_sensors)
    if not prune or not config.sensor_specs:
        return config

    required: set[str] = set()
    for alpha in registry.signal_alphas():
        required.update(getattr(alpha, "depends_on_sensors", ()))
    if not required:
        # No SIGNAL alphas declare sensor deps — leave the stack intact
        # (PORTFOLIO-only / observational configs still need sensors).
        return config

    available = {spec.sensor_id for spec in config.sensor_specs}
    missing = sorted(required - available)
    if missing:
        raise ConfigurationError(
            "prune_unused_sensors: loaded SIGNAL alphas require sensors "
            f"{missing} that are not present in platform sensor_specs"
        )

    pruned = tuple(spec for spec in config.sensor_specs if spec.sensor_id in required)
    logger.info(
        "prune_unused_sensors: %d → %d specs (kept %s)",
        len(config.sensor_specs),
        len(pruned),
        sorted(required),
    )
    return replace(config, sensor_specs=pruned)


__all__ = [
    "consumed_features_for_signal_registration",
    "consumed_value_keys_from_signal_source",
    "feature_ids_for_sensor_at_horizon",
    "maybe_prune_unused_sensors",
    "required_warm_feature_ids_for_signal_alpha",
    "warn_unread_sensor_dependencies",
]
