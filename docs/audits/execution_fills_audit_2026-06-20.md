# Execution Fills Audit 2026-06-20

Scope: read-only audit of `OrderRequest -> ExecutionBackend -> router -> fill model -> tick/regulatory -> Trade/PnL`.
No production code was modified.

Verification run:

- `uv run pytest tests/execution/ -q` -> 662 passed.
- `uv run pytest tests/acceptance/test_bt11_parity_post_fill_model.py tests/acceptance/test_bt14_tick_rounding.py tests/acceptance/test_bt17_market_data_latency.py tests/acceptance/test_inv12_stress_gate.py -q` -> 22 passed.
- `uv run pytest tests/acceptance/test_backtest_app_baseline.py -q` -> 1 failed, 1 passed. The cached APP replay produced 4 fills and net PnL $52.54, while the baseline pins 6 fills and $69.06 in `tests/acceptance/test_backtest_app_baseline.py:125`.

Legend: implementation bug = code behavior violates the intended execution contract; modeling choice = deliberate approximation that may be optimistic; intentional design = documented tradeoff that is internally consistent.

## 1. Executive summary

1. **P0 implementation bug: passive resting LIMIT orders are posted immediately despite positive backtest fill latency.** The configured default is 50 ms (`platform.yaml:115`), but `_post_passive` records the order with `ack_ts = self._clock.now_ns()` and begins evaluating it on later quotes without an exchange-time eligibility deadline (`src/feelies/execution/passive_limit_router.py:534`, `src/feelies/execution/passive_limit_router.py:573`). This affects the default `passive_limit` profile (`platform.yaml:185`) and can fill on pre-eligibility quotes/trades. Fix: defer passive order posting until `submit_quote.exchange_timestamp_ns + latency_ns`, just like aggressive fills. Expected impact: lower passive fill rate and less early price improvement.
2. **No market/aggressive fill lookahead found.** Market orders with positive latency become `DeferredFill`s and fill only when a later quote reaches the exchange-time deadline (`src/feelies/execution/backtest_router.py:298`, `src/feelies/execution/backtest_router.py:312`; `src/feelies/execution/passive_limit_router.py:397`, `src/feelies/execution/passive_limit_router.py:409`). This is causal for market-mode and aggressive fallback fills.
3. **P1 validation blocker: the data-backed APP baseline is not green in this workspace.** The functional baseline expects 6 fills and $69.06 (`tests/acceptance/test_backtest_app_baseline.py:125`), but the requested run produced 4 fills and $52.54. Until cache provenance or constants are reconciled, this test cannot support promotion claims for APP/2026-03-26.
4. **The root `platform.yaml` still defaults the runtime edge gate below the Inv-12 target.** It sets `signal_min_edge_cost_ratio: 1.0` while documenting that Inv-12 wants 1.5 (`platform.yaml:149`, `platform.yaml:156`). APP-style deployment configs override to 1.5 (`configs/bt_sig_benign_midcap.yaml:21`), and bootstrap warns on 1.0 to <1.5 (`src/feelies/bootstrap.py:260`), but the default CLI config remains research-permissive. This is a P1 config-risk modeling choice.
5. **Passive queue realism is much improved in the reference profile, but only by config.** Code defaults leave through-fill size caps and trade-required level fills off (`src/feelies/core/platform_config.py:456`, `src/feelies/core/platform_config.py:461`); `platform.yaml` flips both on (`platform.yaml:206`, `platform.yaml:210`) and sets a 200-share queue proxy (`platform.yaml:189`). Direct configs that do not extend `platform.yaml` can still be optimistic.
6. **Within-L1 impact is implemented and enabled in `platform.yaml`, but permanent impact remains uncalibrated/off.** The code supports temporary participation and permanent sqrt impact (`src/feelies/execution/market_fill.py:140`), root config enables `cost_within_l1_impact_factor: 0.3` and leaves `cost_permanent_impact_coefficient: 0.0` (`platform.yaml:213`, `platform.yaml:222`). This is a P2 calibration gap, not an implementation defect.
7. **Short-side costs remain optimistic for omitted symbols.** Omitted borrow symbols default to `available` (`src/feelies/execution/regulatory/borrow_availability.py:5`), and root HTB cost is disabled (`platform.yaml:177`). Short alphas therefore assume locates and no borrow fee unless config says otherwise. This is P1 for non-large-cap or HTB-prone universes.
8. **MOC timing is causal, but price realism is still a close-mid proxy.** MOC waits until a clean post-close quote (`src/feelies/execution/moc_fill.py:116`, `src/feelies/execution/moc_fill.py:145`) and root config adds a 3 bps penalty (`platform.yaml:219`), but fills still use NBBO close mid, not an official auction print (`src/feelies/execution/moc_fill.py:205`). This is P2.
9. **Tick rounding is conservative.** Taker BUY fills round up and SELL fills round down (`src/feelies/execution/tick_size.py:34`), and passive limits round on the passive side (`src/feelies/execution/tick_size.py:41`). No rounding-in-favor issue found.
10. **Backtest/live parity is structurally sound at the seam, but live fill economics are not literally shared.** Backtest mode uses the shared `OrderRouter` protocol and aggressive fill helper (`src/feelies/execution/backend.py:55`, `src/feelies/execution/market_fill.py:3`); PAPER/LIVE fills still come from broker/backend code, so sim-vs-live cost parity is monitored, not guaranteed by code sharing.
11. **The golden `market_fill` replay gap noted in the prior audit is closed.** The deterministic manifest includes `market_fill_acks` (`tests/determinism/parity_manifest.py:117`), and the golden replay pins the ack hash/count (`tests/determinism/test_market_fill_replay.py:103`).
12. **Inv-12 mechanics are wired, but full data-backed survival remains an operator/data run.** `apply_inv12_stress` scales cost by 1.5 and both latency legs by 2 (`src/feelies/core/inv12_stress.py:41`), and the CLI flag applies it (`src/feelies/harness/backtest_cli.py:94`); the requested acceptance slice validates helpers, not APP stressed PnL.

