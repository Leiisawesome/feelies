<!--
  File:   docs/research/prompt_pack_12p_router_fill_timing_parity.md
  Status: COMPLETE — Task 12-P (2026-07-12). Router fill-timing parity
          battery (PRECONDITION section of prompt set v2.0 Task 12,
          brought forward). AXIS-1 disposition: VERIFIED. Regression
          guards committed under tests/execution/ and tests/kernel/.
  Owner:  backtest-engine / live-execution (parity); card-independent
          engineering — no alpha evidence, multiple-testing N-impact 0.
-->

# Task 12-P — Router fill-timing parity battery

**Mandate.** Map existing router fill-timing coverage, add targeted
synthetic-tape cases for every uncovered asymmetry in which a passive
order could become fill-eligible off an event predating its
live+latency-eligible time, include the FQ-2 size-cap split cases
T12-SC1–SC5 (`prompt_pack_00c_eval_canon.md` §2), run the full gate
battery under `PYTHONHASHSEED=0`, and record the AXIS-1 disposition.
No overlay runs, no alpha evidence, no fixes (a violation would have
stopped the task as OPEN-DEFECT).

**Eligibility contract under test** (`execution/passive_limit_router.py`):
a resting passive order's live time is
`ack_timestamp_ns = max(clock.now_ns, submit-quote exchange_ts) + latency_ns`;
quotes gate at `_check_resting_orders` (`quote.exchange_timestamp_ns <
ack_timestamp_ns → skip`, before any counter/hazard state is touched) and
trades gate identically in `on_trade`. Deferred aggressive fills gate at
`fill_deadline_exchange_ns` in `_flush_deferred_aggressive` /
`_flush_deferred_market_fills` (shared `DeferredFill` record, Inv-9).

---

## 1. Coverage map (existing, at 5acdcd7)

| Surface | Where covered | Timing asymmetry covered? |
|---|---|---|
| Deferred MARKET latency queue (both routers): no fill before eligibility, fill prices off first post-eligibility quote, FIFO, per-symbol isolation | `tests/execution/test_router_latency.py` | Yes (one-way: eligible quote arrives and crosses) |
| Resting LIMIT through-fill deferred until latency-eligible (single cross persists past eligibility) | `test_router_latency.py::test_resting_limit_through_fill_deferred_until_latency_eligible` | Partially — did NOT cover cross-then-revert or stale-cross price memory |
| Passive drain-fill latency gate; no second latency leg on fill ts | `test_passive_limit_router.py::TestLatency::test_passive_fill_latency` | Yes (basic gate only; state non-contamination unpinned) |
| Pre-eligibility trade excluded from queue drain (queue-shares mode) | `test_passive_limit_router.py::test_pre_eligibility_trade_does_not_count_toward_queue_drain` | Yes — but only the `queue_position_shares` regime, not the P1.2 volume gate |
| Deferred aggressive: zero-depth/crossed-quote/limit-violation rejects at the fill quote, id release + retry, timeout after `max_resting_ticks` stale ticks, reject ts ≥ ACK ts | `test_passive_limit_router.py::TestLatency` | Yes (aggressive path) |
| Aggressive chokepoint pricing (impact, splits, clamps, tick grid) | `tests/execution/test_market_fill.py` | Timing-free by design (fill_ts is a caller input) |
| Size-cap partial + rest-in-place; volume gate on/off | `tests/execution/test_execution_realism_knobs.py` | No latency interaction; SC1–SC5 ambiguities unpinned |
| Halt entry suppression + resume blackout + exit permitted | `tests/kernel/test_orchestrator.py::TestHaltModeling` | `BacktestOrderRouter` signal path only; passive-router resting/deferred paths unpinned |

## 2. Cases added (permanent regression guards)

`tests/execution/test_router_fill_timing_parity.py` (14 tests):

