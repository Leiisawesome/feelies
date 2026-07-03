# Monitoring & Safety-Controls Audit — 2026-07-02

Scope: read-only audit of `src/feelies/monitoring/` (kill switch, health, alerting,
telemetry, structured logging, horizon metrics, paper session recorder), its wiring
into `kernel/orchestrator.py` and `bootstrap.py`, and the adjacent ingestion-health /
broker-connectivity surfaces that feed it. Lens: Inv-11 (fail-safe default — controls
only tighten autonomously; loosening requires human re-authorization; every control
must fail closed on its own error). No production code, tests, configs, or ledgers
were modified.

Verification run (read-only):

- `uv sync --all-extras` (environment was not pre-installed in this session).
- `uv run pytest tests/monitoring/ tests/ingestion/test_ingest_health.py tests/kernel/test_data_integrity_runtime.py -q` — **51 passed**.
- `uv run pytest tests/integration/test_paper_rth_safety.py -q -m paper_rth` — **3 skipped**: `Outside US RTH (9:30–16:00 ET); set PAPER_RTH_FORCE=1 to override` (this sandbox also has no IB Gateway / `MASSIVE_API_KEY`, so these three E2E safety-path tests — data-gap degrade, risk lockdown, G12 cost alert — could not be exercised end-to-end here; see §8).

Severity convention (per audit brief):

- **P0**: kill switch fails open / disarms autonomously / only logs; health loosens autonomously; an uncovered catastrophic failure mode.
- **P1**: arbitrary/undisclosed thresholds, dead alerts, propagation-latency window, wall-clock in recorder/telemetry, or a documented-contract violation with real safety-relevant ambiguity.
- **P2**: richer telemetry, operator tooling, bounded/low-blast-radius weakness, or a design choice needing explicit owner acceptance.

Findings are labeled **implementation bug**, **documented limitation** (already disclosed as "Not shipped" in the owning skill), or **intentional design** wherever the distinction matters.

---

## 1. Executive summary

- **P0 — Broker (IB) disconnect produces zero automated safety response.** Connection-level IB errors (incl. code 1100, "connectivity lost") are detected (`broker/ib/connection.py:387-422`) and routed to the bus, but hardcoded at `AlertSeverity.WARNING` (`bootstrap.py:765`) — a severity `InMemoryAlertManager.emit()` doesn't even log specially, let alone act on (`monitoring/in_memory.py:129-140`). The order-scoped connectivity path is worse: it's a self-admitted `TODO` that silently drops the ack with only a plain-text log line, no bus event at all (`broker/ib/router.py:236-247`). A disconnect while positions are open triggers no kill switch, no macro degrade, no order-flow suppression — exactly the "broker disconnect with open positions" scenario named as the audit's own P0 example.
- **P1 — The `AlertSeverity.CRITICAL`/`EMERGENCY` "autonomously activates safety controls" contract is not realized.** `core/events.py:436,450` and `monitoring/alerting.py:28-30,40-41` document that CRITICAL and EMERGENCY both trigger safety controls; `InMemoryAlertManager.emit()` only auto-trips the kill switch on EMERGENCY (`in_memory.py:129,136`), and its own docstring defends this as intentional. Worse: `AlertSeverity.EMERGENCY` has **zero production emission sites** in `src/feelies` — the only severity that can auto-trip the switch via this path is unreachable as shipped. Proven by a passing test that asserts the documented contract is false: `tests/monitoring/test_in_memory.py:129-133`.
- **P1 — Kill switch module docstring overpromises.** `monitoring/kill_switch.py:3-8` states activation cancels all open orders and flattens all positions. `InMemoryKillSwitch.activate()` (`in_memory.py:192-201`) only flips a boolean and logs. Cancellation/flattening only happens via the independent `_escalate_risk()` cascade (`orchestrator.py:3636-3662`); the other two of three `.activate()` call sites (`in_memory.py:137`, `orchestrator.py:5811`) halt new order flow but leave resting orders and open positions completely unmanaged.
- **P1 — LULD/regulatory halt detection ships disabled by default, silently.** `halt_on_condition_codes`/`halt_off_condition_codes` both default to `()` (`core/platform_config.py:131-132`); the code's own comment admits "Empty ⇒ halt modeling is inert." No boot-time warning fires when this is left empty in PAPER/LIVE mode.
- **P1 — `test_kill_switch.py` and `test_alerting.py` do not test the shipped classes.** Both files define throwaway local `SimpleKillSwitch`/`SimpleAlertManager` classes to exercise the *Protocol shape* and never import `InMemoryKillSwitch`/`InMemoryAlertManager` — the actual classes wired into every trading session (`bootstrap.py:562-564`). Real coverage lives only in `test_in_memory.py`.
- **P1 — `kill_switch: KillSwitch | None = None` is fail-open-by-omission at the type level.** Every gate in the orchestrator reads `if self._kill_switch is not None and self._kill_switch.is_active:` (`orchestrator.py:1093,1633,1684,2292,5808`). `bootstrap.py` wires a real instance diligently today, but nothing prevents a future/alternate entry point from silently running with the entire kill-switch net disabled. Contrast: `metric_collector` has no default — it's mandatory (`orchestrator.py:490`).
- **P1 — No dedicated "kill switch evaluation throws" test.** Traced the actual behavior: `_process_tick()`'s blanket `try/except Exception` (`orchestrator.py:2173-2178`) would catch an exception raised from `self._kill_switch.is_active` at the tick gate (line 2292) and degrade macro via `_handle_tick_failure` (lines 2180-2234) — **plausibly fail-closed by construction**, but this is an incidental side effect of a generic tick-safety net, not a verified kill-switch contract. No test exercises this path.
- **P1 — Alert acknowledgment permanently suppresses future distinct alerts of the same name.** `InMemoryAlertManager.acknowledge()`/`active_alerts()` (`in_memory.py:142-147`) key off a set that's never cleared or expired. One human ack of e.g. `composition.low_completeness` silently hides every future occurrence of that alert name for the life of the process — the audit's own "deduplicated without suppressing genuine re-alerts" question, answered no.
- **P1 — `StructuredLogger` has zero concrete implementations.** The documented JSON-lines-per-layer, injectable-clock-timestamped logging system (`monitoring/structured_logging.py:1-13`) is Protocol-only; real runtime logging is unstructured stdlib `logging.getLogger(__name__)` calls scattered through the codebase. Weakens Inv-13 incident reconstruction relative to what's documented.
- **P1 — `HealthRegistry`/`HealthCheck` are fully dead code.** Zero concrete implementations anywhere; `bootstrap.py` never imports `feelies.monitoring.health`. The "health state machine" this audit was asked to formalize does not exist as such — actual health enforcement lives in the unrelated, bespoke `DataHealth` enum (`ingestion/data_integrity.py`) plus `MacroState`/`RiskLevel`.
- **P1 — Inv-10 violation in the one script wiring the paper recorder.** `scripts/run_paper.py:140,173` writes `datetime.now(UTC).timestamp() * 1_000_000_000` into `PaperSessionRecorder` metadata (`session_start_ns`/`session_end_ns`), bypassing the injectable clock.
- **P1 — Silent feed-stall is not detected as staleness.** Gap detection is purely sequence-number based (`ingestion/massive_normalizer.py:879-884`), with explicit WS-disconnect handling (`massive_normalizer.py:970-984`). A feed that goes silent without an explicit disconnect frame and without ever resuming (so no gap is ever observed) produces `IdleTick` events every ~1s, but the only consumer effect is draining broker fills (`orchestrator.py:1812-1817`) — no staleness alert, no `DataHealth` transition.
- **P1 — Kill-switch activation provenance is inconsistent.** Only the `_escalate_risk()` path publishes the typed `KillSwitchActivation` bus event (`orchestrator.py:3654-3662`); the G12 direct-trigger path (`orchestrator.py:5811-5814`) and the `InMemoryAlertManager` EMERGENCY path (`in_memory.py:136-140`) call `.activate()` directly with no bus event — weakens Inv-13 for those two triggers.
- **Positive** — the risk-escalation SM (`risk/escalation.py`) is genuinely monotone and hard to bypass; `unlock_from_lockdown` enforces a real, non-vacuous zero-exposure check (`orchestrator.py:1666-1671`) before allowing recovery; `degrade_on_data_gap` defaults `True` (`platform_config.py:105`) and CORRUPTED/GAP_DETECTED do drive a real force-flatten + macro DEGRADED (`orchestrator.py:6618-6659`); macro `DEGRADED`/`RISK_LOCKDOWN` recovery is structurally gated behind explicit operator calls, never a single benign tick.
- **P2s** (detail in §9): vacuous `_verify_data_integrity()` pass in the BACKTEST/no-normalizer path (PAPER/LIVE unaffected since a normalizer is always wired there); no automated retry after a failed emergency/degrade flatten; `time.monotonic()` bypassing the injectable clock outside the tick path; a misspelled alert name (`degrase_flatten_failed`) that would silently break exact-match alert routing; no operator entry point ever calls `recover_from_degraded()`.

