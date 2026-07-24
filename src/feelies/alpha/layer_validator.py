"""Three-layer architecture validation gates.

This module owns G1-G16 as defined in ``alphas/SCHEMA.md``.

Each newly active gate is *purely structural* — it operates on the
raw YAML spec dict without invoking the alpha loader's compilation
machinery.  Deep semantic checks (e.g. parsing the regime-gate DSL
into an AST) live in the dedicated parsers
(:class:`feelies.signals.regime_gate.RegimeGate`,
:class:`feelies.alpha.cost_arithmetic.CostArithmetic`) and are
re-used here so a single error class
(:class:`LayerValidationError`) is raised from the gate path.

Wiring
------

The loader invokes :py:meth:`LayerValidator.validate` on every
``schema_version: "1.1"`` spec after the syntactic schema check has
passed and *before* feature/signal compilation.  A raised
:class:`LayerValidationError` aborts the load with a structured error.

The validator never mutates the spec.  It only reads top-level fields
and may consult external configuration via constructor injection
(``registered_horizons`` for G7, ``known_sensor_ids`` for G6).
"""

from __future__ import annotations

import ast
import logging
from collections.abc import Sequence
from typing import Any

_logger = logging.getLogger(__name__)


# ── Exception hierarchy ─────────────────────────────────────────────────


class LayerValidationError(Exception):
    """Raised when a schema-1.1 spec violates an architectural gate.

    Distinct from :class:`feelies.alpha.loader.AlphaLoadError` so that
    callers can distinguish *syntactic* schema failures (loader) from
    *architectural* compliance failures (this module).  Both are fatal
    to ``AlphaLoader.load``; the loader catches and re-raises this class
    transparently, but downstream tooling (CI dashboards, promotion
    gates) can filter on type.
    """


class TrendMechanismValidationError(LayerValidationError):
    """Raised when a v0.3 mechanism-bound spec fails gate G16.

    Catch :class:`LayerValidationError` if you want both classes;
    catch this one for mechanism-specific handling.  Each binding
    rule from §20.6.1 raises a *distinct subclass* of this base so
    callers can attribute failures cleanly without parsing message
    strings.
    """


class UnknownTrendMechanismError(TrendMechanismValidationError):
    """G16 rule 1 — ``family`` is not one of the 5 normative enum values."""


class MechanismHalfLifeOutOfRangeError(TrendMechanismValidationError):
    """G16 rule 2 — ``expected_half_life_seconds`` falls outside the
    family's empirical half-life envelope (§20.6.1, Table §20.2)."""


class MechanismHorizonMismatchError(TrendMechanismValidationError):
    """G16 rule 3 — declared ``horizon_seconds`` is outside
    ``[0.5×, 4×]`` of ``expected_half_life_seconds``."""


class MissingMechanismSensorError(TrendMechanismValidationError):
    """G16 rule 4 — a sensor referenced under
    ``l1_signature_sensors`` is not registered in the platform's
    sensor universe at the declared version."""


class MissingFingerprintSensorError(TrendMechanismValidationError):
    """G16 rule 5 — the family's primary fingerprint sensor (per
    Table §20.4.5) is not present in ``l1_signature_sensors``."""


class MissingFailureSignatureError(TrendMechanismValidationError):
    """G16 rule 6 — ``failure_signature`` block is empty (Inv-2:
    falsifiability before testing must be operationalised at the
    mechanism layer, not just statistically)."""


class StressFamilyEntryProhibitedError(TrendMechanismValidationError):
    """G16 rule 7 — a SIGNAL alpha declaring
    ``family: LIQUIDITY_STRESS`` whose signal block can emit a
    non-FLAT entry direction (LONG/SHORT) on any code path
    reachable from a fresh-position state.  Stress family is
    permitted only as exit/de-leverage."""


class MechanismShareUnreachableError(TrendMechanismValidationError):
    """G16 rule 8 — PORTFOLIO ``trend_mechanism.consumes`` declares
    ``max_share_of_gross`` that sums below 1.0 — full book
    deployment is structurally unreachable."""


class UnauthorizedMechanismDependencyError(TrendMechanismValidationError):
    """G16 rule 9 — PORTFOLIO ``depends_on_signals`` references a
    SIGNAL whose ``trend_mechanism.family`` is not in this PORTFOLIO's
    ``trend_mechanism.consumes`` whitelist."""


class UnbackedSignatureSensorError(TrendMechanismValidationError):
    """A signature sensor is missing from the alpha's dependencies."""


class MissingTrendMechanismError(TrendMechanismValidationError):
    """G16 strict-mode (§20.6.2) — ``platform.yaml.enforce_trend_mechanism``
    is True and a schema-1.1 SIGNAL/PORTFOLIO spec failed to declare a
    ``trend_mechanism:`` block."""


# ── G16 rule data tables (§20.6.1) ──────────────────────────────────────


_NORMATIVE_FAMILY_NAMES: frozenset[str] = frozenset(
    {
        "KYLE_INFO",
        "INVENTORY",
        "HAWKES_SELF_EXCITE",
        "LIQUIDITY_STRESS",
        "SCHEDULED_FLOW",
    }
)


_FAMILY_HALF_LIFE_RANGES_SECONDS: dict[str, tuple[int, int]] = {
    "KYLE_INFO": (60, 1800),
    "INVENTORY": (5, 60),
    "HAWKES_SELF_EXCITE": (5, 60),
    "LIQUIDITY_STRESS": (30, 600),
    "SCHEDULED_FLOW": (60, 1800),
}


_FAMILY_FINGERPRINT_SENSORS: dict[str, tuple[str, ...]] = {
    # Book imbalance is the level-invariant micro-price deviation signature.
    "KYLE_INFO": ("kyle_lambda_60s", "micro_price", "book_imbalance"),
    "INVENTORY": ("quote_replenish_asymmetry",),
    "HAWKES_SELF_EXCITE": ("hawkes_intensity",),
    "LIQUIDITY_STRESS": ("vpin_50bucket", "realized_vol_30s"),
    "SCHEDULED_FLOW": ("scheduled_flow_window",),
}


_HORIZON_RATIO_FLOOR: float = 0.5
_HORIZON_RATIO_CEILING: float = 4.0
# Warn when minor half-life recalibration could cross a hard ratio bound.
_HORIZON_RATIO_WARN_MARGIN: float = 0.05


# ── G17: Stage-0 safety_exit_policy data (design rev 5 §2.8 / §3.4) ──────

# Dual-permission actuation modes (mirrors ``feelies.alpha.loader``).
_SAFETY_EXIT_POLICY_DEFAULT_MODE: str = "gate_close_flat"
_SAFETY_EXIT_POLICY_DECOUPLE_MODE: str = "decouple_caps_only"

