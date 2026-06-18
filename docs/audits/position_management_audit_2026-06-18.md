# Position-management, order-decision economics & PnL-ledger audit

- **Date:** 2026-06-18
- **Scope:** single-name SIGNAL capital path — sizing → signal→intent decision → position-manager / netting (G-1/G-5) → every close/reduce path → PnL ledger (position stores, lot ledger, trade journal).
- **Method:** read-only, evidence-based. Tests run: `tests/execution/test_intent.py`, `test_position_manager.py`, `test_portfolio_netter.py`, `tests/risk/test_position_sizer.py`, `test_edge_weighted_sizer.py`, `tests/portfolio/` → **548 passed**.
- **Legend:** `[BUG]` implementation defect · `[GAP]` documented G-1…G-7 baseline gap · `[DESIGN]` intentional.

---

## 1. Executive summary (safety/economics risks first)

1. **`[GAP/P0]` TRIM is driven by default and its locked APP baseline was never regenerated.** `position_manager_drive=True`, `position_manager_enable_trim=True`, `position_manager_trim_edge_gate_multiplier=1.0` are all default-ON (`platform_config.py:323-329`) and wired live through bootstrap (`bootstrap.py:555,725-726`). The only CI guard, `tests/acceptance/test_backtest_app_baseline.py`, is data-gated (skips on cache miss) and its header (lines 34-43) still declares the pinned constants are the **PRE-G-1 baseline** that "MUST be regenerated before this functional test passes again." So a default-on PnL/order-path change runs unverified in CI (Inv-5 re-baseline).
2. **`[BUG/P1]` The baseline file's provenance is internally contradictory.** The G-1 note (lines 34-43) says constants are pre-G-1 and stale, yet later "Re-baked" notes (R-1, 2P) and the live constant `_BASELINE_NET_PNL=71.56` (line 71) imply a regeneration happened. Either the note is stale or the constant is wrong — a reader cannot tell whether the locked number reflects the trim-on path.
3. **`[DESIGN]` Safety exits are unblockable — verified.** Stop (`__stop_exit__`) and session-flat (`__session_flat__`) are in `_FORCED_MARKET_EXIT_STRATEGIES` (`orchestrator.py:300-305`), bypass netting (`orchestrator.py:2434`), bypass min-lot + edge gate via the EXIT carve-out (`orchestrator.py:4505-4509,4518-4519`), and force MARKET (`orchestrator.py:4551,4558`). Hazard / emergency / degrade flatten submit even on a `REJECT`/`FORCE_FLATTEN` verdict (`orchestrator.py:5994-6025`, `3590-3611`, `6321-6336`). Reverse exit leg always submits; only the entry leg is gated (`orchestrator.py:4208`). No Inv-11 regression found.
4. **`[DESIGN/P2]` Default TRIM crosses at MARKET.** `position_manager_urgency_exec=False` (default) → a discretionary same-direction reduce executes MARKET (`position_manager.py:468`), paying full spread+impact on a non-safety reduce. The passive working-exit-with-fallback path exists but is opt-in. Mitigated by the churn guard and the P3b edge gate, but default trims pay avoidable spread.
5. **`[DESIGN]` Edge-weighted sizer can amplify but cannot breach `max_position` or fire without explicit config.** Factors clamp to `[floor, cap]`, combined to `[tilt_floor=0.10, tilt_cap=3.0]`, then re-capped at `max_position_per_symbol` and floored at 0 (`edge_weighted_sizer.py:247,282-285`). Amplification only when `sizer_tilt_drive=True` **and** a factor enabled — default off and shadow-only (`platform_config.py:360-372`, `bootstrap.py:550`). Inv-11 honored.
6. **`[DESIGN]` Base sizer is edge-blind and regime-only-shrinks.** `BudgetBasedSizer` target = `floor(equity·alloc%·strength·regime/price)`, capped (`position_sizer.py:90-109`); `edge_estimate_bps` unused in base size; `regime_factor` hard-clamped `min(1.0, EV)` (`position_sizer.py:137`); `strength` clamped to `[0,1]` (`position_sizer.py:100`). Edge only enters sizing via the opt-in G-7 tilt.
7. **`[GAP]` Legacy translator has no trim path (RC-A confirmed).** `SignalPositionTranslator` routes purely on `target − current_quantity`, blind to avg price / unrealized PnL / age (`intent.py:103-212`). A weaker same-direction signal at/over current yields `NO_ACTION` (`intent.py:150-158`). The trim capability lives only in `TargetPositionManager` (default-driven), not the translator.
8. **`[DESIGN]` Netting is provably inert when off.** `enable_portfolio_netting=False` (default) → the net branch is never taken (`orchestrator.py:2432-2451`) and the standing-target book is only maintained when a shadow sink is wired (`orchestrator.py:3982`). `PortfolioNetter.net` is a pure, order-independent sum over `live_targets` sorted by `strategy_id` (`portfolio_netter.py:125-191`).
9. **`[DESIGN]` B4/B5 gates use the fill-realistic cost model.** Both delegate to `round_trip_cost_bps` which prices the exit leg as a **taker** (`position_manager.py:507-528`), the conservative assumption matching aggressive exits. B4 default `signal_min_edge_cost_ratio=1.0` on `round_trip` basis (`platform_config.py:308-309`); B5 default multiplier `1.5` (`platform_config.py:314`).
10. **`[DESIGN]` Lot ledger is observability-only.** Written at fill reconcile (`orchestrator.py:5450`), exposed via a read-only property (`orchestrator.py:1022-1024`), never read on the decision path — same forensic-only contract as the promotion ledger; parity-neutral.
11. **`[DESIGN]` Marks are conservative and sign-correct.** Longs→bid, shorts→ask, fallback mid (`memory_position_store.py:138-145`); `unrealized = (mark − avg)·qty` is sign-correct for shorts (qty<0).
12. **`[GAP/P1]` Cross-symbol fill attribution is approximate for shared-symbol exits.** When no per-alpha attribution record exists (emergency flatten / stop / attribution failure) the fill is distributed proportionally across strategies (`orchestrator.py:5501-5513`); aggregate realized stays correct but per-alpha realized can mis-attribute.
13. **`[DESIGN]` Order-ID derivation is deterministic across all paths**, but the working-exit fallback uses a bespoke `sha256(f"{parent}:working_fallback")` (`orchestrator.py:5053`) instead of `derive_order_id`, a stylistic inconsistency (still collision-free, deterministic).
14. **`[GAP/P1]` No store-vs-lot reconciliation test and no dedicated trim/decision-path test module.** `tests/**/*trim*` → none; FIFO realized is tested in isolation (`test_lot_ledger.py`) but never reconciled against the avg-cost store on a shared fill stream; decision-path exit coverage is buried in `tests/kernel/test_orchestrator*.py`.
15. **`[DESIGN]` Divergence streams (`PlanDivergence`, `NetDivergence`, `SizeDivergence`) are observational** — emitted only when a sink is wired and never touch orders/bus/journal/parity (`orchestrator.py:2471-2480,3920-3926,3976-3983`).