---

## 2. Safety-control inventory

| Control | Trigger | Action | Fail direction (own error / omission) |
|---|---|---|---|
| Kill switch (`InMemoryKillSwitch`, `monitoring/in_memory.py:171-223`) | `.activate()` called by 1 of 3 sites (see §3) | Sets `_active=True`; tick gate (`orchestrator.py:2291-2311`) skips all further tick processing and degrades macro if in a trading mode | **Omission**: constructor default `None` → every gate no-ops (fail open). **Own-error**: no dedicated handling; incidentally caught by the generic per-tick exception handler (§3.2) |
| Risk escalation SM (`risk/escalation.py`) | Risk-engine breach detection (out of scope; see risk-engine skill) | R0→R4 monotonic cascade; R3 emergency-flattens via market orders; R4 activates kill switch + `KillSwitchActivation` + macro `RISK_LOCKDOWN` | Forward-only by transition table (`risk/escalation.py:29-58`); only `unlock_from_lockdown(audit_token=...)` can return to NORMAL, and only after a real zero-exposure check |
| Data-health gate (`_data_health_blocks_trading`, `orchestrator.py:6587-6660`) | `DataHealth ∈ {CORRUPTED, HALTED, GAP_DETECTED(if configured)}` from `MassiveNormalizer.health()` | CORRUPTED/GAP_DETECTED: force-flatten symbol + macro DEGRADED. HALTED: block fills only, no macro escalation (LULD is expected to resume) | **Fail open**: entire gate is a no-op if `self._normalizer is None` (`orchestrator.py:6601-6602`) — true for BACKTEST unless a test/caller supplies one; always populated for PAPER/LIVE (`bootstrap.py:461-475`) |
| LULD halt classification (`ingestion/data_integrity.py`, `massive_normalizer.py:915-943`) | Tape condition codes in `halt_on_condition_codes`/`halt_off_condition_codes` | Sets/clears `DataHealth.HALTED` | **Fail open by default config**: both code tuples default to `()`, which the code comments call "inert" (`platform_config.py:126-132`) |
| Alert manager (`InMemoryAlertManager`, `in_memory.py:110-156`) | Any `Alert` published on the bus (forwarded via `orchestrator.py:6002-6004`) | Appends to `_alerts`; CRITICAL/EMERGENCY get a `logger.warning`; EMERGENCY additionally calls `kill_switch.activate()` | **Under-triggers relative to its own documented contract** for CRITICAL (see §6); EMERGENCY path is unreachable (no production emitter) |
| G12 realized-cost escalation (`orchestrator.py:5773-5814`) | Consecutive fills breaching `alert_ratio × disclosed cost` (`g12_realized_cost_exceeds_disclosure`) | Publishes CRITICAL `Alert`; if streak breach persists, directly calls `kill_switch.activate()` (bypasses `AlertManager`) | Self-contained, doesn't depend on `AlertManager`/EMERGENCY at all — one of the few triggers that reliably fires |
| Hazard-exit controller (`risk/hazard_exit.py`, out of scope — see risk-engine skill) | `RegimeHazardSpike` / max position age | `OrderRequest` exit, opt-in per alpha (`hazard_exit.enabled`) | Exit-only by construction; formal `check_order` REJECT on a non-reducing hazard order blocks submission (`orchestrator.py:6308-6335`) |
| IB connectivity alert (`bootstrap.py:752-773`) | Non-fatal IB error codes (incl. 1100 disconnect) via `connection.py:411-421` | Publishes `Alert(severity=WARNING, alert_name="ib_connectivity_event")` | **Fails to escalate**: WARNING never reaches kill switch, macro, or `DataHealth` — see P0 in §1/§4 |
| IB order-scoped connectivity codes (`broker/ib/router.py:223-247`) | `fill.error_code ∈ {1100,1101,1102,2110}` on an order callback | `logger.warning(...)`; ack dropped (`return None`) | **No typed event at all** — explicit `TODO` in the code (`router.py:236-237`) admits this is unwired |
| `HealthRegistry`/`HealthCheck` (`monitoring/health.py`) | N/A | N/A | **Dead code** — zero concrete implementations, never imported by `bootstrap.py` |
| `StructuredLogger` (`monitoring/structured_logging.py`) | N/A | N/A | **Dead code** — zero concrete implementations; real logging is unstructured stdlib |