## 2. Execution inventory

| Component | Role | Realism notes |
|---|---|---|
| `ExecutionBackend` / `OrderRouter` | Mode seam and order contract | `OrderRouter.submit`/`poll_acks` define the shared interface (`src/feelies/execution/backend.py:55`). |
| `ReplayFeed` | Backtest market-data visibility | Feed latency advances visible clock before yielding events (`src/feelies/ingestion/replay_feed.py:101`). |
| `BacktestOrderRouter` | Market/aggressive backtest fills | Emits ACK then immediate or deferred fills; positive latency uses deadline (`src/feelies/execution/backtest_router.py:272`, `src/feelies/execution/backtest_router.py:301`). |
| `PassiveLimitOrderRouter` | Passive queue and aggressive fallback | Aggressive fallback is causal; passive posting is immediate and currently ignores positive latency before resting (`src/feelies/execution/passive_limit_router.py:515`, `src/feelies/execution/passive_limit_router.py:534`). |
| `market_fill.py` | Shared aggressive fill economics | Cross-price taker model, spread embedded in fill price (`src/feelies/execution/market_fill.py:10`, `src/feelies/execution/market_fill.py:219`). |
| `moc_fill.py` | MOC close fill controller | Causal close timing, close-mid proxy, optional penalty (`src/feelies/execution/moc_fill.py:116`, `src/feelies/execution/moc_fill.py:205`, `src/feelies/execution/moc_fill.py:220`). |
| `DefaultCostModel` | Fees, adverse selection, spread floor, HTB | Variable costs stress; fixed broker floors/caps not stressed (`src/feelies/execution/cost_model.py:129`, `src/feelies/execution/cost_model.py:283`). |
| `estimate_round_trip_cost_bps` | Runtime edge-vs-cost gate | Prices entry plus exit, with depth-aware taker legs when depth is supplied (`src/feelies/execution/cost_model.py:570`, `src/feelies/execution/cost_model.py:621`). |
| `tick_size.py` | Reg-NMS rounding | Taker fills round against trader; passive limits round to valid passive grid (`src/feelies/execution/tick_size.py:7`, `src/feelies/execution/tick_size.py:41`). |
| Borrow/PDT/RTH | Regulatory/session gates | Static locate model, PDT min-equity gate, RTH entry suppression (`src/feelies/execution/regulatory/borrow_availability.py:1`, `src/feelies/execution/regulatory/pdt_constraint.py:1`, `src/feelies/execution/trading_session.py:114`). |
| Inv-12 stress | Cost/latency stress harness | Pure config replacement, deterministic (`src/feelies/core/inv12_stress.py:9`, `src/feelies/core/inv12_stress.py:41`). |