---

## 2. Decision-path inventory

| Stage | Module / entry | Flag | Default | Reads |
|---|---|---|---|---|
| Sizer (base) | `BudgetBasedSizer.compute_target_quantity` (`position_sizer.py:80`) | — | always | equity, alloc%, `strength` (clamped [0,1]), regime EV (clamped ≤1.0); **not** edge |
| Sizer (tilt) | `EdgeWeightedSizer` (`edge_weighted_sizer.py:261`) | `sizer_tilt_drive` | **False** | edge, realized-vol provider, inventory provider; live only when driven |
| Decision (legacy) | `SignalPositionTranslator.translate` (`intent.py:94`) | `position_manager_drive=False` branch | inactive | `position.quantity` only (RC-A) |
| Decision (planner) | `TargetPositionManager.plan` → `order_intent_from_plan` (`orchestrator.py:2422-2464`) | `position_manager_drive` | **True** | qty, target, edge (for trim gate), quote, cost_model |
| └ TRIM leg | `TargetPositionManager.plan` (`position_manager.py:363-480`) | `position_manager_enable_trim` | **True** | same; emits partial reduce where legacy holds |
| └ TRIM edge gate | P3b (`position_manager.py:431-455`) | `position_manager_trim_edge_gate_multiplier` | **1.0** | `edge_bps` vs trim round-trip cost |
| Netting | `PortfolioNetter.net` (`orchestrator.py:2432-2451`) | `enable_portfolio_netting` | **False** | standing targets, budgets, portfolio cap |
| Entry gate (B4) | `_signal_passes_edge_cost_gate` (`orchestrator.py:3020`) | `signal_min_edge_cost_ratio` / `signal_edge_cost_basis` | **1.0 / round_trip** | edge×calibration, round-trip taker cost |
| Reversal gate (B5) | `_reversal_passes_combined_edge_gate` (`orchestrator.py:3128`) | `reversal_min_edge_cost_multiplier` | **1.5** | edge vs (exit+entry) round-trip cost |
| Execute | `_try_build_order_from_intent` / `_execute_reverse` (`orchestrator.py:4477,4087`) | — | always | intent, verdict.scaling_factor, exec-style override |
| Ledger (avg) | `MemoryPositionStore.update` (`memory_position_store.py:44`) | — | always | fill, fees, ts |
| Ledger (FIFO) | `LotLedger.apply_fill` (`orchestrator.py:5450`) | — | always (observability) | fill, strategy_id, intent |
| Journal | `TradeJournal.record` (`orchestrator.py:5558`) | — | when wired | order_id, strategy_id, correlation_id, intent, per-trade realized |

