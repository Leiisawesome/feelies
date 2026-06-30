# APP 2026-06-01 backtest — `__stop_exit__` and entry-signal investigation

> Archived from `docs/pending issues/` — investigation resolved; retained under `docs/audits/`.

**Status:** Resolved (P0 platform fix landed 2026-06-19; see §9)  
**Date:** 2026-06-17 (investigation) · 2026-06-19 (resolution)  
**Scope:** Forensic analysis of `sig_benign_midcap_v1` on APP for 2026-06-01 using `configs/bt_sig_benign_midcap.yaml`. The investigation itself modified no production code; the P0 execution-path bug it identified was fixed on 2026-06-19 (§9).

**Related artifacts**

- Alpha: `alphas/sig_benign_midcap_v1/sig_benign_midcap_v1.alpha.yaml`
- Config: `configs/bt_sig_benign_midcap.yaml` (extends `platform.yaml`)
- Kernel guards: `src/feelies/kernel/orchestrator.py` (`_check_stop_exit`, resting-order guard, `_cancel_resting_for_symbol`, `_FORCED_MARKET_EXIT_STRATEGIES`)
- Gate-OFF FLAT path: `src/feelies/signals/horizon_engine.py` (`_publish_gate_close`)

**Reproduce**

```bash
uv run python scripts/run_backtest.py \
  --symbol APP --date 2026-06-01 \
  --config configs/bt_sig_benign_midcap.yaml
```

---

## 1. Executive summary

A single-day APP backtest lost **−0.94%** (−$470.88 net after fees). **82% of realized losses** (−$446 of −$548.50) came from one `__stop_exit__` cover at $608.42 on a short opened at $599.50.

**Root cause (stop loss):** The 1% hard stop (`stop_loss_pct: 0.01`) was **correctly breached** around 11:22 ET (mid ≈ $605.51 vs threshold ≈ $605.50), but the stop **could not submit a MARKET exit for ~57 minutes** because a resting passive LIMIT cover order from the alpha's regime-gate OFF → FLAT path was still active. The `resting_order_guard` treats an existing pending exit as blocking duplicate exits — including `__stop_exit__`. When the passive order finally **expired** at tick budget (`passive_max_resting_ticks: 8000`), the stop fired at **$608.42**, realizing **−1.49%** per share instead of the configured **−1.0%**.

**Root cause (entries):** The three filled entries were **structurally valid** under the alpha's declared logic (OFI z-score + book-imbalance confirmation + regime gate). Two shorts were followed by **adverse 120s returns** (−8.5 bps and −17.9 bps); the long was the weakest signal (z barely above threshold) but had a modest favorable 120s move (+2.5 bps). The day loss is therefore a combination of **alpha misfire on direction** and a **platform execution bug** that amplified the second short's loss.

**Highest-ROI fix:** Make `__stop_exit__` (and ideally gate-OFF FLAT exits when a hard stop is breached) **cancel resting exit orders and cross at MARKET**, mirroring the existing REVERSE path in `_execute_reverse()`.

---

## 2. Backtest configuration

| Setting | Value | Source |
|---------|-------|--------|
| Alpha | `sig_benign_midcap_v1` only | `configs/bt_sig_benign_midcap.yaml` |
| Symbol / date | APP / 2026-06-01 | CLI |
| `entry_threshold_z` | 1.5 (override; alpha default 0.8) | config `parameter_overrides` |
| `edge_per_z_bps` | 6.0 (override; alpha default 4.0) | config `parameter_overrides` |
| `signal_min_edge_cost_ratio` | 1.5 (Inv-12 round-trip floor) | config |
| `execution_mode` | `passive_limit` | `platform.yaml` |
| `passive_max_resting_ticks` | 8000 | `platform.yaml` |
| `stop_loss_pct` | 0.01 (1%) | `platform.yaml` |
| Trailing stop | 0.5% activate, 50% giveback | `platform.yaml` |
| Horizon | 120s | alpha YAML |

**Headline results**

| Metric | Value |
|--------|-------|
| Return | −0.94% ($50,000 → $49,529.12) |
| Net P&L | −$470.88 |
| Realized P&L | −$548.50 |
| Unrealized P&L (EOD) | +$107.50 |
| Fees | $29.88 |
| Orders submitted / filled | 7 / 5 |
| Signals emitted | 4,832 |
| Max drawdown | −1.22% |
| Kill switch | Not activated |

**Parity hashes (reproducibility)**

