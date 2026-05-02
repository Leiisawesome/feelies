---
name: risk-engine
description: >
  Risk control layer + portfolio governor for the feelies platform. Owns
  the `RiskEngine` protocol with three entry points (`check_signal`,
  `check_order`, `check_sized_intent` for the Layer-3 path), the
  `RiskLevel` escalation SM, real-time PnL attribution, regime-aware
  sizing, the `HazardExitController`, and the per-leg veto semantics
  that turn a `SizedPositionIntent` into per-leg `OrderRequest`s. Use
  when designing risk constraints, debugging the per-leg veto path,
  reasoning about regime-conditional sizing, hazard-driven exits,
  fail-safe escalation, or PnL attribution.
---

# Risk Engine & Portfolio Governor

The risk engine is the sole gatekeeper between any alpha layer and the
order router. **No order intent reaches `OrderRouter.submit` without
transiting the risk engine**. The system defaults to safe: unknown
states, missing data, and unhandled conditions all resolve to
position reduction or trading halt, never to increased exposure
(Inv-11).

The risk engine has three entry points, one per upstream:

| Entry point | Caller | Path |
|-------------|--------|------|
| `check_signal(signal, positions)` | M5 (SIGNAL → Order) | Per-symbol gate before order construction |
| `check_order(order, positions)` | M6 (post-construction) | Final gate before submission |
| `check_sized_intent(intent, positions)` | CROSS_SECTIONAL (PORTFOLIO) | Per-leg veto on cross-sectional intent |

The third path was added with the Layer-3 PORTFOLIO architecture and
is documented in detail below.

## Core Invariants

Inherits Inv-5 (deterministic replay), Inv-11 (fail-safe default +
monotonic safety). Additionally:

1. **No bypass** — every order request transits the risk engine; no
   direct alpha → execution path exists.
2. **Two-phase per-symbol check** — `check_signal()` at M5,
   `check_order()` at M6. Both must pass.
3. **Per-leg veto on cross-sectional** — `check_sized_intent` evaluates
   each leg independently; a single failed leg drops only that leg
   (the rest of the intent proceeds). This is Inv-11 made structural.
4. **Independent authority** — the risk engine can halt trading
   unilaterally; no other layer can override.
5. **Replay-deterministic ordering** — per-leg `OrderRequest`s are
   sorted lexicographically by symbol so the L3-orders parity hash
   stays bit-identical.

## Risk Escalation SM

The `RiskLevel` SM (`risk/escalation.py`) enforces monotonic safety
tightening. Once escalation begins, de-escalation is forbidden — only
the full cycle through LOCKED and human-authorized unlock returns to
NORMAL (Inv-11).

| State | ID | Transitions to |
|-------|----|----------------|
| `NORMAL` | R0 | WARNING |
| `WARNING` | R1 | BREACH_DETECTED |
| `BREACH_DETECTED` | R2 | FORCED_FLATTEN |
| `FORCED_FLATTEN` | R3 | LOCKED |
| `LOCKED` | R4 | NORMAL (only via `unlock_from_lockdown(audit_token)` with zero-exposure guard) |

`Orchestrator._escalate_risk()` walks R0 → R1 → R2 → R3 → R4
atomically, then activates `KillSwitch` and transitions macro to
RISK_LOCKDOWN. For intermediate stranding (callback exception during
escalation), `reset_risk_escalation(audit_token)` resets from
{WARNING, BREACH_DETECTED, FORCED_FLATTEN}; LOCKED is exit-only.

## `RiskAction` Decisions

`RiskEngine` returns `RiskVerdict` events (`core/events.py`) with a
typed `RiskAction`:

| `RiskAction` | Pipeline response |
|--------------|-------------------|
| `ALLOW` | Proceed to order construction / submission |
| `SCALE_DOWN` | Apply `verdict.scaling_factor` to order quantity |
| `REJECT` | Skip order; transition to M10 |
| `FORCE_FLATTEN` | Trigger `_escalate_risk()` cascade; abort pipeline |

