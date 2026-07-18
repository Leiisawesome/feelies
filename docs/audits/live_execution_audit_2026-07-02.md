# Live Execution & Broker Integration Audit — 2026-07-02

**Scope:** the feelies live order path — `execution/backend.py`, `paper_backend.py`,
`live_router.py`, `execution/order_state.py`, `execution/trading_session.py`,
`broker/ib/{connection,router,contracts}.py`, `monitoring/kill_switch.py` — and its parity
with backtest (Inv-9) per `docs/prompts/audit_live_execution.md`. Read-only pass; no
production code, baseline, config, or ledger was modified.

**Method:** read the mandatory agent context (`platform-invariants.mdc`,
`karpathy-guidelines.mdc`, skills README, `live-execution` + `backtest-engine` SKILLs and
their `order-lifecycle.md` / `safety-controls.md` references), then the full scope file
list plus `kernel/orchestrator.py` (the order-lifecycle owner — `_apply_ack_to_order`,
`_reconcile_fills`, `_escalate_risk`, `unlock_from_lockdown`, `_build_order_from_intent`,
the emergency-flatten path), `bootstrap.py` (mode wiring), `risk/escalation.py`,
`core/identifiers.py`, `monitoring/in_memory.py`, `scripts/run_paper.py`,
`scripts/run_paper_soak.py`, `scripts/verify_ib_broker.py`, `docs/paper_rth_test_runbook.md`,
and every test file named in the prompt. Ran (read-only, after `uv sync --all-extras`):

```
pytest tests/execution/test_order_state.py tests/execution/test_paper_backend.py \
       tests/execution/test_router_parity.py -q        → 24 passed
pytest tests/broker/ib/test_ib_connection.py tests/broker/ib/test_ib_router.py -q → 47 passed
pytest tests/monitoring/test_kill_switch.py -q          → 5 passed
```

`paper_rth` / `functional` network tests were **not run** (require IB Gateway + RTH +
`MASSIVE_API_KEY`) — read only, per instructions.

Severity legend (per task brief): **P0** parity leakage, duplicate orders, lost fills, kill
switch fail-open, wall-clock in core. **P1** reconnect edge cases, contract-resolution gaps,
weak idempotency. **P2** richer broker error handling, observability. Each finding is tagged
**[bug] / [limitation] / [design]** — "limitation" means a gap the owning skill already
documents as **Not shipped**; "bug" means shipped code that misbehaves relative to its own
contract or to backtest.

---

## 1. Executive summary

1. **Scoping fact, not a defect:** `OperatingMode.LIVE` / `ExecutionMode.LIVE` has **no
   implementation**. `LiveOrderRouter.__init__` unconditionally raises `NotImplementedError`
   (`execution/live_router.py:24-28`), and `bootstrap._create_backend` raises for any mode
   other than `BACKTEST`/`PAPER` (`bootstrap.py:1086-1089`, `"Live router is future work"`).
   The only real-time, real-broker path today is **PAPER** (`IBOrderRouter` + IB Gateway
   paper account on :4002, real-time Massive WS feed). All findings below are about PAPER
   mode; "live" in this report means PAPER unless stated otherwise.
2. **[P0, bug] MOC orders are silently mis-routed through `IBOrderRouter`.** `OrderRequest.is_moc`
   (`core/events.py:340-342`) is set by the orchestrator whenever `strategy_id` is in
   `moc_strategy_ids` and MOC bounds resolved — **independent of `OperatingMode`**
   (`kernel/orchestrator.py:1267-1276`) — but `IBOrderRouter._build_ib_order`
   (`broker/ib/router.py:200-221`) never reads `request.is_moc` and builds a plain `MKT`/`LMT`
   order. A PAPER-mode MOC-tagged order fills immediately at submission instead of at the
   closing print. Currently **dormant**: no shipped config sets `moc_strategy_ids` (verified
   against `configs/*.yaml`), but nothing prevents it and no test would catch it (§8).
3. **[P0, bug] A pipeline exception during emergency flatten can silently orphan a live
   broker fill.** `_force_order_terminal_after_pipeline_error` (`orchestrator.py:5123-5183`),
   called only from `_emergency_flatten_all`'s exception handler
   (`orchestrator.py:3755-3768`), forces a tracked order to REJECTED/CANCELLED/EXPIRED and
   prunes it from `_active_orders` even when the broker may already have accepted (or will
   still fill) it. Any later real fill for that `order_id` is then dropped by the Inv-11
   unknown-order guards (`_apply_ack_to_order` `orchestrator.py:5377-5390`, `_reconcile_fills`
   `orchestrator.py:5620-5643`) instead of being reconciled. `unlock_from_lockdown`'s
   zero-exposure guard (`orchestrator.py:1666-1671`) trusts `PositionStore.total_exposure()`,
   which would read zero while the broker still holds the position — an operator could unlock
   trading believing exposure is flat. This is precisely the "Broker > internal (missed
   fill)" case the live-execution skill marks unimplemented, but it is reachable through
   *shipped* code (the emergency-flatten path itself is live), not just an absent feature.
4. **[P0, bug/limitation] No reconnect path exists; a mid-session IB Gateway drop orphans
   open orders with no automated detection.** `run_paper.py` calls
   `ib_connection.connect_and_start()` exactly once (`scripts/run_paper.py:244`) with no
   retry loop; `IBGatewayConnection` has no self-reconnect (`broker/ib/connection.py`);
   connectivity blips (codes 1100/1101/1102/2110) surface only as a WARNING `Alert`
   (`bootstrap.py:755-773`) with no automated response. The project's own runbook lists "IB
   Gateway kill mid-session" as a **manual** failure-injection scenario
   (`docs/paper_rth_test_runbook.md:69`), and the only two "reconnect" checks in the
   codebase — `test_ib_functional.py::TestIBGatewayReconnect` and
   `verify_ib_broker.py::check_reconnect` — both build a **brand-new** connection object with
   a **different client_id**; neither exercises resuming the same session's open orders.
   Since no `reqOpenOrders`/`reqExecutions` reconciliation-on-connect exists anywhere, an
   order open at disconnect time is invisible to whatever process/connection comes next.
