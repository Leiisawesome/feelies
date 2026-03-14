"""Alpha loader — parse .alpha.yaml specs into AlphaModule instances.

The AlphaLoader is the bridge between the external quant lab's YAML
deliverables and the platform's typed protocol system.  It:

  1. Parses a single ``.alpha.yaml`` file
  2. Validates schema structure and parameter types/ranges
  3. Compiles inline Python code blocks in a sandboxed namespace
  4. Auto-flattens compound features (``return_type: list[N]``)
  5. Wraps the signal evaluate function with provenance patching
  6. Produces a ``LoadedAlphaModule`` implementing ``AlphaModule``

Security: inline code is compiled via ``compile()`` + ``exec()`` in a
restricted namespace.  No ``import``, ``open``, ``eval``, ``exec``,
``__import__``, or filesystem access is available to inline code.

Invariants preserved:
  - Inv 5 (deterministic replay): compiled code is pure functions
  - Inv 7 (typed schemas): output is standard AlphaModule protocol
  - Inv 13 (provenance): manifest carries full hypothesis + version
"""

from __future__ import annotations

import logging
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable

import yaml

from feelies.alpha.module import (
    AlphaManifest,
    AlphaModule,
    AlphaRiskBudget,
    ParameterDef,
)
from feelies.core.events import (
    FeatureVector,
    NBBOQuote,
    Signal,
    SignalDirection,
    Trade,
)
from feelies.features.definition import FeatureDefinition, WarmUpSpec
from feelies.services.regime_engine import RegimeEngine, get_regime_engine

logger = logging.getLogger(__name__)

_REQUIRED_TOP_KEYS = {"alpha_id", "version", "description", "hypothesis",
                      "falsification_criteria", "features", "signal"}

_REQUIRED_FEATURE_KEYS = {"version", "description", "computation"}

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
}

_LIST_RETURN_RE = re.compile(r"^list\[(\d+)]$")


# ── Loader errors ────────────────────────────────────────────────────


class AlphaLoadError(Exception):
    """Raised when an .alpha.yaml file fails validation or compilation."""


# ── YAML feature computation adapter ─────────────────────────────────


class _YAMLFeatureComputation:
    """Wraps compiled initial_state/update callables into FeatureComputation."""

    __slots__ = ("_initial_state_fn", "_update_fn", "_params")

    def __init__(
        self,
        initial_state_fn: Callable[[], dict[str, Any]],
        update_fn: Callable[..., Any],
        params: dict[str, Any],
    ) -> None:
        self._initial_state_fn = initial_state_fn
        self._update_fn = update_fn
        self._params = params

    def initial_state(self) -> dict[str, Any]:
        return self._initial_state_fn()

    def update(self, quote: NBBOQuote, state: dict[str, Any]) -> float:
        result = self._update_fn(quote, state, self._params)
        return float(result)


class _CompoundElementComputation:
    """Wraps one element of a compound (list-returning) feature.

    A shared computation is called once per tick; this wrapper extracts
    element [index] from the cached result.  The tick counter in state
    prevents recomputation when the engine calls each sub-feature
    sequentially within the same tick.
    """

    __slots__ = ("_shared", "_index", "_params")

    def __init__(
        self,
        shared: _SharedCompoundComputation,
        index: int,
        params: dict[str, Any],
    ) -> None:
        self._shared = shared
        self._index = index
        self._params = params

    def initial_state(self) -> dict[str, Any]:
        return {"_tick": -1, "_cached": self._shared.default_value()}

    def update(self, quote: NBBOQuote, state: dict[str, Any]) -> float:
        tick = state.get("_tick", -1)
        result = self._shared.compute_once(quote, tick, self._params)
        state["_tick"] = self._shared.current_tick
        state["_cached"] = result
        return float(result[self._index])


