# Sensor audit — 2026-06-30 (prompt-pack validation pass)

Read-only re-audit of Layer-1 sensors + horizon aggregation, executed to validate
the new **Agent context (mandatory)** workflow in `docs/prompts/audit_sensor.md`.
Prior full audit: [`sensor_audit_2026-06-19.md`](sensor_audit_2026-06-19.md).

**Agent context loaded (in order):**

1. `.cursor/rules/platform-invariants.mdc` — Inv-5, 6, 10, 11
2. `.cursor/rules/karpathy-guidelines.mdc`
3. `.cursor/skills/README.md`
4. `.cursor/skills/feature-engine/SKILL.md` (**owner**)
5. `.cursor/skills/microstructure-alpha/SKILL.md`

**Not shipped cross-check:** `feature-engine` marks sensor checkpoint persistence as
**Not shipped** — absence of a feature-event store is **not** a P0 (confirmed).

---

## Executive summary

1. **Prompt pack validation:** Agent context + Working method Not shipped bullet
   produced a structured pass without false P0s on design targets (checkpoint).
2. **Tests green:** `tests/sensors/` → 199 passed, 1 skipped; determinism replays → 4 passed.
3. **Inv-5 (replay):** Sensor + snapshot parity hashes still pass; no new nondeterminism observed.
4. **P0 delta vs 2026-06-19:** `boundary_ts_ns` now carried on `HorizonTick` and
   `HorizonFeatureSnapshot` (ENG-1) — nominal grid anchor is explicit; `timestamp_ns`
   remains trigger-time (causal, documented in `core/events.py:684-686`).
5. **P0 open — version-blind dispatch:** Multi-version sensor readings still warn-only;
   feature state keyed without `sensor_version` (`aggregator.py:304-314`, `379-400`).
6. **P0 open — throttle contract latent:** All active `sensor_specs` have
   `throttled_ms: null` (`platform.yaml`); `SensorSpec` stateful-throttle rule untested live.
7. **P1 unchanged:** Active sensors remain heuristic L1 proxies; aggregation is
   per-feature with no cross-sensor fusion (`aggregator.py:57-70` docstring region).
8. **P1 unchanged:** Offline IC harness (`scripts/sensor_feature_ic.py`) still covers
   four families only — extend before promoting new mechanism fingerprints.
9. **Inv-6 (causality):** `HorizonAggregator._build_snapshot` uses `asof_ns` from
   tick boundary for stale checks; warm-reading clock uses `max(prev, ts_ns)` guard
   (`aggregator.py:368-372`, `581-591`).
10. **Inv-11 (fail-safe):** Non-finite feature values demoted to cold (`aggregator.py:518-537`).
11. **Inv-10:** No wall-clock reads found in hot sensor/aggregator path (spot-check).
12. **Opportunity:** Consumers should prefer `boundary_ts_ns` over `timestamp_ns` for
    horizon-aligned IC / forward-return pairing after sparse tapes.
13. **Opportunity:** Re-run full per-sensor economic audit when adding a 16th active sensor.
14. **Guardrails:** `tests/docs/test_audit_prompt_structure.py` now enforces Agent
    context on all 18 audit prompts.

---

## Sensor inventory

15 active sensors in `platform.yaml` `sensor_specs:` (flat DAG — no live
`input_sensor_ids` edges). Same set as 2026-06-19 audit; dormant modules remain in
`sensors/impl/` (`vpin_50bucket`, `snr_drift_diffusion`, `structural_break_score`).

