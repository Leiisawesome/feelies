# Feelies SIGNAL Alpha Audit — 2026-07-02

Read-only audit of the Layer-2 SIGNAL layer per `docs/prompts/audit_signal_alpha.md`: the
`HorizonSignal` alphas, `HorizonSignalEngine`, `cost_arithmetic` disclosure, the
`trend_mechanism` (G16) taxonomy, and the `Signal` event contract. No production code,
baselines, configs, or ledgers were modified.

**Agent context loaded (in order):**

1. `.cursor/rules/platform-invariants.mdc` — Inv-1, 2, 5, 6, 7, 12; glossary (horizon
   signal, cost arithmetic, trend mechanism, hazard exit).
2. `.cursor/rules/karpathy-guidelines.mdc`.
3. `.cursor/skills/README.md` — parity L2 → testing-validation; layer topology →
   system-architect.
4. `.cursor/skills/microstructure-alpha/SKILL.md` (**owner**).
5. `.cursor/skills/feature-engine/SKILL.md` — sole Layer-2 input contract
   (`HorizonFeatureSnapshot`).

**Not shipped cross-check:** `microstructure-alpha/SKILL.md` carries no "Not shipped"
sections — every contract it documents (regime-gate DSL, cost arithmetic, G16, hazard
exit) is implemented and tested. `feature-engine/SKILL.md`'s one "Not shipped" item
(sensor checkpoint/warm-start persistence) is a Layer-1 concern with no bearing on SIGNAL
correctness; confirmed no false-P0 risk from design-target confusion this cycle.

**Prior audits:** [`signal_alpha_audit_2026-06-20.md`](signal_alpha_audit_2026-06-20.md)
(full), [`signal_alpha_audit_2026-06-14.md`](signal_alpha_audit_2026-06-14.md) (origin of
the `sig_inventory_revert_v1` quarantine). This pass re-verifies every prior claim against
current `HEAD` (`929e9fb6`, 2026-07-01T20:28+08:00) rather than assuming carry-forward
validity — two 06-20 backlog items turned out to already be resolved (§8), and two new
issues were found and empirically reproduced (§3.5).

Assumptions (unchanged from 06-20 unless noted):

- "Reference SIGNAL alphas" = the 5 discovered non-template `sig_*` specs plus the
  underscore-excluded `paper_smoke_v1` smoke fixture.
- "Cost survival" is evaluated from disclosed YAML arithmetic and code contracts, not a
  new market-data backtest — this audit ran no new data-driven IC/PnL study.
- A pass on static G16/G12 validation is evidence the spec satisfies the repository's
  declared structural contracts, not evidence of a live edge.
- Severity: P0 correctness/safety, P1 economic soundness, P2 research/product hardening,
  per the audit prompt's rubric. Findings whose blast radius is confined to a metrics
  counter (never the locked `Signal` bus, never capital) are still reported at the
  severity their *reachability and current dormancy* warrant, with that scoping stated
  explicitly rather than mechanically forced into P0.

---

## 1. Executive Summary

1. **No P0** correctness/safety defect confirmed in the SIGNAL engine, gates, or shipped
   alphas this cycle. Four independent read-only test runs are green (974 tests across
   `tests/signals/`, `tests/alpha/`, `tests/determinism/`, `tests/acceptance/` scope, 1
   skip; §"Verification Run"); scoped `mypy --strict` on every file in this audit's scope
   is clean.
2. **RESOLVED since 06-20:** the G16 rule-7 static-analysis gap on dynamic
   `LIQUIDITY_STRESS` direction expressions is closed by an unconditional runtime
   backstop — the engine suppresses **any** non-`FLAT` signal from an
   `EXIT_ONLY_MECHANISMS`-registered alpha regardless of how the direction was computed
   (`src/feelies/signals/horizon_engine.py:580-590`); tested
   (`tests/signals/test_horizon_signal_engine.py:1021-1043`).
3. **RESOLVED, correcting a 06-20 backlog item:** a real, end-to-end-wired, tested
   promotion cap already blocks `sig_inventory_revert_v1` (and any
   `lifecycle_state: RESEARCH` alpha) from reaching PAPER/LIVE
   (`src/feelies/alpha/lifecycle.py:301-309`, wired via `AlphaRegistry.register` →
   `lifecycle_cap=manifest.lifecycle_cap`, tested
   `tests/alpha/test_sig_inventory_revert_v1.py:66-79`). The 06-20 report's "add a
   promotion test" P1 was already satisfied; see §8 for the (much narrower) residual.
4. **NEW — P1, empirically reproduced (Inv-13):** ENG-2 observability double-counts the
   `feelies.signal.gate.transition{to=ON}` counter exactly when a gate's `on_condition`
   first evaluates true while the entry is warm/stale-blocked. The deliberate
   `mutate=False` design correctly withholds the latch commit in that case
   (`horizon_engine.py:401-411`), but the metric-emission logic
   (`horizon_engine.py:519-525`) fires off the function's *returned* value, not whether
   the mutation actually committed. Reproduced directly against the engine (§3.5):
   one logical admission emits `gate.transition` **twice**. Confined to the metrics
   collector — verified it cannot perturb the locked `Signal` bus or cause a phantom
   `_publish_gate_close` — but it corrupts the one counter an operator would use to
   detect real regime-gate flapping, and it does so preferentially during data-quality
   gaps, which is exactly when that signal matters most.
5. **NEW — P1 (Inv-13):** the engine still lets an alpha's returned
   `Signal.expected_half_life_seconds` silently override the G16-validated `registered`
   value (`horizon_engine.py:812-816`). Unlike `trend_mechanism` (which needs the
   `TrendMechanism` enum — absent from the loader's compiled-code sandbox,
   `src/feelies/alpha/loader.py:1458-1478`, so **unreachable** from any YAML-authored
   alpha today), `expected_half_life_seconds` is a bare `int` any inline `signal:` body
   can set with no special import. No shipped alpha does this, and the only live
   consumer of the per-event field (`CrossSectionalRanker` decay weighting,
   `src/feelies/composition/cross_sectional.py:295,298,440,443,515,518`) is disabled by
   default on both PORTFOLIO research alphas — so blast radius is zero today. The
   hazard-exit `hard_exit_age_seconds` derivation is unaffected: it reads the
   *registered module's* value, not the per-event field
   (`src/feelies/bootstrap.py:2154`).
6. **STILL OPEN — P1 (Inv-12), unchanged since 06-14/06-20:** `cost_floor_bps` (the
   only per-alpha self-suppression against sub-cost entries) is never checked against
   `cost_arithmetic.cost_total_bps` at load time. Every production alpha declares
   `min: 0.0` on this parameter, so a config override can zero it with no gate noticing
   — the runtime B4 gate (`orchestrator.py:3146`) remains the sole backstop.
7. **STILL OPEN — P2, unchanged:** the engine has no duplicate-`(alpha_id, symbol,
   boundary_index)` idempotence check (`horizon_engine.py:338-345`); a duplicate
   upstream `HorizonFeatureSnapshot` would be dispatched twice.
8. **Cost arithmetic is honest** for all 6 specs — independently recomputed every
   `margin_ratio` from disclosed components (§6); all reconcile exactly (0.00 residual)
   and all clear the ≥1.5 one-way G12 floor. But none of the 5 production alphas'
   disclosed edge clears even a **1.0×** round-trip cost estimate (raw RT margins
   0.8–1.0), so live viability depends entirely on the runtime B4 gate's selectivity on
   the *live-computed* edge, never on the disclosed peak.