| # | Case | Asymmetry targeted |
|---|---|---|
| 1 | Reference profile pins `backtest_fill_latency_ns > 0` and `market_data_latency_ns > 0` | Zero-latency prohibition precondition (00c decision A / OQ-4) |
| 2, 3 | BUY / SELL cross-then-revert inside the latency window → never fills (drain disabled so any fill = stale cross) | Through-fill inside the latency window |
| 4 | Stale in-window cross offers a better price than the post-eligibility cross → fill prices off the post-eligibility quote (99.98, not 99.90), ts = eligible quote | Through-fill price memory / lookahead |
| 5 | Control ≡ treatment: pre-eligibility at-level quotes consume no seeded hazard draws and advance no counters (identical fill tick/ts/price) | Level-fill hazard trials on stale quotes |
| 6 | 5 stale ticks > `max_resting_ticks=3` do not expire the order; expiry fires on the 3rd eligible tick, EXPIRED ts ≥ ACK ts | `max_resting_ticks` expiry × latency |
| 7 | In-window print does not satisfy the P1.2 `require_trade_for_level_fill` volume gate; post-eligibility print does | Arrival mid-queue-drain (volume-gate regime) |
| 8 | Level cancels (bid steps over limit) and replenishes inside the window → post-window behavior identical to control | Cancel/replenish at the resting level |
| 9 | Explicit `cancel_order` inside the window: CANCELLED ts floored at ACKNOWLEDGED; later crossing quote cannot fill the dead order | Cancel × latency, monotonic ack stream |
| 10 | **T12-SC1** partial through-fill then timeout: EXPIRED fee = `cancel_fee_per_share × FULL original qty` (pinned; see observation O-1); only the partial 30 sh ever filled; terminal-only stats tally the order as a cancel | 00c §2 SC1 |
| 11 | **T12-SC2** two-slice split of a 50-share order pays the $0.35 IBKR floor per slice (2 × 0.35) | 00c §2 SC2 |
| 12 | **T12-SC3** partial fill inside RTH, next through-tick past the close → REJECTED (`RTH_ENTRY_SUPPRESSED`) for an order with `filled_quantity > 0`; order removed | 00c §2 SC3 |
| 13 | **T12-SC4** zero-size crossing quote → full-remainder fill fallback | 00c §2 SC4 |
| 14 | **T12-SC5** drain-of-remainder: ack qty = remainder (70), adverse selection switches to the LEVEL rate (2.0 bps → fees 1.40 vs THROUGH slice 1.50 on 30 sh) | 00c §2 SC5 |

`tests/kernel/test_orchestrator.py::TestHaltModeling::test_halt_suppresses_passive_router_fill_paths`
(halt suppression, both passive-router fill paths — kernel-owned gate, so
the case lives with the kernel harness): resting passive order cancelled
at halt-on (Inv-11); an in-halt crossing quote past both orders'
eligibility deadlines is withheld from the router entirely (router wired
via the bus behind the M1 publish, exactly as `bootstrap.py:500`); the
surviving deferred MARKET order fills post-resume at the post-resume
quote's own cross — no price from inside the halt window.

## 3. Gate battery (PYTHONHASHSEED=0, host per 00d, git base 5acdcd7, branch main)

| Gate | Result |
|---|---|
| `uv run pytest -m "not functional and not slow"` | **3996 passed, 9 skipped**, 0 failed (143 s) |
| `uv run pytest tests/determinism/` | **126 passed, 4 skipped** — no locked baseline touched |
| `uv run mypy src/feelies` (strict) | clean (193 files; no src changes) |
| `uv run ruff check src/ tests/` | clean |
| `uv run ruff format --check` (changed files) | clean |
| New battery (`test_router_fill_timing_parity.py` + `TestHaltModeling`) | 18 passed |

No production code was changed; the parity manifest and promotion ledger
are untouched.

## 4. Disposition

| Axis | Status | Basis |
|---|---|---|
| **AXIS-1** (router fill-timing parity) | **VERIFIED** — no violation found; every targeted asymmetry (through-fill in-window, stale-quote hazard trials, mid-drain arrival, cancel/replenish, expiry × latency, halt suppression both paths) resolves causally; T12-SC1–SC5 pinned; cases committed as permanent regression guards | this battery |
| **AXIS-2** (reported alongside per the FQ-5B binding amendment) | WS size units **RESOLVED — SHARES** (FQ-5B/FQ-6A live capture, `prompt_pack_03c_universe_and_cache.md` §8). Live-WS dissemination residuals (cancel/correction records on the `T` channel; June-2026 condition/indicator population change incl. uninterpreted quote condition 34) remain **OPEN** pending vendor answers | `prompt_pack_00_architecture_verification.md` §(e) |

Per the register's binding amendment, this task does **not** close the
last parity gap: AXIS-2 dissemination residuals remain open.

### Observations (pinned behavior, not AXIS-1 defects — no fix in this task)

- **O-1 (SC1 cancel-fee basis).** `_append_cancel_ack` computes the
  cancel fee on `pending.request.quantity` (full original size), not the
  unfilled remainder, after a partial through-fill. Inert on the
  canonical profile (`passive_cancel_fee_per_share: 0.0`) and
  conservative (overstates cost) if ever configured — but wrong-basis.
  Pinned by SC1; any future fix is its own reviewed thread and must
  update that pin deliberately.
- **O-2 (expiry-count asymmetry, both directions causal).** Passive
  resting orders count only post-eligibility ticks toward
  `max_resting_ticks` (a stale window cannot expire them); deferred
  aggressive orders count pre-eligibility ticks and time out (Inv-11
  liveness). Neither direction permits a fill off a pre-live event; the
  asymmetry is documented, not a timing defect.
- **O-3 (halt trade-path forwarding).** While a symbol is halted via the
  BT-5 condition-code gate, quotes are withheld from the router, but
  in-halt Trade prints still reach `router.on_trade` unless a normalizer
  reports `DataHealth.HALTED`. No fill path exists (resting orders are
  cancelled at halt-on; entries are suppressed), so this is a forensic
  note only.

**Honest accounting:** engineering verification; no alpha construction or
parameter variant evaluated; multiple-testing ledger N-impact 0.
