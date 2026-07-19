# Position Management Audit - 2026-07-02

## Executive summary

- Assumption: read-only audit of the default SIGNAL capital path (sizing → decision → gates → execute → ledger). No production code, configs, or ledgers were changed; this report is the only file written.
- **P0** (Inv-11, Inv-9; `src/feelies/risk/basic_risk.py:211-220`): the shared risk-engine exposure/drawdown gate can silently drop a stop-loss, session-flatten, alpha-FLAT, TRIM, or reversal-exit order. `BasicRiskEngine.check_signal`/`check_order` exempt the position-limit, PDT, RTH, and buying-power checks for reducing orders via `_opens_or_increases`/`signal_reduces` (`src/feelies/risk/basic_risk.py:194-200`, `503-504`, `531-532`, `578-579`), but `_check_exposure_and_drawdown` runs unconditionally for every signal/order (`src/feelies/risk/basic_risk.py:211-220`, `313-323`) and can return `REJECT` for gross exposure at/above cap (`src/feelies/risk/basic_risk.py:741-749`) or `FORCE_FLATTEN` for non-positive equity (`src/feelies/risk/basic_risk.py:729-737`) or a drawdown breach (`src/feelies/risk/basic_risk.py:755-763`) — for an order that only ever *reduces* exposure.
- **P0** (Inv-11; `src/feelies/kernel/orchestrator.py:2481-2482`): the orchestrator elevates `_check_stop_exit`/`_check_session_flat`'s synthetic FLAT signal into `signal` and runs it through the ordinary M4-M6 walk (`src/feelies/kernel/orchestrator.py:2477-2482`), which calls `check_signal` unconditionally (`src/feelies/kernel/orchestrator.py:2607`) and drops the tick without building any order on `REJECT` (`src/feelies/kernel/orchestrator.py:2652-2666`) or `FORCE_FLATTEN` (`src/feelies/kernel/orchestrator.py:2615-2649`) — the identical pattern recurs for the M6 `check_order` gate (`src/feelies/kernel/orchestrator.py:2809-2859`) and for the exit leg of a reversal (`src/feelies/kernel/orchestrator.py:4335-4363`).
- **P0** (Inv-9; `src/feelies/kernel/macro.py:74-79`): in `BACKTEST_MODE`, the `FORCE_FLATTEN` branch above does not even trigger a compensating flatten, because `_escalate_risk`/`_emergency_flatten_all` are reachable only when `can_transition(MacroState.RISK_LOCKDOWN)` is true, which `src/feelies/kernel/macro.py:74-79` makes structurally impossible from `BACKTEST_MODE` — so the position that triggered the stop simply stays open with no order and no flatten, while the identical condition in `PAPER_TRADING_MODE`/`LIVE_TRADING_MODE` correctly cascades into `_emergency_flatten_all` (`src/feelies/kernel/orchestrator.py:3599-3670`). This is a live backtest/live parity break on top of the Inv-11 issue. Empirically reproduced against `BasicRiskEngine.check_signal` in a read-only scratch script (see §D) — a stop-loss on a position whose own notional exceeds `max_gross_exposure_pct` returns `REJECT`; a drawdown-breached book (loss on an unrelated symbol) returns `FORCE_FLATTEN`.
- Contrast, folded into the same finding rather than a separate one: the hazard-exit bus handler already implements the correct carve-out — a `REJECT` on a reducing order is logged but the order still submits (`src/feelies/kernel/orchestrator.py:6294`, `6304`, `6310`, `6336-6357`), tested at `tests/kernel/test_orchestrator_hazard_exit_routing.py:309`. No equivalent carve-out or test exists for stop-loss, session-flatten, alpha-FLAT, TRIM, or the reversal exit leg, even though stop-loss ranks *above* hazard exits in the platform's own override hierarchy.
- **P1** (Inv-12, Inv-13; `src/feelies/kernel/orchestrator.py:4798-4802`): the STOP_EXIT panic-fill reason stamp — fixed by the 2026-06-20 audit's P1 remediation in commit `7704c86` — was silently dropped by a later merge-conflict cleanup (commit `4a90cd8`, 2026-06-24): `_try_build_order_from_intent`'s `OrderRequest(...)` call still carries the explanatory comment but no `reason=` kwarg at all (`src/feelies/kernel/orchestrator.py:4798-4802`). Confirmed currently failing: `uv run pytest tests/kernel/test_orchestrator.py -q` → 5 failed, 127 passed, all in `TestForcedExitReasonClassification`/`TestForcedExitPanicReason`/`TestTradeJournalProvenance` (`tests/kernel/test_orchestrator.py`). Stop-loss fills are silently underpriced in backtests again and journal provenance is empty again — the exact defect the 06-20 audit already fixed once. `CLAUDE.md`/`AGENTS.md`'s "no known failures" note predates this feature and is now stale for this one file.
- RC-A is still present by design, not new: `SignalPositionTranslator.translate` reads only `signal.direction` and `position.quantity` (`src/feelies/execution/intent.py:94-119`) and both `_handle_long`/`_handle_short` clamp same-direction over-target books to `NO_ACTION` (`src/feelies/execution/intent.py:150-158`, `187-195`) — the documented, still-supported legacy fallback.
- G-1's `LegacyPositionManager` remains provably byte-faithful to the translator (`src/feelies/execution/position_manager.py:207-295`, no TRIM, full-size MARKET exits/reverses); the default driver is `TargetPositionManager` with `enable_trim=True` and `trim_edge_gate_multiplier=1.0`, both default-on (`src/feelies/core/platform_config.py:323-329`). Every default-on flip in this file cites its own audit number and a re-baseline note in `tests/acceptance/test_backtest_app_baseline.py:34-88` — good hygiene, no silent default-on change found.
- B4 (`src/feelies/kernel/orchestrator.py:3146-3199`) applies a realization-calibration factor to the disclosed edge (`src/feelies/kernel/orchestrator.py:3178-3179`); B5 (`src/feelies/kernel/orchestrator.py:3276-3335`) still compares raw `edge_estimate_bps` (`src/feelies/kernel/orchestrator.py:3279`, `4413`) — the same inconsistency the 06-20 audit flagged, unchanged, and still only P2 because the exit leg submits regardless of the B4/B5 outcome.
- `DesiredPosition.mandatory` (`src/feelies/execution/position_manager.py:90-102`) is dead: documented as forcing the cost gate open for a risk-driven desired, but never set `True` anywhere and never read by `plan()` or any gate in the repository (grep finds only the definition site).
- Sizing (G-7) is sound: `BudgetBasedSizer` is edge-blind and clamps `regime_factor` to `min(1.0, ev)` (`src/feelies/risk/position_sizer.py:100`, `137`); `EdgeWeightedSizer` deliberately can amplify but every factor is independently clamped and the combined tilt is always re-capped at `max_position_per_symbol` (`src/feelies/risk/edge_weighted_sizer.py:283`, `286-289`) — never autonomous beyond the alpha's declared envelope. `sizer_tilt_drive` stays default OFF (`src/feelies/core/platform_config.py:374`).
- Netting (G-5) is provably inert when `enable_portfolio_netting=False` (default, `src/feelies/core/platform_config.py:354`): `_record_net_shadow` short-circuits without a sink (`src/feelies/kernel/orchestrator.py:4177-4182`), `PortfolioNetter.net` is order-independent via strategy-id-sorted `live_targets` (`src/feelies/execution/portfolio_netter.py:125-134`), and forced-exit strategies bypass the net target unconditionally (`src/feelies/kernel/orchestrator.py:2527-2530`).
- PnL ledger reconciles: a fresh hand-worked open→add→partial-reduce→partial-reduce sequence (§G) gives avg-cost realized = FIFO realized = $1,150 at flat, while the two legitimately diverge by $80 at the intermediate partial-reduce point, matching the documented "differ mid-stream, agree at flat" contract (`src/feelies/portfolio/lot_ledger.py:14-17`; tested at `tests/portfolio/test_lot_ledger.py:111`, `141`).
- Verification on this checkout: the three prompt-specified suites are unchanged from 06-20 (385 / 116 / 50 passed); `tests/execution/test_reducing_leg_invariants.py` + `tests/kernel/test_orchestrator_hazard_exit_routing.py` + `tests/kernel/test_orchestrator_cost_gate.py` all pass (25/25); the wider `tests/kernel/test_orchestrator.py` has the 5 failures above.