9. **Verified not a defect:** `platform.yaml`'s `signal_min_edge_cost_ratio: 1.0` (below
   the Inv-12 1.5× bar) is an intentional, explicitly-documented research-only default
   (`platform.yaml:144-156`, "Audit P1-3"). Every trading-adjacent config
   (`bt_multialpha`, `bt_sig_*`, `paper_run`, `paper_smoke_rth`) already overrides to
   1.5, and the override is asserted by
   `tests/acceptance/test_backtest_app_config_keys.py:103,117`.
10. `sig_inventory_revert_v1` remains correctly quarantined by its own recorded
    forward-IC failure (pooled ρ≈-0.007, contra-indicated SHORT leg) — no new evidence
    this cycle changes that; still the platform's clearest example of the promotion
    pipeline enforcing a negative result rather than papering over it.
11. `sig_moc_imbalance_v1` remains honest that its directional edge is an exogenous
    calendar prior, not an L1-observable mechanism — OFI only confirms, never derives,
    direction (Inv-1 compliance by explicit disclosure, not by claiming a mechanism it
    doesn't have).
12. Multi-alpha standalone arbitration (`EdgeWeightedArbitrator`) is deterministic,
    `FLAT`-privileged, and picks one winner rather than stacking same-direction
    evidence — unchanged, still the correct conservative default. Both research
    PORTFOLIO alphas remain explicitly decommissioned from production discovery
    (`N=3` universe, `IR = IC·√N` argument) — unchanged.
13. A resolved *upstream* causality fix (`08c3da6`, feature-engine layer, cited for
    context only) closed a latent lookahead-adjacent bug where snapshot staleness was
    computed against the triggering event's timestamp instead of the true horizon
    boundary on sparse tapes. Verified present at `HEAD`
    (`src/feelies/features/aggregator.py:511-531`); full feature-engine review is out
    of this audit's scope (see `audit_sensor.md`).
14. Engine-mechanics determinism now has a **non-empty** replay lock
    (`tests/determinism/test_signal_fires_replay.py`, a synthetic probe alpha walking
    OFF→ON→OFF) pinning sequence allocation, gate-close emission, and
    mechanism/half-life provenance stamping. This narrows — but does not close — the
    standing P2 that no *real* reference alpha has a non-empty economic replay baseline
    on realistic data (the Level-2 `sig_*` baseline is still the empty-stream hash;
    §3.3).
15. Highest-value next work is unchanged in kind from 06-20: per-alpha OOS IC / stressed
    B4 survival on cached NBBO. The in-flight `gas_02_fast_ofi_momentum` research note
    (`docs/research/gas_02_fast_ofi_momentum.md`) is a good template for this platform —
    pre-registered cost-gate criteria, no alpha authored until the gate passes.

---

## 2. SIGNAL Alpha Inventory

| Alpha | Layer | Lifecycle | Horizon | Mechanism | Half-life | Ratio h/hl | Main sensors | Cost basis | Edge bps | One-way cost bps | G12 margin | Raw RT margin | Strict G16 |
|---|---|---|---:|---|---:|---:|---|---|---:|---:|---:|---:|---|
| `paper_smoke_v1` | SIGNAL | not declared (test fixture) | 30s | none | n/a | n/a | `micro_price`, `realized_vol_30s` | n/a | 10.0 | 2.5 | 4.00 | 2.00 | intentionally off (smoke config only) |
| `sig_benign_midcap_v1` | SIGNAL | RESEARCH | 120s | KYLE_INFO | 120s | 1.00 | `ofi_ewma`, `micro_price`, `book_imbalance`, `spread_z_30d`, `realized_vol_30s` | one_way | 9.0 | 5.0 | 1.80 | 0.90 | pass |
| `sig_hawkes_burst_v1` | SIGNAL | RESEARCH | 30s | HAWKES_SELF_EXCITE | 30s | 1.00 | `hawkes_intensity`, `trade_through_rate`, `ofi_ewma`, `spread_z_30d`, `realized_vol_30s` | one_way | 8.0 | 5.0 | 1.60 | 0.80 | pass |
| `sig_inventory_revert_v1` | SIGNAL | RESEARCH, **quarantined** (`lifecycle_cap="RESEARCH"` enforced) | 30s | INVENTORY | 20s | 1.50 | `quote_replenish_asymmetry`, `spread_z_30d`, `quote_hazard_rate`, `realized_vol_30s` | one_way | 8.8 | 5.5 | 1.60 | 0.80 | pass |
| `sig_kyle_drift_v1` | SIGNAL | RESEARCH | 300s | KYLE_INFO | 600s | 0.50 | `kyle_lambda_60s`, `ofi_ewma`, `micro_price`, `spread_z_30d`, `realized_vol_30s` | one_way | 11.7 | 6.5 | 1.80 | 0.90 | pass |
| `sig_moc_imbalance_v1` | SIGNAL | RESEARCH | 120s | SCHEDULED_FLOW | 240s | 0.50 | `scheduled_flow_window`, `ofi_ewma`, `realized_vol_30s` | one_way | 12.0 | 6.0 | 2.00 | 1.00 | pass |
| `pro_burst_revert_v1` (PORTFOLIO, research-only) | PORTFOLIO | RESEARCH, decommissioned from discovery | 300s | consumes HAWKES_SELF_EXCITE(≤0.6) + INVENTORY(≤0.6) | — | — | via `sig_hawkes_burst_v1`, `sig_inventory_revert_v1` | n/a | 10.0 | n/a | 2.5 | n/a | consumes-cap sum ≥1.0 (0.6+0.6=1.2) |
| `pro_kyle_benign_v1` (PORTFOLIO, research-only) | PORTFOLIO | RESEARCH, decommissioned from discovery | 300s | consumes KYLE_INFO(≤1.0) | — | — | via `sig_benign_midcap_v1`, `sig_kyle_drift_v1` | n/a | 10.0 | n/a | 2.22 | n/a | consumes-cap sum ≥1.0 (1.0) |

Notes (independently re-derived this cycle, not copied from 06-20):

- All five production `sig_*` specs pass the G16 `horizon_seconds /
  expected_half_life_seconds ∈ [0.5, 4.0]` band (`layer_validator.py:944-950`); ratios
  land at exactly 0.5, 1.0, or 1.5 — none in the interior, i.e. every alpha operates at
  a band edge or the natural midpoint, not an arbitrarily-tuned value.
  `sig_inventory_revert_v1` at 1.50 is the outlier worth watching: its own YAML
  comments (`parameters.realized_capture_ratio`) already concede the 30s horizon
  overshoots its 20s half-life and compensate with an explicit capture-ratio tax —
  see §4.
- `paper_smoke_v1` is excluded from discovered active-alpha tests because underscore
  path segments are filtered
  (`tests/alpha/test_discovered_alpha_specs_load.py`); confirmed unchanged — no
  `trend_mechanism:` block, loads only via `configs/paper_smoke_rth.yaml` with strict
  trend enforcement explicitly disabled.
- "Raw RT margin" = `edge_estimate_bps / (2 × cost_total_bps)` from disclosed YAML
  values (`cost_basis: one_way` in every production spec) — not the runtime cost-model
  result. See §6 for the stress matrix.
- Both research PORTFOLIO alphas explicitly self-document
  (`notes:` field) that they were "decommissioned from production discovery" at
  sub-$250k scale because `IR = IC·√N` with `N=3` doesn't justify the composition
  layer's complexity — this is the alpha authors correctly declining to over-engineer,
  not an audit finding.
- Source anchors (`alphas/<id>/<id>.alpha.yaml`): `sig_kyle_drift_v1` cost/trend/signal
  at lines 122-131 / 133-144 / 147-181; `sig_hawkes_burst_v1` at 117-126 / 128-138 /
  150-184; `sig_inventory_revert_v1` at 188-199 / 201-212 / 214-269;
  `sig_moc_imbalance_v1` at 135-144 / 146-155 / 157-214; `sig_benign_midcap_v1` at
  140-149 / 161-171 / 173-235.

---

## 3. Engine Audit

Scope: `src/feelies/signals/horizon_engine.py` (`HorizonSignalEngine`, `RegisteredSignal`),
`src/feelies/signals/horizon_protocol.py` (`HorizonSignal` Protocol),
`src/feelies/signals/regime_gate.py` (`RegimeGate`, purity boundary).

### 3.1 Purity

`HorizonSignal.evaluate(snapshot, regime, params)` is documented as a pure function with
no per-instance mutable state (`horizon_protocol.py:22-26`). The adapter that wraps
inline YAML `signal:` code, `_CompiledHorizonSignal`
(`src/feelies/alpha/signal_layer_module.py:222-260`), holds only immutable
`signal_id`/`signal_version`/`_fn` slots and forwards every call — no closure-side cache,
confirmed by reading the class body directly (no mutable attribute is ever written after
`__init__`).

The compiled-code sandbox (`AlphaLoader._build_namespace`,
`src/feelies/alpha/loader.py:1458-1478`) exposes only `Signal`, `SignalDirection`,
`NBBOQuote`, `Trade`, the `LONG`/`SHORT`/`FLAT` direction constants, `alpha_id`, and
(when a regime engine is bound) `regime_posteriors`/`regime_state_names` — with
`"__builtins__": {}`. This is a materially important finding for §3.5 below: **`Signal`
and `SignalDirection` are constructible, but `TrendMechanism` is not in this namespace at
all** — a YAML-authored `signal:` body cannot reference `TrendMechanism.<anything>`; the
name simply doesn't exist in its execution scope. G5 (`layer_validator.py:584-616`, not
re-audited in depth here — owned by `audit_alpha_lifecycle.md`) additionally AST-bans
`Attribute`/`Import`/`global`/`nonlocal`. Together these close off any route by which a
YAML alpha could spoof a `TrendMechanism` value (§3.5, finding P1-b).

