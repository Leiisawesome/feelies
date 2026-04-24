"""Regime gate DSL evaluator (§8.4 of three_layer_architecture.md).

Each ``layer: SIGNAL`` (and Phase-4 ``layer: PORTFOLIO``) alpha
declares a ``regime_gate:`` block:

    regime_gate:
      regime_engine: hmm_3state_fractional
      on_condition: |
          P(normal) > 0.7 AND ofi_ewma_zscore > 2.0 AND spread_z_30d < 0.5
      off_condition: |
          P(normal) < 0.5 OR spread_z_30d > 1.5
      hysteresis:
          posterior_margin: 0.20
          percentile_margin: 0.30

The conditions are **strings** evaluated under a tightly restricted
DSL — *not* arbitrary Python.  The implementation parses the string
once at YAML-load time, walks the AST, and rejects every node that is
not in the whitelist below.  Evaluation at runtime is then a pure
recursive walk over the validated AST against a fresh ``Bindings``
mapping per ``(snapshot, regime)`` pair — no string interpolation, no
``eval``, no symbol leakage.

Whitelist (§8.4):

    P(<state_name>)        — regime posterior, float in [0, 1]
    <sensor_id>            — latest SensorReading.value for that sensor
    <sensor_id>_percentile — percentile rank in rolling window
    <sensor_id>_zscore     — z-score in rolling window
    dominant               — name of the currently dominant state
    p<NN>                  — percentile literal, e.g. p40 = 0.40
    Operators: and, or, not, ==, !=, <, <=, >, >=, +, -, *, /
    Functions: abs, min, max
    Numeric / string / bool / None constants

Forbidden (raise :class:`UnsafeExpressionError` at parse time):

    Attribute, Subscript, Call (outside whitelist), Lambda, ListComp,
    SetComp, DictComp, GeneratorExp, Import / ImportFrom, FunctionDef,
    ClassDef, Yield, Await, Starred, Assign, NamedExpr, JoinedStr,
    FormattedValue.

The :class:`RegimeGate` instance also owns the **per-(alpha_id, symbol)
hysteresis state machine** (ON/OFF) — see §8.4 + §6.4 of the design
doc.  When ``on_condition`` evaluates True the gate transitions
OFF→ON; when ``off_condition`` evaluates True it transitions ON→OFF.
Both conditions can fail simultaneously (the hysteresis band) — the
state then carries forward unchanged.  This matches the hypothesis
prompt's hysteresis margin requirement (Step 6 of
``grok/prompts/hypothesis_reasoning.md``).
"""

from __future__ import annotations