5. **[P1, bug] RTH entry-suppression (BT-16) is wired into both backtest routers but absent
   from `IBOrderRouter`.** `BacktestOrderRouter` and `PassiveLimitOrderRouter` both bind
   `RthEntryFillGate`/`bind_position_qty` (`execution/backtest_router.py:196-200`,
   `execution/passive_limit_router.py:250-254`); `IBOrderRouter` implements neither. The
   orchestrator's own `_bind_router_position_qty_for_rth` treats this as an expected no-op
   via `getattr(router, "bind_position_qty", None)` (`orchestrator.py:1104-1121`). An entry
   generated outside configured RTH bounds is rejected immediately in backtest
   (`RTH_ENTRY_SUPPRESSED`) but forwarded to IB as a working DAY order in PAPER — a real,
   if bounded (IB's own session mechanics partially cover it differently), Inv-9 divergence.
6. **[P1, bug] Contract resolution never sets `primary_exchange`.** `IBOrderRouter._build_ib_order`
   calls `stock_contract(request.symbol)` with no override (`broker/ib/router.py:145`), even
   though `contracts.py`'s own docstring says the argument "exists because SMART routing
   requires it whenever a symbol is ambiguous (e.g. `MSFT` cross-listed)"
   (`broker/ib/contracts.py:4-6`). No per-symbol config or validation gate exists to prevent
   an ambiguous ticker resolving to the wrong instrument. No test file for `contracts.py`
   exists at all.
7. **[P1, documented limitation, escalated] No ack-timeout watchdog.** `IBOrderRouter.submit()`
   emits a synchronous ACKNOWLEDGED before the writer thread confirms transmission to IB
   (`broker/ib/router.py:151-162`) — intentional, mirrors `BacktestOrderRouter`
   (`execution/backtest_router.py:272-284`) for order-SM parity (Inv-9). The
   `order-lifecycle.md` skill already marks ack-timeout "NOT YET IMPLEMENTED"; this audit
   confirms no timer/reaper exists anywhere in `orchestrator.py` or `connection.py`. Combined
   with finding 4, an order can sit ACKNOWLEDGED forever with no broker confirmation ever
   having occurred and nothing will flag it.
8. **[good] The order-lifecycle state machine itself is sound and well tested.** The 9-state
   `OrderState` SM (`execution/order_state.py`) matches its own spec exactly; illegal
   transitions structurally raise `IllegalTransition` (`core/state_machine.py:124-160`);
   `test_order_state.py` exhaustively checks all four terminal states have zero outbound
   edges. `_apply_ack_to_order` exhaustively matches every `OrderAckStatus` and raises on an
   unhandled member (`orchestrator.py:5482-5485`) — fail-loud, not fail-silent.
9. **[good] Idempotency within a session is solid.** Both routers reject duplicate
   `order_id` submissions with an identically-shaped REJECTED ack
   (`execution/backtest_router.py:231-240`, `broker/ib/router.py:111-132`); `IBOrderRouter`
   converts IB's **cumulative** fill quantity/VWAP to **per-delta** values and drops
   duplicate-cumulative and regressed-cumulative callbacks (`broker/ib/router.py:312-337`,
   tested exhaustively in `test_ib_router.py`). Order IDs are SHA-256 of
   `correlation_id:sequence` (`core/identifiers.py:18-25`) — deterministic in backtest,
   collision-safe in PAPER because `correlation_id` embeds a real, ever-advancing exchange
   timestamp.
10. **[P2, bug] `IBOrderRouter._submitted_order_ids` never releases an id**, even after a
    terminal reject (contrast `BacktestOrderRouter._reject(..., release_submitted_id=True)`
    default). Low practical impact given deterministic, non-repeating order IDs, but it is an
    unnecessary asymmetry and an unbounded-growth set for the life of a PAPER process.
11. **[P2, limitation] `run_paper.py` only wires `SIGINT`, not `SIGTERM`**
    (`scripts/run_paper.py:231-234`) — the project's own runbook says as much ("Use `kill
    -INT` ... until SIGTERM handler is wired", `docs/paper_rth_test_runbook.md:74`).
12. **[P2, non-issue but Inv-10-adjacent] `datetime.now(UTC)` appears in `run_paper.py`
    (:140, :173) and `run_paper_soak.py` (:47)** — session-recorder / soak-summary metadata
    only, never fed into `Clock`, the tick pipeline, or any hashed artifact. Not a
    determinism risk (PAPER runs are not replay-hashed) but worth tightening for consistency
    with the DTZ rule's letter.
13. **[good] Zero mode-branching found in the tick-processing path.** Every
    `OperatingMode`/`ExecutionMode` check in the codebase is bootstrap-time wiring
    (`bootstrap.py`) or CLI/harness selection — never inside `orchestrator.py`'s tick methods,
    which the code itself asserts (`orchestrator.py:421`, `":  The orchestrator never
    inspects backend.mode to branch logic"`) and this audit found no counter-example to.
14. **[test-gap, high signal] `test_router_parity.py` does not test parity with IB at all.**
    Despite its name, it only pins `BacktestOrderRouter` vs. `PassiveLimitOrderRouter` fill
    economics (`tests/execution/test_router_parity.py:1-7`). There is **no** automated check
    that `IBOrderRouter` produces equivalent behavior to either backtest router for the same
    `OrderRequest` — which is exactly how findings 2 and 5 went uncaught.
15. **[good] Kill switch and escalation are fail-closed everywhere this audit could verify.**
    `bootstrap.py` always wires a real `InMemoryKillSwitch` (`bootstrap.py:562`, never
    `None` in production); the tick-start gate suppresses processing and degrades macro state
    when active (`orchestrator.py:2292-2311`); `_require_safe_session_entry` blocks starting
    any session while the switch is active or risk is non-NORMAL
    (`orchestrator.py:1087-1102`); `RiskLevel` escalation is monotonic and forward-only
    (`risk/escalation.py:29-59`). Deep kill-switch mechanism review is deferred to
    `audit_monitoring_safety.md` per the task brief.

---

## 2. Live-path inventory

| Component | File | Role | Mode(s) | Status |
|---|---|---|---|---|
| `ExecutionBackend` / `ExecutionMode` | `execution/backend.py` | Facade over `MarketDataSource` + `OrderRouter`; the one mode-specific seam | ALL | Shipped |
| `build_backtest_backend` / `build_passive_limit_backend` | `execution/backtest_backend.py` | Composes `ReplayFeed` + `BacktestOrderRouter`/`PassiveLimitOrderRouter` | BACKTEST | Shipped |
| `build_paper_backend` | `execution/paper_backend.py` | Composes `MassiveLiveFeed` + `IBOrderRouter` | PAPER | Shipped |
| `LiveOrderRouter` | `execution/live_router.py` | `OrderRouter` stub | LIVE | **Not implemented** — `__init__` raises |
| `BacktestOrderRouter` | `execution/backtest_router.py` | Cross-price taker fill sim, MOC, RTH gate | BACKTEST (`execution_mode: market`) | Shipped |
| `PassiveLimitOrderRouter` | `execution/passive_limit_router.py` | Queue-position fill sim, MOC, RTH gate | BACKTEST (`passive_limit`/`minimum_cost`) | Shipped |
| `IBOrderRouter` | `broker/ib/router.py` | Adapts `IBGatewayConnection` to `OrderRouter` | PAPER | Shipped — no MOC, no RTH gate (§3, §5) |
| `IBGatewayConnection` | `broker/ib/connection.py` | Threaded `ibapi` EClient/EWrapper, queue-based cross-thread comm | PAPER | Shipped — no reconnect (§6) |
| `stock_contract` | `broker/ib/contracts.py` | `ibapi.Contract` factory | PAPER | Shipped — `primary_exchange` never supplied (§6) |
| `OrderState` SM | `execution/order_state.py` | 9-state order lifecycle | ALL | Shipped, well tested |
| `TradingSessionBounds` / `RthEntryFillGate` | `execution/trading_session.py` | RTH entry suppression, holiday/early-close | Shared code, wired only into backtest routers | Not wired to `IBOrderRouter` |
| `KillSwitch` (Protocol) | `monitoring/kill_switch.py` | Emergency-halt contract | ALL | Shipped |
| `InMemoryKillSwitch` | `monitoring/in_memory.py` | Concrete kill switch, always wired at boot | ALL | Shipped |
| `Orchestrator._escalate_risk` / `unlock_from_lockdown` | `kernel/orchestrator.py` | R0→R4 escalation, human-gated recovery | ALL | Shipped |
| `Orchestrator._apply_ack_to_order` / `_reconcile_fills` | `kernel/orchestrator.py` | Ack→SM mapping, fill→position reconciliation | ALL | Shipped |
| `run_paper.py` | `scripts/run_paper.py` | PAPER entry point (boot → connect → run → teardown) | PAPER | Shipped — single connect, no reconnect loop, SIGINT only |
| `run_paper_soak.py` | `scripts/run_paper_soak.py` | Long-running soak wrapper (subprocess) | PAPER | Shipped — no restart-on-crash |
| `verify_ib_broker.py` | `scripts/verify_ib_broker.py` | Manual IB connectivity preflight | PAPER | Shipped |

---

## 3. Parity audit (Inv-9)

### 3.1 Mode reality check

Only two modes are constructible: **BACKTEST** (`ReplayFeed` + `BacktestOrderRouter`/
`PassiveLimitOrderRouter`) and **PAPER** (`MassiveLiveFeed` + `IBOrderRouter`, real-time data,
real (paper) broker account). `LIVE` is a `NotImplementedError` at both the router
(`execution/live_router.py:24-28`) and bootstrap (`bootstrap.py:1086-1089`) levels. Every
finding in this report about "live" behavior is about PAPER, which is architecturally the
live order path minus a production IB port (paper accounts run on :4002, live on :4001;
`bootstrap.py:266-270` even warns if a PAPER config points at :4001).

### 3.2 What is genuinely shared (the good news)

- The micro-state tick pipeline (`_process_tick_inner`, M0–M10) is one code path; the
  orchestrator's own comment asserts it never inspects `backend.mode`
  (`orchestrator.py:421`), and this audit found no counter-example — every
  `OperatingMode`/`ExecutionMode` check in the repo lives in `bootstrap.py` (composition-time
  wiring: clock selection, event-log ordering strictness, normalizer construction) or
  `harness/`/CLI code, never inside a tick-time method.
- `_build_order_from_intent` / `_try_build_order_from_intent` (`orchestrator.py:4676-4835`)
  is 100% shared: same edge-cost gate, same passive/aggressive routing decision, same
  `derive_order_id` formula, regardless of mode.
- `_apply_ack_to_order` and `_reconcile_fills` (`orchestrator.py:5367-5656`) consume the same
  typed `OrderAck`/`OrderAckStatus` from either router with no branching on origin.
- Both concrete routers (`BacktestOrderRouter`, `IBOrderRouter`) emit a synchronous
  ACKNOWLEDGED ack at `submit()` time and reject duplicate `order_id`s with an
  identically-shaped `OrderAck(status=REJECTED, reason="duplicate order_id: ...")` — this is
  explicit, commented parity intent on both sides (`execution/backtest_router.py:41-42,
  272-273`; `broker/ib/router.py:7-11`).
- `enforce_market_order` is deliberately relaxed for PAPER/LIVE event logs
  (`bootstrap.py:283-293`) because live feeds append in arrival order, not
  cross-symbol-timestamp order — a justified, documented, non-tick-path difference, not a
  defect.

### 3.3 Divergence catalog

| Behavior | Backtest (`BacktestOrderRouter`/`PassiveLimitOrderRouter`) | PAPER (`IBOrderRouter`) | Verdict |
|---|---|---|---|
| MOC (`is_moc=True`) orders | Held by `MocFillController` until the closing print (`moc_fill.py:71`) | **Ignored** — built as plain `MKT`/`LMT`, fills immediately (`broker/ib/router.py:200-221`) | **[P0 bug]** — silent economic divergence |
| RTH entry suppression | `RthEntryFillGate` rejects with `RTH_ENTRY_SUPPRESSED`/`MARKET_HOLIDAY` (`trading_session.py:114-135`, wired at `backtest_router.py:196-200`, `passive_limit_router.py:250-254`) | No gate; order forwarded to IB as a resting DAY order | **[P1 bug]** — behavior diverges (reject-now vs. queue-until-open), bounded by IB's own session mechanics |
| Contract resolution | N/A (no real instrument) | `stock_contract(symbol)` with no `primary_exchange` (`broker/ib/contracts.py` docstring flags this exact risk) | **[P1 bug]** — latent wrong-instrument risk for ambiguous symbols |
| Ack timing | Synchronous ACK at `submit()`, before any fill (`backtest_router.py:272-284`) | Synchronous ACK at `submit()`, before writer thread confirms to IB (`router.py:151-162`) | **[intentional design]** — parity by construction; risk is the *absence* of an ack-timeout watchdog (finding 7) |
| Duplicate order_id | Reject, id released for re-use (`backtest_router.py:231-240`) | Reject, id **never** released (`router.py:111-132`, `_submitted_order_ids` only grows) | **[P2 bug]** — asymmetric but low-impact given deterministic non-repeating ids |
| Event ordering strictness | Strict monotonic merge-key order; `ReplayFeed` raises `CausalityViolation` on violation | Relaxed (`enforce_market_order=False`) because live arrival order isn't cross-symbol monotonic | **[intentional design]**, documented at `bootstrap.py:283-293` |
| Clock | `SimulatedClock` | `WallClock` | **[intentional design]** — required; not a tick-path branch (`bootstrap.py:787-790`) |
| Cancel semantics | `cancel_order` synchronous where possible (MOC), otherwise duck-typed absent | `cancel_order` fire-and-forget, `True` means "enqueued," not "confirmed" (`router.py:176-189`) | **[intentional design]**, correctly documented in `backend.py:62-70` |
| Metrics granularity | `emit_reading_metrics=False` in BACKTEST | `True` in PAPER/LIVE (`bootstrap.py:1588`) | Cosmetic — telemetry volume only, no behavior difference |

### 3.4 `test_router_parity.py` — what it actually pins

Despite the name, `tests/execution/test_router_parity.py` (and `test_router_wiring.py`)
compare **`BacktestOrderRouter` against `PassiveLimitOrderRouter` only** — both simulated,
in-process fill models. There is no test anywhere that submits the same `OrderRequest` to
`IBOrderRouter` and either backtest router and compares the resulting ack shape/semantics.
This is the direct, falsifiable reason findings 2 and 5 are not caught by CI: the test that
sounds like it would catch a router-to-router behavioral drift structurally cannot, because
`IBOrderRouter` is outside its universe of comparison. See §8 for a proposed minimal test.

---

## 4. Order-lifecycle SM audit

### 4.1 States and legal transitions

`execution/order_state.py` defines 9 states exactly as specified in the owning skill:

```
CREATED → SUBMITTED
SUBMITTED → {ACKNOWLEDGED, REJECTED}
ACKNOWLEDGED → {PARTIALLY_FILLED, FILLED, CANCEL_REQUESTED, CANCELLED, EXPIRED, REJECTED}
PARTIALLY_FILLED → {PARTIALLY_FILLED, FILLED, CANCEL_REQUESTED, CANCELLED, EXPIRED}
CANCEL_REQUESTED → {CANCELLED, FILLED}
FILLED / CANCELLED / REJECTED / EXPIRED → {}  (terminal)
```

Every non-terminal state has an explicit exit set; there is no implicit/inferred state. This
matches `order-lifecycle.md` exactly, including the two audit-remediated edges
(`ACKNOWLEDGED → REJECTED` for post-ack risk-reject/deferred-fill rejects, and
`PARTIALLY_FILLED → {CANCEL_REQUESTED, CANCELLED, EXPIRED}` for cancel-the-remainder / TIF
expiry on a partial fill) — both are exercised by dedicated tests
(`test_acknowledged_to_rejected`, `test_partially_filled_to_cancel_requested`,
`test_partially_filled_direct_to_cancelled`, `test_partially_filled_to_expired` in
`tests/execution/test_order_state.py`).

### 4.2 Structural enforcement (verified, not assumed)

- `StateMachine.transition()` raises `IllegalTransition` for any edge not in the table
  (`core/state_machine.py:124-160`); `test_illegal_transition_created_to_filled` and
  `test_illegal_transition_created_to_acknowledged` confirm this raises rather than silently
  clamping or ignoring.
- `test_terminal_states_have_no_outbound` parametrizes over all four terminal states and
  asserts `can_transition()` is `False` for **every** `OrderState` member — a genuinely
  exhaustive check, not spot-checked.
- `_apply_ack_to_order` (`orchestrator.py:5367-5485`) exhaustively matches every
  `OrderAckStatus` member and `raise ValueError(...)` on anything unhandled
  (`:5482-5485`) — an enum-exhaustiveness guard that fails loud rather than silently dropping
  a future enum member.
- Acks that are structurally valid but inapplicable to the order's *current* SM state (e.g.
  a `CANCELLED` ack arriving after the order already reached `FILLED`) emit
  `ack_inapplicable_to_order_state` (`orchestrator.py:5487-5507`) instead of raising or
  silently discarding — full provenance (Inv-13) preserved even on the drop path.