No alpha's `evaluate()` body (all 5 production specs read line-by-line, §4) performs I/O,
reads a clock, or mutates `params`/`snapshot`. Residual risk (unchanged from 06-20):
purity is enforced by sandbox + static AST scan, not by a runtime property test that
calls every loaded alpha twice with the identical snapshot object and asserts bitwise
output equality *and* no mutation of `params`/`snapshot.values` — no such test exists in
`tests/alpha/test_sig_*.py` today (spot-checked `test_sig_kyle_drift_v1.py`,
`test_sig_inventory_revert_v1.py` — both assert output values, not idempotence-under-
repeated-call). P2 (§8).

### 3.2 Causality

`evaluate()` receives only the current `HorizonFeatureSnapshot` and the contemporaneous
`RegimeState` (or `None`); it never touches `HorizonSignalEngine._sensor_cache` or raw
`NBBOQuote`/`Trade` events — those are engine-internal and never passed into `evaluate()`
(`horizon_engine.py:541-546`). All 5 production alphas read exclusively from
`snapshot.values.get(...)` (verified by direct read of every `signal:` block, §4) — none
subscript a live cache or hold module-level state across calls.

The **regime-gate** DSL is a different causality surface: gate *bindings* are built from
`snapshot.values` first, falling back to `HorizonSignalEngine._sensor_cache` (latest
event-time reading) only for identifiers absent from the snapshot
(`horizon_engine.py:726-758`, `setdefault` priority rule). This is documented and
intentional (v0.2 passive-aggregator compatibility) but means "the snapshot is the only
input" is literally true for `evaluate()` and not literally true for **gate expressions**
— unchanged assessment from 06-20, still accurate, still a modeling choice rather than a
bug (the cache is itself event-time-only, never ahead of the boundary, since
`_on_sensor_reading` only ever records readings as they arrive on the bus in event order).