## Decision-path inventory

| Stage | Module | Flag / default | Active default | Reads |
|---|---|---:|---|---|
| Signal arbitration | `src/feelies/kernel/orchestrator.py` | N/A | one bus-arbitrated signal; session-flatten then stop-loss override inline | `_select_bus_signal` picks the arbitrated winner (`src/feelies/kernel/orchestrator.py:6143-6218`); `_check_session_flat` then `_check_stop_exit` results override `signal` in that order, so stop wins ties (`src/feelies/kernel/orchestrator.py:2477-2482`) |
| Base size | `src/feelies/risk/position_sizer.py` | always wired | `BudgetBasedSizer` live unless G-7 drive enabled | `account_equity`, alpha allocation, `signal.strength`, mid price, regime posterior EV clamped `min(1.0, ev)`; `edge_estimate_bps` unused (`src/feelies/risk/position_sizer.py:90-109`, `137`) |
| G-7 tilted size | `src/feelies/risk/edge_weighted_sizer.py` | `sizer_tilt_drive=False` | shadow-only by default | edge / realized-vol / inventory factors, all independently gated off by default (`src/feelies/core/platform_config.py:374-383`, `src/feelies/risk/edge_weighted_sizer.py:53`, `59`, `65`) |
| Legacy translator | `src/feelies/execution/intent.py` | used only when PM drive off | supported fallback path | `signal.direction` + `position.quantity` only (`src/feelies/execution/intent.py:94-119`) — RC-A |
| G-1 position manager | `src/feelies/execution/position_manager.py` | `position_manager_drive=True`, `enable_trim=True`, `trim_edge_gate_multiplier=1.0` | active default | signed desired target, current qty, edge/cost context for TRIM (`src/feelies/core/platform_config.py:323-329`, `src/feelies/execution/position_manager.py:374-495`) |
| G-5 portfolio netter | `src/feelies/execution/portfolio_netter.py` | `enable_portfolio_netting=False` | inert/shadow unless enabled | per-alpha standing targets, sorted by `strategy_id` (`src/feelies/core/platform_config.py:354`, `src/feelies/execution/portfolio_netter.py:125-134`) |
| Entry edge gate B4 | `src/feelies/kernel/orchestrator.py` | `signal_min_edge_cost_ratio=1.0` | live | quote BBO/depth, cost model, calibrated signal edge (`src/feelies/kernel/orchestrator.py:3146-3199`, calibration at `3178-3179`) |
| Reversal edge gate B5 | `src/feelies/kernel/orchestrator.py` | `reversal_min_edge_cost_multiplier=1.5` | live | quote BBO/depth, raw signal edge, exit+entry cost (`src/feelies/kernel/orchestrator.py:3276-3335`) |
| Risk gate (Gate 1 / Gate 2) | `src/feelies/risk/basic_risk.py` | always wired | live, not exit-aware for exposure/drawdown | `check_signal`/`check_order` exempt position-limit/PDT/RTH/buying-power for reducing orders but run `_check_exposure_and_drawdown` unconditionally (`src/feelies/risk/basic_risk.py:194-220`, `313-323`) — see P0 (Inv-11) in §D |
| Execution | `src/feelies/kernel/orchestrator.py` | execution-mode dependent | exits force MARKET unless urgency-exec passive; min-lot/B4 bypass for `TradingIntent.EXIT` | `_try_build_order_from_intent`'s `is_exit_or_stop` branch (`src/feelies/kernel/orchestrator.py:4704-4708`); STOP_EXIT `reason` stamp is currently dropped (`src/feelies/kernel/orchestrator.py:4798-4802`) — see P1 (Inv-12, Inv-13) in §D |
| Ledger | `src/feelies/portfolio/`, `src/feelies/storage/` | always on | avg-cost is parity-bearing, lot ledger forensic-only | fills only; no decision path reads the lot ledger (`src/feelies/portfolio/lot_ledger.py:14-17`) |

