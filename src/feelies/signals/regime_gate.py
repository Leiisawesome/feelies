"""Safe expression evaluator and hysteresis latch for regime gates.

Expressions are parsed once and evaluated without ``eval``. Bindings expose
regime probabilities, sensor values, z-scores, percentiles, dominance, entropy,
percentile literals, basic arithmetic and comparisons, plus ``abs``, ``min``,
and ``max``. All other AST constructs are rejected.

Each alpha-symbol gate moves OFF→ON on its entry condition and ON→OFF on its
exit condition. When neither condition passes, hysteresis preserves the state.
"""

from __future__ import annotations

import ast
import logging
import re
from typing import Any, Mapping

_LOGGER = logging.getLogger(__name__)


# ── Errors ──────────────────────────────────────────────────────────────


class RegimeGateError(Exception):
    """Base class for regime-gate failures (parse, evaluate, lookup)."""


class UnsafeExpressionError(RegimeGateError):
    """Raised when the DSL parse encounters a forbidden AST node.

    The error message names the offending node type and the line
    number from the source string so YAML authors can locate the
    problem without external tooling.
    """


class UnknownIdentifierError(RegimeGateError):
    """Raised at evaluation when an identifier resolves to nothing.

    Distinct from :class:`UnsafeExpressionError` because the
    *expression* is well-formed — the runtime binding is just
    missing.  Bindings come from the snapshot + regime; a missing
    sensor reading is a sign of cold-start or warm-up incomplete and
    callers typically suppress emission rather than crash.

    ``missing_binding_token`` is set when the missing name is a sensor /
    feature binding (scalar, ``*_percentile``, or ``*_zscore``) rather
    than an unavailable regime object — consumers may log those at
    DEBUG during sensor warm-up.
    """

    missing_binding_token: str | None

    def __init__(
        self,
        message: str,
        *,
        missing_binding_token: str | None = None,
    ) -> None:
        super().__init__(message)
        self.missing_binding_token = missing_binding_token


class UnknownRegimeStateError(RegimeGateError):
    """Raised when ``P(<name>)`` references an undeclared state name.

    Per §5.4: the engine's ``state_names`` is the source of truth.
    Misspellings (``P(beningn)``) fail loudly.
    """


# ── Whitelist tables ────────────────────────────────────────────────────


# Accept p0 through p100; _resolve_name rejects larger percentiles.
_PERCENTILE_LITERAL_RE = re.compile(r"^p(\d{1,3})$")
_PERCENTILE_SUFFIX = "_percentile"
_ZSCORE_SUFFIX = "_zscore"
_DOMINANT_NAME = "dominant"
_ENTROPY_NAME = "entropy"
_REGIME_FUNCTION_NAME = "P"
_SAFE_FUNCTIONS: frozenset[str] = frozenset({"abs", "min", "max"})
_SAFE_FUNCTIONS_AND_REGIME: frozenset[str] = _SAFE_FUNCTIONS | {_REGIME_FUNCTION_NAME}

# AST node types tolerated by the validator.  Anything not in this
# set raises :class:`UnsafeExpressionError`.
_ALLOWED_NODES: tuple[type[ast.AST], ...] = (
    ast.Expression,
    ast.BoolOp,
    ast.And,
    ast.Or,
    ast.UnaryOp,
    ast.Not,
    ast.USub,
    ast.UAdd,
    ast.BinOp,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.Mod,
    ast.FloorDiv,
    ast.Compare,
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
    ast.Constant,
    ast.Name,
    ast.Load,
    ast.Call,
)


# ── Bindings — runtime resolution context ───────────────────────────────


class Bindings:
    """Read-only runtime values exposed to the gate evaluator.

    Missing identifiers raise :class:`UnknownIdentifierError`; they never
    default to zero. Regime bindings are unavailable below the configured
    discriminability floor, causing the gate to fail closed.
    """

    __slots__ = ("regime", "sensor_values", "percentiles", "zscores", "min_discriminability")

    def __init__(
        self,
        *,
        regime: Any,
        sensor_values: Mapping[str, float],
        percentiles: Mapping[str, float] | None = None,
        zscores: Mapping[str, float] | None = None,
        min_discriminability: float = 0.0,
    ) -> None:
        self.regime = regime
        self.sensor_values = sensor_values
        self.percentiles = percentiles or {}
        self.zscores = zscores or {}
        self.min_discriminability = min_discriminability


