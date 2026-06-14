"""Alpha loader — parse .alpha.yaml specs into layer-specialised modules.

The AlphaLoader is the bridge between the external quant lab's YAML
deliverables and the platform's typed protocol system.  It:

  1. Parses a single ``.alpha.yaml`` file
  2. Validates schema structure and parameter types/ranges
  3. Compiles inline Python code blocks in a sandboxed namespace
  4. Auto-flattens compound features (``return_type: list[N]``)
  5. Wraps the signal evaluate function with provenance patching
  6. Produces a :class:`LoadedSignalLayerModule` (``layer: SIGNAL``)
     or :class:`LoadedPortfolioLayerModule` (``layer: PORTFOLIO``)

Workstream D.2 retired the per-tick ``LoadedAlphaModule`` produced by
the historical ``layer: LEGACY_SIGNAL`` path; PR-2 of D.2 then deleted
the class itself.  Every accepted layer now resolves to a dedicated
loaded-module type with a deterministic dispatch branch in
:meth:`AlphaLoader.load_from_dict` — there is no longer a generic
fall-through path.

Security: inline code is compiled via ``compile()`` + ``exec()`` in a
restricted namespace.  No ``import``, ``open``, ``eval``, ``exec``,
``__import__``, or filesystem access is available to inline code.

Invariants preserved:
  - Inv 5 (deterministic replay): compiled code is pure functions
  - Inv 7 (typed schemas): output is standard AlphaModule protocol
  - Inv 13 (provenance): manifest carries full hypothesis + version
"""

from __future__ import annotations

import inspect
import logging
import math
import re
from pathlib import Path
from typing import Any, Callable

import yaml  # pyright: ignore[reportMissingModuleSource]

from feelies.alpha.cost_arithmetic import CostArithmetic, CostArithmeticError
from feelies.alpha.module import (
    AlphaManifest,
    AlphaRiskBudget,
    ParameterDef,
)
from feelies.alpha.promotion_evidence import parse_gate_thresholds_overrides
from feelies.alpha.portfolio_layer_module import (
    LoadedPortfolioLayerModule,
    _CompiledPortfolioConstructor,
    _DefaultPortfolioConstructor,
    parse_consumes_mechanisms,
)
from feelies.alpha.signal_layer_module import (
    LoadedSignalLayerModule,
    _CompiledHorizonSignal,
)
from feelies.core.events import (
    HorizonFeatureSnapshot,
    NBBOQuote,
    RegimeState,
    Signal,
    SignalDirection,
    Trade,
    TrendMechanism,
)
from feelies.services.regime_engine import RegimeEngine, get_regime_engine
from feelies.signals.regime_gate import RegimeGate, RegimeGateError

logger = logging.getLogger(__name__)

# §8.5 parameter surface cap — at most this many parameters may declare a
# ``range:`` (free for optimization).  ``min``/``max`` validation bounds
# do not count against this cap (audit P1-8).
_MAX_FREE_OPTIMIZATION_PARAMS: int = 3

# Workstream D.2 retired ``layer: LEGACY_SIGNAL`` from the loader's
# accepted set; the once-per-process sunset banner and the per-tick
# :class:`LoadedAlphaModule` class were both deleted by D.2 PR-2.  Any
# LEGACY_SIGNAL manifest is now hard-rejected at parse time with a
# migration pointer (see :meth:`AlphaLoader._validate_schema`).
# ``_REQUIRED_TOP_KEYS`` is retained as a frozen historical record of
# the legacy schema-1.0 contract so the early-validation messages can
# point at exactly which field a copy-pasted-from-1.0 fixture is
# missing — the keys themselves are no longer accepted.
_REQUIRED_TOP_KEYS = {
    "alpha_id",
    "version",
    "description",
    "hypothesis",
    "falsification_criteria",
    "features",
    "signal",
}

_REQUIRED_SIGNAL_LAYER_KEYS = {
    "alpha_id",
    "version",
    "description",
    "hypothesis",
    "falsification_criteria",
    "signal",
    "horizon_seconds",
    "depends_on_sensors",
    "regime_gate",
    "cost_arithmetic",
}

# PORTFOLIO-layer required keys (§6.6 / Phase 4).
# A PORTFOLIO alpha replaces ``signal`` / ``depends_on_sensors`` with
# ``universe`` and ``depends_on_signals``; the optimization weights are
# carried in ``risk_budget`` and the (optional) ``construct:`` block.
_REQUIRED_PORTFOLIO_LAYER_KEYS = {
    "alpha_id",
    "version",
    "description",
    "hypothesis",
    "falsification_criteria",
    "horizon_seconds",
    "universe",
    "depends_on_signals",
    "cost_arithmetic",
}

_SUPPORTED_SCHEMA_VERSIONS = {"1.1"}

# Schema 1.1 layer values per §6.6.  Workstream D.2 retired
# ``LEGACY_SIGNAL`` from both the "valid" and "accepted" sets; it is
# now handled as a dedicated *retired* category with its own migration
# message.  ``SIGNAL`` and ``PORTFOLIO`` are accepted; ``SENSOR``
# remains reserved (sensor specs live under platform.yaml, not alpha
# YAML).  See docs/three_layer_architecture.md §10.
_VALID_1_1_LAYERS = {"SIGNAL", "PORTFOLIO", "SENSOR"}
_ACCEPTED_LAYERS = {"SIGNAL", "PORTFOLIO"}

# Layers that were once accepted but have been removed from the
# loader's dispatch table.  Membership in this set triggers a dedicated
# rejection path with a migration pointer (rather than the generic
# "unknown layer" message), so authors who copy old fixtures get a
# stable, actionable error instead of a typo-shaped one.
_RETIRED_LAYERS = {"LEGACY_SIGNAL"}
_LAYER_PHASE_MAP = {
    "SENSOR": "Phase 2 (sensor framework — declared in platform.yaml, not alpha YAML)",
    "SIGNAL": "Phase 3 (horizon signal engine)",
    "PORTFOLIO": "Phase 4 (composition layer)",
}

# v0.3 closed taxonomy of trend-formation mechanisms (§20.2).  When the
# optional ``trend_mechanism:`` block is present in a schema-1.1 spec,
# its ``family:`` field must be one of these names.  Enforcement of the
# rest of the block is deferred to Phase 3.1 (gate G16); in Phase 1.1
# only the family-name closedness is checked.
_TREND_MECHANISM_FAMILIES = {
    "KYLE_INFO",
    "INVENTORY",
    "HAWKES_SELF_EXCITE",
    "LIQUIDITY_STRESS",
    "SCHEDULED_FLOW",
}

# Phase-3 minimum allowed value for ``horizon_seconds:`` in a SIGNAL
# spec.  Below 30s the platform's L1 NBBO sampling rate (and the
# associated session boundaries scheduled by
# :class:`feelies.sensors.horizon_scheduler.HorizonScheduler`) cannot
# carry a meaningful horizon-anchored snapshot.  The platform-level
# horizon registry (``PlatformConfig.horizons_seconds``) is the
# authoritative whitelist; this floor is a defensive sanity check
# applied before the registry membership check (G7).
_SIGNAL_MIN_HORIZON_SECONDS = 30
_ALPHA_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")

