# Execution Fills Audit 2026-07-02

Scope: read-only audit of `OrderRequest -> ExecutionBackend -> router -> fill model ->
tick/regulatory -> Trade/PnL` in backtest simulation, per
`docs/prompts/audit_execution_fills.md`. No production code, baselines, configs, or
ledgers were modified. This is a follow-up to `execution_fills_audit_2026-06-20.md`
(and `2026-06-19.md`); findings below are re-verified against the current tree, not
assumed carried over.

Legend: **implementation bug** = code violates the intended execution contract;
**modeling choice** = deliberate approximation that may be optimistic;
**intentional design** = documented tradeoff, internally consistent.

**Verification run (this session, `PYTHONHASHSEED=0`):**

- `uv run pytest tests/execution/ -q` → **663 passed**.
- `uv run pytest tests/acceptance/test_bt11_parity_post_fill_model.py tests/acceptance/test_bt14_tick_rounding.py tests/acceptance/test_bt17_market_data_latency.py tests/acceptance/test_inv12_stress_gate.py -q` → **27 passed**.
- `uv run pytest tests/acceptance/test_backtest_app_baseline.py -q -rs` → **1 passed, 1 skipped**. The data-backed `test_app_20260326_backtest_baseline_from_disk_cache` skipped: no disk cache present at `~/.feelies/cache` in this workspace and no `MASSIVE_API_KEY` (`tests/acceptance/test_backtest_app_baseline.py:179`). The data-free `test_app_baseline_config_contract_hash` passed. **This is an environment limitation, not a code finding** — unlike the 2026-06-20 run (which executed against a populated cache and found a PnL/fill-count drift), this session cannot confirm or refute the currently pinned baseline (`_BASELINE_NET_PNL = 430.85`, `_BASELINE_FILL_COUNT = 21`, re-baked 2026-06-29 per `tests/acceptance/test_backtest_app_baseline.py:104-111`). See Appendix item 1.

## 1. Executive summary