- `pnl_hash`: `f02fd9b0862c2fe764f4477fada50d23c92b69f45c6aaea87a856dbcdf5e76fe`
- `parity_hash`: `17494223fcf04ad0db6c2a8ca998c2cfc9856bdd115e8b19856af62ee4210c35`

**Cost survival (per strategy)**

| Strategy | Fills | Net P&L | Status |
|----------|-------|---------|--------|
| `sig_benign_midcap_v1` | 4 | −$130.97 | BLEED |
| `__stop_exit__` | 1 | −$447.41 | BLEED |

---

## 3. Trade timeline

All times ET.

| # | Time | Strategy | Action | Qty | Price | Realized P&L | Notes |
|---|------|----------|--------|-----|-------|--------------|-------|
| 1 | 10:33:55 | `sig_benign_midcap_v1` | SHORT entry | 50 | $595.99 | $0 | Passive fill |
| 2 | 10:43:36 | `sig_benign_midcap_v1` | Cover (FLAT) | 50 | $598.04 | −$102.50 | Gate OFF → passive cover |
| 3 | 10:58:02 | `sig_benign_midcap_v1` | SHORT entry | 50 | $599.50 | $0 | **Position closed by stop** |
| 4 | 12:19:24 | **`__stop_exit__`** | Cover (MARKET) | 50 | **$608.42** | **−$446.00** | Stop finally fires |
| 5 | 15:53:57 | `sig_benign_midcap_v1` | LONG entry | 50 | $611.30 | $0 | Still open at EOD (+$107.50 unrealized) |

**Fourth signal (not filled):** SHORT at ~14:54 with z ≈ −1.54 — structurally valid but likely blocked by conflict with the pending long entry resting in the book.

---

## 4. `__stop_exit__` failure chain

### 4.1 Stop math is correct

For the second short at entry **$599.50**:

- Hard stop threshold: `599.50 × 1.01 = 605.495` → breach when mid **> ~$605.50**
- First quote breach observed: **~11:22 ET** (mid ≈ $605.51)
- Actual fill: **12:19:24 @ $608.42** → loss **$8.92/share = 1.49%**, not 1.0%

The stop formula in `_check_stop_exit()` (`orchestrator.py:3643–3714`) behaved as designed. The loss magnitude is an **execution-path failure**, not a miscalculation.

### 4.2 Sequence of events

```mermaid
sequenceDiagram
    participant Alpha as sig_benign_midcap_v1
    participant Gate as RegimeGate
    participant Orch as Orchestrator
    participant Book as Passive LIMIT book

    Note over Alpha,Book: 10:58 — SHORT filled @ $599.50
    Note over Gate: 11:00:01 — Gate OFF (HMM leaves normal)
    Alpha->>Orch: FLAT signal
    Orch->>Book: LIMIT BUY cover @ ~$600.32
    Note over Book: Price rises; cover never fills
    Note over Orch: ~11:22 — stop breached on quotes
    Orch--xOrch: __stop_exit__ MARKET blocked<br/>(resting_order_guard + pending exit)
    Note over Book: ~12:19 — passive order EXPIRED (8000 ticks)
    Orch->>Book: __stop_exit__ MARKET BUY
    Book-->>Orch: Fill @ $608.42 (−$446)
```

1. **10:58:02** — Second short fills @ $599.50.
2. **11:00:01** — Regime gate transitions OFF (`P(normal)` collapses as HMM moves toward `vol_breakout`). Alpha emits FLAT. Orchestrator posts a **passive LIMIT BUY** cover at ~$600.32.
3. **11:00–12:19** — APP rallies; the passive cover never trades. Hard stop is **breached on quotes** but stop MARKET order is **not submitted**.
4. **12:19:23** — Passive cover **expires** (`passive_max_resting_ticks: 8000`).
5. **12:19:24** — `__stop_exit__` MARKET cover fills @ $608.42.

### 4.3 Why the stop was blocked

`__stop_exit__` is in `_FORCED_MARKET_EXIT_STRATEGIES` and is intended to always cross aggressively (Inv-11). However, the resting-order guard at `orchestrator.py:2819–2822` blocks submission when:

```python
if self._has_pending_order_for_symbol(order.symbol):
    if intent.intent != TradingIntent.EXIT or self._has_pending_exit_for_symbol(order.symbol):
        # NO_ORDER — resting_order_guard_blocked_duplicate_passive_order
```

Because the alpha's gate-OFF FLAT already posted a **pending BUY cover**, `_has_pending_exit_for_symbol()` returns True for the short. Every subsequent `__stop_exit__` MARKET attempt is suppressed until that resting order reaches a terminal state (fill, cancel, or expiry).

