# Order Lifecycle — State Machine Detail

Complete state transition reference for the live execution order state machine.

## State Transition Diagram

```
CREATED
  ├─ risk_approved ──> RISK_APPROVED
  └─ risk_rejected ──> RISK_REJECTED (terminal)

RISK_APPROVED
  └─ submit ──> SUBMITTED

SUBMITTED
  ├─ ack_received ──────> ACKNOWLEDGED
  ├─ rejected ──────────> REJECTED (terminal)
  ├─ timeout_expired ───> CANCEL_PENDING
  └─ fill_before_ack ──> PARTIALLY_FILLED or FILLED (reconcile ack later)

ACKNOWLEDGED
  ├─ partial_fill ──> PARTIALLY_FILLED
  ├─ full_fill ─────> FILLED (terminal)
  ├─ cancel_request ─> CANCEL_PENDING
  ├─ expired ────────> EXPIRED (terminal)
  └─ error ──────────> ERROR (terminal)

PARTIALLY_FILLED
  ├─ additional_fill ──> PARTIALLY_FILLED (self-loop; update fill qty)
  ├─ final_fill ───────> FILLED (terminal)
  ├─ cancel_request ───> CANCEL_PENDING (cancel remaining)
  └─ expired ──────────> EXPIRED (terminal; partial fill stands)

CANCEL_PENDING
  ├─ cancel_confirmed ──> CANCELLED (terminal)
  ├─ cancel_rejected ───> ACKNOWLEDGED (re-enter; cancel failed)
  ├─ fill_during_cancel ─> FILLED or PARTIALLY_FILLED (race condition)
  └─ timeout_expired ───> ERROR (terminal; escalate)

Terminal states: RISK_REJECTED, FILLED, CANCELLED, REJECTED, EXPIRED, ERROR
```

## Transition Event Schema

Every state transition emits:

```
{
  "order_id": str,
  "idempotency_key": str,
  "from_state": OrderState,
  "to_state": OrderState,
  "trigger": str,
  "timestamp": int (UTC nanoseconds),
  "metadata": {
    "fill_price": float | null,
    "fill_qty": int | null,
    "reject_reason": str | null,
    "broker_order_id": str | null
  }
}
```

All transitions are persisted to the order journal append-only log.

## Edge Cases

### Fill-Before-Ack

Broker sends an execution report before the acknowledgment message.

1. Accept the fill; create an internal ack
2. Transition: `SUBMITTED` -> `PARTIALLY_FILLED` or `FILLED`
3. If a late ack arrives, log and ignore (idempotent)
4. If a late reject arrives after a fill, this is a broker error — escalate

### Race: Fill During Cancel

Cancel request crosses with a fill in flight.

1. If fill arrives before cancel-ack: accept fill, update quantities
2. If fill is partial and cancel-ack also arrives: order is cancelled with partial fill
3. If fill is full and cancel-ack also arrives: ignore cancel-ack; order is filled
4. The fill always wins — never discard a confirmed fill

### Timeout Escalation

```
SUBMITTED, no ack within 5s:
  -> Send cancel request
  -> Transition to CANCEL_PENDING
  -> Query order status from broker

  If broker says order exists:
    -> Wait for cancel confirmation
  If broker says order unknown:
    -> Transition to CANCELLED (assumed never received)
  If broker query times out:
    -> Transition to ERROR
    -> Trigger position reconciliation
```

### Stale State Detection

An order in a non-terminal state for longer than its expected lifetime is stale:

| State | Max Lifetime | Action |
|-------|-------------|--------|
| SUBMITTED | 10s | Force cancel; reconcile |
| ACKNOWLEDGED | Strategy-defined TTL | Cancel if TTL exceeded |
| PARTIALLY_FILLED | Strategy-defined TTL | Cancel remaining if TTL exceeded |
| CANCEL_PENDING | 10s | Query broker; escalate to ERROR |

A background reaper process scans for stale orders every 5s.

## Order Journal

The order journal is an append-only log of all state transitions. It supports:

- **Audit**: reconstruct the full history of any order
- **Replay**: reproduce order flow for debugging
- **Reconciliation**: compare journal against broker records
- **Analytics**: compute execution quality metrics post-session

Journal entries are flushed synchronously before the transition is applied
internally. If the system crashes mid-transition, recovery replays from the
journal to reconstruct consistent state.

## Idempotency Key Generation

```
idempotency_key = SHA256(
  signal_id       +  # unique per signal emission
  symbol          +  # instrument
  side            +  # BUY or SELL
  size            +  # order quantity
  floor(timestamp / bucket_size)  # time bucket (default: 1s)
)
```

The time bucket prevents replay of old signals while allowing retry within
the same logical decision window. Bucket size is configurable per strategy.

Keys are stored in a bounded LRU cache (default: 10,000 entries, 5-minute TTL).
Expired keys are also persisted in the journal for audit.