| sensor_id | version (YAML) | mechanism family (G16) |
|-----------|----------------|------------------------|
| spread_z_30d | 1.1.0 | LIQUIDITY_STRESS |
| quote_replenish_asymmetry | 1.1.0 | INVENTORY |
| quote_hazard_rate | 1.0.0 | INVENTORY |
| ofi_ewma | 1.1.0 | KYLE_INFO |
| ofi_raw | 1.0.0 | KYLE_INFO |
| micro_price | 1.1.0 | KYLE_INFO |
| book_imbalance | 1.0.0 | KYLE_INFO |
| kyle_lambda_60s | 2.0.0 | KYLE_INFO |
| trade_through_rate | 1.1.0 | KYLE_INFO |
| hawkes_intensity | 1.2.0 | HAWKES_SELF_EXCITE |
| scheduled_flow_window | 1.2.0 | SCHEDULED_FLOW |
| realized_vol_30s | 1.3.0 | LIQUIDITY_STRESS |
| inventory_pressure | 1.0.0 | INVENTORY |
| liquidity_stress_score | 1.0.0 | LIQUIDITY_STRESS |
| quote_flicker_rate | 1.0.0 | INVENTORY |

---

## Prior P0 reconciliation (2026-06-19 → today)

| ID | Finding | Status | Evidence |
|----|---------|--------|----------|
| P0-1 | Snapshot `timestamp_ns` ≠ nominal boundary | **Partially remediated** | `boundary_ts_ns` on tick + snapshot (`horizon_scheduler.py:304-323`, `aggregator.py:569`; `events.py:684-686`); `timestamp_ns` still trigger-time |
| P0-2 | Version-blind feature dispatch | **Open** | Warning-only multi-version path (`aggregator.py:379-400`); audit comment at `304-314` |
| P0-3 | Throttle/stateful contract untested | **Open** | All `throttled_ms: null` in `platform.yaml`; spec contract in `sensors/spec.py` |
| N/A | Checkpoint not feature store | **Not a defect** | **Not shipped** in feature-engine skill — correctly excluded from P0 |

---

## Horizon aggregation audit (spot-check)

- **Policy:** Per-feature reducers on `SensorReading` stream; no cross-feature fusion.
- **Determinism:** Features and symbols iterated in sorted construction order
  (`_features_sorted`, `_symbols_sorted`).
- **Stale/warm:** Per-feature flags; cold features omitted from `values` (not zero-filled).
- **Provenance:** `feature_versions` populated per feature (Inv-13).
- **Grid anchor:** Prefer `boundary_ts_ns` for horizon math; document consumer contract in alpha YAML comments where forward returns are paired.

---

## Test gap matrix (unchanged highlights)

| Invariant | Coverage | Gap |
|-----------|----------|-----|
| Inv-5 replay | L1 sensor + L3 snapshot hashes | — |
| Multi-version sensors | Warning log only | Need fail-fast or version-keyed feature ids |
| Throttled accumulators | No active YAML | Registry test when throttle enabled |
| Sensor IC by regime | Partial script coverage | Extend `sensor_feature_ic.py` |
| ENG-1 boundary anchor | Field present | Consumer tests using `boundary_ts_ns` |

---

## Prioritized backlog

| Tier | Item | Effort | Inv |
|------|------|--------|-----|
| P0 | Fail-fast or version-keyed features when two sensor versions active | M | Inv-5, Inv-13 |
| P0 | Acceptance test for throttled + stateful `SensorSpec` before enabling throttle in YAML | S | Inv-5 |
| P1 | Document alpha consumer contract: use `boundary_ts_ns` for horizon pairing | S | Inv-6 |
| P1 | Extend sensor IC harness to all 15 active sensors + regime buckets | M | Inv-2, Inv-3 |
| P2 | Full per-sensor literature alignment review (defer to next scheduled audit) | L | Inv-1 |

---

## Appendix

- **Verification commands run:**
  - `uv run pytest tests/sensors/ -q` → 199 passed, 1 skipped
  - `uv run pytest tests/determinism/test_sensor_reading_replay.py tests/determinism/test_horizon_feature_snapshot_replay.py -q` → 4 passed
- **Prompt structure guard:** `uv run pytest tests/docs/test_audit_prompt_structure.py -q` → 5 passed
- **Open data question:** RankIC by mechanism family on APP/2026-03-26 disk cache — methodology only; no code run in this pass.