_SAFE_BUILTINS = {
    "abs": abs,
    "min": min,
    "max": max,
    "round": round,
    "len": len,
    "range": range,
    "sum": sum,
    "float": float,
    "int": int,
    "bool": bool,
    "str": str,
    "list": list,
    "dict": dict,
    "tuple": tuple,
    "True": True,
    "False": False,
    "None": None,
    "math": math,
    # Exception hierarchy — needed for try/except in sandboxed signal code.
    "Exception": Exception,
    "BaseException": BaseException,
    "ValueError": ValueError,
    "TypeError": TypeError,
    "KeyError": KeyError,
    "IndexError": IndexError,
    "ZeroDivisionError": ZeroDivisionError,
    "ArithmeticError": ArithmeticError,
    "NameError": NameError,
    "AttributeError": AttributeError,
    "RuntimeError": RuntimeError,
    "StopIteration": StopIteration,
    "OverflowError": OverflowError,
}


def _check_arity(
    fn: Callable[..., Any],
    expected: int,
    name: str,
    source: str,
    context: str,
) -> None:
    """Validate that *fn* accepts exactly *expected* required positional args."""
    sig = inspect.signature(fn)
    n_required = sum(
        1
        for p in sig.parameters.values()
        if p.default is inspect.Parameter.empty
        and p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
    )
    if n_required != expected:
        raise AlphaLoadError(
            f"{source}: {name} in '{context}' requires {expected} "
            f"positional arg(s), got {n_required}"
        )


# ── Loader errors ────────────────────────────────────────────────────


class AlphaLoadError(Exception):
    """Raised when an .alpha.yaml file fails validation or compilation."""


# ── AlphaLoader ──────────────────────────────────────────────────────