## 3. Fill realism & lookahead audit

### Market/aggressive fill trace

Implementation status: intentional design, causal.

For market-mode or aggressive fallback fills, the router stores the last visible quote, acknowledges first, and either fills immediately when `latency_ns <= 0` or appends a deferred fill when `latency_ns > 0` (`src/feelies/execution/backtest_router.py:242`, `src/feelies/execution/backtest_router.py:272`, `src/feelies/execution/backtest_router.py:286`, `src/feelies/execution/backtest_router.py:298`). Deferred market fills ignore quotes whose `exchange_timestamp_ns` is before the fill deadline (`src/feelies/execution/backtest_router.py:325`) and execute against the first eligible quote (`src/feelies/execution/backtest_router.py:359`). The passive router's aggressive path mirrors this (`src/feelies/execution/passive_limit_router.py:371`, `src/feelies/execution/passive_limit_router.py:399`, `src/feelies/execution/passive_limit_router.py:419`, `src/feelies/execution/passive_limit_router.py:479`).

The feed side is also causal: default market-data latency is 20 ms (`src/feelies/core/platform_config.py:37`), and bootstrap passes it into the backtest backend (`src/feelies/bootstrap.py:479`). Tests cover zero-latency fast path and positive-latency later-quote fill (`tests/execution/test_router_latency.py:67`, `tests/execution/test_router_latency.py:81`, `tests/execution/test_router_latency.py:162`).

### Passive resting order latency

Finding: P0 implementation bug in `passive_limit` / `minimum_cost` modes.

Positive `latency_ns` delays aggressive fills but not passive order placement. `_post_passive` records the limit order immediately at `ack_ts = self._clock.now_ns()` (`src/feelies/execution/passive_limit_router.py:534`) and inserts it into `_resting_orders` before any latency deadline (`src/feelies/execution/passive_limit_router.py:543`). `_check_resting_orders` evaluates every later quote for fills (`src/feelies/execution/passive_limit_router.py:573`), so a quote/trade arriving inside the 50 ms configured order latency can fill an order that should not yet be resting at the exchange. The fill ack timestamp then adds latency at emission time (`src/feelies/execution/passive_limit_router.py:913`), which preserves timestamp monotonicity but does not fix order-existence causality.

This is not future-price lookahead; the quote is visible by fill sim-time. The defect is exchange placement causality: a passive order can participate in liquidity before its submit latency has elapsed. Because `platform.yaml` uses `execution_mode: passive_limit` (`platform.yaml:185`) and 50 ms fill latency (`platform.yaml:115`), this affects the reference backtest profile, not only tests.

Relevant test gap: the only test named as a resting-limit latency check uses `latency_ns=0` (`tests/execution/test_router_latency.py:180`, `tests/execution/test_router_latency.py:185`). It does not prove positive-latency passive posting.

Minimal fix: introduce a `_DeferredPassivePost` with `post_deadline_exchange_ns = max(clock.now_ns(), submit_quote.exchange_timestamp_ns) + latency_ns`; before the deadline, do not add the order to `_resting_orders`. Emit ACK at `now + latency_ns` or model broker ACK separately if needed, but keep fill eligibility at or after the exchange deadline.

Expected PnL impact: fewer passive fills and less price improvement in fast-moving quotes, especially for through fills and short-horizon signals.

### Passive queue and partial fills

Implementation status: mixed; current reference profile is conservative, code defaults are still compatibility-neutral.

Through fills can be capped by crossing quote size when `through_fill_size_cap_enabled` is true (`src/feelies/execution/passive_limit_router.py:617`, `src/feelies/execution/passive_limit_router.py:623`). If disabled, the full remaining order fills (`src/feelies/execution/passive_limit_router.py:622`). Root `platform.yaml` enables the cap (`platform.yaml:206`), and tests cover both default full-fill and enabled partial-fill behavior (`tests/execution/test_execution_realism_knobs.py:198`, `tests/execution/test_execution_realism_knobs.py:215`).

