"""``PortfolioAlpha`` ABC and supporting types (§6.5).

A :class:`PortfolioAlpha` is the Layer-3 analogue of a Layer-2
:class:`feelies.signals.horizon_protocol.HorizonSignal`: a *pure*
function from a barrier-synced :class:`CrossSectionalContext` to a
:class:`SizedPositionIntent`.

Determinism contract
--------------------

Implementations MUST be:

* **Pure** — no I/O, no wall-clock reads, no in-process state mutation
  outside the ``state`` argument provided to ``construct``.
* **Idempotent** — invoking ``construct`` twice on the same context
  with the same parameters returns equal intents (deep equality on
  :class:`SizedPositionIntent`).
* **Order-independent** — the implementation must not depend on
  ``ctx.signals_by_symbol`` iteration order.  Implementations that
  need a stable iteration order MUST sort by symbol explicitly.

Failure mode (Inv-11 fail-safe)
-------------------------------

When an implementation cannot construct a meaningful intent (e.g.
``ctx.completeness`` falls below threshold, or a numerical solver
returns infeasible), it MUST raise :class:`CompositionContextError`.
The :class:`feelies.composition.engine.CompositionEngine` wraps the
exception and emits a degenerate "no position change" intent — the
canonical safe-default per §11.4.

Symbol-universe contract
------------------------

The ``construct`` argument ``ctx.universe`` is the alpha's *effective*
universe at this barrier.  Symbols absent from ``signals_by_symbol`` or
mapped to ``None`` were stale or non-warm at the barrier close; the
alpha is responsible for defaulting their target weight (typically to
zero, holding the existing position).
"""

from __future__ import annotations

from typing import Any, Mapping, Protocol

from feelies.core.events import CrossSectionalContext, SizedPositionIntent


class CompositionContextError(Exception):
    """Raised when a portfolio alpha cannot construct an intent.

    The :class:`feelies.composition.engine.CompositionEngine` catches
    this and emits a degenerate "no position change" intent so the
    risk engine receives an authoritative "do nothing" signal rather
    than silently dropping the decision (Inv-11 fail-safe; §11.4).
    """


class PortfolioAlpha(Protocol):
    """Layer-3 alpha — converts cross-sectional context into target weights.

    Implementations are constructed by the
    :class:`feelies.alpha.loader.AlphaLoader` when it encounters a
    schema-1.1 ``layer: PORTFOLIO`` spec, and registered with the
    :class:`feelies.alpha.registry.AlphaRegistry` exactly like a
    LEGACY_SIGNAL or SIGNAL alpha.

    Attributes
    ----------
    alpha_id :
        Stable identifier (also the YAML ``alpha_id``).
    horizon_seconds :
        Decision horizon — the
        :class:`feelies.composition.synchronizer.UniverseSynchronizer`
        only emits :class:`CrossSectionalContext` events at boundaries
        of this horizon.
    """

    # Declared as read-only properties so concrete classes that expose
    # ``alpha_id`` / ``horizon_seconds`` as ``@property`` descriptors
    # (e.g. ``LoadedPortfolioLayerModule``, whose attributes are derived
    # from an immutable manifest) satisfy the protocol under
    # ``mypy --strict``.  Settable subclasses remain conformant — the
    # property contract is a strict subset of the attribute contract.
    @property
    def alpha_id(self) -> str: ...

    @property
    def horizon_seconds(self) -> int: ...

    def construct(
        self,
        ctx: CrossSectionalContext,
        params: Mapping[str, Any],
    ) -> SizedPositionIntent:
        """Convert *ctx* into a :class:`SizedPositionIntent`.

        Parameters
        ----------
        ctx :
            Universe-wide barrier-synced snapshot per §5.6.
        params :
            Resolved parameter mapping for this alpha (immutable).

        Returns
        -------
        :class:`SizedPositionIntent`
            Target positions per symbol.  Absent symbols are
            interpreted as "hold the existing position" by the risk
            engine.

        Raises
        ------
        CompositionContextError
            When the alpha cannot construct a meaningful intent for
            this context (e.g. completeness below threshold, solver
            infeasible).  The engine wraps the failure in a degenerate
            "no position change" intent.
        """
        ...


__all__ = ["CompositionContextError", "PortfolioAlpha"]
