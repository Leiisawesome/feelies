# 12-Engine Architecture Review — Comprehension Record

**Date:** 2026-08-09
**Scope:** `src/feelies/` against a 12-engine ownership model, plus cross-cutting layers
**Status:** review complete; remediation merged across PRs #220–#231

This is a *comprehension* document, not a design spec. It records how the platform
is actually built, where the engine model maps cleanly onto it and where it does
not, and what the review learned by measurement rather than by reading. The
canonical sources remain [`platform-invariants.mdc`](../../.cursor/rules/platform-invariants.mdc),
[`three_layer_architecture.md`](../three_layer_architecture.md), and
[`alphas/SCHEMA.md`](../../alphas/SCHEMA.md); where this document and those
disagree, they win.

---

## 1. The shape of the system

Three layers over L1 NBBO, with a kernel that sequences them:

```
  market data ──► SENSOR (L1) ──► SIGNAL (L2) ──► PORTFOLIO (L3) ──► RISK ──► EXECUTION
                     │               │                │                │
                  sensors/        signals/        composition/       risk/    execution/
                  features/                                        broker/
```

- **SENSOR (Layer 1)** — incremental observers over quotes and trades, emitting
  versioned `SensorReading`. `features/` aggregates them onto horizon boundaries.
- **SIGNAL (Layer 2)** — `HorizonSignalEngine` evaluates alpha YAML at horizon
  boundaries and emits typed `Signal` (direction, strength, edge estimate).
  Stateless: no position or order awareness.
- **PORTFOLIO (Layer 3)** — `CompositionEngine` turns multiple signals into a
  `SizedPositionIntent` — a desired book state, not orders.
- **RISK** — vetoes and sizes. `check_order` on the standalone path,
  `check_sized_intent` (per-leg veto) on the composition path. Also *authors*
  exit orders, which is the subtle part; see §4.
- **EXECUTION** — `ExecutionBackend` is the single mode seam (Inv-9). Routers:
  `backtest_router`, `passive_limit_router`, `live_router`; `broker/ib/` for IB.

Everything crosses a synchronous typed event bus (Inv-7). There is no polling.

**Module footprint** (files / lines, 2026-08-09) — a rough proxy for where
complexity actually lives:

| module | files | lines | | module | files | lines |
|---|---:|---:|---|---|---:|---:|
| `alpha` | 18 | 8786 | | `sensors` | 26 | 4271 |
| `kernel` | 5 | 6731 | | `risk` | 14 | 3222 |
| `execution` | 24 | 5265 | | `harness` | 6 | 2889 |
| `composition` | 8 | 2473 | | `ingestion` | 9 | 2302 |
| `research` | 7 | 1802 | | `forensics` | 10 | 1721 |
| `services` | 4 | 1608 | | `signals` | 4 | 1582 |
| `features` | 8 | 1522 | | `portfolio` | 6 | 958 |
| `broker` | 5 | 880 | | | | |

`alpha/` and `kernel/` dominate. That is worth knowing: the orchestrator is the
single largest concentration of behaviour in the system, and most of the review's
findings were in it.

---

## 2. Engine-model mapping

The 12-engine model maps onto the codebase, but not one-to-one. Recording the
mismatches is more useful than pretending it fits.

| # | Engine | Primary home | Mapping quality |
|---|---|---|---|
| 1 | Ingestion | `ingestion/`, `storage/cache_replay.py` | clean |
| 2 | Sensor | `sensors/` (registry + 20-odd impls) | clean |
| 3 | Feature/horizon | `features/` | clean |
| 4 | Regime | `services/regime_engine.py`, `regime_state_cache.py` | clean after #220-era work |
| 5 | Signal | `signals/horizon_engine.py`, `alpha/` | **split** — the DSL, loader, and gates live in `alpha/`, the runtime in `signals/` |
| 6 | Composition | `composition/` | clean |
| 7 | Risk | `risk/` | **overloaded** — vetoes *and* authors exit orders |
| 8 | Sizing | `risk/position_sizer.py`, `edge_weighted_sizer.py` | inside Risk, not separate |
| 9 | Execution | `execution/`, `broker/` | clean; `ExecutionBackend` is the mode seam |
| 10 | Portfolio/position | `portfolio/` | **two stores** — symbol-net and per-strategy slice |
| 11 | Forensics | `forensics/`, `research/` | clean |
| 12 | Promotion/lifecycle | `alpha/lifecycle.py`, `promotion_ledger.py`, `cli/` | clean |