## Close-path table

| Mechanism | Trigger | Order type / size | Gates bypassed | Hierarchy / determinism | Finding |
|---|---|---|---|---|---|
| FORCE_FLATTEN emergency | risk escalation to `FORCED_FLATTEN` | MARKET, full non-zero position, sorted symbols | bypasses `check_signal`/`check_order` entirely — submits directly (`src/feelies/kernel/orchestrator.py:3696-3741`) | lexicographic symbol order + content-derived IDs (`src/feelies/kernel/orchestrator.py:3696`, `3703`) | Genuinely unblockable; reason correctly `"FORCE_FLATTEN"` (`src/feelies/kernel/orchestrator.py:3718`) |
| Degrade-flatten | data-integrity/gap degrade before macro DEGRADED | MARKET, full symbol position | bypasses `check_signal`/`check_order` entirely (`src/feelies/kernel/orchestrator.py:6696-6710`) | content-addressed `(reason, symbol, seq)` order id (`src/feelies/kernel/orchestrator.py:6683`) | Genuinely unblockable, per-symbol exception isolation (`src/feelies/kernel/orchestrator.py:6711-6738`) |
| Hazard / hard-age exit | risk-layer `OrderRequest` on bus | MARKET, full current position | runs `check_order` defensively but overrides `REJECT` when the order reduces the position, submitting anyway with a WARNING alert (`src/feelies/kernel/orchestrator.py:6294`, `6304`, `6310`, `6336-6357`) | idempotency guard on `order_id` (`src/feelies/kernel/orchestrator.py:6291-6293`) | Correctly exit-fail-safe; tested at `tests/kernel/test_orchestrator_hazard_exit_routing.py:309` |
| Stop-loss / trailing stop | `_check_stop_exit` fixed/trailing thresholds | synthetic FLAT routed through the ordinary M4-M6 walk; MARKET unless overridden | min-lot and B4 bypassed via `is_exit_or_stop` (`src/feelies/kernel/orchestrator.py:4704-4708`); exposure/drawdown gate is not bypassed | overrides the arbitrated alpha signal and session-flat on the same tick, assigned last (`src/feelies/kernel/orchestrator.py:2481-2482`) | P0 (Inv-11): `check_signal` can `REJECT`/`FORCE_FLATTEN` this signal before an order is ever built (`src/feelies/risk/basic_risk.py:211-220`); P1: `reason="STOP_EXIT"` currently unset (`src/feelies/kernel/orchestrator.py:4798-4802`) |
| Session flatten (G-6) | exchange time ≥ `rth_close − buffer`, default ON | synthetic FLAT through the same M4-M6 walk; MARKET unless overridden | entries blocked in-window (`src/feelies/kernel/orchestrator.py:2709-2726`); exits unaffected by that specific gate; exposure/drawdown gate is not bypassed | resolved per-quote NY session date, multi-day rebind intact (`src/feelies/kernel/orchestrator.py:3877-3893`); session-flat assigned before stop, stop wins ties (`src/feelies/kernel/orchestrator.py:2477-2482`) | P0 (Inv-11): same shared-gate exposure as stop-loss (`src/feelies/risk/basic_risk.py:211-220`); correctly excluded from the panic-reason set by design (`src/feelies/kernel/orchestrator.py:315-320`) |
| Alpha FLAT full exit | alpha emits FLAT while positioned | MARKET (or PASSIVE-with-fallback if urgency-exec) full exit | min-lot/B4 bypassed (`is_exit_or_stop`); exposure/drawdown gate is not bypassed | ordinary arbitrated-signal path | P0 (Inv-11): same shared-gate exposure (`src/feelies/risk/basic_risk.py:211-220`) |
| G-1 TRIM (discretionary) | same-direction target shrink, `enable_trim=True` | partial EXIT; PASSIVE-with-MARKET-fallback (urgency-exec default ON) | reducing leg uses the EXIT bypass for min-lot/B4; churn guard and P3b edge-hold gate can suppress the trim itself (hold, not block); exposure/drawdown gate on the resulting EXIT order is not bypassed | maps to `TradingIntent.EXIT` (`src/feelies/execution/position_manager.py:682-688`) | Discretionary, so lower severity, but routes through the same shared risk gate (`src/feelies/risk/basic_risk.py:211-220`) as the safety exits above |
| Reverse exit leg | opposite-direction signal against an open book | MARKET full close, then optional PASSIVE/MARKET entry | exit is risk-checked via `check_order`; SCALE_DOWN ignored for the exit qty; exposure/drawdown gate is not bypassed | deterministic `:exit`/`:entry` order-id suffixes (`src/feelies/kernel/orchestrator.py:4314`, `4479`); exit submits before entry | P0 (Inv-11): a `REJECT` or (paper/live) `FORCE_FLATTEN` on the exit leg aborts the entire reversal including the close (`src/feelies/kernel/orchestrator.py:4329-4363`) |
| G-3 working-exit fallback | passive reduction cancelled/expired unfilled | residual MARKET | bypasses `check_signal`/`check_order` entirely — submits directly (`src/feelies/kernel/orchestrator.py:5292-5297`) | deterministic fallback id from parent order id (`src/feelies/kernel/orchestrator.py:5272`) | Genuinely unblockable (`src/feelies/kernel/orchestrator.py:5229-5235`) |

