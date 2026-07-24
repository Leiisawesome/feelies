"""Parse ``.alpha.yaml`` specs into typed layer modules.

``AlphaLoader``:

  1. Parses a single ``.alpha.yaml`` file
  2. Validates schema structure and parameter types/ranges
  3. Compiles inline Python code blocks in a sandboxed namespace
  4. Auto-flattens compound features (``return_type: list[N]``)
  5. Wraps the signal evaluate function with provenance patching
  6. Produces a :class:`LoadedSignalLayerModule` (``layer: SIGNAL``)
     or :class:`LoadedPortfolioLayerModule` (``layer: PORTFOLIO``)

Only ``SIGNAL`` and ``PORTFOLIO`` layers are accepted. Inline code runs in a
restricted namespace without imports, file access, or dynamic evaluation.
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
    parse_mechanism_caps,
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

# At most three parameters may declare an optimization range. Validation bounds
# do not count toward this limit.
_MAX_FREE_OPTIMIZATION_PARAMS: int = 3

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

# PORTFOLIO alphas use universe and signal dependencies instead of inline signals.
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

# SENSOR is reserved for platform config. Retired layers receive migration help.
_VALID_1_1_LAYERS = {"SIGNAL", "PORTFOLIO", "SENSOR"}
_ACCEPTED_LAYERS = {"SIGNAL", "PORTFOLIO"}
_RETIRED_LAYERS = {"LEGACY_SIGNAL"}
_LAYER_PHASE_MAP = {
    "SENSOR": "Phase 2 (sensor framework — declared in platform.yaml, not alpha YAML)",
    "SIGNAL": "Phase 3 (horizon signal engine)",
    "PORTFOLIO": "Phase 4 (composition layer)",
}

# Closed taxonomy for declared trend-formation mechanisms.
_TREND_MECHANISM_FAMILIES = {
    "KYLE_INFO",
    "INVENTORY",
    "HAWKES_SELF_EXCITE",
    "LIQUIDITY_STRESS",
    "SCHEDULED_FLOW",
}

# Stage-0 dual-permission actuation modes (design rev 5 §3.4).
#   ``gate_close_flat``     — default; the SIGNAL engine flattens immediately on
#                             the clean gate-OFF transition (today's behaviour,
#                             bit-identical).
#   ``decouple_caps_only``  — Stage-0 opt-in; the clean gate-OFF FLAT is decoupled
#                             into a bounded deferral, so both ceiling fields
#                             (``max_hold_after_safe_off`` and
#                             ``hard_exit_age_seconds``) are mandatory.
_SAFETY_EXIT_POLICY_DEFAULT_MODE: str = "gate_close_flat"
_SAFETY_EXIT_POLICY_DECOUPLE_MODE: str = "decouple_caps_only"
_SAFETY_EXIT_POLICY_MODES: frozenset[str] = frozenset(
    {_SAFETY_EXIT_POLICY_DEFAULT_MODE, _SAFETY_EXIT_POLICY_DECOUPLE_MODE}
)

# Below 30 seconds, L1 sampling cannot support a meaningful horizon snapshot.
# PlatformConfig remains the authoritative horizon whitelist.
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

    Dispatch in :meth:`load_from_dict`:

    * ``layer: SIGNAL``     → :class:`LoadedSignalLayerModule`
    * ``layer: PORTFOLIO``  → :class:`LoadedPortfolioLayerModule`

    Other layers (including retired ``LEGACY_SIGNAL``) are rejected by
    :meth:`_validate_schema`.
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
        Returns ``LoadedSignalLayerModule`` or ``LoadedPortfolioLayerModule``
        based on ``layer:``.
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

        - ``SIGNAL``    → :class:`LoadedSignalLayerModule`
        - ``PORTFOLIO`` → :class:`LoadedPortfolioLayerModule`
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

        # Every accepted layer must have an explicit dispatch branch.
        raise AssertionError(  # pragma: no cover
            f"{source}: layer '{layer_value}' passed _validate_schema "
            f"but has no dispatch branch in load_from_dict. "
            f"This is a loader bug — please file an issue."
        )

    def _load_signal_layer(
        self,
        spec: dict[str, Any],
        *,
        param_overrides: dict[str, Any] | None,
        source: str,
    ) -> LoadedSignalLayerModule:
        """Load a schema-1.1 ``layer: SIGNAL`` alpha.

        1. **No inline features** — ``depends_on_sensors`` + SensorRegistry.
        2. **3-arg evaluate** — ``evaluate(snapshot, regime, params)`` on
           :class:`HorizonFeatureSnapshot`.
        3. **Mandatory** ``cost_arithmetic`` and ``regime_gate`` blocks.
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

        # Expose numeric parameters to gates; exclude bool despite its int subclass.
        gate_params = {
            name: float(value)
            for name, value in params.items()
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        }
        try:
            regime_gate = RegimeGate.from_spec(
                alpha_id=alpha_id,
                spec=spec.get("regime_gate"),
                params=gate_params,
                strict=self._enforce_layer_gates,
            )
        except RegimeGateError as exc:
            raise AlphaLoadError(f"{source}: {exc}") from exc

        regime_engine = self._resolve_regime_engine(spec.get("regimes"), source)
        # Validate posterior state names at load time when an engine is available.
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
        # Validate hazard regime names against the resolved engine taxonomy.
        hazard_known_states = (
            frozenset(regime_engine.state_names) if regime_engine is not None else None
        )
        hazard_exit_block = self._parse_hazard_exit_block(
            spec.get("hazard_exit"), source, hazard_known_states
        )
        safety_exit_policy_block = self._parse_safety_exit_policy_block(
            spec.get("safety_exit_policy"), source
        )
        decouple_gate_close = (
            safety_exit_policy_block is not None
            and safety_exit_policy_block.get("mode") == _SAFETY_EXIT_POLICY_DECOUPLE_MODE
        )
        promotion_overrides = self._parse_promotion_block(spec.get("promotion"), source)
        lifecycle_cap = self._parse_lifecycle_state(spec.get("lifecycle_state"), source)
        trend_enum, expected_half_life = self._extract_trend_metadata(
            trend_mechanism_block,
            source,
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
            safety_exit_policy=safety_exit_policy_block,
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
            # Retain source so required_warm can follow actual value reads.
            signal_source=str(spec["signal"]),
            decouple_gate_close=decouple_gate_close,
        )

    def _load_portfolio_layer(
        self,
        spec: dict[str, Any],
        *,
        param_overrides: dict[str, Any] | None,
        source: str,
    ) -> LoadedPortfolioLayerModule:
        """Load a schema-1.1 ``layer: PORTFOLIO`` alpha.

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
            # G12 validation only — PORTFOLIO modules do not retain cost_arith.
            CostArithmetic.from_spec(
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
            mechanism_caps = parse_mechanism_caps(consumes_raw)
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
                mechanism_caps=mechanism_caps,
                global_mechanism_cap=max_share_of_gross,
                neutralize=bool(spec.get("factor_neutralization", False)),
                consumes_mechanisms=consumes,
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
            mechanism_caps=mechanism_caps,
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
        with deterministic metadata.
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

        Expects ``evaluate(snapshot, regime, params)`` from schema 1.1.
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
        """Validate the top-level schema and dispatch by ``layer``.

        Validation order:

          1. ``spec`` is a dict.
          2. Read ``schema_version``; reject if missing or unsupported.
             Only ``"1.1"`` is supported.
          3. Read ``layer`` (mandatory in 1.1).
          4. Dispatch on layer:
             - LEGACY_SIGNAL → reject with a migration pointer.
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

        # Retired layers get specific migration guidance.
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
        """Parse the optional ``trend_mechanism:`` block.

        Enforces:
          - block is a mapping if present.
          - if ``family:`` is set, it is one of the 5 closed
            ``TrendMechanism`` names.

        Remaining fields are retained for G16. An absent block returns ``None``.
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
            "applies_to_regimes",
        }
    )

    # Translate known aliases with a warning instead of silently ignoring them.
    _HAZARD_EXIT_LEGACY_KEYS: dict[str, str] = {
        "posterior_drop_threshold": "hazard_score_threshold",
    }

    def _parse_hazard_exit_block(
        self,
        block: Any,
        source: str,
        known_state_names: frozenset[str] | None = None,
    ) -> dict[str, Any] | None:
        """Parse the optional ``hazard_exit:`` block.

        Unknown keys raise :class:`AlphaLoadError`. Known aliases are
        renamed with a warning.

        Value types are coerced and range-checked so bootstrap can
        trust the parsed block:

        * ``enabled``                — bool-ish (only literal True opts in)
        * ``hazard_score_threshold`` — float in (0.0, 1.0]
        * ``min_age_seconds``        — int ≥ 0
        * ``hard_exit_age_seconds``  — int > 0 (or omitted → derived
          from ``2 × expected_half_life_seconds`` at composition time)
        * ``applies_to_regimes``     — optional list of departure filters
          (§20.5.3 / §20.7.1).  Each entry is either a transition
          ``"<departing> -> <incoming>"`` or a bare departing-state name
          ``"<departing>"`` (any incoming).  Omitted / empty ⇒ the exit
          fires on **all** qualifying departures (backward-compatible).
          When ``known_state_names`` is supplied (SIGNAL path, engine
          resolved) every referenced state is checked against the
          engine taxonomy so a typo cannot silently disable an exit
          filter.
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

        if "applies_to_regimes" in normalized:
            normalized["applies_to_regimes"] = self._normalize_applies_to_regimes(
                normalized["applies_to_regimes"], source, known_state_names
            )

        return normalized

    @staticmethod
    def _normalize_applies_to_regimes(
        value: Any,
        source: str,
        known_state_names: frozenset[str] | None,
    ) -> tuple[str, ...]:
        """Validate and canonicalize ``hazard_exit.applies_to_regimes`` (§20.5.3).

        Returns a tuple of canonical strings — ``"<from> -> <to>"`` for a
        transition entry, or a bare ``"<from>"`` departing-state entry.
        """
        if not isinstance(value, (list, tuple)):
            raise AlphaLoadError(
                f"{source}: hazard_exit.applies_to_regimes must be a list of "
                f"strings, got {type(value).__name__}"
            )
        out: list[str] = []
        for entry in value:
            if not isinstance(entry, str) or not entry.strip():
                raise AlphaLoadError(
                    f"{source}: hazard_exit.applies_to_regimes entries must be "
                    f"non-empty strings, got {entry!r}"
                )
            s = entry.strip()
            states: tuple[str, ...]
            if "->" in s:
                parts = [p.strip() for p in s.split("->")]
                if len(parts) != 2 or not parts[0] or not parts[1]:
                    raise AlphaLoadError(
                        f"{source}: hazard_exit.applies_to_regimes transition "
                        f"{entry!r} must be '<departing> -> <incoming>'"
                    )
                states = (parts[0], parts[1])
                canonical = f"{parts[0]} -> {parts[1]}"
            else:
                states = (s,)
                canonical = s
            if known_state_names is not None:
                unknown = [st for st in states if st not in known_state_names]
                if unknown:
                    raise AlphaLoadError(
                        f"{source}: hazard_exit.applies_to_regimes references "
                        f"unknown regime state(s) {sorted(unknown)} in {entry!r}; "
                        f"engine publishes {sorted(known_state_names)}"
                    )
            out.append(canonical)
        return tuple(out)

    _SAFETY_EXIT_POLICY_KNOWN_KEYS: frozenset[str] = frozenset(
        {
            "mode",
            "max_hold_after_safe_off",
            "hard_exit_age_seconds",
        }
    )

    def _parse_safety_exit_policy_block(
        self,
        block: Any,
        source: str,
    ) -> dict[str, Any] | None:
        """Parse the optional ``safety_exit_policy:`` block (design rev 5 §3.4).

        Structural, single-block validation:

        * block is a mapping if present (else ``None`` — the default
          ``gate_close_flat`` behaviour, bit-identical to today).
        * unknown keys are rejected.
        * ``mode`` ∈ ``{gate_close_flat, decouple_caps_only}`` (default
          ``gate_close_flat``).
        * ``mode == decouple_caps_only`` **requires** both bounded-deferral
          ceilings, each a positive integer number of seconds:
          ``max_hold_after_safe_off`` (the deferral ceiling that turns "no
          immediate flatten" into a *bounded* delay, never a removal) **and**
          ``hard_exit_age_seconds`` (the monotonic position-age backstop).
          A ``decouple_caps_only`` alpha missing either ceiling is rejected at
          load (design §3.6: "Stage 0 without ``max_hold_after_safe_off`` or
          ``hard_exit_age_seconds`` → reject load").

        Cross-block invariants (``story_permission ⇒ mode ≠ gate_close_flat``;
        ``max_hold_after_safe_off`` ≤ the per-family half-life multiple) live in
        gate G17 of :class:`~feelies.alpha.layer_validator.LayerValidator`, which
        also has the ``trend_mechanism:`` / ``story_permission:`` context.

        Returns the normalized block with ``mode`` always present and the two
        ceilings coerced to ``int`` when supplied.
        """
        if block is None:
            return None
        if not isinstance(block, dict):
            raise AlphaLoadError(
                f"{source}: 'safety_exit_policy' must be a mapping, got {type(block).__name__}"
            )

        unknown = sorted(k for k in block if k not in self._SAFETY_EXIT_POLICY_KNOWN_KEYS)
        if unknown:
            raise AlphaLoadError(
                f"{source}: safety_exit_policy carries unknown key(s) {unknown}; "
                f"supported keys are {sorted(self._SAFETY_EXIT_POLICY_KNOWN_KEYS)}"
            )

        normalized: dict[str, Any] = {}
        mode = str(block.get("mode", _SAFETY_EXIT_POLICY_DEFAULT_MODE))
        if mode not in _SAFETY_EXIT_POLICY_MODES:
            raise AlphaLoadError(
                f"{source}: safety_exit_policy.mode {mode!r} is not supported; "
                f"must be one of {sorted(_SAFETY_EXIT_POLICY_MODES)}"
            )
        normalized["mode"] = mode

        for key in ("max_hold_after_safe_off", "hard_exit_age_seconds"):
            if key not in block or block[key] is None:
                continue
            try:
                seconds = int(block[key])
            except (TypeError, ValueError) as exc:
                raise AlphaLoadError(
                    f"{source}: safety_exit_policy.{key} must be an integer "
                    f"number of seconds, got {block[key]!r}"
                ) from exc
            if seconds <= 0:
                raise AlphaLoadError(
                    f"{source}: safety_exit_policy.{key} must be > 0, got {seconds}"
                )
            normalized[key] = seconds

        if mode == _SAFETY_EXIT_POLICY_DECOUPLE_MODE:
            missing = [
                key
                for key in ("max_hold_after_safe_off", "hard_exit_age_seconds")
                if key not in normalized
            ]
            if missing:
                raise AlphaLoadError(
                    f"{source}: safety_exit_policy.mode='{_SAFETY_EXIT_POLICY_DECOUPLE_MODE}' "
                    f"requires {missing} — both bounded-deferral ceilings are "
                    f"mandatory under decoupling so the delayed flatten stays a "
                    f"bounded delay, never a removal (design §2.3 / §3.6)."
                )

        return normalized

    def _parse_promotion_block(
        self,
        block: Any,
        source: str,
    ) -> dict[str, Any] | None:
        """Parse the optional ``promotion:`` block.

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
        """Parse an optional research-only ``lifecycle_state``.

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
            # Bounds validate values; ranges also mark optimization knobs.
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
        """Reject ``P(<state>)`` names the resolved engine cannot emit."""
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