# The Stage-0 ``max_hold_after_safe_off`` ceiling may not exceed a per-family
# multiple of the alpha's declared ``expected_half_life_seconds`` (§2.8).  The
# multiple is per *mechanism family* — not a global scalar and not per-alpha —
# because the residual edge left to harvest after safety-OFF depends on the
# family's decay shape.  Short-decay families (market-maker inventory drift,
# order-flow self-excitation) retain negligible residual by the time the gate
# flips, so their deferral ceiling is a single half-life; slower information and
# scheduled-flow families may harvest residual for a few half-lives.  Frozen at
# schema freeze; changing a value is a deliberate platform-level decision.
_FAMILY_MAX_HOLD_HALF_LIFE_MULTIPLE: dict[str, int] = {
    "KYLE_INFO": 3,
    "INVENTORY": 1,
    "HAWKES_SELF_EXCITE": 1,
    "LIQUIDITY_STRESS": 2,
    "SCHEDULED_FLOW": 2,
}


_STRESS_FAMILY: str = "LIQUIDITY_STRESS"
_NON_FLAT_DIRECTIONS: frozenset[str] = frozenset({"LONG", "SHORT"})


# ── Active-gate constants ──────────────────────────────────────────────


# Fallback horizon set when the loader has no platform-specific values.
DEFAULT_REGISTERED_HORIZONS: frozenset[int] = frozenset({30, 120, 300, 900, 1800})

# G5 / G8: AST node types and bare names that are forbidden in inline
# ``signal:`` and ``computation:`` blocks.  These are the same
# constructs the regime-gate DSL refuses; we factor them here so the
# signal-purity check is independently testable.
_BANNED_SIGNAL_AST_NODES: tuple[type[ast.AST], ...] = (
    ast.Import,
    ast.ImportFrom,
    ast.Global,
    ast.Nonlocal,
)
_BANNED_SIGNAL_NAMES: frozenset[str] = frozenset(
    {
        "exec",
        "eval",
        "compile",
        "open",
        "__import__",
        "globals",
        "locals",
        "vars",
        "input",
        "breakpoint",
        "exit",
        "quit",
    }
)