**Override-hierarchy note.** The documented hierarchy (FORCE_FLATTEN > stop-loss >
hazard/age > alpha) assumes each tier's action reliably executes once triggered. The
finding above (Inv-11, `src/feelies/risk/basic_risk.py:211-220`) breaks that assumption
for the stop-loss tier specifically: when the shared exposure/drawdown gate fires on the
stop's own synthetic signal, no substitute action occurs in `BACKTEST_MODE` — nothing is
flattened, the stop is simply dropped (`src/feelies/kernel/macro.py:74-79`) — so the
lower-priority alpha-signal tier is not even the one being starved; the stop-loss tier
starves itself. In `PAPER_TRADING_MODE`/`LIVE_TRADING_MODE` the `FORCE_FLATTEN` half
self-heals into a full-book `_emergency_flatten_all()` (`src/feelies/kernel/orchestrator.py:3599-3670`,
more aggressive than the single-symbol stop would have been), but the `REJECT` half
(gross exposure cap) has no mode-dependent escalation anywhere
(`src/feelies/risk/basic_risk.py:741-749`) and silently drops the order in every mode.

## Decision-economics audit

### RC-A status

`SignalPositionTranslator.translate` still branches purely on `signal.direction` and
`position.quantity` (`src/feelies/execution/intent.py:94-119`); it never reads avg entry
price, unrealized PnL, holding age, or cost. `_handle_long`/`_handle_short` clamp any
same-direction over-target book to `NO_ACTION`
(`src/feelies/execution/intent.py:150-158`, `187-195`) — a stronger signal with a lower
target never trims under this path. This is the documented, still-supported legacy
fallback (used only when `position_manager_drive=False`); it is not exercised in the
current default configuration.

### G-1 equivalence and trim path