### 4.3 Partial fills and reconciliation

`_reconcile_fills` (`orchestrator.py:5511-5656`) is careful and fail-safe by construction:

- Fee-only acks (CANCELLED/EXPIRED carrying `fees > 0`) are debited even with zero fill
  quantity (`:5530-5548`) — cancel/expiry fees are real costs.
- A FILLED/PARTIALLY_FILLED ack with `fill_price is None` or `filled_quantity <= 0` is
  rejected with `fill_ack_missing_price_or_quantity` rather than silently applying a
  zero/garbage delta (`:5565-5593`).
- A "fill-like" payload riding a non-fill status is rejected with
  `fill_payload_inconsistent_with_ack_status` (`:5594-5618`) — defends against a malformed
  upstream ack.
- Fills for an `order_id` not in `_active_orders` are rejected outright with
  `fill_for_unknown_order`, explicitly reasoning "cannot determine side (Inv-11 fail-safe)"
  (`:5620-5643`) — correct in isolation, but see §4.4 for how this same guard becomes a
  liability when the order was force-terminated *by the platform itself* while still open at
  the broker.

Race (fill vs. cancel): `CANCEL_REQUESTED → FILLED` is a legal transition and the fill always
wins over a racing cancel — verified by `test_fill_beats_cancel`. This matches the documented
contract exactly.