# ── Compilation ─────────────────────────────────────────────────────────


def compile_expression(source: str) -> ast.Expression:
    """Parse and validate a regime-gate expression string.

    Returns the validated AST tree.  Raises
    :class:`UnsafeExpressionError` on any forbidden node.

    The returned AST is safe to evaluate against arbitrary
    :class:`Bindings` — every node has been pre-screened.
    """
    src = (source or "").strip()
    if not src:
        raise UnsafeExpressionError("regime-gate expression must be non-empty")
    # Normalize the human-friendly capitalised connectives used in the
    # design-doc examples ("P(benign) > 0.7 AND vpin < p40") into
    # Python keyword form so the standard ``ast`` parser accepts them.
    src_for_parse = _normalize_logical_keywords(src)
    try:
        tree = ast.parse(src_for_parse, mode="eval")
    except SyntaxError as exc:
        raise UnsafeExpressionError(
            f"regime-gate expression failed to parse: {exc.msg} "
            f"(line {exc.lineno}, offset {exc.offset})"
        ) from exc

    _validate(tree)
    return tree


_LOGICAL_RE = re.compile(r"\b(AND|OR|NOT)\b")


def _normalize_logical_keywords(src: str) -> str:
    """Lowercase ``AND``/``OR``/``NOT`` so the Python parser accepts them.

    Other identifiers (sensor names, ``dominant``, ``P``) are left
    untouched so identifier-level case sensitivity is preserved.
    """
    return _LOGICAL_RE.sub(lambda m: m.group(0).lower(), src)


def _validate(tree: ast.AST) -> None:
    """Walk *tree*; raise :class:`UnsafeExpressionError` on any
    forbidden node or function call outside the whitelist."""
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            raise UnsafeExpressionError(
                f"regime-gate expression contains forbidden node "
                f"{type(node).__name__!r}; only safe boolean / "
                f"comparison / arithmetic / Name / Call(abs|min|max|P) "
                f"nodes are permitted"
            )
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name):
                raise UnsafeExpressionError(
                    "regime-gate expression contains a Call whose "
                    "callee is not a bare identifier; attribute "
                    "access is forbidden"
                )
            if node.func.id not in _SAFE_FUNCTIONS_AND_REGIME:
                raise UnsafeExpressionError(
                    f"regime-gate expression calls forbidden function "
                    f"{node.func.id!r}; whitelist is "
                    f"{sorted(_SAFE_FUNCTIONS_AND_REGIME)}"
                )
            if node.keywords:
                raise UnsafeExpressionError(
                    f"regime-gate expression passes keyword arguments "
                    f"to {node.func.id!r}; only positional args allowed"
                )
            if node.func.id == _REGIME_FUNCTION_NAME:
                if len(node.args) != 1 or not isinstance(node.args[0], ast.Name):
                    raise UnsafeExpressionError(
                        "regime-gate expression: P(...) must take "
                        "exactly one bare identifier (regime state "
                        "name)"
                    )


# ── Evaluation ──────────────────────────────────────────────────────────


def evaluate(tree: ast.Expression, bindings: Bindings) -> Any:
    """Evaluate a previously :func:`compile_expression`-validated AST.

    Returns the expression value (typically a bool, but may be a
    numeric scalar for use inside a comparison).  Raises one of:

    - :class:`UnknownIdentifierError` when a sensor / percentile /
      z-score binding is missing.
    - :class:`UnknownRegimeStateError` when ``P(<name>)`` references
      a state name not in ``bindings.regime.state_names``.
    """
    return _eval_node(tree.body, bindings)


