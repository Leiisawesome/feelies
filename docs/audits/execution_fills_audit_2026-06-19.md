# Execution / Fill-Model & Backtest-Realism Audit — 2026-06-19

**Scope:** `OrderRequest` → `ExecutionBackend` (backtest) → router → fill model →
tick/regulatory rounding → simulated `Trade` → PnL. Read-only, evidence-based.
No production code was modified.

**Verdict headline:** The fill path is **causally clean** — I found **no Inv-6
lookahead** (no fill prices off future or same-instant-but-future quotes). The
clock-visibility model (`ReplayFeed` + `SimulatedClock`) and the deferred-fill
routers are correctly causal. The PnL-realism risk is therefore **not** lookahead
but **optimism**: full-quantity passive fills, impact modeled only on the
*excess* above L1 depth, Inv-12 stress that is plumbed but **not CI-enforced on
realized PnL**, and several short-side / latency knobs whose defaults err toward
the strategy at the builder seam.

**Read-only checks run (all green):**

- `uv run pytest tests/execution/ -q` → **647 passed** (0.25s)
- `uv run pytest tests/acceptance/test_bt11_parity_post_fill_model.py test_bt14_tick_rounding.py test_bt17_market_data_latency.py test_inv12_stress_gate.py -q` → **21 passed**
- `uv run pytest tests/acceptance/test_backtest_app_baseline.py -q` → **2 passed** (disk cache present)

Legend for cause: **[bug]** implementation defect · **[model]** modeling choice ·
**[design]** intentional, documented design.

---

## 1. Executive summary (top PnL-realism risks first)