Level fills have two regimes. With positive queue ahead, fill hazard is zero until observed trades drain the queue (`src/feelies/execution/passive_limit_router.py:754`). With queue ahead zero, quote-imbalance fills can fire without trade volume unless `require_trade_for_level_fill` is true (`src/feelies/execution/passive_limit_router.py:759`). Root `platform.yaml` sets `passive_queue_position_shares: 200` and also enables the trade-required gate (`platform.yaml:189`, `platform.yaml:210`), which is conservative for reference backtests. The code defaults preserve legacy behavior (`src/feelies/core/platform_config.py:278`, `src/feelies/core/platform_config.py:461`).

### Stop and forced-exit slippage

Implementation status: intentional design with a remaining calibration gap.

Forced exits are identified by `STOP_EXIT_REASONS` and charge extra spread when `stop_slippage_half_spreads > 1` (`src/feelies/execution/market_fill.py:226`, `src/feelies/execution/market_fill.py:227`). The current profile also depletes effective L1 depth on stops (`src/feelies/execution/market_fill.py:232`, `src/feelies/execution/market_fill.py:237`) and root config sets `cost_stop_depth_depletion_factor: 2.0` (`platform.yaml:216`). This is conservative relative to a pure cross fill. The remaining gap is calibration: the 2x depth depletion is a chosen proxy, not fitted to live or cached stop-exit data.

### MOC fills

Implementation status: causal timing, modeling choice on price source.

MOC orders are rejected at/after cutoff (`src/feelies/execution/moc_fill.py:85`), wait until `official_close_ns` (`src/feelies/execution/moc_fill.py:134`), skip crossed/locked closing quotes (`src/feelies/execution/moc_fill.py:137`), and fill at the closing mid (`src/feelies/execution/moc_fill.py:205`). Root config adds a 3 bps MOC penalty (`platform.yaml:219`), but the model still does not consume official auction prints, imbalance feed, or close auction size. This is P2 unless a strategy depends materially on MOC execution.

## 4. Cost model & Inv-12 stress audit

### Cost decomposition

Implementation status: mostly conservative, with explicit attribution caveats.

`DefaultCostModel` includes taker spread cost/floor, IB-style commission, taker/maker exchange fees, maker adverse selection, sell regulatory fees, FINRA TAF, HTB borrow, and a stress multiplier (`src/feelies/execution/cost_model.py:83`, `src/feelies/execution/cost_model.py:214`). Variable costs are stressed while fixed floors/caps are not (`src/feelies/execution/cost_model.py:283`).

The major accounting convention is intentional: taker fills cross at the touch, so half-spread is embedded in fill price, not charged as a separate fee (`src/feelies/execution/market_fill.py:10`, `src/feelies/execution/market_fill.py:219`). This is economically correct for NAV, but it means `fees`/`cost_bps` on realized taker fills do not alone represent total execution cost. Any TCA report must reconstruct spread/impact from arrival mid or decision quote, not only from `ack.cost_bps`.

### Impact

Implementation status: improved, calibration still needed.

The aggressive fill helper applies a within-L1 participation premium and optional permanent sqrt premium (`src/feelies/execution/market_fill.py:140`). It then walks the excess over effective L1 depth with capped impact (`src/feelies/execution/market_fill.py:259`, `src/feelies/execution/market_fill.py:287`). The round-trip estimator mirrors the same knobs for gating and policy decisions (`src/feelies/execution/cost_model.py:459`, `src/feelies/execution/cost_model.py:570`).

Root `platform.yaml` enables temporary within-L1 impact at 0.3 (`platform.yaml:213`) but leaves permanent impact at 0.0 pending calibration (`platform.yaml:222`). This is not a code defect; it is a P2 data task because a blind permanent-impact coefficient can be worse than no coefficient.

### Inv-12 stress

Implementation status: mechanics wired, full APP stressed run not covered by requested checks.