def _eval_node(node: ast.AST, b: Bindings) -> Any:
    if isinstance(node, ast.Constant):
        return node.value

    if isinstance(node, ast.Name):
        return _resolve_name(node.id, b)

    if isinstance(node, ast.UnaryOp):
        operand = _eval_node(node.operand, b)
        if isinstance(node.op, ast.Not):
            return not operand
        if isinstance(node.op, ast.USub):
            return -operand
        if isinstance(node.op, ast.UAdd):
            return +operand
        raise UnsafeExpressionError(
            f"regime-gate evaluator: unsupported unary op {type(node.op).__name__!r}"
        )

    if isinstance(node, ast.BoolOp):
        if isinstance(node.op, ast.And):
            for child in node.values:
                if not _eval_node(child, b):
                    return False
            return True
        if isinstance(node.op, ast.Or):
            for child in node.values:
                if _eval_node(child, b):
                    return True
            return False
        raise UnsafeExpressionError(
            f"regime-gate evaluator: unsupported boolean op {type(node.op).__name__!r}"
        )

    if isinstance(node, ast.BinOp):
        left = _eval_node(node.left, b)
        right = _eval_node(node.right, b)
        op = node.op
        if isinstance(op, ast.Add):
            return left + right
        if isinstance(op, ast.Sub):
            return left - right
        if isinstance(op, ast.Mult):
            return left * right
        if isinstance(op, ast.Div):
            return left / right
        if isinstance(op, ast.Mod):
            return left % right
        if isinstance(op, ast.FloorDiv):
            return left // right
        raise UnsafeExpressionError(
            f"regime-gate evaluator: unsupported binary op {type(op).__name__!r}"
        )

    if isinstance(node, ast.Compare):
        left = _eval_node(node.left, b)
        for cmp_op, right_node in zip(node.ops, node.comparators):
            right = _eval_node(right_node, b)
            if not _compare(cmp_op, left, right):
                return False
            left = right
        return True

    if isinstance(node, ast.Call):
        assert isinstance(node.func, ast.Name)
        name = node.func.id
        if name == _REGIME_FUNCTION_NAME:
            assert len(node.args) == 1 and isinstance(node.args[0], ast.Name)
            return _resolve_posterior(node.args[0].id, b)
        args = [_eval_node(a, b) for a in node.args]
        if name == "abs":
            return abs(*args)
        if name == "min":
            return min(*args)
        if name == "max":
            return max(*args)
        raise UnsafeExpressionError(f"regime-gate evaluator: unsupported function {name!r}")

    raise UnsafeExpressionError(f"regime-gate evaluator: unsupported node {type(node).__name__!r}")


def _compare(op: ast.cmpop, left: Any, right: Any) -> bool:
    if isinstance(op, ast.Eq):
        return bool(left == right)
    if isinstance(op, ast.NotEq):
        return bool(left != right)
    if isinstance(op, ast.Lt):
        return bool(left < right)
    if isinstance(op, ast.LtE):
        return bool(left <= right)
    if isinstance(op, ast.Gt):
        return bool(left > right)
    if isinstance(op, ast.GtE):
        return bool(left >= right)
    raise UnsafeExpressionError(
        f"regime-gate evaluator: unsupported comparison {type(op).__name__!r}"
    )


def _regime_unusable_reason(b: Bindings) -> str | None:
    """Return why a present regime is unsafe for gate bindings.

    Uncalibrated or insufficiently discriminative posteriors are treated as
    missing, causing regime-dependent gates to fail closed. Regime-free gates
    are unaffected.
    """
    regime = b.regime
    if regime is None:
        return None
    if not bool(getattr(regime, "calibrated", True)):
        return "uncalibrated (placeholder emissions; audit P0-1)"
    floor = b.min_discriminability
    if floor > 0.0:
        d = float(getattr(regime, "discriminability", float("inf")))
        if d < floor:
            return f"indiscriminate (emission separation d={d:.3f} < floor {floor:.3f}; audit R-1)"
    return None


