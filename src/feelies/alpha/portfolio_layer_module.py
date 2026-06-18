"""Phase-4 ``layer: PORTFOLIO`` alpha module.

A :class:`LoadedPortfolioLayerModule` is the loader-side artifact for a
schema-1.1 ``layer: PORTFOLIO`` alpha.  Its surface mirrors
:class:`feelies.alpha.signal_layer_module.LoadedSignalLayerModule` —
the manifest plus a Phase-4 surface exposing the universe, decision
horizon, mechanism-consumes whitelist, and ``construct`` callable
consumed by :class:`feelies.composition.engine.CompositionEngine`.

PR-2b-iv removed the legacy ``AlphaModule.evaluate`` method from the
protocol entirely (it had degraded to a no-op shim after PR-2b-ii
deleted the composite signal engine).  PORTFOLIO alphas now drive
order flow exclusively via the bus-driven path:
``CompositionEngine`` aggregates the upstream SIGNAL alphas they
declare in ``depends_on_signals``, emits a ``SizedPositionIntent``
for each tick, and ``Orchestrator._on_bus_sized_intent`` translates
that intent into per-leg ``OrderRequest`` events through
``RiskEngine.check_sized_intent``.

PR-2b-iii first added ``depends_on_signals`` to the surface (it was
parsed from the manifest by the loader but discarded earlier).  The
orchestrator's ``_on_bus_signal`` subscriber reads this list across
every registered PORTFOLIO at boot and uses it to **skip** translating
those upstream SIGNAL alphas' ``Signal`` events into ``OrderRequest``
events directly — they would otherwise be double-traded (Inv-11:
prefer no order over duplicate orders).

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
    SizedPositionIntent,
    TrendMechanism,
)
from feelies.features.definition import FeatureDefinition

PortfolioConstructor = Callable[[CrossSectionalContext, Mapping[str, Any]], SizedPositionIntent]

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
        "_mechanism_caps",
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
        mechanism_caps: Mapping[TrendMechanism, float] | None = None,
    ) -> None:
        self._manifest = manifest
        self._construct = construct
        self._universe = tuple(sorted(set(universe)))
        self._horizon_seconds = int(horizon_seconds)
        self._consumes_mechanisms = consumes_mechanisms
        self._max_share_of_gross = float(max_share_of_gross)
        self._mechanism_caps: dict[TrendMechanism, float] = dict(mechanism_caps or {})
        self._factor_neutralization_disclosed = bool(factor_neutralization_disclosed)
        self._depends_on_signals = tuple(depends_on_signals)
        self._params = dict(params)

    # ── AlphaModule protocol ─────────────────────────────────────────

    @property
    def manifest(self) -> AlphaManifest:
        return self._manifest

    def feature_definitions(self) -> Sequence[FeatureDefinition]:
        return ()

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
    def mechanism_caps(self) -> dict[TrendMechanism, float]:
        """Per-family ``max_share_of_gross`` caps declared in the YAML.

        Empty when the alpha declares no per-family caps; the global
        :attr:`max_share_of_gross` still applies as the default.
        """
        return dict(self._mechanism_caps)

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

    __slots__ = (
        "_engine_thunk",
        "_strategy_id",
        "_feeder_strategy_ids",
        "_mechanism_caps",
        "_global_mechanism_cap",
    )

    def __init__(
        self,
        *,
        engine_thunk: Any,
        strategy_id: str,
        feeder_strategy_ids: tuple[str, ...] = (),
        mechanism_caps: Mapping[TrendMechanism, float] | None = None,
        global_mechanism_cap: float | None = None,
    ) -> None:
        self._engine_thunk = engine_thunk
        self._strategy_id = strategy_id
        self._feeder_strategy_ids = feeder_strategy_ids
        self._mechanism_caps: dict[TrendMechanism, float] = dict(mechanism_caps or {})
        self._global_mechanism_cap = global_mechanism_cap

    def __call__(
        self,
        ctx: CrossSectionalContext,
        params: Mapping[str, Any],
    ) -> SizedPositionIntent:
        engine = self._engine_thunk()
        if engine is None:  # pragma: no cover - bootstrap bug
            raise CompositionContextError("_DefaultPortfolioConstructor: engine not yet wired")
        # Per-alpha decay override (audit P1-6): the shared ranker carries a
        # global decay toggle, so without this an alpha that enables decay
        # would flip it on for every PORTFOLIO sharing the engine.  Reading
        # the alpha's own resolved param here keeps the toggle local.  When
        # the alpha does not declare the param we pass ``None`` so the ranker
        # instance flag still applies (back-compat).
        raw_decay = params.get("decay_weighting_enabled")
        decay_override = bool(raw_decay) if isinstance(raw_decay, bool) else None
        intent: SizedPositionIntent = engine.run_default_pipeline(
            ctx,
            strategy_id=self._strategy_id,
            feeder_strategy_ids=self._feeder_strategy_ids,
            mechanism_caps=self._mechanism_caps or None,
            global_mechanism_cap=self._global_mechanism_cap,
            decay_weighting_enabled=decay_override,
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
        raise ValueError(f"trend_mechanism.consumes must be a list, got {type(raw).__name__}")
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


def parse_mechanism_caps(raw: Any) -> dict[TrendMechanism, float]:
    """Map a YAML ``trend_mechanism.consumes:`` list to per-family caps.

    Returns ``{family: max_share_of_gross}`` for every ``consumes`` entry
    that declares a ``max_share_of_gross`` (audit P0-4 — these caps were
    previously parsed away by :func:`parse_consumes_mechanisms` and never
    reached the runtime ranker).  Entries without an explicit cap are
    omitted (the global ``trend_mechanism.max_share_of_gross`` applies as
    the default).  ``None`` / list-of-strings → empty mapping.
    """
    if raw is None:
        return {}
    if not isinstance(raw, (list, tuple)):
        raise ValueError(f"trend_mechanism.consumes must be a list, got {type(raw).__name__}")
    caps: dict[TrendMechanism, float] = {}
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        family = entry.get("family")
        if family not in _FAMILY_BY_NAME:
            raise ValueError(
                f"trend_mechanism.consumes: unknown family {family!r}; "
                f"allowed: {sorted(_FAMILY_BY_NAME)}"
            )
        if "max_share_of_gross" not in entry:
            continue
        cap = float(entry["max_share_of_gross"])
        if not 0.0 < cap <= 1.0:
            raise ValueError(
                f"trend_mechanism.consumes[{family}].max_share_of_gross must be "
                f"in (0, 1], got {cap}"
            )
        caps[_FAMILY_BY_NAME[family]] = cap
    return caps


__all__ = [
    "LoadedPortfolioLayerModule",
    "_CompiledPortfolioConstructor",
    "_DefaultPortfolioConstructor",
    "parse_consumes_mechanisms",
    "parse_mechanism_caps",
]