Exhaustiveness guards at M5, M6, and the per-leg veto loop raise
`ValueError` for any `RiskAction` not explicitly handled.

---

## Layer-3 Path: `check_sized_intent`

Triggered by Layer-3 PORTFOLIO alphas at the `CROSS_SECTIONAL`
sub-state. The `CompositionEngine` emits one `SizedPositionIntent` per
`(alpha_id, horizon_seconds, boundary_index)`; `check_sized_intent`:

1. **Resolves desired delta** against `PositionStore` (current signed
   quantity and `latest_mark`)
2. **Emits per-leg `OrderRequest`s** sorted lexicographically by symbol
   (deterministic ordering for the L3-orders parity hash)
3. **Applies per-leg risk checks** with **per-leg veto** — a single
   failed leg drops only that leg, not the whole intent
4. **Stamps `OrderRequest.reason = "PORTFOLIO"`** for forensic lineage

The per-leg veto is structural Inv-11: a single risk-bound stock
cannot break the entire cross-sectional book. Each emitted leg
inherits the intent's `correlation_id` so post-trade attribution can
recover the originating intent.

`SizedPositionIntent.mechanism_breakdown: dict[TrendMechanism, float]`
is preserved through the veto loop — the per-mechanism gross-exposure
share is recorded even after some legs are vetoed, so the
`MultiHorizonAttributor` can compute realized vs decided breakdowns.

---

## Real-Time Constraints

### Position Limits

| Constraint | Scope | Default | Enforcement |
|------------|-------|---------|-------------|
| Max shares per symbol | Per-symbol | configured per ticker | Reject if post-fill exceeds limit |
| Max notional per symbol | Per-symbol | % of NAV | Reject based on mark-to-market notional |
| Max symbols held | Portfolio | configurable | Reject new-name orders at capacity |
| Max position as % of ADV | Per-symbol | 1% of 20-day ADV | Prevent outsized participation |

### Exposure Limits

| Constraint | Definition | Action on breach |
|------------|-----------|------------------|
| Max gross | Σ\|long\| + \|short\| / NAV | Block new; begin unwinding if sustained |
| Max net | (long − short) / NAV | Block directional that increases |
| Max sector gross | Sector notional / NAV | Block same-sector orders |
| Max single-name concentration | One position / gross | Reject orders increasing concentration |

### Drawdown Gates

| Level | Trigger | Response |
|-------|---------|----------|
| Warning | Intraday PnL < −0.5% NAV | Log alert; tighten sizing to 50% |
| Throttle | Intraday PnL < −1.0% NAV | Cancel open; reduce sizing to 25%; no new positions |
| Circuit breaker | Intraday PnL < −1.5% NAV | Cancel all; positions monitored with stops |
| Kill switch | Intraday PnL < −2.0% NAV | Flatten all; halt for the day |

Drawdown thresholds are configurable. PnL is mark-to-market using
last NBBO mid. **Ownership boundary**: this skill defines the policy
(thresholds and responses). The live-execution skill owns the
mechanism layer (kill switch, circuit breaker, capital throttle).

### Volatility-Adjusted Sizing

```
target_risk = risk_budget_bps × NAV
position_size = target_risk / (realized_vol × vol_scalar)
position_size = min(position_size, max_position_limit, adv_limit)
```

The default `BudgetBasedSizer` (`risk/position_sizer.py`) applies
regime-dependent scaling drawn from `RegimeEngine.current_state`
(read-only). E.g., `vol_breakout` → 0.5×, `normal` → 1.0×.

---

## Hazard-Driven Exit

`HazardExitController` (`risk/hazard_exit.py`) consumes
`RegimeHazardSpike` events from `RegimeHazardDetector` (services
package) and emits `OrderRequest` exits for open positions when a
regime flip is imminent.

