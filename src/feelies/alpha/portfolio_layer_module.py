"""Phase-4 ``layer: PORTFOLIO`` alpha module.

A :class:`LoadedPortfolioLayerModule` is the loader-side artifact for a
schema-1.1 ``layer: PORTFOLIO`` alpha.  Its surface mirrors
:class:`feelies.alpha.signal_layer_module.LoadedSignalLayerModule` —
the manifest, an :class:`AlphaModule.evaluate` that always returns
``None`` (post-D.2 PR-2b-ii the per-tick composite signal engine is
deleted; the protocol method survives only as orchestrator
test-scaffolding and PORTFOLIO alphas are wired by
:class:`feelies.composition.engine.CompositionEngine` instead), and a
Phase-4 surface exposing the universe, decision horizon,
mechanism-consumes whitelist, and ``construct`` callable consumed by
the composition engine.

PR-2b-iii (this commit) adds the ``depends_on_signals`` attribute to
the surface (it was parsed from the manifest by the loader but
discarded prior to this PR).  The orchestrator's bus-driven ``Signal``
subscriber (``_on_bus_signal``) reads this list across every
registered PORTFOLIO at boot and uses it to **skip** translating
those upstream SIGNAL alphas' ``Signal`` events into ``OrderRequest``
events — they are aggregated through ``CompositionEngine`` and emerge
as ``SizedPositionIntent`` events instead (PR-2b-iv will translate
intents into orders).  Translating them through both paths would
double-trade (Inv-11: prefer no order over duplicate orders).

The default canonical implementation runs the engine's *default
pipeline* (ranker → neutralizer → matcher → optimizer) with the
alpha's declared parameters.  Custom alphas may override
``construct`` by providing an inline ``construct(ctx, params)`` block
in the YAML; the loader then wraps that callable in a
:class:`_CompiledPortfolioConstructor` adapter to keep call-site
semantics stable.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Callable, Mapping

from feelies.alpha.module import AlphaManifest
from feelies.composition.protocol import CompositionContextError
from feelies.core.events import (
    CrossSectionalContext,
    FeatureVector,
    Signal,
    SizedPositionIntent,
    TrendMechanism,
)
from feelies.features.definition import FeatureDefinition

PortfolioConstructor = Callable[
    [CrossSectionalContext, Mapping[str, Any]], SizedPositionIntent
]

_FAMILY_BY_NAME: dict[str, TrendMechanism] = {m.name: m for m in TrendMechanism}


class LoadedPortfolioLayerModule:
    """Concrete ``AlphaModule`` for a schema-1.1 ``layer: PORTFOLIO`` alpha."""

    __slots__ = (
        "_manifest",
        "_construct",
        "_universe",
        "_horizon_seconds",
        "_consumes_mechanisms",
        "_max_share_of_gross",
        "_factor_neutralization_disclosed",
        "_depends_on_signals",
        "_params",
    )

    def __init__(
        self,
        *,
        manifest: AlphaManifest,
        construct: PortfolioConstructor,
        universe: tuple[str, ...],
        horizon_seconds: int,
        consumes_mechanisms: tuple[TrendMechanism, ...],
        max_share_of_gross: float,
        factor_neutralization_disclosed: bool,
        depends_on_signals: tuple[str, ...],
        params: Mapping[str, Any],
    ) -> None:
        self._manifest = manifest
        self._construct = construct
        self._universe = tuple(sorted(set(universe)))
        self._horizon_seconds = int(horizon_seconds)
        self._consumes_mechanisms = consumes_mechanisms
        self._max_share_of_gross = float(max_share_of_gross)
        self._factor_neutralization_disclosed = bool(
            factor_neutralization_disclosed
        )
        self._depends_on_signals = tuple(depends_on_signals)
        self._params = dict(params)

    # ── AlphaModule protocol ─────────────────────────────────────────

    @property
    def manifest(self) -> AlphaManifest:
        return self._manifest

    def feature_definitions(self) -> Sequence[FeatureDefinition]:
        return ()

    def evaluate(self, features: FeatureVector) -> Signal | None:
        """No-op — PORTFOLIO alphas do not run on the per-tick path."""
        return None

    def validate(self) -> list[str]:
        errors: list[str] = []
        for pdef in self._manifest.parameter_schema:
            value = self._params.get(pdef.name, pdef.default)
            errors.extend(pdef.validate_value(value))
        return errors

    # ── PORTFOLIO-layer surface ──────────────────────────────────────

    @property
    def alpha_id(self) -> str:
        return self._manifest.alpha_id

    @property
    def universe(self) -> tuple[str, ...]:
        return self._universe

    @property
    def horizon_seconds(self) -> int:
        return self._horizon_seconds

    @property
    def consumes_mechanisms(self) -> tuple[TrendMechanism, ...]:
        return self._consumes_mechanisms

    @property
    def max_share_of_gross(self) -> float:
        return self._max_share_of_gross

    @property
    def factor_neutralization_disclosed(self) -> bool:
        return self._factor_neutralization_disclosed

    @property
    def depends_on_signals(self) -> tuple[str, ...]:
        """SIGNAL alpha_ids whose ``Signal`` events feed this PORTFOLIO.

        Consumed by the orchestrator's PR-2b-iii Signal-bus subscriber to
        skip translating these alphas' Signals into ``OrderRequest`` events
        — they are aggregated through ``CompositionEngine`` and emerge as
        ``SizedPositionIntent`` events instead (PR-2b-iv will translate
        intents into orders).  Translating them through both paths would
        double-trade (Inv-11).
        """
        return self._depends_on_signals

    @property
    def params(self) -> Mapping[str, Any]:
        return dict(self._params)

    def construct(
        self,
        ctx: CrossSectionalContext,
        params: Mapping[str, Any],
    ) -> SizedPositionIntent:
        """Forward to the bound constructor (default pipeline or custom)."""
        return self._construct(ctx, params)


# ── PortfolioAlpha adapter for the default pipeline ─────────────────────


class _DefaultPortfolioConstructor:
    """Constructor that delegates to the engine's default pipeline.

    Bound at registration time — the engine instance itself is not
    available at module load, so we hold a *thunk* that the bootstrap
    rebinds once both the engine and the registry are wired.
    """

    __slots__ = ("_engine_thunk", "_strategy_id")

    def __init__(self, *, engine_thunk: Any, strategy_id: str) -> None:
        self._engine_thunk = engine_thunk
        self._strategy_id = strategy_id

    def __call__(
        self,
        ctx: CrossSectionalContext,
        params: Mapping[str, Any],
    ) -> SizedPositionIntent:
        engine = self._engine_thunk()
        if engine is None:  # pragma: no cover - bootstrap bug
            raise CompositionContextError(
                "_DefaultPortfolioConstructor: engine not yet wired"
            )
        intent: SizedPositionIntent = engine.run_default_pipeline(
            ctx, strategy_id=self._strategy_id,
        )
        return intent


# ── PortfolioAlpha adapter for inline YAML construct() ──────────────────


class _CompiledPortfolioConstructor:
    """Adapter wrapping a compiled inline ``construct(ctx, params)``."""

    __slots__ = ("_fn",)

    def __init__(self, *, fn: Any) -> None:
        self._fn = fn

    def __call__(
        self,
        ctx: CrossSectionalContext,
        params: Mapping[str, Any],
    ) -> SizedPositionIntent:
        result = self._fn(ctx, params)
        if not isinstance(result, SizedPositionIntent):
            raise CompositionContextError(
                f"_CompiledPortfolioConstructor: expected "
                f"SizedPositionIntent, got {type(result).__name__}"
            )
        return result


def parse_consumes_mechanisms(
    raw: Any,
) -> tuple[TrendMechanism, ...]:
    """Map a YAML ``trend_mechanism.consumes:`` list to a tuple of enums.

    Empty / missing → empty tuple.  Accepts both list-of-strings and
    list-of-dicts (G16 schema requires dicts with ``family:`` keys for
    PORTFOLIO specs); unknown family names raise :class:`ValueError`.
    """
    if raw is None:
        return ()
    if not isinstance(raw, (list, tuple)):
        raise ValueError(
            f"trend_mechanism.consumes must be a list, got {type(raw).__name__}"
        )
    out: list[TrendMechanism] = []
    for entry in raw:
        if isinstance(entry, dict):
            family = entry.get("family")
        else:
            family = entry
        if family not in _FAMILY_BY_NAME:
            raise ValueError(
                f"trend_mechanism.consumes: unknown family {family!r}; "
                f"allowed: {sorted(_FAMILY_BY_NAME)}"
            )
        out.append(_FAMILY_BY_NAME[family])
    return tuple(out)


__all__ = [
    "LoadedPortfolioLayerModule",
    "_CompiledPortfolioConstructor",
    "_DefaultPortfolioConstructor",
    "parse_consumes_mechanisms",
]