### 4.4 P0 — pipeline error during emergency flatten can strand a real fill

Full trace, `kernel/orchestrator.py`:

1. `_escalate_risk` reaches R3 `FORCED_FLATTEN` and calls `_emergency_flatten_all`
   (`:3636-3637`).
2. For each non-zero position, `_emergency_flatten_all` tracks the order, transitions it to
   `SUBMITTED`, calls `self._backend.order_router.submit(order)`, publishes the order, polls
   acks, applies them, and reconciles fills — all inside one `try` block (`:3721-3754`).
3. **Any** exception in that block (not just `submit()` — also the poll/apply/reconcile
   steps) is caught by a blanket `except Exception as exc` (`:3755`), which calls
   `_force_order_terminal_after_pipeline_error(order, exc, context="emergency_flatten")` when
   the order is still tracked (`:3763-3768`).
4. That helper (`:5123-5183`) forces the order's SM to the first of
   `REJECTED`/`CANCELLED`/`EXPIRED` that is legal from its current state, then calls
   `_prune_terminal_orders()` — **removing it from `_active_orders`**.
5. If the broker actually accepted (or later fills) that order — plausible, since the
   exception may have occurred *after* `submit()` succeeded, e.g. in ack polling or
   reconciliation — the eventual real `OrderAck` arrives for an `order_id` the platform no
   longer tracks. `_apply_ack_to_order` treats it as `ack_for_unknown_order`
   (`:5377-5390`) and `_reconcile_fills` treats it as `fill_for_unknown_order`
   (`:5620-5643`) — **both drop it**, by design, to avoid guessing a side for an unknown fill.
6. The residual-exposure check immediately after the flatten loop (`:3770-3793`) only sees
   what `PositionStore` already knows; it cannot detect a fill that hasn't arrived yet. It
   does raise `emergency_flatten_incomplete` (CRITICAL) if the *known* residual is non-zero,
   but a fill that lands *after* this check runs is invisible to it.
7. `unlock_from_lockdown` (`:1646-1688`) later gates recovery on
   `self._positions.total_exposure() == Decimal("0")` (`:1666-1671`) — exactly the quantity
   that would be wrong in this scenario.

This is the fail-safe design intent (never *guess* a side for an unknown fill, never
*increase* believed exposure) turned into its own failure mode: the platform can end up
believing it is flatter than it actually is, at the exact moment (R3→R4 lockdown) when that
belief gates whether a human is allowed to re-enable trading. **This is reachable through
shipped code** — the emergency-flatten path runs on every real R3 escalation — not a
"Not shipped" gap.

### 4.5 P0 — reconnect mid-order: orphan orders, no re-sync

No code path anywhere reconciles open orders against the broker after a connection is
(re)established. Confirmed by:

- **No API surface for it.** Neither `IBGatewayConnection` nor `IBOrderRouter` calls or
  handles `reqOpenOrders`/`reqExecutions`/`execDetails` (repo-wide grep: zero matches).
  `IBOrderRouter`'s `_meta`, `_last_cumulative`, `_last_cum_value`, `_submitted_order_ids` are
  plain in-process dicts/sets with no persistence and no re-hydration path.