Default-on close-path behaviors: **session flatten** (`session_flatten_enabled=True`, `platform_config.py:340`) and **TRIM** (above).

---

## 3. Close-path table

| Mechanism | Trigger | strategy_id / reason | Order type | Gates bypassed | Always submits? |
|---|---|---|---|---|---|
| Stop / trailing | inline M4, unrealized vs threshold (`orchestrator.py:3643-3716`) | `__stop_exit__` | MARKET | min-lot, B4, netting | Yes (unless identical exit already pending) |
| Session flatten | quote ≥ `rth_close − buffer` (`orchestrator.py:3718-3771`) | `__session_flat__` | MARKET | min-lot, B4, netting | Yes |
| Hazard spike / hard-age | async bus `OrderRequest` from `HazardExitController` (`orchestrator.py:5945-6025`) | `HAZARD_SPIKE`/`HARD_EXIT_AGE` | per controller | audit-only `check_order`; submits even on REJECT; FORCE_FLATTEN not broadcast | Yes |
| Emergency flatten (FORCE_FLATTEN) | risk lockdown (`orchestrator.py:3522-3611`) | `emergency_flatten` | MARKET | iterates all symbols sorted; per-symbol failure isolated | Yes (best-effort) |
| Degrade flatten | pre-DEGRADED macro (`orchestrator.py:6287-6336`) | `degrade_flatten` | MARKET | best-effort; never raises | Yes (best-effort) |
| Reverse exit leg | flip intent (`orchestrator.py:4112-4172`) | alpha id | MARKET | min-lot; full `close_qty` (scaling no-op) | Yes |
| Reverse entry leg | flip intent (`orchestrator.py:4197-4275`) | alpha id | passive/market | — | **Gated** (B5 then B4); flatten-only if suppressed |
| FLAT exit | alpha FLAT signal (`intent.py:121-138` → EXIT) | alpha id | MARKET | min-lot, B4 | Yes |
| TRIM | same-direction shrink (`position_manager.py:469-480` → EXIT) | alpha id | MARKET (PASSIVE if `urgency_exec`) | min-lot, B4 (reducing leg) | Yes; churn-guard + P3b edge gate may hold |
| Working-exit fallback | passive reduce unfilled at timeout (`orchestrator.py:5005-5100`) | `__working_exit_fallback__` | MARKET | min-lot | Yes (residual only) |

