# Position-Management Baseline & Gap Analysis — feelies

**Date:** 2026-06-08
**Scope:** the full signal→position decision path and every position
close/reduce path:
`src/feelies/kernel/orchestrator.py` (`_process_tick_inner`, sizing,
intent dispatch, gates, `_execute_reverse`, `_check_stop_exit`,
`_emergency_flatten_all`, `_on_bus_hazard_order`, halt/RTH handling),
`src/feelies/execution/intent.py` (`SignalPositionTranslator`),
`src/feelies/risk/position_sizer.py` (`BudgetBasedSizer`),
`src/feelies/risk/hazard_exit.py` (`HazardExitController`),
`src/feelies/portfolio/{position_store,memory_position_store,strategy_position_store}.py`.
**Mode:** Read-only, evidence-based. This is a **baseline map + gap
analysis**, not a remediation. No code is changed by this document.
**Context:** commissioned after the B5 reversal-edge-guard work
(`docs/audits/position_management_reversal_hotspot.md`, PR #100)
revealed the reversal loss was the *tip* of a broader
position-management gap.

> Severity legend: **P0** correctness / safety control absent or
> economically unsafe by default, **P1** economic soundness / missing
> capability that materially affects realized PnL, **P2**
> research / robustness / cleanup. Effort S / M / L.

---

## 0. How to read this

Part 1 is the **factual baseline** — exactly what the system does today
when a signal fires, with file:line citations. Part 2 is the **gap
analysis** — where that behavior falls short of an institutional-retail
grade position manager, tiered by severity. Part 3 scopes what is *not*
broken so remediation stays surgical. Part 4 proposes sequencing.

The two root causes that nearly every gap traces back to:

- **RC-A — the decision layer is quantity-only.** Intent is derived from
  `target − current_quantity` and nothing else. It never reads avg
  price, unrealized PnL, holding age, or the cost of the book it is
  about to disturb.
- **RC-B — the book is a netted single-average ledger.** One blended
  `avg_entry_price` and one signed `quantity` per symbol. No lots, no
  holding age per lot, no intent/strategy tag, no per-alpha attribution
  at the point of decision.

---

## Part 1 — Baseline: position management on signal trigger

### 1.1 Tick entry & signal selection (M0→M4)

`Orchestrator._process_tick_inner` (`orchestrator.py:1832`) walks a
micro-state machine M0→M10 per quote. Relevant to position management:

- Signals arrive on the bus and are buffered; **at most one signal per
  tick** drives the trade walk. Multiple buffered signals are resolved
  by an `EdgeWeightedArbitrator` (`_select_bus_signal`,
  `orchestrator.py:2046`).
- `_check_stop_exit(quote)` (`orchestrator.py:3127`) runs **inline at
  M4** and, if it fires, **replaces** the selected alpha signal
  (`orchestrator.py:2049-2059`). "Position safety beats alpha
  conviction" (Inv-11).
- Marks are refreshed first (`update_mark`, `orchestrator.py:1949`) so
  unrealized PnL and the drawdown high-water mark reflect live BBO.

### 1.2 Sizing — `BudgetBasedSizer` (`position_sizer.py:78-99`)

The target is a deterministic, single-factor formula:

```
target_shares = floor( account_equity
                       × (capital_allocation_pct / 100)
                       × max(0, signal.strength)
                       × regime_factor
                       / symbol_price )
capped at risk_budget.max_position_per_symbol, floored at 0
```

Properties that matter for position management:

- **Unsigned and absolute.** It is a *target position size*, not an
  increment. Direction is the translator's job (`position_sizer.py:35-40`).
- **`signal.edge_estimate_bps` is not used by the sizer at all.** Edge
  feeds the downstream cost gates (B4/B5), never the size.
- **`regime_factor` can only shrink** — clamped `min(1.0, EV)`
  (`position_sizer.py:122`, Inv-11). No regime can *amplify*.
- No volatility targeting, no Kelly / edge-weighted sizing, no inventory
  or risk-parity term. `risk_budget` comes from
  `alpha.manifest.risk_budget` (`alpha/module.py`).

### 1.3 Intent translation — the 7-intent matrix (`intent.py:73-214`)

This is the heart of position management. `SignalPositionTranslator`
is a pure **signal-direction × current-quantity** matrix:

| Signal | Position | Intent | Quantity |
|--------|----------|--------|----------|
| LONG  | 0        | `ENTRY_LONG`            | target          |
| LONG  | +N ≥ tgt | `NO_ACTION`             | 0               |
| LONG  | +N < tgt | `SCALE_UP`              | tgt − N         |
| LONG  | −N       | `REVERSE_SHORT_TO_LONG` | N + tgt         |
| SHORT | +N       | `REVERSE_LONG_TO_SHORT` | N + tgt         |
| SHORT | −N ≥ tgt | `NO_ACTION`             | 0               |
| SHORT | −N < tgt | `SCALE_UP`              | tgt − \|N\|     |
| FLAT  | ±N       | `EXIT`                  | \|N\|           |
| FLAT  | 0        | `NO_ACTION`             | 0               |

The translator reads **only `position.quantity`** (`intent.py:105`).
It does not consult avg price, unrealized PnL, age, or cost. This is
RC-A in its purest form.

### 1.4 Gates (M5→M6, `orchestrator.py:2102-2440`)

In order: `check_signal` (`2109`) → halt-resolution blackout for
entry-opening intents (`2173`) → SSR / Reg-SHO short refusal (`2199`)
→ short-locate / borrow gate (`2219`) → dispatch. Inside the
entry/reverse builders sit the **B4 edge-vs-cost gate**
(`_signal_passes_edge_cost_gate`) and the new **B5 reversal-edge gate**
(`_reversal_passes_combined_edge_gate`). `SCALE_DOWN` verdicts from the
two risk gates are composed (tightest cap wins), not multiplied
(`orchestrator.py:2329`).

### 1.5 Execution paths

- **ENTRY_LONG / ENTRY_SHORT / SCALE_UP** → `_try_build_order_from_intent`
  → `check_order` → submit (`orchestrator.py:2246-2416`).
- **EXIT** → same builder; exits **bypass `min_order_shares`** and the
  edge gate (`orchestrator.py:3665-3680`).
- **REVERSE_*** → `_execute_reverse` (`orchestrator.py:3242`): full-size
  MARKET exit leg + passive/own-mode entry leg (now guarded by B5).

### 1.6 Position store semantics (`memory_position_store.py:49-101`)

A single-average-price, netted ledger per symbol:

- **Open** (old_qty 0): `avg = fill_price`.
- **Add** (same sign): `avg = (avg·|old| + fill·|Δ|) / |new|`
  (`memory_position_store.py:78-80`).
- **Reduce** (opposite sign, no cross): realize
  `(fill − avg)·closed` for longs, `(avg − fill)·closed` for shorts
  (`memory_position_store.py:81-87`).
- **Cross-through-zero**: realize the closed leg, then reset `avg` to
  the reversal fill price for the residual
  (`memory_position_store.py:89-90`).
- **Mark**: longs → bid, shorts → ask, fallback mid; `unrealized =
  (mark − avg)·qty` (`memory_position_store.py:137-151`).

**No FIFO/LIFO lots, no per-lot holding age, no intent or strategy tag.**
One blended number per symbol. This is RC-B.

### 1.7 Multi-alpha netting (`strategy_position_store.py:95-131`)

`StrategyPositionStore` keeps a per-alpha sub-book each, but exposes a
**netted aggregate view** (`get_aggregate`): it sums signed quantities
and weighted-average cost across alphas. The orchestrator's intent
translation runs against this **net**. Consequence: when two alphas
disagree, the book they see is already collapsed — one alpha's exit can
be another's entry against the same physical share, invisibly.

### 1.8 Close / reduce paths — seven mechanisms, one hierarchy

Six of seven are **full-position MARKET flattens**:

| # | Mechanism | Trigger | Order | Qty | Risk gate |
|---|-----------|---------|-------|-----|-----------|
| 1 | **Stop-loss exit** (`orchestrator.py:3127`) | fixed: `unreal/sh < −threshold`; trailing: drawdown from peak > `trail_pct` | MARKET | full | none (bypasses all) |
| 2 | **Hazard-spike** (`hazard_exit.py:148`) | `RegimeHazardSpike` score ≥ threshold + age ≥ min_age | MARKET | full | audit-only (REJECT still submits) |
| 3 | **Hard-exit-age** (`hazard_exit.py:166`) | position age ≥ `hard_exit_age_seconds` | MARKET | full | audit-only |
| 4 | **Risk-escalation flatten** (`orchestrator.py:3007`) | `FORCE_FLATTEN` (drawdown breach) | MARKET | full, all symbols | none; bypasses micro-SM |
| 5 | **Reverse exit leg** (`orchestrator.py:3242`) | REVERSE intent | MARKET | full existing | checked; failure aborts |
| 6 | **Normal FLAT exit** (`intent.py:123`) | FLAT signal → `EXIT` | MARKET or passive LIMIT | full | yes (size never rejects an exit) |
| 7 | **Halt** (`orchestrator.py:4954`) | LULD condition codes | cancels resting; blocks *entries* | — | exits still permitted |

**Override hierarchy (who wins on a tick):**

```
FORCE_FLATTEN (risk escalation R3→G8 lockdown)      ← highest, irreversible
   > stop-loss exit (__stop_exit__, inline override)
   > hazard / hard-age exits (async bus RISK orders, submit even on REJECT)
   > alpha signal (entry / scale / reverse / FLAT-exit)   ← lowest
```

Stop-exit is computed inline at M4 and replaces the alpha signal
(`orchestrator.py:2058-2059`). Hazard/age exits arrive asynchronously
(`_on_bus_hazard_order`, `orchestrator.py:4855`) and are episode-
suppressed (one per open episode). Emergency flatten runs **outside**
the micro-SM, iterating all symbols lexicographically, no risk check,
no min-lot (`orchestrator.py:3007-3125`).

**Two notable absences:**

- **No end-of-day / session-close flatten exists.** At RTH close the
  system only flips buying-power phase (4×→2×) and gates *new entries*;
  open positions **persist into after-hours**
  (`_maybe_flip_buying_power_at_rth_close`, `orchestrator.py:843`).
- **MOC routing is entry-only**, not a closing mechanism.

### 1.9 The consolidated lifecycle

```
SIGNAL fires
  ├─ _check_stop_exit ──(overrides)──► synthetic FLAT "__stop_exit__"
  ▼
SIZER: target = floor(equity·alloc%·strength·regime / price)   [UNSIGNED, ABSOLUTE]
  │     (edge NOT used; no vol-target; regime only shrinks)
  ▼
TRANSLATOR: diff target vs NET book.quantity ONLY → one of 7 intents
  │     (blind to avg, unrealized, age, lot cost; no trim path)
  ▼
GATES: check_signal → halt-blackout → SSR → locate → [B4 / B5] → check_order
  ▼
EXECUTE: ENTRY/SCALE_UP | EXIT(full) | REVERSE(full MARKET exit + passive entry)
  ▼
FILL → _reconcile_fills → POSITION STORE (single avg, netted, no lots, no intent)
                          └─ StrategyPositionStore: per-alpha books, NETTED aggregate
  ▲
ASYNC overlays: hazard-spike / hard-exit-age (full MARKET); FORCE_FLATTEN (all-symbol)
```

---

## Part 2 — Gap analysis vs. institutional-retail grade

Each gap lists: **evidence** (what the code does), **impact** (why it
costs money or risk), **institutional reference** (what good looks
like), **severity / effort**.

### G-1 — Decision layer is economically blind (P0, L) — *root cause RC-A*

- **Evidence:** the translator routes on `target − current_quantity`
  only (`intent.py:105`); no exit/flip/scale decision sees avg price,
  unrealized PnL, holding age, or disturbance cost. The B5 guard
  (PR #100) was a point-patch bolted onto `_execute_reverse`, not a
  property of the decision layer.
- **Impact:** every reversal, exit, and scale decision is taken without
  knowing the economic state of the book. The −$243 APP reversal was
  one symptom; the same blindness silently mis-prices ordinary exits
  and scale-ups.
- **Institutional reference:** a position manager diffs a **desired
  portfolio state** (target weights/qty *with* cost-and-risk awareness)
  against the current book and emits the minimal, cost-aware set of
  child orders. Edge, cost, inventory, and holding-state are inputs to
  the decision, not afterthoughts.
- **Severity P0 / Effort L.** This is the structural fix; most other
  gaps are facets of it.

### G-2 — No trim / de-risk / partial-reduction path (P1, M)

- **Evidence:** the matrix has `SCALE_UP` but no `SCALE_DOWN` of an
  existing position. A weaker same-direction signal with a *lower*
  target yields `NO_ACTION` (`intent.py:152-160, 189-197`). Reduction
  exists only as full `EXIT` or full `REVERSE`.
- **Impact:** the system **never trims a winner, never takes partial
  profit, never de-risks on conviction decay.** Positions are sticky at
  the cap and only ever leave via a binary full close. This forgoes a
  large fraction of achievable PnL capture and concentrates exit impact.
- **Institutional reference:** continuous position targeting — as
  conviction/edge decays, the target shrinks and the book is *trimmed*
  toward it (partial sells), not held until a full exit.
- **Severity P1 / Effort M** (adds a `SCALE_DOWN`-toward-target intent +
  partial-reduce execution).

### G-3 — Exits are uniform "panic full-MARKET" (P1, M) — ✅ CLOSED (2026-06-08)

> **Closed (P4a + P4b).** Discretionary reductions (TRIMs) now work
> `PASSIVE` (post a near-BBO limit, save the spread) under
> `position_manager_urgency_exec`, and any passive reduction that
> terminates unfilled (the router's resting timeout → CANCELLED/EXPIRED)
> escalates its residual to a guaranteed MARKET order
> (`_escalate_unfilled_working_exits`) — so working the exit never risks
> a stranded position. Risk-driven exits, stops, reverse-exits, and the
> EOD flatten stay aggressive (Inv-11).

- **Evidence:** six of seven close-paths dump the entire position at
  market (table §1.8). Only the normal FLAT exit can be passive, and
  even it closes full size.
- **Impact:** no working-the-exit, no size-aware liquidation against
  displayed depth, no passive unwind for non-stop exits. For any
  non-trivial size this guarantees spread + impact cost on every exit —
  the exact cost the B4/B5 gates try to avoid on *entry* is paid
  unconditionally on *exit*.
- **Institutional reference:** exit execution is a first-class algo
  (TWAP/POV/passive-peg with a market fallback on urgency), sized to
  available depth; only genuine risk events (stop, hazard, flatten) go
  full-aggressive.
- **Severity P1 / Effort M.**

### G-4 — No lot / age / tax accounting (P1, M) — *root cause RC-B* — ◑ PARTIAL (2026-06-08)

> **Observability layer landed.** `LotLedger`
> (`portfolio/lot_ledger.py`) maintains a per-symbol **FIFO** open-lot
> book beside the average-cost position store, updated on every fill in
> `_reconcile_fills` and exposed via `orchestrator.lot_ledger`. It gives
> per-lot holding age (oldest = FIFO front), per-lot strategy/intent
> provenance, and an honest FIFO realized-PnL view distinct from the
> avg-cost realized PnL. **Pure observability** — it touches no
> position/journal/bus and is not in the config snapshot, so it is fully
> parity-neutral (no re-baseline). *Remaining:* consume per-lot age in
> the hazard hard-exit-age path, lot-aware TRIM (trim the worst/oldest
> lot), tax-lot/wash-sale matching, and surfacing in the report — each a
> behavioral change with its own baseline.

- **Evidence:** single blended `avg_entry_price`
  (`memory_position_store.py:78-80`); hard-exit-age uses one
  position-level `opened_at_ns`, reset on any cross-through-zero
  (`memory_position_store.py:73-74`).
- **Impact:** no FIFO/LIFO lots, no per-lot holding age, no wash-sale /
  tax-lot awareness, and exit-leg realized PnL is an artifact of the
  blend rather than of identifiable lots. Per-lot risk rules (e.g.
  "exit lots older than N", "trim the worst lot first") are impossible.
- **Institutional reference:** lot-level book (open lots with price +
  timestamp + originating intent), with configurable close
  matching.
- **Severity P1 / Effort M-L.**

### G-5 — Multi-alpha netting is implicit and unmanaged (P1, L)

- **Evidence:** intent translation runs against the **netted aggregate
  view** (`strategy_position_store.py:95-131`); the per-alpha books are
  collapsed before the decision.
- **Impact:** cross-alpha churn (one alpha exiting what another holds)
  is invisible to the decision layer and to cost accounting. Two alphas
  can pay round-trip cost fighting over the same net share with no
  arbitration. There is no portfolio-level manager reconciling intents
  across alphas before they hit the book.
- **Institutional reference:** a portfolio construction / netting layer
  that aggregates *desired* per-alpha targets into a single net target
  and nets the *trades*, so internal crossing is free and only the
  residual reaches the market.
- **Severity P1 / Effort L.**

### G-6 — No session / overnight position lifecycle (P1, S-M) — ✅ CLOSED (2026-06-08)

> **Closed.** `_check_session_flat` unwinds any open book (forced MARKET)
> and `_in_session_flatten_window` blocks new entries once the quote
> crosses `rth_close − session_flatten_seconds_before_close`, independent
> of alpha behaviour. Config: `session_flatten_enabled` (default on),
> `session_flatten_seconds_before_close`.

- **Evidence:** no EOD flatten; RTH close only flips buying power and
  gates entries (`orchestrator.py:843-872`). Max-holding-period is only
  the optional per-alpha `hard_exit_age_seconds`.
- **Impact:** an intraday book silently carries **overnight gap risk**
  unless an alpha happens to emit FLAT. For retail-institutional
  intraday strategies this is a structural hole.
- **Institutional reference:** explicit session policy — flat-by-close
  / managed-into-the-auction / approved-overnight list, enforced by the
  kernel independent of alpha behavior.
- **Severity P1 / Effort S-M.**

### G-7 — Single-factor sizing (P2, M)

- **Evidence:** capital × strength × regime, capped
  (`position_sizer.py:78-99`); edge unused.
- **Impact:** size ignores edge magnitude, realized volatility, and
  current inventory — so a 2-bps and a 40-bps signal of equal
  `strength` take the same size, and a volatile name is sized like a
  calm one.
- **Institutional reference:** vol-targeted / edge-weighted sizing with
  an inventory penalty; edge and cost enter the size, not just the
  gate.
- **Severity P2 / Effort M.**

### Gap summary

Status as of 2026-06-11 (G-1…G-7 overhaul complete):

| Gap | Title | Root | Sev | Effort | Status |
|-----|-------|------|-----|--------|--------|
| G-1 | Decision layer economically blind | RC-A | P0 | L | shipped (driven) |
| G-2 | No trim / partial-reduce path | RC-A | P1 | M | shipped (driven) |
| G-3 | Exits are panic full-MARKET | — | P1 | M | shipped |
| G-4 | No lot / age / tax accounting | RC-B | P1 | M-L | shipped (observ.) |
| G-5 | Multi-alpha netting unmanaged | RC-B | P1 | L | shipped dark; measured, off (netting A/B) |
| G-6 | No session / overnight lifecycle | — | P1 | S-M | shipped (driven) |
| G-7 | Single-factor sizing | — | P2 | M | shipped dark; measured, off (see g7 outcome note) |


---

## Part 3 — What is *not* broken (keep remediation surgical)

So the rework does not regress working safety machinery:

- **Inv-11 fail-safe exits are sound.** Stop/hazard/flatten always
  submit, bypass min-lot, and override alpha — keep this.
- **Determinism (Inv-5).** All order IDs are derived deterministically;
  replay parity is intact. Any new decision logic must preserve it.
- **The gate stack (B4/B5, SSR, locate, halt-blackout) is correct** —
  the issue is that gates are *entry-biased* and bolt-on, not that they
  misfire.
- **The escalation ladder (R0→R4→G8) and emergency flatten** are robust
  and should remain the backstop.
- **Per-alpha sub-books already exist** in `StrategyPositionStore` — the
  netting layer (G-5) builds *on top* of them, it does not need a new
  store.

---

## Part 4 — Recommended sequencing

The gaps are not independent; G-1 (RC-A) is load-bearing. Suggested
order:

1. **Lift the decision into a real position-management layer (G-1).**
   Introduce a target-vs-current *portfolio diff* that is cost/risk/
   inventory-aware, with the translator's 7-intent matrix becoming a
   thin projection of it. This subsumes the B5 point-patch.
2. **Add the trim/partial-reduce intent (G-2)** as the first capability
   the new layer unlocks — smallest economically-meaningful win.
3. **Exit execution algo (G-3)** and **session lifecycle (G-6)** in
   parallel — both are self-contained and high-value.
4. **Lot accounting (G-4)** under the position store, enabling per-lot
   age/risk rules and honest exit PnL.
5. **Cross-alpha netting layer (G-5)** once the single-book decision
   layer is solid.
6. **Sizing upgrade (G-7)** last — it tunes magnitude once the
   structure is right.

Each step is independently shippable behind config (default-off) to
preserve replay parity until explicitly enabled, matching the B5
pattern.
