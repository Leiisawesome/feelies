"""``CrossSectionalTracker`` — per-strategy aggregated exposure metrics.

A read-only consumer that listens to :class:`SizedPositionIntent`
events on the bus and records, **per strategy_id**, the latest:

* gross USD exposure        (sum of ``|target_usd|``)
* net USD exposure          (sum of ``target_usd``)
* expected turnover USD     (intent ``expected_turnover_usd``)
* factor exposures (post-neutralization residual)
* mechanism breakdown       (gross share per ``TrendMechanism``)
* completeness              (forwarded from the ``CrossSectionalContext``
  most recently observed for the same horizon)

The tracker maintains **only the latest snapshot per strategy_id** —
historical state belongs to the forensics layer
(:mod:`feelies.forensics.multi_horizon_attribution`).  Callers query
the latest snapshot via :meth:`snapshot`.

Determinism (Inv-5)
-------------------

The tracker performs no time reads — every recorded value is taken
verbatim from the intent event.  Two replays produce identical
snapshots.  Iteration over recorded strategies is lex-sorted to keep
JSON-serialised emissions bit-stable.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Mapping

from feelies.bus.event_bus import EventBus
from feelies.core.events import (
    CrossSectionalContext,
    SizedPositionIntent,
    TrendMechanism,
)

_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CrossSectionalSnapshot:
    """Latest aggregated metrics for one strategy.

    All USD values are floats (mirroring ``SizedPositionIntent``);
    ``mechanism_breakdown`` keys are :class:`TrendMechanism` enums so
    consumers (forensics, monitoring) can switch on them without
    re-parsing strings.
    """

    strategy_id: str
    horizon_seconds: int
    timestamp_ns: int
    boundary_index: int
    gross_usd: float
    net_usd: float
    expected_turnover_usd: float
    factor_exposures: dict[str, float] = field(default_factory=dict)
    mechanism_breakdown: dict[TrendMechanism, float] = field(default_factory=dict)
    completeness: float = 0.0


class CrossSectionalTracker:
    """Bus-attached tracker; one global instance per platform.

    The tracker subscribes to two events:

    * :class:`CrossSectionalContext` — observed first (synchronizer
      runs before the composition engine on the bus); records the
      barrier completeness so the next per-strategy snapshot can stamp
      it.
    * :class:`SizedPositionIntent` — observed second; records the
      per-strategy gross/net/exposure breakdown.

    Both subscriptions are lazily installed by :meth:`attach`.
    """

    __slots__ = (
        "_bus",
        "_attached",
        "_snapshots",
        "_last_completeness",
    )

    def __init__(self, *, bus: EventBus) -> None:
        self._bus = bus
        self._attached = False
        self._snapshots: dict[str, CrossSectionalSnapshot] = {}
        # Keyed by ``(horizon_seconds, boundary_index)`` so a per-
        # strategy intent picks up the completeness recorded at the
        # *same* barrier (intents lag the context by zero or more
        # bus deliveries; see CompositionEngine).
        self._last_completeness: dict[tuple[int, int], float] = {}

    # ── Public API ───────────────────────────────────────────────────

    def attach(self) -> None:
        if self._attached:
            return
        self._bus.subscribe(
            CrossSectionalContext, self._on_context,  # type: ignore[arg-type]
        )
        self._bus.subscribe(
            SizedPositionIntent, self._on_intent,  # type: ignore[arg-type]
        )
        self._attached = True

    def snapshot(self, strategy_id: str) -> CrossSectionalSnapshot | None:
        """Return the most recent snapshot for ``strategy_id`` (or ``None``)."""
        return self._snapshots.get(strategy_id)

    def all_snapshots(self) -> dict[str, CrossSectionalSnapshot]:
        """Lex-sorted dict of every strategy's most recent snapshot."""
        return dict(sorted(self._snapshots.items()))

    # ── Bus handlers ─────────────────────────────────────────────────

    def _on_context(self, ctx: CrossSectionalContext) -> None:
        self._last_completeness[(ctx.horizon_seconds, ctx.boundary_index)] = (
            float(ctx.completeness)
        )

    def _on_intent(self, intent: SizedPositionIntent) -> None:
        gross, net = self._gross_net(intent.target_positions)
        # Look up the completeness recorded for the same barrier; if
        # the intent arrived without a context (degenerate path) we
        # fall back to 0.0 — never to a stale value from a different
        # horizon.
        completeness = 0.0
        # ``boundary_index`` is implicit in the intent's correlation_id
        # (see CompositionEngine: "xsect:{h}:{bi}" → "xsect:{h}:{bi}");
        # parse defensively to keep the tracker decoupled from the
        # exact format.
        bi = self._parse_boundary_from_correlation(intent.correlation_id)
        if bi is not None:
            completeness = self._last_completeness.get(
                (intent.horizon_seconds, bi), 0.0,
            )

        self._snapshots[intent.strategy_id] = CrossSectionalSnapshot(
            strategy_id=intent.strategy_id,
            horizon_seconds=intent.horizon_seconds,
            timestamp_ns=intent.timestamp_ns,
            boundary_index=bi if bi is not None else -1,
            gross_usd=gross,
            net_usd=net,
            expected_turnover_usd=float(intent.expected_turnover_usd),
            factor_exposures=dict(intent.factor_exposures),
            mechanism_breakdown=dict(intent.mechanism_breakdown),
            completeness=completeness,
        )

    # ── Internals ────────────────────────────────────────────────────

    @staticmethod
    def _gross_net(
        target_positions: Mapping[str, object],
    ) -> tuple[float, float]:
        gross = 0.0
        net = 0.0
        for symbol in sorted(target_positions):
            tgt = target_positions[symbol]
            usd = float(getattr(tgt, "target_usd", 0.0))
            gross += abs(usd)
            net += usd
        return gross, net

    @staticmethod
    def _parse_boundary_from_correlation(cid: str) -> int | None:
        """Parse the boundary index from either an intent or context cid.

        Engine intents use ``intent:{alpha_id}:{horizon_seconds}:{boundary_index}``
        (or ``...:degenerate``).  Contexts use
        ``xsect:{horizon_seconds}:{boundary_index}``.  Returns ``None``
        on any other format so the tracker stays robust against future
        format changes.
        """
        if cid.startswith("xsect:"):
            parts = cid.split(":")
            if len(parts) != 3:
                return None
            try:
                return int(parts[2])
            except ValueError:
                return None
        if cid.startswith("intent:"):
            parts = cid.split(":")
            if len(parts) < 4:
                return None
            try:
                return int(parts[3])
            except ValueError:
                return None
        return None


__all__ = ["CrossSectionalSnapshot", "CrossSectionalTracker"]