---

## 3. Kill-switch audit (deep dive)

### 3.1 Does activation halt/flatten deterministically, or merely log?

Three activation call sites exist, each with different actual effect — the module docstring implies uniform behavior across all of them, which is not the case:

| Call site | Cancels resting orders? | Flattens positions? | Blocks new ticks? | Publishes `KillSwitchActivation`? |
|---|---|---|---|---|
| `_escalate_risk()` R3→R4 (`orchestrator.py:3636-3662`) | No (no cancel-all path exists anywhere) | **Yes** — `_emergency_flatten_all()` runs *before* `.activate()` is called, bypassing the micro SM directly | Yes, from the next tick onward via the gate at `orchestrator.py:2292` | **Yes** (`orchestrator.py:3654-3662`) |
| G12 cost-overrun (`orchestrator.py:5806-5814`) | No | No | Yes | No |
| `InMemoryAlertManager.emit()` on EMERGENCY (`in_memory.py:136-140`) | No | No | Yes | No |

So "activation" reliably means "no new ticks are processed" (verified — see §3.4), but "cancel all open orders" and "flatten all positions" (`kill_switch.py:4-5`) are true **only** for the risk-escalation path, and even there the flatten happens as a *separate, prior* step, not as part of what `.activate()` itself does. **Classification: documented limitation / implementation-vs-docstring mismatch** — the `InMemoryKillSwitch.activate()` docstring (`in_memory.py:176-179`) is accurate ("blocks all new order submissions until manually reset"); the module-level `kill_switch.py:3-8` docstring is the one that overstates what the concrete adapter does.

### 3.2 Fail closed on its own error?

The `KillSwitch` Protocol docstring promises: "If the kill switch mechanism itself fails, the system defaults to halted (`is_active` returns True)" (`kill_switch.py:33-34`). Nothing in `InMemoryKillSwitch` or at any call site implements this contract explicitly — there is no `try/except` wrapping `self._kill_switch.is_active` anywhere.

Traced what actually happens if it throws at the primary gate (`orchestrator.py:2292`, inside `_process_tick_inner`): `_process_tick()` wraps the entire inner call in `try/except Exception` (`orchestrator.py:2173-2178`) and routes any exception to `_handle_tick_failure()` (`orchestrator.py:2180-2234`), which resets the micro SM and transitions macro to `DEGRADED` if currently in a trading mode. **Net effect: an exception from the kill-switch check on the main tick path is plausibly fail-closed** (no order is emitted that tick, and the system does not silently resume normal trading — it requires an explicit `recover_from_degraded()` call to leave DEGRADED). This is **incidental**, not a verified contract: it falls out of a generic tick-level safety net rather than a kill-switch-specific guarantee, and:

- `recover_from_degraded()` (`orchestrator.py:1630-1644`, called outside the tick path) and `unlock_from_lockdown()` (`orchestrator.py:1646-1689`) are **not** wrapped by that handler — an exception there propagates to the caller uncaught. Since the caller is an operator-driven recovery action, this is arguably acceptable (macro simply never leaves DEGRADED/RISK_LOCKDOWN), but it means the same generic protection doesn't apply everywhere `is_active`/`.activate()`/`.reset()` are read.
- The current `InMemoryKillSwitch` implementation is trivial (a boolean flag + list append + `logger` call) and has essentially no realistic internal failure mode of its own — the fail-closed contract is therefore untested against any implementation that actually could throw (e.g., a future remote-config- or DB-backed adapter).