**Override hierarchy per tick (M4):** `session_flat` set first, then `stop` overrides (`orchestrator.py:2390-2395`) — both FLAT, immaterial. FORCE_FLATTEN/emergency runs on the macro lockdown path, outside the per-tick signal walk. Hierarchy is deterministic: **FORCE_FLATTEN > stop = session-flat > hazard/age (async) > alpha**. Confirmed.

---

## 4. Decision-economics audit (RC-A, B4/B5)

**RC-A status.** Both decision implementations are economically thin. The legacy translator reads only `position.quantity` (`intent.py:103`); the default-driven `TargetPositionManager` diffs a signed target against current and adds exactly one economic refinement — the cost-aware TRIM (`position_manager.py:425-455`). Neither reads avg price, unrealized PnL, holding age, or disturbance cost on the **add/hold** side; B4/B5 supply the only entry-side economics, evaluated downstream in the orchestrator.

**Trim path (dimension A.3).** With defaults, a weaker same-direction signal whose target falls **below** current no longer yields `NO_ACTION`: `TargetPositionManager` emits a `TRIM` of `|current|−|target|` (`position_manager.py:388,469-480`) unless (a) it is below the churn threshold `ceil(0.10·|cur|)` (`position_manager.py:389-404`), or (b) the forward edge still clears `1.0×` the trim's round-trip cost (P3b, `position_manager.py:431-455`). Foregone-trim cost class is therefore bounded to sub-threshold wobble and still-profitable holds — economically defensible, but it is a **default-on order-path change** (see §1.1).

**B4 recomputation.** `entry_edge_clears_cost` returns `edge_basis ≥ min_ratio · rt_cost_bps` where `edge_basis = 2·edge` on `round_trip` basis (`position_manager.py:531-545`). With default `min_ratio=1.0`, basis `round_trip`: an entry passes iff `2·edge_bps ≥ rt_cost_bps`, i.e. **one-way edge ≥ half the round-trip cost** = round-trip breakeven. `rt_cost_bps` prices entry + **taker** exit (`position_manager.py:507-528`), matching the fills. The orchestrator additionally multiplies edge by a per-strategy realization-calibration factor (`orchestrator.py:3052-3053`) — trades on the calibrated edge, parity-preserving at factor 1.0. **Sound and fill-consistent.**

**B5 recomputation.** `reversal_edge_gate` returns `passes = edge_bps > (exit_cost + entry_cost)·multiplier` (`position_manager.py:548-562`). The exit leg is priced taker/non-short, the entry leg taker (`orchestrator.py:3163-3180`). **Can a reversal pass B5 while its exit leg alone destroys the disclosed edge?** No, by construction: B5 charges the **combined** exit+entry cost at `1.5×`, so the exit's crystallization cost is already inside the gate. Independently, the exit leg always submits (it only flattens existing exposure); if B5 fails, only the entry leg is suppressed and the book ends flat (`orchestrator.py:4208,4230`). **No economic blind spot on flips.**

---

## 5. Sizing audit

- **Base formula** (`position_sizer.py:90-109`): `allocated = equity·alloc%/100`; `conviction = allocated·clamp(strength,[0,1])`; `sized = conviction·clamp(EV,≤1.0)`; `shares = floor(sized/price)`; `capped = min(shares, max_position_per_symbol)`; `max(0, …)`. Edge unused. ✔ Inv-11 (regime only shrinks; `position_sizer.py:137`). ✔ Inv-12 (budget cap).
- **Tilt math** (`edge_weighted_sizer.py:118-154`): `edge=clamp(edge/ref,[0.25,2.0])`, `vol=clamp(target/realized,[0.25,2.0])` (no-op on missing/≤0 data), `inventory=clamp(1−|inv|/cap,[floor,1.0])` (never amplifies). Combined `clamp(product,[0.10,3.0])`, applied `floor(base·tilt)`, re-capped at `max_position`, floored 0 (`edge_weighted_sizer.py:247,282-285`).
- **Amplification bound (dimension C.2):** the tilt **can** exceed the untilted baseline (intended), but never exceeds `max_position_per_symbol` (hard re-cap) and never fires unless `sizer_tilt_drive=True` and a factor is explicitly enabled. FLAT/exit signals pass through at base (`edge_weighted_sizer.py:207`) — edge-weighting never shrinks a close. ✔ Inv-11.
- **Shadow discipline (C.3):** default `sizer_tilt_drive=False` → `bootstrap.py:550` selects the base sizer; the tilt is computed only for the `SizeDivergence` stream. Live sizing stays single-factor and byte-identical. The G-7 re-baseline note (`test_backtest_app_baseline.py:45-52`) correctly asserts the live path is unchanged (config-snapshot-only shift).