1. **The prior P0 (passive resting-order latency) is fixed and now regression-tested.** Commits `b923201` and `bca1efd` (2026-07-01) make `_post_passive` compute `ack_timestamp_ns = max(clock.now_ns(), quote.exchange_timestamp_ns) + latency_ns` (`src/feelies/execution/passive_limit_router.py:540`), gate `_check_resting_orders` on it (`passive_limit_router.py:589-593`), and gate `on_trade` queue accumulation on the same timestamp (`passive_limit_router.py:290-291`) so pre-eligibility trades can't drain the queue early. Both a through-fill and a drain-fill positive-latency regression test now exist (`tests/execution/test_router_latency.py:210-248`, `tests/execution/test_passive_limit_router.py:995-1021`). **No open P0 found in this pass** — see §3.
2. **No fill lookahead found (Inv-6 holds).** `ReplayFeed.events()` advances the clock to `exchange_timestamp_ns + market_data_latency_ns` *before* yielding each quote (`src/feelies/ingestion/replay_feed.py:100-108`) and raises `CausalityViolation` if events arrive out of merge-sort order (`replay_feed.py:89-98`). Both routers price fills off the quote current at fill sim-time, never a future one; deferred (`latency_ns > 0`) fills wait for the first quote at/after the exchange-time deadline (`backtest_router.py:312-361`; `passive_limit_router.py:415-487`). **[design]**
3. **New P2: passive THROUGH/DRAIN fill acks double-count `latency_ns` in their timestamp** (not price). `_emit_passive_fill` sets `fill_ts = self._clock.now_ns() + self._latency_ns` (`passive_limit_router.py:924`) on top of a resting order whose `ack_timestamp_ns` already embeds one full `latency_ns` (`passive_limit_router.py:540`). Every other fill-timestamp site in both routers pays `latency_ns` exactly once (`backtest_router.py:296`, `:359`; `passive_limit_router.py:485`). The bias is timestamp-only and conservative (fills are reported *later*, never earlier, so this cannot manufacture lookahead or inflate PnL) but skews passive-fill latency telemetry by a full `latency_ns` (50ms default) relative to aggressive fills. **[implementation bug, low severity]**
4. **The root runtime cost gate is still below the Inv-12 target.** `platform.yaml:156` sets `signal_min_edge_cost_ratio: 1.0` against Inv-12's 1.5; `bootstrap.py:259-261` only warns for `1.0 <= ratio < 1.5`. Unchanged since 2026-06-20. **[config risk]**
5. **Short-side costs remain optimistic by default.** Omitted symbols resolve to `BorrowTier.AVAILABLE` via `self._borrow_default_tier` (`kernel/orchestrator.py:838`, `:6492-6494`), root `platform.yaml:91` ships an empty `borrow_availability: {}`, and `cost_htb_borrow_annual_bps: 0.0` (`platform.yaml:177`). A `borrow_default_tier` config knob now exists (`platform_config.py:465`) but is unset in every shipped config — the escape hatch exists, unused. **[modeling choice]** — unchanged in substance since 2026-06-20.
6. **Live-like passive realism still depends entirely on `platform.yaml` overriding optimistic code defaults, with no guard rail.** `passive_through_fill_size_cap_enabled`, `passive_require_trade_for_level_fill`, and `cost_within_l1_impact_factor` all default off/zero in `PlatformConfig` (`platform_config.py:438,456,461`) and are flipped on only by the root YAML (`platform.yaml:206,210,213`). No validation helper asserts a "production" config carries these; this was recommended in the 2026-06-20 backlog (#5) and remains unimplemented. **[test/config gap]**
7. **The Inv-12 latency-doubling acceptance test exercises the non-default router.** `test_router_deferred_fill_uses_doubled_latency` (`tests/acceptance/test_inv12_stress_gate.py:85-169`) only constructs a `BacktestOrderRouter` (`execution_mode: market`); root `platform.yaml:185` runs `execution_mode: passive_limit`. There is no acceptance-level proof that `--inv12-stress` doubles latency correctly through `PassiveLimitOrderRouter`'s two latency-gated paths (aggressive-fallback deferral and passive order-entry deferral). **[test gap]** — new finding, not raised in prior passes.
8. **Impact modeling has closed the "zero impact within L1" gap, but permanent impact remains uncalibrated at zero.** `base_impact_premium` charges a temporary participation premium plus an optional permanent sqrt term on the within-L1 leg (`market_fill.py:140-172`); root config enables the temporary term (`cost_within_l1_impact_factor: 0.3`, `platform.yaml:213`) but `cost_permanent_impact_coefficient: 0.0` (`platform.yaml:222`). **[calibration gap, P2]** — unchanged since 2026-06-19.
9. **MOC fills remain causal but use a close-mid proxy, not an official auction print.** `MocFillController` waits for `official_close_ns` and skips crossed/locked closing quotes (`moc_fill.py:134-144`) but fills at `(quote.bid + quote.ask) / 2` (`moc_fill.py:206`) plus a flat `cost_moc_penalty_bps: 3.0` (`platform.yaml:219`, applied at `moc_fill.py:220-223`). **[modeling choice, P2]** — unchanged.
10. **Tick rounding is still conservative in both directions and stop slippage still widens spread + depletes depth for forced exits** — `tick_size.py:34-45` (taker rounds against the trader, passive rounds to a valid resting tick, never invented price improvement); `market_fill.py:226-239` (stop/hazard/force-flatten fills pay `stop_slippage_half_spreads` extra half-spread and see effective L1 depth shrunk by `stop_depth_depletion_factor`). No rounding-in-the-strategy's-favor path found. **[design]**
11. **A realized-cost-overrun kill-switch escalation now exists but is off everywhere and untested at unit/backtest-router level.** `orchestrator.py:5773-5814` escalates to `KillSwitch.activate(reason="realized_cost_persistent_overrun")` after `realized_cost_escalation_streak` consecutive G12-cost-exceeding fills, but `realized_cost_escalation_enabled` defaults `False` (`platform_config.py:470`) and is unset in `platform.yaml` and `configs/bt_app.yaml`. Only a `paper_rth`-gated integration test (`tests/integration/test_paper_rth_safety.py`) touches it. Partially closes the 2026-06-20 "observability-only" note but doesn't change default backtest behavior. **[design, P2]** — new observation.
12. **Backtest/live parity at the seam is structurally sound; the golden `market_fill` replay gap is closed.** Both routers implement the shared `OrderRouter` protocol (`backend.py:55-79`) and delegate to the single `append_market_fill_acks` chokepoint (`market_fill.py:184-354`); the parity manifest includes `market_fill_acks` and BT-11 re-verified it this session (27/27 passed). `market_fill.py` still has no dedicated unit-test module — coverage is embedded in `test_backtest_router.py`, `test_passive_limit_router.py`, `test_router_latency.py`, and `tests/determinism/test_market_fill_replay.py`. **[test-organization note]**
13. **Cost accounting convention is unchanged and still a TCA foot-gun if misread.** Taker fills embed the half-spread in `avg_entry_price` (cross price), not in `fees` (`market_fill.py:8-24`, `cost_model.py:267-281` calls with `half_spread=0` on the taker leg since the router always passes `fee_half_spread=0` except for stop exits). NAV is invariant; a consumer reading `fees`/`cost_bps` alone as "total transaction cost" understates round-trip cost for normal taker fills. **[design]** — unchanged.
14. **The `on_trade` pre-eligibility fix (`bca1efd`) has no dedicated regression test.** The 6-line change gating `shares_traded_at_level` accumulation on `trade.exchange_timestamp_ns >= pending.ack_timestamp_ns` (`passive_limit_router.py:286-291`) shipped without a new test exercising a trade that prints between order submission and eligibility. **[test gap, P2]** — new finding.
15. **Regulatory/session gates are unchanged and sound**: RTH entry suppression with exits always permitted (`trading_session.py:114-135`), PDT round-trip counter + $25k floor for `margin_25k` only (`pdt_constraint.py:162-179`), ex-date detection (not adjustment) for single-day raw replay (`tests/acceptance/test_bt18_ex_date_guard.py`). **[design]**

## 2. Execution inventory

| Component | Role | Realism notes |
|---|---|---|
| `ExecutionBackend` / `OrderRouter` | Mode seam and order contract | `submit`/`poll_acks` protocol; backtest is the only implementation in scope (`src/feelies/execution/backend.py:55-79`, `:82-99`). |
| `ReplayFeed` | Backtest market-data visibility | Advances `SimulatedClock` to `exchange_ts + market_data_latency_ns` before yielding; causality-guarded (`src/feelies/ingestion/replay_feed.py:68-108`). |
| `BacktestOrderRouter` | Market/aggressive backtest fills (`execution_mode: market`) | ACK-then-fill; zero-latency fast path or exchange-time-deferred fill; MOC delegated to `MocFillController` (`src/feelies/execution/backtest_router.py:118-438`). |
| `PassiveLimitOrderRouter` | Passive queue + aggressive-fallback fills (`execution_mode: passive_limit`, `minimum_cost`) | Through/drain fill model with a seeded-Bernoulli level-fill hazard; order-entry latency now gates both quote and trade evaluation (`src/feelies/execution/passive_limit_router.py:138-1081`). |
| `market_fill.py` | Shared aggressive fill economics (both routers) | Cross-price taker model + D14 partial fill + within-L1/permanent impact premium (`src/feelies/execution/market_fill.py:1-354`). |
| `moc_fill.py` / `moc_session.py` | MOC close fill controller | Causal close timing (waits for `official_close_ns`), close-mid proxy + flat penalty (`src/feelies/execution/moc_fill.py:1-238`, `moc_session.py:1-134`). |
| `DefaultCostModel` | Fees, adverse selection, spread floor, HTB | Taker/maker split, through- vs drain-fill adverse selection, sell-side regulatory + FINRA TAF + HTB, stress multiplier on variable costs only (`src/feelies/execution/cost_model.py:196-406`). |
| `estimate_round_trip_cost_bps` / `estimate_aggressive_taker_cost_bps` | Runtime edge-vs-cost (B4) gate + minimum-cost policy pricing | Depth-aware when book sizes supplied, mirrors router impact knobs (`cost_model.py:459-697`). |
| `MinimumCostExecutionPolicy` | Per-order passive-vs-aggressive routing decision | Pure function of cost model + config; opportunity-cost-of-non-fill penalty on the passive leg (`src/feelies/execution/min_cost_policy.py:106-256`). |
| `tick_size.py` | Reg-NMS tick grid | Taker rounds against the trader; passive rounds to a valid resting tick (`src/feelies/execution/tick_size.py:27-51`). |
| `trading_session.py` | RTH session gate | Entries suppressed outside RTH/holidays; exits always permitted (`src/feelies/execution/trading_session.py:114-193`). |
| `regulatory/borrow_availability.py`, `regulatory/pdt_constraint.py` | Locate + PDT gates | Static per-symbol tier with configurable default; rolling round-trip counter + $25k floor (`borrow_availability.py:1-76`, `pdt_constraint.py:1-217`). |
| `core/inv12_stress.py` | Cost/latency stress harness | Pure `dataclasses.replace`; scales `cost_stress_multiplier` ×1.5 and both latency legs ×2 (`src/feelies/core/inv12_stress.py:41-55`). Touchpoint only — owned by `audit_core_clock_config.md`. |
| `order_state.py` | Order lifecycle SM | 9-state, shared by backtest and live (`src/feelies/execution/order_state.py:19-94`). |

## 3. Fill realism & lookahead audit

### 3.1 Market/aggressive fill trace (Inv-6)

**Implementation status: intentional design, causal — re-confirmed.**

The feed side is causal: `ReplayFeed.events()` sets `SimulatedClock` to `market_data_visible_at_ns(exchange_ts, market_data_latency_ns)` strictly before yielding the event (`replay_feed.py:100-107`), so no downstream sensor, signal, or router can see a quote before its feed-propagation delay has elapsed. `ReplayFeed` also raises `CausalityViolation` if the underlying `EventLog` yields events out of `event_merge_sort_key` order (`replay_feed.py:89-98`).

On the order side, `BacktestOrderRouter.submit()` acknowledges immediately, then either fills inline against the *current* last-seen quote when `latency_ns <= 0` (`backtest_router.py:286-297`) or enqueues a `DeferredFill` with `fill_deadline_exchange_ns = max(clock.now_ns(), quote.exchange_timestamp_ns) + latency_ns` (`backtest_router.py:298-310`). `_flush_deferred_market_fills` only fills once a later quote's `exchange_timestamp_ns >= fill_deadline_exchange_ns` (`backtest_router.py:325-360`) — the fill price comes from *that* qualifying quote, never the submission-time quote. `PassiveLimitOrderRouter._submit_aggressive_market` / `_flush_deferred_aggressive` mirror this exactly (`passive_limit_router.py:367-487`), including a same-mode BBO-adverse-move re-check on marketable limits routed through the aggressive path (`passive_limit_router.py:467-479`).

At `latency_ns = 0` (test/ad-hoc wiring only — production `platform.yaml:116-117` sets 50ms/20ms), a fill *does* price off the same quote that triggered the order in the same tick. This is not lookahead (the strategy already had access to that quote's data), but it is a zero-round-trip idealization; `build_backtest_backend` / `build_passive_limit_backend` now warn on it (`backtest_backend.py:30-58`). Unchanged since 2026-06-19/20.

### 3.2 Passive resting-order latency — P0 CLOSED, re-verified

**Implementation status: fixed (was implementation bug; now intentional design, causal).**

The 2026-06-20 P0 ("passive limit orders are posted immediately despite positive `backtest_fill_latency_ns`, and become fill-eligible on the very next quote") is fixed by two same-day commits (`b923201`, `bca1efd`, both 2026-07-01):

1. `_post_passive` now computes `ack_ts = max(self._clock.now_ns(), quote.exchange_timestamp_ns) + self._latency_ns` (`passive_limit_router.py:540`) — identical shape to the aggressive path's `ack_ts` (`passive_limit_router.py:377`).
2. `_check_resting_orders` skips fill evaluation entirely for any quote whose `exchange_timestamp_ns < pending.ack_timestamp_ns` (`passive_limit_router.py:589-593`) — this gates *both* the guaranteed "through" fill and the probabilistic "drain" fill (`_evaluate_fill` is only reached after the gate).
3. `on_trade` — which feeds `shares_traded_at_level` for the queue-depth and volume-gated hazard regimes — independently checks `trade.exchange_timestamp_ns < pending.ack_timestamp_ns` and skips accumulation (`passive_limit_router.py:290-291`). Without this second gate, a pre-eligibility trade print could still satisfy the queue-drain threshold or the `require_trade_for_level_fill` volume gate before the order was actually resting, so the first *eligible* quote would drain-fill immediately — the same bug via a different code path. This closes that.

Both fill triggers are now covered by positive-latency regression tests: `test_resting_limit_through_fill_deferred_until_latency_eligible` (`tests/execution/test_router_latency.py:210-248`) proves a crossing quote inside the latency window does *not* fill, and `test_passive_fill_latency` (`tests/execution/test_passive_limit_router.py:995-1021`) proves the ack timestamp reflects the full latency window. The `on_trade` gate (§3.2 item 3 / commit `bca1efd`) has no analogous dedicated test — see §8 gap matrix and finding #14.

### 3.3 New: passive fill-ack timestamp double-counts latency (timestamp only, not price)

**Implementation status: implementation bug, low severity — new finding.**

`_emit_passive_fill`, which stamps the FILLED/PARTIALLY_FILLED ack for both through- and drain-fills, computes:

```python
fill_ts = self._clock.now_ns() + self._latency_ns   # passive_limit_router.py:924
```

At the point this executes, `self._clock.now_ns()` is already the market-data-latency-adjusted visibility time of the *triggering* quote, and the resting order's `ack_timestamp_ns` (which gated fill eligibility per §3.2) already embeds one full `latency_ns` order-entry leg. Adding `self._latency_ns` again here charges a second order-entry-latency round trip to report a fill on an order that is already resting live at the exchange. Contrast with every other fill-timestamp computation in both routers, which pay `latency_ns` exactly once:

- `backtest_router.py:296` (`fill_ts = ack_ts`, immediate path) and `:359` (`fill_ts = max(self._clock.now_ns(), dm.ack_timestamp_ns)`, deferred path — no addition).
- `passive_limit_router.py:485` (`fill_ts = max(self._clock.now_ns(), dm.ack_timestamp_ns)`, deferred aggressive path — no addition).
- `passive_limit_router.py:979` (`cancel_ts = max(self._clock.now_ns(), pending.ack_timestamp_ns)`, timeout/explicit cancel — no addition).

Only the passive THROUGH/DRAIN fill path adds a second `latency_ns`. Because the bias only *delays* the reported fill timestamp (never advances it), it cannot manufacture lookahead and does not touch fill price, cost, or PnL — NAV and the parity hashes are unaffected. The practical effect is on anything that measures fill *timing*: a passive fill's ack timestamp is `latency_ns` (50ms default) later than the exchange-time instant it actually happened, so signal-to-fill / ack-to-fill latency telemetry (the kind of metric the live-execution skill's real-time monitoring reads) would read passive fills as systematically slower than they are, by a fixed offset not present on aggressive fills. Minimal fix: `fill_ts = max(self._clock.now_ns(), pending.ack_timestamp_ns)`, matching the pattern used everywhere else.

### 3.4 Passive queue and partial fills

**Implementation status: mixed — conservative in the reference profile, code defaults remain optimistic-neutral. Unchanged since 2026-06-20.**

Through-fills are capped at the crossing quote's opposite-side size only when `through_fill_size_cap_enabled` (`passive_limit_router.py:634-639`); level (drain) fills use a seeded-Bernoulli per-tick hazard (`_fill_hazard`, `passive_limit_router.py:734-791`) that is zero until `shares_traded_at_level` clears `queue_ahead_shares` in the queue-depth regime, or requires at least one trade print when `require_trade_for_level_fill` is set in the quote-imbalance regime (`passive_limit_router.py:765-775`). All three knobs default off/zero in `PlatformConfig` (`platform_config.py:278,456,461`) and are enabled only by root `platform.yaml:189,206,210`. The Bernoulli draw is deterministic and replay-safe: `_seeded_uniform` hashes replay-stable quote/order keys with SHA-256, no RNG (`passive_limit_router.py:793-814`).

### 3.5 Stop and forced-exit slippage

**Implementation status: intentional design, calibration gap. Unchanged since 2026-06-20.**

`STOP_EXIT_REASONS = {"STOP_EXIT", "HARD_EXIT_AGE", "HAZARD_SPIKE", "FORCE_FLATTEN"}` (`_fill_helpers.py:11-18`) triggers extra spread cost (`stop_slippage_half_spreads`, `market_fill.py:226-230`) and shrinks the effective L1 depth the fill walks against (`stop_depth_depletion_factor`, `market_fill.py:232-239`) in `append_market_fill_acks` — the single chokepoint both routers call, so the treatment is identical for market-mode stops and passive-mode aggressive-fallback stops (`test_stop_slippage.py:58-159` exercises both). Root config sets `cost_stop_depth_depletion_factor: 2.0` (`platform.yaml:216`); the multiplier itself is a chosen proxy, not fit to cached or live stop-exit data.

### 3.6 MOC fills

**Implementation status: causal timing, modeling choice on price source. Unchanged since 2026-06-20.**

`MocFillController.submit` rejects at/after `moc_cutoff_ns` (`moc_fill.py:85-94`) and cross-day submits (`moc_fill.py:74-83`); `on_quote` only fills once `quote.exchange_timestamp_ns >= official_close_ns` and skips a crossed/locked closing tick rather than fill on it (`moc_fill.py:134-144`), with `expire_unfilled` as the session-end backstop when no clean post-close quote ever arrives (`moc_fill.py:178-197`; wired from both routers' `expire_pending_moc`, `backtest_router.py:407-419`, `passive_limit_router.py:1042-1054`). The fill itself is the closing NBBO mid, not an official auction print or imbalance-informed price (`moc_fill.py:206`), with a flat `cost_moc_penalty_bps` layered on top as a size-agnostic proxy for auction pressure (`moc_fill.py:220-223`; `platform.yaml:219` sets 3.0 bps). `tests/integration/test_moc_imbalance_e2e.py` exercises the wider MOC-imbalance alpha pipeline end-to-end but not official-auction-print realism, which isn't in scope for an L1-only feed.

## 4. Cost model & Inv-12 stress audit

### 4.1 Cost decomposition

**Implementation status: mostly conservative, unchanged in substance since 2026-06-20.**

`DefaultCostModel.compute` (`cost_model.py:214-406`) itemizes spread cost (taker-only by default via `spread_floor_taker_only`, `cost_model.py:267-281`), IB-Tiered commission with an IBKR-accurate floor/cap ordering (`cost_model.py:283-330`), maker adverse selection split by through- vs drain-fill regime (`cost_model.py:332-360`), sell-side SEC + FINRA TAF (`cost_model.py:362-375`), and HTB borrow cost gated on `is_short` (`cost_model.py:377-393`). `stress_multiplier` scales variable costs only; fixed broker floors (`min_commission`, `max_commission_pct`, `finra_taf_max_per_order`) and the maker rebate are deliberately not stressed (`cost_model.py:129-133` docstring, enforced at each call site). The half-spread-embedded-in-price convention (§ executive summary #13) is unchanged and correctly NAV-neutral, just an attribution foot-gun for naive TCA.

### 4.2 Cost-arithmetic reconciliation (structural check)

The load-time G12 gate consumes each SIGNAL alpha's static `cost_arithmetic` block — e.g. `alphas/sig_benign_midcap_v1/sig_benign_midcap_v1.alpha.yaml:141-149` discloses `edge_estimate_bps: 9.0`, one-way `half_spread_bps: 2.0` + `impact_bps: 2.0` + `fee_bps: 1.0`, `margin_ratio: 1.8`, `cost_basis: one_way` (round-trip ≈10.0 bps per the file's own comment, edge/round-trip ≈0.90). The runtime B4 gate independently recomputes round-trip cost from the *live* `DefaultCostModel` and current quote via `round_trip_cost_bps` (`orchestrator.py:3167-3199, 3201-3230`), gated at `signal_min_edge_cost_ratio`. These are structurally consistent (same cost components, same impact knobs when depth is supplied) but are two independent estimates of the same quantity — the disclosed value is static per-alpha metadata, the runtime value is dynamic and config-driven. Numeric reconciliation on real fills requires a data run; see Appendix item 2 (also offered as an optional follow-up in the audit prompt).

### 4.3 Inv-12 stress

**Implementation status: mechanics wired and re-verified; one router untested under the acceptance gate — see finding #7.**

`apply_inv12_stress` scales `cost_stress_multiplier` by 1.5 and both `backtest_fill_latency_ns` and `market_data_latency_ns` by 2 via `stressed_fill_latency_ns`/`stressed_cost_multiplier` (`inv12_stress.py:29-55`); `--inv12-stress` applies it in the CLI path (owned by `audit_core_clock_config.md`, touchpoint only here). This session's acceptance run (27/27 passed) included `test_router_deferred_fill_uses_doubled_latency`, which constructs a bare `BacktestOrderRouter` and proves an intermediate quote at the *unstressed* deadline does not fill while the quote at the *doubled* deadline does (`tests/acceptance/test_inv12_stress_gate.py:85-169`). This is solid proof for `execution_mode: market`, but root `platform.yaml:185` runs `execution_mode: passive_limit`, and no acceptance test constructs a `PassiveLimitOrderRouter` under stressed latency to prove the same property for either its aggressive-fallback deferral or its order-entry-gated passive-post deferral (§3.2). `tests/acceptance/test_inv12_pnl_survival.py` separately proves a known +$0.50/share edge survives 1.5× cost stress through the *aggressive* path (`test_inv12_pnl_survival.py:92-101`), again not through the passive router. The full data-backed APP survival run under `--inv12-stress` remains a data/operator task (Appendix item 1).

## 5. Latency injection audit

**Market-data vs fill latency: distinct, correctly wired, re-verified.**

`market_data_latency_ns` (feed propagation) and `backtest_fill_latency_ns` (order-entry/fill) are separate `PlatformConfig` fields defaulting to 20ms/50ms (`platform_config.py:36-37`, `DEFAULT_MARKET_DATA_LATENCY_NS` / `DEFAULT_BACKTEST_FILL_LATENCY_NS`), pinned identically in root `platform.yaml:116-117`, and independently re-verified this session by `tests/acceptance/test_bt17_market_data_latency.py` (locked defaults, `latency_stress_ns` doubling both legs, and two feed-visibility tests proving the clock reaches `exchange_ts + md_latency` and never a later quote's visibility early). Bootstrap threads both into backend construction (`bootstrap.py:481-482`) and `_create_backend` passes them into the market or passive-limit builder (`bootstrap.py:1003-1004, 1028-1029`). Builder function signatures still default both to `0` (`backtest_backend.py:68,76,134,148`) but now warn when either is non-positive (`backtest_backend.py:30-58`), addressing the 2026-06-19 P1 finding. Production bootstrap always passes the non-zero config values, so this only matters for direct/ad-hoc router construction (tests, scripts).

Audit result, re-confirmed:

- Market/aggressive fills: causal, covered by both unit and acceptance tests.
- Passive resting fills: **now causal** (§3.2) — the 2026-06-20 P0 is closed.
- Stress: both latency legs scale under Inv-12, proven for the market router; not proven for the passive router (§4.3, finding #7).

## 6. Tick-size & regulatory audit

**Tick-size: covered and conservative, unchanged.** `tick_size()` uses penny ticks at/above $1, sub-penny below (`tick_size.py:27-31`); `snap_fill_price` rounds taker fills against the trader — BUY ceils, SELL floors (`tick_size.py:34-38`); `snap_limit_price` rounds resting limits to a valid passive-side tick — BUY floors, SELL ceils (`tick_size.py:41-45`). BT-14 acceptance (`test_bt14_tick_rounding.py`) re-verified both the walk-the-book impact leg and passive-post snapping this session (27/27 passed overall). No rounding-in-the-strategy's-favor path found in either router.

**Borrow: unchanged.** `build_borrow_table` normalizes a `{symbol: tier}` config map (`borrow_availability.py:45-53`); omitted symbols resolve through `self._borrow_tier_for` to `self._borrow_default_tier`, which now defaults from a config field (`platform_config.py:465`, default `"available"`) rather than being hardcoded, but every shipped config (`platform.yaml`, `configs/bt_app.yaml`) leaves it unset, so the effective default is still `available` (no HTB, shortable) everywhere. `_borrow_blocks_intent` correctly refuses short sales when the tier is `UNAVAILABLE` (`orchestrator.py:6496-6500`), and `htb_fee_applies` only flags HTB cost for the `HARD` tier (`borrow_availability.py:74-76`) — the mechanism is sound, the *data* (empty table, HTB fee 0) is optimistic for anything but a large-cap easy-to-borrow universe. Severity unchanged: P1 for non-large-cap or HTB-prone short research.

**PDT: unchanged, intentional design.** Only `AccountType.MARGIN_25K` is implemented; `should_suppress_entry` blocks new day-trade entries only when PDT-flagged *and* equity has dropped below `min_equity` (`pdt_constraint.py:162-179`); the round-trip counter and pruning are pure functions of fill timestamps via `ZoneInfo("America/New_York")`, no wall clock (`pdt_constraint.py:100-217`).

**RTH: unchanged.** Entries suppressed pre-open, during the configurable `no_entry_first_seconds` warm-up window, at/after close, and on market holidays; exits always pass (`trading_session.py:114-135`, `RthEntryFillGate.should_suppress` at `:173-193`). BT-16 acceptance covers router-level entry rejection with position-qty binding, buying-power-mode flip at close, and early-close MOC cutoff shift.

**Ex-date: unchanged, intentional design for single-day raw replay.** `test_bt18_ex_date_guard.py` verifies detection-not-adjustment policy and that a replay spanning an ex-date without adjustment produces a flagged violation — appropriate for the platform's raw-unadjusted, single-session backtest model; multi-day replay across corporate actions would need adjustment data this module doesn't attempt to source.

## 7. Backtest/live parity audit

**Implementation status: structurally sound at the seam; the golden-replay gap noted in 2026-06-19 remains closed.**

Both `BacktestOrderRouter` and `PassiveLimitOrderRouter` implement the same `OrderRouter` protocol (`backend.py:55-79`) and delegate every aggressive fill to the single `append_market_fill_acks` chokepoint in `market_fill.py`, so the two paths cannot silently diverge on latency, D14 partial-fill, or impact semantics (`market_fill.py:1-28` docstring states this explicitly as the reason the module exists). `DeferredFill` is likewise a single shared dataclass (`market_fill.py:44-70`), aliased in both routers rather than duplicated. The parity manifest's `market_fill_acks` baseline (owned by `tests/determinism/test_market_fill_replay.py`) was re-verified this session via the BT-11 acceptance wrapper (27/27 passed) — `test_locked_parity_baseline_matches_replay_after_fill_model_changes` iterates every entry in `parity_manifest.LOCKED_PARITY_BASELINES` and fails loudly with a rebaseline pointer on drift (`test_bt11_parity_post_fill_model.py:23-38`).

`market_fill.py` still has no dedicated `test_market_fill.py` — coverage is embedded in `test_backtest_router.py`, `test_passive_limit_router.py`, `test_router_latency.py`, and the determinism golden replay. This is a test-organization note, not a coverage gap in substance (the function is exercised extensively by proxy), but a targeted regression in `append_market_fill_acks` would surface as failures scattered across three unrelated-looking test files rather than one obvious one.

Remaining parity limitation, unchanged: PAPER/LIVE fills are broker-sourced (out of scope — `audit_live_execution.md`), so sim-vs-live cost/fill parity is monitored via the live-execution skill's drift metrics, not guaranteed by code sharing beyond the `OrderRouter` protocol shape itself.

## 8. Test gap matrix

| Property | Current evidence | Status | Gap / action |
|---|---|---|---|
| Market/aggressive no-lookahead | `test_router_latency.py:67,81,162` | Covered | None found. |
| Market-data visibility latency | BT-17 acceptance re-passed this session; defaults pinned (`platform_config.py:36-37`) | Covered | None found. |
| **Passive posting latency (quote gate)** | `test_router_latency.py:210-248`, `test_passive_limit_router.py:995-1021` | **Covered (new)** | 2026-06-20 gap closed by `b923201`. |
| **Passive posting latency (trade/on_trade gate)** | Code fix in `bca1efd`; no dedicated test found | **Missing** | Add a test: submit a passive order, print a trade before `ack_timestamp_ns` that would satisfy the queue/volume threshold, assert it does not fill on the next eligible quote. |
| Passive through partial fill | `test_execution_realism_knobs.py` (`TestPassiveThroughFillCap`, line 214+) | Covered when knob on | Add a config-level assertion that live-like configs keep the knob on (2026-06-20 backlog #5, still open). |
| Passive level fill requires volume | `test_execution_realism_knobs.py` (`TestVolumeGatedLevelFill`, line 249+) | Covered when knob on | Same config-level assertion gap as above. |
| Aggressive within-L1 / permanent impact | `test_execution_realism_knobs.py` (`TestWithinL1Impact` line 93+, `TestPermanentImpact` line 130+) | Covered | Permanent impact calibration still needed before enabling. |
| Golden fill replay | `tests/determinism/test_market_fill_replay.py`; BT-11 re-passed | Covered | Keep the rebaseline workflow strict. |
| **Inv-12 latency doubling — market router** | `test_inv12_stress_gate.py:85-169` | Covered | None found. |
| **Inv-12 latency doubling — passive router** | None found | **Missing (new)** | Add a `PassiveLimitOrderRouter`-under-`apply_inv12_stress` test mirroring `test_router_deferred_fill_uses_doubled_latency`, covering both the aggressive-fallback and passive-post latency gates. |
| Inv-12 synthetic PnL survival | `test_inv12_pnl_survival.py` (aggressive path only) | Partial | Same router-coverage gap as above. |
| Inv-12 data-backed APP survival | Not runnable in this workspace (no cache/API key) | Blocked (environment) | Populate `~/.feelies/cache` and run `--inv12-stress`; see Appendix item 1. |
| Tick rounding against trader | BT-14 re-passed; `tick_size.py:34-45` | Covered | None found. |
| Borrow/HTB realism | `regulatory/test_borrow_availability.py` (10 tests); defaults available/0 (`orchestrator.py:838`, `platform.yaml:91,177`) | Partial | Set `borrow_default_tier`/populate a table for short-enabled configs; calibrate HTB fee. |
| PDT gate | `regulatory/test_pdt_constraint.py` (21 tests) | Covered | None found (only `margin_25k` implemented, by design). |
| RTH entry suppression | `test_bt16_rth_session.py` (5 tests) | Covered | None found. |
| MOC official close | `test_moc_fill.py` (7 tests), `test_moc_imbalance_e2e.py` | Partial | Price source is still a proxy; add official auction-print fixture if/when data exists. |
| Stop/forced-exit slippage | `test_stop_slippage.py` (both routers) | Covered | Depth-depletion multiplier still uncalibrated. |
| **Passive fill-ack double-latency** | None (defect not yet known to a test) | **Missing (new)** | Add a test asserting a THROUGH/DRAIN fill's ack `timestamp_ns` equals `max(clock.now_ns(), pending.ack_timestamp_ns)`, not `+ latency_ns` again; will fail until §3.3 is fixed. |
| `market_fill.py` isolated unit coverage | Embedded in 3 router test files + determinism replay | Partial (organizational) | Optional: a `test_market_fill.py` exercising `append_market_fill_acks` directly would localize regressions. |
| Data-backed APP regression | Not run this session (cache absent) | Unverified | See Appendix item 1. |

## 9. Prioritized backlog

| Pri | Effort | Type | Component | Evidence | One-sentence fix | Expected impact |
|---|---|---|---|---|---|---|
| P1 | S | Test gap | Inv-12 stress not proven for the default router | `tests/acceptance/test_inv12_stress_gate.py:85-169` (market only); `platform.yaml:185` (passive default) | Add a `PassiveLimitOrderRouter` variant of `test_router_deferred_fill_uses_doubled_latency` covering both its latency-gated fill paths. | Closes the acceptance-level blind spot on the execution mode actually used in production/reference backtests. |
| P1 | S | Config risk | Root runtime cost gate below Inv-12 | `platform.yaml:156`, `bootstrap.py:259-261` | Set root/default `signal_min_edge_cost_ratio` to 1.5 or require an explicit opt-out for 1.0. | Prevents default backtests from trading edges that don't clear the Inv-12 target margin. |
| P1 | M | Modeling choice | Borrow/HTB defaults optimistic | `orchestrator.py:838,6492-6494`, `platform.yaml:91,177` | Populate `borrow_availability` or set `borrow_default_tier` for short-enabled configs; calibrate HTB fees. | Prevents free/always-available shorting outside large-cap universes. |
| P1 | S | Test/config gap | Live-like realism knobs can silently be off | `platform_config.py:438,456,461` (code defaults) vs `platform.yaml:206,210,213` (root overrides) | Add a validation helper/profile check requiring the through-cap, trade-required-level-fill, and non-zero within-L1-impact knobs for any config flagged "production". | Avoids accidentally optimistic configs that bypass the reference profile (2026-06-20 backlog #5, still open). |
| P2 | S | Implementation bug | Passive fill-ack timestamp double-counts latency | `passive_limit_router.py:924` vs `:296,359,485,979` | Change `_emit_passive_fill`'s `fill_ts` to `max(self._clock.now_ns(), pending.ack_timestamp_ns)`, matching every other fill-timestamp site. | Fixes passive-fill latency telemetry; no PnL/price effect either way. |
| P2 | S | Test gap | `on_trade` pre-eligibility gate untested | `passive_limit_router.py:286-291` (fix `bca1efd`, no accompanying test) | Add a regression test: trade prints before `ack_timestamp_ns`, assert it doesn't count toward queue/volume thresholds. | Locks in the 2026-07-01 fix against silent regression. |
| P2 | M | Modeling choice | MOC official close proxy | `moc_fill.py:206`, `platform.yaml:219` | Use official auction prints/imbalance data when available; keep the penalty as fallback. | Improves MOC PnL realism for auction-dependent strategies. |
| P2 | M | Calibration gap | Permanent impact disabled | `market_fill.py:146` (coefficient plumbing), `platform.yaml:222` | Estimate the permanent-impact coefficient from cached fills/live TCA before enabling. | Better cost for larger orders without blind over-penalization. |
| P2 | S | Observability gap | Taker spread embedded in fill price | `market_fill.py:8-24`, `cost_model.py:267-281` | Add TCA columns for arrival-mid spread/impact cost independent of `fees`/`cost_bps`. | Prevents under-reading transaction cost from `ack.cost_bps` alone. |
| P2 | S | Config/observability | Realized-cost-overrun escalation off by default | `platform_config.py:470`, `orchestrator.py:5773-5814` | Consider enabling `realized_cost_escalation_enabled` in `platform.yaml` (or document why not) and add a backtest-router-level unit test. | Makes the fail-safe cost-drift halt actually load-bearing in the reference profile, not just paper/live. |
| P2 | S | Test-organization | No isolated `market_fill.py` unit test module | `src/feelies/execution/market_fill.py` (no `tests/execution/test_market_fill.py`) | Add a focused unit-test module for `append_market_fill_acks` / `base_impact_premium`. | Localizes regressions instead of spreading failures across three router test files. |

## 10. Appendix: open questions needing data runs

1. **APP/2026-03-26 baseline is unverified in this workspace.** `~/.feelies/cache` is empty and no `MASSIVE_API_KEY` is set, so `test_app_20260326_backtest_baseline_from_disk_cache` skipped rather than passed or failed. The currently pinned values are `_BASELINE_NET_PNL = Decimal("430.85")`, `_BASELINE_FILL_COUNT = 21` (`tests/acceptance/test_backtest_app_baseline.py:107-111`), substantially different from the 2026-06-20 audit's observations ($69.06 pinned / $52.54 observed, 6 fills pinned / 4 observed) because of an intervening, documented re-bake ("2026-06-29 ... after the L1->L2 boundary-time/latch regression audit"). Whoever has the populated cache should re-run `uv run pytest tests/acceptance/test_backtest_app_baseline.py -q -m functional` and confirm it's still green before relying on it as a promotion gate.
2. After (1), run the same cached day with and without `--inv12-stress` to measure actual PnL compression from 1.5× cost and 2× latency, and specifically confirm the `passive_limit`-mode latency doubling behaves as intended end-to-end (not just in the synthetic unit tests noted in §4.3/§8).
3. Quantify the passive-fill-ack double-latency bias (§3.3) on a real trading day: how many passive fills' reported timestamps are `latency_ns` later than their true exchange-time instant, and does anything downstream (hazard-exit age checks, latency dashboards) key off that timestamp in a way that matters.
4. Calibrate `cost_within_l1_impact_factor` (currently 0.3) and `cost_permanent_impact_coefficient` (currently 0.0) from cached/live TCA — `platform.yaml:213,222`.
5. For all short-enabled alphas, enumerate symbols absent from `borrow_availability` and estimate realistic HTB/locate tiers — currently all default to `available` (`platform.yaml:91`, `orchestrator.py:838`).
6. For MOC strategies, compare the close-mid proxy plus 3 bps penalty (`moc_fill.py:206`, `platform.yaml:219`) against official auction prints/imbalance sizes on cached sessions.
7. Reconcile `sig_benign_midcap_v1`'s disclosed `cost_arithmetic` (round-trip ≈10.0 bps, `alphas/sig_benign_midcap_v1/sig_benign_midcap_v1.alpha.yaml:141-149`) against the B4 runtime gate's live-recomputed round-trip cost on the same cached day, to confirm the static disclosure and dynamic runtime estimate stay within a reasonable band of each other.

## 11. Implementation update — 2026-07-04

The prioritized backlog above was actioned in a follow-up pass on this branch. Outcome per item:

| Backlog item | Outcome |
|---|---|
| P1: Inv-12 stress not proven for the default (passive) router | **Fixed.** Added `test_passive_router_aggressive_fallback_uses_doubled_latency` and `test_passive_router_resting_post_uses_doubled_latency` (`tests/acceptance/test_inv12_stress_gate.py`), covering both of `PassiveLimitOrderRouter`'s latency-gated fill paths under 2× stress. |
| P1: Root runtime cost gate below Inv-12 (`platform.yaml:156`) | **Deferred to the user, not changed.** The line carries an explicit, dated comment ("Audit P1-3 ... intentionally permissive for the reference profile ... raise to 1.5 for any cost-realistic run") — a documented prior decision, not an oversight. Every real deployment/paper config already overrides to 1.5 independently, so this is a considered policy choice, not a live defect; flipping it unilaterally would override that documented intent. |
| P1: Borrow/HTB defaults optimistic | **Assessed, not fabricated.** Confirmed real exposure: `sig_inventory_revert_v1` explicitly shorts as part of its strategy ("short after ask-side depletion"); every shipped research config trades only `APP` and none set `borrow_availability` or `borrow_default_tier`. Populating real per-symbol borrow tiers or calibrated HTB fees requires actual broker-locate data this session doesn't have — inventing values would be fabricating financial data, so this is left as an open, real gap for whoever has that data. |
| P1: Live-like realism knobs can silently be off | **Fixed.** Added `src/feelies/execution/realism_profile.py` (`live_like_realism_violations` / `assert_live_like_execution_realism`) plus `tests/execution/test_realism_profile.py`, including a test that asserts the shipped `platform.yaml` itself stays live-like — regressions on these knobs now fail CI. |
| P2: Passive fill-ack timestamp double-counts latency | **Fixed.** `passive_limit_router.py:924` now uses `max(self._clock.now_ns(), pending.ack_timestamp_ns)`, matching every other fill-timestamp site. Updated the one test that pinned the old (buggy) value (`test_passive_fill_latency`, `tests/execution/test_passive_limit_router.py`); verified the fix is regression-meaningful by confirming the test fails without it. |
| P2: `on_trade` pre-eligibility gate untested | **Fixed.** Added `test_pre_eligibility_trade_does_not_count_toward_queue_drain` (`tests/execution/test_passive_limit_router.py`); confirmed it fails without the `bca1efd` gate. |
| P2: MOC official close proxy | **Not actioned** — requires real auction-print/imbalance data this session doesn't have. |
| P2: Permanent impact calibration | **Not actioned** — requires real cached-fill/live TCA data this session doesn't have. |
| P2: Taker spread embedded in fill price (TCA observability) | **Not actioned this pass** — a new TCA column touches `OrderAck`/`TradeRecord` schema, which sits on the locked parity-hash surface; safer as its own reviewed change than folded into this remediation pass. |
| P2: Realized-cost-overrun escalation off by default | **Partially fixed.** Added backtest-level unit coverage (`TestRealizedCostEscalation`, `tests/kernel/test_orchestrator.py`) proving the streak-counter and kill-switch escalation work in backtest mode, not just the `paper_rth`-gated integration test (which — side discovery — asserts an alert name, `g12_realized_cost_exceeds_disclosure_stress`, that does not match what the code actually emits, `g12_realized_cost_exceeds_disclosure`; that's a live-execution-track bug, flagged here but not fixed as out of scope). Did **not** flip `realized_cost_escalation_enabled` on in `platform.yaml`: it is inherited via `extends:` by every research config with none overriding it, and this workspace has no disk cache to verify it doesn't change the pinned APP baseline fill count/PnL — left for a data-backed decision. |
| P2: No isolated `market_fill.py` unit test module | **Fixed.** Added `tests/execution/test_market_fill.py` (14 tests) directly exercising `append_market_fill_acks` and `base_impact_premium` in isolation. |

**Side effect on the test suite:** the new `realism_profile.py` module required registering in `tests/docs/test_prompt_coverage_map.py`'s `_FILE_OWNERS` (a drift guard requiring every `execution/` module to have an explicit audit owner) — done, owner `audit_execution_fills`.

**Pre-existing, unrelated failures confirmed on the clean tree (not touched):** `tests/acceptance/test_no_walltime_outside_clock.py::test_wall_clock_allowlist_has_no_stale_entries` (a `core/` wall-clock allowlist drift) and five `tests/kernel/test_orchestrator.py` `STOP_EXIT` reason-classification tests (`order_reason` metadata resolving to `''` instead of `'STOP_EXIT'`). Both confirmed present before any change in this pass via `git stash`; both are outside the execution-fills scope.

**Full verification after the pass:** `uv run mypy src/feelies` — clean (193 files). `uv run ruff check src/ tests/` — clean. `uv run pytest -m "not functional and not slow"` — 3840 passed, 5 skipped, 6 pre-existing failures (above), same failures with or without this pass's changes. `uv run pytest tests/execution/ -q` — 684 passed (was 663). `uv run pytest tests/acceptance/test_bt11_parity_post_fill_model.py tests/acceptance/test_bt14_tick_rounding.py tests/acceptance/test_bt17_market_data_latency.py tests/acceptance/test_inv12_stress_gate.py -q` — 29 passed (was 27).
