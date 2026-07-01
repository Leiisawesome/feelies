# Execution: fill model, cost model & backtest realism audit (Claude Code)

Use this prompt in a **Claude Code** session with full repo access. Scope: feelies
backtest execution — fill simulation, cost model, latency injection, routers, MOC
mechanics, tick-size / regulatory rounding — from `OrderRequest` → simulated `Trade`.
This is the **PnL believability** layer.

---

## Mission

You are a senior execution-quant and backtest-realism auditor. Perform a **read-only,
evidence-based audit** of the feelies execution/fill path in simulation.

**Primary focus:** Every backtest PnL number the platform reports is a function of this
layer. Optimistic fills, mis-modeled queue position, missing latency, or lookahead in
fill timing invalidates all research and every promotion gate. Inv-12 demands the edge
survive 1.5× cost and 2× latency.

**Goal:** Identify where fill/cost modeling is conservative vs. optimistic, where latency
is wired vs. defaulted to zero, where backtest fills could peek at future prices, and what
changes would yield **realistic, fail-safe** simulated execution — without breaking
invariants.

**Do not implement fixes in this pass.** Deliver a structured audit report with
file/line citations, severity, and prioritized recommendations.

---

## Agent context (mandatory)

| Step | Resource |
|------|----------|
| 1 | `.cursor/rules/platform-invariants.mdc` — **Inv-6, 9, 12**; glossary: backtest, simulation |
| 2 | `.cursor/rules/karpathy-guidelines.mdc` |
| 3 | `.cursor/skills/README.md` |
| 4 | `.cursor/skills/backtest-engine/SKILL.md` (**owner**) — read **Not shipped** in `fill-model.md` / `stress-testing.md` |
| 5 | `.cursor/skills/live-execution/SKILL.md` — shared `ExecutionBackend` parity |
| 6 | `src/feelies/core/inv12_stress.py` — `--inv12-stress` touchpoint (owned by `audit_core_clock_config.md`) |

Optional: `.cursor/skills/backtest-engine/fill-model.md`, `.cursor/skills/backtest-engine/stress-testing.md`.


Before running commands, follow `AGENTS.md` for environment/test guidance. If Claude Code
also loads `CLAUDE.md`, `AGENTS.md`, this prompt, and `.cursor/rules/` /
`.cursor/skills/` context take precedence for audit execution.

**Shipped vs Not shipped:** Treat skill sections marked **Not shipped** as design
targets — P0 only if code/tests claim they are live.

**Finding bar:** P0/P1 items must cite `Inv-N` + `path:line`. Read-only pass per
`.cursor/rules/karpathy-guidelines.mdc`.

---

## Platform context (read first)

**Docs and config** (after Agent context):

1. Read `docs/three_layer_architecture.md` §12 (determinism/parity) and §7 (micro SM
   M6 order/fill stages).


**Architecture (contractual):**

```
OrderRequest
  → ExecutionBackend (backtest) → router (market / passive-limit / MOC)
  → fill model: market_fill / moc_fill, queue + latency + cost_model
  → tick_size / regulatory rounding (borrow, PDT)
  → simulated Trade → PositionStore / PnL
```

- **Single seam:** mode-specific code lives only behind `ExecutionBackend`.
- **Latency:** market-data latency vs submit/fill latency are distinct (BT-17).
- **Cost:** `cost_model` produces realistic half-spread + impact + fees.

**Hard invariants (non-negotiable):**

- Inv-5: deterministic replay (Level fill/order parity).
- Inv-6: a fill at sim-time T uses only prices visible at ≤ T (no lookahead).
- Inv-9: backtest/live parity — shared core; divergence is a defect.
- Inv-12: survive 1.5× cost and 2× latency; `expected_edge > 1.5× round_trip_cost`.

---

## Scope — files to audit

### Backend & routers

- `src/feelies/execution/backend.py` — `ExecutionBackend` / `MarketDataSource` contract
- `src/feelies/execution/backtest_backend.py`, `backtest_router.py`
- `src/feelies/execution/passive_limit_router.py`, `min_cost_policy.py`
- `src/feelies/execution/order_state.py` — order lifecycle
  (`intent.py` / `SignalPositionTranslator` is a *touchpoint only* — the
  signal→position decision is owned by `audit_position_management.md`)

### Fill & cost models

- `src/feelies/execution/market_fill.py`, `_fill_helpers.py`
- `src/feelies/execution/moc_fill.py`, `moc_session.py` — market-on-close mechanics
- `src/feelies/execution/cost_model.py` — half-spread / impact / fees
- `src/feelies/execution/tick_size.py` — price rounding to tick
- `src/feelies/execution/regulatory/borrow_availability.py`, `pdt_constraint.py`
- `src/feelies/execution/trading_session.py` — RTH / session boundaries
- `src/feelies/core/inv12_stress.py` — cost/latency stress harness

### Tests (spec + gap analysis)

- `tests/execution/test_cost_model.py`, `test_moc_fill.py`, `test_tick_size.py`,
  `test_round_trip_cost_estimate.py`, `test_depth_aware_estimate.py`,
  `test_min_cost_policy.py`, `test_stop_slippage.py`, `test_backtest_router.py`,
  `test_passive_limit_router.py`, `test_router_latency.py`, `test_trading_session.py`
  (note: `market_fill.py` has **no dedicated test module** — its coverage is embedded in
  router/orchestrator tests; flag this in the test-gap matrix)
- `tests/execution/regulatory/test_borrow_availability.py`, `test_pdt_constraint.py`
- Acceptance: `tests/acceptance/test_bt11_parity_post_fill_model.py`,
  `test_bt14_tick_rounding.py`, `test_bt16_rth_session.py`,
  `test_bt17_market_data_latency.py`, `test_bt18_ex_date_guard.py`,
  `test_inv12_stress_gate.py`, `test_backtest_app_baseline.py`