| Reason | Trigger | Suppression |
|--------|---------|-------------|
| `HAZARD_SPIKE` | Posterior departure exceeds per-alpha `hazard_score_threshold` AND position open ≥ `min_age_seconds` | Per `(symbol, alpha_id, departing_state)` — at most one spike-exit per departure episode |
| `HARD_EXIT_AGE` | Position open ≥ `hard_exit_age_seconds` | Per-symbol `hard_exit_suppression_seconds` |

Behavior:

- Wired behind alpha-level `hazard_exit.enabled: true` (default off,
  v0.2-compatible)
- Bit-identical replay (Inv-5) — verified by the Level-1 + Level-4
  hazard-exit replay tests
- The controller never closes a position on its own initiative
  without a triggering event; the spike merely surfaces a
  microstructure signal

See the regime-detection skill for the hazard detector itself.

---

## Regime Detection

The risk engine consumes regime state from the platform-level
`RegimeEngine` service (services package). Read-only access via
`current_state(symbol)`. **Ownership boundary**:

- microstructure-alpha defines the regime taxonomy (what regimes exist)
- regime-detection owns the platform-level service (the writer/reader contract)
- this skill owns the risk response to regime transitions
- post-trade-forensics audits classification accuracy

When forensic and risk-engine regime labels diverge, use the **more
conservative** classification.

### Volatility Regime

| Regime | Detection | Risk response |
|--------|-----------|---------------|
| Low | Realized vol < 20th percentile | Normal sizing |
| Normal | 20–80th | Normal sizing |
| Elevated | 80–95th | Reduce to 50%; widen stops |
| Crisis | > 95th or vol spike > 3× rolling mean | Reduce to 25%; activate circuit breaker eval |

### Correlation Clustering

| Condition | Detection | Response |
|-----------|-----------|----------|
| Correlation spike | Mean pairwise corr > 0.7 | Reduce gross exposure; alert |
| Directional clustering | > 80% positions same-sign beta | Flag concentration; enforce net cap |
| Correlation breakdown | Historically stable correlations diverge | Re-evaluate hedges; manual review |

### Concentration Risk

| Metric | Threshold | Action |
|--------|-----------|--------|
| Notional Herfindahl | > 0.25 | Alert; block further concentration |
| Top-3 weight | > 60% gross | Reduce or block |
| Sector Herfindahl | > 0.35 | Alert; enforce sector caps |

---

## Risk-Neutral Overlays

### Beta Hedge

```
portfolio_beta = Σ position_i × beta_i / NAV
hedge_needed   = (portfolio_beta − target_beta) × NAV
```

Hedge orders route through the same risk engine — they are not exempt
from limits or exposure checks.

### Dynamic Exposure Scaling

```
effective = base × regime_scalar × health_scalar × drawdown_scalar
```

Scalars multiply — compounding reduces exposure aggressively when
multiple risk signals fire simultaneously.

### Emergency De-Leveraging

| Phase | Trigger | Action |
|-------|---------|--------|
| 1 — Reduce | 2+ warning-level signals | Cut new sizes by 50% |
| 2 — Defensive | Any throttle-level + elevated vol | Cancel open; reduce positions to 50% |
| 3 — Flatten | Kill-switch trigger or 3+ throttle signals | Market-order flatten; halted state, irreversible without manual restart |

---

## Real-Time PnL Attribution

Tracked continuously, updated on every fill and every quote.

| Component | Definition |
|-----------|-----------|
| Gross PnL | Mark-to-market change |
| Realized PnL | Closed-trade P/L |
| Unrealized PnL | Open-position MTM |
| Transaction costs | Commissions + fees |
| Slippage cost | Fill vs reference at signal time |
| Net PnL | Gross − costs − slippage |

### Attribution Sources

```
total_return = alpha + beta_return + slippage + spread_cost + timing_cost + fees
```