`apply_inv12_stress` scales `cost_stress_multiplier` by 1.5 and doubles both `backtest_fill_latency_ns` and `market_data_latency_ns` (`src/feelies/core/inv12_stress.py:41`). CLI override uses that function when `--inv12-stress` is supplied (`src/feelies/harness/backtest_cli.py:94`). The selected acceptance command passed `test_inv12_stress_gate.py`, which covers the helper and a unit deferred-fill scenario, but it does not run APP/2026-03-26 under `--inv12-stress`.

The project now has a data-free synthetic PnL survival test (`tests/acceptance/test_inv12_pnl_survival.py:1`), but it was not part of the requested verification command. The remaining Inv-12 open question is data-backed survival for APP and other promoted alphas.

### Runtime edge gate

Finding: P1 config-risk modeling choice.

The runtime cost gate returns true if disabled or missing a cost model (`src/feelies/kernel/orchestrator.py:3117`), otherwise it computes round-trip cost from current BBO, depth, and impact knobs (`src/feelies/kernel/orchestrator.py:3119`, `src/feelies/kernel/orchestrator.py:3171`). This is the correct wiring. The issue is default policy: `PlatformConfig` default and root `platform.yaml` use 1.0 (`src/feelies/core/platform_config.py:308`, `platform.yaml:156`), while Inv-12 target is 1.5. Bootstrap warns but allows 1.0 (`src/feelies/bootstrap.py:260`). APP config overrides to 1.5 (`configs/bt_sig_benign_midcap.yaml:21`).

Recommendation: make root `platform.yaml` 1.5, or require an explicit `research_cost_gate_relaxed: true` style opt-out for 1.0.

## 5. Latency injection audit

Market-data latency and fill latency are distinct in config defaults: 20 ms for feed and 50 ms for fill (`src/feelies/core/platform_config.py:35`, `src/feelies/core/platform_config.py:37`). Root `platform.yaml` pins those same values (`platform.yaml:115`, `platform.yaml:116`). Bootstrap threads both into backend construction (`src/feelies/bootstrap.py:475`, `src/feelies/bootstrap.py:479`), and `_create_backend` passes them into market or passive backtest builders (`src/feelies/bootstrap.py:997`, `src/feelies/bootstrap.py:1022`).

The builder signatures still default both latency legs to zero (`src/feelies/execution/backtest_backend.py:68`, `src/feelies/execution/backtest_backend.py:76`, `src/feelies/execution/backtest_backend.py:134`, `src/feelies/execution/backtest_backend.py:148`) but now warn on zero (`src/feelies/execution/backtest_backend.py:30`). That is acceptable for tests/ad-hoc construction if warnings are visible. Production bootstrap passes non-zero config values.

Audit result:

- Market/aggressive fills: causal and covered.
- Passive resting fills: not causal with respect to order-placement latency; P0 bug as described in section 3.
- Stress: both latency legs scale under Inv-12 (`src/feelies/core/inv12_stress.py:49`, `src/feelies/core/inv12_stress.py:52`).

## 6. Tick-size & regulatory audit

Tick-size status: covered and conservative. Prices at or above $1 use penny ticks, below $1 use subpenny ticks (`src/feelies/execution/tick_size.py:27`). Taker fills round against the trader (`src/feelies/execution/tick_size.py:34`), and passive limit prices round on the passive side (`src/feelies/execution/tick_size.py:41`). The requested BT-14 acceptance slice passed.

Borrow status: implementation supports available/hard/unavailable tiers and blocks unavailable shorts through the higher-level gates, but omitted symbols default to available (`src/feelies/execution/regulatory/borrow_availability.py:5`). Root config has an empty borrow table and HTB fee 0 (`platform.yaml:73`, `platform.yaml:177`). For a short-capable strategy, this is optimistic unless the universe is genuinely easy-to-borrow. Severity P1 for non-large-cap short research, P2 for large-cap-only runs.

PDT status: intentional locked account-tier design. The code documents `margin_25k` only and no cash/T+2 branch (`src/feelies/execution/regulatory/pdt_constraint.py:3`). The constraint records round trips (`src/feelies/execution/regulatory/pdt_constraint.py:102`) and suppresses entries only when flagged and below the equity floor (`src/feelies/execution/regulatory/pdt_constraint.py:162`). Bootstrap refuses unimplemented account types (`src/feelies/bootstrap.py:397`).