**Recommendation (spec only, no code in this pass):** add the audit's suggested test — a `KillSwitch` stub whose `is_active` raises, asserting the tick aborts into `DEGRADED` rather than silently proceeding — to convert this from "true by incidental construction" to "contractually guaranteed." See §8.

### 3.3 Arming/disarming authority

`InMemoryKillSwitch.reset()` requires `operator` and `audit_token` kwargs (`in_memory.py:203-219`) — there is no way to disarm without supplying both. `Orchestrator.unlock_from_lockdown(audit_token=...)` additionally enforces a **real** zero-exposure guard (`orchestrator.py:1666-1671`, raises `RuntimeError` if `total_exposure() != 0`) before it will reset the kill switch and transition macro back to READY. This is a genuine, non-vacuous fail-safe check — **positive finding**. There is no autonomous disarm path anywhere in the codebase (grep for `.reset(` call sites confirms only `unlock_from_lockdown` and tests call it).

### 3.4 Latency — how fast does a trigger propagate to the order path?

The gate is checked once per tick, at the top of `_process_tick_inner`, *before* signal buffering/order construction (`orchestrator.py:2291-2311`) and returns immediately. Because `_process_tick` is synchronous and single-threaded per the deterministic tick pipeline, there is **no window within a tick** where an order can be constructed after `is_active` becomes true mid-tick — the check happens once, early, per tick. The residual latency is exactly "one full tick" — if activation happens asynchronously (e.g., broker callback thread calling `kill_switch.activate()` mid-tick-processing), the *current* tick's processing already in flight is not interrupted, only the *next* tick is gated. Given the orchestrator's `_quote_tick_in_flight` flag (`orchestrator.py:2172,2178`) and `_drain_async_fills` reconciliation path exist specifically to handle out-of-band broker events between ticks, this is consistent with the platform's single-threaded-per-tick design and is not flagged as a gap on its own — but it does mean the kill switch is a **between-ticks** gate, not a **mid-flight-order** interrupt, which is worth stating plainly rather than leaving implicit.

---

## 4. Trigger-coverage matrix

| Failure mode | Covered? | Mechanism | Threshold justified? | Evidence |
|---|---|---|---|---|
| Intraday drawdown breach | Yes | `RiskEngine` → `_escalate_risk()` cascade | Configurable `max_drawdown_pct`, single gate (not tiered) — out of this audit's scope (risk-engine skill) | `orchestrator.py:3599-3668` |
| Gross exposure breach | Yes | `RiskEngine` per-order/per-leg checks | Out of scope (risk-engine skill) | — |
| Data corruption (sequence-reuse / parse error) | Yes | `DataHealth.CORRUPTED` → force-flatten symbol + macro DEGRADED | Not threshold-based — binary detector, always terminal | `ingestion/massive_normalizer.py:855-865,945-955`; `orchestrator.py:6618-6633` |
| Data gap (sequence discontinuity) | Yes, **if `degrade_on_data_gap` left at its default `True`** | `DataHealth.GAP_DETECTED` → force-flatten symbol + macro DEGRADED | Pure sequence-number gap, no duration threshold (a 1-sequence gap and a 10,000-sequence gap are treated identically) | `massive_normalizer.py:879-884`; `platform_config.py:105`; `orchestrator.py:6642-6659` |
| Regulatory/LULD halt | **No, by default** | `DataHealth.HALTED`, driven by `halt_on_condition_codes`/`halt_off_condition_codes` | **Not justified — ships empty/inert** (P1, §1) | `platform_config.py:126-132` |
| WS feed clean disconnect | Yes | `notify_feed_interrupted()` → `GAP_DETECTED` | N/A | `massive_normalizer.py:970-984` |
| WS feed silent stall (no disconnect frame, no resumption) | **No** | `IdleTick` fires but only drains broker fills; no staleness alert or `DataHealth` transition | N/A — no threshold exists | `ingestion/massive_ws.py:113-119`; `orchestrator.py:1812-1817` (P1, §1) |
| Broker (IB) connection loss with open positions | **No** | Detected, but capped at WARNING with no downstream action | Hardcoded severity, not a tunable threshold at all | `connection.py:387-422`; `bootstrap.py:759-771`; `router.py:236-247` (**P0**, §1) |
| Runaway order rate | **No** | No rate limiter or order-count circuit breaker found anywhere in `src/feelies/execution/` or `kernel/` | N/A | Confirmed by grep — no matches for order-rate/throttle logic |
| Realized cost exceeds disclosed cost (G12) | Yes | Direct kill-switch trigger on sustained breach streak, independent of `AlertManager` | `realized_cost_escalation_streak`, configurable | `orchestrator.py:5773-5814` |
| Hazard/regime flip on open position | Yes (opt-in per alpha) | `HazardExitController` | Out of scope (risk-engine skill) — `hazard_exit.enabled` default off | `.cursor/skills/risk-engine/SKILL.md` |
| Manual/EMERGENCY alert-driven halt | **Nominally yes, practically unreachable** | `InMemoryAlertManager.emit()` on EMERGENCY | EMERGENCY is never emitted in production code (P1, §1) | `in_memory.py:136-140`; zero `AlertSeverity.EMERGENCY(` production hits |
| Emergency-flatten itself fails (residual exposure) | Partially | CRITICAL alert only (`emergency_flatten_incomplete`); risk SM still proceeds to LOCKED regardless, so new trading stays blocked, but the residual position is not retried | No automated retry (P2, §9) | `orchestrator.py:3770-3792` |
| Force-flatten-on-degrade fails | Partially | Same shape: CRITICAL alert (misspelled `alert_name`, see §9 P2-4), no retry | — | `orchestrator.py:6711-6738` |
| Circuit breaker / capital throttle (tiered) | **Not shipped — documented limitation, not audited as a gap** | N/A | N/A | live-execution skill explicitly discloses these as design targets; confirmed no `CircuitBreaker`/`throttle_level` implementation exists in `src/feelies/` |