1. **No fill lookahead found (Inv-6 holds).** A market fill at sim-time T prices off a quote whose visibility time ≤ T: `ReplayFeed` advances the `SimulatedClock` to `exchange_ts + market_data_latency_ns` *before* yielding (`replay_feed.py:101`), and deferred fills price off the first latency-eligible (strictly later) quote (`backtest_router.py:298`). This is the single most important result of the audit — every backtest PnL is *not* inflated by future-price peeking. **[design]**
2. **Passive through-fills assume 100% fill of full order quantity** the instant the opposite BBO crosses the limit, ignoring quote size and trade size (`passive_limit_router.py:569`, `:582`). A resting order behind the queue would only partially fill on a through-trade. This is the largest *queue-optimism* PnL inflator in `passive_limit`/`minimum_cost` modes. **[model]** → **P1**
3. **Default passive level-fill needs no trade print.** With the default `passive_queue_position_shares = 0` (`platform_config.py:278`), level fills fire on a *quote-imbalance* hazard per tick (`passive_limit_router.py:692-711`) — a passive order can "fill" with zero traded volume at its level. The conservative queue-drain mode that requires `on_trade` volume is opt-in. **[model]** → **P1**
4. **Market impact is modeled only on the excess above displayed L1 depth.** Orders sized ≤ `ask_size`/`bid_size` (the common case) pay *zero* impact and fill entirely at the touch (`market_fill.py:189`, `:263`). No permanent-impact / sqrt term exists. Under-models cost for any order that consumes a meaningful share of L1 without exceeding it. **[model]** → **P1**
5. **Inv-12 1.5×-cost / 2×-latency survival is plumbed but not a CI gate on PnL.** `apply_inv12_stress` is correct and pure (`inv12_stress.py:41`), but it is **opt-in via the `--inv12-stress` CLI flag** (`backtest_cli.py:94`); the default backtest and the APP baseline run unstressed. `test_inv12_stress_gate.py` only asserts the *helpers* scale factors + one unit deferred-fill test — it never runs a full backtest under stress and asserts edge survival. Automated Inv-12 enforcement is therefore **load-time disclosure only** (G12 `margin_ratio ≥ 1.5`). **[model/gap]** → **P1**
6. **`market_fill` output is not locked by any in-CI golden replay.** BT-11 explicitly notes the synthetic L1–L6 determinism fixtures **do not route through `market_fill`** (`test_bt11_parity_post_fill_model.py:4-8`). The only end-to-end exercise of fill prices is the **data-gated, skip-on-cache-miss** APP baseline (`test_backtest_app_baseline.py:154`), which is not in default CI. A fill-price or cost-attribution regression can ship without tripping a determinism hash. **[gap]** → **P1**
7. **`latency_ns = 0` is silently optimistic at the builder seam.** `build_backtest_backend`/`build_passive_limit_backend` default `latency_ns=0` and `market_data_latency_ns=0` (`backtest_backend.py:38-39`, `:87,:96`). Production bootstrap overrides these with the 50ms/20ms config defaults (`bootstrap.py:479-480`), so *production is safe*, but any direct caller (tests, ad-hoc scripts) that omits latency gets same-tick zero-latency fills with **no warning**. **[model]** → **P1**
8. **Short-side defaults are optimistic.** HTB borrow fee defaults to `0.0` (`platform_config.py:425`) and unknown symbols default to `BorrowTier.AVAILABLE` (shortable, no fee) (`borrow_availability.py:6-7`). For any non-large-cap universe this under-charges and over-permits shorts. The fail-safe direction (UNAVAILABLE → block) exists but is never the default. **[model]** → **P1/P2**
9. **MOC fills the full quantity at the closing mid with zero spread and zero impact** (`moc_fill.py:200-209`) — no auction depth/imbalance penalty regardless of size. Optimistic for any non-trivial MOC order; timing itself is causal (waits for first post-close quote). **[model]** → **P2**
10. **Realized-cost overrun is observability-only.** When a fill's `cost_bps` exceeds `1.5×` the alpha's disclosed G12 cost, the orchestrator emits a WARNING `Alert` but does **not** block, scale, or quarantine (`orchestrator.py:5541`). Cost drift does not fail-safe at runtime. **[design]**
11. **Stop/panic slippage is charged as a *fee*, not as a worse fill price**, and only widens the spread component — it does not model depth collapse/gapping during a stop cascade beyond the normal walk-the-book (`market_fill.py:181-185`). NAV impact is correct but partial; attribution lives in `fees`, not `avg_entry_price`. **[model]** → **P2**
12. **Spread cost on normal taker fills is embedded in the fill price, so the realized `cost_bps` line reads 0 for the spread** (`market_fill.py:165-185` passes `half_spread=0`). NAV is invariant (spread → unrealized markdown), but any consumer reading `cost_bps`/`cumulative_fees` as "total transaction cost" understates round-trip cost. Documented, but a forensics foot-gun. **[design]**
13. **PDT hard cap is not modeled.** `margin_25k` is PDT-exempt; only a `<$25k`-equity *and* flagged account suppresses entries (`pdt_constraint.py:162-179`). With the `$50k` default equity (`platform_config.py:173`) the gate never fires — fine for the locked tier, but it is not a real day-trade-count constraint. **[design]**
14. **Backtest cost model is never applied to live fills.** Parity is *structural* (shared `OrderRouter` protocol, ack types, order SM, `_process_tick`), but live fees come from the broker, not `DefaultCostModel`. Sim-vs-live cost divergence is a monitored metric, not a structural guarantee. **[design]**
15. **Ex-date handling is detect-and-flag, not adjust.** `check_ex_date_replay_window` raises a *violation* when a replay spans an ex-date (`test_bt18_ex_date_guard.py:42`); the data policy is raw-unadjusted single-day L1. Multi-day replays across an ex-date are flagged, never price-adjusted. **[design]**

---

## 2. Execution inventory