- Integration: `tests/integration/test_moc_imbalance_e2e.py` (MOC session mechanics)

**Out of scope:** live broker/router (see `audit_live_execution.md`), risk sizing,
signal logic, and the signal→intent position decision / exit economics (see
`audit_position_management.md`).

---

## Audit dimensions (answer each with evidence)

### A. Fill realism & lookahead (Inv-6) — highest priority

1. Trace a market fill: which price/quote does it use, and is that quote's **visibility
   time ≤ fill sim-time**? Any use of the trade/quote that triggered the decision (same
   tick) as the fill price (lookahead)?
2. Queue position / partial fills: is queue uncertainty modeled, or are passive limits
   assumed filled optimistically?
3. Stop slippage (`test_stop_slippage.py`): conservative on adverse moves?
4. MOC fills (`moc_fill.py`): use the official close, and is timing causal?

### B. Cost model (Inv-12)

1. `cost_model.py`: decompose half-spread + impact + fee. Are impact and fees realistic
   for the symbol cohort, or zero/under-modeled?
2. Round-trip cost estimate vs the alpha's disclosed `cost_arithmetic` — do they agree?
3. Stress harness `inv12_stress.py`: does 1.5× cost / 2× latency actually flow into fills,
   and does the acceptance gate enforce edge survival?

### C. Latency injection (BT-17)

1. Market-data latency vs submit/fill latency: distinct, or conflated/double-counted?
2. Default values: is latency defaulted to 0 anywhere that a production backtest would
   use? Is that flagged unsafe?
3. Wiring: is latency sourced from bootstrap/config and applied via the injectable clock?

### D. Tick-size & regulatory realism

1. `tick_size.py`: rounding direction — does it ever round in the strategy's favor?
2. `src/feelies/execution/regulatory/borrow_availability.py`: shorts blocked when unavailable (fail-safe)?
3. `pdt_constraint.py`: pattern-day-trade limits enforced where applicable?
4. Ex-date guard (`test_bt18_ex_date_guard.py`): dividends/splits handled?

### E. Session mechanics

1. `trading_session.py` / RTH: orders outside session rejected/queued correctly?
2. MOC session: imbalance/auction timing modeled causally?

### F. Backtest/live parity (Inv-9)

1. Is fill/cost/latency logic shared with live behind `ExecutionBackend`, or duplicated
   and at risk of drift?
2. `test_bt11_parity_post_fill_model.py`: what exactly does it pin? Gaps?

### G. Test & validation gaps + prioritized recommendations

1. Map invariants (no-lookahead fills, cost realism, latency wiring, conservative
   rounding, parity) to tests — **covered / partial / missing**.
2. Propose **minimal** new tests (golden fill replay, adversarial lookahead probe) —
   specs only.
3. Tiers:
   - **P0:** fill lookahead, optimistic fills that don't survive stress, latency=0 in
     prod backtest, rounding in strategy's favor, non-determinism.
   - **P1:** under-modeled impact/fees, parity drift, queue optimism.
   - **P2:** richer impact model, calibration from cached data.

Each item: component, `file:line`, one-sentence fix, expected impact on PnL realism.

---

## Working method

1. Build an **execution inventory** (routers, fill models, cost components, latency
   knobs, rounding rules).
2. Audit fill lookahead first — trace one fill end-to-end against visibility time.
3. Audit cost model + stress harness; reconcile with alpha cost disclosures.
4. Audit latency wiring and tick/regulatory rounding.
5. Cross-check findings against the owning skill's **Not shipped** sections before filing P0 on absent features.
6. Run **read-only** checks only:
   - `uv run pytest tests/execution/ -q`
   - `uv run pytest tests/acceptance/test_bt11_parity_post_fill_model.py tests/acceptance/test_bt14_tick_rounding.py tests/acceptance/test_bt17_market_data_latency.py tests/acceptance/test_inv12_stress_gate.py -q`
   - `uv run pytest tests/acceptance/test_backtest_app_baseline.py -q` (needs disk cache APP/2026-03-26)
   Do not modify production code.

---

## Output format (strict)

Write the audit report to `docs/audits/execution_fills_audit_YYYY-MM-DD.md` with these sections:

1. **Executive summary** (≤15 bullets): top PnL-realism risks first.
2. **Execution inventory** (markdown table).
3. **Fill realism & lookahead audit** (deep dive — largest section).
4. **Cost model & Inv-12 stress audit**.
5. **Latency injection audit** (market-data vs fill).
6. **Tick-size & regulatory audit**.
7. **Backtest/live parity audit**.
8. **Test gap matrix**.
9. **Prioritized backlog** (P0/P1/P2, effort S/M/L).
10. **Appendix:** open questions needing data runs.

Use code citations as `path:line` for every non-trivial claim.
Distinguish **implementation bug** vs **modeling choice** vs **intentional design**.

---

## Quality bar

- Prefer **falsifiable** statements ("market_fill uses the decision-triggering quote as
  the fill price → 1 half-spread of lookahead profit per fill") over adjectives.
- Treat any fill lookahead as a P0 — it inflates every backtest.
- Every rounding/fill choice should err **against** the strategy, never for it.
- Respect deterministic replay: no fixes that introduce randomness or wall-clock.

---

## Optional follow-ups (paste after the audit)

- *"After the report, draft P0 fixes only for fill-price visibility and latency-default
  safety as a follow-up PR plan."*
- *"Reconcile each alpha's disclosed `cost_arithmetic` against the `cost_model` output on
  disk cache APP/2026-03-26 — methodology only, no code."*
- *"Run an adversarial lookahead probe spec for `market_fill` — describe the test, don't
  implement it."*