- **No reconnect trigger in production code.** `run_paper.py` calls
  `ib_connection.connect_and_start()` exactly once (`:244`); there is no retry/backoff loop,
  and `on_alert_event` (wired at `bootstrap.py:755-773`) only publishes a WARNING `Alert` for
  connectivity codes 1100/1101/1102/2110 — nothing calls `connect_and_start()` again, flips
  the kill switch, or triggers `_escalate_risk`.
- **The only "reconnect" tests validate a different thing.** `test_ib_functional.py`'s
  `TestIBGatewayReconnect.test_reconnect_after_clean_disconnect` (`:356-381`) and
  `verify_ib_broker.py`'s `check_reconnect` (`:289-301`) both build a **new**
  `IBGatewayConnection` with a **different `client_id`** after the first one cleanly
  disconnected, and only assert the new connection gets a valid `next_order_id()`. Neither
  attaches an `IBOrderRouter` to the new connection, and neither asserts anything about
  orders that were open on the original connection. `test_ib_connection.py`'s
  `test_next_valid_id_never_regresses_on_reconnect_pulse` (`:72-88`) tests only that
  `nextValidId` bookkeeping doesn't regress on a *simulated* re-handshake pulse — again, no
  order state involved.
- **The project's own runbook confirms this is a known, unautomated gap.** The failure-
  injection table lists "IB Gateway kill mid-session → DEGRADED; no duplicate submits on
  restart" as a **manual** exercise (`docs/paper_rth_test_runbook.md:65-74`). "No duplicate
  submits on restart" holds today only incidentally — because `order_id` is derived from a
  real, ever-advancing exchange timestamp (`core/identifiers.py:9-15`, `:18-25`), a fresh
  process naturally won't regenerate a live order's id — but the runbook is silent on the
  graver risk: an order open at kill time is not merely at risk of duplication, it is
  **permanently untracked** by whatever process/session comes next.

Net effect: a mid-session IB Gateway restart, network blip, or process crash silently
converts any open order into an untracked position risk, discoverable only by an operator
manually reconciling against the IB TWS/Gateway UI. There is no DEGRADED transition, no
alert beyond a WARNING connectivity log line, and no code path that would surface this to the
kill switch or risk escalation.

### 4.6 Reject/cancel paths — fail-safe where checked

- Submit-time exceptions transition the order to REJECTED via `_reject_order_after_submit_failure`
  (`orchestrator.py:5086-5121`) — correct, since `submit()` raising means the broker almost
  certainly never saw the order (this differs from §4.4, where the exception occurs *after* a
  successful `submit()`).
- `shutdown()` best-effort resolves any lingering `CANCEL_REQUESTED` order to `CANCELLED`
  (`orchestrator.py:1746-1754`) and surfaces any still-non-terminal order as a WARNING
  `pending_orders_at_shutdown` alert (`:1757-1777`) rather than silently dropping it — good
  provenance, though (per §4.5) it cannot detect an order the platform has already forgotten.

---

## 5. Idempotency audit

### 5.1 Order ID generation

`derive_order_id(seed) = sha256(seed)[:16]` (`core/identifiers.py:18-25`), never `uuid4`. The
SIGNAL path seeds with `f"{correlation_id}:{seq}"` (`orchestrator.py:4696`); hazard/
emergency-flatten/degrade-flatten paths use distinguishing seed prefixes
(`f"emergency_flatten:{correlation_id}:{symbol}:{seq}"` at `:3703`,
`f"degrade_flatten:{reason}:{symbol}:{seq}"` at `:6683`, etc.). `correlation_id` itself embeds
`(symbol, exchange_timestamp_ns, sequence)` (`core/identifiers.py:9-15`). This formula is
shared verbatim across BACKTEST and PAPER — the same code, not parallel implementations —
so the only source of non-determinism in PAPER is real time and real fill arrival, which is
expected and explicitly out of scope for replay-hash parity
(`core/identifiers.py:36-38`: "acceptable: live is not replay-hashed").

### 5.2 Duplicate-submission handling — parity confirmed

| | `BacktestOrderRouter.submit()` | `IBOrderRouter.submit()` |
|---|---|---|
| Duplicate `order_id` | Reject via `append_reject_ack` (`market_fill.py:73-106`), same `OrderAck` shape | Reject inline (`router.py:118-131`), same `OrderAck` shape |
| Reason string | `f"duplicate order_id: {request.order_id}"` | `f"duplicate order_id: {request.order_id}"` (identical text) |
| `request_sequence` preserved | Yes | Yes |
| Id released after any reject | Yes (`release_submitted_id=True` default) | **No — never released** (§3.3, §9 P2) |

`verify_ib_broker.py::check_duplicate_submit` (`:130-162`) exercises this exact path against
a real IB Gateway and asserts exactly one ACKNOWLEDGED and one REJECTED.

### 5.3 Broker-callback dedup (`IBOrderRouter`)

This is the most carefully engineered idempotency surface in the codebase, and the test
coverage matches:

- **Cumulative → per-delta conversion.** IB's `orderStatus` reports *cumulative* filled
  quantity and *cumulative* VWAP on every callback; `_fill_to_ack`
  (`broker/ib/router.py:312-337`) computes `delta_qty = cum_new - cum_prev` and
  `per_delta_price = (cum_new·avg_new − cum_prev·avg_prev) / delta_qty` **before** mutating
  the stored previous values — verified correct arithmetic by
  `test_cumulative_to_delta_quantity` and `test_cumulative_to_delta_price`.
- **Duplicate-cumulative drop.** `delta_qty == 0` on a FILLED/PARTIALLY_FILLED status is
  treated as a redundant echo and dropped (`:340-341`) — `test_cumulative_to_delta_drops_duplicate_cumulative`.
- **Regression guard.** `delta_qty < 0` (impossible under normal IB behavior) is logged and
  dropped rather than applied as a negative fill (`:313-321`) —
  `test_cumulative_to_delta_skips_negative_regression`.
- **PreSubmitted/Submitted echo suppression.** The synchronous submit-time ACK is not
  re-emitted when IB's own `PreSubmitted`/`Submitted` callback arrives later
  (`_has_acked` bookkeeping + `:308-310`) — `test_pre_submitted_callback_suppressed_after_synchronous_ack`.
- **Terminal-status re-delivery.** A duplicate terminal FILLED ack for an already-FILLED
  order is caught at the orchestrator layer too (`duplicate_terminal_fill_ack`,
  `orchestrator.py:5421-5438`) — defense in depth above the router's own pruning.

### 5.4 Gaps

- **Cross-connection idempotency does not exist** — see §4.5. All the dedup machinery above
  is scoped to a single `IBOrderRouter` instance's in-memory dicts; nothing survives (or is
  designed to survive) a reconnect.