class AlphaLoader:
    """Parse ``.alpha.yaml`` files into layer-specialised loaded modules.

    Optional ``regime_engine_options`` are forwarded as ``**kwargs`` to
    :func:`feelies.services.regime_engine.get_regime_engine` when this
    loader must instantiate a standalone regime engine (no shared
    ``regime_engine`` instance was supplied at construction).

    Each accepted ``layer:`` value resolves to a dedicated loaded-module
    class via a deterministic dispatch branch in :meth:`load_from_dict`:

    * ``layer: SIGNAL``     → :class:`LoadedSignalLayerModule`
    * ``layer: PORTFOLIO``  → :class:`LoadedPortfolioLayerModule`

    ``layer: LEGACY_SIGNAL`` was retired by workstream D.2; the per-tick
    ``LoadedAlphaModule`` class that historically backed it was deleted
    in D.2 PR-2.  Any LEGACY_SIGNAL manifest is hard-rejected by
    :meth:`_validate_schema` with a migration-cookbook pointer.
    """

    def __init__(
        self,
        regime_engine: RegimeEngine | None = None,
        *,
        enforce_trend_mechanism: bool = False,
        enforce_layer_gates: bool = True,
        regime_engine_options: dict[str, object] | None = None,
    ) -> None:
        self._regime_engine = regime_engine
        self._enforce_trend_mechanism = bool(enforce_trend_mechanism)
        self._enforce_layer_gates = bool(enforce_layer_gates)
        self._regime_engine_options = dict(regime_engine_options or {})

    def load(
        self,
        path: str | Path,
        param_overrides: dict[str, Any] | None = None,
    ) -> LoadedSignalLayerModule | LoadedPortfolioLayerModule:
        """Load an alpha specification from a YAML file.

        Raises ``AlphaLoadError`` on any validation or compilation failure.
        Returns one of the two layer-specialised module types depending
        on the parsed ``layer:`` field (SIGNAL → ``LoadedSignalLayerModule``,
        PORTFOLIO → ``LoadedPortfolioLayerModule``).  ``layer: LEGACY_SIGNAL``
        was retired by workstream D.2 and is hard-rejected at parse time.
        """
        path = Path(path)
        try:
            raw = path.read_text(encoding="utf-8")
            spec = yaml.safe_load(raw)
        except Exception as exc:
            raise AlphaLoadError(f"Failed to read {path}: {exc}") from exc

        return self.load_from_dict(spec, param_overrides=param_overrides, source=str(path))

    def load_from_dict(
        self,
        spec: dict[str, Any],
        param_overrides: dict[str, Any] | None = None,
        source: str = "<dict>",
    ) -> LoadedSignalLayerModule | LoadedPortfolioLayerModule:
        """Load an alpha specification from a pre-parsed dict.

        Dispatches on ``layer:`` (schema 1.1):

        - ``SIGNAL``                       → :class:`LoadedSignalLayerModule`
          (Phase-3 horizon-anchored, regime-gated contract).
        - ``PORTFOLIO``                    → :class:`LoadedPortfolioLayerModule`
          (Phase-4 cross-sectional construction).

        ``LEGACY_SIGNAL`` was retired by workstream D.2 and is rejected
        in :meth:`_validate_schema`; the per-tick ``LoadedAlphaModule``
        class that historically backed it was deleted in D.2 PR-2 and
        no longer exists in the codebase.
        """
        self._validate_schema(spec, source)

        layer_value = str(spec.get("layer") or "")
        if layer_value == "SIGNAL":
            return self._load_signal_layer(
                spec,
                param_overrides=param_overrides,
                source=source,
            )
        if layer_value == "PORTFOLIO":
            return self._load_portfolio_layer(
                spec,
                param_overrides=param_overrides,
                source=source,
            )

        # _validate_schema rejects every layer that does not have a
        # dispatch branch above.  Reaching here means a layer slipped
        # through `_ACCEPTED_LAYERS` without a corresponding branch in
        # this method — a programmer error.  Keep the assertion in
        # place so the failure surfaces loudly rather than producing
        # ``None`` or hanging on a missing ``features`` key.
        raise AssertionError(  # pragma: no cover
            f"{source}: layer '{layer_value}' passed _validate_schema "
            f"but has no dispatch branch in load_from_dict. "
            f"This is a loader bug — please file an issue."
        )

    # ── SIGNAL-layer load path (Phase 3) ──────────────────────

    def _load_signal_layer(
        self,
        spec: dict[str, Any],
        *,
        param_overrides: dict[str, Any] | None,
        source: str,
    ) -> LoadedSignalLayerModule:
        """Load a schema-1.1 ``layer: SIGNAL`` alpha.

        Defining characteristics of the SIGNAL layer (vs. the retired
        per-tick path that workstream D.2 removed):

        1. **No inline features.**  ``depends_on_sensors`` declares the
           Layer-1 sensors the alpha consumes; the platform provides
           those via :class:`feelies.sensors.registry.SensorRegistry`.
        2. **3-arg evaluate.**  The compiled inline ``signal:`` code
           must define ``evaluate(snapshot, regime, params)``.  The
           snapshot type is :class:`HorizonFeatureSnapshot`; ``regime``
           is the latest :class:`RegimeState` (or ``None`` at cold
           start); ``params`` is the resolved parameter mapping.
        3. **Mandatory ``cost_arithmetic`` and ``regime_gate`` blocks**,
           parsed up-front into :class:`CostArithmetic` and
           :class:`RegimeGate` instances respectively.  Failure of
           either parser surfaces as :class:`AlphaLoadError` so the
           operator sees a single error class.
        """
        alpha_id = spec["alpha_id"]
        param_defs = self._parse_parameters(spec.get("parameters", {}), source)
        params = self._resolve_params(param_defs, param_overrides or {}, source)

        horizon_seconds = self._parse_horizon_seconds(spec, source)
        depends_on_sensors = self._parse_depends_on_sensors(spec, source)

        try:
            cost_arith = CostArithmetic.from_spec(
                alpha_id=alpha_id,
                spec=spec.get("cost_arithmetic"),
            )
        except CostArithmeticError as exc:
            raise AlphaLoadError(f"{source}: {exc}") from exc

        try:
            regime_gate = RegimeGate.from_spec(
                alpha_id=alpha_id,
                spec=spec.get("regime_gate"),
            )
        except RegimeGateError as exc:
            raise AlphaLoadError(f"{source}: {exc}") from exc

        regime_engine = self._resolve_regime_engine(spec.get("regimes"), source)
        # Audit P1-2: validate every ``P(<state>)`` in the gate against the
        # engine's published ``state_names`` at LOAD time.  Previously a typo
        # (``P(noraml)``) compiled cleanly and only failed at the first
        # runtime evaluation as an ``UnknownRegimeStateError`` — and on the
        # OFF path that error did not even unwind a latched-ON gate (see
        # P1-1).  Failing loud at boot turns a latent production hazard into
        # a config error.  Skipped only when no engine is resolvable (the
        # gate then cannot be name-checked against a taxonomy).
        self._validate_gate_posterior_states(regime_gate, regime_engine, source)
        namespace = self._build_namespace(alpha_id, regime_engine)
        namespace["HorizonFeatureSnapshot"] = HorizonFeatureSnapshot
        namespace["RegimeState"] = RegimeState
        compiled_evaluate = self._compile_signal_layer_evaluate(
            spec["signal"],
            alpha_id,
            namespace,
            source,
        )
        signal_obj = _CompiledHorizonSignal(
            signal_id=alpha_id,
            signal_version=str(spec["version"]),
            fn=compiled_evaluate,
        )

        trend_mechanism_block = self._parse_trend_mechanism_block(
            spec.get("trend_mechanism"), source
        )
        hazard_exit_block = self._parse_hazard_exit_block(spec.get("hazard_exit"), source)
        promotion_overrides = self._parse_promotion_block(spec.get("promotion"), source)
        lifecycle_cap = self._parse_lifecycle_state(spec.get("lifecycle_state"), source)
        trend_enum, expected_half_life = self._extract_trend_metadata(
            trend_mechanism_block,
            source,
        )
        # Audit P1-4: surface cosmetic G16 fingerprints — a
        # ``l1_signature_sensors`` entry the alpha does not actually
        # depend on cannot be the fingerprint of a mechanism it never
        # consumes.  Warn (not reject) so the canonical G16 fixtures and
        # the 9-rule completeness lock are untouched; hardening this to a
        # G16 binding rule is a §20.6.1 design-doc change.
        self._warn_unbacked_signature_sensors(
            trend_mechanism_block, depends_on_sensors, source
        )

        symbols_raw = spec.get("symbols")
        symbols = frozenset(symbols_raw) if symbols_raw is not None else None

        risk_budget_raw = spec.get("risk_budget", {}) or {}
        risk_budget = AlphaRiskBudget(
            max_position_per_symbol=risk_budget_raw.get("max_position_per_symbol", 100),
            max_gross_exposure_pct=risk_budget_raw.get("max_gross_exposure_pct", 5.0),
            max_drawdown_pct=risk_budget_raw.get("max_drawdown_pct", 1.0),
            capital_allocation_pct=risk_budget_raw.get("capital_allocation_pct", 10.0),
        )
        self._validate_risk_budget(risk_budget, source)

        manifest = AlphaManifest(
            alpha_id=alpha_id,
            version=str(spec["version"]),
            description=str(spec["description"]),
            hypothesis=str(spec["hypothesis"]),
            falsification_criteria=tuple(spec["falsification_criteria"]),
            required_features=frozenset(),
            symbols=symbols,
            parameters=params,
            parameter_schema=tuple(param_defs),
            risk_budget=risk_budget,
            layer="SIGNAL",
            trend_mechanism=trend_mechanism_block,
            hazard_exit=hazard_exit_block,
            gate_thresholds_overrides=promotion_overrides,
            lifecycle_cap=lifecycle_cap,
        )

        return LoadedSignalLayerModule(
            manifest=manifest,
            signal=signal_obj,
            gate=regime_gate,
            cost=cost_arith,
            horizon_seconds=horizon_seconds,
            depends_on_sensors=depends_on_sensors,
            trend_mechanism=trend_enum,
            expected_half_life_seconds=expected_half_life,
            consumed_features=depends_on_sensors,
            params=params,
            # 2P-1: retain the raw body so the platform can statically derive
            # which snapshot.values keys the alpha actually reads.
            signal_source=str(spec["signal"]),
        )

    # ── PORTFOLIO-layer load path (Phase 4) ───────────────────────

    def _load_portfolio_layer(
        self,
        spec: dict[str, Any],
        *,
        param_overrides: dict[str, Any] | None,
        source: str,
    ) -> LoadedPortfolioLayerModule:
        """Load a schema-1.1 ``layer: PORTFOLIO`` alpha (§6.6 / Phase 4).

        Differs from the SIGNAL path in three places:

        1. **No inline ``signal:`` block.**  PORTFOLIO alphas operate on
           the universe-wide :class:`CrossSectionalContext` rather than
           per-symbol snapshots; the optional ``construct:`` block holds
           the alpha's custom optimizer.  Absent ``construct:`` falls
           back to the engine's default pipeline.
        2. **``universe`` and ``depends_on_signals``** replace
           ``symbols`` and ``depends_on_sensors``.  Both are parsed into
           sorted tuples so iteration order is replay-stable.
        3. **``trend_mechanism.consumes:`` whitelist** maps to a tuple
           of :class:`TrendMechanism` enums; the engine refuses to
           operate on signals whose family is outside the whitelist.
        """
        alpha_id = spec["alpha_id"]
        param_defs = self._parse_parameters(spec.get("parameters", {}), source)
        params = self._resolve_params(param_defs, param_overrides or {}, source)

        horizon_seconds = self._parse_horizon_seconds(spec, source)
        universe = self._parse_universe(spec, source)
        depends_on_signals = self._parse_depends_on_signals(spec, source)

        try:
            cost_arith = CostArithmetic.from_spec(
                alpha_id=alpha_id,
                spec=spec.get("cost_arithmetic"),
            )
        except CostArithmeticError as exc:
            raise AlphaLoadError(f"{source}: {exc}") from exc

        trend_mechanism_block = self._parse_trend_mechanism_block(
            spec.get("trend_mechanism"), source
        )
        hazard_exit_block = self._parse_hazard_exit_block(spec.get("hazard_exit"), source)
        promotion_overrides = self._parse_promotion_block(spec.get("promotion"), source)
        lifecycle_cap = self._parse_lifecycle_state(spec.get("lifecycle_state"), source)

        consumes_raw = (
            (trend_mechanism_block or {}).get("consumes") if trend_mechanism_block else None
        )
        try:
            consumes = parse_consumes_mechanisms(consumes_raw)
        except ValueError as exc:
            raise AlphaLoadError(f"{source}: {exc}") from exc

        max_share_of_gross = float((trend_mechanism_block or {}).get("max_share_of_gross", 1.0))
        if not 0.0 < max_share_of_gross <= 1.0:
            raise AlphaLoadError(
                f"{source}: trend_mechanism.max_share_of_gross must be in "
                f"(0, 1], got {max_share_of_gross}"
            )

        # Optional inline construct() block
        constructor: Any
        if "construct" in spec and spec["construct"]:
            namespace = self._build_namespace(alpha_id, regime_engine=None)
            namespace["CrossSectionalContext"] = _import_cross_sectional_context()
            namespace["SizedPositionIntent"] = _import_sized_position_intent()
            namespace["TargetPosition"] = _import_target_position()
            compiled = self._compile_portfolio_construct(
                spec["construct"],
                alpha_id,
                namespace,
                source,
            )
            constructor = _CompiledPortfolioConstructor(fn=compiled)
        else:
            # Default-pipeline marker; bootstrap rebinds to engine.
            constructor = _DefaultPortfolioConstructor(
                engine_thunk=lambda: None,
                strategy_id=alpha_id,
                feeder_strategy_ids=depends_on_signals,
            )

        risk_budget_raw = spec.get("risk_budget", {}) or {}
        risk_budget = AlphaRiskBudget(
            max_position_per_symbol=risk_budget_raw.get("max_position_per_symbol", 100),
            max_gross_exposure_pct=risk_budget_raw.get("max_gross_exposure_pct", 5.0),
            max_drawdown_pct=risk_budget_raw.get("max_drawdown_pct", 1.0),
            capital_allocation_pct=risk_budget_raw.get("capital_allocation_pct", 10.0),
        )
        self._validate_risk_budget(risk_budget, source)

        manifest = AlphaManifest(
            alpha_id=alpha_id,
            version=str(spec["version"]),
            description=str(spec["description"]),
            hypothesis=str(spec["hypothesis"]),
            falsification_criteria=tuple(spec["falsification_criteria"]),
            required_features=frozenset(),
            symbols=frozenset(universe) if universe else None,
            parameters=params,
            parameter_schema=tuple(param_defs),
            risk_budget=risk_budget,
            layer="PORTFOLIO",
            trend_mechanism=trend_mechanism_block,
            hazard_exit=hazard_exit_block,
            gate_thresholds_overrides=promotion_overrides,
            lifecycle_cap=lifecycle_cap,
        )

        return LoadedPortfolioLayerModule(
            manifest=manifest,
            construct=constructor,
            universe=universe,
            horizon_seconds=horizon_seconds,
            consumes_mechanisms=consumes,
            max_share_of_gross=max_share_of_gross,
            factor_neutralization_disclosed=bool(spec.get("factor_neutralization", False)),
            depends_on_signals=depends_on_signals,
            params=params,
        )

    @staticmethod
    def _parse_universe(spec: dict[str, Any], source: str) -> tuple[str, ...]:
        raw = spec.get("universe")
        if raw is None or not isinstance(raw, list) or not raw:
            raise AlphaLoadError(
                f"{source}: PORTFOLIO 'universe' must be a non-empty list "
                f"of symbol strings; got {raw!r}"
            )
        out: list[str] = []
        for entry in raw:
            if not isinstance(entry, str) or not entry:
                raise AlphaLoadError(
                    f"{source}: PORTFOLIO 'universe' entries must be "
                    f"non-empty strings; got {entry!r}"
                )
            out.append(entry)
        return tuple(sorted(set(out)))

    @staticmethod
    def _parse_depends_on_signals(
        spec: dict[str, Any],
        source: str,
    ) -> tuple[str, ...]:
        raw = spec.get("depends_on_signals")
        if raw is None or not isinstance(raw, list) or not raw:
            raise AlphaLoadError(
                f"{source}: PORTFOLIO 'depends_on_signals' must be a "
                f"non-empty list of signal alpha_ids; got {raw!r}"
            )
        out: list[str] = []
        for entry in raw:
            if not isinstance(entry, str) or not entry:
                raise AlphaLoadError(
                    f"{source}: PORTFOLIO 'depends_on_signals' entries "
                    f"must be non-empty strings; got {entry!r}"
                )
            out.append(entry)
        return tuple(out)

    def _compile_portfolio_construct(
        self,
        code: str,
        alpha_id: str,
        namespace: dict[str, Any],
        source: str,
    ) -> Any:
        """Compile inline ``construct(ctx, params)`` per the PORTFOLIO contract."""
        try:
            tree = compile(code, f"<{alpha_id}.construct>", "exec")
        except SyntaxError as exc:
            raise AlphaLoadError(
                f"{source}: PORTFOLIO 'construct' block has a syntax error: {exc}"
            ) from exc
        local_ns: dict[str, Any] = {}
        exec(tree, namespace, local_ns)
        fn = local_ns.get("construct")
        if fn is None or not callable(fn):
            raise AlphaLoadError(
                f"{source}: PORTFOLIO 'construct' must define a callable "
                f"named 'construct(ctx, params)'."
            )
        sig = inspect.signature(fn)
        if len(sig.parameters) != 2:
            raise AlphaLoadError(
                f"{source}: PORTFOLIO 'construct' must accept exactly 2 "
                f"parameters (ctx, params); got "
                f"{list(sig.parameters)}"
            )
        return fn

    @staticmethod
    def _parse_horizon_seconds(spec: dict[str, Any], source: str) -> int:
        raw = spec.get("horizon_seconds")
        if not isinstance(raw, int) or isinstance(raw, bool):
            raise AlphaLoadError(
                f"{source}: 'horizon_seconds' must be an integer (>= "
                f"{_SIGNAL_MIN_HORIZON_SECONDS}); got "
                f"{type(raw).__name__}={raw!r}"
            )
        if raw < _SIGNAL_MIN_HORIZON_SECONDS:
            raise AlphaLoadError(
                f"{source}: 'horizon_seconds' must be >= "
                f"{_SIGNAL_MIN_HORIZON_SECONDS}, got {raw}. "
                f"Sub-30s horizons are not supported by the L1 NBBO "
                f"sampling regime."
            )
        return raw

    @staticmethod
    def _parse_depends_on_sensors(
        spec: dict[str, Any],
        source: str,
    ) -> tuple[str, ...]:
        raw = spec.get("depends_on_sensors")
        if raw is None:
            return ()
        if not isinstance(raw, list):
            raise AlphaLoadError(
                f"{source}: 'depends_on_sensors' must be a list of "
                f"sensor_id strings, got {type(raw).__name__}"
            )
        sensors: list[str] = []
        seen: set[str] = set()
        for entry in raw:
            if not isinstance(entry, str) or not entry.strip():
                raise AlphaLoadError(
                    f"{source}: every 'depends_on_sensors' entry must be "
                    f"a non-empty sensor_id string; got {entry!r}"
                )
            sid = entry.strip()
            if sid in seen:
                raise AlphaLoadError(
                    f"{source}: duplicate sensor_id {sid!r} in depends_on_sensors"
                )
            seen.add(sid)
            sensors.append(sid)
        return tuple(sensors)

    @staticmethod
    def _extract_trend_metadata(
        block: dict[str, Any] | None,
        source: str,
    ) -> tuple[TrendMechanism | None, int]:
        """Lift v0.3 ``trend_mechanism:`` family + half-life onto the module.

        Returns ``(enum_or_None, half_life_seconds)`` so the
        :class:`HorizonSignalEngine` can stamp every emitted ``Signal``
        with deterministic metadata.  Phase 3.1 will activate the
        full G16 binding rules; here we only need the family enum and
        the disclosed half-life.
        """
        if block is None:
            return None, 0
        family_str = block.get("family")
        enum_value: TrendMechanism | None = None
        if family_str is not None:
            try:
                enum_value = TrendMechanism[str(family_str)]
            except KeyError as exc:
                raise AlphaLoadError(
                    f"{source}: trend_mechanism.family {family_str!r} "
                    f"could not be mapped to TrendMechanism enum"
                ) from exc
        half_life_raw = block.get("expected_half_life_seconds", 0)
        try:
            half_life = int(half_life_raw)
        except (TypeError, ValueError) as exc:
            raise AlphaLoadError(
                f"{source}: trend_mechanism.expected_half_life_seconds "
                f"must be an integer, got {half_life_raw!r}"
            ) from exc
        if half_life < 0:
            raise AlphaLoadError(
                f"{source}: trend_mechanism.expected_half_life_seconds "
                f"must be >= 0, got {half_life}"
            )
        return enum_value, half_life

    def _compile_signal_layer_evaluate(
        self,
        signal_code: str,
        alpha_id: str,
        namespace: dict[str, Any],
        source: str,
    ) -> Callable[..., Signal | None]:
        """Compile the SIGNAL-layer inline ``signal:`` evaluate function.

        Expects the 3-arg ``evaluate(snapshot, regime, params)`` signature
        introduced in schema 1.1.  The legacy 2-arg
        ``evaluate(features, params)`` signature was deleted with the
        ``LoadedAlphaModule`` per-tick path in D.2 PR-2.
        """
        if not isinstance(signal_code, str):
            raise AlphaLoadError(
                f"{source}: layer: SIGNAL spec 'signal' must be inline "
                f"Python code (string), got {type(signal_code).__name__}"
            )
        ns = dict(namespace)
        try:
            compiled = compile(signal_code, f"<{source}:signal>", "exec")
            exec(compiled, ns)  # noqa: S102
        except SyntaxError as exc:
            raise AlphaLoadError(f"{source}: signal code syntax error: {exc}") from exc

        evaluate_fn = ns.get("evaluate")
        if evaluate_fn is None:
            raise AlphaLoadError(
                f"{source}: layer: SIGNAL signal code must define "
                f"evaluate(snapshot, regime, params)"
            )
        _check_arity(evaluate_fn, 3, "evaluate", source, alpha_id)
        evaluate_callable: Callable[..., Signal | None] = evaluate_fn
        return evaluate_callable

    # ── Schema validation ─────────────────────────────────────

    def _validate_schema(self, spec: dict[str, Any], source: str) -> None:
        """Validate top-level schema, dispatching on ``layer``.

        Per docs/three_layer_architecture.md §6.6 + §8.7 the
        validation ordering (post-workstream-D.2) is:

          1. ``spec`` is a dict.
          2. Read ``schema_version``; reject if missing or unsupported.
             Schema 1.0 was removed in workstream D.1; the only
             supported value is ``"1.1"``.
          3. Read ``layer`` (mandatory in 1.1).
          4. Dispatch on layer:
             - LEGACY_SIGNAL → hard-reject with migration pointer
               (workstream D.2 retired the per-tick legacy path).
             - SENSOR / unknown layer → reject.
             - SIGNAL → enforce ``_REQUIRED_SIGNAL_LAYER_KEYS`` and
               run the LayerValidator.
             - PORTFOLIO → enforce ``_REQUIRED_PORTFOLIO_LAYER_KEYS``
               and run the LayerValidator.
          5. Validate alpha_id and version syntax (per-layer branch).
          6. Run the LayerValidator (G14, G15 active).
        """
        if not isinstance(spec, dict):
            raise AlphaLoadError(f"{source}: root must be a YAML mapping")

        schema_version = spec.get("schema_version")
        if schema_version is None:
            raise AlphaLoadError(
                f"{source}: missing required 'schema_version' field. "
                f'The only supported value is "1.1". Schema 1.0 was '
                f"removed in workstream D.1; see "
                f"docs/migration/schema_1_0_to_1_1.md for the migration "
                f"cookbook (still applicable as historical reference)."
            )
        if str(schema_version) not in _SUPPORTED_SCHEMA_VERSIONS:
            raise AlphaLoadError(
                f"{source}: unsupported schema_version "
                f"'{schema_version}', supported: "
                f"{sorted(_SUPPORTED_SCHEMA_VERSIONS)}. "
                f"Schema 1.0 was removed in workstream D.1; migrate by "
                f'setting schema_version: "1.1" and declaring '
                f"layer: SIGNAL or layer: PORTFOLIO. "
                f"See docs/migration/schema_1_0_to_1_1.md."
            )
        schema_version = str(schema_version)

        layer = spec.get("layer")

        if layer is None:
            raise AlphaLoadError(
                f"{source}: schema_version '1.1' requires the 'layer' "
                f"field (§8.7 of docs/three_layer_architecture.md). "
                f"There is no implicit upgrade path. Declare "
                f"`layer: SIGNAL` (horizon-anchored, regime-gated) or "
                f"`layer: PORTFOLIO` (cross-sectional construction). "
                f"See docs/migration/schema_1_0_to_1_1.md."
            )
        layer_str = str(layer)

        # Workstream D.2: ``layer: LEGACY_SIGNAL`` was retired in PR-1
        # and the per-tick ``LoadedAlphaModule`` class itself was
        # deleted in PR-2.  The only survivors are SIGNAL/PORTFOLIO.
        # Surface a dedicated rejection (rather than a generic
        # "unknown layer" typo message) so authors copying old
        # fixtures get a stable migration pointer.
        if layer_str in _RETIRED_LAYERS:
            raise AlphaLoadError(
                f"{source}: layer '{layer_str}' was retired by "
                f"workstream D.2 of the three-layer refactor. "
                f"The per-tick legacy execution path no longer exists. "
                f"Migrate to `layer: SIGNAL` (horizon-anchored, "
                f"regime-gated, cost-aware) or `layer: PORTFOLIO` "
                f"(cross-sectional construction over upstream signals). "
                f"See docs/migration/schema_1_0_to_1_1.md for the "
                f"step-by-step cookbook."
            )

        if layer_str not in _VALID_1_1_LAYERS:
            raise AlphaLoadError(
                f"{source}: unknown layer '{layer_str}'. "
                f"Valid layers: {sorted(_VALID_1_1_LAYERS)}."
            )
        if layer_str not in _ACCEPTED_LAYERS:
            phase = _LAYER_PHASE_MAP.get(layer_str, "a future phase")
            raise AlphaLoadError(
                f"{source}: layer '{layer_str}' is not yet implemented "
                f"({phase}). Use `layer: SIGNAL` or `layer: PORTFOLIO`. "
                f"See docs/migration/schema_1_0_to_1_1.md."
            )

        if layer_str == "SIGNAL":
            missing = _REQUIRED_SIGNAL_LAYER_KEYS - set(spec.keys())
            if missing:
                raise AlphaLoadError(
                    f"{source}: layer: SIGNAL spec is missing required "
                    f"top-level keys: "
                    + ", ".join(sorted(missing))
                    + ". Required (Phase 3): "
                    + ", ".join(sorted(_REQUIRED_SIGNAL_LAYER_KEYS))
                )
            self._validate_alpha_id_and_version(spec, source)
            from feelies.alpha.layer_validator import LayerValidator

            LayerValidator(
                enforce_trend_mechanism=self._enforce_trend_mechanism,
                enforce_layer_gates=self._enforce_layer_gates,
            ).validate(spec, source)
            return

        if layer_str == "PORTFOLIO":
            missing = _REQUIRED_PORTFOLIO_LAYER_KEYS - set(spec.keys())
            if missing:
                raise AlphaLoadError(
                    f"{source}: layer: PORTFOLIO spec is missing required "
                    f"top-level keys: "
                    + ", ".join(sorted(missing))
                    + ". Required (Phase 4): "
                    + ", ".join(sorted(_REQUIRED_PORTFOLIO_LAYER_KEYS))
                )
            self._validate_alpha_id_and_version(spec, source)
            from feelies.alpha.layer_validator import LayerValidator

            LayerValidator(
                enforce_trend_mechanism=self._enforce_trend_mechanism,
                enforce_layer_gates=self._enforce_layer_gates,
            ).validate(spec, source)
            return

        # All accepted layers return inside their branch above; reaching
        # this point would mean a layer slipped through `_ACCEPTED_LAYERS`
        # without a dispatch case — a programmer error in this file.
        raise AssertionError(  # pragma: no cover
            f"{source}: layer '{layer_str}' is in _ACCEPTED_LAYERS but "
            f"has no dispatch branch in _validate_schema. "
            f"This is a loader bug — please file an issue."
        )

    def _validate_alpha_id_and_version(
        self,
        spec: dict[str, Any],
        source: str,
    ) -> None:
        """Shared identifier validation lifted from ``_validate_schema``.

        Both SIGNAL and PORTFOLIO layers gate on alpha_id syntax
        (lower-snake-case) and semver version strings.  Extracted into
        a helper so both branches enforce the same rules without
        duplicating error messages.
        """
        alpha_id = spec.get("alpha_id", "")
        if not _ALPHA_ID_RE.match(str(alpha_id)):
            raise AlphaLoadError(
                f"{source}: alpha_id '{alpha_id}' must match "
                f"'^[a-z][a-z0-9_]*$' (lowercase, underscores only)"
            )

        version = spec.get("version", "")
        if not _SEMVER_RE.match(str(version)):
            raise AlphaLoadError(f"{source}: version '{version}' must be semver (e.g. '1.0.0')")

    # ── v0.3 optional YAML blocks ─────────────────────────────

    def _parse_trend_mechanism_block(
        self,
        block: Any,
        source: str,
    ) -> dict[str, Any] | None:
        """Parse the optional v0.3 ``trend_mechanism:`` block (§20.5).

        Phase 1.1 only enforces:
          - block is a mapping if present.
          - if ``family:`` is set, it is one of the 5 closed
            ``TrendMechanism`` names.

        The remainder of the block (e.g. parameter constraints,
        decay-curve specifications) is captured verbatim for
        consumption by the gate G16 in Phase 3.1.  Absent block ⇒
        opt-in not exercised; returns ``None``.
        """
        if block is None:
            return None
        if not isinstance(block, dict):
            raise AlphaLoadError(
                f"{source}: 'trend_mechanism' must be a mapping, got {type(block).__name__}"
            )
        family = block.get("family")
        if family is not None and str(family) not in _TREND_MECHANISM_FAMILIES:
            raise AlphaLoadError(
                f"{source}: trend_mechanism.family '{family}' is not in "
                f"the closed taxonomy. Valid families: "
                f"{sorted(_TREND_MECHANISM_FAMILIES)}. "
                f"See §20.2 of docs/three_layer_architecture.md."
            )
        return dict(block)

    _HAZARD_EXIT_KNOWN_KEYS: frozenset[str] = frozenset(
        {
            "enabled",
            "hazard_score_threshold",
            "min_age_seconds",
            "hard_exit_age_seconds",
        }
    )

    # Legacy / mis-named keys we accept with a translation, to fail loudly
    # when authors copy the design-doc spelling.  ``posterior_drop_threshold``
    # was used by ``sig_hawkes_burst_v1`` in the field — silently ignored by
    # bootstrap which only reads ``hazard_score_threshold`` — until audit
    # P1 H-2.  The detector's ``hazard_score`` IS clip01((p_prev − p_now) /
    # max(p_prev, ε)), i.e. a normalized posterior drop — same semantic
    # field, mis-named, rename in place with a WARN.
    _HAZARD_EXIT_LEGACY_KEYS: dict[str, str] = {
        "posterior_drop_threshold": "hazard_score_threshold",
    }

    def _parse_hazard_exit_block(
        self,
        block: Any,
        source: str,
    ) -> dict[str, Any] | None:
        """Parse the optional v0.3 ``hazard_exit:`` block (§20.5).

        Audit P1 H-2: strict schema.  Unknown keys raise
        :class:`AlphaLoadError` (matching the discipline already used
        by :meth:`_parse_promotion_block`).  Legacy / mis-named keys
        listed in ``_HAZARD_EXIT_LEGACY_KEYS`` are renamed in place
        with a WARNING — the field author's intent (e.g.
        ``posterior_drop_threshold``) was silently dropped before this
        fix.

        Value types are coerced and range-checked so bootstrap can
        trust the parsed block:

        * ``enabled``                — bool-ish (only literal True opts in)
        * ``hazard_score_threshold`` — float in (0.0, 1.0]
        * ``min_age_seconds``        — int ≥ 0
        * ``hard_exit_age_seconds``  — int > 0 (or omitted → derived
          from ``2 × expected_half_life_seconds`` at composition time)
        """
        if block is None:
            return None
        if not isinstance(block, dict):
            raise AlphaLoadError(
                f"{source}: 'hazard_exit' must be a mapping, got {type(block).__name__}"
            )

        normalized: dict[str, Any] = {}
        for key, value in block.items():
            if key in self._HAZARD_EXIT_LEGACY_KEYS:
                new_key = self._HAZARD_EXIT_LEGACY_KEYS[key]
                logger.warning(
                    "%s: hazard_exit.%s is a legacy spelling of "
                    "hazard_exit.%s; rename to %s in the YAML to silence "
                    "this warning",
                    source,
                    key,
                    new_key,
                    new_key,
                )
                if new_key in block:
                    raise AlphaLoadError(
                        f"{source}: hazard_exit declares both {key!r} "
                        f"and {new_key!r}; remove the legacy key {key!r}"
                    )
                normalized[new_key] = value
            elif key in self._HAZARD_EXIT_KNOWN_KEYS:
                normalized[key] = value
            else:
                raise AlphaLoadError(
                    f"{source}: hazard_exit block carries unknown key "
                    f"{key!r}; supported keys are "
                    f"{sorted(self._HAZARD_EXIT_KNOWN_KEYS)} "
                    f"(legacy accepted with warning: "
                    f"{sorted(self._HAZARD_EXIT_LEGACY_KEYS)})"
                )

        if "hazard_score_threshold" in normalized:
            try:
                threshold = float(normalized["hazard_score_threshold"])
            except (TypeError, ValueError) as exc:
                raise AlphaLoadError(
                    f"{source}: hazard_exit.hazard_score_threshold must "
                    f"be numeric, got {normalized['hazard_score_threshold']!r}"
                ) from exc
            if not 0.0 < threshold <= 1.0:
                raise AlphaLoadError(
                    f"{source}: hazard_exit.hazard_score_threshold must "
                    f"be in (0.0, 1.0], got {threshold}"
                )
            normalized["hazard_score_threshold"] = threshold

        if "min_age_seconds" in normalized:
            try:
                min_age = int(normalized["min_age_seconds"])
            except (TypeError, ValueError) as exc:
                raise AlphaLoadError(
                    f"{source}: hazard_exit.min_age_seconds must be int, "
                    f"got {normalized['min_age_seconds']!r}"
                ) from exc
            if min_age < 0:
                raise AlphaLoadError(
                    f"{source}: hazard_exit.min_age_seconds must be >= 0, got {min_age}"
                )
            normalized["min_age_seconds"] = min_age

        if (
            "hard_exit_age_seconds" in normalized
            and normalized["hard_exit_age_seconds"] is not None
        ):
            try:
                hard_age = int(normalized["hard_exit_age_seconds"])
            except (TypeError, ValueError) as exc:
                raise AlphaLoadError(
                    f"{source}: hazard_exit.hard_exit_age_seconds must "
                    f"be int or null, got "
                    f"{normalized['hard_exit_age_seconds']!r}"
                ) from exc
            if hard_age <= 0:
                raise AlphaLoadError(
                    f"{source}: hazard_exit.hard_exit_age_seconds must be > 0, got {hard_age}"
                )
            normalized["hard_exit_age_seconds"] = hard_age

        return normalized

    def _parse_promotion_block(
        self,
        block: Any,
        source: str,
    ) -> dict[str, Any] | None:
        """Parse the optional Workstream F-5 ``promotion:`` block.

        Schema::

            promotion:
              gate_thresholds:
                paper_min_trading_days: 7
                dsr_min: 1.2
                ...

        Returns the type-coerced override dict (or ``None`` when the
        block is absent or carries an empty / missing
        ``gate_thresholds:`` sub-block).  Override keys are validated
        against :class:`feelies.alpha.promotion_evidence.GateThresholds`
        field names — unknown keys raise :class:`AlphaLoadError` with
        the source path so the operator gets a concrete YAML location.

        Numeric invariant checks (e.g. cross-field consistency) are
        deferred to consumers; the loader is responsible only for
        structural + per-field type validation.
        """
        if block is None:
            return None
        if not isinstance(block, dict):
            raise AlphaLoadError(
                f"{source}: 'promotion' must be a mapping, got {type(block).__name__}"
            )

        unknown_keys = sorted(k for k in block if k != "gate_thresholds")
        if unknown_keys:
            raise AlphaLoadError(
                f"{source}: promotion block carries unknown key(s) "
                f"{unknown_keys}; only 'gate_thresholds' is supported "
                "today"
            )

        raw_overrides = block.get("gate_thresholds")
        if raw_overrides is None:
            return None
        if not isinstance(raw_overrides, dict):
            raise AlphaLoadError(
                f"{source}: 'promotion.gate_thresholds' must be a "
                f"mapping, got {type(raw_overrides).__name__}"
            )
        if not raw_overrides:
            return None

        try:
            return parse_gate_thresholds_overrides(raw_overrides)
        except ValueError as exc:
            raise AlphaLoadError(f"{source}: promotion.gate_thresholds: {exc}") from exc

    @staticmethod
    def _parse_lifecycle_state(raw: Any, source: str) -> str | None:
        """Parse optional ``lifecycle_state`` (BT-13 research-only cap).

        Only ``RESEARCH`` is supported today: it blocks PAPER/LIVE promotion
        while still allowing the alpha to load for integration tests.
        """
        if raw is None:
            return None
        if not isinstance(raw, str):
            raise AlphaLoadError(
                f"{source}: 'lifecycle_state' must be a string, got {type(raw).__name__}"
            )
        normalized = raw.strip().upper()
        if normalized != "RESEARCH":
            raise AlphaLoadError(
                f"{source}: unsupported lifecycle_state {raw!r}; only 'RESEARCH' is supported"
            )
        return normalized

    @staticmethod
    def _validate_risk_budget(budget: AlphaRiskBudget, source: str) -> None:
        errors: list[str] = []
        if budget.max_position_per_symbol <= 0:
            errors.append("max_position_per_symbol must be > 0")
        if not (0 < budget.max_gross_exposure_pct <= 100):
            errors.append("max_gross_exposure_pct must be in (0, 100]")
        if not (0 < budget.max_drawdown_pct <= 100):
            errors.append("max_drawdown_pct must be in (0, 100]")
        if not (0 < budget.capital_allocation_pct <= 100):
            errors.append("capital_allocation_pct must be in (0, 100]")
        if errors:
            raise AlphaLoadError(f"{source}: risk_budget validation failed: " + "; ".join(errors))

    # ── Parameter resolution ──────────────────────────────────

    def _parse_parameters(self, params_raw: dict[str, Any], source: str) -> list[ParameterDef]:
        defs: list[ParameterDef] = []
        free_optimization_params: list[str] = []
        for name, pspec in params_raw.items():
            if not isinstance(pspec, dict):
                raise AlphaLoadError(
                    f"{source}: parameter '{name}' must be a mapping with type/default/description"
                )
            param_type = str(pspec.get("type", "float"))
            default = pspec.get("default")
            if default is None:
                raise AlphaLoadError(f"{source}: parameter '{name}' missing 'default'")
            range_raw = pspec.get("range")
            param_range = (
                (float(range_raw[0]), float(range_raw[1])) if range_raw is not None else None
            )
            if param_range is not None:
                free_optimization_params.append(name)
            # Audit P1-8: ``min``/``max`` were parsed into nothing and
            # silently ignored.  Map them to an enforced validation
            # envelope (``bounds``) — distinct from ``range`` so they do
            # not count as free-optimization knobs against the §8.5 cap.
            min_raw = pspec.get("min")
            max_raw = pspec.get("max")
            param_bounds: tuple[float, float] | None = None
            if min_raw is not None or max_raw is not None:
                lo = float(min_raw) if min_raw is not None else float("-inf")
                hi = float(max_raw) if max_raw is not None else float("inf")
                if lo > hi:
                    raise AlphaLoadError(
                        f"{source}: parameter '{name}' has min ({lo}) > max ({hi})"
                    )
                param_bounds = (lo, hi)
            pdef = ParameterDef(
                name=name,
                param_type=param_type,
                default=default,
                range=param_range,
                bounds=param_bounds,
                description=str(pspec.get("description", "")),
            )
            # Reject specs whose own declared default violates its bounds
            # so the envelope can be trusted by downstream override checks.
            default_errors = pdef.validate_value(default)
            if default_errors:
                raise AlphaLoadError(
                    f"{source}: parameter '{name}' default is invalid: "
                    + "; ".join(default_errors)
                )
            defs.append(pdef)

        # §8.5 parameter surface cap (docs/three_layer_architecture.md):
        # at most 3 parameters declared free for optimization (``range:``).
        # ``min``/``max``-bounded parameters are unlimited.
        if len(free_optimization_params) > _MAX_FREE_OPTIMIZATION_PARAMS:
            raise AlphaLoadError(
                f"{source}: §8.5 parameter surface cap exceeded — "
                f"{len(free_optimization_params)} parameters declare a "
                f"'range:' (free for optimization); max is "
                f"{_MAX_FREE_OPTIMIZATION_PARAMS}. Offenders: "
                f"{free_optimization_params}. Use 'min'/'max' for "
                f"validation bounds that do not count against the cap."
            )
        return defs

    def _warn_unbacked_signature_sensors(
        self,
        trend_mechanism_block: dict[str, Any] | None,
        depends_on_sensors: tuple[str, ...],
        source: str,
    ) -> None:
        """Audit P1-4 — warn when ``l1_signature_sensors`` is not a subset
        of ``depends_on_sensors``.

        A signature sensor the alpha never declares as a dependency (and
        therefore cannot consume) is a cosmetic G16 fingerprint: it
        satisfies the rule-5 family-marker check on paper while the
        ``evaluate`` body reads something else entirely.  This is a
        non-fatal WARN so the canonical G16 test fixtures (which use
        deliberately-minimal ``depends_on_sensors``) and the 9-rule
        completeness lock stay green; promoting it to a hard G16 rule is
        a §20.6.1 + acceptance-matrix design change.
        """
        if not trend_mechanism_block:
            return
        sig_raw = trend_mechanism_block.get("l1_signature_sensors") or []
        if not isinstance(sig_raw, list):
            return
        declared = {s for s in sig_raw if isinstance(s, str)}
        unbacked = sorted(declared - set(depends_on_sensors))
        if unbacked:
            logger.warning(
                "%s: trend_mechanism.l1_signature_sensors %s not present in "
                "depends_on_sensors — cosmetic fingerprint risk (audit P1-4): "
                "a signature sensor the alpha does not consume cannot be the "
                "mechanism's L1 fingerprint.",
                source,
                unbacked,
            )

    def _resolve_params(
        self,
        param_defs: list[ParameterDef],
        overrides: dict[str, Any],
        source: str,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {}
        errors: list[str] = []
        override_keys = set(overrides)
        declared = {p.name for p in param_defs}
        unknown = sorted(override_keys - declared)
        if unknown:
            raise AlphaLoadError(
                f"{source}: unknown parameter_overrides key(s): {unknown} — refusing silent drops"
            )

        for pdef in param_defs:
            value = overrides.get(pdef.name, pdef.default)
            errs = pdef.validate_value(value)
            errors.extend(errs)
            params[pdef.name] = value

        if errors:
            raise AlphaLoadError(f"{source}: parameter validation failed: " + "; ".join(errors))
        return params

    # ── Regime engine resolution ──────────────────────────────

    @staticmethod
    def _validate_gate_posterior_states(
        regime_gate: RegimeGate,
        regime_engine: RegimeEngine | None,
        source: str,
    ) -> None:
        """Reject ``P(<state>)`` references to names the engine cannot emit.

        Audit P1-2.  No-op when no engine is resolvable (the gate's state
        names cannot be checked against any taxonomy in that case).
        """
        if regime_engine is None:
            return
        referenced = regime_gate.referenced_posterior_states()
        if not referenced:
            return
        known = frozenset(regime_engine.state_names)
        unknown = sorted(referenced - known)
        if unknown:
            raise AlphaLoadError(
                f"{source}: regime_gate references unknown regime state(s) "
                f"{unknown} in P(...); engine {type(regime_engine).__name__} "
                f"publishes state_names {sorted(known)}.  Fix the spelling "
                f"in on_condition/off_condition or align the engine taxonomy."
            )

    def _resolve_regime_engine(
        self,
        regimes_raw: dict[str, Any] | None,
        source: str,
    ) -> RegimeEngine | None:
        if regimes_raw is None:
            return self._regime_engine

        engine_name = regimes_raw.get("engine")
        if engine_name is None or engine_name == "null":
            return self._regime_engine

        if self._regime_engine is not None:
            return self._regime_engine

        try:
            return get_regime_engine(
                engine_name,
                **dict(self._regime_engine_options),
            )
        except KeyError as exc:
            raise AlphaLoadError(f"{source}: {exc}") from exc
        except TypeError as exc:
            raise AlphaLoadError(
                f"{source}: invalid regime_engine_options for engine {engine_name!r}: {exc}"
            ) from exc

    # ── Namespace construction ────────────────────────────────

    def _build_namespace(
        self,
        alpha_id: str,
        regime_engine: RegimeEngine | None,
    ) -> dict[str, Any]:
        ns: dict[str, Any] = {
            **_SAFE_BUILTINS,
            "__builtins__": {},
            "Signal": Signal,
            "SignalDirection": SignalDirection,
            "NBBOQuote": NBBOQuote,
            "Trade": Trade,
            "LONG": SignalDirection.LONG,
            "SHORT": SignalDirection.SHORT,
            "FLAT": SignalDirection.FLAT,
            "alpha_id": alpha_id,
        }
        if regime_engine is not None:
            ns["regime_posteriors"] = regime_engine.current_state
            ns["regime_state_names"] = regime_engine.state_names
        return ns


# ── Lazy event imports for PORTFOLIO inline construct() namespaces ─────


def _import_cross_sectional_context() -> Any:
    from feelies.core.events import CrossSectionalContext as _CSC

    return _CSC


def _import_sized_position_intent() -> Any:
    from feelies.core.events import SizedPositionIntent as _SPI

    return _SPI


def _import_target_position() -> Any:
    from feelies.core.events import TargetPosition as _TP

    return _TP
