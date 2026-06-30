# Position management, order-decision economics & PnL-ledger audit (Claude Code)

Use this prompt in a **Claude Code** session with full repo access. Scope: the feelies
**single-name SIGNAL capital path** — sizing, the signal→intent decision, the
position-manager / netting layer (G-1/G-5), every position close/reduce path, and the
PnL ledger (position stores, lot ledger, trade journal) — from `Signal` →
`TradingIntent` → `OrderRequest` → fill reconcile → realized/unrealized PnL.

---

## Mission

You are a senior quantitative execution researcher and position-management auditor.
Perform a **read-only, evidence-based audit** of the feelies position-management layer.

**Primary focus:** This is the *default capital path* for SIGNAL-only deployments — a
permanently supported deployment mode, not a transitional one. It is where a stateless
`Signal` becomes a real position and where that position is later reduced, reversed, or
flattened. The decision layer has historically been **economically blind** (RC-A: intent
derived from `target − current_quantity` only) over a **netted single-average book**
(RC-B). The G-1…G-7 remediation is actively landing here; every new mechanism (position manager, netting,
lot ledger, session flatten, working exits, edge-weighted sizing) must be audited with
the same rigor as the layers above it.

**Goal:** Identify where decision economics are sound vs. blind, where exit paths are
fail-safe vs. cost-blind, where the new G-1…G-7 machinery preserves replay parity vs.
risks it, and where the PnL ledger faithfully reconciles with fills — without breaking
platform invariants.

**Do not implement fixes in this pass.** Deliver a structured audit report with
file/line citations, severity, and prioritized recommendations.

---

## Agent context (mandatory)

| Step | Resource |
|------|----------|
| 1 | `.cursor/rules/platform-invariants.mdc` — **Inv-5, 11, 12, 13** |
| 2 | `.cursor/rules/karpathy-guidelines.mdc` |
| 3 | `.cursor/skills/README.md` |
| 4 | `.cursor/skills/risk-engine/SKILL.md` — sizing, fail-safe (**co-owner**) |
| 5 | `.cursor/skills/live-execution/SKILL.md` — order lifecycle, intent translation (**co-owner**) |
| 6 | `.cursor/skills/system-architect/SKILL.md` — micro-state ordering touchpoint |

Defer deep orchestrator ordering critique to `audit_kernel.md`; defer fill math to `audit_execution_fills.md`.


**Shipped vs Not shipped:** Treat skill sections marked **Not shipped** as design
targets — P0 only if code/tests claim they are live.

**Finding bar:** P0/P1 items must cite `Inv-N` + `path:line`. Read-only pass per
`.cursor/rules/karpathy-guidelines.mdc`.

---

## Platform context (read first)

**Docs and config** (after Agent context):

1. Read `src/feelies/execution/intent.py`, `position_manager.py`, and
   `portfolio_netter.py` (the G-1/G-5 decision contracts and legacy adapter).
2. Read `src/feelies/portfolio/lot_ledger.py`, `storage/trade_journal.py`, and the
   position-store modules (PnL ledger path).


**Architecture (contractual):**

```
Signal (selected at M4; _select_bus_signal arbitration; _check_stop_exit may override)
  → sizer: BudgetBasedSizer target (+ optional EdgeWeightedSizer tilt, G-7)
  → decision: SignalPositionTranslator 7-intent matrix (legacy)
              / PositionManager (G-1: DesiredPosition → PlannedOrder)
              / PortfolioNetter net target (G-5, enable_portfolio_netting)
  → gates: check_signal → halt-blackout → SSR → locate → B4 edge-cost → B5 reversal-edge
  → execute: ENTRY / SCALE_UP / EXIT / REVERSE / session-flatten (G-6) / working-exit (G-3)
  → fill reconcile → position stores (netted avg) + LotLedger (G-4) + trade journal
```

- **Override hierarchy (close paths):** FORCE_FLATTEN > stop-loss exit (inline M4
  override) > hazard / hard-age exits (async bus) > alpha signal. Safety exits always
  submit and bypass min-lot.
- **Default-off gating:** new decision behavior ships behind config flags
  (`enable_portfolio_netting` default False) to preserve replay parity; **exception:**
  `session_flatten_enabled` defaults **True** (G-6) — a default-on close-path behavior.

**Hard invariants (non-negotiable):**

- Inv-11: fail-safe — safety exits (stop, hazard, flatten) must never be blockable by
  economic gates; entries may be vetoed, exits may not.
- Inv-12: decision economics — entries/reversals must clear the B4/B5 edge-vs-cost
  gates; exits must not silently pay avoidable spread/impact.
- Inv-5: deterministic replay — order IDs, intent selection, netting, and lot matching
  are pure functions of the event log; default-off flags preserve bit-identical parity.