- **`IBOrderRouter._submitted_order_ids` is monotonically growing** (§3.3, §9) — a minor
  correctness asymmetry with backtest, not a safety issue given the id-derivation guarantees
  in §5.1, but worth fixing for consistency and to bound memory in very long paper sessions.

---

## 6. Broker adapter audit (IB)

### 6.1 `connection.py` — threading and handshake

The threading model is explicit and disciplined: EReader (ibapi-owned) → message thread
(`run()`, populates `_fill_queue`) → writer thread (`_drain_writer_queues`, sole caller of
`placeOrder`/`cancelOrder`) → main/orchestrator thread (`enqueue_*`, `poll_fills`,
`next_order_id`), all cross-thread communication via `queue.Queue` — no shared mutable state,
no locks needed beyond `_next_id_lock`. This is verified under real concurrency by
`test_writer_thread_serialises_submit_and_cancel` (50 orders + 24 net cancels from 4 threads,
zero duplicate ib_ids) and `test_next_order_id_thread_safe_under_parallel_calls` (800 calls
from 8 threads, all unique, all sequential).

- **`nextValidId` never regresses** (`:339-348`) — correctly defends against IB re-sending a
  stale baseline after a socket-level reconnect pulse; tested
  (`test_next_valid_id_never_regresses_on_reconnect_pulse`). This is necessary but not
  sufficient for real reconnect safety (§4.5) — it protects the *id counter*, not open-order
  state.
- **Fatal vs. non-fatal connection errors are correctly split**: codes `{326, 502, 504}`
  abort the handshake (`_CONNECT_FATAL_ERROR_CODES`, `:50`, `:408-410`); everything else with
  `reqId <= 0` is logged and, if a callback is registered, surfaced as a non-fatal alert
  (`:411-421`) — but as noted in §4.5/§7, nothing consumes that alert to take corrective
  action.
- **`placeOrder`/`cancelOrder` failures are converted to synthetic fill events**
  (`_writer_place_order`, `:258-278`) rather than raised on the writer thread (which would
  crash it silently) — good defensive design, and it correctly reaches `IBOrderRouter` as a
  REJECTED ack via the generic error branch (`router.py:275-286`), tested end-to-end
  (`test_place_order_failure_pushes_synthetic_fill_event`,
  `test_place_order_failure_emits_rejected_ack`).
- **No reconnect/backoff logic** (§4.5) — `disconnect_and_stop()` and `connect_and_start()`
  are the only lifecycle primitives; nothing calls the pair in sequence automatically.

### 6.2 `router.py` — submission, cancellation, fill mapping

- Order construction (`_build_ib_order`, `:200-221`) is minimal and correct for what it
  covers: `MKT`/`LMT`, `BUY`/`SELL`, `tif="DAY"`, and the `eTradeOnly=False`/
  `firmQuoteOnly=False` defaults required to avoid ibapi ≥10.x Error 10268 — regression-tested
  (`test_market_order_maps_to_mkt_without_limit_price`,
  `test_etradeonly_defaults_regression_unit_side`). It does **not** cover `is_moc` (§3.3) or
  RTH-aware routing (§3.3).
- Status-string → `OrderAckStatus` mapping (`_STATUS_TO_ACK`, `:57-68`) covers all
  IB statuses the codebase expects (`PreSubmitted`, `Submitted`, `PendingSubmit`,
  `PendingCancel`, `PartiallyFilled`, `Filled`, `Cancelled`, `ApiCancelled`, `Inactive`,
  `Expired`); an unrecognized status string is dropped with a WARNING log and (if wired) an
  alert (`:288-306`) — fail-safe, not fail-silent, and tested
  (`test_unknown_orderstatus_string_dropped`).
- Error-code mapping is a three-tier fallthrough: `{201}` → REJECTED, `{202}` → CANCELLED,
  connectivity codes `{1100,1101,1102,2110}` → dropped (alert-only), anything else → REJECTED
  (`:240-286`) — every branch has a direct test (`test_error_code_201_maps_to_rejected_ack`,
  `test_error_code_202_maps_to_cancelled_ack`, `test_connectivity_error_codes_drop_ack`,
  `test_unknown_error_code_maps_to_rejected_ack`).
- **Defensive partial-fill downgrade**: a `Filled` status whose cumulative quantity is still
  short of `total_quantity` is downgraded to `PARTIALLY_FILLED`
  (`:343-346`) rather than trusting a possibly-premature IB status string —
  `test_filled_status_downgraded_to_partial_when_qty_short`.
- `cancel_order()` is fire-and-forget and honest about it: returns `True` only to mean "a
  cancel was enqueued for a known id," not "confirmed cancelled" (`:176-189`) — matches the
  `OrderRouter` protocol's documented duck-typed contract (`backend.py:62-70`).

### 6.3 `contracts.py` — resolution correctness

`stock_contract()` (`broker/ib/contracts.py:17-34`) is a thin, correct factory — **but it is
never called with anything beyond the bare symbol** from its one call site
(`router.py:145: stock_contract(request.symbol)`). The function's own docstring names the
exact risk: `primary_exchange` "exists because SMART routing requires it whenever a symbol
is ambiguous (e.g. `MSFT` cross-listed)." There is no universe-level allowlist, symbol
metadata table, or config surface anywhere in `bootstrap.py`/`platform_config.py` that
supplies a `primary_exchange` per symbol, and no test file exists for `contracts.py` at all
(confirmed: no `test_contracts*.py` in the repo). For the platform's current "US large cap"
universe this is low-probability, but it is completely unguarded — the first ambiguous
ticker added to a PAPER universe silently becomes a wrong-instrument risk with no code path
that would catch it before submission.

---

## 7. Safety / kill-switch audit

### 7.1 Kill switch is real, always wired, fail-closed at every checked gate

- `bootstrap.py:562` unconditionally constructs `InMemoryKillSwitch()` for every mode; the
  `KillSwitch | None` type on the orchestrator exists for hand-built test orchestrators, not
  for any production path — this audit found no `build_platform` code path that leaves it
  `None`.
- Tick-start gate (`orchestrator.py:2292-2311`): if active, the tick is suppressed, a
  `tick_suppressed_kill_switch` counter metric fires, and macro transitions to `DEGRADED`
  (when in a trading mode) — the tick never reaches sensor/signal/risk/order logic. Fails
  closed.
- `_require_safe_session_entry` (`:1087-1102`) blocks `run_research`/`run_backtest`/
  `run_paper`/`run_live` from even starting while the switch is active or risk escalation is
  non-`NORMAL` — verified by `test_run_backtest_refuses_active_kill_switch`.
- `recover_from_degraded` explicitly refuses to leave `DEGRADED` while the switch is active
  (`:1630-1637`) — `test_recover_from_degraded_refuses_when_kill_switch_active`.
- `_escalate_risk` (`:3599-3668`) is a monotonic R0→R4 walk; whenever a kill switch is
  present it is unconditionally activated at R4 and a `KillSwitchActivation` event is
  published (`:3649-3662`) — activation is never conditional on the flatten having succeeded.