`LegacyPositionManager.plan` reproduces the translator's clamp exactly — `eff = max(cur,
mag)` on the long side / `min(cur, -mag)` on the short side
(`src/feelies/execution/position_manager.py:242-247`) — and never emits `TRIM`
(`src/feelies/execution/position_manager.py:279-295`), matching the byte-equivalence
claim; exercised by `tests/execution/test_position_manager.py:52`
(`test_legacy_manager_matches_translator_truth_table`).

`TargetPositionManager` overrides only the same-direction-shrink hold
(`src/feelies/execution/position_manager.py:388-397`): a churn guard suppresses trims
below `trim_min_fraction` (default 0.10,
`src/feelies/execution/position_manager.py:399-415`), then the P3b edge-hold gate
suppresses the trim entirely (holds the excess) while `edge_bps >=
trim_edge_gate_multiplier × round_trip_cost_bps`
(`src/feelies/execution/position_manager.py:440-470`). Both `enable_trim` and
`trim_edge_gate_multiplier` (now `1.0`, not `0.0`) are default-on
(`src/feelies/core/platform_config.py:323-329`); every flip traces to a comment-cited
audit number and the config-contract re-baseline log in
`tests/acceptance/test_backtest_app_baseline.py:34-51` — a documented, deliberate
default-on trade-path choice, not a silent one. The APP/2026-03-26 reference dataset
emits no discretionary TRIM (`tests/acceptance/test_backtest_app_baseline.py:86-88`), so
the edge-gate multiplier's live effect is untested against that specific baseline — a
minor coverage gap, P2, not a parity break.

A `TRIM` leg projects onto `TradingIntent.EXIT`
(`src/feelies/execution/position_manager.py:682-688`), which is exempt from
`min_order_shares` and the B4 gate via the `is_exit_or_stop` branch
(`src/feelies/kernel/orchestrator.py:4704-4708`) — but, like every other reducing leg,
is not exempt from `check_signal`'s exposure/drawdown gate
(`src/feelies/risk/basic_risk.py:211-220`).

### B4 / B5 recomputation

B4 (`_signal_passes_edge_cost_gate`, `src/feelies/kernel/orchestrator.py:3146-3199`) is a
no-op only when `signal_min_edge_cost_ratio <= 0` or no cost model is wired
(`src/feelies/kernel/orchestrator.py:3165-3166`); default is `1.0`
(`src/feelies/core/platform_config.py:303-308`, round-trip-breakeven, flipped from 0.0
per audit F-H-14). It compares a realization-calibrated edge
(`effective_edge_bps = signal.edge_estimate_bps * factor`, factor defaulting to `1.0`
when uncalibrated, `src/feelies/kernel/orchestrator.py:3178-3179`) against
`entry_edge_clears_cost` (`src/feelies/execution/position_manager.py:550-564`), the
single source of truth also used by the P3b trim gate.

B5 (`_reversal_passes_combined_edge_gate`,
`src/feelies/kernel/orchestrator.py:3276-3335`) compares raw `edge_estimate_bps` (no
calibration factor — `src/feelies/kernel/orchestrator.py:3279`, called with
`intent.signal.edge_estimate_bps` at `src/feelies/kernel/orchestrator.py:4413`) against
`reversal_edge_gate`'s combined exit+entry cost
(`src/feelies/execution/position_manager.py:567-581`). `_execute_reverse` runs B5 first;
only if it passes does it also run B4 (calibrated) on the entry leg
(`src/feelies/kernel/orchestrator.py:4463-4475`) — so a reversal needs
raw-edge-clears-combined-cost and calibrated-edge-clears-entry-cost to get its entry
leg; failing either leaves a flatten-only reversal. This is fail-safe on its own terms
(the exit leg is unconditional on B4/B5, subject only to the shared risk-gate issue
above), so the calibration asymmetry stays P2, unchanged since the 06-20 audit.

`entry_edge_clears_cost`'s `basis` parameter
(`src/feelies/core/platform_config.py:298-301`, `signal_edge_cost_basis` default
`"round_trip"`) doubles the disclosed one-way edge onto a round-trip basis before
comparing; B5 has no equivalent basis parameter — a second, minor asymmetry worth
documenting alongside the calibration one but not independently actionable.

## Sizing audit

Base sizer (`BudgetBasedSizer.compute_target_quantity`,
`src/feelies/risk/position_sizer.py:80-109`): `floor(equity ×
capital_allocation_pct/100 × clamp(strength,0,1) × regime_factor / price)`, capped at
`risk_budget.max_position_per_symbol` (`src/feelies/risk/position_sizer.py:107`) and
floored at 0 for non-positive price/equity
(`src/feelies/risk/position_sizer.py:87-88`). `edge_estimate_bps` is never referenced in
this file. `regime_factor` is the EV over the posterior, clamped `min(1.0, ev)`
(`src/feelies/risk/position_sizer.py:137`) — can only shrink, per Inv-11;
unknown/missing posteriors fail safe to `min(all factors)`
(`src/feelies/risk/position_sizer.py:117-125`).

G-7 tilt (`src/feelies/risk/edge_weighted_sizer.py`): every factor is independently
clamped — `edge_factor` to `[edge_floor, edge_cap]` (default `[0.25, 2.0]`, no-op on
non-positive reference, `src/feelies/risk/edge_weighted_sizer.py:118-127`); `vol_factor`
to `[vol_floor, vol_cap]`, no-op on missing/non-positive realized vol
(`src/feelies/risk/edge_weighted_sizer.py:130-141`); `inventory_factor` tapers only
(`1 - used`, clamped `[floor, 1.0]`, never amplifies,
`src/feelies/risk/edge_weighted_sizer.py:144-154`). The combined tilt is clamped to
`[tilt_floor, tilt_cap] = [0.10, 3.0]`
(`src/feelies/risk/edge_weighted_sizer.py:69-70`, `251`), and `apply_tilt` floors
deterministically then re-caps at the same `max_position_per_symbol` the base sizer
already respects (`src/feelies/risk/edge_weighted_sizer.py:283`, `286-289`) —
amplification is deliberate (G-7's purpose) but structurally bounded, never autonomous
beyond the alpha's declared envelope. FLAT signals always get unit tilt so G-7 never
shrinks a close (`src/feelies/risk/edge_weighted_sizer.py:183`, `207-215`).

Shadow discipline: `sizer_tilt_drive` defaults `False`
(`src/feelies/core/platform_config.py:374`); with it off the live size is
byte-identical to `BudgetBasedSizer` (`src/feelies/risk/edge_weighted_sizer.py:278-280`)
and the tilted target is computed only for the shadow `SizeDivergence` stream.
Individually enabling a factor while leaving `sizer_tilt_drive=False` still only feeds
the shadow — confirmed by `tests/bootstrap/test_position_manager_wiring.py:129-165`.

## Netting audit

Standing-target expiry: `_is_stale` treats `now_ns == expiry_ns` as fresh
(`src/feelies/execution/portfolio_netter.py:106-107`), matching the `k × horizon` policy
(`src/feelies/execution/portfolio_netter.py:52-69`) and the signal-buffer staleness
contract. Horizon-zero signals cannot receive a `k×horizon` expiry, so both the
SIGNAL-path (`src/feelies/kernel/orchestrator.py:4224-4225`) and the PORTFOLIO-bridge
path (`src/feelies/kernel/orchestrator.py:4159-4160`) explicitly track and evict them on
the next tick (`src/feelies/kernel/orchestrator.py:4203-4205`).

Default inertness: `enable_portfolio_netting` defaults `False`
(`src/feelies/core/platform_config.py:354`). `_record_net_shadow` maintains the
standing-target book only when a sink is wired or netting drives
(`src/feelies/kernel/orchestrator.py:4177-4182`); the decision itself only reads the net
target when `position_manager_drive` and `enable_portfolio_netting` are both true
(`src/feelies/kernel/orchestrator.py:2517-2530`) — with netting off, `decision_signal`
stays the arbitrated winner and the flip is byte-identical to the pre-N2 path.

Forced-exit bypass: stop-loss/session-flat signals unconditionally skip the net target
(`src/feelies/kernel/orchestrator.py:2527-2530`) — so a synthetic safety exit always
targets flat regardless of what other alphas' standing targets would net to. The bypass
set is exactly `_FORCED_MARKET_EXIT_STRATEGIES`
(`src/feelies/kernel/orchestrator.py:304-308`) and nothing more; hazard exits never
reach this decision branch (separate bus path) and TRIM only fires on an
already-net-computed same-direction shrink, so neither is a gap.

Live netting / determinism: `PortfolioNetter.net` clamps each live target to its own
`max_abs_qty`, sums, clamps to the portfolio cap, and derives `edge_bps`/`urgency` only
from contributors aligned with the net direction
(`src/feelies/execution/portfolio_netter.py:152-191`).
`DesiredTargetBook.live_targets` sorts by `strategy_id`
(`src/feelies/execution/portfolio_netter.py:125-134`), so `net()` is order-independent —
exercised by `tests/execution/test_portfolio_netter.py:110`
(`test_net_is_order_independent`). The only unordered-iteration method,
`DesiredTargetBook.symbols()` (`src/feelies/execution/portfolio_netter.py:136-137`,
returns a `set`), is not on the live decision path.

## PnL-ledger audit

### Hand-worked reconciliation (fresh example; store code unchanged since 06-20)

Sequence on one symbol: buy 100 @ 50 → buy 50 @ 54 → sell 120 @ 60 → sell 30 @ 55.

**Avg-cost store** (`src/feelies/portfolio/memory_position_store.py:44-95`):
1. Buy 100 @ 50: `avg = 50`, `qty = 100`.
2. Buy 50 @ 54 (same sign, blend at `src/feelies/portfolio/memory_position_store.py:72-74`):
   `avg = (50×100 + 54×50) / 150 = 51.3333`, `qty = 150`.
3. Sell 120 @ 60 (opposite sign, reduce at `src/feelies/portfolio/memory_position_store.py:75-84`):
   `closed = 120`, `realized += (60 − 51.3333) × 120 = 1040.00`; `avg` unchanged
   (partial reduce, `|delta| ≤ |old_qty|`); `qty = 30`.
4. Sell 30 @ 55: `closed = 30`, `realized += (55 − 51.3333) × 30 = 110.00`; `qty = 0` →
   `avg` reset to 0 (`src/feelies/portfolio/memory_position_store.py:88-89`).
   Total realized = 1040 + 110 = **$1,150.00**.

**FIFO lot ledger** (`src/feelies/portfolio/lot_ledger.py:52-115`), same fills:
1. Lots: `[100@50]`. 2. Lots: `[100@50, 50@54]`.
3. Sell 120 (FIFO front-first, `src/feelies/portfolio/lot_ledger.py:89-101`): consume
   `100@50` fully (`realized += (60−50)×100 = 1000`), then `20` from `50@54`
   (`realized += (60−54)×20 = 120`); running FIFO realized = 1120; lots `[30@54]`.
4. Sell 30: consumes the remaining `30@54` (`realized += (55−54)×30 = 30`); FIFO
   realized = 1150; lots `[]`.
   Total FIFO realized = 1000 + 120 + 30 = **$1,150.00**.

Both books agree at flat ($1,150.00 = $1,150.00), matching
`tests/portfolio/test_lot_ledger.py:111`, `141` (deterministic and randomized
flat-return properties). They legitimately diverge mid-stream: after fill 3 the avg-cost
store shows $1,040 realized while FIFO shows $1,120 — a documented $80 difference
(`src/feelies/portfolio/lot_ledger.py:14-17`) because FIFO recognizes the cheaper, older
lot's larger per-share gain first while the blended average smooths it — not a bug, and
correctly never read by the decision path (`src/feelies/portfolio/lot_ledger.py:1-18`;
no call site outside `portfolio/`, `forensics/`, and tests found in the audited scope).

### Marks and aggregation

Longs mark to bid, shorts to ask, mid as fallback
(`src/feelies/portfolio/memory_position_store.py:138-141`, audit F-H-03); `unrealized =
(mark − avg) × quantity` is sign-correct for shorts because `quantity` is negative
(`src/feelies/portfolio/memory_position_store.py:145`).
`StrategyPositionStore.get_aggregate` sums realized/unrealized/fees verbatim across
per-alpha stores and derives a netted `avg_entry_price` from signed cost over net
quantity (`src/feelies/portfolio/strategy_position_store.py:95-129`); the docstring
correctly warns this net average can be lower or negative than any individual alpha's
cost basis under mixed directions
(`src/feelies/portfolio/strategy_position_store.py:98-103`) — a net-book view, not a
per-alpha attribution error, and Σ per-alpha realized/fees equal the aggregate by
construction (summed, not re-derived).

### Trade journal provenance

`TradeRecord.metadata` now carries `order_reason`/`order_source_layer`
(`src/feelies/kernel/orchestrator.py:5844-5851`, the 2026-06-20 audit's remediation) when the upstream
`OrderRequest.reason` is actually populated — which the STOP_EXIT regression above
breaks specifically for stop-loss fills (hazard/hard-age and FORCE_FLATTEN fills are
unaffected; those `OrderRequest`s are built on different code paths that still set
`reason` correctly, `src/feelies/kernel/orchestrator.py:3718`).
`TradeRecord.net_pnl`'s docstring is current and consistent with the BT-3 fill-price
convention (`src/feelies/storage/trade_journal.py:60-74`) — the 06-20 P2 documentation
finding is fixed.

## Determinism & flag-parity matrix

| Feature / path | Default | Parity posture | Evidence | Audit call |
|---|---:|---|---|---|
| Legacy translator | supported fallback | pure function of signal/qty/target | `src/feelies/execution/intent.py:94-119` | intentional supported path |
| Position manager drive + trim + P3b edge gate | ON | deliberate trade-path change, rebaselined | `src/feelies/core/platform_config.py:323-329`; `tests/acceptance/test_backtest_app_baseline.py:34-88` | documented gap closure (G-1/P3b), not silent |
| Urgency-passive trims | ON | deliberate, rebaselined | `src/feelies/core/platform_config.py:330-339`; `tests/acceptance/test_backtest_app_baseline.py:77-82` | intentional design |
| Portfolio netting | OFF | inert unless enabled or shadow sink wired | `src/feelies/core/platform_config.py:354`; `src/feelies/kernel/orchestrator.py:4181-4182` | parity-preserving default |
| Sizer tilt drive | OFF | base sizer stays live | `src/feelies/core/platform_config.py:374`; `src/feelies/risk/edge_weighted_sizer.py:278-280` | parity-preserving default |
| Lot ledger | always maintained | observability-only | `src/feelies/portfolio/lot_ledger.py:1-18`; no decision-path reader found | intentional design |
| Session flatten (G-6) | ON | default-on close-path exception, tested | `src/feelies/core/platform_config.py:345`; `tests/kernel/test_orchestrator.py:2326-2361` | intentional safety default |
| Stop / session forced-exit strategy set | N/A | deterministic set, priority-ordered inline | `src/feelies/kernel/orchestrator.py:304-308`, `2477-2482` | deterministic ordering, but the set does not exempt these signals from the shared risk gate — P0 (Inv-11), `src/feelies/risk/basic_risk.py:211-220` |
| STOP_EXIT panic-reason stamp | should be ON | currently absent — regression | `src/feelies/kernel/orchestrator.py:4798-4802` vs. `git show 4a90cd8` | P1 (Inv-12, Inv-13): fixed 06-20, silently reverted 2026-06-24, 5 tests currently failing in `tests/kernel/test_orchestrator.py` |
| Reverse / working-fallback order IDs | N/A | deterministic (SHA-256 of correlation_id/parent id) | `src/feelies/kernel/orchestrator.py:4314`, `5272`; no `uuid4` usage found in the audited scope | deterministic |
| Net shadow / divergence streams | OFF unless sink wired | observational | `src/feelies/kernel/orchestrator.py:4181-4182`, `4227-4229` | parity-neutral |
| `DesiredPosition.mandatory` | always `False` | never set, never read | `src/feelies/execution/position_manager.py:90-102`; repo-wide grep finds only the definition | dead field — see executive summary |

## Test gap matrix

| Invariant / behavior | Status | Evidence | Gap |
|---|---|---|---|
| Safety exit survives the risk-engine exposure/drawdown gate | Missing — P0 (Inv-11), `src/feelies/risk/basic_risk.py:211-220` | `tests/execution/test_reducing_leg_invariants.py` covers only the B4/min-lot bypass at the planner layer (its own docstring scopes this to the never-min-lot-filtered EXIT path, lines 1-13); no test anywhere constructs a `REJECT`/`FORCE_FLATTEN` `RiskVerdict` and asserts a stop-loss/session-flat/alpha-FLAT/reverse-exit order still submits | add the property the hazard-routing suite already has (`tests/kernel/test_orchestrator_hazard_exit_routing.py:309`) for the four other exit paths |
| Hazard/hard-age exit survives REJECT | Covered | `tests/kernel/test_orchestrator_hazard_exit_routing.py:309` (`test_reducing_exit_submits_despite_reject`), `:330` (non-reducing REJECT still blocks) | none found |
| STOP_EXIT panic-reason + journal provenance | Currently failing — P1 (Inv-12, Inv-13), `src/feelies/kernel/orchestrator.py:4798-4802` | `tests/kernel/test_orchestrator.py::TestForcedExitReasonClassification`/`TestForcedExitPanicReason`/`TestTradeJournalProvenance` — 5 failures on this checkout | fix the regression; the tests already correctly pin the intended behavior and need no changes |
| Legacy translator / legacy manager parity | Covered | `tests/execution/test_position_manager.py:52` | none found |
| Trim planning, churn guard, P3b edge gate, urgency style | Covered | `tests/execution/test_position_manager.py:332`, `371`, `428`, `450`, `472`, `493`, `513` | add one case exercising the live default `trim_edge_gate_multiplier=1.0` against a non-zero cost model, complementing the APP-baseline's no-TRIM gap in §D |
| B4 standalone entry gate | Covered | `tests/kernel/test_orchestrator_cost_gate.py:22-87` (all passed in this run) | none found |
| B5 reversal flatten-only safety | Covered, kernel-embedded | `tests/kernel/test_orchestrator.py:2877`, `2905` (module-level run is green) | none found |
| G-7 tilt bounds | Covered | `tests/risk/test_edge_weighted_sizer.py:213`, `228` (`test_recapped_at_budget`, `test_combined_tilt_clamped`) | property-test random configs for `0 ≤ target ≤ max_position` (still open from 06-20) |
| Netting inertness / order independence | Covered | `tests/execution/test_portfolio_netter.py:110`; `tests/bootstrap/test_position_manager_wiring.py` | none found |
| Store-vs-lot reconciliation | Covered | `tests/portfolio/test_lot_ledger.py:111`, `141` (also hand-reconciled fresh in §G above) | none found |
| Aggregate strategy-store PnL identity | Covered | `src/feelies/portfolio/strategy_position_store.py:95-129` sums verbatim (arithmetic identity by construction); exercised by `tests/portfolio/test_strategy_position_store.py` | none found |
| `DesiredPosition.mandatory` semantics | Untested / unused | grep-only finding, `src/feelies/execution/position_manager.py:90-102` | wire it into `plan()`'s cost-gate short-circuit, or delete the field and its docstring claim |
| Decision-path exit tests live inside kernel modules | Partial (structural) | stop/session-flatten/reverse/B4 coverage is embedded in `tests/kernel/test_orchestrator.py` rather than a dedicated exit-safety module | this placement is exactly why the risk-gate finding above went unnoticed — a dedicated cross-cutting "no exit is ever blocked" module (mirroring `tests/execution/test_reducing_leg_invariants.py:1-13` but at the risk-verdict layer) would have caught it |

## Prioritized backlog

| Priority | Type | Component | Evidence | One-sentence fix | Expected impact | Effort |
|---|---|---|---|---|---|---|
| P0 (Inv-11, Inv-9) | Implementation bug | Risk-engine exposure/drawdown gate vs. reducing orders | `src/feelies/risk/basic_risk.py:211-220`, `313-323`, `741-749`, `729-737`, `755-763`; orchestrator drop points `src/feelies/kernel/orchestrator.py:2615-2666`, `2809-2859`, `4335-4363`; empirically reproduced, §D | exempt `_check_exposure_and_drawdown`'s `REJECT`/`FORCE_FLATTEN` outcome for reducing orders, mirroring `_opens_or_increases` and the hazard handler's `order_reduces` carve-out (`src/feelies/kernel/orchestrator.py:6304-6357`) | stops and session-flattens actually close the position instead of silently no-op'ing when the book is already stressed; removes a live backtest/live parity break | M |
| P1 (Inv-12, Inv-13) | Regression | STOP_EXIT panic-fill reason stamp | `src/feelies/kernel/orchestrator.py:4798-4802` (comment with no `reason=` kwarg); `git show 4a90cd8`; 5 failing tests in `tests/kernel/test_orchestrator.py` on this checkout | re-add `reason=_FORCED_EXIT_PANIC_REASON.get(intent.signal.strategy_id, "")` to the `OrderRequest(...)` construction in `_try_build_order_from_intent` | restores realistic stop-loss fill pricing and journal provenance; the already-correct tests go green with no test changes needed | S |
| P1 (Inv-11) | Test gap | Reducing-leg-vs-risk-gate coverage | `tests/execution/test_reducing_leg_invariants.py:1-13` scopes only B4/min-lot; no risk-verdict-layer equivalent exists anywhere | add a module asserting stop/session-flat/alpha-FLAT/reverse-exit orders submit under a stubbed `REJECT`/`FORCE_FLATTEN` risk verdict, parametrized like `tests/kernel/test_orchestrator_hazard_exit_routing.py:309` | locks the risk-gate fix above and prevents recurrence; would have caught it before this audit | S |
| P2 | Consistency | B4/B5 edge-basis mismatch | B4 calibrated (`src/feelies/kernel/orchestrator.py:3178-3179`), B5 raw (`src/feelies/kernel/orchestrator.py:3279`, `4413`) | decide and document whether B5 should use the calibrated edge, or note explicitly why raw is intentional | fewer flip entries / more flatten-only reversals if calibrated; no safety change either way | S |
| P2 | Dead code / doc drift | `DesiredPosition.mandatory` | `src/feelies/execution/position_manager.py:90-102`; no setter, no reader in repo | wire it into `TargetPositionManager.plan()`'s cost-gate short-circuit, or delete the field and its docstring claim | removes a misleading "this is how safety is enforced" signal for future maintainers | S |
| P2 | Coverage | P3b trim edge gate at its live default | APP/2026-03-26 baseline never emits a TRIM (`tests/acceptance/test_backtest_app_baseline.py:86-88`), so `trim_edge_gate_multiplier=1.0`'s live effect is unexercised by the pinned baseline | add a synthetic (non-baseline) test driving a same-direction shrink through a wired cost model with the live default multiplier | confirms the default-on P3b gate behaves as intended outside the one dataset that happens not to trigger it | S |
| P2 | Property test | G-7 tilt bounds | `tests/risk/test_edge_weighted_sizer.py:213`, `228` are example-based, not property-based (carried over from 06-20) | add a `hypothesis`-style test asserting `0 ≤ apply_tilt(...) ≤ max_position` over randomized factor configs | raises confidence beyond the fixed examples already covered | S |

Read-only checks run on this checkout:

- `uv run pytest tests/execution/test_intent.py tests/execution/test_position_manager.py tests/execution/test_portfolio_netter.py -q` → 385 passed.
- `uv run pytest tests/risk/test_position_sizer.py tests/risk/test_edge_weighted_sizer.py -q` → 116 passed.
- `uv run pytest tests/portfolio/ -q` → 50 passed.
- Supplementary, to verify the findings above: `uv run pytest tests/execution/test_reducing_leg_invariants.py tests/kernel/test_orchestrator_hazard_exit_routing.py tests/kernel/test_orchestrator_cost_gate.py -q` → 25 passed.
- Supplementary: `uv run pytest tests/kernel/test_orchestrator.py -q` → 127 passed, 5 failed (`TestForcedExitReasonClassification::test_only_stop_exit_intent_is_tagged_as_panic`, `::test_stop_trigger_tags_order_and_journals_reason`, `TestForcedExitPanicReason::test_stop_exit_order_carries_stop_exit_reason`, `::test_stop_exit_fill_pays_panic_slippage_end_to_end`, `TestTradeJournalProvenance::test_stop_exit_fill_records_reason_in_journal_metadata`).
- Supplementary: a read-only, non-persisted Python repro against `BasicRiskEngine.check_signal` (`src/feelies/risk/basic_risk.py:167-229`) confirmed a `__stop_exit__` FLAT signal is `REJECT`-ed when the closing position's own notional exceeds `max_gross_exposure_pct`, and `FORCE_FLATTEN`-ed when account equity is driven non-positive by an unrelated symbol's realized loss. No production code or fixtures were modified; the script lived only in the session scratch directory.

No production code, baselines, configs, or ledgers were modified in this audit.