class LayerValidator:
    """Architectural-compliance gates for schema-1.1 alpha specs."""

    def __init__(
        self,
        *,
        registered_horizons: frozenset[int] | None = None,
        known_sensor_ids: frozenset[str] | None = None,
        enforce_trend_mechanism: bool = False,
        enforce_layer_gates: bool = True,
    ) -> None:
        """Construct a validator with optional platform-context overrides.

        - ``registered_horizons``: set of allowed ``horizon_seconds``
          values.  Defaults to :data:`DEFAULT_REGISTERED_HORIZONS` so
          the gate has a sane refusal even outside bootstrap.  Passing
          a non-default set lets the bootstrap layer reject SIGNAL
          alphas whose horizon is not provisioned in the running
          platform.
        - ``known_sensor_ids``: set of sensor IDs the platform has
          available.  When provided, G6 asserts every entry in
          ``depends_on_sensors`` resolves; when ``None`` the check
          is skipped because the platform may load alphas before the registry.
        """
        self._registered_horizons = (
            registered_horizons if registered_horizons is not None else DEFAULT_REGISTERED_HORIZONS
        )
        self._known_sensor_ids = known_sensor_ids
        self._enforce_trend_mechanism = bool(enforce_trend_mechanism)
        # When False, G1 and G3 downgrade to WARNINGs (research escape
        # hatch).  G9 / G10 / G11 are *always* blocking — they are
        # data-integrity gates whose violation would silently produce
        # wrong-numbered intents.  Default True (production posture).
        self._enforce_layer_gates = bool(enforce_layer_gates)

    def _softly(
        self,
        check: Any,
        spec: dict[str, Any],
        source: str,
        *,
        gate: str,
    ) -> None:
        """Run *check*; downgrade :class:`LayerValidationError` to a WARNING.

        Used for the soft gates (G1, G3) that ``enforce_layer_gates``
        gates between blocking and warn-only.  The default
        :attr:`_enforce_layer_gates` ``True`` re-raises so production
        deployments stay strict; passing ``False`` from
        :class:`PlatformConfig.enforce_layer_gates` lets researchers
        iterate on cross-layer prototypes without bypassing the
        always-blocking data-integrity gates G9 / G10 / G11.
        """
        try:
            check(spec, source)
        except LayerValidationError as exc:
            if self._enforce_layer_gates:
                raise
            _logger.warning(
                "%s downgraded to WARNING (enforce_layer_gates=False): %s",
                gate,
                exc,
            )

    def validate(self, spec: dict[str, Any], source: str) -> None:
        """Run every gate against *spec*.

        Raises :class:`LayerValidationError` (or a subclass) on the
        first failure.  Order is fixed: gates are applied in numeric
        order (G1 → G16) so that error messages reference a stable
        gate identifier.

        Parameters
        ----------
        spec :
            The pre-parsed YAML spec, already past
            :py:meth:`AlphaLoader._validate_schema`.
        source :
            Filesystem path or sentinel (``<dict>``) for the spec.
            Threaded into all error messages for operator triage.
        """
        # Gate order makes error reporting deterministic.
        self._softly(
            self._check_g1_layer_independence,
            spec,
            source,
            gate="G1",
        )
        self._check_g2_event_typing(spec, source)
        self._softly(
            self._check_g3_no_cross_horizon_leakage,
            spec,
            source,
            gate="G3",
        )
        self._check_g4_regime_gate_purity(spec, source)
        self._check_g5_signal_purity(spec, source)
        self._check_g6_feature_dependency_dag(spec, source)
        self._check_g7_horizon_registration(spec, source)
        self._check_g8_no_implicit_lookahead(spec, source)
        self._check_g9_session_alignment(spec, source)
        self._check_g10_universe_disclosure(spec, source)
        self._check_g11_factor_neutralization_disclosure(spec, source)
        self._check_g12_cost_arithmetic_disclosure(spec, source)
        self._check_g13_warm_up_documentation(spec, source)

        # Data-scope and fill-assumption gates.
        self._check_g14_data_scope(spec, source)
        self._check_g15_fill_assumptions(spec, source)

        # Trend-mechanism gate.
        self._check_g16_trend_mechanism_compliance(spec, source)

        # Stage-0 dual-permission actuation gate.  Always blocking — the
        # bounded-deferral ceiling and the story/decouple coupling are
        # safety-critical (Inv-11), not research-downgradable.
        self._check_g17_safety_exit_policy(spec, source)

    def _check_g14_data_scope(self, spec: dict[str, Any], source: str) -> None:
        """G14 — alpha must declare no data dependency beyond L1 NBBO + trades.

        Per gate G14 in ``alphas/SCHEMA.md`` / §6.6.

        The loader's namespace exposes
        only ``NBBOQuote`` and ``Trade`` event types to compiled
        feature/signal code.  A spec that declares a ``data_sources``
        block referencing anything outside this scope is rejected.

        ``data_sources`` is an *optional* declaration; absence means
        "implicit L1 NBBO + trades" which trivially satisfies G14.
        """
        sources_decl = spec.get("data_sources")
        if sources_decl is None:
            return
        if not isinstance(sources_decl, list):
            raise LayerValidationError(
                f"{source}: G14 — 'data_sources' must be a list, got {type(sources_decl).__name__}"
            )
        allowed = {"l1_nbbo", "trades", "reference_data", "session_calendar"}
        declared = {str(s).lower() for s in sources_decl}
        unknown = declared - allowed
        if unknown:
            raise LayerValidationError(
                f"{source}: G14 — alpha declares data_sources outside the "
                f"L1 NBBO + trades scope: {sorted(unknown)}. "
                f"Allowed: {sorted(allowed)}."
            )

    def _check_g15_fill_assumptions(self, spec: dict[str, Any], source: str) -> None:
        """G15 — fill assumptions must be consistent with the platform router.

        Per gate G15 in ``alphas/SCHEMA.md`` / §6.6.

        When an alpha declares a ``fill_model:``
        block, its ``router:`` field must name an implementation that
        the platform actually ships
        (``PassiveLimitOrderRouter`` or ``BacktestOrderRouter``).
        Absent block ⇒ implicit acceptance of the platform default,
        which trivially satisfies G15.
        """
        fill_model = spec.get("fill_model")
        if fill_model is None:
            return
        if not isinstance(fill_model, dict):
            raise LayerValidationError(
                f"{source}: G15 — 'fill_model' must be a mapping, got {type(fill_model).__name__}"
            )
        router = fill_model.get("router")
        if router is None:
            return
        allowed_routers = {"PassiveLimitOrderRouter", "BacktestOrderRouter"}
        if str(router) not in allowed_routers:
            raise LayerValidationError(
                f"{source}: G15 — fill_model.router '{router}' is not a "
                f"platform-supported router. "
                f"Allowed: {sorted(allowed_routers)}."
            )

    def _check_g1_layer_independence(self, spec: dict[str, Any], source: str) -> None:
        """G1 — no Layer-N alpha may import or call into Layer-(N+k) code.

        The loader exposes only layer-appropriate event types
        (``HorizonFeatureSnapshot`` + ``RegimeState`` for SIGNAL,
        ``CrossSectionalContext`` for PORTFOLIO).  ``import`` is
        already banned by G5 / G2 AST checks.  Here we additionally
        forbid PORTFOLIO specs from declaring ``depends_on_sensors``
        (a SIGNAL-only field) and SIGNAL specs from declaring
        ``universe`` (a PORTFOLIO-only field).
        """
        layer = str(spec.get("layer") or "")
        if layer == "SIGNAL" and "universe" in spec:
            raise LayerValidationError(
                f"{source}: G1 — layer: SIGNAL specs may not declare "
                f"'universe:' (a PORTFOLIO-layer field).  Layer "
                f"independence violated."
            )
        if layer == "PORTFOLIO" and "depends_on_sensors" in spec:
            raise LayerValidationError(
                f"{source}: G1 — layer: PORTFOLIO specs may not declare "
                f"'depends_on_sensors:' (a SIGNAL-layer field).  Layer "
                f"independence violated; declare 'depends_on_signals:' "
                f"instead."
            )

    def _check_g3_no_cross_horizon_leakage(self, spec: dict[str, Any], source: str) -> None:
        """G3 — alphas must operate on a single declared horizon.

        PORTFOLIO alphas declare a single
        ``horizon_seconds`` and their ``depends_on_signals`` must
        reference signals at the same horizon.  We can't cross-check
        the dependency horizons here (registry-level concern), but we
        do reject specs that accidentally declare multiple horizons.
        """
        layer = str(spec.get("layer") or "")
        if layer not in ("SIGNAL", "PORTFOLIO"):
            return
        # ``horizon_seconds`` must be a scalar int — never a list.
        h = spec.get("horizon_seconds")
        if isinstance(h, (list, tuple)):
            raise LayerValidationError(
                f"{source}: G3 — 'horizon_seconds' must be a single int; "
                f"multi-horizon alphas are not supported."
            )

    def _check_g9_session_alignment(self, spec: dict[str, Any], source: str) -> None:
        """G9 — horizon boundaries must align with ``session_open_ns``.

        :class:`HorizonScheduler` aligns boundaries
        automatically (``session_open_ns + k * horizon_seconds * 1e9``).
        At validation time we only check the horizon is in the
        registered platform set (already covered by G7) and that
        PORTFOLIO horizons match a registered cross-sectional horizon.
        """
        layer = str(spec.get("layer") or "")
        if layer != "PORTFOLIO":
            return
        # PORTFOLIO must declare a horizon (already enforced in
        # _REQUIRED_PORTFOLIO_LAYER_KEYS by the loader).  This gate is
        # otherwise a structural placeholder.

    def _check_g10_universe_disclosure(self, spec: dict[str, Any], source: str) -> None:
        """G10 — portfolio alphas must declare ``universe:`` explicitly (ACTIVE)."""
        layer = str(spec.get("layer") or "")
        if layer != "PORTFOLIO":
            return
        universe = spec.get("universe")
        if not isinstance(universe, list) or not universe:
            raise LayerValidationError(
                f"{source}: G10 — layer: PORTFOLIO spec must declare a "
                f"non-empty 'universe:' list; got {universe!r}"
            )
        for entry in universe:
            if not isinstance(entry, str) or not entry:
                raise LayerValidationError(
                    f"{source}: G10 — 'universe' entries must be non-empty strings; got {entry!r}"
                )

    def _check_g11_factor_neutralization_disclosure(
        self, spec: dict[str, Any], source: str
    ) -> None:
        """G11 — portfolio alphas must declare neutralization rules (ACTIVE).

        A PORTFOLIO alpha must either:

        - Declare ``factor_neutralization: true`` — opting into the
          platform's static factor model (FF5+momentum+STR by default).
        - Declare ``factor_neutralization: false`` — explicit opt-out;
          the operator accepts whatever raw factor exposure the
          composition pipeline generates.

        Either way the choice is disclosed in the spec; silent
        ambiguity is rejected.
        """
        layer = str(spec.get("layer") or "")
        if layer != "PORTFOLIO":
            return
        if "factor_neutralization" not in spec:
            raise LayerValidationError(
                f"{source}: G11 — layer: PORTFOLIO spec must declare "
                f"'factor_neutralization:' as a boolean (true to opt into "
                f"the platform factor model; false to opt out explicitly)."
            )
        val = spec["factor_neutralization"]
        if not isinstance(val, bool):
            raise LayerValidationError(
                f"{source}: G11 — 'factor_neutralization' must be a bool, "
                f"got {type(val).__name__}={val!r}"
            )

    def _check_g2_event_typing(self, spec: dict[str, Any], source: str) -> None:
        """G2 — every cross-layer event must be a typed dataclass (Inv-7).

        A SIGNAL spec must declare its inline
        ``signal:`` block as a string of Python source code.  The
        loader compiles that source into a function whose return type
        is a typed :class:`feelies.core.events.Signal` (or ``None``);
        the function-side typing is enforced at compile time by the
        loader.  Here we only verify the spec carries the inline
        block in the expected shape so the loader's typed compile
        contract has something to operate on.
        """
        layer = str(spec.get("layer") or "")
        if layer != "SIGNAL":
            return
        signal_block = spec.get("signal")
        if not isinstance(signal_block, str) or not signal_block.strip():
            raise LayerValidationError(
                f"{source}: G2 — layer: SIGNAL spec must declare inline "
                f"'signal:' code (string, non-empty); got "
                f"{type(signal_block).__name__}={signal_block!r}"
            )

    def _check_g4_regime_gate_purity(self, spec: dict[str, Any], source: str) -> None:
        """G4 — regime gate must be a pure boolean function of posteriors.

        Parse both ``on_condition`` and
        ``off_condition`` through the regime-gate DSL compiler
        (:func:`feelies.signals.regime_gate.compile_expression`).
        Any unsafe AST node, attribute access, lambda, comprehension,
        or non-whitelisted call surfaces as
        :class:`LayerValidationError` here so the operator sees the
        gate's ID up front.
        """
        layer = str(spec.get("layer") or "")
        if layer != "SIGNAL":
            return
        gate_block = spec.get("regime_gate")
        if not isinstance(gate_block, dict):
            raise LayerValidationError(
                f"{source}: G4 — layer: SIGNAL spec must declare a "
                f"'regime_gate:' mapping; got "
                f"{type(gate_block).__name__}"
            )
        from feelies.signals.regime_gate import (
            UnsafeExpressionError,
            compile_expression,
        )

        for key in ("on_condition", "off_condition"):
            cond = gate_block.get(key)
            if not isinstance(cond, str) or not cond.strip():
                raise LayerValidationError(
                    f"{source}: G4 — regime_gate.{key} must be a non-empty string; got {cond!r}"
                )
            try:
                compile_expression(cond)
            except UnsafeExpressionError as exc:
                raise LayerValidationError(
                    f"{source}: G4 — regime_gate.{key} failed DSL validation: {exc}"
                ) from exc

    def _check_g5_signal_purity(self, spec: dict[str, Any], source: str) -> None:
        """G5 — signal evaluate() must be a pure function of features.

        AST-scan the inline ``signal:`` source and reject:

        * Any :class:`ast.Import` or :class:`ast.ImportFrom` node.
        * Any reference to a banned built-in name
          (``exec``, ``eval``, ``compile``, ``open``, ``__import__``,
          ``globals``, ``locals``, ``vars``, ``input``,
          ``breakpoint``, ``exit``, ``quit``).
        * ``ast.Global`` / ``ast.Nonlocal`` (state escape hatches).

        The loader's restricted exec namespace already strips most of
        these at runtime; the AST scan is defence-in-depth and surfaces
        the failure during the *load* phase rather than at first
        invocation.
        """
        layer = str(spec.get("layer") or "")
        if layer != "SIGNAL":
            return
        signal_code = spec.get("signal")
        if not isinstance(signal_code, str):
            return  # G2 will already have raised.
        self._scan_inline_python(
            signal_code,
            source=source,
            gate="G5",
            context="signal",
            what="signal evaluate",
        )

    def _check_g6_feature_dependency_dag(self, spec: dict[str, Any], source: str) -> None:
        """G6 — sensor / feature dependency graph must be a DAG.

        - **SIGNAL**: ``depends_on_sensors`` must be a non-empty list
          of unique sensor identifiers.  When ``known_sensor_ids`` was
          injected at construction, every entry must resolve.
        - **PORTFOLIO**: no inline-feature DAG to validate; the gate is
          a no-op.  Cross-alpha dependencies on upstream SIGNAL outputs
          are resolved at registry merge time by the composition layer.

        ``LEGACY_SIGNAL`` is rejected by the loader before these gates run.
        """
        layer = str(spec.get("layer") or "")
        if layer != "SIGNAL":
            return
        depends = spec.get("depends_on_sensors")
        if not isinstance(depends, list) or not depends:
            raise LayerValidationError(
                f"{source}: G6 — layer: SIGNAL spec must declare "
                f"a non-empty 'depends_on_sensors' list; got "
                f"{depends!r}"
            )
        seen: set[str] = set()
        for entry in depends:
            if not isinstance(entry, str) or not entry.strip():
                raise LayerValidationError(
                    f"{source}: G6 — every depends_on_sensors "
                    f"entry must be a non-empty sensor_id "
                    f"string; got {entry!r}"
                )
            if entry in seen:
                raise LayerValidationError(
                    f"{source}: G6 — duplicate sensor_id {entry!r} in depends_on_sensors"
                )
            seen.add(entry)
        if self._known_sensor_ids is not None:
            missing = sorted(seen - self._known_sensor_ids)
            if missing:
                raise LayerValidationError(
                    f"{source}: G6 — depends_on_sensors references "
                    f"sensor(s) {missing} which are not registered "
                    f"in the platform; available: "
                    f"{sorted(self._known_sensor_ids)}"
                )

    def _check_g7_horizon_registration(self, spec: dict[str, Any], source: str) -> None:
        """G7 — declared ``horizon_seconds`` must be in
        ``platform.yaml`` registered horizons.

        For SIGNAL specs, verify ``horizon_seconds`` is an integer in the validator's
        ``registered_horizons`` set.  Defaults to the canonical
        ``{30, 120, 300, 900, 1800}`` when bootstrap doesn't inject
        a platform-specific list.
        """
        layer = str(spec.get("layer") or "")
        if layer != "SIGNAL":
            return
        h_raw = spec.get("horizon_seconds")
        if not isinstance(h_raw, int) or isinstance(h_raw, bool):
            raise LayerValidationError(
                f"{source}: G7 — 'horizon_seconds' must be an integer; "
                f"got {type(h_raw).__name__}={h_raw!r}"
            )
        if h_raw not in self._registered_horizons:
            raise LayerValidationError(
                f"{source}: G7 — horizon_seconds {h_raw} is not a "
                f"registered platform horizon; allowed: "
                f"{sorted(self._registered_horizons)}"
            )

    def _check_g8_no_implicit_lookahead(self, spec: dict[str, Any], source: str) -> None:
        """G8 — feature/signal code must not reference future state.

        AST-scan inline signal code for symbols that imply wall-clock lookups
        (``time``, ``datetime``, ``perf_counter``, ``monotonic``,
        ``now``).  Combined with G5's import ban this prevents the
        compiled function from peeking at future events through the
        process clock.
        """
        layer = str(spec.get("layer") or "")
        if layer != "SIGNAL":
            return
        banned = frozenset(
            {
                "time",
                "datetime",
                "monotonic",
                "perf_counter",
                "process_time",
                "now",
            }
        )
        signal_code = spec.get("signal")
        if isinstance(signal_code, str):
            self._scan_for_banned_names(
                signal_code,
                source=source,
                gate="G8",
                banned=banned,
                what="signal evaluate",
            )

    def _check_g12_cost_arithmetic_disclosure(self, spec: dict[str, Any], source: str) -> None:
        """G12 — alpha must declare ``cost_arithmetic:`` (bps vs $) explicitly.

        SIGNAL specs require ``cost_arithmetic:`` validated by
        :func:`feelies.alpha.cost_arithmetic.CostArithmetic.from_spec`.
        That parser enforces the canonical ``margin_ratio >= 1.5``
        floor and the disclosed-vs-computed reconciliation rule.
        """
        layer = str(spec.get("layer") or "")
        if layer != "SIGNAL":
            return
        from feelies.alpha.cost_arithmetic import (
            CostArithmetic,
            CostArithmeticError,
        )

        block = spec.get("cost_arithmetic")
        if not isinstance(block, dict):
            raise LayerValidationError(
                f"{source}: G12 — layer: SIGNAL spec must declare a "
                f"'cost_arithmetic:' mapping; got "
                f"{type(block).__name__}"
            )
        try:
            cost = CostArithmetic.from_spec(
                alpha_id=str(spec.get("alpha_id", "<unknown>")),
                spec=block,
            )
        except CostArithmeticError as exc:
            raise LayerValidationError(f"{source}: G12 — {exc}") from exc

        # A declared cost floor cannot be overridden below disclosed one-way cost.
        params_block = spec.get("parameters")
        if not isinstance(params_block, dict):
            return
        floor_def = params_block.get("cost_floor_bps")
        if not isinstance(floor_def, dict):
            return
        floor_min_raw = floor_def.get("min")
        if isinstance(floor_min_raw, bool) or not isinstance(floor_min_raw, (int, float)):
            return
        floor_min = float(floor_min_raw)
        if floor_min < cost.cost_total_bps:
            raise LayerValidationError(
                f"{source}: G12 — parameters.cost_floor_bps.min={floor_min!r} "
                f"is below cost_arithmetic.cost_total_bps={cost.cost_total_bps!r}; "
                f"a config override inside the declared bound could weaken "
                f"the alpha's self-suppression below its own disclosed cost. "
                f"Raise cost_floor_bps.min to at least "
                f"{cost.cost_total_bps!r}."
            )

    def _check_g13_warm_up_documentation(self, spec: dict[str, Any], source: str) -> None:
        """No-op: surviving layers declare no inline features."""
        del spec, source  # all surviving layers are no-ops

    # ── AST-scan helpers (G5 / G8) ───────────────────────────────────

    @staticmethod
    def _scan_inline_python(
        code: str,
        *,
        source: str,
        gate: str,
        context: str,
        what: str,
    ) -> None:
        """Reject banned AST nodes / banned name references in *code*."""
        try:
            tree = ast.parse(code, filename=f"<{source}:{context}>")
        except SyntaxError as exc:
            raise LayerValidationError(
                f"{source}: {gate} — {what} failed to parse: {exc.msg} (line {exc.lineno})"
            ) from exc
        for node in ast.walk(tree):
            if isinstance(node, _BANNED_SIGNAL_AST_NODES):
                raise LayerValidationError(
                    f"{source}: {gate} — {what} contains forbidden "
                    f"AST node {type(node).__name__!r}; "
                    f"import / global / nonlocal are disallowed"
                )
            if isinstance(node, ast.Name) and node.id in _BANNED_SIGNAL_NAMES:
                raise LayerValidationError(
                    f"{source}: {gate} — {what} references banned "
                    f"identifier {node.id!r}; the loader's restricted "
                    f"namespace forbids it at runtime, but the gate "
                    f"refuses load to surface the failure earlier"
                )
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == "__builtins__"
            ):
                raise LayerValidationError(
                    f"{source}: {gate} — {what} accesses '__builtins__' which is forbidden"
                )

    @staticmethod
    def _scan_for_banned_names(
        code: str,
        *,
        source: str,
        gate: str,
        banned: frozenset[str],
        what: str,
    ) -> None:
        """Reject references to banned bare identifiers in *code*."""
        try:
            tree = ast.parse(code, filename=f"<{source}:{gate}>")
        except SyntaxError:
            # G5 will have raised already; don't compound errors.
            return
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id in banned:
                raise LayerValidationError(
                    f"{source}: {gate} — {what} references banned "
                    f"identifier {node.id!r}; clock / wall-time access "
                    f"would leak future state into the deterministic "
                    f"replay path"
                )

    def _check_g16_trend_mechanism_compliance(self, spec: dict[str, Any], source: str) -> None:
        """G16 — mechanism-horizon binding (§20.6.1).

        Two activation triggers per §20.6:

        1. *Opt-in*: the spec declares a ``trend_mechanism:`` block —
           rules 1-9 apply.
        2. *Strict mode*: ``enforce_trend_mechanism=True`` was
           passed to the validator (typically driven by
           ``platform.yaml: enforce_trend_mechanism: true``) — every
           schema-1.1 SIGNAL/PORTFOLIO spec must declare
           ``trend_mechanism:`` or load is refused via
           :class:`MissingTrendMechanismError`.

        Each rule raises a distinct
        :class:`TrendMechanismValidationError` subclass so callers
        can attribute failures cleanly without parsing message
        strings.  Rule 7 inspects the inline ``signal:`` AST to
        confirm the LIQUIDITY_STRESS family never returns a non-FLAT
        direction (entry-only prohibition).
        """
        block = spec.get("trend_mechanism")
        layer = str(spec.get("layer") or "").upper()
        schema_version = str(spec.get("schema_version") or "")
        is_v11_signal_or_portfolio = schema_version == "1.1" and layer in {"SIGNAL", "PORTFOLIO"}

        if not is_v11_signal_or_portfolio:
            return

        if block is None:
            if self._enforce_trend_mechanism:
                raise MissingTrendMechanismError(
                    f"{source}: G16 strict-mode — schema-1.1 {layer} "
                    f"alpha must declare a 'trend_mechanism:' block "
                    f"when platform.enforce_trend_mechanism=true"
                )
            return
        if not isinstance(block, dict):
            raise TrendMechanismValidationError(
                f"{source}: G16 — 'trend_mechanism' must be a mapping, got {type(block).__name__}"
            )

        if layer == "PORTFOLIO":
            self._check_g16_portfolio_rules(spec, block, source)
        else:
            self._check_g16_signal_rules(spec, block, source)

    def _check_g16_signal_rules(
        self,
        spec: dict[str, Any],
        block: dict[str, Any],
        source: str,
    ) -> None:
        """Rules 1-7 for SIGNAL alphas with ``trend_mechanism:`` declared."""
        family_raw = block.get("family")
        if family_raw is None:
            raise UnknownTrendMechanismError(
                f"{source}: G16 rule 1 — 'trend_mechanism.family' is required"
            )
        family = str(family_raw)
        if family not in _NORMATIVE_FAMILY_NAMES:
            raise UnknownTrendMechanismError(
                f"{source}: G16 rule 1 — unknown trend_mechanism.family "
                f"{family!r}; must be one of "
                f"{sorted(_NORMATIVE_FAMILY_NAMES)}"
            )

        half_life_raw = block.get("expected_half_life_seconds")
        if half_life_raw is None:
            raise MechanismHalfLifeOutOfRangeError(
                f"{source}: G16 rule 2 — 'trend_mechanism.expected_half_life_seconds' is required"
            )
        try:
            half_life = int(half_life_raw)
        except (TypeError, ValueError) as exc:
            raise MechanismHalfLifeOutOfRangeError(
                f"{source}: G16 rule 2 — "
                f"expected_half_life_seconds must be int, got "
                f"{type(half_life_raw).__name__}"
            ) from exc
        lo, hi = _FAMILY_HALF_LIFE_RANGES_SECONDS[family]
        if not lo <= half_life <= hi:
            raise MechanismHalfLifeOutOfRangeError(
                f"{source}: G16 rule 2 — expected_half_life_seconds={half_life} "
                f"is outside the empirical range for {family} ({lo}-{hi}s); "
                f"see Table §20.2"
            )

        horizon_raw = spec.get("horizon_seconds")
        if horizon_raw is None:
            raise MechanismHorizonMismatchError(
                f"{source}: G16 rule 3 — 'horizon_seconds' is required "
                f"for SIGNAL alphas declaring trend_mechanism:"
            )
        try:
            horizon = int(horizon_raw)
        except (TypeError, ValueError) as exc:
            raise MechanismHorizonMismatchError(
                f"{source}: G16 rule 3 — horizon_seconds must be int, got "
                f"{type(horizon_raw).__name__}"
            ) from exc
        ratio = horizon / half_life if half_life > 0 else float("inf")
        if not _HORIZON_RATIO_FLOOR <= ratio <= _HORIZON_RATIO_CEILING:
            raise MechanismHorizonMismatchError(
                f"{source}: G16 rule 3 — horizon_seconds/expected_half_life_seconds "
                f"= {horizon}/{half_life} = {ratio:.3f}; must be in "
                f"[{_HORIZON_RATIO_FLOOR}, {_HORIZON_RATIO_CEILING}]"
            )
        if (
            ratio <= _HORIZON_RATIO_FLOOR + _HORIZON_RATIO_WARN_MARGIN
            or ratio >= _HORIZON_RATIO_CEILING - _HORIZON_RATIO_WARN_MARGIN
        ):
            _logger.warning(
                "%s: G16 rule 3 (sensor_audit_2026-07-02 P2) — "
                "horizon_seconds/expected_half_life_seconds = %d/%d = %.3f sits "
                "within %.2f of the [%.1f, %.1f] bound; a small future "
                "expected_half_life_seconds recalibration could flip this alpha "
                "into a G16 rule-3 rejection with no advance notice.",
                source,
                horizon,
                half_life,
                ratio,
                _HORIZON_RATIO_WARN_MARGIN,
                _HORIZON_RATIO_FLOOR,
                _HORIZON_RATIO_CEILING,
            )

        sensors_raw = block.get("l1_signature_sensors", []) or []
        declared_sensor_ids = _extract_sensor_ids(sensors_raw, source)

        if self._known_sensor_ids is not None:
            missing = [sid for sid in declared_sensor_ids if sid not in self._known_sensor_ids]
            if missing:
                raise MissingMechanismSensorError(
                    f"{source}: G16 rule 4 — l1_signature_sensors "
                    f"references sensors not registered in the platform: "
                    f"{sorted(missing)}; "
                    f"known: {sorted(self._known_sensor_ids)[:10]}..."
                )

        primary_options = _FAMILY_FINGERPRINT_SENSORS[family]
        if not any(sid in declared_sensor_ids for sid in primary_options):
            raise MissingFingerprintSensorError(
                f"{source}: G16 rule 5 — {family} requires at least one "
                f"primary fingerprint sensor in l1_signature_sensors; "
                f"acceptable: {list(primary_options)}; "
                f"declared: {sorted(declared_sensor_ids)}"
            )

        failure_sig = block.get("failure_signature")
        if not failure_sig or not isinstance(failure_sig, list):
            raise MissingFailureSignatureError(
                f"{source}: G16 rule 6 — 'failure_signature' must be a "
                f"non-empty list of mechanism-specific invalidator "
                f"clauses (Inv-2)"
            )

        # A signature sensor must be a real dependency, not cosmetic metadata.
        depends_raw = spec.get("depends_on_sensors") or []
        depends_ids = {d for d in depends_raw if isinstance(d, str)}
        unbacked = sorted(declared_sensor_ids - depends_ids)
        if unbacked:
            raise UnbackedSignatureSensorError(
                f"{source}: G16 rule 10 — l1_signature_sensors {unbacked} "
                f"are not in depends_on_sensors; a signature sensor the "
                f"alpha does not depend on cannot be the mechanism's L1 "
                f"fingerprint (cosmetic fingerprint). Add them to "
                f"depends_on_sensors or drop them from l1_signature_sensors."
            )

        if family == _STRESS_FAMILY:
            self._check_stress_family_entry_prohibition(spec, source)

    def _check_stress_family_entry_prohibition(
        self,
        spec: dict[str, Any],
        source: str,
    ) -> None:
        """G16 rule 7 — LIQUIDITY_STRESS may not emit a non-FLAT
        direction from any reachable code path in the inline
        ``signal:`` block.

        Static AST inspection: any ``return Signal(..., direction=X, ...)``
        whose ``X`` resolves to ``LONG``, ``SHORT``, or one of the
        symbolic equivalents (``"LONG"``, ``"SHORT"``,
        ``SignalDirection.LONG``, ``SignalDirection.SHORT``) is a
        violation.  Returning ``FLAT`` (the de-leverage path) is
        always allowed.

        The check accepts a missing ``signal:`` block (e.g. a SIGNAL
        spec that delegates to an external module — uncommon but
        valid); G5 / G2 will catch the deeper integrity issues.

        Abstention is safe: when the direction is computed dynamically and
        cannot be resolved statically, this rule abstains, but
        :class:`~feelies.signals.horizon_engine.HorizonSignalEngine` provides a
        runtime backstop — it suppresses any non-FLAT signal emitted by an
        ``EXIT_ONLY_MECHANISMS`` alpha, so dynamic direction cannot open exposure.
        """
        signal_src = spec.get("signal")
        if not isinstance(signal_src, str):
            return
        try:
            tree = ast.parse(signal_src)
        except SyntaxError:
            return
        for node in ast.walk(tree):
            if not isinstance(node, ast.Return):
                continue
            direction = _extract_direction_argument(node.value)
            if direction in _NON_FLAT_DIRECTIONS:
                raise StressFamilyEntryProhibitedError(
                    f"{source}: G16 rule 7 — LIQUIDITY_STRESS family is "
                    f"exit-only; the inline signal: block may not return "
                    f"a non-FLAT direction (found {direction!r}). "
                    f"Use FLAT to de-leverage; see §20.6.1 rule 7."
                )

    def _check_g16_portfolio_rules(
        self,
        spec: dict[str, Any],
        block: dict[str, Any],
        source: str,
    ) -> None:
        """Rules 8-9 for PORTFOLIO alphas with
        ``trend_mechanism.consumes:`` declared."""
        consumes_raw = block.get("consumes")
        if consumes_raw is None:
            return
        if not isinstance(consumes_raw, list):
            raise TrendMechanismValidationError(
                f"{source}: G16 — 'trend_mechanism.consumes' must be a list, "
                f"got {type(consumes_raw).__name__}"
            )

        seen_families: set[str] = set()
        share_total = 0.0
        for entry in consumes_raw:
            if not isinstance(entry, dict):
                raise TrendMechanismValidationError(
                    f"{source}: G16 — every 'consumes' entry must be a "
                    f"mapping, got {type(entry).__name__}"
                )
            fam = str(entry.get("family") or "")
            if fam not in _NORMATIVE_FAMILY_NAMES:
                raise UnknownTrendMechanismError(
                    f"{source}: G16 rule 1 — unknown family {fam!r} in "
                    f"PORTFOLIO consumes; allowed: "
                    f"{sorted(_NORMATIVE_FAMILY_NAMES)}"
                )
            seen_families.add(fam)
            share_raw = entry.get("max_share_of_gross", 0.0)
            try:
                share = float(share_raw)
            except (TypeError, ValueError) as exc:
                raise MechanismShareUnreachableError(
                    f"{source}: G16 rule 8 — max_share_of_gross for "
                    f"family {fam!r} must be float, got "
                    f"{type(share_raw).__name__}"
                ) from exc
            if not 0.0 <= share <= 1.0:
                raise MechanismShareUnreachableError(
                    f"{source}: G16 rule 8 — max_share_of_gross={share} "
                    f"for {fam!r} must be in [0.0, 1.0]"
                )
            share_total += share

        if share_total < 1.0 - 1e-9:
            raise MechanismShareUnreachableError(
                f"{source}: G16 rule 8 — sum of max_share_of_gross "
                f"= {share_total:.3f} < 1.0; full book deployment is "
                f"structurally unreachable"
            )

        depends = spec.get("depends_on_signals") or []
        if isinstance(depends, list):
            for dep in depends:
                if isinstance(dep, dict):
                    fam = str(dep.get("trend_mechanism_family") or "")
                else:
                    fam = ""
                if fam and fam not in seen_families:
                    raise UnauthorizedMechanismDependencyError(
                        f"{source}: G16 rule 9 — depends_on_signals "
                        f"references family {fam!r} which is not in "
                        f"this PORTFOLIO's consumes whitelist "
                        f"{sorted(seen_families)}"
                    )

    def _check_g17_safety_exit_policy(self, spec: dict[str, Any], source: str) -> None:
        """G17 — Stage-0 dual-permission actuation (design rev 5 §2.8 / §3.4).

        Cross-block, single-spec invariants for the ``safety_exit_policy:`` and
        ``story_permission:`` blocks (both SIGNAL-only).  The purely structural
        checks (``mode`` enum; both ceilings present + positive under
        ``decouple_caps_only``) live in
        :meth:`~feelies.alpha.loader.AlphaLoader._parse_safety_exit_policy_block`;
        this gate owns the invariants that need *other* blocks:

        1. ``safety_exit_policy`` / ``story_permission`` are SIGNAL-layer only.
        2. ``story_permission`` set ⇒ ``mode ≠ gate_close_flat`` (a story map
           while the gate still auto-flattens on close is contradictory, §3.4).
        3. ``decouple_caps_only`` requires a ``trend_mechanism:`` with a known
           ``family`` and a positive ``expected_half_life_seconds`` — the
           deferral ceiling is bounded by the family's half-life envelope, so a
           decoupled alpha with no family has nothing to bound it against (§2.8).
        4. ``max_hold_after_safe_off`` ≤ per-family multiple ×
           ``expected_half_life_seconds`` (§2.8).

        Deliberately tolerant of a *structurally* malformed block (non-mapping,
        unknown mode, missing/negative ceiling): those raise from the loader's
        parser, so this gate returns early rather than double-reporting.
        """
        policy = spec.get("safety_exit_policy")
        story = spec.get("story_permission")
        if policy is None and story is None:
            return  # default gate_close_flat behaviour — nothing to validate.

        layer = str(spec.get("layer") or "").upper()
        if layer != "SIGNAL":
            offending = "safety_exit_policy" if policy is not None else "story_permission"
            raise LayerValidationError(
                f"{source}: G17 — '{offending}:' is a SIGNAL-layer block "
                f"(Stage-0 dual-permission actuation is regime-gate-scoped); "
                f"layer: {layer or '<missing>'} may not declare it."
            )

        # ``mode`` defaults to gate_close_flat; a non-mapping / unknown mode is a
        # structural error the loader parser raises — defer to it.
        if policy is not None and not isinstance(policy, dict):
            return
        mode = (
            str((policy or {}).get("mode", _SAFETY_EXIT_POLICY_DEFAULT_MODE))
            if policy is not None
            else _SAFETY_EXIT_POLICY_DEFAULT_MODE
        )

        # (2) story ⇒ decouple.
        if story is not None and mode != _SAFETY_EXIT_POLICY_DECOUPLE_MODE:
            raise LayerValidationError(
                f"{source}: G17 — 'story_permission:' requires "
                f"safety_exit_policy.mode='{_SAFETY_EXIT_POLICY_DECOUPLE_MODE}' "
                f"(got mode='{mode}'); a story map while the gate still "
                f"auto-flattens on close is contradictory (design §3.4)."
            )

        if mode != _SAFETY_EXIT_POLICY_DECOUPLE_MODE:
            return

        # (3) decouple requires a family + half-life envelope to bound the ceiling.
        tm = spec.get("trend_mechanism")
        family = str(tm.get("family")) if isinstance(tm, dict) and tm.get("family") else None
        if family is None or family not in _NORMATIVE_FAMILY_NAMES:
            raise LayerValidationError(
                f"{source}: G17 — safety_exit_policy.mode="
                f"'{_SAFETY_EXIT_POLICY_DECOUPLE_MODE}' requires a "
                f"'trend_mechanism.family' in {sorted(_NORMATIVE_FAMILY_NAMES)}; "
                f"the deferral ceiling is bounded by the family's half-life "
                f"envelope, so decoupling with no family has nothing to bound "
                f"max_hold_after_safe_off against (design §2.8)."
            )
        half_life_raw = tm.get("expected_half_life_seconds") if isinstance(tm, dict) else None
        try:
            half_life = int(half_life_raw)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            half_life = 0
        if half_life <= 0:
            raise LayerValidationError(
                f"{source}: G17 — safety_exit_policy.mode="
                f"'{_SAFETY_EXIT_POLICY_DECOUPLE_MODE}' requires a positive "
                f"'trend_mechanism.expected_half_life_seconds' to bound the "
                f"deferral ceiling (§2.8); got {half_life_raw!r}."
            )

        # (4) max_hold_after_safe_off ≤ per-family multiple × half-life.
        max_hold_raw = (policy or {}).get("max_hold_after_safe_off")
        try:
            max_hold = int(max_hold_raw)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return  # missing / malformed ceiling — the loader parser rejects it.
        if max_hold <= 0:
            return  # non-positive ceiling — loader parser rejects it.
        multiple = _FAMILY_MAX_HOLD_HALF_LIFE_MULTIPLE[family]
        ceiling = multiple * half_life
        if max_hold > ceiling:
            raise LayerValidationError(
                f"{source}: G17 — safety_exit_policy.max_hold_after_safe_off="
                f"{max_hold}s exceeds the {family} ceiling of "
                f"{multiple}×expected_half_life_seconds({half_life}) = {ceiling}s "
                f"(design §2.8 — the deferral window may not outlast a per-family "
                f"multiple of the mechanism's half-life)."
            )