- Inv-13: every realized/unrealized PnL number traceable to fills via the ledger.

---

## Scope — files to audit

### Decision layer (signal → intent → planned order)

- `src/feelies/execution/intent.py` — `TradingIntent`, `SignalPositionTranslator`
  (the 7-intent matrix; reads only `position.quantity` — RC-A)
- `src/feelies/execution/position_manager.py` — G-1: `DesiredPosition`, `ExecStyle`,
  `PlannedOrder`, `LegacyPositionManager` (byte-for-byte shadow equivalence claimed)
- `src/feelies/execution/portfolio_netter.py` — G-5: `StandingTarget`,
  `DesiredTargetBook`, `PortfolioNetter`, `NetDivergence`
- `src/feelies/risk/position_sizer.py` — `BudgetBasedSizer`
  (`target = floor(equity·alloc%·strength·regime/price)`; edge unused)
- `src/feelies/risk/edge_weighted_sizer.py` — G-7: `SizerTiltConfig`,
  `EdgeWeightedSizer`, `edge_factor` / `vol_factor` / `inventory_factor`, `apply_tilt`,
  `SizeDivergence` shadow stream

### Orchestrator decision/exit economics (shared file — see ownership note)

- `src/feelies/kernel/orchestrator.py` — **decision economics only**; micro-state
  *ordering* is owned by `audit_kernel.md`. In scope here:
  `_select_bus_signal`, `_check_stop_exit` (fixed + trailing),
  `_signal_passes_edge_cost_gate` (B4), `_reversal_passes_combined_edge_gate` (B5),
  `_execute_reverse`, `_emergency_flatten_all`, `_force_flatten_symbol_on_degrade`,
  `_session_flatten_deadline_ns` / `_in_session_flatten_window` (G-6),
  `_escalate_unfilled_working_exits` / `_submit_working_exit_fallback` (G-3),
  `_record_net_shadow` / `_record_portfolio_net_shadow` (G-5),
  `_on_bus_hazard_order`, `_maybe_flip_buying_power_at_rth_close`
- `src/feelies/core/platform_config.py` — `session_flatten_enabled` (default True),
  `session_flatten_seconds_before_close`, `enable_portfolio_netting` (default False),
  sizer-tilt keys

### PnL ledger (book state + accounting)

- `src/feelies/portfolio/position_store.py`, `memory_position_store.py` — netted
  single-average book: open/add/reduce/cross-through-zero realize math, bid/ask marks
- `src/feelies/portfolio/strategy_position_store.py` — per-alpha sub-books + netted
  aggregate view (RC-B)
- `src/feelies/portfolio/lot_ledger.py` — G-4: `Lot`, `LotLedger` (FIFO open lots,
  observability-grade)
- `src/feelies/storage/trade_journal.py`, `memory_trade_journal.py` — fill journal

### Operator surfaces (measurement streams)

- `configs/backtest_multialpha.yaml`, `backtest_multialpha_netting.yaml`,
  `backtest_sizing_tilt.yaml` (+ ablation variants: `backtest_sizing_tilt_edgeonly.yaml`,
  `backtest_sizing_tilt_invonly.yaml`, `backtest_multialpha_sizing_tilt.yaml`,
  `backtest_app_edge_drive.yaml`, `backtest_multialpha_edge_drive.yaml`)

### Tests (spec + gap analysis)

- `tests/execution/test_intent.py`, `test_position_manager.py`, `test_portfolio_netter.py`
- `tests/risk/test_position_sizer.py`, `test_edge_weighted_sizer.py`
- `tests/portfolio/test_lot_ledger.py`, `test_memory_position_store.py`,
  `test_strategy_position_store.py`, `test_position_store_bid_ask_marks.py`
- `tests/storage/test_trade_journal.py` (fill-journal contract)
- Kernel-embedded coverage (note the placement): stop-exit / reverse / session-flatten /
  working-exit behavior is tested inside `tests/kernel/test_orchestrator.py` and
  `test_orchestrator_bus_signal.py`; B4 in `tests/kernel/test_orchestrator_cost_gate.py`