**The three mismatches matter:**

- **Risk is two engines wearing one coat.** It is both the veto authority and an
  order *author*. Four controllers emit exit orders: `stop_exit`, `hazard_exit`,
  `exit_composer`, `deferral_cap`. These bypass the normal signal→intent→order
  path and enter the kernel through a dedicated bridge. Treating "Risk" as a pure
  gate would miss half of what it does — and that half is the safety-critical half.
- **Position state is two stores, deliberately.** `MemoryPositionStore` holds
  symbol-net; `StrategyPositionStore` holds per-alpha slices. They must agree, and
  most of the review's worst findings were about them silently disagreeing.
- **Signal logic is split across `alpha/` and `signals/`.** The alpha YAML, its
  seventeen validation gates (G1–G17), and the loader are in `alpha/`; evaluation
  is in `signals/`. This is a reasonable split but it means "the signal engine" is
  not one directory.

---

## 3. The hot path

`Orchestrator._on_market_event` drives a 16-state micro state machine per tick.
The states are a legal transition spine, not all visited every tick — sensor,
horizon, signal and portfolio states are skipped when their layers aren't
configured.

```
WAITING_FOR_MARKET_EVENT → MARKET_EVENT_RECEIVED → STATE_UPDATE
  → SENSOR_UPDATE → HORIZON_CHECK → HORIZON_AGGREGATE
  → SIGNAL_GATE → CROSS_SECTIONAL → FEATURE_COMPUTE → SIGNAL_EVALUATE
  → RISK_CHECK → ORDER_DECISION → ORDER_SUBMIT → ORDER_ACK
  → POSITION_UPDATE → LOG_AND_METRICS
```

A macro state machine sits above it: `INIT → DATA_SYNC → READY` then one of
`RESEARCH_MODE / BACKTEST_MODE / PAPER_TRADING_MODE / LIVE_TRADING_MODE`, with
`DEGRADED`, `RISK_LOCKDOWN` and `SHUTDOWN` as safety terminals.

**Ordering facts that turned out to be load-bearing:**

- The book must be marked *before* the quote is published, or drawdown is
  evaluated against a stale mark. Getting this backwards flipped a measured
  drawdown verdict from 0.055% to 1.000% against a 1.0% bar.
- A cancel reconciles queued acks *including fills*, so the book can move between
  a forced exit's reduce-test and its submission. Everything downstream of
  `_cancel_resting_for_symbol` must re-read the book, not trust the earlier read.
- Per-slice realized PnL must be measured around each slice's own
  `strategy_positions.update()`. Apportioning the aggregate figure by quantity is
  correct only when every slice entered at the same price.

**Volume, for calibration:** a single APP session is ~250k events; ten sessions
~1.78M. Sensors fire per event (kyle_lambda_60s emitted ~170k readings in one
session). Signals are far rarer — ~60 per session, ~415 across ten.

---

## 4. Trading logic

### Entry

Alpha YAML declares a mechanism (G16 closed enum), a regime gate, cost
arithmetic, and an `evaluate()` returning a `Signal`. Entry requires: the
regime gate ON, the alpha's own thresholds met, and disclosed edge clearing the
B4 cost gate (`signal_min_edge_cost_ratio`, Inv-12). Sizing is
`equity × capital_allocation_pct × strength × regime_factor / price`, capped by
`max_position_per_symbol`.

> **A caveat found by measurement, not reading:** a minimum-order clamp raises any
> nonzero target up to `_min_order_shares`. That defaults to 1, but `platform.yaml`
> sets `platform_min_order_shares: 50` and the paper configs mostly follow. At 50k
> equity and a ~$400 price every alpha's sized target lands under 50, so all of
> them get exactly 50 shares regardless of what their risk budget declares —
> `capital_allocation_pct` is effectively inert on that path. Verified by running
> one alpha at 5% and 50% allocation and getting identical targets, and by
> watching another size to 50 across strengths from 0.501 to 1.077. Whether this
> is intended is an open question (§7).

