# Order Lifecycle — State Machine Detail

Complete state transition reference for the `OrderState` SM
(`execution/order_state.py`). Each order gets its own `StateMachine[OrderState]`
instance, tracked in `Orchestrator._active_orders`.

## State Transition Diagram (9-state)

```
CREATED
  └─ submitted ──> SUBMITTED

SUBMITTED
  ├─ broker_ack ─────> ACKNOWLEDGED
  └─ broker_reject ──> REJECTED (terminal)

ACKNOWLEDGED
  ├─ partial_fill ──────> PARTIALLY_FILLED
  ├─ fill_complete ─────> FILLED (terminal)
  ├─ cancel_requested ──> CANCEL_REQUESTED
  └─ order_expired ─────> EXPIRED (terminal)

PARTIALLY_FILLED
  ├─ partial_fill ──> PARTIALLY_FILLED (self-loop)
  └─ fill_complete ─> FILLED (terminal)

CANCEL_REQUESTED
  ├─ broker_cancel ──> CANCELLED (terminal)
  └─ fill_complete ──> FILLED (terminal; fill beats cancel)

Terminal states: FILLED, CANCELLED, REJECTED, EXPIRED
```

Note: risk approval/rejection happens **before** order construction
(at M5 `check_signal` and M6 `check_order` in the micro-state pipeline),
not as order states. RISK_APPROVED and RISK_REJECTED from the original
spec were removed — risk is a pre-construction gate, not an order lifecycle
phase. The ERROR state was also removed — errors are handled via the
fail-safe cascade (micro reset + macro DEGRADED).

## Transition Event Schema

Every state transition emits a `StateTransition` event (`core/events.py`)
via `TransitionRecord` callback on the order's `StateMachine[OrderState]`:

```python
@dataclass(frozen=True)
class TransitionRecord:
    machine_name: str       # "order:{order_id}"
    from_state: str
    to_state: str
    trigger: str            # e.g., "broker_ack", "fill_complete", "cancel_requested:operator"
    timestamp_ns: int
    correlation_id: str
    metadata: dict[str, Any]
```

The orchestrator converts each `TransitionRecord` to a `StateTransition`
event on the bus, ensuring no silent transitions (invariant 13).

Fill details are communicated via `OrderAck` events with typed
`OrderAckStatus` (ACKNOWLEDGED, PARTIALLY_FILLED, FILLED, CANCELLED,
REJECTED, EXPIRED). The `_apply_ack_to_order()` method maps each status
to the appropriate order SM transition.

## Edge Cases

### Fill-Before-Ack

Broker sends a fill `OrderAck` before an ACKNOWLEDGED ack. The
`_apply_ack_to_order()` method handles this by auto-acknowledging first:

1. If SM is SUBMITTED and ack status is FILLED/PARTIALLY_FILLED/CANCELLED/EXPIRED:
   auto-transition SUBMITTED → ACKNOWLEDGED via implicit `broker_ack`
2. Then apply the fill/cancel/expiry transition from ACKNOWLEDGED
3. If a late ACKNOWLEDGED ack arrives afterward, it's a no-op (SM already past that state)

### Race: Fill During Cancel

Cancel request crosses with a fill in flight. The `OrderState` SM
handles this structurally:

- `CANCEL_REQUESTED → FILLED` is a legal transition (fill beats cancel)
- `CANCEL_REQUESTED → CANCELLED` is a legal transition (cancel confirmed)
- If a CANCELLED ack arrives but the SM is already FILLED, `can_transition`
  returns False and an `ack_inapplicable_to_order_state` alert is emitted
- The fill always wins — never discard a confirmed fill

### Timeout Escalation

The 9-state `OrderState` SM has no `CANCEL_PENDING` or `ERROR` state.
A submission that ack-times-out is escalated within the existing
transition table:

```
SUBMITTED, no ack within 5s:
  -> Orchestrator.cancel_order(order_id, reason="ack_timeout")
     -> SM transition: SUBMITTED → CANCEL_REQUESTED
        (via auto-ack to ACKNOWLEDGED first, then CANCEL_REQUESTED;
         see _apply_ack_to_order Fill-Before-Ack handling)
  -> Query order status from broker

  If broker says order exists:
    -> Wait for CANCELLED ack on the existing CANCEL_REQUESTED SM
  If broker says order unknown:
    -> Emit synthetic CANCELLED ack
       -> SM transition: CANCEL_REQUESTED → CANCELLED (terminal)
  If broker query times out:
    -> Fail-safe cascade: _handle_tick_failure
       -> Macro transitions to DEGRADED; position reconciliation runs
          via _reconcile_fills before any further ticks
```