**Out of scope:** micro-state ordering / single-writer discipline (see
`audit_kernel.md`), fill price/cost/latency simulation (see `audit_execution_fills.md`),
risk limits / escalation SM / buying power / hazard *detection* (see
`audit_risk_engine.md`, `audit_regime.md` — `src/feelies/risk/hazard_exit.py` stays
with risk_engine; only the orchestrator's *routing* of hazard orders is in scope here),
PORTFOLIO-layer sized-intent construction (see `audit_composition.md`).

---

## Audit dimensions (answer each with evidence)

### A. Decision-layer economic awareness (RC-A) — highest priority

1. Confirm what the active decision path reads: does `SignalPositionTranslator` still
   route on `target − current_quantity` only, blind to avg price, unrealized PnL,
   holding age, and disturbance cost? Which deployments run the legacy translator vs.
   `PositionManager` vs. the netter?
2. G-1 equivalence: is `LegacyPositionManager` provably byte-identical to the
   translator's truth table (the parity-neutrality claim)? What diverges once a
   non-legacy manager is enabled, and is that behind a default-off flag?
3. Trim path: does a weaker same-direction signal with a lower target still yield
   `NO_ACTION` (G-2: no partial reduce), or has a scale-down intent landed? If absent,
   quantify the foregone-trim cost class.
4. B4/B5 gates: recompute the edge-vs-cost arithmetic. Entry gate (B4) and reversal
   gate (B5) — do they use the same cost model the fills will charge (Inv-12)? Can a
   reversal pass B5 while its exit leg alone destroys the disclosed edge?

### B. Exit-path safety vs. cost (Inv-11 / Inv-12)

1. Enumerate every close/reduce path (stop, hazard, hard-age, FORCE_FLATTEN, reverse
   exit leg, FLAT exit, session flatten, working-exit fallback). For each: trigger,
   order type, size, which gates it bypasses. Verify the override hierarchy
   (FORCE_FLATTEN > stop > hazard/age > alpha) is deterministic per tick.
2. **Safety exits must never be blockable:** prove stop / hazard / flatten orders
   always submit (audit-only risk checks, min-lot bypass). Any regression introduced
   by G-3/G-5/G-6 wiring?
3. **Cost on exits:** which exits are full-size MARKET (paying unconditional
   spread+impact) vs. worked passively with the G-3 fallback? Is the
   `_escalate_unfilled_working_exits` escalation deadline causally sound and
   deterministic?
4. G-6 session flatten — **default ON** (`platform_config.py`): exact window semantics
   (`rth_close − session_flatten_seconds_before_close`), interaction with the
   buying-power phase flip, behavior across multi-day replays (cf. the per-day RTH
   rebind fix), and whether entries are blocked while exits proceed (fail-safe
   direction). Does default-on change pre-G-6 backtest baselines, and is that
   re-baseline documented?

### C. Sizing economics (G-7)

1. `BudgetBasedSizer`: confirm target formula; confirm `regime_factor` is clamped
   `min(1.0, EV)` (can only shrink — Inv-11); confirm `edge_estimate_bps` is unused in
   the base size.
2. `EdgeWeightedSizer`: factor math (`edge_factor`, `vol_factor`, `inventory_factor`),
   clamps, and `apply_tilt` bounds. Can any tilt **amplify** size beyond
   `max_position` or beyond the untilted baseline without explicit config (Inv-11)?
3. Shadow discipline: is the G-7 tilt currently shadow-only (`SizeDivergence` stream)
   or live-sizing? If live, what flag gates it and what re-baseline evidence exists?

### D. Netting layer (G-5)

1. `PortfolioNetter`: standing-target expiry vs. the signal-buffer staleness policy —
   aligned (the two fixes `2281f56` / `e396da0` claim so)? Horizon-0 transience handled
   (no stale PORTFOLIO targets persisting in the net shadow)?
2. Forced-market-exit signals bypass netting (`0afdc45`) — verify the bypass is
   exactly the safety-exit set and nothing more.
3. With `enable_portfolio_netting=False` (default): is the netter provably inert
   (shadow-only, bit-identical replay)? With True: is cross-alpha churn actually
   netted (one alpha's exit crossing another's entry internally), and is the
   `NetDivergence` stream sufficient to quantify the saving?
4. Determinism: netting decisions a pure function of the event log? Any iteration
   over unordered structures across alphas/symbols?

### E. PnL-ledger fidelity (RC-B, Inv-13)

1. Recompute the store math by hand for one open→add→reduce→cross-through-zero
   sequence: blended `avg_entry_price`, realized on reduce, avg reset on cross.
   Does `LotLedger` (FIFO) agree with the blended store on total realized PnL for the
   same fill stream? Where do they legitimately diverge (per-lot vs. blended)?
2. Marks: longs→bid, shorts→ask, fallback mid — conservative? Unrealized =
   `(mark − avg)·qty` sign-correct for shorts?
3. `StrategyPositionStore` netted aggregate: does Σ per-alpha realized equal aggregate
   realized? Can the netted view mis-attribute PnL across alphas (G-5 churn invisible
   to attribution)?
4. Trade journal: is every fill journaled with enough provenance (order reason,
   alpha_id, correlation_id) for forensics to reconstruct the ledger (Inv-13)?
5. Lot ledger is "observability-grade" — confirm nothing on the decision path reads it
   (replay-safety, same forensic-only contract as the promotion ledger).

### F. Determinism & parity (Inv-5)

1. Order-ID derivation across all decision paths (entry, reverse legs, stop, flatten,
   working-exit fallback, netted orders): deterministic and collision-free?
2. Flag matrix: for each of `enable_portfolio_netting`, sizer tilt, lot ledger,
   session flatten — state default, and whether the OFF state is bit-identical to the
   pre-feature baseline. Flag any default-on feature lacking a re-baseline record.
3. Do the divergence JSONL emit streams perturb the decision path, or are they
   strictly observational?

### G. Test & validation gaps + prioritized recommendations

1. Map invariants (safety-exit unblockability, override hierarchy, tilt ≤ baseline,
   netting inertness when off, store/lot reconciliation, flag-off parity) to tests —
   **covered / partial / missing**. Note that stop/flatten/reverse coverage lives
   embedded in `tests/kernel/test_orchestrator*.py` rather than a dedicated module —
   assess whether that placement hides gaps.
2. Propose **minimal** new tests (store-vs-lot reconciliation property, "no exit ever
   blocked" property, netting-off bit-identity, tilt-bounds property) — specs only.
3. Tiers:
   - **P0:** a safety exit that can be vetoed or starved, a default-on behavior change
     without re-baseline, ledger math that doesn't reconcile with fills,
     nondeterministic order IDs or netting, any tilt/netting path that increases
     exposure autonomously.
   - **P1:** missing trim path economics, cost-blind exit selection, store-vs-lot
     divergence unexplained, stale standing targets, decision-path tests buried in
     kernel modules.
   - **P2:** sizing-model richness, exit-algo upgrades, attribution ergonomics.

Each item: component, `file:line`, one-sentence fix, expected impact on realized PnL
or safety.

---

## Working method

1. Build a **decision-path inventory** (sizer → translator/manager/netter → gates →
   execute → ledger) with the flag state of each stage (default on/off).
2. Audit the close-path table first (every exit mechanism, its gates, its bypasses) —
   safety beats economics.
3. Recompute one position lifecycle by hand through the store **and** the lot ledger;
   reconcile.
4. Audit G-5/G-6/G-7 flag-off parity claims against the determinism tests.
5. Cross-check findings against the owning skill's **Not shipped** sections before filing P0 on absent features.
6. Run **read-only** checks only:
   - `uv run pytest tests/execution/test_intent.py tests/execution/test_position_manager.py tests/execution/test_portfolio_netter.py -q`
   - `uv run pytest tests/risk/test_position_sizer.py tests/risk/test_edge_weighted_sizer.py -q`
   - `uv run pytest tests/portfolio/ -q`
   Do not modify production code.

---

## Output format (strict)

Write the audit report to `docs/audits/position_management_audit_YYYY-MM-DD.md` with
these sections:

1. **Executive summary** (≤15 bullets): top safety/economics risks first.
2. **Decision-path inventory** (markdown table: stage, module, flag, default, reads).
3. **Close-path table** (mechanism × trigger × order type × gates bypassed × hierarchy).
4. **Decision-economics audit** (RC-A status, B4/B5 recomputation — deep dive).
5. **Sizing audit** (base formula, tilt bounds, shadow discipline).
6. **Netting audit** (G-5 inertness, staleness alignment, churn quantification).
7. **PnL-ledger audit** (store math, lot reconciliation, aggregate attribution).
8. **Determinism & flag-parity matrix**.
9. **Test gap matrix** (note kernel-embedded decision tests).
10. **Prioritized backlog** (P0/P1/P2, effort S/M/L).

Use code citations as `path:line` for every non-trivial claim.
Distinguish **implementation bug** vs **documented gap (G-1…G-7 baseline)** vs
**intentional design**.

---

## Quality bar

- Prefer **falsifiable** statements ("the translator yields NO_ACTION when a LONG
  signal's target falls below current quantity, so conviction decay never trims —
  `intent.py:152-160`") over adjectives.
- Treat any blockable safety exit or autonomous exposure increase as a P0 (Inv-11).
- Treat any default-on behavior change without a re-baseline record as a P0 (Inv-5).
- A ledger that doesn't reconcile with its fills lies to forensics and promotion —
  P0 (Inv-13).
- Respect deterministic replay: no fixes that introduce randomness or wall-clock.

---

## Optional follow-ups (paste after the audit)

- *"After the report, draft P0 fixes only for any blockable safety exit and any
  flag-off parity break as a follow-up PR plan."*
- *"Reconcile LotLedger FIFO realized PnL against the blended store on the APP
  2026-03-26 backtest fill stream — methodology + result only, no code changes."*
- *"Propose a 'no exit ever blocked' property test across all seven close paths —
  spec only, no code."*