### 7.2 The one place kill-switch fail-closed depends on something else being correct

`unlock_from_lockdown`'s zero-exposure guard (`:1646-1688`, guard at `:1666-1671`) is sound
*as written* — it is exactly the Inv-11 check the skill specifies. But it is only as strong
as `PositionStore.total_exposure()`'s accuracy, and §4.4 shows a concrete, shipped code path
(emergency-flatten pipeline error) where that number can be wrong (too low) at precisely the
moment this guard is consulted. This is not a kill-switch defect — the switch itself
activates correctly and cannot be bypassed directly — it is a case where an *upstream*
position-tracking gap can make a *downstream* fail-safe check pass when it should not.
Recommend cross-referencing this with `audit_monitoring_safety.md`'s reconciliation-engine
review.

### 7.3 IB connectivity loss: alerted, not acted on

Non-fatal IB connectivity codes (1100 disconnect, 1101/1102/2110 restore) are wired all the
way to the bus as a WARNING `Alert` (`bootstrap.py:755-773`, `alert_name="ib_connectivity_event"`).
Nothing consumes that alert to trigger a reconnect, a throttle, or a kill-switch activation —
confirmed by grep (no subscriber for `ib_connectivity_event` anywhere in `src/feelies`). This
is consistent with — and directly causes — the §4.5 finding: the platform *knows* the link
dropped (or was restored) and logs it, but neither halts new signal generation nor attempts
recovery. Whether "an IB link drop should tighten `RiskLevel`" is a policy decision, but today
the answer is structurally "no."

### 7.4 Clock discipline (Inv-10)

No `datetime.now()`/`datetime.utcnow()`/`time.time()` call exists in any in-scope
`src/feelies/execution/*`, `src/feelies/broker/ib/*`, or `src/feelies/monitoring/kill_switch.py`
file (verified by direct grep of the full scope list). The only wall-clock reads in scope are
in `scripts/run_paper.py` (:140, :173) and `scripts/run_paper_soak.py` (:47), both purely for
session-recorder/soak-summary metadata timestamps, never fed into `Clock`, the tick pipeline,
the order path, or any hashed/replayed artifact. `WallClock` itself
(`core/clock.py`, the one file exempted by the ruff DTZ rule) is correctly the sole real-time
source threaded through `IBGatewayConnection`/`IBOrderRouter` (`paper_backend.py:47-56`).

### 7.5 Process-lifecycle gap

`run_paper.py` registers a `SIGINT` handler only (`:231-234`); there is no `SIGTERM` handler.
The project's own runbook flags this explicitly ("Use `kill -INT` (not SIGTERM) until SIGTERM
handler is wired," `docs/paper_rth_test_runbook.md:74`) — a documented, tracked gap, not a
surprise, but relevant to safety because an orchestrator (systemd, k8s, a supervisor process)
that sends SIGTERM by default would bypass the `halt()` → `shutdown()` teardown path entirely
and rely on Python's default terminate behavior, skipping the final fill drain
(`orchestrator.py:1725-1742`) and the pending-order shutdown alert (`:1757-1777`).

---

## 8. Test gap matrix