def _resolve_name(name: str, b: Bindings) -> Any:
    """Resolve an identifier against the binding tables.

    Resolution order (deterministic, no fallback ambiguity):

      1. ``dominant``                — regime.dominant_name
      2. ``p<NN>``                   — float NN/100
      3. ``<sensor_id>_percentile``  — percentiles[<sensor_id>]
      4. ``<sensor_id>_zscore``      — zscores[<sensor_id>]
      5. ``<sensor_id>``             — sensor_values[<sensor_id>]
    """
    if name == _DOMINANT_NAME:
        if b.regime is None:
            raise UnknownIdentifierError(
                "regime-gate: 'dominant' referenced but no RegimeState "
                "is available (cold start / regime engine inactive)"
            )
        reason = _regime_unusable_reason(b)
        if reason is not None:
            raise UnknownIdentifierError(
                f"regime-gate: 'dominant' referenced but the RegimeState is "
                f"{reason}; failing entry gate safe to OFF"
            )
        return b.regime.dominant_name

    if name == _ENTROPY_NAME:
        if b.regime is None:
            raise UnknownIdentifierError(
                "regime-gate: 'entropy' referenced but no RegimeState "
                "is available (cold start / regime engine inactive)"
            )
        reason = _regime_unusable_reason(b)
        if reason is not None:
            raise UnknownIdentifierError(
                f"regime-gate: 'entropy' referenced but the RegimeState is "
                f"{reason}; failing entry gate safe to OFF"
            )
        return float(b.regime.posterior_entropy_nats)

    pmatch = _PERCENTILE_LITERAL_RE.match(name)
    if pmatch is not None:
        n = int(pmatch.group(1))
        if not 0 <= n <= 100:
            raise UnsafeExpressionError(
                f"regime-gate: percentile literal {name!r} out of range (must be p0..p100)"
            )
        return n / 100.0

    if name.endswith(_PERCENTILE_SUFFIX):
        sensor_id = name[: -len(_PERCENTILE_SUFFIX)]
        if sensor_id not in b.percentiles:
            raise UnknownIdentifierError(
                f"regime-gate: percentile {name!r} not in bindings; "
                f"known sensors with percentiles: "
                f"{sorted(b.percentiles)}",
                missing_binding_token=name,
            )
        return b.percentiles[sensor_id]

    if name.endswith(_ZSCORE_SUFFIX):
        sensor_id = name[: -len(_ZSCORE_SUFFIX)]
        if sensor_id not in b.zscores:
            raise UnknownIdentifierError(
                f"regime-gate: zscore {name!r} not in bindings; "
                f"known sensors with zscores: {sorted(b.zscores)}",
                missing_binding_token=name,
            )
        return b.zscores[sensor_id]

    if name in b.sensor_values:
        return b.sensor_values[name]

    raise UnknownIdentifierError(
        f"regime-gate: identifier {name!r} not in bindings; "
        f"available sensors: {sorted(b.sensor_values)}",
        missing_binding_token=name,
    )


def _resolve_posterior(state_name: str, b: Bindings) -> float:
    if b.regime is None:
        raise UnknownIdentifierError(
            f"regime-gate: P({state_name}) referenced but no RegimeState "
            f"is available (cold start / regime engine inactive)"
        )
    reason = _regime_unusable_reason(b)
    if reason is not None:
        # Fail OFF on unusable posteriors, but report malformed state names first.
        if state_name not in tuple(b.regime.state_names):
            raise UnknownRegimeStateError(
                f"regime-gate: state {state_name!r} not in engine "
                f"state_names {tuple(b.regime.state_names)!r}"
            )
        raise UnknownIdentifierError(
            f"regime-gate: P({state_name}) referenced but the RegimeState "
            f"is {reason}; failing entry gate safe to OFF"
        )
    state_names = tuple(b.regime.state_names)
    posteriors = tuple(b.regime.posteriors)
    if state_name not in state_names:
        raise UnknownRegimeStateError(
            f"regime-gate: state {state_name!r} not in engine state_names {state_names!r}"
        )
    return float(posteriors[state_names.index(state_name)])


# ── Hysteresis state machine ────────────────────────────────────────────