class _SharedCompoundComputation:
    """Shared computation for a compound feature that returns list[N].

    Called once per tick regardless of how many element wrappers exist.
    """

    __slots__ = ("_initial_state_fn", "_update_fn", "_n_elements",
                 "_states", "_tick_counter", "_last_results")

    def __init__(
        self,
        initial_state_fn: Callable[[], dict[str, Any]],
        update_fn: Callable[..., Any],
        n_elements: int,
    ) -> None:
        self._initial_state_fn = initial_state_fn
        self._update_fn = update_fn
        self._n_elements = n_elements
        self._states: dict[str, dict[str, Any]] = {}
        self._tick_counter: int = 0
        self._last_results: dict[str, list[float]] = {}

    @property
    def current_tick(self) -> int:
        return self._tick_counter

    def default_value(self) -> list[float]:
        return [0.0] * self._n_elements

    def compute_once(
        self, quote: NBBOQuote, caller_tick: int, params: dict[str, Any]
    ) -> list[float]:
        symbol = quote.symbol
        if symbol not in self._states:
            self._states[symbol] = self._initial_state_fn()

        if caller_tick < self._tick_counter:
            self._tick_counter += 1
            result = self._update_fn(quote, self._states[symbol], params)
            result_list = [float(v) for v in result]
            self._last_results[symbol] = result_list
            return result_list

        cached = self._last_results.get(symbol)
        if cached is not None:
            return cached

        self._tick_counter += 1
        result = self._update_fn(quote, self._states[symbol], params)
        result_list = [float(v) for v in result]
        self._last_results[symbol] = result_list
        return result_list


# ── Loaded alpha module ──────────────────────────────────────────────


class LoadedAlphaModule:
    """Concrete AlphaModule produced by the AlphaLoader.

    Satisfies the AlphaModule protocol so it can be registered with
    AlphaRegistry without any special handling.
    """

    __slots__ = ("_manifest", "_feature_defs", "_evaluate_fn", "_params")

    def __init__(
        self,
        manifest: AlphaManifest,
        feature_defs: list[FeatureDefinition],
        evaluate_fn: Callable[[FeatureVector, dict[str, Any]], Signal | None],
        params: dict[str, Any],
    ) -> None:
        self._manifest = manifest
        self._feature_defs = feature_defs
        self._evaluate_fn = evaluate_fn
        self._params = params

    @property
    def manifest(self) -> AlphaManifest:
        return self._manifest

    def feature_definitions(self) -> Sequence[FeatureDefinition]:
        return self._feature_defs

    def evaluate(self, features: FeatureVector) -> Signal | None:
        result = self._evaluate_fn(features, self._params)
        if result is None:
            return None
        if not isinstance(result, Signal):
            return None
        if not hasattr(result, "correlation_id") or result.correlation_id == "":
            result = replace(
                result,
                correlation_id=features.correlation_id,
                sequence=features.sequence,
            )
        return result

    def validate(self) -> list[str]:
        errors: list[str] = []
        for pdef in self._manifest.parameter_schema:
            value = self._params.get(pdef.name)
            if value is None:
                value = pdef.default
            errors.extend(pdef.validate_value(value))
        return errors


# ── AlphaLoader ──────────────────────────────────────────────────────