| Invariant / property | Covered | Partial | Missing | Evidence |
|---|---|---|---|---|
| Order SM legal transitions (all edges + terminal exhaustiveness) | ✓ | | | `test_order_state.py` (15 tests, incl. exhaustive terminal-state parametrization) |
| `IllegalTransition` raised on forbidden edge | ✓ | | | `test_illegal_transition_created_to_filled/acknowledged` |
| `OrderAckStatus` exhaustive matching in orchestrator | ✓ (by construction: `raise ValueError`) | | | `orchestrator.py:5482-5485`; no test directly forces the `ValueError`, but the guard is structural |
| Backtest-vs-backtest router fill-economics parity | ✓ | | | `test_router_parity.py` (3 tests) |
| **Backtest-vs-IB router parity** | | | ✗ | No such test exists anywhere (§3.4) |
| `IBOrderRouter` submit/dedup/cumulative-delta/status-mapping | ✓ | | | `test_ib_router.py` (33 tests, exhaustive) |
| `IBOrderRouter` honors `is_moc` | | | ✗ | No test asserts MOC handling one way or the other |
| `IBOrderRouter` honors RTH gating | | | ✗ | No `bind_position_qty`/RTH test for the IB router |
| `IBGatewayConnection` handshake, threading, error-code triage | ✓ | | | `test_ib_connection.py` (14 tests) |
| Contract resolution correctness (`primary_exchange`, ambiguous symbols) | | | ✗ | No `test_contracts.py` file exists |
| Reconnect preserves/reconciles open-order state | | | ✗ | Existing "reconnect" tests only cover a fresh connection object getting a valid id (§4.5) |
| Duplicate broker callback / replay dedup | ✓ | | | `test_cumulative_to_delta_drops_duplicate_cumulative`, `test_pre_submitted_callback_suppressed_...` |
| `KillSwitch` protocol shape | ✓ (via bespoke stand-in) | | | `test_kill_switch.py` — tests a local `SimpleKillSwitch`, not the shipped class |
| `InMemoryKillSwitch` concrete behavior | ✓ (outside this audit's file list) | | | `tests/monitoring/test_in_memory.py::TestInMemoryKillSwitch` |
| Orchestrator kill-switch gate / escalation / unlock | ✓ (outside this audit's file list) | | | `tests/kernel/test_orchestrator.py` (`test_unlock_from_lockdown_clears_kill_switch`, `test_run_backtest_refuses_active_kill_switch`, `test_live_mode_force_flatten_reaches_macro_risk_lockdown`, etc.) |
| `paper_backend` composition shape | ✓ (composition only) | | | `test_paper_backend.py` — does not start threads or connect |
| Real IB Gateway E2E (fills, cancels, partials) | | ✓ (gated) | | `test_ib_functional.py`, `test_paper_rth_e2e.py` — require IB Gateway + RTH; not run per instructions |
| Emergency-flatten pipeline-error recovery (§4.4) | | | ✗ | No test injects an exception between `submit()` and `_reconcile_fills()` in `_emergency_flatten_all` |
| Session-recorder / soak wall-clock fields | n/a | | | Not a correctness-relevant path |

**Minimal new tests (specs only):**

1. **`test_ib_router_ignores_moc_flag`** (`tests/broker/ib/test_ib_router.py`) — submit an
   `OrderRequest(is_moc=True)` through `IBOrderRouter`, assert the built `ibapi.Order` either
   carries MOC semantics (once fixed) or explicitly document/xfail the current gap so a fix
   has a locking test to flip green.
2. **`test_ib_router_no_rth_gate` / `test_ib_router_bind_position_qty`** — assert current
   behavior (no `bind_position_qty` attribute) so a future implementation is a deliberate,
   visible change rather than a silent one.
3. **New `tests/broker/ib/test_contracts.py`** — at minimum, assert `stock_contract()`
   forwards a caller-supplied `primary_exchange`, and add a router-level test that a
   configured per-symbol exchange map (once added) reaches `_build_ib_order`.
4. **`test_reconnect_with_open_order_flags_orphan`** — using the existing `_FakeIBConnection`
   pattern from `test_ib_router.py`: submit an order, ACK it, discard the router/connection,
   build a fresh pair, and assert the orchestrator either (a) surfaces a loud alert/DEGRADED
   transition for the orphaned `order_id`, or (b) is documented as relying entirely on manual
   operator reconciliation. Today neither is asserted anywhere.
5. **`test_emergency_flatten_pipeline_error_preserves_order_tracking`**
   (`tests/kernel/test_orchestrator.py`) — inject an exception inside the
   poll/apply/reconcile portion of `_emergency_flatten_all` (after a successful `submit()`)
   and assert the order is **not** silently pruned from `_active_orders` (or, if it must be,
   that a CRITICAL alert distinct from `emergency_flatten_incomplete` names the specific
   `order_id` as "broker state unknown" rather than folding it into a generic residual count).
6. **Cross-router shape-parity smoke** in `test_router_parity.py` (or a new file) — submit an
   equivalent `OrderRequest` to `BacktestOrderRouter` and `IBOrderRouter` (via
   `_FakeIBConnection`) and assert at least the ack **sequence of statuses** matches
   (ACKNOWLEDGED → ... → terminal), closing the naming/coverage mismatch in §3.4.

---

## 9. Prioritized backlog

**P0**

| # | Component | `file:line` | One-line fix | Impact | Effort |
|---|---|---|---|---|---|
| 1 | MOC routing | `broker/ib/router.py:200-221` | Check `request.is_moc` in `_build_ib_order` and set IB's MOC order type/TIF (or raise loudly if MOC-via-IB isn't yet supported) instead of silently building a regular order | Stops a silent immediate-fill-instead-of-closing-print divergence the moment any PAPER config sets `moc_strategy_ids` | S |
| 2 | Emergency-flatten fill loss | `kernel/orchestrator.py:3755-3768`, `:5123-5183` | Do not prune `_active_orders` on a post-submit pipeline exception; instead keep the order tracked in a "broker-state-unknown" bucket and block `unlock_from_lockdown` until it is resolved (manually or via a fill) | Closes the phantom-flat window that can defeat the zero-exposure unlock guard | M |
| 3 | No reconnect / orphan orders | `scripts/run_paper.py:244`, `broker/ib/connection.py`, `broker/ib/router.py` | Add a reconnect loop with backoff around `connect_and_start()`, and on (re)connect call `reqOpenOrders`/`reqExecutions` to reconcile any order the router doesn't already know about before resuming | Eliminates the "silent orphan" failure mode that today requires manual TWS/Gateway reconciliation | L |

**P1**

| # | Component | `file:line` | Fix | Impact | Effort |
|---|---|---|---|---|---|
| 4 | RTH gate | `broker/ib/router.py` | Implement `bind_position_qty`/an RTH check on `IBOrderRouter` mirroring `RthEntryFillGate`, or explicitly document why IB's native session handling is an accepted substitute | Removes an Inv-9 divergence for off-hours entries | M |
| 5 | Contract resolution | `broker/ib/contracts.py`, `broker/ib/router.py:145` | Add a per-symbol `primary_exchange` config/lookup and thread it through `_build_ib_order` | Removes a latent wrong-instrument risk for any future ambiguous ticker | S |
| 6 | Ack-timeout watchdog | `kernel/orchestrator.py`, `broker/ib/connection.py` | Implement the already-specified ack-timeout escalation (`order-lifecycle.md`'s "Timeout Escalation" design) | Bounds how long an order can sit ACKNOWLEDGED with no real broker confirmation (compounds with #3) | M |
| 7 | IB connectivity alert has no consumer | `bootstrap.py:755-773` | Subscribe something (throttle, `RiskLevel` nudge, or at minimum a DEGRADED transition) to `ib_connectivity_event` | Turns a logged-only signal into an actionable one | S |

**P2**

| # | Component | `file:line` | Fix | Effort |
|---|---|---|---|---|
| 8 | `_submitted_order_ids` never released | `broker/ib/router.py:118-132` | Release the id on terminal REJECTED, matching `BacktestOrderRouter`'s `release_submitted_id` | S |
| 9 | No `test_contracts.py` | `broker/ib/contracts.py` | Add direct unit tests (see §8 spec 3) | S |
| 10 | SIGTERM unwired | `scripts/run_paper.py:231-234` | Register the same handler for `SIGTERM` as `SIGINT` | S |
| 11 | `datetime.now(UTC)` in paper scripts | `scripts/run_paper.py:140,173`, `scripts/run_paper_soak.py:47` | Route through `Clock`/`WallClock` for consistency with the DTZ rule's letter (no behavior change — metadata only) | S |
| 12 | `test_router_parity.py` naming | `tests/execution/test_router_parity.py` | Rename to `test_backtest_router_parity.py` or add the cross-router case from §8 spec 6 so the name matches the coverage | S |

---

## 10. Appendix: open questions needing a live/paper session

1. **MOC-via-IB semantics.** If MOC support for PAPER/live is added (backlog #1), does IB's
   API for a retail/paper account actually support a `MOC` order type reliably enough to
   match the backtest closing-print model, or does the fix need to be "refuse to submit an
   `is_moc` order outside BACKTEST" instead of "translate it"? Needs a real IB Gateway
   session to check order-type acceptance for the account type in use.
2. **Extended-hours queuing behavior.** This audit inferred (from `tif="DAY"` and no
   `outsideRth` flag) that an off-RTH entry sent to IB queues until the next open rather than
   erroring or routing to an ECN. Confirming this requires submitting a real off-hours order
   against the paper account and observing the resulting `orderStatus` sequence.
3. **Real reconnect timing.** How long does `ibapi`'s socket layer take to notice a dead TCP
   connection (vs. a clean disconnect) in practice, and does `error()` reliably fire code
   1100 in that case, or can the writer thread block silently on a half-open socket? This
   determines whether backlog #3's reconnect loop needs an additional liveness timeout beyond
   the alert-callback path.
4. **Current config posture.** No shipped config sets `moc_strategy_ids` today (verified
   against `configs/*.yaml` and `platform.yaml`), so finding 2 is latent, not active. Worth an
   explicit operator confirmation that no in-flight alpha promotion plans to enable MOC
   execution for a PAPER/LIVE-track strategy before backlog #1 is prioritized down.
5. **Cross-reference with `audit_monitoring_safety.md`.** §7.2's "kill switch is correct but
   trusts an upstream number" and §7.3's "connectivity alert has no consumer" both sit right
   at the boundary this audit was told to defer — recommend that audit explicitly pick up
   "should an IB connectivity WARNING or an unresolved emergency-flatten order tighten
   `RiskLevel`?" as a named question.

---

*Read-only audit. No production code, baseline, config, or ledger was modified. All test
commands in the Method section were run for evidence only; `paper_rth`/`functional` network
tests were read but not executed.*