---

## 6. Netting audit (G-5)

- **Inertness when off (D.3):** `enable_portfolio_netting=False` (default). The decision branch that calls `net()` is guarded by `self._enable_portfolio_netting` (`orchestrator.py:2433`); the standing-target book is maintained only if a shadow sink is wired **or** netting drives (`orchestrator.py:3982`). With both off the default winner-take-all path is untouched → bit-identical.
- **Staleness alignment (D.1):** `standing_target_from_desired` sets `expiry_ns = signal_ts + k·horizon·1e9` (`portfolio_netter.py:67-69`); `_is_stale` uses `now_ns > expiry_ns` (strict), so the boundary instant stays fresh in lock-step with the orchestrator's pre-tick signal-buffer policy (`age ≤ horizon·1e9`) — the docstring at `portfolio_netter.py:36-40` documents the alignment. Horizon-0 PORTFOLIO targets get no `k·horizon` expiry and are registered one-tick-transient + evicted next tick (`orchestrator.py:3955-3961`), preventing stale persistence.
- **Safety-exit bypass (D.2):** netting is bypassed exactly for `signal.strategy_id not in _FORCED_MARKET_EXIT_STRATEGIES` (`orchestrator.py:2434`) — the bypass set is precisely `{__stop_exit__, __session_flat__}` and nothing more. ✔
- **Determinism (D.4):** `live_targets` returns targets **sorted by `strategy_id`** (`portfolio_netter.py:127-134`); `net()` is a pure sum + clamp with no iteration over unordered structures. Order-independence is covered by `test_net_is_order_independent` (`test_portfolio_netter.py:110`). ✔
- **Churn quantification (D.3, on):** when on, opposing per-alpha desires offset before summing (`portfolio_netter.py:169`), so one alpha's exit nets against another's entry internally; the `NetDivergence` stream records winner-vs-net disagreement (`portfolio_netter.py:85-103`) — sufficient to quantify the saving in shadow before flipping.

---

## 7. PnL-ledger audit (RC-B, Inv-13)

**Hand recomputation — open→add→reduce→cross-through-zero** (`memory_position_store.py:70-90`), one lot of fills BUY100@10, BUY100@12, SELL150@13, SELL100@9:

| Step | qty | avg | realized (avg-cost) |
|---|---|---|---|
| BUY 100@10 | 100 | 10 | 0 |
| BUY 100@12 | 200 | 11 (`(10·100+12·100)/200`) | 0 |
| SELL 150@13 | 50 | 11 (unchanged on reduce) | `(13−11)·150 = +300` |
| SELL 100@9 (crosses 0) | −50 | 9 (reset to fill on cross, `:83-84,89`) | `+300 + (9−11)·50 = +200` |

**LotLedger FIFO** for the same stream (`lot_ledger.py:52-115`): SELL150 consumes lot1(100@10)→`(13−10)·100=300`, lot2(50@12)→`(13−12)·50=50` ⇒ +350; SELL100 reduces remaining lot2(50@12)→`(9−12)·50=−150` then opens −50@9 ⇒ FIFO realized `350−150=+200`. **Total-to-flat agrees (+200)**; the intra-sequence divergence (350 vs 300 after the first reduce) is the documented, legitimate FIFO-vs-blended difference on partial reduces (`lot_ledger.py:15-17`). ✔ — but **no test reconciles the two on a shared stream** (§9).