Computed per-trade and aggregated at strategy + portfolio level.
Rolling windows (1 hr, session, daily) for monitoring.

**Ownership boundary**: this skill computes real-time attribution
for operational risk. The post-trade-forensics skill performs deeper
forensic attribution over multi-day windows including per-mechanism
decomposition (`MultiHorizonAttributor`) — same framework, longer
window, different purpose.

### Reconciliation

| Check | Frequency | Action on failure |
|-------|-----------|-------------------|
| PnL vs position × price change | Every quote | Alert; re-derive from fills |
| Σ attributed = total | Every trade | Alert; flag attribution model |
| Internal vs broker | End of day | Investigate; broker is authoritative |

---

## Risk Budget Allocation

### Per-Strategy Budgets

| Parameter | Scope | Purpose |
|-----------|-------|---------|
| Max drawdown | Per-strategy | Independent kill switch per strategy |
| Capital allocation | Per-strategy | Fraction of NAV available |
| Position limit | Per-strategy per-symbol | Prevent monopolizing a name |
| Correlation budget | Cross-strategy | Limit aggregate correlated exposure |

### Portfolio Governor

Aggregate constraints no single strategy can evaluate alone:

- Total gross across all strategies
- Total drawdown (diversified)
- Net beta exposure
- Aggregate concentration across strategies holding the same name

If aggregate constraints bind, the governor reduces the most recently
submitted order first (LIFO priority for risk reduction).

---

## Event Interface

| Event | Source | Key fields |
|-------|--------|-----------|
| `RiskVerdict` | `RiskEngine` | `action: RiskAction`, `reason`, `scaling_factor`, `constraints` |
| `StateTransition` | Risk-escalation SM | `machine_name="risk_escalation"`, from/to, trigger |
| `Alert` | Orchestrator / risk | `severity: AlertSeverity`, `alert_name`, context |
| `KillSwitchActivation` | Orchestrator | `reason`, `activated_by` |

`OrderRequest.reason` is set to `"SIGNAL"`, `"PORTFOLIO"`,
`"HAZARD_SPIKE"`, or `"HARD_EXIT_AGE"` depending on the upstream path,
giving post-trade forensics a clean lineage axis.

---

## Failure Modes

| Failure | Detection | Response |
|---------|-----------|----------|
| Stale NBBO | Heartbeat monitor on quote stream | Use last-known; flag stale; block new orders if sustained |
| Risk-engine crash | Watchdog process | Kill switch activates; no orders route |
| PnL calculation error | Reconciliation check fails | Halt new orders; re-derive PnL from fills |
| Regime model divergence | Backtest vs live disagreement | Use more conservative classification |
| Clock desync | Drift detection (Inv-10) | Use earlier timestamp; alert |

The risk engine is a **hard dependency** for order flow. If
unavailable, the system cannot trade. By design.

---

## Integration Points

| Dependency | Interface |
|------------|-----------|
| System Architect | Clock, EventBus, layer boundaries, `PositionStore` |
| Live Execution | Order routing gate; safety controls coordination; execution-quality health signal |
| Backtest Engine | Shared risk-check logic; deterministic replay of risk decisions |
| Microstructure Alpha | `Signal` events with `SignalDirection`, `trend_mechanism`; entry / exit conditions |
| Composition Layer | `SizedPositionIntent` consumed via `check_sized_intent`; per-leg veto |
| Regime Detection | `current_state(symbol)` for sizing scalars; `RegimeHazardSpike` for hazard exits |
| Data Engineering | Real-time NBBO feed for MTM and vol estimation |
| Post-Trade Forensics | `OrderRequest.reason` lineage; per-mechanism attribution |
| Alpha Lifecycle | Quarantine demotion; capital-tier scaling |

The risk engine sits between every alpha layer and execution in
backtest, paper, and live. Same logic, same constraints, same
fail-safe behavior — mode-specific differences are confined to
`ExecutionBackend` (`execution/backend.py`).