Errors are handled by the macro-level fail-safe cascade
(`_handle_tick_failure` → DEGRADED), not by an order-level `ERROR`
state. Risk approval/rejection happens **before** order construction
(M5/M6); it is also not an order-lifecycle phase.

### Stale State Detection

> **NOT YET IMPLEMENTED** — The background reaper described below is a
> design target; the hook point is `Orchestrator._active_orders`.

An order in a non-terminal state for longer than its expected lifetime is stale:

| State | Max Lifetime | Action |
|-------|-------------|--------|
| SUBMITTED | 10s | Cancel via `cancel_order()` |
| ACKNOWLEDGED | Strategy-defined TTL | Cancel if TTL exceeded |
| PARTIALLY_FILLED | Strategy-defined TTL | Cancel remaining if TTL exceeded |
| CANCEL_REQUESTED | 10s | Escalate via `_escalate_risk()` |

A background reaper process scans for stale orders every 5s.
The `cancel_order()` method on `Orchestrator` transitions the order SM
to `CANCEL_REQUESTED` and submits a cancel to the `OrderRouter`.

## Order Journal

The `TradeJournal` protocol (`src/feelies/storage/trade_journal.py`) provides the
append-only log for completed trades as `TradeRecord` dataclasses. For
full order state transition history, every SM transition is emitted as
a `StateTransition` event and persisted by the `EventLog` protocol
(`src/feelies/storage/event_log.py`). Together they support:

- **Audit**: reconstruct the full history of any order via `StateTransition` events
- **Replay**: reproduce order flow for debugging (deterministic replay invariant)
- **Reconciliation**: compare journal against broker records via `_reconcile_fills()`
- **Analytics**: compute execution quality metrics from `TradeRecord`s post-session

## Deterministic Order ID Generation

Order IDs are generated via SHA-256 in `Orchestrator._build_order_from_intent()`:

```python
seq = self._seq.next()
order_id = hashlib.sha256(
    f"{correlation_id}:{seq}".encode()
).hexdigest()[:16]
```

The input is `correlation_id` (which ties back to the originating tick
via `make_correlation_id(symbol, exchange_timestamp_ns, sequence)` from
`core/identifiers.py`) concatenated with a monotonic sequence number
from `SequenceGenerator`. This produces deterministic IDs for backtest
replay (Inv-5). The same event log replayed with the same parameters
always generates the same order IDs — locked by the L2, L3-orders, and
L4 parity hashes (`tests/determinism/`).

An exhaustiveness guard in `_side_from_intent()` ensures every
`TradingIntent` enum member is explicitly handled. `FLAT` signals
are handled by the `IntentTranslator` which returns `NO_ACTION`,
causing the pipeline to skip from M4 directly to M10 — before the
risk check at M5.

## `OrderRequest.reason` Lineage

Each emitted `OrderRequest` carries a `reason` string identifying its
origin layer for forensic attribution and per-strategy quarantine:

| `reason` | Origin | Path |
|----------|--------|------|
| `"SIGNAL"` | Layer-2 SIGNAL alpha → `IntentTranslator` | M4 → M5 → M6 → M7 |
| `"PORTFOLIO"` | Layer-3 PORTFOLIO alpha → `RiskEngine.check_sized_intent` | CROSS_SECTIONAL → M5 (per-leg) → M7 |
| `"HAZARD_SPIKE"` | `HazardExitController` consuming `RegimeHazardSpike` | hazard branch → M7 |
| `"HARD_EXIT_AGE"` | `HazardExitController` time-cap branch | hazard branch → M7 |

Post-trade-forensics consumes these via the `MultiHorizonAttributor`
and `OrderRequest`-keyed `TradeRecord` joins.

> **Future**: LRU-based deduplication cache for live mode, keyed by
> order ID, to prevent accidental double-submission.