**Resolved upstream (context, not re-audited in full — feature-engine layer):** commit
`08c3da6` (2026-06-29, predates this audit window's baseline) fixed a real
causality-adjacent defect in `HorizonAggregator._build_snapshot`
(`src/feelies/features/aggregator.py:474-531`). Before the fix, per-feature staleness was
computed as `tick.timestamp_ns - last_reading_ns`, where `tick.timestamp_ns` is the
*triggering* event's timestamp — which on a sparse tape can land strictly **after** the
true nominal horizon boundary. That means a sensor reading published *after* the boundary
but *before* the (later) triggering event could be picked up as "the latest warm
reading," making a feature appear fresher than it should be for the boundary actually
being finalized — a lookahead-adjacent violation of Inv-6. The fix introduces
`asof_timestamp_ns` (`HorizonTick.boundary_ts_ns` fallback to `timestamp_ns`,
`core/events.py:592-624`) and a `_latest_warm_reading_ns_at_or_before(..., asof_ns=...)`
helper that explicitly filters `ts_ns <= asof_ns` (`aggregator.py:579-599`). Verified
present at `HEAD`; tested (`tests/features/test_aggregator.py`,
`tests/core/test_new_events.py`). This is squarely feature-engine territory (owned by
`audit_sensor.md`) — flagged here only because it directly underwrites the causality
guarantee this audit's Section A asks about, and it changed the same commit
(`08c3da6`) that added `RegimeGate.evaluate(mutate=False)` (§3.4).

### 3.3 Ordering / Determinism

Registered signals are sorted by `(horizon_seconds, alpha_id)` at registration time
(`horizon_engine.py:238-242`), so dispatch order is a deterministic function of the
registered id set, independent of registration call order. All emitted `Signal` events
draw from one dedicated `signal_sequence_generator`
(never the orchestrator's main `_seq`) — `horizon_engine.py:592-598, 614-634, 776-819`.

The Level-2 SIGNAL parity test (`tests/determinism/test_signal_replay.py`) hashes the
`Signal` stream from all 5 v0.3 reference alphas on a canonical synthetic fixture. Its
own docstring states plainly that on this fixture **every alpha stays below its entry
threshold** — the locked baseline is the SHA-256 of an empty stream, verified accurate by
reading the file (`tests/determinism/test_signal_replay.py:1-26`). This pins "no
accidental emission / no subscription drift," not economic behavior. A second,
newer test (`tests/determinism/test_signal_fires_replay.py`, added since 06-20) closes
the adjacent gap the first test's docstring calls out explicitly ("a real
signal-emission-ordering or sequence-reuse bug could not be caught") by driving a
synthetic probe alpha through a deterministic OFF→ON→ON→OFF→ON gate walk and hashing the
**non-empty** resulting stream — locking sequence allocation, `regime_gate_state`
stamping, gate-close FLAT emission, and mechanism/half-life provenance propagation. This
is real progress on engine-mechanics determinism, but it is still a synthetic probe, not
a real reference alpha (`sig_kyle_drift_v1`, etc.) replayed non-empty on realistic NBBO —
that remains a data-dependent open item (§9).

**Duplicate-boundary idempotence — still open (P2, unchanged):** `_on_snapshot`
(`horizon_engine.py:338-345`) dispatches every registered signal whose `horizon_seconds`
matches the incoming snapshot with no deduplication key on
`(alpha_id, symbol, boundary_index)`. If an upstream producer ever emits two
`HorizonFeatureSnapshot`s for the same boundary (a bug elsewhere, not observed in this
audit), the engine would evaluate both and could emit two `Signal`s for one boundary.
Nothing in this layer defends against it; the platform currently relies on the upstream
aggregator not doing that.

### 3.4 Warm / Stale Handling

`_dispatch_one` (`horizon_engine.py:349-598`) computes `entry_blocked` from the alpha's
`required_warm_feature_ids` (or, when unset, every key in `snapshot.warm`) —
`not_warm = any(not snapshot.warm[k] ...)`, `is_stale = any(snapshot.stale.get(k, False)
...)` (`horizon_engine.py:375-396`). Crucially, the gate is **still evaluated** when
`entry_blocked` is true — only the *entry* is suppressed afterward
(`horizon_engine.py:527-539`), so an ON→OFF transition on stale data can still publish a
conservative `FLAT` close (`_publish_gate_close`, `horizon_engine.py:600-634`). This
correctly implements the documented contract ("entry suppressed when stale; exits
permitted") and is tested both ways
(`tests/signals/test_horizon_signal_engine.py:353` stale-permits-close,
`:399` stale-suppresses-entry).

**New this cycle — the `mutate` parameter (added by `08c3da6`, ENG-1/ENG-2 window).**
`RegimeGate.evaluate(*, symbol, bindings, mutate=True)`
(`src/feelies/signals/regime_gate.py:700-748`) now accepts `mutate=False`, which
evaluates the ON/OFF transition rules and *returns* the resulting boolean without
*committing* it to `self._state[symbol]`. The engine calls it with:

```python
on = registered.gate.evaluate(
    symbol=snapshot.symbol,
    bindings=bindings,
    mutate=not (entry_blocked and not was_on),
)
```
(`horizon_engine.py:407-411`)

i.e. `mutate=False` **only** in the specific case the gate is currently OFF (`was_on ==
False`) *and* the snapshot is entry-blocked. I traced every other combination:

| `was_on` | `entry_blocked` | `mutate` | Effect |
|---|---|---|---|
| `True` | any | `True` | Normal — a stale/cold snapshot can still commit an ON→OFF transition and fire the FLAT close (Inv-11 fail-safe preserved). |
| `False` | `False` | `True` | Normal — a clean snapshot commits OFF→ON exactly as pre-`08c3da6`. |
| `False` | `True` | **`False`** | New — the on-condition can evaluate true, but the latch does **not** arm. On the *next* clean snapshot, the transition re-evaluates from the same OFF state and commits for real. |

I verified this design is **correct** for the case it targets: it prevents a spurious
`ON` latch from persisting purely because data happened to be stale exactly when
`on_condition` first became true — without it, a later `_publish_gate_close` could fire a
`FLAT` for a position that was never actually opened (no `Signal` was ever emitted while
entry was blocked). Tracing the full state machine confirms this phantom-close scenario
**cannot** occur with the current code, because the OFF→ON commit is withheld until a
boundary where entry is *not* blocked, at which point the real entry and the real
transition happen together.

### 3.5 New Finding — ENG-2 Metric Double-Count (P1, empirically reproduced)

The metric-emission logic downstream of the `mutate` call was **not** updated to match
the new semantics:

```python
if not on:
    return
if not was_on:
    # Normal OFF → ON gate transition (admission).
    self._emit_metric("feelies.signal.gate.transition", ..., tags={..., "to": "ON"})
if entry_blocked:
    self._emit_metric("feelies.signal.entry.suppressed", ...)
    return
```
(`horizon_engine.py:517-539`)

This branches on the *returned* `on` value and the *pre-call* `was_on` snapshot — not on
whether `mutate` actually committed the transition. In the `mutate=False` case, `on=True`
is returned (the on-condition is genuinely true) but `self._state[symbol]` was **not**
updated — yet the `if not was_on:` branch still fires the `"transition"→"ON"` metric.

**Reproduced directly against `HorizonSignalEngine`** (using the existing test helpers in
`tests/signals/test_horizon_signal_engine.py`, no engine modification):

```
Boundary N   (feature cold, gate currently OFF):
    captured Signal count:        0   (correct — entry suppressed)
    gate.transition{to=ON} count: 1   (WRONG — latch was not committed: gate.is_on() == False)
    entry.suppressed count:       1   (correct)

Boundary N+1 (feature warm, gate still OFF from N):
    captured Signal count:        1   (correct — the real entry fires)
    gate.transition{to=ON} count: 2   (WRONG — this is the second count for one admission)
    emitted count:                1   (correct)
```

One logical OFF→ON admission produces **two** `gate.transition{to=ON}` events. The
existing ENG-2 test suite does not catch this: `test_horizon_engine_metrics.py`'s
`test_entry_suppressed_counter_increments_when_required_feature_cold`
(`tests/signals/test_horizon_engine_metrics.py:43-60`) asserts only the
`entry.suppressed` count for exactly this scenario and never checks `gate.transition`;
`test_gate_transition_on_and_emitted_counters_on_real_signal`
(`:63-73`) only exercises the clean (never-blocked) admission path.

**Impact scoping (why this is not P0):** the dedicated `_metrics_seq` generator and the
`MetricCollector` sink are architecturally isolated from the `signal_sequence_generator`
and the bus-published `Signal` stream (`horizon_engine.py:198-206`, confirmed by
inspection — no code path lets a metric event reach `self._bus.publish`), so this cannot
perturb the Level-2 parity hash, capital, or replay determinism of trading decisions
(Inv-5 intact). It **does** corrupt the one telemetry signal (`feelies.signal.gate
.transition`) an operator would consult to distinguish "the regime gate is flapping" from
"the regime gate admitted once, cleanly" — and the false double-count is emitted
*specifically* during the data-quality-gap scenario that operator telemetry exists to
surface (Inv-13 — full, accurate provenance). Fix is a one-line change: gate the metric
emission on `mutate and not was_on` (or equivalently, on the committed post-call
`gate.is_on(symbol)`) rather than on the returned `on` value. S effort.

### 3.6 New Finding — `expected_half_life_seconds` Engine Override (P1)

`_patch_signal` (`horizon_engine.py:776-819`) lets the alpha's own returned `Signal`
override two provenance fields the engine would otherwise stamp from the G16-validated
`RegisteredSignal`:

```python
trend_mechanism=(
    raw.trend_mechanism if raw.trend_mechanism is not None else registered.trend_mechanism
),
expected_half_life_seconds=(
    raw.expected_half_life_seconds if raw.expected_half_life_seconds
    else registered.expected_half_life_seconds
),
```
(`horizon_engine.py:807-816`)

This is intentional and tested as "alpha wins"
(`tests/signals/test_horizon_signal_engine.py:876-919`,
`test_alpha_supplied_mechanism_overrides_registered_default`). I traced whether either
override channel is **reachable** from a real (YAML-loaded) alpha:

- **`trend_mechanism` override — not reachable.** As established in §3.1, the compiled
  sandbox namespace does not bind `TrendMechanism` at all
  (`loader.py:1458-1478`); a YAML `signal:` body cannot construct
  `TrendMechanism.<X>`. The existing test that exercises this path constructs a
  hand-written native Python `HorizonSignal` class, not a compiled YAML alpha
  (`test_horizon_signal_engine.py:881-902`) — that registration path has no current
  production caller. Practically closed. This also matters for the entry-only
  backstop in §1/item 2: that check reads `registered.trend_mechanism` (the
  G16-validated source), evaluated **before** `_patch_signal` runs
  (`horizon_engine.py:580` vs. `:592`) — so even a hypothetical override cannot be used
  to launder a `LIQUIDITY_STRESS` alpha's non-`FLAT` entry past the backstop.
- **`expected_half_life_seconds` override — reachable, unguarded.** This field is a
  plain `int`; any inline `signal:` body can write
  `expected_half_life_seconds=<literal>` on its `Signal(...)` return with **no** special
  import, because integer literals need no namespace binding. None of the 5 shipped
  alphas do this (verified by reading every `signal:` block in §4 — none set the field).
  But nothing prevents it, and no test locks "emitted `Signal.expected_half_life_seconds`
  equals the registered/declared value" as an *invariant* for the general case — only
  for the specific alphas exercised.

Where this value flows: `CrossSectionalRanker` reads `sig.expected_half_life_seconds`
directly off the bus-published `Signal` for `exp(-Δt/hl)` decay weighting
(`composition/cross_sectional.py:295,298,440,443,515,518`) whenever
`decay_weighting_enabled: true`. Both PORTFOLIO research specs default this **false**
(`pro_burst_revert_v1` line 89, `pro_kyle_benign_v1` line 100), so the composition-layer
consumer of the overridable field is dormant today. Separately, the hazard-exit
`hard_exit_age_seconds` default (`2 × expected_half_life_seconds`) is derived once at
**bootstrap** from `module.expected_half_life_seconds` — the loaded module/manifest
value, never the per-`Signal`-instance field — confirmed at `bootstrap.py:2152-2165`.
So the one safety-relevant consumer (hazard hard-exit age) is unaffected by this gap;
the one economically-relevant consumer (decay-weighted ranking) is currently switched
off. Recommend: drop the `raw.expected_half_life_seconds` ternary (make the engine
authoritative for this field, matching the spirit of "registered metadata is the trust
anchor") or add a load/registration-time assertion. S effort; **Inv-13** (provenance —
the emitted event's decay-relevant half-life should trace to the same G16-validated
source as its declared mechanism, not a value an alpha body can set unchecked).

---

## 4. Per-Alpha Audit

### `sig_kyle_drift_v1`

**Mechanism honesty:** Strong, re-verified. Declares `KYLE_INFO`; `evaluate()`
(`alphas/sig_kyle_drift_v1/sig_kyle_drift_v1.alpha.yaml:148-181`) reads
`kyle_lambda_60s_percentile`, `kyle_lambda_60s_zscore`, and `ofi_ewma` — a direct
Kyle-λ read gated by a percentile floor and OFI-sign agreement, consistent with Kyle
(1985), "Continuous Auctions and Insider Trading," *Econometrica* 53(6). Half-life
600s vs. 300s horizon sits at the G16 floor (ratio 0.50) — the alpha's own
`falsification_criteria` explicitly names "Realised half-life ... drifts outside [60,
1800]s" as a kill condition (line 33-35), so the alpha itself documents what would
disprove it, satisfying Inv-2.

**Cost reconciliation (independently recomputed):** `11.7 / (2.5+3.0+1.0) = 1.8000`,
exact match to the declared `margin_ratio: 1.8` (line 127) — 0.0% residual, well inside
the ±5% tolerance. Round-trip ≈ 13.0 bps; disclosed edge / round-trip = 0.90 — the YAML's
own comment (line 128-130) states this plainly. `cost_floor_bps` default 6.5 matches
`cost_total_bps` exactly (line 84-97) — the self-suppression floor is currently aligned
with disclosure, but nothing *enforces* that alignment (§1 item 6).

**Falsifiability:** Good — four concrete, checkable criteria (lines 27-42), including an
explicit spread-regime dead-man's switch ("spread z-score persistently > 1.0 ... gate
stays OFF"). Missing evidence, as in 06-20: a current OOS bucket-return report by λ̂
percentile and OFI sign — this is a data-run gap, not a code gap.

**Classification:** No implementation bug found this cycle; economic cost-survival
remains unproven by data (only by disclosure arithmetic).

### `sig_hawkes_burst_v1`

**Mechanism honesty:** Strong. Declares `HAWKES_SELF_EXCITE`; `evaluate()`
(`alphas/sig_hawkes_burst_v1/...yaml:152-184`) gates on `hawkes_intensity_zscore` and
`trade_through_rate`, sized/directed by `ofi_ewma` — consistent with Hawkes (1971),
"Spectra of Some Self-Exciting and Mutually Exciting Point Processes," *Biometrika*
58(1). Half-life exactly equals the 30s horizon (ratio 1.00). `hazard_exit.enabled: true`
with `hazard_score_threshold: 0.30` (lines 146-148) is the right control for a mechanism
whose edge collapses as intensity decays — decoupling the exit from waiting a full 30s
horizon boundary.

**Cost reconciliation:** `8.0 / (2.0+2.0+1.0) = 1.6000` — exact match to declared 1.6.
Round-trip ≈ 10.0 bps; disclosed-edge/round-trip = 0.80, the tightest of the five
production specs, which is the correct ordering given 30s is also the shortest horizon
(most exposed to latency and spread-widening shocks per unit of expected edge).

**Falsifiability:** Good — names intensity-half-life drift above 90s as a G16-relevant
kill condition and toxicity-probability breach as the hazard-exit trigger (lines 30-41).

**Classification:** No implementation bug; highest latency/stress sensitivity of the
five by construction (shortest horizon, tightest raw RT margin).

### `sig_inventory_revert_v1`

**Mechanism honesty:** Explicitly quarantined, and the quarantine is real (not just
documentation). `lifecycle_state: RESEARCH` (line 9) + the `notes:` block (lines 10-24)
records a specific negative forward-IC study: pooled Spearman ρ ≈ -0.007 across 6
sessions / 3 symbols, per-day sign instability, and the SHORT leg showing *positive*
forward returns in 5/6 sessions — directly contradicting the fade premise ("faster
replenishment marks the displaced side and we fade with LONG," lines 227-232). This is
the platform's own audit trail working as designed: the alpha's spec, its tests, and its
runtime lifecycle cap are all internally consistent about "do not trust this yet."

**Verified this cycle — the quarantine is mechanically enforced, not just documented:**
`test_research_lifecycle_cap_blocks_paper_promotion`
(`tests/alpha/test_sig_inventory_revert_v1.py:66-79`) constructs the real
`AlphaLifecycle` from the loaded manifest's `lifecycle_cap` and asserts
`promote_to_paper()` returns an error and the state stays `RESEARCH`. The cap check
itself lives in `AlphaLifecycle._lifecycle_promotion_errors`
(`src/feelies/alpha/lifecycle.py:297-309`): `lifecycle_cap == "RESEARCH"` blocks both
`PAPER` and `LIVE` targets unconditionally. `AlphaRegistry.register()` wires
`lifecycle_cap=manifest.lifecycle_cap` into every constructed `AlphaLifecycle`
(`src/feelies/alpha/registry.py`, confirmed in the current diff against 06-20 baseline)
— so this is live for any registration path with a clock attached, not just this unit
test. **This corrects the 06-20 audit's P1 backlog item** ("Add a promotion/lifecycle
test that quarantined SIGNAL alphas cannot be promoted") — the mechanism and its test
already existed at `HEAD` (the underlying `lifecycle_cap` machinery predates even the
06-14 audit per `git log --follow`). The only residual gap (§8, downgraded to P2): the
cap is a function of the YAML continuing to declare `lifecycle_state: RESEARCH` — a
one-line edit removes it with no automatic re-check against the recorded forward-IC
failure. That is a code-review/PR-process control, not a runtime one, which is
consistent with how every other YAML-driven safety declaration in this platform works.

**Cost reconciliation:** `8.8 / (2.5+2.0+1.0) = 1.6000` — exact match. Note the gate's
literal thresholds were refactored since 06-20 to reference declared `parameters:` by
name (`abs(quote_replenish_asymmetry_zscore) > asymmetry_z_threshold` instead of the
literal `2.0`, lines 172-186) — a pure hygiene fix; I confirmed the parameter defaults
(`asymmetry_z_threshold: 2.0`, `hazard_floor: 4.0`, `vol_taper_z_scale: 3.5`) exactly
match the literals they replaced, so this is behavior-preserving.

**Classification:** No engine bug; current empirical evidence correctly says do not
promote, and the platform's own machinery enforces that.

### `sig_moc_imbalance_v1`

**Mechanism honesty:** Honest about an L1 identifiability limit, unchanged from 06-20.
The hypothesis block is unusually direct: "`flow_direction_prior` is NOT derived from L1
NBBO — it is an exogenous, statically-configured field" from a reference calendar file
(lines 17-25). OFI (`ofi_ewma`) only *confirms* sign agreement
(`evaluate()` lines 185-191); it never derives direction. This is the correct way to
handle a genuinely exogenous edge source under an L1-only platform constraint: disclose
it, don't dress it up as a microstructure mechanism.

**Cost reconciliation:** `12.0 / (2.5+2.5+1.0) = 2.0000` — exact match, the best G12
margin and the best raw RT margin (1.00) of the five. The `min_seconds_to_close: 60`
guard plus the `cost_floor_bps` self-suppression (lines 94-107) mean the alpha
structurally refuses to trade in the terminal window where fill slippage is worst — a
sound design choice given the mechanism's known decay near auction close.

**Falsifiability:** Good, and unusually operative — the falsification criterion is
literally the thing that would kill the alpha's only edge source: "sign-agreement rate
between the calendar prior and realised forward-120s return drops below 0.55" (lines
41-47), not a generic DSR threshold.

**Classification:** No implementation bug; the exogenous-prior dependency is the
platform's one clearly-disclosed L1 identifiability limit among the five, and it's
disclosed, not hidden.

### `sig_benign_midcap_v1`

**Mechanism honesty:** Plausible L1 projection of `KYLE_INFO`, weaker than the direct
λ̂-based `sig_kyle_drift_v1` by construction. `evaluate()`
(`alphas/sig_benign_midcap_v1/...yaml:174-235`) sizes off `ofi_ewma_zscore`, confirmed
by same-sign `book_imbalance_mean` (a level-invariant Stoikov-style imbalance, not raw
micro-price z-scored against a ~$100 price level — the YAML's own comment at lines
182-188 explains why `micro_price_zscore` was rejected as a confirmation signal in a
prior pass). The `l1_signature_sensors` fingerprint is `micro_price` +
`book_imbalance` + `ofi_ewma` (lines 164-167), each a genuine dependency (subset of
`depends_on_sensors`), satisfying G16 rule 5/10.

**Cost reconciliation:** `9.0 / (2.0+2.0+1.0) = 1.8000` — exact match. Raw RT margin
0.90.

**Falsifiability:** Reasonable — the hypothesis explicitly separates "the tradeable
claim is the footprint itself, not the algorithm tag" (line 21), avoiding the common
overfitting trap of attributing edge to an unobservable parent-order identity. Sign
alignment, floor suppression, and cap tests are present
(`tests/alpha/test_sig_benign_midcap_v1.py`, spot-checked to confirm coverage of the
`imbalance_floor` epsilon-band logic added since the mechanism-fingerprint fix noted in
the YAML's own audit comment, lines 151-160).

**Classification:** No implementation bug; mechanism is an explicitly-labeled L1 proxy,
not overclaimed as the ground-truth Kyle λ.

### `paper_smoke_v1`

Unchanged from 06-20: a deliberate test fixture (no `trend_mechanism:` block, permissive
`on_condition: "True"`), excluded from alpha discovery by its underscore path segment,
loaded only by `configs/paper_smoke_rth.yaml` with strict trend enforcement off. Cost
arithmetic (`10.0/2.5=4.0`) reconciles trivially. Not a research alpha; correctly not
promotable through the normal discovery path.

---

## 5. Multi-Alpha Interaction

`EdgeWeightedArbitrator` (`src/feelies/alpha/arbitration.py:34-85`) is the standalone
(non-PORTFOLIO) conflict resolver: composite score = `edge_estimate_bps × strength`;
any `FLAT` among the candidates wins immediately and unconditionally over directional
signals — "FLAT is a constraint (exit), not a preference" (docstring, lines 41-45),
directly implementing Inv-11. Ties are broken deterministically by ascending
`strategy_id` (lines 71-72, 77-79) rather than relying on iteration order — I confirmed
this by reading the `min(..., key=lambda s: (-score, s.strategy_id))` construction
directly; it is order-independent by design, not by accident. Below `dead_zone_bps`
(default 0.5) the arbitrator returns `None` rather than acting on a weak, contested
signal (lines 82-83).

`aggregate_intents` (`src/feelies/alpha/aggregation.py:64-114`) is the exit-priority
two-bucket netter for order construction: exits are summed into bucket 1 and are
"never cancelled by opposing entries" (module docstring, lines 6-8); entries net into
bucket 2. `_to_signed_quantity` (lines 37-61) raises `ValueError` on any
unhandled `TradingIntent` rather than silently defaulting — a defensive exhaustiveness
guard consistent with Inv-11 (fail loud rather than silently mis-net).

**Net effect:** the standalone SIGNAL path picks one winner per symbol per tick rather
than stacking same-direction evidence from independent alphas — a deliberately
conservative choice. Economic *combination* of correlated or complementary mechanisms is
meant to happen through an explicit `layer: PORTFOLIO` spec, not incidental
simultaneous SIGNAL emissions.

Both shipped research PORTFOLIO specs exercise that path:

- `pro_burst_revert_v1` combines `HAWKES_SELF_EXCITE` + `INVENTORY`
  (`sig_hawkes_burst_v1` + `sig_inventory_revert_v1`), each capped at 0.6 gross share
  (`trend_mechanism.consumes`, lines 72-76). It inherits
  `sig_inventory_revert_v1`'s quarantine risk directly — the composition math is sound,
  but one of its two legs is a confirmed-non-viable signal by the platform's own
  forward-IC study.
- `pro_kyle_benign_v1` combines two `KYLE_INFO` legs (`sig_benign_midcap_v1` +
  `sig_kyle_drift_v1`) with a **permissive 1.0 single-family cap** (lines 84-87) — G16
  rule 8 requires the cap sum to reach ≥1.0 for full-book deployment to be structurally
  reachable, and with only one family declared, 1.0 is the minimum value that satisfies
  that rule, not evidence the two legs are diversifying. Both alphas read `ofi_ewma`;
  the YAML's own hypothesis (lines 25-36) argues their conditioning sets are "partially
  orthogonal" by gate tightness, but that argument is unverified by data.

Both remain explicitly `lifecycle_state: RESEARCH, decommissioned from production
discovery` — this audit did not find new evidence to change that status, and the
composition-layer internals (`CrossSectionalRanker`, factor neutralization, sector
matching) that would ultimately arbitrate these are owned by `audit_composition.md`, not
re-audited here beyond the `trend_mechanism.consumes` / decay-weighting touchpoints in
§3.6.

---

## 6. Cost & Stress Matrix

Every `margin_ratio` below was **independently recomputed** from the disclosed
`cost_arithmetic` components (not copied from YAML or a prior audit) using
`edge_bps / (half_spread_bps + impact_bps + fee_bps)`, matching
`compute_margin_ratio` (`src/feelies/alpha/cost_arithmetic.py:267-286`).

| Alpha | Edge | One-way cost | Recomputed margin | Declared margin | Residual | Round-trip cost | Raw RT margin | 1.5× stress RT margin |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `paper_smoke_v1` | 10.0 | 2.5 | 4.0000 | 4.0 | 0.0% | 5.0 | 2.00 | 1.33 |
| `sig_benign_midcap_v1` | 9.0 | 5.0 | 1.8000 | 1.8 | 0.0% | 10.0 | 0.90 | 0.60 |
| `sig_hawkes_burst_v1` | 8.0 | 5.0 | 1.6000 | 1.6 | 0.0% | 10.0 | 0.80 | 0.53 |
| `sig_inventory_revert_v1` | 8.8 | 5.5 | 1.6000 | 1.6 | 0.0% | 11.0 | 0.80 | 0.53 |
| `sig_kyle_drift_v1` | 11.7 | 6.5 | 1.8000 | 1.8 | 0.0% | 13.0 | 0.90 | 0.60 |
| `sig_moc_imbalance_v1` | 12.0 | 6.0 | 2.0000 | 2.0 | 0.0% | 12.0 | 1.00 | 0.67 |

**Every disclosure reconciles to 0.0% residual** — none of the six specs is lying about
its own arithmetic (well inside `cost_arithmetic.py`'s ±5% `MARGIN_RATIO_TOLERANCE`,
line 95). All six clear the `MIN_MARGIN_RATIO = 1.5` one-way floor (line 90), enforced at
load by `CostArithmetic.from_spec` (lines 168-264) — this is `alpha/cost_arithmetic.py`,
which has had **zero code changes** since 06-20 (confirmed via `git diff`), so this gate
is exactly as strong as previously audited.

**But**: on the disclosed numbers alone, no production alpha clears a **1.0× raw
round-trip** margin, let alone the Inv-12-mandated 1.5×. The 1.5×-stress column shows
every production alpha at 0.53–0.67 — well under 1.0. This is not a G12 implementation
bug (G12 validates one-way disclosure honesty, not round-trip survival — that
distinction is explicit in the module's own docstring, `cost_arithmetic.py:33-54`); it's
a disclosed, and disclosed-as-such, economic fact. Every production spec's own YAML
comment says so explicitly (e.g. `sig_hawkes_burst_v1` line 124: "does not clear the
1.5x round-trip Inv-12 bar").

**The runtime B4 gate is the actual Inv-12 enforcement point**, and it operates on
*live-computed* `Signal.edge_estimate_bps` (which is frequently below the disclosed
YAML peak — every alpha applies floors, caps, and decay-style haircuts inside
`evaluate()`) against a *live-modeled* round-trip cost, not the static disclosure:
`Orchestrator._signal_passes_edge_cost_gate` (`kernel/orchestrator.py:3146-3169`),
gated by `signal_min_edge_cost_ratio` and `signal_edge_cost_basis` in
`PlatformConfig`. I traced the actual configured values rather than assuming the code
default applies everywhere:

| Config | `signal_min_edge_cost_ratio` | `signal_edge_cost_basis` |
|---|---:|---|
| `platform.yaml` (reference) | **1.0** | `round_trip` |
| `configs/bt_multialpha.yaml` | 1.5 | — |
| `configs/bt_sig_{benign_midcap,hawkes_burst,inventory_revert,kyle_drift,moc_imbalance}.yaml` | 1.5 | — |
| `configs/paper_run.yaml` | 1.5 | — |
| `configs/paper_smoke_rth.yaml` | 1.5 | — |

`platform.yaml`'s `1.0` is **explicitly documented as intentional** at the point of
declaration (`platform.yaml:144-156`, "Audit P1-3: Inv-12 requires edge > 1.5× ROUND-TRIP
cost. This default (1.0) is only round-trip break-even; it is intentionally permissive
for the reference profile ... Leave reference at 1.0 only for research; raise to 1.5 for
any cost-realistic run"). Every config that actually resembles a real trading run already
overrides to 1.5, and that override is locked by test
(`tests/acceptance/test_backtest_app_config_keys.py:103,117`,
`test_sig_backtest_configs_load_with_single_alpha`). I verified this chain end-to-end
before concluding it was not a defect — it would have been an easy, plausible-looking P0
to over-claim without checking whether the *reference* file is actually load-bearing for
live/paper trading (it is not, by policy and by every operational config's override).

---

## 7. Test Gap Matrix

| Area | Current coverage | Gap | Priority |
|---|---|---|---|
| G12 arithmetic | Reconciliation, tolerance, non-negative costs, floor all covered (`tests/alpha/test_cost_arithmetic_gate.py:45-181`) | No test ties `cost_floor_bps` (per-alpha param) to `cost_arithmetic.cost_total_bps` — a config override can set the floor to 0 | P1 |
| G16 structural validation | Family, half-life, ratio, fingerprint, failure-signature, and **rule-7 stress-entry backstop** are all covered, including the dynamic-direction abstention case (`tests/alpha/test_gate_g16.py:533-560`); rule completeness itself is meta-tested (`tests/acceptance/test_g16_rule_completeness.py:107-173`) | None found this cycle — the 06-20 "residual G16 risk" for dynamic `LIQUIDITY_STRESS` direction is closed by the runtime backstop (§1 item 2), which **is** tested end-to-end (`tests/signals/test_horizon_signal_engine.py:1021-1043`) | — resolved |
| Engine warm/stale | Required-feature narrowing, stale-permits-close, stale-suppresses-entry all covered (`tests/signals/test_horizon_signal_engine.py:230,353,399`) | No test on the `mutate=False` interaction itself (i.e. that a *second*, clean snapshot after a blocked one correctly commits the transition) — behavior verified correct by direct trace + reproduction in this audit (§3.4/3.5), but not asserted by a dedicated unit test | P2 |
| Engine observability (ENG-2, new) | Entry-suppressed and clean-path gate-transition counters are covered (`tests/signals/test_horizon_engine_metrics.py:43-73`) | **No test covers the entry-blocked-at-first-admission scenario for the `gate.transition` counter** — this is precisely the gap that let the §3.5 double-count ship untested | P1 |
| Engine mechanism/half-life provenance | "Alpha wins" override is asserted as intended behavior for both fields (`tests/signals/test_horizon_signal_engine.py:876-919`) | No test asserts the *invariant* case — that a normal (non-overriding) alpha's emitted `expected_half_life_seconds` cannot silently diverge from the registered value; no test exercises the reachable-via-plain-int channel specifically | P1 |
| Typed SIGNAL parity output | JSONL provenance fields and arrival order covered (`tests/determinism/test_emit_signals_jsonl.py`) | Shape tests, not economic-edge tests | P2 |
| Determinism (empty baseline) | Level-2 hash locks zero-emission on the synthetic fixture for all 5 reference alphas (`tests/determinism/test_signal_replay.py`) | Confirmed still empty-stream-only for real alphas | P2 |
| Determinism (engine mechanics, non-empty) | **New since 06-20** — synthetic-probe non-empty replay locks sequence/ordering/provenance (`tests/determinism/test_signal_fires_replay.py`) | Still no *real reference alpha* non-empty economic replay on realistic NBBO | P2 |
| G2-G13 loader gates | Purity, no-clock, sensor-DAG, horizon, delegated-G12 all covered (`tests/alpha/test_layer_validator_g2_g13.py`) | Structural only, as designed | P2 |
| Per-alpha behavior | Emission/suppression/cap tests per alpha, including the promotion-cap test for the quarantined alpha (`tests/alpha/test_sig_inventory_revert_v1.py:66-79`, `tests/alpha/test_sig_benign_midcap_v1.py`) | Tests verify code behavior, not forward-return IC, slippage, or OOS profitability — data-run gap, not code gap | P1 |
| Promotion discipline for quarantined alpha | **Resolved this cycle** — see above; the 06-20 "missing" claim was incorrect at the time it was written or resolved immediately after | Residual: the cap is removable by a one-line YAML edit with no automatic evidence re-check (a PR-review-process control, consistent with every other YAML-driven safety declaration in the platform) | P2 |
| Inv-12 stress | Stress-factor and latency-doubling harness mechanics tested (`tests/acceptance/test_inv12_stress_gate.py`) | No per-alpha pass/fail matrix under actually-stressed spread/fee/impact/latency on real data | P1 |
| Reference-config B4 threshold | `platform.yaml` vs. per-strategy config override verified consistent and tested (`tests/acceptance/test_backtest_app_config_keys.py:103,117`) | None found — verified not a gap (§6) | — resolved |
| Multi-alpha crowding | Arbitration determinism and dead-zone tested (`tests/alpha/test_arbitration.py`); aggregation reversal/exit/entry bucket tests present (`tests/alpha/test_aggregation.py`) | `pro_kyle_benign_v1`'s two overlapping-OFI KYLE_INFO legs have no independence test | P2 |

---

## 8. Prioritized Backlog

### P0

None found this cycle. (06-20 also found none; this pass independently re-verified
purity, causality, ordering, and cost-gate wiring rather than assuming the prior
finding still held.)

### P1

| Item | Why | Inv | Effort |
|---|---|---|---|
| Fix ENG-2 `gate.transition{to=ON}` double-count on entry-blocked first admission | Corrupts the primary operator signal for regime-gate flapping, precisely during data-quality gaps (§3.5); one-line fix (branch on the committed post-call state, not the returned value) | Inv-13 | S |
| Make the engine authoritative for `Signal.expected_half_life_seconds` (drop or guard the alpha-wins ternary) | Reachable-by-plain-int channel with a live (if currently disabled) downstream consumer in composition decay-weighting; no test locks the non-override invariant (§3.6) | Inv-13 | S |
| Enforce `cost_floor_bps >= cost_arithmetic.cost_total_bps` at load, or otherwise pin it | Every production alpha's only self-suppression against sub-cost entries has a `min: 0.0` escape hatch a config override can exploit unnoticed | Inv-12 | S |
| Add per-alpha stressed-B4 survival reports on real data | Disclosed raw RT margins are 0.8–1.0 for every production alpha even before the 1.5× stress multiplier (§6); live survival depends entirely on B4 selectivity, unproven by data | Inv-12 | M |
| Add OOS IC / bucket-return reports for every RESEARCH SIGNAL alpha | Static contracts (G12/G16) cannot prove alpha; missing evidence is directional forward return net of realistic costs | Inv-1, Inv-2 | M |

### P2

| Item | Why | Effort |
|---|---|---|
| Add a unit test for the entry-blocked → clean-snapshot `mutate` handoff | Behavior verified correct by trace + reproduction in this audit, but not asserted by a dedicated test — regression risk if the `mutate` condition is ever refactored | S |
| Add duplicate-boundary `(alpha_id, symbol, boundary_index)` idempotence guard or metric | Engine has no defensive check; currently relies entirely on upstream not double-emitting | S |
| Add a purity property test (repeated identical call → bitwise-identical output, no mutation) | Purity is enforced by sandbox + AST scan, not a runtime property test, for the loaded alpha set | S |
| Add independence analysis for `pro_kyle_benign_v1`'s two OFI-overlapping KYLE_INFO legs | Both PORTFOLIO research specs are already decommissioned from discovery, so this is low urgency, but the 1.0 single-family cap is a structural minimum, not evidence of diversification | M |
| Real reference-alpha non-empty economic replay fixture | Engine-mechanics non-empty replay now exists via a synthetic probe (§3.3); a real alpha's replay on realistic multi-day data remains open | M |
| Document the `lifecycle_cap` bypass-by-YAML-edit as an explicit PR-review checklist item for RESEARCH-capped alphas | The runtime mechanism is sound (§4); the only gap is process, not code | S |

---

## 9. Appendix: Open Questions Needing Data Runs

- For `sig_kyle_drift_v1`: OOS forward returns by `kyle_lambda_60s_percentile`, OFI
  sign, and spread bucket after realistic queue/slippage assumptions?
- For `sig_benign_midcap_v1`: does `book_imbalance` confirmation add independent
  information after OFI, or is it mostly a noisy transform of the same pressure?
- For `sig_hawkes_burst_v1`: how much edge survives doubled latency and widened spread
  in burst regimes, especially when `trade_through_rate` is elevated?
- For `sig_inventory_revert_v1`: does a newer, by-leg (LONG vs. SHORT separately) sample
  reverse the recorded sign instability, or does the mechanism remain non-viable?
- For `sig_moc_imbalance_v1`: what is the isolated contribution of the calendar prior
  versus OFI confirmation, and is the prior reproducible from archived
  `event_calendar` inputs?
- Across all five production alphas: what fraction of candidate emissions survives
  runtime B4 under normal cost, 1.5× spread/fee/impact stress, and doubled latency —
  on real cached NBBO, not disclosed YAML arithmetic?
- **`gas_02_fast_ofi_momentum` (in flight, `docs/research/gas_02_fast_ofi_momentum.md`):**
  a candidate fast-horizon (~30s) `HAWKES_SELF_EXCITE`-adjacent momentum signal on
  `ofi_integrated`, with RankIC +0.10 (n≈810, single day) already measured but the
  binding Inv-12 cost gate (`edgeBps > 1.5× round_trip_cost_bps`) not yet evaluated on
  pooled multi-day data. The note pre-registers the most likely honest outcome ("real
  signal, too small to clear costs") and commits to authoring **no** new alpha unless the
  cost gate passes — worth tracking as the platform's current model of correct
  falsifiability-first research discipline for this layer.
- For `pro_kyle_benign_v1`: are the two `KYLE_INFO` legs independent after controlling
  for `ofi_ewma`, or should a stricter same-family cap apply if/when this spec is ever
  reconsidered for production discovery?
- Does the regime-gate sensor-cache fallback (`horizon_engine.py:726-758`) ever, in a
  live multi-symbol deployment, resolve to a reading from a later event-time than the
  snapshot it's gating for a *different* symbol's queue ordering? (Traced as safe for
  the single-symbol case in this audit; not stress-tested for cross-symbol bus
  interleaving.)

---

## Verification Run

All commands executed read-only from repo root at `HEAD=929e9fb6`
(`claude/signal-alpha-audit-ot00rv`); no production file was modified.

```
$ uv sync --all-extras
  (38 packages installed; environment was not present at session start)

$ uv run pytest tests/signals/test_horizon_signal_engine.py tests/alpha/test_gate_g16.py \
      tests/alpha/test_cost_arithmetic_gate.py -q
  116 passed, 1 warning (PYTHONHASHSEED unset — re-run below with it pinned)

$ PYTHONHASHSEED=0 uv run pytest tests/determinism/test_signal_replay.py \
      tests/acceptance/test_inv12_stress_gate.py -q
  15 passed

$ PYTHONHASHSEED=0 uv run pytest tests/alpha/ tests/signals/ -q
  785 passed

$ PYTHONHASHSEED=0 uv run pytest tests/acceptance/test_g16_rule_completeness.py \
      tests/acceptance/test_falsifiability_inv2.py tests/acceptance/test_strict_mode_reference_alphas.py \
      tests/acceptance/test_strict_mode_default_true.py tests/acceptance/test_reference_alpha_load_invariants.py \
      tests/acceptance/test_signal_fires_from_active_aggregator.py tests/determinism/test_emit_signals_jsonl.py \
      tests/alpha/test_discovered_alpha_specs_load.py tests/alpha/test_shipped_alpha_specs_load.py -q
  58 passed, 1 skipped

$ uv run mypy src/feelies/signals src/feelies/alpha/cost_arithmetic.py \
      src/feelies/alpha/layer_validator.py src/feelies/alpha/arbitration.py \
      src/feelies/alpha/aggregation.py src/feelies/alpha/signal_layer_module.py
  Success: no issues found in 9 source files
```

**Total: 974 passed, 1 skipped, 0 failed** across the SIGNAL-layer test scope touched by
this audit, plus a clean scoped `mypy --strict` run. The §3.5 ENG-2 double-count finding
was additionally confirmed by direct reproduction against the live engine using existing
test fixtures (not a new test file — script discarded, not committed, per the read-only
mandate).