# ── G16 helpers ─────────────────────────────────────────────────────────


def _extract_sensor_ids(raw: Any, source: str) -> set[str]:
    """Coerce ``l1_signature_sensors`` to ``set[str]``.

    Accepts the canonical list-of-strings form::

        l1_signature_sensors:
          - kyle_lambda_60s
          - ofi_ewma

    or a list of mappings carrying ``id:`` (used by some richer
    schemas that pin sensor versions inline)::

        l1_signature_sensors:
          - {id: kyle_lambda_60s, version: 1}

    Anything else raises :class:`TrendMechanismValidationError` so the
    G16 family checks can rely on a clean ``set[str]``.
    """
    if not isinstance(raw, list):
        raise TrendMechanismValidationError(
            f"{source}: G16 — 'trend_mechanism.l1_signature_sensors' "
            f"must be a list, got {type(raw).__name__}"
        )
    out: set[str] = set()
    for entry in raw:
        if isinstance(entry, str):
            out.add(entry)
        elif isinstance(entry, dict) and isinstance(entry.get("id"), str):
            out.add(entry["id"])
        else:
            raise TrendMechanismValidationError(
                f"{source}: G16 — l1_signature_sensors entry must be a "
                f"string or mapping with 'id', got {type(entry).__name__}"
            )
    return out