**Contrast:** The REVERSE path already cancels resting orders before an aggressive close:

```4109:4110:src/feelies/kernel/orchestrator.py
        # ── Cancel any resting orders for this symbol ──────────────
        self._cancel_resting_for_symbol(intent.symbol, cid)
```

The stop-exit path does **not** call `_cancel_resting_for_symbol()` before submitting its MARKET leg.

### 4.4 Inv-11 tension

Inv-11 requires fail-safe defaults: safety controls tighten autonomously; exits must not be blocked by stale passive orders when a hard stop is breached. The current guard prevents duplicate exit pile-ups (reasonable for repeated FLAT signals) but **incorrectly subordinates a forced MARKET stop to a stale passive cover**.

---

## 5. Entry signal forensics

Alpha entry logic (`sig_benign_midcap_v1.alpha.yaml:163–222`):

- **SHORT** if `ofi_ewma_zscore < −entry_threshold_z` and `book_imbalance_mean < 0` (strict alignment)
- **LONG** if opposite
- Regime gate **ON**: `P(normal) > 0.5 and spread_z_30d < 1.5`
- Regime gate **OFF**: `P(normal) < 0.35` OR spread/vol stress conditions
- Edge: `min(|z| × edge_per_z_bps, edge_cap_bps)`, suppressed below `cost_floor_bps` (5.0)

With config overrides: threshold **1.5**, slope **6.0 bps/z**.

### 5.1 Short #1 (filled ~10:33)

| Field | Value |
|-------|-------|
| `ofi_ewma_zscore` | −2.20 |
| `book_imbalance_mean` | −0.056 |
| `P(normal)` | 0.999 |
| Edge (reported) | 13.2 bps |
| 120s forward return | **−8.5 bps** (adverse — price rose) |

At **10:36** (~4 min later): HMM → `vol_breakout`, `P(normal) = 0`, OFI z flips to +0.99 → gate OFF → FLAT → passive cover @ $598.04 → **−$102.50**.

**Verdict:** Valid entry under declared rules; regime flipped quickly; short thesis failed within one horizon.

### 5.2 Short #2 (filled ~10:58) — stop-loss position

| Field | Value |
|-------|-------|
| `ofi_ewma_zscore` | **−2.84** (strongest entry of the day) |
| `book_imbalance_mean` | −0.092 |
| `P(normal)` | 0.998 |
| Edge (reported) | 17.1 bps |
| 120s forward return | **−17.9 bps** (adverse) |

Gate OFF again at **11:00:01** → passive FLAT cover posted → stop breached but blocked → **−$446** at 12:19.

**Verdict:** Strongest structural signal; still wrong on direction. Loss amplified by execution bug, not by bad stop math.

### 5.3 Long (filled ~15:53)

| Field | Value |
|-------|-------|
| `ofi_ewma_zscore` | +1.56 (barely above 1.5 threshold) |
| `book_imbalance_mean` | +0.084 |
| Edge (reported) | 9.3 bps |
| Strength | 0.52 (weakest sizing) |
| Passive fill delay | ~72 minutes resting |
| 120s forward return | +2.5 bps (favorable but small) |

**Verdict:** Weakest conviction entry; modest edge realization; EOD unrealized +$107.50.

### 5.4 Unfilled short (~14:54)

| Field | Value |
|-------|-------|
| `ofi_ewma_zscore` | −1.54 |
| Edge | ~9.2 bps |

Structurally valid SHORT; did not fill — likely superseded by pending long entry order on the same symbol.

---

## 6. Recommended mitigations

### 6.1 Code (P0 — platform)

| Priority | Change | Rationale |
|----------|--------|-----------|
| **P0** | Before submitting `__stop_exit__` (and `__session_flat__`), call `_cancel_resting_for_symbol()` then MARKET close | Mirror REVERSE path; enforce Inv-11 |
| **P1** | When hard stop is breached, supersede passive alpha FLAT covers (cancel + MARKET) | Prevents gate-OFF FLAT from trapping position |
| **P2** | Add determinism test: short + gate-OFF FLAT + rising market → stop fires at ≤1% loss | Lock regression baseline |
| **P2** | Emit `AlertEvent` when stop is suppressed by pending exit | Operator visibility |

**Suggested test scenario:** Short entry → gate OFF posts passive cover → price gaps through stop threshold → assert MARKET stop fills within N ticks at ≤ `stop_loss_pct + slippage_budget`.

### 6.2 Config / alpha (research hygiene)