import ast
import re
from typing import Any, Mapping


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
    """


class UnknownRegimeStateError(RegimeGateError):
    """Raised when ``P(<name>)`` references an undeclared state name.

    Per §5.4: the engine's ``state_names`` is the source of truth.
    Misspellings (``P(beningn)``) fail loudly.
    """


# ── Whitelist tables ────────────────────────────────────────────────────


_PERCENTILE_LITERAL_RE = re.compile(r"^p(\d{1,2})$")
_PERCENTILE_SUFFIX = "_percentile"
_ZSCORE_SUFFIX = "_zscore"
_DOMINANT_NAME = "dominant"
_REGIME_FUNCTION_NAME = "P"
_SAFE_FUNCTIONS: frozenset[str] = frozenset({"abs", "min", "max"})
_SAFE_FUNCTIONS_AND_REGIME: frozenset[str] = (
    _SAFE_FUNCTIONS | {_REGIME_FUNCTION_NAME}
)

# AST node types tolerated by the validator.  Anything not in this
# set raises :class:`UnsafeExpressionError`.
_ALLOWED_NODES: tuple[type[ast.AST], ...] = (
    ast.Expression,
    ast.BoolOp, ast.And, ast.Or,
    ast.UnaryOp, ast.Not, ast.USub, ast.UAdd,
    ast.BinOp, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod, ast.FloorDiv,
    ast.Compare,
    ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
    ast.Constant,
    ast.Name,
    ast.Load,
    ast.Call,
)


# ── Bindings — runtime resolution context ───────────────────────────────


class Bindings:
    """Snapshot+regime view consumed by the gate at evaluation time.

    All values are resolved from typed events (no dict introspection)
    so the evaluator never needs to know about source serialization.

    - ``regime`` — latest :class:`feelies.core.events.RegimeState` for
      the snapshot's symbol, or ``None`` when no posterior has been
      published yet (cold start).
    - ``sensor_values`` — latest scalar sensor reading per ``sensor_id``
      (typically copied from ``snapshot.values`` for sensor-id keys).
    - ``percentiles`` — per-``sensor_id`` percentile rank in the
      configured rolling window, suffix ``_percentile`` in the DSL.
    - ``zscores`` — per-``sensor_id`` rolling-window z-score, suffix
      ``_zscore`` in the DSL.

    All four are read-only mappings — the evaluator never mutates
    bindings.  Missing keys raise :class:`UnknownIdentifierError`
    rather than silently defaulting to 0; gate authors must declare
    every consumed sensor so the validator (G6) can DAG-check them.
    """

    __slots__ = ("regime", "sensor_values", "percentiles", "zscores")

    def __init__(
        self,
        *,
        regime: Any,
        sensor_values: Mapping[str, float],
        percentiles: Mapping[str, float] | None = None,
        zscores: Mapping[str, float] | None = None,
    ) -> None:
        self.regime = regime
        self.sensor_values = sensor_values
        self.percentiles = percentiles or {}
        self.zscores = zscores or {}


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
        raise UnsafeExpressionError(
            "regime-gate expression must be non-empty"
        )
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
                if len(node.args) != 1 or not isinstance(
                    node.args[0], ast.Name
                ):
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
            f"regime-gate evaluator: unsupported unary op "
            f"{type(node.op).__name__!r}"
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
            f"regime-gate evaluator: unsupported boolean op "
            f"{type(node.op).__name__!r}"
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
            f"regime-gate evaluator: unsupported binary op "
            f"{type(op).__name__!r}"
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
        raise UnsafeExpressionError(
            f"regime-gate evaluator: unsupported function {name!r}"
        )

    raise UnsafeExpressionError(
        f"regime-gate evaluator: unsupported node "
        f"{type(node).__name__!r}"
    )


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
        f"regime-gate evaluator: unsupported comparison "
        f"{type(op).__name__!r}"
    )


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
        return b.regime.dominant_name

    pmatch = _PERCENTILE_LITERAL_RE.match(name)
    if pmatch is not None:
        n = int(pmatch.group(1))
        if not 0 <= n <= 100:
            raise UnsafeExpressionError(
                f"regime-gate: percentile literal {name!r} out of range "
                f"(must be p0..p100)"
            )
        return n / 100.0

    if name.endswith(_PERCENTILE_SUFFIX):
        sensor_id = name[: -len(_PERCENTILE_SUFFIX)]
        if sensor_id not in b.percentiles:
            raise UnknownIdentifierError(
                f"regime-gate: percentile {name!r} not in bindings; "
                f"known sensors with percentiles: "
                f"{sorted(b.percentiles)}"
            )
        return b.percentiles[sensor_id]

    if name.endswith(_ZSCORE_SUFFIX):
        sensor_id = name[: -len(_ZSCORE_SUFFIX)]
        if sensor_id not in b.zscores:
            raise UnknownIdentifierError(
                f"regime-gate: zscore {name!r} not in bindings; "
                f"known sensors with zscores: {sorted(b.zscores)}"
            )
        return b.zscores[sensor_id]

    if name in b.sensor_values:
        return b.sensor_values[name]

    raise UnknownIdentifierError(
        f"regime-gate: identifier {name!r} not in bindings; "
        f"available sensors: {sorted(b.sensor_values)}"
    )


def _resolve_posterior(state_name: str, b: Bindings) -> float:
    if b.regime is None:
        raise UnknownIdentifierError(
            f"regime-gate: P({state_name}) referenced but no RegimeState "
            f"is available (cold start / regime engine inactive)"
        )
    state_names = tuple(b.regime.state_names)
    posteriors = tuple(b.regime.posteriors)
    if state_name not in state_names:
        raise UnknownRegimeStateError(
            f"regime-gate: state {state_name!r} not in engine "
            f"state_names {state_names!r}"
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

    Hysteresis semantics (§6 Step 6 of
    ``grok/prompts/hypothesis_reasoning.md``):

    - When state == OFF and ``on_condition`` evaluates True → ON.
    - When state == ON  and ``off_condition`` evaluates True → OFF.
    - Otherwise state is unchanged.
    """

    __slots__ = ("_alpha_id", "_on_tree", "_off_tree", "_state",
                 "_hysteresis", "_engine_name")

    def __init__(
        self,
        *,
        alpha_id: str,
        on_condition: str,
        off_condition: str,
        hysteresis: Mapping[str, float] | None = None,
        engine_name: str | None = None,
    ) -> None:
        self._alpha_id = alpha_id
        self._engine_name = engine_name
        self._on_tree = compile_expression(on_condition)
        self._off_tree = compile_expression(off_condition)
        self._state: dict[str, bool] = {}
        self._hysteresis: dict[str, float] = dict(hysteresis or {})

    @property
    def alpha_id(self) -> str:
        return self._alpha_id

    @property
    def engine_name(self) -> str | None:
        return self._engine_name

    @property
    def hysteresis(self) -> Mapping[str, float]:
        return dict(self._hysteresis)

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

    def evaluate(self, *, symbol: str, bindings: Bindings) -> bool:
        """Update the latch for *symbol* and return the new state.

        Returns the **post-transition** state (True if currently ON,
        False otherwise).  Callers that need the pre-transition state
        for forensics should snapshot :meth:`is_on` first.
        """
        currently_on = self._state.get(symbol, False)
        if currently_on:
            if self._eval(self._off_tree, bindings):
                self._state[symbol] = False
                return False
            return True
        if self._eval(self._on_tree, bindings):
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
    ) -> "RegimeGate":
        """Build a :class:`RegimeGate` from the parsed YAML ``regime_gate:`` block.

        Raises :class:`UnsafeExpressionError` (sub-class of
        :class:`RegimeGateError`) if either condition fails the DSL
        validation.
        """
        if not isinstance(spec, Mapping):
            raise RegimeGateError(
                f"alpha {alpha_id!r}: regime_gate block must be a "
                f"mapping, got {type(spec).__name__}"
            )
        spec_map: Mapping[str, Any] = spec
        on_condition = spec_map.get("on_condition")
        off_condition = spec.get("off_condition")
        if not isinstance(on_condition, str) or not on_condition.strip():
            raise RegimeGateError(
                f"alpha {alpha_id!r}: regime_gate.on_condition must be "
                f"a non-empty string"
            )
        if not isinstance(off_condition, str) or not off_condition.strip():
            raise RegimeGateError(
                f"alpha {alpha_id!r}: regime_gate.off_condition must be "
                f"a non-empty string"
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
        return cls(
            alpha_id=alpha_id,
            on_condition=on_condition,
            off_condition=off_condition,
            hysteresis=hyst,
            engine_name=str(engine_name) if engine_name is not None else None,
        )


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
