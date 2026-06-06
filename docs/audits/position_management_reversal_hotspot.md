# Position-Management Reversal Hotspot — Design Audit & Implementation Prompt

> **Purpose:** This document is both a design audit note and a self-contained
> Claude Code prompt. The "Background" sections describe the problem. The
> "Task" sections describe the exact code changes to implement. Read the
> background first; then execute the tasks in order.

---

## Background — the APP observed case

During a 4-day APP backtest replay (2026-06-01 to 2026-06-04) the single
largest realized loss on 2026-06-02 was **-$243.00** from this trade record:

```
2026-06-02 12:54:02 EDT | SELL 50 @ 600.81 | realized -$243.00 | sig_benign_midcap_v1
```

Trace of what happened:

| Time (ET) | Event |
|-----------|-------|
| 12:16:09  | BUY 50 APP @ 605.67 — entry long from LONG signal |
| 12:54:01  | SHORT signal fires: `ofi_ewma_zscore = -2.27`, `strength = 0.758`, `edge = 13.6 bps`, `regime_gate = ON` |
| 12:54:02  | `REVERSE_LONG_TO_SHORT` intent translated — EXIT leg (MARKET SELL 50) fills @ 600.81 |
| 12:55:53  | New short ENTRY leg fills @ 601.52 |
| 12:56:11  | That short closed for +$4.50 |

The loss comes entirely from the exit leg of the reversal. Every gate said
green (`RiskAction.ALLOW`, `regime_gate = ON`, RTH within session). The
signal was not wrong in isolation. The loss came from the fact that the
current book was opposite the new signal direction.

### Why this is a structural hotspot, not a one-off

The current code path for a reversal is:

```
orchestrator._process_tick_inner
  -> _compute_target_quantity           # BudgetBasedSizer
  -> intent_translator.translate(signal, position, target_qty)
      -> SignalPositionTranslator._handle_short(qty=+50, tgt=50)
          -> REVERSE_LONG_TO_SHORT  (target_quantity = 50+50 = 100)
  -> risk_engine.check_signal(signal, positions)   # gate 1: ALLOW
  -> _execute_reverse(intent, verdict, cid, quote)
      -> EXIT leg: MARKET SELL 50
      -> risk_engine.check_order(exit_order, positions)  # gate 2: ALLOW
      -> ENTRY leg: LIMIT SELL 50 @ ask
      -> risk_engine.check_order(entry_order, post_exit_positions)  # gate 3: ALLOW
```

**What is missing:** nowhere in this pipeline is the question asked:
> "Does the raw signal edge on the *new* direction exceed the round-trip
> cost of *first closing the existing opposite position*?"

The existing `_signal_passes_edge_cost_gate` guard in `orchestrator.py`
(around line 2560) is only applied to the *entry leg*. It is entirely
absent from the *reversal decision* itself — i.e., from the point at which
the system decides to flip rather than just exit and wait.

A signal with 13.6 bps edge authorises a reversal that first crystallises
unrealised loss from the existing book, which may dwarf the edge being
captured.

### The general pattern

```
delta_q = q_target - q_current
```

When sign(q_target) != sign(q_current), delta_q must pass through zero. The
cost of that zero-crossing is **independent of the new signal's edge** but is
paid immediately. The signal edge is earned only if the new position is
also correct.

Any alpha family is exposed:

- Kyle-style momentum (this case): directional flip intra-session.
- Mean-reversion: overshoot recovery flips sign.
- Regime-transition strategies: model flip after regime change.
- Multi-alpha systems: one alpha exits while another enters opposite.

---

## Background — current code surface to modify

| File | Role |
|------|------|
| `src/feelies/kernel/orchestrator.py` | Main reversal entry point ~line 2240 (`_execute_reverse`). Edge-cost gate ~line 2560 (`_signal_passes_edge_cost_gate`). |
| `src/feelies/execution/intent.py` | `SignalPositionTranslator` and `TradingIntent`. The `REVERSE_*` intents are set here without cost awareness. |
| `src/feelies/risk/basic_risk.py` | `check_signal` ~line 143. Currently passes reversals because `signal_reduces = True` for the opposite side. |
| `src/feelies/core/platform_config.py` | Config dataclass. New config knob lives here. |
| `src/feelies/harness/backtest_report.py` | Report generation — reversal stats should appear here. |
| `tests/kernel/test_orchestrator.py` | Regression tests for orchestrator paths. |
| `alphas/sig_benign_midcap_v1/sig_benign_midcap_v1.alpha.yaml` | Reference alpha used in the observed case. |

---

## Task 1 — Add a reversal edge guard in `_execute_reverse`

**File:** `src/feelies/kernel/orchestrator.py`

**Where:** Inside `_execute_reverse`, before the EXIT leg is submitted
(currently the first action after `_cancel_resting_for_symbol`).

**What to add:** a `_reversal_passes_combined_edge_gate` helper check:

```
signal.edge_estimate_bps
    > (exit_roundtrip_cost_bps + entry_roundtrip_cost_bps)
      * self._reversal_min_edge_cost_multiplier
```

- `exit_roundtrip_cost_bps` — cost model estimate for closing the existing
  opposite position (half-spread + impact for the exit side). Reuse
  `_signal_passes_edge_cost_gate`'s internal `round_trip_cost_bps`
  computation, called for the exit side.
- `entry_roundtrip_cost_bps` — same computation for the new entry side.
- `self._reversal_min_edge_cost_multiplier` — sourced from
  `PlatformConfig.reversal_min_edge_cost_multiplier` (Task 2).

If the guard fires:
1. Submit **only** the exit leg (do not flip — just flatten). This
   preserves Inv-11.