def _extract_direction_argument(call_node: ast.AST | None) -> str | None:
    """Return the textual direction passed to a ``Signal(...)`` constructor.

    Recognised forms:

    * ``Signal(..., direction="LONG", ...)`` → ``"LONG"``
    * ``Signal(..., direction=SignalDirection.SHORT, ...)`` → ``"SHORT"``
    * ``Signal(..., direction=Direction.FLAT)`` → ``"FLAT"``
    * Any positional 2nd argument matching the same shapes → resolved
      defensively to catch authors who skip the keyword.

    Returns ``None`` when the return value is not recognisable as a
    ``Signal(...)`` invocation or when ``direction`` cannot be statically
    resolved (in which case G16 abstains — the safer default for a
    structural gate).
    """
    if not isinstance(call_node, ast.Call):
        return None
    func_name = _qualified_call_name(call_node.func)
    if func_name is None or not func_name.endswith("Signal"):
        return None

    for kw in call_node.keywords:
        if kw.arg == "direction":
            return _literal_or_attr_name(kw.value)
    if len(call_node.args) >= 2:
        return _literal_or_attr_name(call_node.args[1])
    return None


def _qualified_call_name(node: ast.AST) -> str | None:
    """Best-effort dotted name extraction for ``Call.func``."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _qualified_call_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return None


def _literal_or_attr_name(node: ast.AST) -> str | None:
    """Resolve a string literal or ``Enum.MEMBER`` to its tail name.

    * ``ast.Constant("LONG")`` → ``"LONG"``
    * ``ast.Attribute(SignalDirection, "LONG")`` → ``"LONG"``
    * ``ast.Name("LONG")`` (rare; module-level constant) → ``"LONG"``

    Anything dynamic returns ``None``.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return None


