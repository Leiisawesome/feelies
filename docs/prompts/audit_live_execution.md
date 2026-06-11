# Live execution & broker integration audit (Claude Code)

Use this prompt in a **Claude Code** session with full repo access. Scope: feelies live
order path — `live_router`, `paper_backend`, order-lifecycle state machine, the IB broker
adapter, idempotency, and kill-switch safety — and its **parity with backtest** (Inv-9).

---

## Mission

You are a senior live-trading systems engineer and safety auditor. Perform a
**read-only, evidence-based audit** of the feelies live/paper execution path.

**Primary focus:** This is where simulation meets real capital. The platform's entire
research edge is only valid if live execution behaves *identically* to backtest behind
the `ExecutionBackend` seam (Inv-9). Order duplication, lost acks, a kill switch that
fails open, or mode-specific logic leaking outside the seam are P0.

**Goal:** Identify where live behavior diverges from backtest, where the order-lifecycle
SM mishandles partial fills / reconnects, where idempotency could break, and where safety
controls fail-safe vs. fail-open — without breaking invariants.

**Do not implement fixes in this pass.** Deliver a structured audit report with
file/line citations, severity, and prioritized recommendations.

---

## Platform context (read first)

1. Read `.cursor/skills/live-execution/SKILL.md` end-to-end.
2. Read `.cursor/skills/backtest-engine/SKILL.md` § on the shared `ExecutionBackend`.
3. Read `docs/paper_rth_test_runbook.md` and `AGENTS.md` § Paper RTH.
4. Read `.cursor/rules/platform-invariants.mdc` Inv-9 (parity), Inv-11 (fail-safe),
   Inv-10 (clock).

**Architecture (contractual):**

```
OrderRequest
  → ExecutionBackend (paper/live) → live_router → broker (IB) adapter
  → order_state SM (NEW → SUBMITTED → ACK → PARTIAL/FILLED/CANCELLED/REJECTED)
  → fills reconcile → PositionStore
  kill_switch / safety controls gate the whole path
```

- **Single seam:** only `ExecutionBackend`-bound code differs between modes.
- **Idempotency:** order IDs / correlation IDs prevent duplicate submission.
- **Fail-safe:** kill switch and safety controls only *tighten* autonomously (Inv-11).

**Hard invariants (non-negotiable):**

- Inv-9: backtest/live parity — shared core; divergence is a flaggable defect.
- Inv-10: timestamps via injectable clock; no raw `datetime.now()` in core.
- Inv-11: fail-safe — errors / unknown states → reduced exposure; kill switch fails closed.

---

## Scope — files to audit

### Live path & seam

- `src/feelies/execution/backend.py`, `paper_backend.py`
- `src/feelies/execution/live_router.py`
- `src/feelies/execution/order_state.py` — order-lifecycle state machine
- `src/feelies/execution/trading_session.py` — session gating

### Broker adapter

- `src/feelies/broker/ib/connection.py` — connect / reconnect / auth
- `src/feelies/broker/ib/router.py` — order submission / cancel / fill callbacks
- `src/feelies/broker/ib/contracts.py` — contract resolution

### Safety

- `src/feelies/monitoring/kill_switch.py` (cross-ref `audit_monitoring_safety.md`)

### Operator scripts

- `scripts/verify_ib_broker.py` — broker connectivity preflight
- `scripts/run_paper.py`, `run_paper_soak.py` (*touchpoints* — owned by
  `audit_harness_cli.md`; here only the safety wiring they invoke)

### Tests (spec + gap analysis)

