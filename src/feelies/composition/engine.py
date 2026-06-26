"""``CompositionEngine`` — converts ``CrossSectionalContext`` → ``SizedPositionIntent``.

The engine subscribes to :class:`CrossSectionalContext` events,
dispatches each context to every registered :class:`PortfolioAlpha`
(or the canonical default pipeline), and publishes one
:class:`SizedPositionIntent` per context per alpha.

Determinism (§7.5)
------------------

* Iteration over registered alphas is sorted by ``alpha_id`` at
  registration time.
* Sequence numbers come from the dedicated ``_intent_seq`` generator;
  they never collide with any other emitter's stream (Inv-A / C1).
* When ``ctx.completeness`` falls below the configured threshold the
  engine emits a *degenerate* :class:`SizedPositionIntent` (empty
  ``target_positions``) — the risk engine treats this as "hold
  existing positions".  No silent drops.
* When a :class:`PortfolioAlpha.construct` raises, the engine logs
  the exception and emits the same degenerate intent.

The engine is *passive when no PORTFOLIO alphas are registered* — bus
subscription is skipped entirely so SIGNAL-only deployments incur
zero overhead and downstream Layer-4 parity hashes stay bit-stable.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, replace
from typing import Any, Mapping

from feelies.bus.event_bus import EventBus
from feelies.composition.cross_sectional import (
    CrossSectionalRanker,
    RankResult,
    compute_mechanism_breakdown,
)
from feelies.composition.factor_neutralizer import FactorNeutralizer
from feelies.composition.protocol import (
    CompositionContextError,
    PortfolioAlpha,
)
from feelies.composition.sector_matcher import SectorMatcher
from feelies.composition.turnover_optimizer import TurnoverOptimizer
from feelies.core.events import (
    CrossSectionalContext,
    SizedPositionIntent,
    TargetPosition,
    TrendMechanism,
)
from feelies.core.identifiers import SequenceGenerator

_logger = logging.getLogger(__name__)


def _compute_decision_basis_hash(
    *,
    strategy_id: str,
    ctx: CrossSectionalContext,
    rank_result: RankResult,
    current_positions: Mapping[str, float],
    mechanism_caps: Mapping[TrendMechanism, float] | None,
    global_mechanism_cap: float | None,
) -> str:
    """SHA-256 over the canonical decision inputs (audit P0-6).

    Deterministic: every component is emitted in a fixed order (universe
    order for per-symbol rows, mechanism-name order for caps) with a
    fixed float format, so identical inputs hash identically across
    replays and materially-different inputs almost never collide.
    """
    parts: list[str] = [f"{strategy_id}|{ctx.horizon_seconds}|{ctx.boundary_index}"]
    for s in ctx.universe:
        raw = rank_result.raw_scores.get(s, 0.0)
        decay = rank_result.decay_factors.get(s, 0.0)
        mech = rank_result.mechanism_by_symbol.get(s)
        mech_name = mech.name if mech is not None else "-"
        pos = current_positions.get(s, 0.0)
        parts.append(f"{s}={raw:.10g}:{decay:.10g}:{mech_name}:{pos:.2f}")
    gcap = "-" if global_mechanism_cap is None else f"{global_mechanism_cap:.10g}"
    parts.append(f"gcap={gcap}")
    if mechanism_caps:
        for mech in sorted(mechanism_caps, key=lambda m: m.name):
            parts.append(f"cap:{mech.name}={mechanism_caps[mech]:.10g}")
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RegisteredPortfolioAlpha:
    """Immutable record describing one PORTFOLIO alpha."""

    alpha_id: str
    horizon_seconds: int
    alpha: PortfolioAlpha
    params: Mapping[str, Any]


class CompositionEngine:
    """Bus-subscriber that turns barrier-synced contexts into intents."""

    __slots__ = (
        "_bus",
        "_intent_seq",
        "_ranker",
        "_neutralizer",
        "_sector_matcher",
        "_optimizer",
        "_alphas",
        "_completeness_threshold",
        "_attached",
        "_position_lookup",
    )

    def __init__(
        self,
        *,
        bus: EventBus,
        intent_sequence_generator: SequenceGenerator,
        ranker: CrossSectionalRanker,
        neutralizer: FactorNeutralizer,
        sector_matcher: SectorMatcher,
        optimizer: TurnoverOptimizer,
        completeness_threshold: float = 0.80,
        position_lookup: Any | None = None,
    ) -> None:
        if not 0.0 <= completeness_threshold <= 1.0:
            raise ValueError(
                f"completeness_threshold must be in [0, 1], got {completeness_threshold}"
            )
        self._bus = bus
        self._intent_seq = intent_sequence_generator
        self._ranker = ranker
        self._neutralizer = neutralizer
        self._sector_matcher = sector_matcher
        self._optimizer = optimizer
        self._alphas: list[RegisteredPortfolioAlpha] = []
        self._completeness_threshold = float(completeness_threshold)
        self._attached = False
        # Optional callable ``symbol -> current_position_usd`` injected
        # at bootstrap so the optimizer's turnover penalty is computed
        # against actuals rather than a stale shadow ledger.  When None
        # the engine treats current positions as zero (cold start).
        self._position_lookup = position_lookup

    # ── Registration ─────────────────────────────────────────────────

    def register(self, registered: RegisteredPortfolioAlpha) -> None:
        for existing in self._alphas:
            if existing.alpha_id == registered.alpha_id:
                raise ValueError(
                    f"CompositionEngine: alpha {registered.alpha_id!r} is already registered"
                )
        self._alphas.append(registered)
        self._alphas.sort(key=lambda a: (a.horizon_seconds, a.alpha_id))

    @property
    def is_empty(self) -> bool:
        return not self._alphas

    @property
    def alphas(self) -> tuple[RegisteredPortfolioAlpha, ...]:
        return tuple(self._alphas)

    # ── Bus wiring ───────────────────────────────────────────────────

    def attach(self) -> None:
        if self._attached:
            return
        if not self._alphas:
            _logger.debug(
                "CompositionEngine.attach() — no PORTFOLIO alphas; "
                "skipping bus subscription (legacy fast-path preserved)"
            )
            return
        self._bus.subscribe(CrossSectionalContext, self._on_context)
        self._attached = True

    # ── Bus handler ──────────────────────────────────────────────────

    def _on_context(self, ctx: CrossSectionalContext) -> None:
        for registered in self._alphas:
            if registered.horizon_seconds != ctx.horizon_seconds:
                continue
            self._dispatch_one(registered, ctx)

    # ── Per-alpha dispatch ──────────────────────────────────────────

    def _dispatch_one(
        self,
        registered: RegisteredPortfolioAlpha,
        ctx: CrossSectionalContext,
    ) -> None:
        # Below-threshold completeness → degenerate intent (do nothing).
        # The threshold is resolved per-alpha (audit P1-5): an alpha may
        # declare a stricter ``composition_completeness_threshold`` in its
        # ``parameters:`` block; the platform-config value is the fallback.
        threshold = self._resolve_completeness_threshold(registered)
        if ctx.completeness < threshold:
            self._emit_degenerate(
                registered,
                ctx,
                reason=(f"completeness {ctx.completeness:.3f} below threshold {threshold:.3f}"),
            )
            return

        try:
            intent = registered.alpha.construct(ctx, registered.params)
        except CompositionContextError as exc:
            _logger.info(
                "CompositionEngine: %s declined to construct intent for boundary %d: %s",
                registered.alpha_id,
                ctx.boundary_index,
                exc,
            )
            self._emit_degenerate(registered, ctx, reason=str(exc))
            return
        except Exception as exc:  # noqa: BLE001 — fail-safe boundary
            _logger.warning(
                "CompositionEngine: %s.construct raised at boundary %d: %s",
                registered.alpha_id,
                ctx.boundary_index,
                exc,
            )
            self._emit_degenerate(registered, ctx, reason=f"raised: {exc}")
            return

        # Patch in deterministic envelope fields (the alpha returns a
        # *value*; the engine owns sequencing and timestamping).
        # Also propagate per-symbol disclosed cost from the consumed
        # signals so the risk engine can stamp G12 disclosure on each
        # emitted PORTFOLIO OrderRequest (audit R3).  Carried on the
        # intent rather than recomputed in the risk engine because the
        # context's signals are the canonical per-symbol attribution
        # source — recomputing in risk would couple risk to the
        # composition flow.  When the alpha's ``construct`` already
        # populated the field (rare; future-friendly) we preserve the
        # caller's value rather than overwriting.
        disclosed = dict(intent.disclosed_cost_total_bps_by_symbol)
        for symbol in intent.target_positions:
            if symbol in disclosed:
                continue
            sig = ctx.signals_by_symbol.get(symbol)
            if sig is not None and sig.disclosed_cost_total_bps > 0:
                disclosed[symbol] = sig.disclosed_cost_total_bps
                continue
            row = ctx.signals_by_strategy_by_symbol.get(symbol)
            if row:
                for _, cand in sorted(row.items()):
                    if cand is not None and cand.disclosed_cost_total_bps > 0:
                        disclosed[symbol] = cand.disclosed_cost_total_bps
                        break

        publishable = replace(
            intent,
            timestamp_ns=ctx.timestamp_ns,
            sequence=self._intent_seq.next(),
            correlation_id=f"intent:{registered.alpha_id}:{ctx.horizon_seconds}:{ctx.boundary_index}",
            source_layer="PORTFOLIO",
            strategy_id=registered.alpha_id,
            layer="PORTFOLIO",
            horizon_seconds=ctx.horizon_seconds,
            disclosed_cost_total_bps_by_symbol=disclosed,
        )
        self._bus.publish(publishable)

    def _resolve_completeness_threshold(
        self,
        registered: RegisteredPortfolioAlpha,
    ) -> float:
        """Per-alpha completeness threshold with platform-config fallback.

        Reads ``composition_completeness_threshold`` from the alpha's
        resolved params (audit P1-5); falls back to the engine-level
        platform-config value when the alpha does not declare one or
        declares an out-of-range / non-numeric value.
        """
        raw = registered.params.get("composition_completeness_threshold")
        if isinstance(raw, (int, float)) and not isinstance(raw, bool):
            value = float(raw)
            if 0.0 <= value <= 1.0:
                return value
        return self._completeness_threshold

    def _emit_degenerate(
        self,
        registered: RegisteredPortfolioAlpha,
        ctx: CrossSectionalContext,
        *,
        reason: str,
    ) -> None:
        """Publish an empty :class:`SizedPositionIntent` (hold positions)."""
        intent = SizedPositionIntent(
            timestamp_ns=ctx.timestamp_ns,
            sequence=self._intent_seq.next(),
            correlation_id=f"intent:{registered.alpha_id}:{ctx.horizon_seconds}:{ctx.boundary_index}:degenerate",
            source_layer="PORTFOLIO",
            strategy_id=registered.alpha_id,
            layer="PORTFOLIO",
            horizon_seconds=ctx.horizon_seconds,
            target_positions={},
            factor_exposures={},
            expected_turnover_usd=0.0,
            expected_gross_exposure_usd=0.0,
            mechanism_breakdown={},
        )
        _logger.debug(
            "CompositionEngine: emitted degenerate intent for %s (boundary %d): %s",
            registered.alpha_id,
            ctx.boundary_index,
            reason,
        )
        self._bus.publish(intent)

    # ── Helper for default pipeline alphas ──────────────────────────

    def run_default_pipeline(
        self,
        ctx: CrossSectionalContext,
        *,
        strategy_id: str,
        feeder_strategy_ids: tuple[str, ...] = (),
        capital_usd: float | None = None,
        mechanism_caps: Mapping[TrendMechanism, float] | None = None,
        global_mechanism_cap: float | None = None,
        decay_weighting_enabled: bool | None = None,
    ) -> SizedPositionIntent:
        """Execute the canonical ranker → neutralize → match → optimize chain.

        Used by :class:`feelies.alpha.portfolio_layer_module.LoadedPortfolioLayerModule`
        whose alpha is "the default pipeline".  Custom :class:`PortfolioAlpha`
        implementations can compose their own pipeline using the engine's
        public components.

        *mechanism_caps* / *global_mechanism_cap* are the alpha's declared
        ``trend_mechanism`` caps, threaded into the ranker so they are
        enforced at emit time (audit P0-4).  *decay_weighting_enabled*
        overrides the shared ranker's decay toggle for this alpha (audit
        P1-6); ``None`` falls back to the ranker's instance flag.
        """
        rank_result = self._ranker.rank(
            ctx,
            feeder_strategy_ids=feeder_strategy_ids,
            mechanism_caps=mechanism_caps,
            global_mechanism_cap=global_mechanism_cap,
            decay_weighting_enabled=decay_weighting_enabled,
        )
        neutral_weights, factor_exposures = self._neutralizer.neutralize(
            rank_result.weights,
            ctx.universe,
        )
        sector_matched = self._sector_matcher.neutralize(
            neutral_weights,
            ctx.universe,
        )
        # Look up current positions if a lookup is wired.
        current_positions: dict[str, float] = {}
        if self._position_lookup is not None:
            for s in ctx.universe:
                try:
                    current_positions[s] = float(self._position_lookup(s))
                except Exception:  # pragma: no cover - defensive
                    current_positions[s] = 0.0

        opt = self._optimizer.optimize(
            sector_matched,
            ctx.universe,
            current_positions,
        )

        target_positions = {
            s: TargetPosition(symbol=s, target_usd=v) for s, v in sorted(opt.target_usd.items())
        }
        # P0-5: report the *realised* mechanism breakdown computed from the
        # final dollar targets (post-neutralization, post-sector,
        # post-optimization), not the ranker's pre-construction shares.
        realised_breakdown = compute_mechanism_breakdown(
            opt.target_usd,
            rank_result.mechanism_by_symbol,
        )
        # P0-6: in-band provenance digest over the canonical decision
        # inputs (per-symbol raw scores + decay + mechanism, the turnover
        # reference positions, the resolved caps, and the alpha/boundary
        # identity) so structurally-equal intents derived from different
        # inputs are distinguishable.
        decision_basis_hash = _compute_decision_basis_hash(
            strategy_id=strategy_id,
            ctx=ctx,
            rank_result=rank_result,
            current_positions=current_positions,
            mechanism_caps=mechanism_caps,
            global_mechanism_cap=global_mechanism_cap,
        )
        return SizedPositionIntent(
            timestamp_ns=ctx.timestamp_ns,
            sequence=0,  # patched by the engine envelope
            correlation_id="",
            source_layer="PORTFOLIO",
            strategy_id=strategy_id,
            layer="PORTFOLIO",
            horizon_seconds=ctx.horizon_seconds,
            target_positions=target_positions,
            factor_exposures=factor_exposures,
            expected_turnover_usd=opt.expected_turnover_usd,
            expected_gross_exposure_usd=opt.expected_gross_exposure_usd,
            mechanism_breakdown=realised_breakdown,
            decision_basis_hash=decision_basis_hash,
            solver_status=opt.solver_status,
        )


__all__ = ["CompositionEngine", "RegisteredPortfolioAlpha"]