class RegimeGate:
    """Per-alpha regime gate with parsed ON/OFF expressions + hysteresis.

    The instance is constructed once at YAML-load time
    (:meth:`from_spec` parses both expressions) and is reused across
    every snapshot for every symbol the alpha covers.  Per-symbol
    ON/OFF state lives in ``self._state[symbol]`` so the gate is
    safe to share across symbols sharing the same alpha.

    Determinism (Inv-5): the only state is the per-symbol latch.
    Replay starts from ``OFF`` for every symbol; identical inputs
    therefore drive identical state transitions.

    Hysteresis semantics (regime gate DSL; see design doc §8.4):

    - When state == OFF and ``on_condition`` evaluates True → ON.
    - When state == ON  and ``off_condition`` evaluates True → OFF.
    - Otherwise state is unchanged.
    """

    __slots__ = (
        "_alpha_id",
        "_on_tree",
        "_off_tree",
        "_state",
        "_hysteresis",
        "_engine_name",
        "_params",
    )

    def __init__(
        self,
        *,
        alpha_id: str,
        on_condition: str,
        off_condition: str,
        hysteresis: Mapping[str, float] | None = None,
        engine_name: str | None = None,
        params: Mapping[str, float] | None = None,
    ) -> None:
        self._alpha_id = alpha_id
        self._engine_name = engine_name
        self._on_tree = compile_expression(on_condition)
        self._off_tree = compile_expression(off_condition)
        self._state: dict[str, bool] = {}
        self._hysteresis: dict[str, float] = dict(hysteresis or {})
        # Expose alpha parameters as gate constants; hysteresis wins collisions.
        self._params: dict[str, float] = dict(params or {})

    @property
    def alpha_id(self) -> str:
        return self._alpha_id

    @property
    def engine_name(self) -> str | None:
        return self._engine_name

    @property
    def hysteresis(self) -> Mapping[str, float]:
        return dict(self._hysteresis)

    def binding_identifier_names(self) -> frozenset[str]:
        """Names resolved via :func:`_resolve_name` that appear in ON/OFF ASTs.

        Excludes ``P(<state>)`` state labels, ``dominant``, ``entropy``,
        ``pNN`` literals,
        and hysteresis margin keys — these never correspond to
        :class:`~feelies.core.events.HorizonFeatureSnapshot` ``warm`` /
        ``stale`` entries.
        """
        raw: set[str] = set()
        for tree in (self._on_tree, self._off_tree):
            for node in ast.walk(tree):
                if isinstance(node, ast.Name):
                    raw.add(node.id)
        p_state_args = self._p_posterior_argument_names()
        raw -= p_state_args
        raw.discard(_DOMINANT_NAME)
        raw.discard(_ENTROPY_NAME)
        raw -= frozenset(self._hysteresis.keys())
        # Injected alpha-param constants are not warm sensor bindings either.
        raw -= frozenset(self._params.keys())
        lit = {n for n in raw if _PERCENTILE_LITERAL_RE.match(n) is not None}
        raw -= lit
        # Whitelisted Call func names are never binding identifiers.
        raw -= _SAFE_FUNCTIONS_AND_REGIME
        return frozenset(raw)

    def referenced_posterior_states(self) -> frozenset[str]:
        """State names referenced by any ``P(<state>)`` in the ON/OFF ASTs.

        Used by :class:`~feelies.alpha.loader.AlphaLoader` so every ``P(...)`` argument must
        name a real engine state, validated against ``engine.state_names``
        at load rather than surfacing as a runtime
        :class:`UnknownRegimeStateError` on the first evaluation.
        """
        return frozenset(self._p_posterior_argument_names())

    def _p_posterior_argument_names(self) -> set[str]:
        """State labels referenced inside ``P(...)`` calls."""
        out: set[str] = set()
        for tree in (self._on_tree, self._off_tree):
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                if not isinstance(node.func, ast.Name):
                    continue
                if node.func.id != _REGIME_FUNCTION_NAME:
                    continue
                if len(node.args) != 1 or not isinstance(node.args[0], ast.Name):
                    continue
                out.add(node.args[0].id)
        return out

    def is_on(self, symbol: str) -> bool:
        """Latched ON/OFF state for *symbol*.  ``False`` until first ON."""
        return self._state.get(symbol, False)

    def reset(self, symbol: str | None = None) -> None:
        """Reset latched state for *symbol* (or every symbol when None).

        Used by replay harnesses and unit tests; production callers
        should never need to invoke this between events.
        """
        if symbol is None:
            self._state.clear()
        else:
            self._state.pop(symbol, None)

    def evaluate(self, *, symbol: str, bindings: Bindings, mutate: bool = True) -> bool:
        """Update the latch for *symbol* and return the new state.

        Returns the **post-transition** state (True if currently ON,
        False otherwise).  Callers that need the pre-transition state
        for forensics should snapshot :meth:`is_on` first.
        Passing ``mutate=False`` evaluates the same transition rules
        without committing the resulting latch state.

        M7: When ``hysteresis`` margins are declared (e.g.
        ``posterior_margin: 0.20``) they are injected into the binding
        table as named scalar constants so that gate expressions can
        reference them directly:

            on_condition: "P(benign) > 0.7 + posterior_margin"

        Keys in ``hysteresis`` that collide with existing sensor /
        feature names in *bindings* are intentionally overridden by
        the hysteresis values \u2014 margin constants have higher
        precedence than dynamic sensor readings to avoid accidental
        capture.
        """
        # Precedence is parameters, live sensor values, then hysteresis margins.
        if self._hysteresis or self._params:
            merged = {**self._params, **bindings.sensor_values, **self._hysteresis}
            bindings = Bindings(
                regime=bindings.regime,
                sensor_values=merged,
                percentiles=bindings.percentiles,
                zscores=bindings.zscores,
                min_discriminability=bindings.min_discriminability,
            )
        currently_on = self._state.get(symbol, False)
        if currently_on:
            if self._eval(self._off_tree, bindings):
                if mutate:
                    self._state[symbol] = False
                return False
            return True
        if self._eval(self._on_tree, bindings):
            if mutate:
                self._state[symbol] = True
            return True
        return False

    @staticmethod
    def _eval(tree: ast.Expression, bindings: Bindings) -> bool:
        return bool(evaluate(tree, bindings))

    @classmethod
    def from_spec(
        cls,
        *,
        alpha_id: str,
        spec: object,
        params: Mapping[str, float] | None = None,
        strict: bool = False,
    ) -> "RegimeGate":
        """Build a :class:`RegimeGate` from the parsed YAML ``regime_gate:`` block.

        Raises :class:`UnsafeExpressionError` (sub-class of
        :class:`RegimeGateError`) if either condition fails the DSL
        validation.

        ``params`` are the alpha's resolved numeric parameter defaults; they
        are injected as named gate constants so an expression can reference a
        declared param instead of duplicating its literal threshold.

        When ``strict`` is True (loader passes ``enforce_layer_gates``), a
        ``hysteresis:`` block whose declared margins are referenced by neither
        expression is a hard :class:`RegimeGateError` rather than a warning:
        dead margin config silently
        misleads authors into thinking a band is active.
        """
        if not isinstance(spec, Mapping):
            raise RegimeGateError(
                f"alpha {alpha_id!r}: regime_gate block must be a "
                f"mapping, got {type(spec).__name__}"
            )
        spec_map: Mapping[str, Any] = spec
        on_condition = spec_map.get("on_condition")
        off_condition = spec_map.get("off_condition")
        if not isinstance(on_condition, str) or not on_condition.strip():
            raise RegimeGateError(
                f"alpha {alpha_id!r}: regime_gate.on_condition must be a non-empty string"
            )
        if not isinstance(off_condition, str) or not off_condition.strip():
            raise RegimeGateError(
                f"alpha {alpha_id!r}: regime_gate.off_condition must be a non-empty string"
            )
        hyst_block = spec_map.get("hysteresis")
        hyst: dict[str, float] = {}
        if hyst_block is not None:
            if not isinstance(hyst_block, Mapping):
                raise RegimeGateError(
                    f"alpha {alpha_id!r}: regime_gate.hysteresis must "
                    f"be a mapping, got {type(hyst_block).__name__}"
                )
            for k, v in hyst_block.items():
                hyst[str(k)] = float(v)
        engine_name = spec_map.get("regime_engine")
        gate = cls(
            alpha_id=alpha_id,
            on_condition=on_condition,
            off_condition=off_condition,
            hysteresis=hyst,
            engine_name=str(engine_name) if engine_name is not None else None,
            params=params,
        )
        # Hysteresis is explicit; unreferenced margins have no effect.
        if hyst:
            referenced = gate._referenced_identifiers()
            unreferenced = sorted(set(hyst) - referenced)
            if unreferenced:
                if strict:
                    raise RegimeGateError(
                        f"alpha {alpha_id!r}: regime_gate.hysteresis declares "
                        f"{unreferenced} but neither on_condition nor "
                        f"off_condition references any of them; the margins are "
                        f"dead config (no effect on the ON/OFF latch). Reference "
                        f"them (e.g. 'P(normal) > 0.5 + posterior_margin') or "
                        f"remove the hysteresis block."
                    )
                _LOGGER.warning(
                    "alpha %r: regime_gate.hysteresis declares %s but "
                    "neither on_condition nor off_condition references "
                    "any of them; the margins are dead config and have "
                    "no effect on the ON/OFF latch.  Either reference "
                    "them in the expressions (e.g. "
                    "'P(normal) > 0.5 + posterior_margin') or remove "
                    "the hysteresis block",
                    alpha_id,
                    unreferenced,
                )
        return gate

    def _referenced_identifiers(self) -> frozenset[str]:
        """All bare Name identifiers referenced by either condition.

        Used by :meth:`from_spec` to detect dead configuration.
        """
        seen: set[str] = set()
        for tree in (self._on_tree, self._off_tree):
            for node in ast.walk(tree):
                if isinstance(node, ast.Name):
                    seen.add(node.id)
        return frozenset(seen)


__all__ = [
    "Bindings",
    "RegimeGate",
    "RegimeGateError",
    "UnsafeExpressionError",
    "UnknownIdentifierError",
    "UnknownRegimeStateError",
    "compile_expression",
    "evaluate",
]