- `tests/broker/ib/test_ib_connection.py`, `test_ib_router.py`,
  `test_router_market_order.py`, `test_ib_functional.py` (network; note, don't require)
- `tests/execution/test_paper_backend.py`, `test_order_state.py`,
  `test_router_parity.py`, `test_router_latency.py`, `test_router_wiring.py`
- `tests/paper/test_smoke_config.py` (paper smoke-config contract)
- Integration: `tests/integration/test_paper_rth_e2e.py`,
  `tests/integration/test_paper_rth_safety.py`
- `tests/monitoring/test_kill_switch.py`

**Out of scope:** backtest fill model internals (see `audit_execution_fills.md`), risk
sizing, signal logic.

---

## Audit dimensions (answer each with evidence)

### A. Backtest/live parity (Inv-9) — highest priority

1. Enumerate every place live/paper code differs from backtest. Is each difference
   strictly behind `ExecutionBackend`, or is there mode-specific logic leaking into core?
2. Same `OrderRequest` type, same event types, same normalizer/clock across modes?
3. `test_router_parity.py`: what does it pin? Where could behavior silently diverge?

### B. Order-lifecycle state machine

1. Formalize the `order_state` SM (states + legal transitions). Are illegal transitions
   rejected?
2. Partial fills: position reconciliation correct and idempotent? Over/under-fill guard?
3. Reconnect mid-order: can a re-sync double-count or lose a fill? Orphan orders on
   disconnect?
4. Reject / cancel paths: fail-safe (no phantom position)?

### C. Idempotency

1. How are order IDs / correlation IDs generated, and do they prevent duplicate
   submission across retries/reconnects?
2. Replayed or duplicated broker callbacks: deduplicated?

### D. Broker adapter (IB)

1. `connection.py`: reconnect backoff, auth-failure handling, subscription validation.
2. `router.py`: submit/cancel/modify mapping; fill-callback parsing; error codes →
   fail-safe?
3. `contracts.py`: contract resolution correctness (wrong contract = wrong instrument).

### E. Safety & kill switch

1. Kill switch: does it **fail closed** (halt/flatten) on trigger and on its own error?
2. Triggers: which conditions arm it? Coverage gaps (latency, PnL, data staleness)?
3. Clock: any `datetime.now()` in core live logic (Inv-10)?

### F. Test & validation gaps + prioritized recommendations

1. Map invariants (parity, SM legality, idempotency, fail-closed kill switch) to tests —
   **covered / partial / missing**.
2. Note which behaviors are only covered by `paper_rth` (gated, network) tests.
3. Propose **minimal** new tests (SM property tests, reconnect/dup-callback sim) — specs.
4. Tiers:
   - **P0:** parity leakage, duplicate orders, lost fills, kill switch fail-open,
     wall-clock in core.
   - **P1:** reconnect edge cases, contract-resolution gaps, weak idempotency.
   - **P2:** richer broker error handling, observability.

Each item: component, `file:line`, one-sentence fix, expected impact.

---

## Working method

1. Build a **live-path inventory** (backend, router, SM states, kill-switch triggers,
   broker callbacks).
2. Audit the `ExecutionBackend` seam for parity leakage first.
3. Audit the order-lifecycle SM and idempotency.
4. Audit the IB adapter and kill switch.
5. Run **read-only** checks only:
   - `uv run pytest tests/execution/test_order_state.py tests/execution/test_paper_backend.py tests/execution/test_router_parity.py -q`
   - `uv run pytest tests/broker/ib/test_ib_connection.py tests/broker/ib/test_ib_router.py -q`
   - `uv run pytest tests/monitoring/test_kill_switch.py -q`
   - Note `paper_rth` tests require IB Gateway + `MASSIVE_API_KEY` + RTH; do not run.
   Do not modify production code.

---

## Output format (strict)

Write the audit report to `docs/audits/live_execution_audit_YYYY-MM-DD.md` with these sections:

1. **Executive summary** (≤15 bullets): top safety/parity risks first.
2. **Live-path inventory** (markdown table).
3. **Parity audit** (every mode difference — largest section).
4. **Order-lifecycle SM audit** (states, partial fills, reconnect).
5. **Idempotency audit**.
6. **Broker adapter audit (IB)**.
7. **Safety / kill-switch audit**.
8. **Test gap matrix** (note gated `paper_rth` coverage).
9. **Prioritized backlog** (P0/P1/P2, effort S/M/L).
10. **Appendix:** open questions needing a live/paper session.

Use code citations as `path:line` for every non-trivial claim.
Distinguish **implementation bug** vs **documented limitation** vs **intentional design**.

---

## Quality bar

- Prefer **falsifiable** statements ("on IB reconnect, `router` resubmits without checking
  the existing order ID → duplicate order") over adjectives.
- Treat any duplicate-order or lost-fill path as a P0.
- The kill switch must fail **closed**; any fail-open path is a P0.
- Respect Inv-9: any behavior that differs between backtest and live outside the seam is
  a defect, not a feature.

---

## Optional follow-ups (paste after the audit)

- *"After the report, draft P0 fixes only for order idempotency on reconnect and kill-
  switch fail-closed behavior as a follow-up PR plan."*
- *"Enumerate every difference between `paper_backend` and `backtest_backend` and classify
  each as in-seam vs leakage — audit commentary only."*