2. Publish an `Alert`:
   - `alert_name="reversal_edge_insufficient"`
   - `severity="WARNING"`
   - `message` containing symbol, edge_bps, required_bps, deficit_bps
   - `constraints={"edge_bps": ..., "required_bps": ..., "deficit_bps": ...}`
3. Record `"reversal_edge_guard_flat_exit"` in the `signal_order_trace_sink`
   (same pattern as the existing `"reverse_exit_only"` trace).

The guard is a **no-op** when `self._reversal_min_edge_cost_multiplier == 0`
or when `self._cost_model is None`.

---

## Task 2 — Add `reversal_min_edge_cost_multiplier` to `PlatformConfig`

**File:** `src/feelies/core/platform_config.py`

Add to `PlatformConfig`:

```python
# B5: reversal edge guard. Entry leg of a REVERSE intent is suppressed
# unless signal.edge_estimate_bps exceeds this multiplier times the
# combined exit + entry round-trip cost. 0.0 = disabled (legacy).
reversal_min_edge_cost_multiplier: float = 1.5
```

Wire it through `to_dict` / `from_dict` using the same pattern as
`signal_min_edge_cost_ratio` (search that string in `platform_config.py`).

Also wire it into `orchestrator.py`'s boot path where
`self._signal_min_edge_cost_ratio` is read from config (line ~1049).

---

## Task 3 — Add `reversal_cost_estimate_bps` to `Signal`

**File:** `src/feelies/core/events.py`

Add an optional field to the `Signal` dataclass (after
`disclosed_cost_total_bps`):

```python
reversal_cost_estimate_bps: float = 0.0
```

The orchestrator populates this in `_execute_reverse` with
`exit_roundtrip_cost_bps + entry_roundtrip_cost_bps` before the guard
decision, so the value is available to trace sinks and alerts without
recomputing it. All existing `Signal` producers leave it at `0.0`
(backward-compatible, additive field).

---

## Task 4 — Add `trading_intent` to `TradeRecord`

**File:** wherever `class TradeRecord` is defined (search
`src/feelies/`).

Add:

```python
trading_intent: str = ""  # TradingIntent.name at order submission time
```

Populate it in the fill reconciliation path (`_reconcile_fills` in
`orchestrator.py`). This enables the report and analytics to split
journal records by intent type without re-deriving it from fill order.

---

## Task 5 — Surface reversal stats in the backtest report

**File:** `src/feelies/harness/backtest_report.py`

Add a `Reversals` sub-block inside `[TRADE ANALYSIS]`:

```
  Reversals attempted        N
  Reversals executed (full)  M
  Reversals flat-exit only   N-M    (edge guard triggered)
  Avg exit-leg realized      $X.XX
  Worst exit-leg realized    $X.XX
```

Source the data from `TradeRecord.trading_intent` (Task 4). A reversal
"attempted" is any record with `trading_intent` in
`{"REVERSE_LONG_TO_SHORT", "REVERSE_SHORT_TO_LONG"}`. A reversal
"flat-exit only" is a fill whose `order_id` appears in the alert log with
`alert_name="reversal_edge_insufficient"`.

---

## Task 6 — Regression tests

**File:** `tests/kernel/test_orchestrator.py`

Add three tests:

**Test A** — `test_reversal_blocked_when_edge_insufficient`

Set `reversal_min_edge_cost_multiplier = 2.0`. Inject a SHORT signal with
`edge_estimate_bps = 5.0` against a +50 long position. Assert:
- only the exit order is submitted (no entry order),
- an `Alert` with `alert_name="reversal_edge_insufficient"` is published.

**Test B** — `test_reversal_allowed_when_edge_sufficient`

Same setup, `edge_estimate_bps = 30.0`. Assert both exit and entry orders
are submitted.

**Test C** — `test_reversal_exit_never_suppressed_by_edge_guard`

Set `reversal_min_edge_cost_multiplier = 100.0` (extreme). Assert the
exit order still submits even when the entry is blocked. This is the
Inv-11 preservation test.

---

## Acceptance criteria

Run these commands and confirm all pass before declaring the work complete:

```bash
uv run pytest tests/kernel/test_orchestrator.py
uv run pytest -m "not functional and not slow"
uv run python scripts/run_backtest.py \
    --config configs/backtest_app.yaml \
    --symbol APP \
    --date 2026-06-01 \
    --end-date 2026-06-04
uv run ruff check src/ tests/
uv run mypy src/feelies
```

The backtest report must contain a `Reversals` block. The parity hash for
the single-day `2026-06-01` replay must be unchanged from the
pre-implementation baseline (determinism invariant).

---

## Invariants that must not be broken

| Invariant | Rule | Verified by |
|-----------|------|-------------|
| Inv-11 | Exit orders always submit regardless of edge gate | Task 6 Test C |
| Inv-5 | Same inputs -> same outputs (deterministic replay) | Parity hash comparison |
| B4 | Entry edge gate still applies to non-reversal entries | Existing passing tests |
| Fail-safe | Unknown cost model -> guard disabled, not crashed | Guard no-op when `self._cost_model is None` |

---

## Implementation notes

- Reuse `_signal_passes_edge_cost_gate`'s `round_trip_cost_bps` calculation
  rather than duplicating the cost model call. The new helper needs to call
  it twice (once for exit side, once for entry side).
- The guard must not alter `SignalPositionTranslator` — intent
  classification is correct; the guard lives entirely in `_execute_reverse`.
- `reversal_cost_estimate_bps` on `Signal` is additive; all existing
  producers leave it at `0.0`. No parity hashes are affected by the field
  addition alone.
- The `Alert.constraints` dict should use the same keys as the existing
  `signal_edge_below_min_edge_cost_ratio_gate` alert for forensics
  consistency.
