"""Composite engines — multi-alpha behind single FeatureEngine/SignalEngine.

These implementations sit behind the existing Protocol interfaces so the
orchestrator requires no changes.  The CompositeFeatureEngine aggregates
feature definitions from all registered alphas and computes them in
dependency order.  The CompositeSignalEngine fans out evaluation to each
active alpha and applies signal arbitration.

Invariants preserved:
  - Inv 5 (deterministic replay): computation order is deterministic
    (topological sort with stable tie-breaking by feature_id).
  - Inv 8 (layer separation): these are FeatureEngine/SignalEngine
    implementations — no kernel or execution layer knowledge.
  - Inv 11 (fail-safe): alpha evaluation errors are caught and
    suppressed (no signal = no order = safe).
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from feelies.alpha.arbitration import EdgeWeightedArbitrator, SignalArbitrator
from feelies.alpha.registry import AlphaRegistry
from feelies.core.clock import Clock
from feelies.core.events import FeatureVector, NBBOQuote, Signal, SignalDirection, Trade
from feelies.features.definition import FeatureDefinition

logger = logging.getLogger(__name__)


# ── Composite Feature Engine ────────────────────────────────────────


class CompositeFeatureEngine:
    """Aggregates feature definitions from all registered alphas.

    Implements the ``FeatureEngine`` protocol: the orchestrator calls
    ``update(quote)`` and receives a single ``FeatureVector`` containing
    all computed feature values.

    Features are computed in topological dependency order.  Per-symbol
    state is maintained internally for each registered feature.
    """

    def __init__(
        self,
        registry: AlphaRegistry,
        clock: Clock,
    ) -> None:
        self._clock = clock
        self._definitions: list[FeatureDefinition] = []
        self._computation_order: list[str] = []
        self._version_hash: str = ""

        self._per_symbol_state: dict[str, dict[str, dict[str, Any]]] = {}
        self._per_symbol_event_count: dict[str, int] = {}
        self._per_symbol_first_ns: dict[str, int] = {}
        self._per_symbol_last_ns: dict[str, int] = {}
        self._last_values: dict[str, dict[str, float]] = {}

        self._rebuild(registry)

    def _rebuild(self, registry: AlphaRegistry) -> None:
        """Ingest feature definitions from the registry and resolve order."""
        defs = registry.feature_definitions()
        self._definitions = list(defs)

        by_id: dict[str, FeatureDefinition] = {
            d.feature_id: d for d in self._definitions
        }
        self._computation_order = _topological_sort(by_id)

        version_parts = sorted(
            f"{d.feature_id}:{d.version}" for d in self._definitions
        )
        raw = "|".join(version_parts)
        self._version_hash = hashlib.sha256(raw.encode()).hexdigest()[:16]

        self._def_by_id = by_id

    # ── FeatureEngine protocol ───────────────────────────────────

    def update(self, quote: NBBOQuote) -> FeatureVector:
        """Compute all registered features for the given quote.

        Features are evaluated in topological order so that derived
        features can read upstream values from the same tick.
        """
        symbol = quote.symbol
        symbol_state = self._per_symbol_state.setdefault(symbol, {})
        event_count = self._per_symbol_event_count.get(symbol, 0) + 1
        self._per_symbol_event_count[symbol] = event_count

        if symbol not in self._per_symbol_first_ns:
            self._per_symbol_first_ns[symbol] = quote.timestamp_ns
        self._per_symbol_last_ns[symbol] = quote.timestamp_ns

        values: dict[str, float] = {}

        for fid in self._computation_order:
            fdef = self._def_by_id[fid]
            if fid not in symbol_state:
                symbol_state[fid] = fdef.compute.initial_state()

            value = fdef.compute.update(quote, symbol_state[fid])
            values[fid] = value

        self._last_values[symbol] = values
        warm = self._is_warm_for_symbol(symbol)

        return FeatureVector(
            timestamp_ns=quote.timestamp_ns,
            correlation_id=quote.correlation_id,
            sequence=quote.sequence,
            symbol=symbol,
            feature_version=self._version_hash,
            values=values,
            warm=warm,
            event_count=event_count,
        )

    def is_warm(self, symbol: str) -> bool:
        """Whether ALL features have sufficient history for this symbol."""
        return self._is_warm_for_symbol(symbol)

    def reset(self, symbol: str) -> None:
        """Clear all feature state for a symbol."""
        self._per_symbol_state.pop(symbol, None)
        self._per_symbol_event_count.pop(symbol, None)
        self._per_symbol_first_ns.pop(symbol, None)
        self._per_symbol_last_ns.pop(symbol, None)
        self._last_values.pop(symbol, None)

    @property
    def version(self) -> str:
        """Composite hash of all registered feature versions."""
        return self._version_hash

    def checkpoint(self, symbol: str) -> tuple[bytes, int]:
        """Serialize per-symbol state for all features.

        Returns (state_bytes, event_count).  State is JSON-encoded
        for simplicity; a production system would use a more compact
        binary format.
        """
        state = self._per_symbol_state.get(symbol, {})
        event_count = self._per_symbol_event_count.get(symbol, 0)
        payload = {
            "feature_state": state,
            "event_count": event_count,
            "first_ns": self._per_symbol_first_ns.get(symbol, 0),
            "last_ns": self._per_symbol_last_ns.get(symbol, 0),
        }
        return json.dumps(payload, default=str).encode(), event_count

    def restore(self, symbol: str, state: bytes) -> None:
        """Restore per-symbol state from a checkpoint.

        Raises ``ValueError`` if the blob is corrupt or unparseable.
        """
        try:
            payload = json.loads(state.decode())
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError(f"Corrupt checkpoint for {symbol}") from exc

        if "feature_state" not in payload:
            raise ValueError(f"Missing feature_state in checkpoint for {symbol}")

        self._per_symbol_state[symbol] = payload["feature_state"]
        self._per_symbol_event_count[symbol] = payload.get("event_count", 0)
        self._per_symbol_first_ns[symbol] = payload.get("first_ns", 0)
        self._per_symbol_last_ns[symbol] = payload.get("last_ns", 0)

    # ── Trade event processing ──────────────────────────────────

    def process_trade(self, trade: Trade) -> FeatureVector | None:
        """Update features that consume trade events.

        Calls ``update_trade()`` on each feature computation.  Features
        that do not implement trade processing return ``None`` and their
        values are carried forward from the last quote update.

        Returns a new ``FeatureVector`` only if at least one feature
        produced an updated value; otherwise returns ``None`` (no
        downstream signal evaluation needed).
        """
        symbol = trade.symbol
        symbol_state = self._per_symbol_state.get(symbol)
        if symbol_state is None:
            return None

        self._per_symbol_last_ns[symbol] = trade.timestamp_ns

        last_values = self._last_values.get(symbol, {})
        updated = False
        values = dict(last_values)

        for fid in self._computation_order:
            fdef = self._def_by_id[fid]
            if fid not in symbol_state:
                continue

            update_trade_fn = getattr(fdef.compute, "update_trade", None)
            if update_trade_fn is None:
                continue
            result = update_trade_fn(trade, symbol_state[fid])
            if result is not None:
                values[fid] = result
                updated = True

        if not updated:
            return None

        event_count = self._per_symbol_event_count.get(symbol, 0)
        warm = self._is_warm_for_symbol(symbol)

        return FeatureVector(
            timestamp_ns=trade.timestamp_ns,
            correlation_id=trade.correlation_id,
            sequence=trade.sequence,
            symbol=symbol,
            feature_version=self._version_hash,
            values=values,
            warm=warm,
            event_count=event_count,
        )

    # ── Internal ─────────────────────────────────────────────────

    def _is_warm_for_symbol(self, symbol: str) -> bool:
        """Check whether all features meet their warm-up requirements.

        Uses the last event timestamp for this symbol (not the clock)
        so the check is causally correct regardless of call-site timing.
        """
        event_count = self._per_symbol_event_count.get(symbol, 0)
        first_ns = self._per_symbol_first_ns.get(symbol, 0)
        last_ns = self._per_symbol_last_ns.get(symbol, 0)
        elapsed_ns = last_ns - first_ns if first_ns > 0 else 0

        for fdef in self._definitions:
            if event_count < fdef.warm_up.min_events:
                return False
            if elapsed_ns < fdef.warm_up.min_duration_ns:
                return False

        return len(self._definitions) > 0


# ── Composite Signal Engine ─────────────────────────────────────────


class CompositeSignalEngine:
    """Fans out signal evaluation to all registered alphas.

    Implements the ``SignalEngine`` protocol: the orchestrator calls
    ``evaluate(features)`` and receives a single ``Signal | None``.
    Internally, each active alpha evaluates the features independently.
    When multiple alphas produce signals, the arbitrator selects a
    winner.

    Fail-safe (invariant 11): if an alpha's evaluate() raises an
    exception, the error is logged and that alpha is skipped for this
    tick.  No signal = no order = safe.
    """

    def __init__(
        self,
        registry: AlphaRegistry,
        arbitrator: SignalArbitrator | None = None,
    ) -> None:
        self._registry = registry
        self._arbitrator: SignalArbitrator = (
            arbitrator if arbitrator is not None
            else EdgeWeightedArbitrator()
        )

    def evaluate(self, features: FeatureVector) -> Signal | None:
        """Evaluate all active alphas and arbitrate the result.

        Warm/stale gate (Inv-11, feature-engine and microstructure-alpha
        skill contracts):
          - ``warm=False``: suppress all signals (features unreliable)
          - ``stale=True``: suppress entry signals; only FLAT (exit)
            signals pass through (conservative)

        Each alpha is called independently.  Errors in individual
        alphas do not propagate — they are logged and the alpha is
        skipped for this tick.
        """
        if not features.warm:
            return None

        signals: list[Signal] = []
        symbol = features.symbol

        for alpha in self._registry.active_alphas():
            manifest = alpha.manifest

            if manifest.symbols is not None and symbol not in manifest.symbols:
                continue

            try:
                signal = alpha.evaluate(features)
            except Exception:
                logger.exception(
                    "Alpha '%s' raised during evaluate() for %s — skipping",
                    manifest.alpha_id,
                    symbol,
                )
                continue

            if signal is not None:
                signals.append(signal)

        if features.stale:
            signals = [s for s in signals if s.direction == SignalDirection.FLAT]

        if not signals:
            return None

        if len(signals) == 1:
            return signals[0]

        return self._arbitrator.arbitrate(signals)


# ── Topological sort ─────────────────────────────────────────────────


def _topological_sort(
    defs_by_id: dict[str, FeatureDefinition],
) -> list[str]:
    """Stable topological sort of features by dependency.

    Tie-breaking: alphabetical by feature_id for determinism.

    Raises ``ValueError`` if a circular dependency is detected.
    """
    in_degree: dict[str, int] = {fid: 0 for fid in defs_by_id}
    for fid, fdef in defs_by_id.items():
        for dep in fdef.depends_on:
            if dep in defs_by_id:
                in_degree[fid] += 1

    queue = sorted(
        fid for fid, deg in in_degree.items() if deg == 0
    )
    result: list[str] = []

    while queue:
        node = queue.pop(0)
        result.append(node)

        for fid, fdef in defs_by_id.items():
            if node in fdef.depends_on:
                in_degree[fid] -= 1
                if in_degree[fid] == 0:
                    queue.append(fid)
                    queue.sort()

    if len(result) != len(defs_by_id):
        missing = set(defs_by_id.keys()) - set(result)
        raise ValueError(
            f"Circular dependency detected among features: {sorted(missing)}"
        )

    return result