# ── G17 cross-alpha scope invariant (design rev 5 §3.3 / §3.4) ──────────────


def validate_decouple_symbol_scope(
    entries: Sequence[tuple[str, frozenset[str], bool]],
    *,
    backstop_slice_scoped: bool = True,
    source: str = "<platform>",
) -> None:
    """Reject a symbol-net decoupling backstop on a symbol shared by strategies.

    A cross-alpha companion to gate G17: the per-spec loader/validator cannot
    see whether *another* strategy also trades a decoupled alpha's symbol, so
    this runs over the whole registered set at load time (design §3.3, §3.4).

    ``entries`` is ``(alpha_id, resolved_symbols, is_decoupled)`` for every
    registered alpha — the caller resolves each alpha's effective symbol set
    (per-alpha ``symbols`` / ``universe``, or the platform universe when the
    alpha declares none).

    * ``backstop_slice_scoped=True`` (the default, and this platform's wiring —
      :class:`~feelies.risk.deferral_cap.DeferralCapController` and
      :class:`~feelies.risk.exit_composer.ExitComposer` both read the
      per-strategy :class:`~feelies.portfolio.strategy_position_store.StrategyPositionStore`):
      a slice-scoped backstop flattens only the promoting strategy's slice, so a
      decoupled alpha may safely share a symbol with another strategy — nothing
      to reject.

    * ``backstop_slice_scoped=False`` (a symbol-net backstop — e.g. wiring the
      symbol-net :class:`~feelies.risk.hazard_exit.HazardExitController` as the
      age backstop): a symbol-net flatten crosses into every strategy's slice on
      that symbol, so decoupling is hard-restricted to single-strategy-per-symbol
      — a decoupled alpha sharing a symbol with any other strategy is a **defect**
      and is rejected here (not merely recorded, §3.3).

    Raises :class:`LayerValidationError` on a shared-symbol violation.
    """
    if backstop_slice_scoped:
        # Slice-scoped backstop: a shared symbol is safe (the cap flattens one
        # strategy's slice, never symbol-net).  Nothing to enforce.
        return

    owners: dict[str, set[str]] = {}
    for alpha_id, symbols, _is_decoupled in entries:
        for sym in symbols:
            owners.setdefault(sym, set()).add(alpha_id)

    for alpha_id, symbols, is_decoupled in entries:
        if not is_decoupled:
            continue
        shared = sorted(sym for sym in symbols if len(owners.get(sym, set())) > 1)
        if shared:
            others = sorted(
                {owner for sym in shared for owner in owners.get(sym, set())} - {alpha_id}
            )
            raise LayerValidationError(
                f"{source}: G17 scope — decouple_caps_only alpha {alpha_id!r} "
                f"shares symbol(s) {shared} with strateg(ies) {others} while the "
                f"decoupling backstop is symbol-net; a symbol-net cap cannot "
                f"flatten one strategy's slice without cross-flattening the "
                f"others (design §3.3). Either scope the backstop caps to the "
                f"strategy slice or restrict this symbol universe to "
                f"single-strategy-per-symbol."
            )