---

## 5. Health-SM audit

The audit brief asks to formalize "the health state machine." **There is no health state machine matching `monitoring/health.py`'s `HealthRegistry`/`HealthCheck` protocols — that code is unimplemented and unwired** (confirmed: zero concrete classes, `bootstrap.py` never imports `feelies.monitoring.health`). The platform's actual health/degradation mechanism is the combination of:

1. **`DataHealth`** (`ingestion/data_integrity.py:17-34`) — per-symbol, 4-state (`HEALTHY`, `GAP_DETECTED`, `HALTED`, `CORRUPTED`), computed by `MassiveNormalizer`.
2. **`MacroState`** (`kernel/macro.py:27-39`) — system-wide, 10-state, with `DEGRADED` and `RISK_LOCKDOWN` as the two "unsafe" states.
3. **`RiskLevel`** (`risk/escalation.py:19-26`) — the monotonic R0–R4 escalation ladder (out of scope for deep audit here; see risk-engine skill).

Auditing these as the de facto health SM:

1. **Monotone degradation, affirmative recovery**: confirmed structurally. `MacroState._MACRO_TRANSITIONS` (`kernel/macro.py:42-108`) only allows `DEGRADED → {READY, SHUTDOWN}` and `RISK_LOCKDOWN → {READY, SHUTDOWN}` — there is no transition path that reaches `DEGRADED`/`RISK_LOCKDOWN` from a "worse" state and then improves except through the two explicit recovery methods. `recover_from_degraded()` (`orchestrator.py:1630-1644`) and `unlock_from_lockdown()` (`orchestrator.py:1646-1689`) are the **only** call sites that transition `DEGRADED`/`RISK_LOCKDOWN` back to `READY` (confirmed by grep — no other `MacroState.READY` transition originates from either state), and neither is invoked automatically from the tick loop — both require an explicit external call. **Positive finding.**
2. **Can health ever loosen autonomously?** No autonomous path found. `recover_from_degraded()` additionally re-checks `kill_switch.is_active` (must be False) and `_verify_data_integrity()` (see caveat below) before allowing the transition; `unlock_from_lockdown()` requires an `audit_token` and a real zero-exposure check.
   - **Caveat (P2, downgraded from a naive P0/P1 read):** `_verify_data_integrity()` (`orchestrator.py:6740-6777`) performs a **real** check ("every configured symbol tracked and `DataHealth.HEALTHY`") whenever a normalizer is wired (lines 6753-6758) — true for every PAPER/LIVE session (`bootstrap.py:461-475` always constructs one). It only degenerates to a **vacuous `True`** when `self._config is None` (line 6750-6751) or when there is no normalizer *and* `require_healthy_disk_cache_manifests` is left at its default `False` (line 6777) — i.e., BACKTEST/offline-replay contexts only, where there is no live capital at risk. Recommend tightening anyway for defense-in-depth (§9 P2-1), but this is not a live-trading exposure.
3. **Does degraded state actually reduce exposure downstream?** Yes for the paths that do escalate: `_data_health_blocks_trading` return `True` short-circuits the tick before order construction (`orchestrator.py:2313-2315`); `_escalate_risk()`'s R3 step submits real flatten orders. It does **not** for the broker-disconnect and CRITICAL-alert paths (§1, §4, §6) — those simply never reach a `MacroState` transition at all.
4. **Operational completeness note (P2):** no shipped operator script (`scripts/run_paper.py`, `scripts/run_backtest.py`) ever calls `recover_from_degraded()` — grep confirms the only call sites are `orchestrator.py` itself and `tests/kernel/test_orchestrator.py`. In practice, a PAPER session that degrades has no in-process recovery path today; an operator must restart the process. This is conservative (arguably a feature, not a bug) but worth an explicit note since it means "recovery" is currently theoretical for the one live-broker-connected mode.

---

## 6. Alerting audit

1. **Fire on the conditions that matter?** Partially. The 6 production `AlertSeverity.CRITICAL` sites (`orchestrator.py:3392,3455,3787,6317,6725`, plus the conditional at `:5777`) are all well-targeted (regime-calibration failure, emergency-flatten-incomplete, hazard-order-blocked, force-flatten-failure, G12 cost overrun) and each already has its own local fail-safe behavior baked in at the call site (the alert is a *notification*, not the safety mechanism itself, for 5 of the 6). The gap is upstream of alerting: broker disconnect and silent feed-stall (§4) never generate a CRITICAL/EMERGENCY alert in the first place — they're capped at WARNING or produce no typed event.
2. **Dedup without suppressing genuine re-alerts?** **No — confirmed bug-shaped behavior.** `InMemoryAlertManager.acknowledge(alert_name, ...)` adds to `self._acknowledged: set[str]` (`in_memory.py:145-147`) with no expiry, no per-instance scoping, and no re-arm condition. `active_alerts()` (`in_memory.py:142-143`) filters by that set permanently. One acknowledgment of, say, `composition.low_completeness` at 09:35 silently hides every future distinct occurrence of that same alert name for the rest of the process — including a brand-new breach at 14:00 with a completely different `context`. This is distinct from (and worse than) simple non-deduplication: it's over-suppression of genuinely new incidents. Contrast with `HorizonMetricsCollector`'s own state-change throttle for `composition.solver_degraded` (`monitoring/horizon_metrics.py:264-282`), which correctly re-arms on a transition back to healthy (well-tested: `tests/monitoring/test_solver_degraded_alert.py:77-82`) — that pattern is the right model and isn't applied to `InMemoryAlertManager` itself.
3. **Any alert computed but never routed/surfaced?** No fully dead alerts found — everything published to the bus reaches `InMemoryAlertManager.emit()` when one is wired (`orchestrator.py:6002-6004`), which is unconditional in the only production bootstrap path. The closer miss is **severity capping**: `ib_connectivity_event` is computed and published, but pinned to WARNING such that it never reaches the log-worthy/action-worthy branches of `emit()` (§1 P0).
4. **Severity mapping aligned with operator response?** The documented SLA table (`core/events.py:431-438`: INFO async, WARNING <15min, CRITICAL <1min + "activates safety controls", EMERGENCY immediate) is not fully realized — see P1 in §1. `ib_connectivity_event` (an event that, per the IB API, includes genuine link-loss) is filed at WARNING (<15 min human response, no automated action), which under-classifies a scenario with open-position risk. `g12_realized_cost_exceeds_disclosure` correctly escalates from WARNING to CRITICAL on a repeated-breach streak (`orchestrator.py:5773-5777`) and is a good model for how severity-by-persistence should look elsewhere.