### Exit

Two families, and the distinction runs through the whole system:

- **Discretionary exits** — the alpha wants out. Normal signal path.
- **Forced exits** — a safety control mandates it. Eight reason tokens:
  `STOP_EXIT`, `SESSION_FLAT`, `SESSION_FLATTEN`, `HAZARD_SPIKE`,
  `HARD_EXIT_AGE`, `MAX_HOLD_AFTER_SAFE_OFF`, `SAFETY_FAIL_CLOSED`,
  `DECOUPLING_REVOKED`.

Forced exits enter through `_on_bus_hazard_order`, a non-vetoable submission path
with a reduce-only override. Two properties are essential and both were defects
at review time:

1. **A forced exit may never open exposure** (Inv-11). Magnitude shrinkage is
   *not* the test — `abs(current + signed) < abs(current)` is true of any
   reduction including one that crosses zero. The clamp is on the closable side
   only, and it now runs on every path rather than only after cancelling a
   resting order.
2. **Scope.** Five of the eight reasons are *slice-scoped*: their exit may
   legitimately exceed symbol-net, because another strategy holding the opposite
   side can leave the net flat while the mandated slice is still open. Those take
   `max(symbol-net closable, slice closable)`. The other three are symbol-net and
   are clamped to net.

### Attribution

A symbol-net forced exit closes slices belonging to whichever alphas held the
symbol — not the order's own `strategy_id`, which for these authors is a kernel
sentinel or just the policy that triggered. Getting this wrong is not cosmetic:
every per-alpha estimator groups by `strategy_id`, and those feed promotion and
quarantine. The review measured a misattribution worth **−111.63 bps/event**,
which inverted one alpha's measured edge from −0.63 to +4.42 bps.

### Lifecycle

`RESEARCH → PAPER → LIVE → QUARANTINED → DECOMMISSIONED` (the last terminal),
with an append-only promotion ledger and
declarative gates: `research_to_paper`, `paper_to_live`,
`live_promote_capital_tier`, `live_to_quarantined`, `quarantined_to_paper`,
`quarantined_to_decommissioned`, `decouple_caps_only`. `lifecycle_state: RESEARCH`
in a spec is loader-enforced and blocks PAPER/LIVE promotion outright.

---

## 5. Determinism and parity

Inv-5 and Inv-9 are enforced by a locked-baseline corpus in `tests/determinism/`,
registered in `parity_manifest.py` and rolled up into a single
`EXPECTED_MANIFEST_FINGERPRINT` so a coordinated re-pin is one line in review.

**What the review established about it:**

- The registered corpus is **portable across libm** — every locked hash reproduced
  identically on macOS and glibc (CI run 31262226139). The manifest's
  host-sensitivity caveat applies to the *unregistered* hashes, which is why they
  carry exemptions rather than manifest entries.
- `compute_parity_hash` covers the trade sequence, and its field set is the whole
  contract. It was blind to `fees` and `cost_bps` — a fee schedule could change
  and two runs with different net profitability would be declared at parity.
  `realized_pnl` is booked *gross*; the store keeps `cumulative_fees` separately.
- Nothing pinned that hash to a literal (both callers compared it to itself),
  which is why the gap survived.

---

## 6. What the review actually taught

The individual defects matter less than the pattern behind them.

**Six defects hid behind fixtures that covered the one input shape the buggy
logic happened to handle.** The determinism corpus never wired a
`StrategyPositionStore`, never had a resting order live at exit time, never had a
fill land on cancel, never had a partial cover, and never had divergent entry
prices. Each gap concealed a real defect. A seventh instance occurred *during*
remediation: a test written specifically to pin the `max()` branch never reached
it, because that clamp only ran when a resting order existed.

The rule this produced is in [`AGENTS.md`](../../AGENTS.md): **mutate the source
and confirm the new test fails; a green run does not prove the branch executed.**
Scoped to fail-safe guards, where the failure mode is silent. With two caveats
learned the hard way — clear `__pycache__` between mutations, and always end on a
pristine run that must be green, because a failed restore reads exactly like a
failed test.

