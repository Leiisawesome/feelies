"""Trading intent translator — Signal x Position -> OrderAction.

Bridges the gap between a stateless signal ("the market looks long")
and a stateful trading action ("given my current position, here's
what I need to do").  The signal engine is pure and position-unaware;
the intent translator injects position awareness.

The orchestrator calls the translator between M4 (signal evaluate)
and M6 (order decision).  The translator determines whether to
enter, exit, reverse, scale up, or do nothing.

Invariants preserved:
  - Inv 5 (deterministic): same signal + position → same intent
  - Inv 8 (layer separation): translator is injectable, not embedded
    in the orchestrator
  - Inv 11 (fail-safe): unknown states → NO_ACTION
"""

from __future__ import annotations

from feelies.core.intent import IntentTranslator as IntentTranslator
from feelies.core.intent import OrderIntent as OrderIntent
from feelies.core.intent import SignalPositionTranslator as SignalPositionTranslator
from feelies.core.intent import TradingIntent as TradingIntent