---

## 7. Observability & provenance audit (Inv-13, Inv-10)

1. **Structured logging.** `monitoring/structured_logging.py` is Protocol-only (confirmed zero concrete implementations, no JSON-lines log sink anywhere in `src/`). Actual logging is plain stdlib `logging.getLogger(__name__)` with `%s`-interpolated messages throughout `orchestrator.py` and elsewhere — functional for a human tailing logs, materially weaker than the documented "one JSON stream per layer, machine-parseable, correlation-ID-carrying" design for automated post-incident reconstruction. The typed bus events (`Alert`, `MetricEvent`, `KillSwitchActivation`) partially compensate — they *are* structured and *do* carry `correlation_id` — but they are only as complete as what's published (see §3.1's provenance gap: 2 of 3 kill-switch activations never emit `KillSwitchActivation`).
2. **Clock discipline.** Ingestion and monitoring-collector code paths are clean: no `datetime.now()`/`time.time()`/`datetime.utcnow()` found in `src/feelies/ingestion/`, `src/feelies/monitoring/` (all of `horizon_metrics.py`, `in_memory.py`, `paper_session_recorder.py` inherit timestamps from the triggering event or an injected clock), or `src/feelies/broker/ib/`. The one violation found is at the operator-script layer, not core `src/feelies/` logic: **`scripts/run_paper.py:140,173`** — `datetime.now(UTC).timestamp() * 1_000_000_000` written directly into `session_start_ns`/`session_end_ns` in the `PaperSessionRecorder`'s `metadata.json` (via `_wire_session_recorder`/`_flush_session_recorder`, `run_paper.py:122-178`). Blast radius is limited to session-envelope bookkeeping (not the deterministic per-tick timestamp path the replay-parity hashes depend on), but it's a direct, citable Inv-10 finding exactly where the audit asked to look. Two secondary, lower-severity clock notes: `time.monotonic()` is used directly (bypassing the injectable `Clock`) in `ingestion/massive_ingestor.py` (REST-paging progress callback) and `broker/ib/connection.py` (connect-handshake deadline) — both are monotonic (not wall-clock) and both are live-I/O operational timers outside the deterministic tick pipeline, so this is a minor hygiene note, not an Inv-10 violation in the strict (wall-clock) sense.
3. **`PaperSessionRecorder` sufficiency.** Captures signals, order acks, fills, timing rows, and idle-tick counts, all sorted deterministically by `(timestamp_ns, sequence)` before JSONL write (`paper_session_recorder.py:145-153`) — good for parity comparison against a backtest replay of the same session. It does **not** capture `Alert` events, `KillSwitchActivation`, or `DataHealth`/macro-state transitions in its own JSONL streams (only `Signal`/`OrderAck` are wired via `on_event`, `run_paper.py:151-154`) — so a post-incident paper-vs-backtest comparison would show *what* traded but not *why the session degraded*, if it did. That correlation currently depends entirely on separately cross-referencing stdlib log output with the JSONL files by timestamp.
4. **Metrics.** `InMemoryMetricCollector` and `HorizonMetricsCollector` are solid: deterministic (no time reads of their own — `horizon_metrics.py:44-49`), well-tested (`tests/monitoring/test_sensor_metrics.py`, `test_solver_degraded_alert.py`), and correctly use a metric-dedicated `SequenceGenerator` separate from the locked event-sequence streams (Inv-A parity concern, verified by `test_sensor_metrics.py`'s explicit design note).

---

## 8. Test gap matrix

| Invariant / behavior | Status | Evidence |
|---|---|---|
| Kill switch blocks new order flow once active | **Covered** | `tests/kernel/test_orchestrator.py` (tick-gate tests, not itemized here — out of `tests/monitoring/` scope) exercises `orchestrator.py:2292` indirectly via macro-state assertions |
| `InMemoryKillSwitch` activate/reset/history semantics | **Covered** | `tests/monitoring/test_in_memory.py:162-200` |
| **`KillSwitch` Protocol's own fail-closed-on-throw contract** | **Missing** | No test anywhere constructs a `KillSwitch` whose `is_active`/`activate` raises. See §3.2 spec below |
| CRITICAL does not (but per docstring "should") auto-trip | **Covered, but proves the contract violation rather than closing it** | `tests/monitoring/test_in_memory.py:129-133` |
| EMERGENCY auto-trips kill switch | **Covered in isolation; unreachable in production** | `test_in_memory.py:123-127`; zero production `AlertSeverity.EMERGENCY(` emitters |
| Alert acknowledgment doesn't over-suppress future distinct alerts | **Missing** | No test asserts a second, later occurrence of an already-acknowledged `alert_name` remains visible |
| `DataHealth.CORRUPTED` → macro DEGRADED + force-flatten | **Partially covered** | `tests/ingestion/test_data_integrity.py`, `test_massive_normalizer.py` cover the enum/normalizer side; `tests/kernel/test_data_integrity_runtime.py` covers GAP_DETECTED, boot-coverage, strict-coverage, and HALTED at the orchestrator-gate level (4 classes, `test_data_integrity_runtime.py:153-224`) but **not CORRUPTED** at that same orchestrator-gate level |
| `degrade_on_data_gap` default-True behavior | **Covered** | `test_data_integrity_runtime.py:153-166` |
| LULD `halt_on_condition_codes` empty-by-default ⇒ inert, with no operator warning | **Missing** | No test asserts/warns on empty halt-code config in a PAPER/LIVE `PlatformConfig` |
| Broker disconnect ⇒ any safety response | **Missing** | No test exists because no production behavior exists to test; `router.py:236-237`'s own `TODO` comment is the only acknowledgment of the gap |
| IB connectivity alert severity / routing | **Not covered** | No test in `tests/broker/ib/` (out of primary scope, but relevant here) asserts `ib_connectivity_event`'s severity or its (non-)effect on kill switch/macro |
| Macro `DEGRADED`/`RISK_LOCKDOWN` never auto-loosen | **Covered structurally** by the transition table itself (`kernel/macro.py`), reinforced by `tests/kernel/test_orchestrator.py`'s escalation tests | — |
| `unlock_from_lockdown` zero-exposure guard | **Covered** | `tests/kernel/test_orchestrator.py` (escalation/lockdown suite, not itemized here) |
| Paper-session E2E: data-gap degrade, risk lockdown, G12 alert | **Exists but effectively never runs** | `tests/integration/test_paper_rth_safety.py`, gated `functional`+`paper_rth`, requires live IB Gateway + `MASSIVE_API_KEY` + US RTH window (`tests/paper/conftest.py`'s `require_*` guards) — confirmed skipped (3/3) in this audit's read-only run |
| `HorizonMetricsCollector` solver-degradation alert throttle/re-arm | **Well covered** | `tests/monitoring/test_solver_degraded_alert.py` (5 tests, all pass) |
| `monitoring/health.py` `HealthRegistry`/`HealthCheck` | **N/A — no implementation exists to test** | Confirmed dead code, §5 |

**Minimal new tests proposed (spec only, no code in this pass):**

1. *Kill-switch-throws → halt.* A `KillSwitch` stub whose `is_active` property raises; drive one `_process_tick` call; assert macro transitions to `DEGRADED` (not left in a trading mode) and no `OrderRequest` was published. Targets §3.2.
2. *Health/macro-never-loosens property test.* For every `(from_state, to_state)` pair reachable only through `DEGRADED`/`RISK_LOCKDOWN`, assert the transition requires one of the two named recovery methods and cannot be reached by replaying an arbitrary tick sequence alone (a Hypothesis-style state-machine test over `_MACRO_TRANSITIONS` would directly formalize §5.2).
3. *Trigger-coverage matrix as executable assertions.* One parametrized test per row of §4 marked "No" — starting with broker-disconnect-produces-no-response and silent-feed-stall-produces-no-alert — asserting today's (gap) behavior, so a future fix is a visible test flip rather than a silent behavior change.
4. *Alert re-arm after acknowledgment.* Emit alert A, acknowledge it, emit a **new instance** of alert A (fresh `context`/timestamp) — assert it reappears in `active_alerts()`. Currently would fail against `in_memory.py:142-147`.
5. *`ib_connectivity_event` severity assertion.* Directly test `bootstrap.py`'s `_publish_ib_alert` closure (or the `IBConnection.error()` callback) to lock in current WARNING severity as an explicit, visible baseline — so any future change to that hardcoded value is deliberate, not accidental.

---

## 9. Prioritized backlog

| ID | Component | file:line | One-sentence fix | Safety impact | Effort |
|---|---|---|---|---|---|
| **P0-1** | Broker connectivity → safety response | `broker/ib/connection.py:387-422`; `bootstrap.py:759-771`; `broker/ib/router.py:236-247` | Escalate IB disconnect codes (1100 esp.) to CRITICAL/EMERGENCY and wire the order-scoped path's `TODO` into a typed `Alert`, so a disconnect with open positions triggers macro DEGRADED at minimum | Closes the audit's named canonical "uncovered catastrophic failure mode" | M |
| P1-1 | Alert severity contract | `core/events.py:436,450`; `monitoring/alerting.py:28-30,40-41`; `monitoring/in_memory.py:129,136` | Either implement CRITICAL auto-trip (or a documented intermediate action) to match the docstring, or rewrite the docstrings to describe EMERGENCY-only auto-trip, and add at least one production EMERGENCY emitter | Removes a documented-but-false safety promise that a future engineer could reasonably rely on | S (docs) / M (behavior) |
| P1-2 | Kill-switch docstring vs. behavior | `monitoring/kill_switch.py:3-8`; `monitoring/in_memory.py:192-201` | Rewrite the module docstring to describe actual per-path behavior (halt-only vs. halt+flatten), or extend `InMemoryKillSwitch.activate()` to also request a flatten uniformly | Prevents an operator from assuming a manual/EMERGENCY kill-switch pull also flattens positions when it doesn't | S |
| P1-3 | LULD halt inert-by-default | `core/platform_config.py:126-132` | Emit a boot-time WARNING (or hard-fail) when `halt_on_condition_codes` is empty and `mode ∈ {PAPER, LIVE}` | Removes a silent safety gap that currently requires reading source comments to discover | S |
| P1-4 | Misleading test file names | `tests/monitoring/test_kill_switch.py`, `test_alerting.py` | Either import/exercise `InMemoryKillSwitch`/`InMemoryAlertManager` directly in these files, or rename them to `test_kill_switch_protocol.py` and cross-reference `test_in_memory.py` | Removes false confidence that these files regression-protect the shipped classes | S |
| P1-5 | Fail-open-by-omission default | `kernel/orchestrator.py:490,493` | Make `kill_switch` a required constructor argument (matching `metric_collector`), or require an explicit `NullKillSwitch` sentinel that logs loudly at construction | Removes a structural footgun for any future bootstrap/entry point | S |
| P1-6 | Kill-switch-throws untested | `kernel/orchestrator.py:2151-2178` | Add the test specified in §8 item 1 | Converts an incidental safety property into a guaranteed, regression-tested one | S |
| P1-7 | Alert ack over-suppression | `monitoring/in_memory.py:142-147` | Scope acknowledgment to a specific alert instance (e.g. `(alert_name, sequence)` or a time-bounded ack), not the bare name forever | Restores visibility of genuine re-alerts after a prior ack | S |
| P1-8 | `StructuredLogger` unimplemented | `monitoring/structured_logging.py` | Ship a minimal `JsonlStructuredLogger` (or explicitly retire the protocol and document stdlib logging as the intentional design) | Closes the gap between documented and actual incident-reconstruction capability | M |
| P1-9 | `HealthRegistry` dead code | `monitoring/health.py` | Either wire it (register `DataHealth`/order-router/broker-connection checks) or retire the protocol and redirect the skill docs to the real mechanisms (§5) | Removes a misleading abstraction that currently has no bearing on runtime safety | M |
| P1-10 | Inv-10 in paper recorder | `scripts/run_paper.py:140,173` | Route `session_start_ns`/`session_end_ns` through the orchestrator's injected clock instead of `datetime.now(UTC)` | Restores replay-consistency of session metadata (Inv-10) | S |
| P1-11 | Silent feed-stall undetected | `ingestion/massive_ws.py:113-119`; `orchestrator.py:1812-1817` | Add an idle-duration threshold that promotes sustained `IdleTick` streaks to a `DataHealth`/alert signal | Closes a real (if narrow) staleness-detection gap | M |
| P1-12 | Inconsistent activation provenance | `orchestrator.py:5811-5814`; `monitoring/in_memory.py:136-140` | Publish `KillSwitchActivation` from these two call sites too, matching `orchestrator.py:3654-3662` | Restores full Inv-13 provenance for every activation path, not just one | S |
| P2-1 | Vacuous `_verify_data_integrity` | `orchestrator.py:6740-6777` | Default `require_healthy_disk_cache_manifests` to `True`, or require an explicit operator opt-out with a logged reason | Low live-capital impact (PAPER/LIVE unaffected); tightens BACKTEST/replay hygiene | S |
| P2-2 | No retry after failed flatten | `orchestrator.py:3770-3792,6711-6738` | Document as an accepted design choice, or add a bounded retry with backoff before falling back to alert-only | Currently correct-but-passive; explicit owner sign-off recommended | S (docs) / M (retry) |
| P2-3 | `time.monotonic()` bypasses injected clock | `ingestion/massive_ingestor.py`; `broker/ib/connection.py` | Route through `Clock` for consistency, even though not wall-clock | Cosmetic/consistency only | S |
| P2-4 | Misspelled alert name | `orchestrator.py:6727` | Fix `"degrase_flatten_failed"` → `"degrade_flatten_failed"` | Any exact-match alert-routing rule silently misses this CRITICAL alert today | S |
| P2-5 | No operator entry point for `recover_from_degraded()` | `scripts/run_paper.py` (absent) | Add a CLI/script hook if in-process recovery is ever desired for PAPER | Purely operational; current behavior (process restart) is conservative, not unsafe | S |

---

## Appendix — files read for this audit

`src/feelies/monitoring/{kill_switch,health,alerting,in_memory,telemetry,structured_logging,horizon_metrics,paper_session_recorder,__init__}.py`;
`src/feelies/kernel/{orchestrator,macro}.py` (targeted sections: kill-switch gates, `_escalate_risk`, `_data_health_blocks_trading`, `_verify_data_integrity`, `_process_tick`/`_handle_tick_failure`, alert-forwarding, G12 escalation);
`src/feelies/bootstrap.py` (monitoring/kill-switch/alert-manager/normalizer/IB-alert wiring);
`src/feelies/risk/escalation.py`;
`src/feelies/ingestion/data_integrity.py`, `ingest_health.py`, `massive_normalizer.py` (targeted), `idle_tick.py`, `massive_ws.py` (targeted);
`src/feelies/broker/ib/connection.py`, `router.py` (targeted);
`src/feelies/core/{events,platform_config,clock}.py` (targeted);
`scripts/run_paper.py`;
`tests/monitoring/*.py`; `tests/ingestion/test_ingest_health.py`; `tests/kernel/test_data_integrity_runtime.py`; `tests/integration/test_paper_rth_safety.py`;
`docs/three_layer_architecture.md` §14; `.cursor/rules/platform-invariants.mdc`; `.cursor/skills/{live-execution,risk-engine,regime-detection}/SKILL.md`.