class AlphaLoader:
    """Parses .alpha.yaml files and produces LoadedAlphaModule instances."""

    def __init__(
        self,
        regime_engine: RegimeEngine | None = None,
    ) -> None:
        self._regime_engine = regime_engine

    def load(
        self,
        path: str | Path,
        param_overrides: dict[str, Any] | None = None,
    ) -> LoadedAlphaModule:
        """Load an alpha specification from a YAML file.

        Raises ``AlphaLoadError`` on any validation or compilation failure.
        """
        path = Path(path)
        try:
            raw = path.read_text(encoding="utf-8")
            spec = yaml.safe_load(raw)
        except Exception as exc:
            raise AlphaLoadError(f"Failed to read {path}: {exc}") from exc

        return self.load_from_dict(spec, param_overrides=param_overrides,
                                   source=str(path))

    def load_from_dict(
        self,
        spec: dict[str, Any],
        param_overrides: dict[str, Any] | None = None,
        source: str = "<dict>",
    ) -> LoadedAlphaModule:
        """Load an alpha specification from a pre-parsed dict."""
        self._validate_schema(spec, source)

        alpha_id = spec["alpha_id"]
        param_defs = self._parse_parameters(spec.get("parameters", {}), source)
        params = self._resolve_params(param_defs, param_overrides or {}, source)

        regime_engine = self._resolve_regime_engine(spec.get("regimes"), source)

        namespace = self._build_namespace(alpha_id, regime_engine)

        features_raw = spec["features"]
        feature_list = self._normalize_features(features_raw, source)
        feature_defs = self._compile_features(
            feature_list, params, namespace, source
        )

        evaluate_fn = self._compile_signal(
            spec["signal"], alpha_id, namespace, source
        )

        required_features = frozenset(
            fd.feature_id for fd in feature_defs
        )

        symbols_raw = spec.get("symbols")
        symbols = (
            frozenset(symbols_raw)
            if symbols_raw is not None
            else None
        )

        risk_budget_raw = spec.get("risk_budget", {})
        risk_budget = AlphaRiskBudget(
            max_position_per_symbol=risk_budget_raw.get("max_position_per_symbol", 100),
            max_gross_exposure_pct=risk_budget_raw.get("max_gross_exposure_pct", 5.0),
            max_drawdown_pct=risk_budget_raw.get("max_drawdown_pct", 1.0),
            capital_allocation_pct=risk_budget_raw.get("capital_allocation_pct", 10.0),
        )

        manifest = AlphaManifest(
            alpha_id=alpha_id,
            version=spec["version"],
            description=spec["description"],
            hypothesis=spec["hypothesis"],
            falsification_criteria=tuple(spec["falsification_criteria"]),
            required_features=required_features,
            symbols=symbols,
            parameters=params,
            parameter_schema=tuple(param_defs),
            risk_budget=risk_budget,
        )

        return LoadedAlphaModule(
            manifest=manifest,
            feature_defs=list(feature_defs),
            evaluate_fn=evaluate_fn,
            params=params,
        )

    # ── Schema validation ─────────────────────────────────────

    def _validate_schema(self, spec: dict[str, Any], source: str) -> None:
        if not isinstance(spec, dict):
            raise AlphaLoadError(f"{source}: root must be a YAML mapping")

        missing = _REQUIRED_TOP_KEYS - set(spec.keys())
        if missing:
            raise AlphaLoadError(
                f"{source}: missing required top-level keys: "
                + ", ".join(sorted(missing))
            )

    # ── Parameter resolution ──────────────────────────────────

    def _parse_parameters(
        self, params_raw: dict[str, Any], source: str
    ) -> list[ParameterDef]:
        defs: list[ParameterDef] = []
        for name, pspec in params_raw.items():
            if not isinstance(pspec, dict):
                raise AlphaLoadError(
                    f"{source}: parameter '{name}' must be a mapping "
                    f"with type/default/description"
                )
            param_type = str(pspec.get("type", "float"))
            default = pspec.get("default")
            if default is None:
                raise AlphaLoadError(
                    f"{source}: parameter '{name}' missing 'default'"
                )
            range_raw = pspec.get("range")
            param_range = (
                (float(range_raw[0]), float(range_raw[1]))
                if range_raw is not None
                else None
            )
            defs.append(ParameterDef(
                name=name,
                param_type=param_type,
                default=default,
                range=param_range,
                description=str(pspec.get("description", "")),
            ))
        return defs

    def _resolve_params(
        self,
        param_defs: list[ParameterDef],
        overrides: dict[str, Any],
        source: str,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {}
        errors: list[str] = []
        for pdef in param_defs:
            value = overrides.get(pdef.name, pdef.default)
            errs = pdef.validate_value(value)
            errors.extend(errs)
            params[pdef.name] = value

        if errors:
            raise AlphaLoadError(
                f"{source}: parameter validation failed: "
                + "; ".join(errors)
            )
        return params

    # ── Regime engine resolution ──────────────────────────────

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
            return get_regime_engine(engine_name)
        except KeyError as exc:
            raise AlphaLoadError(f"{source}: {exc}") from exc

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
            ns["regime_engine"] = regime_engine
        return ns

    # ── Feature normalization (list or dict) ──────────────────

    def _normalize_features(
        self,
        features_raw: Any,
        source: str,
    ) -> list[dict[str, Any]]:
        if isinstance(features_raw, list):
            for i, item in enumerate(features_raw):
                if not isinstance(item, dict):
                    raise AlphaLoadError(
                        f"{source}: features[{i}] must be a mapping"
                    )
                if "feature_id" not in item:
                    raise AlphaLoadError(
                        f"{source}: features[{i}] missing 'feature_id'"
                    )
            return features_raw

        if isinstance(features_raw, dict):
            normalized: list[dict[str, Any]] = []
            for name, fspec in features_raw.items():
                if not isinstance(fspec, dict):
                    raise AlphaLoadError(
                        f"{source}: feature '{name}' must be a mapping"
                    )
                entry = {"feature_id": name, **fspec}
                normalized.append(entry)
            return normalized

        raise AlphaLoadError(
            f"{source}: 'features' must be a list or mapping"
        )

    # ── Feature compilation ───────────────────────────────────

    def _compile_features(
        self,
        feature_list: list[dict[str, Any]],
        params: dict[str, Any],
        namespace: dict[str, Any],
        source: str,
    ) -> list[FeatureDefinition]:
        all_defs: list[FeatureDefinition] = []

        for fspec in feature_list:
            fid = fspec["feature_id"]
            missing = _REQUIRED_FEATURE_KEYS - set(fspec.keys())
            if missing:
                raise AlphaLoadError(
                    f"{source}: feature '{fid}' missing keys: "
                    + ", ".join(sorted(missing))
                )

            code = fspec["computation"]
            ns = dict(namespace)
            try:
                compiled = compile(code, f"<{source}:{fid}>", "exec")
                exec(compiled, ns)  # noqa: S102
            except SyntaxError as exc:
                raise AlphaLoadError(
                    f"{source}: feature '{fid}' syntax error: {exc}"
                ) from exc

            init_fn = ns.get("initial_state")
            update_fn = ns.get("update")
            if init_fn is None or update_fn is None:
                raise AlphaLoadError(
                    f"{source}: feature '{fid}' must define "
                    f"initial_state() and update(quote, state, params)"
                )

            warm_up = self._resolve_warm_up(
                fspec.get("warm_up", {}), params, source, fid
            )
            depends_on = frozenset(fspec.get("depends_on", []))
            version = str(fspec.get("version", "1.0.0"))
            description = str(fspec.get("description", ""))

            return_type = str(fspec.get("return_type", "float"))
            m = _LIST_RETURN_RE.match(return_type)

            if m:
                n_elements = int(m.group(1))
                shared = _SharedCompoundComputation(init_fn, update_fn, n_elements)
                for idx in range(n_elements):
                    sub_id = f"{fid}_{idx}"
                    comp = _CompoundElementComputation(shared, idx, params)
                    all_defs.append(FeatureDefinition(
                        feature_id=sub_id,
                        version=version,
                        description=f"{description} [element {idx}]",
                        depends_on=depends_on,
                        warm_up=warm_up,
                        compute=comp,
                    ))
            else:
                comp = _YAMLFeatureComputation(init_fn, update_fn, params)
                all_defs.append(FeatureDefinition(
                    feature_id=fid,
                    version=version,
                    description=description,
                    depends_on=depends_on,
                    warm_up=warm_up,
                    compute=comp,
                ))

        return all_defs

    def _resolve_warm_up(
        self,
        warm_up_raw: dict[str, Any],
        params: dict[str, Any],
        source: str,
        feature_id: str,
    ) -> WarmUpSpec:
        min_events_raw = warm_up_raw.get("min_events", 0)
        min_duration_ns = int(warm_up_raw.get("min_duration_ns", 0))

        if isinstance(min_events_raw, str):
            try:
                min_events = int(eval(min_events_raw, {"params": params}))  # noqa: S307
            except Exception as exc:
                raise AlphaLoadError(
                    f"{source}: feature '{feature_id}' warm_up.min_events "
                    f"expression failed: {exc}"
                ) from exc
        else:
            min_events = int(min_events_raw)

        return WarmUpSpec(min_events=min_events, min_duration_ns=min_duration_ns)

    # ── Signal compilation ────────────────────────────────────

    def _compile_signal(
        self,
        signal_code: str,
        alpha_id: str,
        namespace: dict[str, Any],
        source: str,
    ) -> Callable[[FeatureVector, dict[str, Any]], Signal | None]:
        ns = dict(namespace)
        try:
            compiled = compile(signal_code, f"<{source}:signal>", "exec")
            exec(compiled, ns)  # noqa: S102
        except SyntaxError as exc:
            raise AlphaLoadError(
                f"{source}: signal code syntax error: {exc}"
            ) from exc

        evaluate_fn = ns.get("evaluate")
        if evaluate_fn is None:
            raise AlphaLoadError(
                f"{source}: signal code must define evaluate(features, params)"
            )

        return evaluate_fn
