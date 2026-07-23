"""Loaded representation of ``layer: PORTFOLIO`` alphas.

The artifact exposes the manifest, universe, horizon, mechanisms, dependencies,
and constructor consumed by ``CompositionEngine``. Signals listed in
``depends_on_signals`` feed the portfolio only, preventing duplicate standalone
orders. The default constructor runs ranking, neutralization, sector matching,
and turnover optimization; YAML may supply a custom constructor.
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

        The orchestrator skips standalone orders for these signals. They are
        aggregated by ``CompositionEngine`` and translated from the resulting
        ``SizedPositionIntent`` instead, avoiding duplicate trades.
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
        "_neutralize",
        "_consumes_mechanisms",
    )

    def __init__(
        self,
        *,
        engine_thunk: Any,
        strategy_id: str,
        feeder_strategy_ids: tuple[str, ...] = (),
        mechanism_caps: Mapping[TrendMechanism, float] | None = None,
        global_mechanism_cap: float | None = None,
        neutralize: bool = True,
        consumes_mechanisms: tuple[TrendMechanism, ...] = (),
    ) -> None:
        self._engine_thunk = engine_thunk
        self._strategy_id = strategy_id
        self._feeder_strategy_ids = feeder_strategy_ids
        self._mechanism_caps: dict[TrendMechanism, float] = dict(mechanism_caps or {})
        self._global_mechanism_cap = global_mechanism_cap
        self._neutralize = bool(neutralize)
        self._consumes_mechanisms = tuple(consumes_mechanisms)

    def __call__(
        self,
        ctx: CrossSectionalContext,
        params: Mapping[str, Any],
    ) -> SizedPositionIntent:
        engine = self._engine_thunk()
        if engine is None:  # pragma: no cover - bootstrap bug
            raise CompositionContextError("_DefaultPortfolioConstructor: engine not yet wired")
        # Keep this override local to the alpha; ``None`` uses the ranker default.
        raw_decay = params.get("decay_weighting_enabled")
        decay_override = bool(raw_decay) if isinstance(raw_decay, bool) else None
        intent: SizedPositionIntent = engine.run_default_pipeline(
            ctx,
            strategy_id=self._strategy_id,
            feeder_strategy_ids=self._feeder_strategy_ids,
            mechanism_caps=self._mechanism_caps or None,
            global_mechanism_cap=self._global_mechanism_cap,
            decay_weighting_enabled=decay_override,
            neutralize=self._neutralize,
            consumes_mechanisms=self._consumes_mechanisms or None,
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
    that declares a ``max_share_of_gross``. Entries without an explicit cap are
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