| Component | File | Role | Key knobs / defaults |
|---|---|---|---|
| `ExecutionBackend` facade | `execution/backend.py:82` | Only mode-specific seam (Inv-9) | `mode` ∈ BACKTEST/PAPER/LIVE |
| `MarketDataSource` / `OrderRouter` protocols | `execution/backend.py:34,55` | Data + ack contracts | — |
| Backend builders | `execution/backtest_backend.py:27,80` | Compose ReplayFeed + router | `latency_ns=0`, `market_data_latency_ns=0` (signature defaults) |
| `BacktestOrderRouter` (market) | `execution/backtest_router.py:118` | Cross-price taker + D14 walk-book | `latency_ns`, `market_impact_factor=0.5`, `max_impact_half_spreads=10`, `max_resting_ticks=50` |
| `PassiveLimitOrderRouter` | `execution/passive_limit_router.py:133` | Queue-position passive fills | `fill_delay_ticks=3`, `queue_position_shares=0`, `fill_hazard_max=0.5`, `max_resting_ticks=50` |
| Shared aggressive fill | `execution/market_fill.py:140` | `append_market_fill_acks` (both routers) | embeds half-spread in price; impact on excess only |
| Stop-exit reason set | `execution/_fill_helpers.py:11` | Panic-slippage classification | STOP_EXIT/HARD_EXIT_AGE/HAZARD_SPIKE/FORCE_FLATTEN |
| MOC controller | `execution/moc_fill.py:29` | Closing-auction fill at close mid | cutoff 15:50 / close 16:00 ET |
| MOC session bounds | `execution/moc_session.py:67` | ET cutoff/close → ns | early-close 12:50/13:00 |
| Cost model | `execution/cost_model.py:196` | IB Tiered + reg fees + adverse + HTB | see §4 table |
| Round-trip / depth-aware estimators | `execution/cost_model.py:435,526` | B4 gate + min-cost policy pricing | depth-aware on excess |
| Tick grid | `execution/tick_size.py:34,41` | Reg-NMS snap | BUY ceil / SELL floor (fills); BUY floor / SELL ceil (limits) |
| Min-cost policy | `execution/min_cost_policy.py:99` | Per-order passive vs aggressive | `passive_non_fill_probability=0.30`, small-order/tight-spread carve-outs |
| Borrow availability | `execution/regulatory/borrow_availability.py:27` | Locate tiers | unknown → AVAILABLE |
| PDT constraint | `execution/regulatory/pdt_constraint.py:80` | Round-trip counter + $25k gate | `margin_25k` only |
| RTH session gate | `execution/trading_session.py:160` | Entry suppression outside RTH | exits always allowed |
| Latency wiring | `ingestion/replay_feed.py:37` | MD-latency visibility clock advance | `market_data_latency_ns` |
| Inv-12 stress harness | `core/inv12_stress.py:41` | 1.5× cost / 2× both latency legs | opt-in via `--inv12-stress` |
| Config defaults | `core/platform_config.py:36,175,225,253` | Fill/MD latency, cost stress, mode | 50ms / 20ms / 1.0 / `market` |

**Latency legs (BT-17, distinct, not double-counted):**

| Leg | Default | Where applied |
|---|---|---|
| Market-data propagation | 20ms (`platform_config.py:37`) | `ReplayFeed` advances clock to `exchange_ts + md_latency` before yield (`replay_feed.py:101-107`) |
| Order-submission / fill | 50ms (`platform_config.py:36`) | Router defers fill eligibility to `exchange_ts + latency_ns` (`backtest_router.py:291`) |

---

## 3. Fill realism & lookahead audit (deep dive)

### 3.1 Trace of one market fill — is it causal? (Inv-6)

The end-to-end sequence inside one tick (`orchestrator._process_tick_inner`):

1. `ReplayFeed.events()` advances `SimulatedClock` to the quote's **visibility time** `exchange_ts + market_data_latency_ns` and only then yields the quote (`replay_feed.py:100-108`). The decision clock can never be earlier than visibility.
2. The orchestrator publishes the quote on the bus (`orchestrator.py:2250`), which fires `backtest_router.on_quote(quote)` (subscribed at `bootstrap.py:498`), setting `_last_quotes[symbol] = quote`.
3. Signals are evaluated; an order is submitted later in the same tick.
4. At submit, the router reads `_last_quotes[request.symbol]` (`backtest_router.py:228`).

**Two regimes:**

- **`latency_ns > 0` (production default 50ms):** the order is queued as a `DeferredFill` with deadline `max(now, quote.exchange_ts) + latency_ns` (`backtest_router.py:287-296`) and fills only when a *later* quote crosses that deadline (`_flush_deferred_market_fills`, `:298-347`). Fill price comes from the **first qualifying (strictly later) quote**, not the decision quote. **Causal and realistic.** ✅
- **`latency_ns <= 0`:** fills immediately against the decision-triggering quote's cross (`backtest_router.py:272-283`). The quote is visible at ≤ T (no future leakage), but there is **no latency between decision and fill** — an optimistic same-tick fill. This is the optimism vector, mitigated by the non-zero default.

**Conclusion (Inv-6):** No use of future or post-decision quotes as the fill price under the default config. The decision-quote-as-fill case only arises when latency is explicitly set to 0. **This is the single highest-value finding: there is no fill lookahead to remediate.**