**A second pattern: "exercise this" repeatedly became "this could never have
run."** The edge-calibration loop had never executed because any backtest range
spanning a weekend failed to boot. The netting shadow had one observation in 33
sessions because no shipped alpha pair ever takes opposing sides. Neither was
visible from reading; both surfaced the moment something tried.

**A third: guards that cannot fail.** The manifest completeness scanner matched
`^EXPECTED_\w*_HASH`, so dict-shaped baselines were invisible — not exempt,
invisible, which is different. Eight allow-list entries named constants that had
not existed for some time. And `main` had no CI at all until this review; every
green claim rested on someone running the suite locally at a commit they chose.

---

## 7. Open questions

These are decisions, not defects, and none are the reviewer's to make.

1. **`sig_benign_midcap_v1` promotability.** Over 15 cached APP sessions: 154
   fills, gross **+$383**, fees **$1,004**, net **−$620** — fees 2.62× gross,
   −$4.03 per fill, 7 of 15 sessions net-positive. Realized edge −75.10 bps
   against 9.0 disclosed, under the *tighter* of the available configurations.
   Not generalized: AAPL and SPY sit outside the alpha's declared mid-cap universe
   and produced 4 and 0 fills, so they say nothing about fee economics. The cache
   holds no second midcap.
2. **Flat-vs-live netting semantics.** With a purpose-built research fixture
   alpha, 15 sessions now yield **108 divergences** (105 opposite-sides-both-live,
   3 winner-flat-net-live) against **1** with the shipped alphas alone. On a tick
   where arbitration holds +253 long and netting holds 247 short, which does the
   platform want? Now answerable from data.
3. **The minimum-order clamp** swallowing per-alpha allocation (§4). It is a
   configured value (`platform_min_order_shares: 50`), not a hardcoded one, so the
   question is whether 50 is right for a 50k book rather than whether the clamp
   should exist. Found incidentally; not acted on.
4. **`sig_kyle_drift_v1`'s timescale gap.** Signature persistence measures
   626.6 s (95% CI [374.6, 877.9], R² 0.993) while the gate-conditioned forward IC
   peaks at 240 s. The two disagree about the natural horizon and G16 rule 3
   forces a choice. Recorded as evidence; horizon left at 300 s.

## 8. What was deliberately not changed

- `LegacyPositionManager` — an internal collaborator of `TargetPositionManager`,
  not dead code. An early draft of this review listed it for deletion; that was
  wrong.
- The `max(symbol-net, slice)` latitude for slice-scoped exits — deliberate and
  documented (§3.3 of the netting design), not a missing clamp.
- Timestamps and `correlation_id` in the parity hash — plumbing, and hashing them
  would make parity sensitive to clock and id wiring rather than economics.
- `enable_portfolio_netting` — stays OFF until the semantics decision is made.

---

## Provenance

Remediation: PRs #220–#231. Measurements in this document come from the cached
event corpus under `~/.feelies/cache/` (APP 15 tradeable sessions, plus AAPL,
INTC, SNDU, SPY) and are reproducible from the configs named alongside them.
Per-alpha evidence is recorded in the alpha specs themselves —
`sig_benign_midcap_v1` (cost arithmetic block) and `sig_kyle_drift_v1`
(trend mechanism block) — so it is found where the decision is made rather than
only here.

## Current-code errata (2026-08-10)

These narrow clarifications describe current code; they preserve the review's
measurements, provenance, and open questions rather than rewriting its history.

- **A02 — dispatch and polling.** Inter-layer event-bus dispatch is synchronous;
  boundary adapters may poll. In particular, live feeds may use an internal poll
  timeout and `OrderRouter.poll_acks()` collects pending acknowledgements.
- **T01 — signal-engine state.** `HorizonSignalEngine` is position/order-unaware,
  not stateless; its registrations and causal regime, sensor, sequence, attachment,
  and boundary-index caches are legitimate runtime state.
- **M09b — live-router status.** `LiveOrderRouter` is a fail-fast reserved stub,
  not a working router. Its constructor raises `NotImplementedError`; this
  clarification makes no API, retirement, or implementation-roadmap decision.