- **Marks (E.2):** longs→bid, shorts→ask, fallback mid (`memory_position_store.py:138-145`). `unrealized = (mark − avg)·qty` — sign-correct: short qty=−100, avg=10, ask=11 → `(11−10)·(−100)=−100` (loss when price rises). Conservative (liquidation-side). ✔
- **Aggregate (E.3):** `StrategyPositionStore.get_aggregate` sums realized/unrealized/fees and computes `avg = signed_cost/net_qty` (`strategy_position_store.py:105-129`). Σ per-alpha realized = aggregate realized (pure sum). **Mis-attribution risk:** shared-symbol exits without an attribution record fall back to proportional distribution (`orchestrator.py:5501-5513`), so per-alpha realized can drift from the alpha that actually held the risk while the **aggregate stays exact** — G-5 churn is invisible to per-alpha attribution.
- **Journal provenance (E.4):** `TradeRecord` carries `order_id, strategy_id, correlation_id, trading_intent`, per-trade differential realized (`position.realized_pnl − prev_realized`), cost_bps, fees (`orchestrator.py:5558-5579`); `net_pnl = realized − fees` (`trade_journal.py:52-62`). Sufficient to reconstruct the ledger from fills (Inv-13). ✔
- **Lot ledger observability (E.5):** written at `orchestrator.py:5450`, exposed read-only (`orchestrator.py:1022-1024`), never read on the decision path. ✔ forensic-only.

---

## 8. Determinism & flag-parity matrix

| Feature | Flag | Default | OFF == pre-feature baseline? | Notes |
|---|---|---|---|---|
| Position-manager drive | `position_manager_drive` | **True** | n/a (on) | byte-faithful to translator while trim off (`order_intent_from_plan` truth table) |
| TRIM | `position_manager_enable_trim` | **True** | n/a (on) | **default-on order-path change; baseline not regenerated in CI (P0)** |
| P3b trim edge gate | `position_manager_trim_edge_gate_multiplier` | **1.0** | n/a (on) | suppresses trim while edge clears cost |
| Session flatten | `session_flatten_enabled` | **True** | n/a (on) | re-baseline noted but data-gated; multi-day RTH rebind handled (`orchestrator.py:3725-3738`) |
| Portfolio netting | `enable_portfolio_netting` | False | **Yes** — branch guarded, book inert | shadow-only when sink wired |
| Sizer tilt | `sizer_tilt_drive` + per-factor | False | **Yes** — base sizer selected, tilt shadow-only | `bootstrap.py:550` |
| Lot ledger | (always on) | — | **Yes** — write-only observability | never read on decision path |

- **Order-ID derivation (F.1):** `derive_order_id` for entry/reverse/emergency/degrade (`orchestrator.py:4115,3555,6308`); working-exit fallback uses bespoke `sha256(parent:working_fallback)` (`orchestrator.py:5053`). All pure functions of `(correlation_id, sequence, symbol, reason)` — deterministic, collision-free given unique sequence. Minor `[BUG-style/P2]` inconsistency: fallback should use `derive_order_id` for uniformity.
- **Iteration order (F.2):** emergency flatten iterates `sorted(positions)` (`orchestrator.py:3548`); netter sorts by strategy_id. No unordered iteration on order-emitting paths.
- **Divergence streams (F.3):** strictly observational; gated on sink presence; never perturb orders (`orchestrator.py:2471-2480,3920-3926`).

---

## 9. Test-gap matrix

| Invariant / property | Coverage | Where |
|---|---|---|
| Safety-exit unblockability (stop/session/hazard always submit) | **Partial** | embedded in `tests/kernel/test_orchestrator*.py`; no single "no exit ever blocked" property |
| Override hierarchy (FORCE_FLATTEN > stop = session > hazard > alpha) | **Partial** | kernel tests; not asserted as one table |
| Tilt ≤ baseline unless config (Inv-11) | **Covered** | `test_edge_weighted_sizer.py` |
| Netting inert when off (bit-identity) | **Partial** | `test_portfolio_netter.py` covers `net()`; orchestrator-level off-parity relies on determinism suite |
| Store-vs-lot reconciliation (total-to-flat) | **Missing** | FIFO tested alone (`test_lot_ledger.py`); never reconciled vs avg-cost store |
| Flag-off parity (drive/trim/netting/tilt) | **Partial / data-gated** | trim+drive on locked only by `test_backtest_app_baseline.py` which **skips on cache miss** |
| TRIM economics (churn guard, P3b edge gate) | **Covered (unit)** | `test_position_manager.py`; no kernel-driven trim parity test module |
| Cross-alpha attribution exactness | **Missing** | proportional fallback (`orchestrator.py:5507`) unasserted for mis-attribution |