| Change | Effect |
|--------|--------|
| `execution_mode: market` for research backtests | Removes passive-trap confound when evaluating alpha edge |
| Raise `entry_threshold_z` to 2.0 | Fewer marginal entries (long was z=1.56) |
| Tighten `on_condition` (e.g. `P(normal) > 0.7`) | Reduce entries near regime transitions |
| Add minimum `|book_imbalance_mean|` filter | Suppress weak confirmation (long had imb=0.084) |

### 6.3 Process

- Do not promote on single-day, single-symbol backtests.
- Require CPCV + paper window before LIVE (existing gate matrix).
- Treat `__stop_exit__` BLEED on a day as an **execution-quality** flag distinct from alpha BLEED.

---

## 7. Open questions

1. Should gate-OFF FLAT exits also be forced MARKET when `stop_loss_pct > 0` (config flag vs always-on)?
2. Should `_has_pending_exit_for_symbol` carve out `_FORCED_MARKET_EXIT_STRATEGIES` without requiring cancel-first (cancel-first is cleaner for live IB parity)?
3. Does passive FLAT on gate OFF violate the alpha hypothesis ("exit when microstructure turns toxic") if the passive order rests through the toxic move?

---

## 8. Investigation method

Read-only replay of the APP 2026-06-01 event log through the standard backtest harness (`feelies.harness.backtest_runner._run_backtest_phases_2_7`). Trade journal, order lifecycle, quote path, regime posteriors, and horizon snapshots were extracted programmatically from the in-memory event log and position store.

No scripts from this investigation were committed to the repo (ad-hoc analysis only).

---

## 9. Resolution (2026-06-19)

### 9.1 P0 — forced MARKET exits now supersede stale resting orders

**Change:** `src/feelies/kernel/orchestrator.py`, resting-order guard in
`_process_tick_inner`.

The guard previously suppressed every `__stop_exit__` / `__session_flat__`
MARKET attempt whenever `_has_pending_exit_for_symbol()` was True — which
included a stale gate-OFF FLAT passive cover that never traded. The guard now
carves out `_FORCED_MARKET_EXIT_STRATEGIES`:

- If a **forced** MARKET exit is *already* in flight for the symbol
  (`_has_pending_forced_exit_for_symbol()` — new helper), the duplicate is
  still suppressed (overshoot guard, unchanged intent of the original guard).
- Otherwise the guard **cancels the resting orders** for the symbol
  (`_cancel_resting_for_symbol()`, mirroring the REVERSE path in
  `_execute_reverse()`) and lets the aggressive close cross immediately
  (Inv-11). This covers both the hard-stop and the session-flatten paths, so
  open question #1/#2 in §7 are answered: a breached forced exit always
  cancels-first and crosses; it never waits for the passive leg to expire.

A forensic `Alert` (`alert_name="forced_exit_supersedes_pending_order"`,
WARNING) is published when the supersede fires, giving operators a marker
distinct from ordinary duplicate-exit suppression (addresses the §6.1 P2
"operator visibility" item).

### 9.2 Regression test (P2)

`tests/kernel/test_orchestrator.py::TestRestingOrderGuardAfterRisk::test_stop_exit_supersedes_resting_passive_cover`
reproduces the failure chain deterministically: short @ $599.50, a resting
passive BUY cover, then a quote that runs through the 1% hard stop. It asserts
the cover is cancelled, a `__stop_exit__` MARKET order fills in the *same*
tick, the position is flat, and the supersede alert is emitted. The existing
`test_stop_exit_does_not_submit_duplicate_exit_while_pending` still passes,
locking the overshoot guard (a forced exit already pending is not re-stacked).

### 9.3 Verification

- `pytest tests/kernel/ tests/determinism/` — 345 passed (parity hashes
  unchanged; the fix only affects the previously-blocked stop path).
- `pytest tests/acceptance/test_backtest_app_baseline.py tests/execution/` —
  664 passed.
- `ruff check` clean; `mypy src/feelies/kernel/orchestrator.py` clean.

### 9.4 Not actioned (research hygiene / process)

The §6.2 config/alpha tuning (market-mode research backtests, higher
`entry_threshold_z`, tighter `on_condition`, book-imbalance floor) and the §6.3
process notes are research-hygiene recommendations for `sig_benign_midcap_v1`,
not platform defects, and are intentionally left to the alpha author. The §5
entry-signal forensics confirmed the entries were *structurally valid* under
the declared logic — the day loss was an alpha direction misfire amplified by
the now-fixed execution bug, not a platform correctness failure.