RTH status: entries are suppressed outside RTH or on holidays; exits are permitted (`src/feelies/execution/trading_session.py:114`, `src/feelies/execution/trading_session.py:124`, `src/feelies/execution/trading_session.py:133`). The requested execution suite and BT-16 tests cover this path.

Ex-date status: detection, not adjustment. The acceptance test verifies raw-unadjusted policy docs and violation on replay spanning an ex-date (`tests/acceptance/test_bt18_ex_date_guard.py:35`, `tests/acceptance/test_bt18_ex_date_guard.py:42`). This is intentional for single-day raw L1 backtests; multi-day replay across corporate-action dates requires guard data.

## 7. Backtest/live parity audit

The seam is structurally correct: mode-specific execution lives behind `ExecutionBackend` and `OrderRouter` protocols (`src/feelies/execution/backend.py:82`, `src/feelies/execution/backend.py:55`). Both backtest routers share the aggressive fill helper (`src/feelies/execution/market_fill.py:3`). The orchestrator publishes the quote, drains router fills before evaluating signals, and keeps position state current (`src/feelies/kernel/orchestrator.py:2297`, `src/feelies/kernel/orchestrator.py:2347`, `src/feelies/kernel/orchestrator.py:2353`).

BT-11 now includes the market-fill ack hash in the parity manifest (`tests/determinism/parity_manifest.py:117`), closing the earlier gap where fill economics were not hashed. The selected BT-11 acceptance command passed.

Remaining parity limitation: live fills are broker-sourced, not literally produced by `DefaultCostModel` or `market_fill.py`. This is intentional architecture; parity is enforced through shared state machine semantics and TCA monitoring, not identical live/backtest fill functions.

## 8. Test gap matrix

| Property | Current evidence | Status | Gap / action |
|---|---|---|---|
| Market/aggressive no-lookahead | Router positive-latency tests (`tests/execution/test_router_latency.py:81`, `tests/execution/test_router_latency.py:162`) | Covered | None found. |
| Market-data visibility latency | BT-17 acceptance passed; defaults pinned (`src/feelies/core/platform_config.py:35`) | Covered | None found. |
| Passive posting latency | Resting-limit test uses `latency_ns=0` (`tests/execution/test_router_latency.py:180`, `tests/execution/test_router_latency.py:185`) | Missing | Add positive-latency passive post test that proves no fills before deadline. |
| Passive through partial fill | Enabled behavior tested (`tests/execution/test_execution_realism_knobs.py:215`) | Covered when knob on | Add config-level assertion that live-like configs keep knob on. |
| Passive level fill requires volume | Enabled behavior tested (`tests/execution/test_execution_realism_knobs.py:249`) | Covered when knob on | Add config-level assertion for live-like configs. |
| Aggressive within-L1 impact | Enabled and default-off tests (`tests/execution/test_execution_realism_knobs.py:73`) | Covered | Calibrate coefficient. |
| Permanent impact | Implemented default-off test (`tests/execution/test_execution_realism_knobs.py:114`) | Partial | Calibration run needed before enabling. |
| Golden fill replay | Manifest includes `market_fill_acks` (`tests/determinism/parity_manifest.py:117`) | Covered | Keep rebaseline workflow strict. |
| Inv-12 helper stress | Selected acceptance passed; helper scales both latencies (`src/feelies/core/inv12_stress.py:41`) | Covered | Include synthetic PnL survival in standard acceptance slice if desired. |
| Inv-12 data-backed APP survival | Not run by requested commands; APP baseline failed unstressed | Missing/blocked | Run APP baseline and `--inv12-stress` after cache/baseline reconciliation. |
| Tick rounding against trader | BT-14 selected acceptance passed; tick code conservative (`src/feelies/execution/tick_size.py:34`) | Covered | None found. |
| Borrow/HTB realism | Unit tests cover tiers; defaults available/0 (`src/feelies/execution/regulatory/borrow_availability.py:5`, `platform.yaml:177`) | Partial | Add short-universe config checks or HTB calibration. |
| MOC official close | MOC tests cover cutoff/close-mid mechanics; price source is proxy (`src/feelies/execution/moc_fill.py:205`) | Partial | Add official close/auction-print fixture when data exists. |
| Data-backed APP regression | Requested run failed against local cache | Failing | Reconcile cache provenance, expected constants, or trade-path change. |