**Decision-path tests buried in kernel modules:** stop / reverse / session-flatten / working-exit live in `tests/kernel/test_orchestrator*.py` rather than a dedicated execution-decision module. This hides the absence of a "no reducing leg is ever cost-gated or min-lot-filtered" property and a "default-on trim parity" check.

**Proposed minimal new tests (specs only):**
1. *Store-vs-lot reconciliation property:* for a random fill stream returning to flat, assert `MemoryPositionStore.realized_pnl == LotLedger.realized_pnl_fifo` (equal only at flat).
2. *No-exit-ever-blocked property:* for every `intent ∈ {EXIT, stop, session-flat, hazard, FORCE_FLATTEN}`, assert an order is always submitted regardless of `min_order_shares`, B4/B5 verdict, and `REJECT` risk action.
3. *Netting-off bit-identity:* replay with `enable_portfolio_netting=False` and assert order stream byte-identical to a no-netter build.
4. *Tilt-bounds property:* for random factors, assert `0 ≤ tilted ≤ max_position_per_symbol` and `tilted == base` when all factors off.
5. *Default-on trim parity:* a non-data-gated kernel test asserting trim order stream against a recorded fixture (de-couples the trim-on guarantee from the disk-cache APP baseline).

---

## 10. Prioritized backlog

| Tier | Item | Component | `file:line` | One-sentence fix | Impact |
|---|---|---|---|---|---|
| **P0** | Default-on TRIM path unverified in CI | acceptance baseline | `test_backtest_app_baseline.py:34-43,121` | Regenerate the APP baseline against the disk cache (or land a non-data-gated trim fixture test) so the default trade path is locked | Inv-5: protects the live order/PnL path from silent regression |
| **P1** | Contradictory baseline provenance | acceptance baseline | `test_backtest_app_baseline.py:34-71` | Reconcile the "PRE-G-1, must regenerate" note with the live `71.56` constant; state which path the number reflects | Inv-5/Inv-13: removes ambiguity in the locked record |
| **P1** | Cross-alpha attribution mis-attribution on shared-symbol exits | strategy store / fill reconcile | `orchestrator.py:5501-5513` | Persist an attribution record for synthetic-exit fills (or document the proportional fallback as forensic-approximate) | Inv-13: per-alpha realized PnL fidelity |
| **P1** | Store-vs-lot reconciliation untested | lot ledger | `lot_ledger.py:137`, `memory_position_store.py:81` | Add the total-to-flat reconciliation property test | Inv-13: guards both ledgers against silent drift |
| **P1** | Decision/exit tests buried in kernel | tests | `tests/kernel/test_orchestrator*.py` | Extract "no reducing leg gated" + "trim parity" into a dedicated module | Inv-11/Inv-5: surfaces hidden gaps |
| **P2** | Default TRIM crosses at MARKET | planner | `position_manager.py:468` | Consider defaulting discretionary trims to the passive working-exit path (`urgency_exec`) | Inv-12: saves spread on non-safety reduces |
| **P2** | Working-exit fallback bespoke order-id hashing | orchestrator | `orchestrator.py:5053` | Use `derive_order_id` for uniform, greppable IDs | Inv-5 hygiene (already deterministic) |
| **P2** | Base sizer edge-blind | sizer | `position_sizer.py:104` | Promote G-7 edge tilt from shadow once re-baselined | Sizing richness / EV capture |

---

## 10a. Remediation status (2026-06-18)

