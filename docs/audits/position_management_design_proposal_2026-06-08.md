# Design Proposal — Unified Position-Management Decision Layer (G-1)

**Date:** 2026-06-08
**Status:** Proposal / RFC. **No code is changed by this document.**
**Addresses:** G-1 (P0) from
`docs/audits/position_management_baseline_2026-06-08.md`, and creates the
seam that later subsumes G-2 (trim), G-3 (exit execution), and the B5
reversal point-patch.
**Scope of this doc:** the *decision layer* — how a desired position is
turned into child orders. It does **not** redesign sizing (G-7), lot
accounting (G-4), or cross-alpha netting (G-5); it leaves explicit seams
for each.
**Mode:** Contracts and pseudocode only. Everything below is *proposed*.

---

## 1. Why this exists

The baseline audit found the decision layer is **economically blind**
(RC-A): intent is derived from `target − current_quantity` and nothing
else. The B5 reversal-edge guard (PR #100) patched one symptom by
bolting a cost check onto `_execute_reverse`. Without a real
decision layer, every future fix is another bolt-on.

### 1.1 The finding that shapes this design: there are already *two* decision paths

The codebase already contains two parallel, half-overlapping decision
mechanisms — and **both are quantity-blind**:

| | SIGNAL path (legacy) | PORTFOLIO path (newer) |
|---|---|---|
| Producer | `Signal` (per-alpha) | `SizedPositionIntent` (composition) |
| Target model | unsigned scalar from `BudgetBasedSizer` (`position_sizer.py:78`) | `target_positions: {symbol: TargetPosition(target_usd, urgency)}` (`events.py:517`) |
| Diff → orders | `SignalPositionTranslator.translate` 7-intent matrix (`intent.py:73`) | `BasicRiskEngine.check_sized_intent` (`basic_risk.py:278`) |
| Diff logic | `target − qty` → one of 7 intents | `delta = target_shares − current.quantity` (`basic_risk.py:348`) |
| Execution style | per-intent (entry passive, exit/reverse MARKET) | **always full-size MARKET** (`basic_risk.py:370`) |
| Cost / PnL / age aware? | **no** | **no** |
| `urgency` honored? | n/a | **no** — carried then ignored |
| Where it lives | injected translator | **inside the risk engine** |

So the system has a *target-based* path already (`TargetPosition`), but
(a) it only nets quantities, (b) it ignores its own `urgency` hint and
always sends MARKET, and (c) it puts portfolio construction **inside the
risk gate**, which is the wrong home.

**The design is therefore a consolidation:** lift both paths onto one
`PositionManager` that consumes a *desired book*, diffs it against the
*current book* with cost/risk/inventory awareness, and emits a
*position plan* of child orders. The risk engine goes back to pure
gating. The 7-intent matrix and `check_sized_intent`'s diff both become
thin projections of the new planner.

---

## 2. Design principles (non-negotiables)

1. **Determinism (Inv-5).** Same inputs → same plan → same orders →
   same parity hash. The planner is a pure function of
   `(desired, current, market_context, config)`. No wall-clock, no
   iteration over unordered containers without a sort key.
2. **Default-off parity.** Ships behind config, **disabled by default**,
   exactly like B5 (`reversal_min_edge_cost_multiplier = 0` → no-op,
   bit-identical). When disabled, the legacy translator / risk-diff path
   runs unchanged and parity hashes are untouched.
3. **Inv-11 fail-safe preserved.** Exits, stops, hazard exits, and
   forced-flatten keep their override authority and gate bypasses. The
   planner can *never* block or shrink a risk-driven exit.
4. **Single responsibility.** The planner decides *what to trade*; the
   risk engine decides *whether it's allowed*; the execution layer
   decides *how to work it*. Portfolio-construction logic leaves the
   risk engine.
5. **Additive, reversible rollout.** Each phase is independently
   shippable and individually toggleable.

---

## 3. Target architecture

### 3.1 Where it sits

```
            ┌─────────── desired book ───────────┐
SIGNAL ─► sizer ─► DesiredPosition(symbol)        │
PORTFOLIO ─► composition ─► {symbol: DesiredPosition}
            └────────────────┬───────────────────┘
                             ▼
                   ┌──────────────────────┐
                   │   PositionManager     │   ← NEW (this proposal)
                   │  .plan(desired,       │
                   │        current_book,  │
                   │        market_ctx)    │
                   └──────────┬───────────┘
                              ▼  PositionPlan (child orders + rationale)
                   gates: check_signal/order ▸ SSR ▸ locate ▸ halt
                              ▼
                   execution (urgency-aware: passive / MARKET / algo)
                              ▼
                   fills ─► position store
```

The planner slots in **between the producers and the gates**, replacing
both `SignalPositionTranslator.translate` (called at
`orchestrator.py:2077`) and the diff inside `check_sized_intent`
(`basic_risk.py:336-353`). Risk gating runs **after** the plan, on each
proposed child order, unchanged.

### 3.2 Core contracts (proposed)

```python
# Generalises TargetPosition (events.py:517). A "desired" book entry.
@dataclass(frozen=True, kw_only=True)
class DesiredPosition:
    symbol: str
    target_qty: int          # signed: +long / -short / 0 flat (absolute target)
    edge_bps: float = 0.0    # NEW: edge on the *target* direction, for the cost gate
    urgency: float = 0.5     # 0..1: how aggressively to close the gap (drives execution)
    source: str = ""         # strategy_id / "__stop_exit__" / "session_flat" ...
    reason: str = ""         # provenance tag for the trace

# What the planner emits — child orders plus an auditable rationale.
@dataclass(frozen=True, kw_only=True)
class PlannedOrder:
    symbol: str
    side: Side
    quantity: int
    style: ExecStyle          # PASSIVE | MARKET | (future) ALGO
    leg: PlanLeg              # ENTRY | SCALE_UP | TRIM | EXIT | REVERSE_EXIT | REVERSE_ENTRY
    is_short: bool
    rationale: dict[str, float]   # edge_bps, cost_bps, required_bps, delta_qty, ...

@dataclass(frozen=True, kw_only=True)
class PositionPlan:
    orders: tuple[PlannedOrder, ...]
    suppressed: tuple[SuppressedLeg, ...]   # (leg, reason, constraints) for traces/alerts
```

```python
class PositionManager(Protocol):
    def plan(
        self,
        *,
        desired: DesiredPosition,
        current: Position,            # netted book today (lot-aware later, G-4)
        market: MarketContext,        # quote, cost_model, depth
        config: PositionManagerConfig,
    ) -> PositionPlan: ...
```

`MarketContext` carries the quote + cost model so the planner can price
the disturbance — i.e., the B4/B5 cost math becomes a *property of the
planner*, computed once, attached to every leg's `rationale`, not a
bolt-on per call site.

### 3.3 The decision logic (replaces the 7-intent matrix)

The planner computes `delta = target_qty − current.quantity` and then
**classifies the delta with economic awareness**:

```
delta == 0                          → NO_ACTION
sign(target) == sign(current):
    |target| > |current|            → SCALE_UP   (cost-gate the increment)
    |target| < |current|            → TRIM       (NEW: partial reduce; G-2)
target == 0                         → EXIT        (full close; urgency-aware style)
sign(target) != sign(current) != 0  → REVERSE     (EXIT existing + ENTRY new)
                                       └─ B5 combined-edge gate decides whether
                                          to flip or flatten-only — now intrinsic
current == 0, target != 0           → ENTRY       (cost-gate)
```

Key changes vs. today:

- **`TRIM` exists** (G-2). A shrinking same-direction target produces a
  partial reduce instead of `NO_ACTION`.
- **Every leg carries its cost rationale.** The B4 entry gate and B5
  reversal gate are evaluated inside `plan()` against
  `market.cost_model`, and the decision + numbers are attached to the
  plan — no separate `_signal_passes_edge_cost_gate` /
  `_reversal_passes_combined_edge_gate` call sites.
- **`urgency` chooses `ExecStyle`** (seam for G-3). Low urgency →
  PASSIVE/working; high urgency or risk-driven source → MARKET. Today
  `urgency` is ignored; the planner is where it finally bites.

### 3.4 Inv-11: risk exits bypass the planner's economic gates

A `DesiredPosition` whose `source` is a risk exit
(`__stop_exit__`, hazard, `emergency_flatten`, `session_flat`) is marked
**mandatory**: the planner emits the full reducing leg at MARKET with
the cost gate **forced open**. The planner can never suppress or shrink
it. This preserves the exact override hierarchy in baseline §1.8.

---

## 4. Unifying the two paths

- **SIGNAL path:** `BudgetBasedSizer` keeps producing an unsigned
  magnitude; the orchestrator wraps it as a *signed* `DesiredPosition`
  using the signal direction (the sign logic currently smeared across
  the translator matrix). The 7-intent enum becomes the planner's
  internal `PlanLeg` classification — same outcomes when the planner is
  disabled, richer (adds `TRIM`) when enabled.
- **PORTFOLIO path:** `check_sized_intent`'s diff
  (`basic_risk.py:336-375`) is **moved into the planner**. Each
  `TargetPosition` maps to a `DesiredPosition` (`target_usd / mark →
  target_qty`, plus `urgency`, plus per-symbol `edge_bps` from
  `disclosed_cost_total_bps_by_symbol`). The risk engine's
  `check_sized_intent` shrinks to: receive planned orders → run
  `check_order` on each → return verdicts. Pure gating again.

Net effect: one diff engine, two producers. Cross-alpha netting (G-5)
then becomes "aggregate `DesiredPosition`s before `plan()`", a clean
future insertion point — not addressed here, but the seam exists.

---

## 5. Determinism & parity strategy

This is the riskiest part (hot path, replay parity), so it's explicit.

1. **Config gate, default-off.** `PositionManagerConfig.enabled = False`
   by default. When disabled, the orchestrator calls the legacy
   translator / risk-diff exactly as today. **No parity hash moves.**
2. **Equivalence harness before flip.** Add a shadow mode
   (`enabled=False, shadow=True`) that runs the planner in parallel,
   logs any divergence between legacy intents and planner `PlanLeg`s to
   a trace sink, and asserts zero divergence on the existing replay
   fixtures *with `TRIM`/urgency features off*. Only when shadow shows
   bit-identical legs do we allow `enabled=True`.
3. **Parity baseline regeneration is intentional and staged.** Turning
   on `TRIM`, urgency-driven styles, or the intrinsic B5 changes trades
   by design — those runs get a **new** baseline, captured per-feature
   so each behavioral change is attributable (mirrors how the regime
   audit captured per-item parity).
4. **Pure-function discipline.** `plan()` takes no clock and sorts any
   multi-symbol iteration (matches `_emergency_flatten_all`'s
   lexicographic order and `check_sized_intent`'s `sorted(...)`).

---

## 6. Rollout phases (each independently shippable)

| Phase | Deliverable | Default | Parity impact |
|-------|-------------|---------|---------------|
| **P0** ✅ | `DesiredPosition` / `PositionPlan` / `PositionManager` Protocol + a `LegacyPositionManager` that reproduces today's matrix exactly | off | none |
| **P1** ✅ | Wire orchestrator SIGNAL path through the planner in **shadow mode**; equivalence-assert on fixtures | shadow | none |
| **P2a** ✅ | Extract B4 + B5 cost math into the planner module as the single source of truth; orchestrator delegates | off | none (pure refactor) |
| **P2b** | Planner *owns* the live gate decision + delete the orchestrator bolt-ons | off→on per-config | requires the drive-from-plan flip (see note) |
| **P3** | Add `TRIM` leg (G-2) behind `enable_trim` | off | new baseline when on |
| **P4** | `urgency → ExecStyle` + passive/working exits (G-3) behind `exit_exec_style` | off | new baseline when on |
| **P5** | Move PORTFOLIO diff out of `check_sized_intent` into the planner; risk engine becomes pure gating | off→on | shadow-verified |

P0–P2a are parity-neutral plumbing. P3+ are the economic wins, each
gated and individually baselined.

> **P2 split note.** P2 was split into **P2a** (done) and **P2b**
> (deferred). The B5 reversal gate runs on the *post-risk-scaling* entry
> quantity computed *inside* `_execute_reverse`, and the B4 taker
> assumption depends on execution mode (passive vs. min-cost-policy).
> The planner cannot reproduce those decisions faithfully at
> signal-translation time without the execution context threaded in —
> that threading **is** the drive-from-plan flip. So P2a consolidates the
> cost arithmetic into the planner module (single source of truth, both
> the live orchestrator and the future planner call it), while P2b — the
> planner owning the live decision and deleting the bolt-ons — lands with
> the flip. This keeps every step parity-neutral and shadow-verifiable
> rather than forcing a risky big-bang.

---

## 7. Test strategy

- **Unit:** `plan()` truth table — one test per `PlanLeg` transition,
  plus the Inv-11 mandatory-exit cases (stop/hazard/flatten always emit,
  cost gate forced open). Reuse the B5 test pattern (tight-spread quote,
  edge thresholds).
- **Equivalence:** `LegacyPositionManager` vs current translator on the
  full intent matrix — property test over (signal direction × current
  qty × target).
- **Parity:** existing replay fixtures must hash-match with the planner
  in shadow/disabled mode; per-feature baselines captured when each
  economic feature is enabled.
- **Determinism:** repeated `plan()` calls and a multi-symbol PORTFOLIO
  plan must be order-stable.

---

## 8. Scope boundaries & open questions

**Explicitly out of scope here** (separate proposals, seams left):
G-4 lot accounting (planner takes `Position`; swap for a lot-aware book
later), G-5 cross-alpha netting (aggregate `DesiredPosition`s pre-plan),
G-6 session lifecycle (emits a `session_flat` `DesiredPosition` — trivial
once the planner exists), G-7 sizing.

**Decisions locked (2026-06-08):**

1. **PORTFOLIO diff moves out of the risk engine — shadow-gated (P5).**
   The diff in `check_sized_intent` (`basic_risk.py:336-375`) relocates
   into the planner; the risk engine returns to pure gating. Verified in
   shadow mode before the flip so the working PORTFOLIO path can't drift.
2. **TRIM is cost-aware.** A same-direction target shrink only produces a
   TRIM leg when the trim notional clears its own round-trip cost (a
   TRIM analog of the B5 gate). Prevents churn on small target wobbles.
3. **The cost gate applies to *additive legs only*** (ENTRY / SCALE_UP /
   REVERSE_ENTRY). It never blocks or shrinks a reducing leg
   (TRIM / EXIT / REVERSE_EXIT) — reductions always execute, keeping
   Inv-11 unambiguous. Note: this makes the cost-aware-trim rule (2) a
   *classification* test (trim vs hold), not a suppression gate on an
   already-chosen reducing order.
4. **One shared `PositionManager` instance**, injected like the
   translator is today — deterministic, and makes future cross-alpha
   netting (G-5) a natural pre-plan aggregation step.

---

## 9. Summary

The decision layer already wants to be target-based — the PORTFOLIO path
proves it with `TargetPosition`. This proposal **consolidates the two
half-implementations into one cost/risk/urgency-aware `PositionManager`**,
turns the 7-intent matrix and the in-risk-engine diff into thin
projections of it, makes B4/B5 intrinsic, and opens clean seams for
trim, working exits, session policy, lots, and netting — all behind a
default-off config so parity holds until each economic change is
explicitly baselined.