## 9. Prioritized backlog

| Pri | Effort | Type | Component | Evidence | One-sentence fix | Expected PnL-realism impact |
|---|---|---|---|---|---|---|
| P0 | M | Implementation bug | Passive resting order latency | `src/feelies/execution/passive_limit_router.py:534`, `src/feelies/execution/passive_limit_router.py:573` | Defer passive order posting until exchange-time submit latency elapses; add positive-latency passive tests. | Reduces pre-eligibility passive fills and early price improvement in default `passive_limit` backtests. |
| P1 | S | Validation blocker | APP baseline drift | `tests/acceptance/test_backtest_app_baseline.py:125` | Re-run with pinned cache provenance; update constants only if trade-path or data change is intentional. | Restores trust in data-backed fill/PnL regression gate. |
| P1 | S | Config risk | Root runtime cost gate below Inv-12 | `platform.yaml:156`, `src/feelies/bootstrap.py:260` | Set root/default gate to 1.5 or require explicit research opt-out for 1.0. | Prevents default backtests from trading edges that do not clear Inv-12 target margin. |
| P1 | M | Modeling choice | Borrow/HTB defaults optimistic | `src/feelies/execution/regulatory/borrow_availability.py:5`, `platform.yaml:177` | Require a borrow table or conservative `borrow_default_tier` for short-enabled configs; calibrate HTB fees. | Prevents free/always-available shorting in midcap or HTB-prone universes. |
| P1 | S | Test/config gap | Live-like realism knobs can be off outside root config | `src/feelies/core/platform_config.py:456`, `src/feelies/core/platform_config.py:461` | Add a validation helper/profile check for production backtests requiring through cap, trade-required level fills, and non-zero within-L1 impact. | Avoids accidental optimistic configs that bypass the reference profile. |
| P2 | M | Modeling choice | MOC official close proxy | `src/feelies/execution/moc_fill.py:205`, `platform.yaml:219` | Use official auction close prints/imbalance data when available; keep penalty fallback. | Improves MOC PnL realism for auction-dependent strategies. |
| P2 | M | Calibration gap | Permanent impact disabled | `src/feelies/execution/market_fill.py:146`, `platform.yaml:222` | Estimate permanent impact coefficient from cached fills/live TCA before enabling. | Better cost for larger orders without blind over-penalization. |
| P2 | S | Observability gap | Taker spread embedded in fill price | `src/feelies/execution/market_fill.py:10`, `src/feelies/execution/market_fill.py:331` | Add TCA columns for arrival-mid spread/impact cost independent of `fees`. | Prevents under-reading transaction cost from `ack.cost_bps` alone. |

## 10. Appendix: open questions needing data runs

1. Why did APP/2026-03-26 produce 4 fills and $52.54 net PnL in this workspace when the pinned baseline expects 6 fills and $69.06 (`tests/acceptance/test_backtest_app_baseline.py:125`)? Determine whether the disk cache, config snapshot, or trade path changed.
2. After the APP baseline is reconciled, run the same cached day with and without `--inv12-stress` to measure actual PnL compression from 1.5x cost and 2x latency (`src/feelies/harness/backtest_cli.py:147`).
3. Quantify passive-posting-latency impact: on cached APP and at least one higher quote-rate symbol, count fills that occur within 50 ms of passive submit and would disappear after the P0 fix.
4. Calibrate `cost_within_l1_impact_factor` and `cost_permanent_impact_coefficient` from cached/live TCA; root config currently uses 0.3 and 0.0 respectively (`platform.yaml:213`, `platform.yaml:222`).
5. For all short-enabled alphas, list symbols absent from `borrow_availability` and estimate realistic HTB/locate availability; omitted symbols currently default to available (`src/feelies/execution/regulatory/borrow_availability.py:5`).
6. For MOC strategies, compare the close-mid proxy plus 3 bps penalty to official auction prints and imbalance sizes on cached sessions (`src/feelies/execution/moc_fill.py:205`, `platform.yaml:219`).