| Item | Status | Evidence |
|---|---|---|
| P0 — trim defaults unverified in CI | **Fixed** | `tests/bootstrap/test_position_manager_wiring.py` locks the `PlatformConfig` trim defaults + bootstrap→orchestrator wiring (data-free). *Refinement:* the kernel trim **behavior** was already CI-tested in `tests/kernel/test_orchestrator.py`, but those tests pass the flags explicitly; the unverified gap was the defaults+wiring, which is what the new test pins. The APP baseline constants were in fact already refreshed to the trim-on output in `d101f30`. |
| P1.1 — contradictory baseline provenance | **Fixed** | `test_backtest_app_baseline.py:34-52` rewritten: constants are the trim-on baseline (refreshed `d101f30`, $71.56), not pre-G-1; stale `$15.07` reference corrected. |
| P1.2 — cross-alpha attribution mis-attribution | **Documented** | `orchestrator.py` proportional-fallback comment now states aggregate stays exact but per-alpha realized is forensic-approximate; exact path is the `allocate_fill` branch. (No behavior change — fix is the honest contract note the audit asked for.) |
| P1.3 — store-vs-lot reconciliation untested | **Fixed** | `tests/portfolio/test_lot_ledger.py::TestStoreVsLotReconciliation` (deterministic + 200-case randomized). Surfaced that reconciliation holds to within avg-cost division rounding (sub-cent), not bit-exactly — documented in the test. |
| P1.4 — decision/exit tests buried | **Fixed** | `tests/execution/test_reducing_leg_invariants.py` concentrates the reducing-leg-never-gated contract (disjoint leg sets, reduce→EXIT projection, reduce never overshoots). |
| P2.2 — bespoke fallback order-id hashing | **Fixed** | `orchestrator.py` working-exit fallback now uses `derive_order_id(...)` — byte-identical (`derive_order_id(seed) == sha256(seed)[:16]`), parity-neutral. |
| P2.1 — default TRIM crosses at MARKET | **Fixed** | `position_manager_urgency_exec` default flipped **ON**: discretionary trims now work PASSIVE with a guaranteed MARKET fallback (the working-exit-fallback layer has since landed, so the safety net the original deferral waited on now exists). Pinned in `test_position_manager_wiring.py::test_trim_execution_style_defaults_to_passive`. |
| P2.3 — base sizer edge-blind | **Available opt-in** | G-7 **EDGE** tilt is fully wired but left **default OFF** (`sizer_tilt_drive` + `sizer_edge_weighting_enabled`): an operator promotes it per deployment rather than platform-wide, so edge-amplified sizing is a conscious, re-baselined choice. Inv-11 preserved (re-capped at `max_position`, floored 0, exits never shrunk — verified in the audit). Pinned in `test_position_manager_wiring.py` (`TestSizerTiltConfigDefaults` default-off + `test_opt_in_routes_through_the_edge_weighted_sizer`). |

> **Re-baseline (P2.1):** flipping `position_manager_urgency_exec` ON shifts
> the resolved config snapshot, so the data-free config-contract hash was
> recomputed (`b01ba703…`). The `APP/2026-03-26` backtest was re-run against
> the disk cache (`scripts/run_backtest.py`) on 2026-06-18: it emits no
> discretionary passive TRIM in this dataset, so Net P&L (`$71.56`) and fill
> count (6) are **unchanged** from the d101f30 trim-on baseline — only the
> config snapshot shifted. The data-gated functional test
> (`test_app_20260326_backtest_baseline_from_disk_cache`) now passes against
> the regenerated constants. P2.3 stays opt-in (default off), so it does not
> perturb this baseline.

## 11. Caveats

- Micro-state *ordering* and single-writer discipline are out of scope (see `audit_kernel.md`); this audit assumes the M4→M10 walk ordering is correct and only audits decision economics within it.
- Fill price / cost / latency simulation is out of scope (see `audit_execution_fills.md`); B4/B5 are audited against the cost-model interface, not its calibration.
- The APP functional baseline could not be executed here (no disk cache in this environment); the P0 finding rests on the in-file note and CI skip semantics, not a live re-run.