Cross-checked by `test_bt17_market_data_latency.py:51-67` (clock at visibility, not exchange time) and `:70-86` (clock after first quote never reaches a later quote's visibility).

### 3.2 Queue position / partial fills

**Through-fill (`action == "through"`):** when the opposite BBO crosses the resting limit, the order fills its **entire `request.quantity`** in a single tick at the (price-improved) crossed BBO (`passive_limit_router.py:569-590`, fill of `pending.request.quantity` in `_emit_passive_fill`, `:842`). It does **not** cap the fill at the crossing quote's size or at the through-trade's size. A resting order behind the queue would, in reality, fill only the volume that trades through. → **queue optimism, P1.**

**Level / drain fill (`action == "drain"`):** two regimes (`_fill_hazard`, `:661-711`):
- **Queue-depth (`queue_ahead_shares > 0`)** — requires accumulated traded volume via `on_trade` to drain the modeled queue ahead before any fill (`:692-695`); hazard is exactly 0 until drained. **Conservative**, but **opt-in** (`queue_position_shares=0` default).
- **Quote-imbalance (default)** — per-tick Bernoulli against `h0·(2·imbalance)` (`:704-705`). Fills can occur on quote ticks alone with **no trade prints at the level**. → **fill-without-volume optimism, P1.**

Determinism preserved: the Bernoulli uniform is a SHA-256 of replay-stable keys, no RNG (`passive_limit_router.py:713-734`). ✅ (Inv-5)

**Depth-aware partial on aggressive fills:** the D14 split (`market_fill.py:189-261`) correctly partials at L1 depth and walks the book on the excess — this is the *good* part of the model. The gap is that **within-L1 orders pay no impact at all** (§4.2).

### 3.3 Stop slippage (conservative on adverse moves?)

Stop / hazard / forced-flatten exits (`STOP_EXIT_REASONS`, `_fill_helpers.py:11`) add a panic premium of `(stop_slippage_half_spreads − 1) × raw_half_spread` (`market_fill.py:181-185`), charged through `fees`, default `2.0` (`platform_config.py:240`). Verified by `test_stop_slippage.py:59-92` (stop fee > normal fee) and `:94-128` (multiplier 1.0 disables).

Caveats: (a) the *fill price* is unchanged — slippage lands in `fees`, not `avg_entry_price`; (b) it widens only the spread component, not depth — a real stop cascade gaps and depletes depth, which this does not model beyond the normal walk-the-book; (c) it uses the **current** quote's `raw_half_spread`, so if the quote has not yet widened the premium is small. **Directionally conservative but partial. P2.**

### 3.4 MOC fills

MOC orders are acked at submit (rejected if at/after the 15:50 cutoff, `moc_fill.py:80-89`), rest until the first NBBO at/after the official close, then fill in one print at the **closing mid** with `half_spread=0` (`moc_fill.py:194-209`). Timing is causal (waits for the post-close quote; `expire_unfilled` is the terminal backstop). The optimism: **full quantity, no spread, no impact, no depth check** regardless of order size — a large MOC ignores auction imbalance entirely. **P2 (model).** Cross-day quotes/submits are correctly refused (`moc_session.covers_ns`).

---

## 4. Cost model & Inv-12 stress audit

### 4.1 Component decomposition (`DefaultCostModel.compute`, `cost_model.py:214-405`)

| Component | Default | Stressed by `stress_multiplier`? | Notes |
|---|---|---|---|
| Spread cost (taker) | actual `half_spread × qty`, floor `min_spread_cost_bps=0.3` | Yes | **Passed `half_spread=0` from `market_fill` for normal taker fills** — spread is embedded in price, so this line is 0 on realized fills (`market_fill.py:165-185`) |
| Commission (IB Tiered) | `$0.0035/sh`, floor `$0.35`, cap `1%` | per-share rate Yes; floor/cap **No** | IBKR doesn't move thresholds under stress (`cost_model.py:286-293`) |
| Taker exchange | `$0.003/sh` | Yes | maker rebate not stressed |
| Adverse selection (maker) | `2.0` bps drain / `5.0` bps through | Yes | billed vs opposite-side BBO when `adverse_notional_price` supplied |
| SEC Section 31 (sells) | `0.5` bps | Yes | `cost_model.py:368-370` |
| FINRA TAF (sells) | `$0.000166/sh`, cap `$8.30` | per-share Yes; cap No | `:371-375` |
| HTB borrow (short sells) | `0.0` (**disabled**) | Yes | one entry-day accrual only; `:385-393` |
| Market impact | walk-the-book on **excess over L1 only** | n/a (in price) | §4.2 |

### 4.2 Impact realism

Impact is `market_impact_factor × (excess/depth) × half_spread`, capped at `max_impact_half_spreads × half_spread`, applied **only to `quantity − available_depth`** (`market_fill.py:217-236`). Orders ≤ L1 depth pay **zero** impact. There is **no permanent-impact / sqrt term** (the SKILL's "permanent: sqrt model" remains a design target). For strategies that size at/below displayed L1 (typical L1-only intraday), realized impact is **systematically zero** → backtest under-states cost. **P1 (model).**

### 4.3 Round-trip estimate vs disclosed `cost_arithmetic`

`estimate_round_trip_cost_bps` (`cost_model.py:526`) is the runtime B4 complement to load-time G12. It correctly: (a) passes the **actual** `half_spread` (so the estimate *does* count spread the realized fill hides in price), (b) keeps the conservative asymmetric option of pricing the **exit leg as taker even when entry is passive** (`:560-569`), (c) uses the depth-aware estimator when depth+impact knobs are supplied (`:585-601`). This is internally consistent and the more-conservative direction. The realized-vs-disclosed comparison at fill time is **alert-only**, not blocking (`orchestrator.py:5541`). A methodical reconciliation of each alpha's disclosed `cost_arithmetic` against `cost_model` output on a cached dataset is listed as an open question (§10).

### 4.4 Inv-12 stress harness

`apply_inv12_stress` (`inv12_stress.py:41-55`) returns a pure `dataclasses.replace` with `cost_stress_multiplier × 1.5`, `backtest_fill_latency_ns × 2`, **and** `market_data_latency_ns × 2` (both legs, BT-17). The cost knob threads to `DefaultCostModelConfig.stress_multiplier` (`bootstrap.py:442`) and only scales **variable** costs (broker thresholds untouched, `cost_model.py:286-293`). Determinism preserved. ✅

**The gap is enforcement, not mechanics:**
- It is **opt-in** via `--inv12-stress` (`backtest_cli.py:94-95`); the default backtest and the APP baseline run unstressed (no latency/cost in `bt_sig_benign_midcap.yaml`).
- `test_inv12_stress_gate.py` asserts the **helpers apply factors** (`:42-82`) and a **single unit deferred-fill** honors 2× latency (`:85-169`). It does **not** run a full stressed backtest and assert PnL/edge survival.
- Automated Inv-12 survival is therefore **load-time disclosure only**: `disclosure_survives_inv12_cost_stress` divides `margin_ratio` by 1.5 and checks `≥ MIN_MARGIN_RATIO` (`inv12_stress.py:63-70`). The "edge survives 1.5×cost/2×latency on realized PnL" claim is delegated to the human-run BT-12 protocol, which is not in CI. **P1.**

---

## 5. Latency injection audit (market-data vs fill)

- **Distinct legs, no double-count.** MD latency advances the *visibility clock* (`replay_feed.py:101-107`); fill latency defers *router fill eligibility* (`backtest_router.py:291`). They compose additively and represent different physical delays. ✅ BT-17.
- **Production defaults are non-zero and safe:** 50ms fill / 20ms MD (`platform_config.py:36-37`, `platform.yaml:116-117`), threaded through `bootstrap.py:479-480` → builders → ReplayFeed/router. `test_bt17_market_data_latency.py:34-42` locks these constants.
- **Builder-seam optimism:** `build_backtest_backend`/`build_passive_limit_backend` default both latencies to `0` (`backtest_backend.py:38-39,87,96`). A direct caller that omits them gets same-tick zero-latency fills with **no warning**. Production is unaffected (bootstrap overrides), but the unsafe default is unflagged. **P1.**
- **Stress doubles both legs** correctly (§4.4). The deferred-fill timeout (`max_resting_ticks=50`) is a fail-safe so thin data cannot strand an ack-only order (`backtest_router.py:312-319`). ✅ Inv-11.
- **Applied via injectable clock** only — no `datetime.now()` in the fill path; `SimulatedClock` monotonicity guard rejects backward time. ✅ Inv-10.

---

## 6. Tick-size & regulatory audit

- **Tick rounding never favors the strategy.** Fills: BUY ceil, SELL floor (`tick_size.py:34-38`). Limits: BUY floor, SELL ceil (`:41-45`). Walk-the-book impact snaps after stacking and before limit-clamp (`market_fill.py:170-178,232-236`). Verified by `test_bt14_tick_rounding.py` (passed). Sub-penny rule: `$0.01` ≥ \$1, `$0.0001` < \$1 (`tick_size.py:27-31`) — correct simplification. ✅ **Conservative.**
- **Borrow / locate:** `BorrowTier.UNAVAILABLE` blocks short entries (fail-safe), `HARD` carries HTB if enabled. But **unknown symbols default to AVAILABLE** (`borrow_availability.py:6-7`) and **HTB defaults to 0** (`platform_config.py:425`) — shorts are shortable and free by default. Fail-safe *direction* exists but is not the default; optimistic for non-large-cap shorts. **P1/P2 (model).**
- **PDT:** round-trip counter + $25k maintenance gate; `margin_25k` is PDT-exempt and the 3-RT/5-day hard cap is **not modeled** (`pdt_constraint.py:1-21,162-179`). With $50k default equity the entry-suppression gate never fires. Documented, deterministic (ET clock, no RNG). **[design].**
- **Ex-date guard:** detect-and-flag, not adjust — `check_ex_date_replay_window` raises a violation when a replay spans an ex-date; the policy is raw-unadjusted single-day L1 (`test_bt18_ex_date_guard.py:35-62`, `docs/data_adjustment_policy.md`). Splits/dividends are not price-adjusted in-fill; multi-day cross-ex-date replays only get a violation. **[design].**

---

## 7. Backtest/live parity audit (Inv-9)

- **Shared core, single seam.** Both backtest routers implement the `OrderRouter` protocol; the aggressive fill path (`market_fill.append_market_fill_acks`), the `DeferredFill` latency record, and `DefaultCostModel` are shared between them, so the two backtest routers cannot drift on latency/ack ordering (`market_fill.py:43`, `backtest_router.py:115`, `passive_limit_router.py:130`). The orchestrator's `_process_tick` is mode-agnostic. ✅
- **Cost model is backtest-only by construction.** Live/paper fills come from the IB broker router; `DefaultCostModel` is not applied to live fills. Parity here is *structural* (ack types, order SM, reconciliation) plus *monitored* (sim-vs-live slippage/fill-rate/cost drift in the live-execution skill), not a code-shared cost guarantee. Acceptable per architecture, but means cost realism is only ever validated against the *model's own* assumptions in backtest. **[design].**
- **BT-11 parity gap:** `test_bt11_parity_post_fill_model.py:4-8` states the synthetic L1–L6 fixtures **do not route through `market_fill`**, so the 11 locked determinism hashes do **not** pin fill prices or cost attribution. The only end-to-end lock on `market_fill` output is the **data-gated APP baseline** (Net PnL `$71.56` + 6 fills, `test_backtest_app_baseline.py:92-93`) which **skips on cache miss** (`:154`) and is `@pytest.mark.functional` (not default CI). **A fill-price/cost regression can pass CI.** **P1 (gap).**

---

## 8. Test gap matrix

| Invariant / property | Test(s) | Status |
|---|---|---|
| No-lookahead fill (Inv-6, visibility clock) | `test_bt17_market_data_latency.py:51-86` | **Covered** (feed level) |
| No-lookahead fill (router uses post-latency quote) | `test_inv12_stress_gate.py:85-169`, `test_router_latency.py` | **Covered** (router level) |
| Adversarial lookahead probe (router given a *future* quote must not use it) | — | **Missing** (§9 spec) |
| Deterministic fill replay (Inv-5) over `market_fill` prices | BT-11 hashes **exclude** `market_fill`; APP baseline data-gated | **Partial / not in CI** |
| Cost model decomposition & stress scaling | `test_cost_model.py`, `test_inv12_stress_gate.py:57-82` | **Covered** |
| Round-trip / depth-aware estimate | `test_round_trip_cost_estimate.py`, `test_depth_aware_estimate.py` | **Covered** |
| Inv-12 *PnL* survival under joint stress (full backtest) | — (only helper + unit) | **Missing** |
| Tick rounding against trader | `test_tick_size.py`, `test_bt14_tick_rounding.py` | **Covered** |
| Stop/panic slippage conservative | `test_stop_slippage.py` | **Covered** (spread-component only) |
| Passive through-fill *partial* (size-capped) | — | **Missing** |
| Passive level-fill requires volume (queue-drain mode) | `test_passive_limit_router.py` | **Covered (opt-in mode)**; default quote-imbalance mode fill-without-volume **untested as a risk** |
| MOC mechanics & timing | `test_moc_fill.py`, `test_moc_imbalance_e2e.py` | **Covered** (no size/imbalance penalty) |
| RTH session gating | `test_trading_session.py`, `test_bt16_rth_session.py` | **Covered** |
| Borrow/PDT regulatory | `test_borrow_availability.py`, `test_pdt_constraint.py` | **Covered** (defaults optimistic, untested as risk) |
| Ex-date replay guard | `test_bt18_ex_date_guard.py` | **Covered** (detect, not adjust) |
| Backtest/live parity (structural) | `test_bt11_parity_post_fill_model.py` | **Covered for SM/hashes; not for fill prices** |
| `market_fill.py` dedicated module | — | **Missing** (coverage only via routers) |

**Minimal proposed new tests (specs only):**

1. **Golden fill replay (P1):** a small fixed L1 event log + a scripted order sequence in `market` mode at default 50ms latency; assert the exact `(fill_price, filled_quantity, fees, cost_bps, timestamp_ns)` tuple per ack and a SHA-256 over them. Wire into the determinism manifest so `market_fill` output is locked in CI (closes §1.6 / §7).
2. **Adversarial lookahead probe (P1):** feed the router quote `Q_T` (decision), submit an order, then feed a *strictly better future* quote `Q_{T+Δ}` before the latency deadline; assert the fill price equals the **first quote at/after the deadline**, never `Q_T`'s touch nor an earlier-than-deadline better quote. Falsifies any same-tick or future-price fill.
3. **Inv-12 PnL survival (P1):** run the APP (or a synthetic) backtest twice — baseline and `apply_inv12_stress` — and assert stressed Net PnL is computed, finite, and that the edge clears a configured survival bar; make it data-light so it runs in CI (synthetic event log if no cache).
4. **Passive through-fill partial (P1):** resting limit qty 1000, through-trade quote with `size=100`; assert filled ≤ 100 (currently fills 1000) — will **fail today**, documenting the optimism.
5. **Latency-default safety (P2):** assert `build_*_backend(...)` either rejects `latency_ns=0` in a "strict realism" mode or emits a one-shot WARNING, so the unsafe default is visible.

---

## 9. Prioritized backlog

> No **P0** items: no fill lookahead, no rounding-in-favor, no non-determinism found. The P0 class is *clean*.

| Pri | Effort | Component | `file:line` | One-sentence fix | PnL-realism impact |
|---|---|---|---|---|---|
| P1 | M | Passive through-fill full-fill | `passive_limit_router.py:569-590` | Cap through-fill quantity at the crossing quote size (and/or split remainder back to resting) instead of filling full order qty | Removes systematic over-fill of passive entries in `passive_limit`/`minimum_cost` modes |
| P1 | M | Default passive level-fill needs no volume | `passive_limit_router.py:692-711`, `platform_config.py:278` | Make the queue-drain (volume-required) regime the default, or gate quote-imbalance fills behind observed trade activity | Stops passive orders filling on quote ticks with zero traded volume |
| P1 | M | Impact only on excess-over-L1 | `market_fill.py:189,217-236` | Add a participation-based impact term that applies to within-L1 size too (linear temp + optional sqrt permanent) | Raises modeled cost for the common ≤L1 order, the main under-charge |
| P1 | S | Inv-12 not CI-enforced on PnL | `backtest_cli.py:94`, `test_inv12_stress_gate.py` | Add a CI test that runs a (synthetic) backtest under `apply_inv12_stress` and asserts edge survival | Turns Inv-12 from disclosure-only into a realized-PnL gate |
| P1 | S | `market_fill` not locked in CI | `test_bt11_parity_post_fill_model.py:4-8` | Add golden fill-replay (§8.1) to the determinism manifest | Catches fill-price/cost regressions before merge |
| P1 | S | `latency_ns=0` unflagged at builders | `backtest_backend.py:38-39,87,96` | Warn (or require explicit opt-in) when a backtest backend is built with zero latency | Prevents accidental optimistic same-tick fills in scripts/tests |
| P1 | S | Short-side optimistic defaults | `borrow_availability.py:6-7`, `platform_config.py:425` | Default unknown symbols to a conservative tier for non-large-cap universes and/or warn when HTB=0 with shorts enabled | Stops free/always-available shorting in backtests |
| P2 | M | MOC no size/impact penalty | `moc_fill.py:194-209` | Add an auction-imbalance/size penalty (and optional half-spread) to MOC fills | Realistic large-MOC cost |
| P2 | M | Stop slippage = fee only, no depth model | `market_fill.py:181-185` | Model depth depletion/gap on forced exits, not just a wider spread fee | Realistic stop-cascade cost |
| P2 | S | Realized-cost overrun alert-only | `orchestrator.py:5541` | Optionally escalate (scale/suppress) when realized cost persistently exceeds disclosure | Runtime fail-safe on cost drift |
| P2 | L | Richer impact + live calibration | `cost_model.py`, `backtest-engine` skill | Calibrate `market_impact_factor`/adverse-selection from cached APP data; add sqrt permanent impact | Closes sim-vs-live cost gap |

---

## 9a. Remediation status (implemented 2026-06-19)

All P1 and P2 items were implemented as **additive, configurable, default-behaviour-neutral** changes (the platform's G-7 / R-1 / P2.x house pattern). Every code default reproduces the prior trade path, so the 11 locked Inv-5 parity hashes and the APP PnL baseline (`$71.56` / 6 fills) are **unchanged**; only the config-contract snapshot grew (re-baked in `test_backtest_app_baseline.py`). Operators opt into the conservative behaviour per deployment via the new knobs.

| Item | Status | New config knob (default) | Tests |
|---|---|---|---|
| Passive through-fill full-fill (P1) | Done | `passive_through_fill_size_cap_enabled` (`false`) | `test_execution_realism_knobs.py::TestPassiveThroughFillCap` |
| Passive level-fill needs no volume (P1) | Done | `passive_require_trade_for_level_fill` (`false`) | `…::TestVolumeGatedLevelFill` |
| Impact only on excess-over-L1 (P1) | Done | `cost_within_l1_impact_factor` (`0.0`) | `…::TestWithinL1Impact` |
| Inv-12 not CI-enforced on PnL (P1) | Done | — (test only) | `test_inv12_pnl_survival.py` |
| `market_fill` not locked in CI (P1) | Done | — (golden replay) | `tests/determinism/test_market_fill_replay.py` (+ parity manifest) |
| `latency_ns=0` unflagged (P1) | Done | — (one-shot WARNING at builders) | covered via `backtest_backend._warn_on_zero_latency` |
| Short-side optimistic defaults (P1) | Done | `borrow_default_tier` (`"available"`) + HTB-zero WARNING | config validation in `test_platform_config.py` |
| MOC no size/impact penalty (P2) | Done | `cost_moc_penalty_bps` (`0.0`) | `…::TestMocPenalty` |
| Stop slippage no depth model (P2) | Done | `cost_stop_depth_depletion_factor` (`1.0`) | `…::TestStopDepthDepletion` |
| Realized-cost overrun alert-only (P2) | Done | `realized_cost_escalation_enabled` (`false`), `realized_cost_escalation_streak` (`3`) | kill-switch escalation in `orchestrator` |
| Richer impact + sqrt permanent (P2-L) | Partial | `cost_permanent_impact_coefficient` (`0.0`) — model term added; **live calibration from cached APP data remains a data task** (§10) | `…::TestPermanentImpact` |

> **Recommended live-like backtest profile** (set in a deployment config, not flipped in code defaults to preserve baselines): enable `passive_through_fill_size_cap_enabled`, `passive_require_trade_for_level_fill`, a small `cost_within_l1_impact_factor` (e.g. `0.3`), `cost_moc_penalty_bps` (e.g. `2–5`), `cost_stop_depth_depletion_factor` (e.g. `2.0`), and a conservative `borrow_default_tier` for non-large-cap universes. Flipping these on changes the trade path → re-bake the APP PnL baseline in the same commit.

---

## 10. Appendix: open questions needing data runs

1. **Cost reconciliation:** Run `bt_app.yaml` on the `APP/2026-03-26` disk cache and reconcile each fill's realized `cost_bps` (remembering spread is in price, not `fees`, for taker fills — §4.1) against `sig_benign_midcap_v1`'s disclosed `cost_arithmetic.cost_total_bps`. Do they agree within the G12 ±5% tolerance once spread-in-price is added back?
2. **Inv-12 PnL delta:** Replay the same dataset with and without `--inv12-stress`. By how many bps does Net PnL compress under 1.5×cost/2×latency, and does the alpha's edge survive? (Today: unknown — never run in CI.)
3. **Passive fill-rate realism:** In `passive_limit` mode with the default quote-imbalance hazard, what is `passive_fill_stats().passive_fill_rate` on real data vs. the queue-drain (volume-required) mode? Quantify the optimism of finding §3.2.
4. **Impact share:** What fraction of APP fills size ≤ L1 depth (and thus pay zero modeled impact)? This sizes the §4.2 under-charge.
5. **Short cohort exposure:** Does any deployed/research alpha take shorts on symbols absent from `borrow_availability` (→ AVAILABLE) with HTB=0? If so, the borrow under-charge is live, not theoretical.
