# Feelies Alpha Audit

Institutional-style adversarial review of every **active** alpha under `alphas/` (templates and underscore-prefixed path segments excluded by discovery). This document is evidence-backed from repository sources and executed tests; it does **not** assert profitability.

## Executive Summary

| Field | Value |
|-------|-------|
| **Audit timestamp (UTC)** | 2026-05-10T10:07:04Z |
| **Git commit** | `56057629c68abd73c378467afb731901e6539bea` |
| **Branch** | `cursor/alpha-institutional-audit-4f52` |
| **Alpha YAML files found** | 10 |
| **Active alpha specs** | 8 (`_template/` × 2 excluded) |
| **Excluded (templates)** | 2 |
| **YAML loader successes** | 8 / 8 (`AlphaLoader`, regime `hmm_3state_fractional`) |
| **YAML loader failures** | 0 |
| **Alphas with audit status PASS** | 0 |
| **Alphas with audit status WARN** | 7 |
| **Alphas with audit status FAIL** | 1 |
| **Decisions: KILL** | 1 (`pofi_hawkes_burst_v1`) |
| **Decisions: RESEARCH_MORE** | 6 |
| **Decisions: PASS_STRUCTURAL_ONLY** | 3 (PORTFOLIO references) |
| **Decisions: PAPER_TRADE_CANDIDATE** | 0 |
| **Decisions: DEPLOY_SMALL_CANDIDATE** | 0 |

**Top critical risks**

1. **BLOCKER — Hawkes tuple vs rolling z-score wiring:** `hawkes_intensity` emits a tuple; `RollingZscoreFeature` ignores tuples → `hawkes_intensity_zscore` does not populate from real readings (`tests/features/test_rolling_zscore_skips_tuple_sensor_values.py`).
2. **HIGH — Reference `platform.yaml` incomplete for shipped SIGNAL set:** No `scheduled_flow_window` sensor spec; explicit `alpha_specs` lists only `pofi_benign_midcap_v1` — `pofi_moc_imbalance_v1` cannot boot on stock root config without operator edits.
3. **HIGH — Mechanism/signal mismatch on benign Kyle alpha:** Hypothesis/`trend_mechanism` cite micro-price / Kyle footprint; `evaluate()` uses only `ofi_ewma_zscore`.
4. **HIGH — PORTFOLIO risk budgets:** Reference cross-sectional alphas use very large position/gross caps unsuitable for personal-tier deployment without platform overrides.
5. **MEDIUM — Trade signing:** `kyle_lambda_60s`, `hawkes_intensity`, and `trade_through_rate` rely on tick-rule or NBBO-at-trade proxies — not aggressor labels.

**Machine-readable twin:** `docs/audits/alpha_audit_findings.json`

---

## Critical Findings (BLOCKER / HIGH first)

| Severity | Scope | Finding | Evidence |
|----------|-------|---------|----------|
| **BLOCKER** | `pofi_hawkes_burst_v1` + bootstrap | Tuple-valued `hawkes_intensity` readings are skipped by `RollingZscoreFeature.observe`, so `hawkes_intensity_zscore` cannot warm from the sensor pipeline. | `src/feelies/bootstrap.py` `_horizon_features_for`; `src/feelies/features/impl/rolling_stats.py`; `tests/features/test_rolling_zscore_skips_tuple_sensor_values.py` |
| **HIGH** | `pofi_xsect_mixed_mechanism_v1` | Depends on `pofi_hawkes_burst_v1`; upstream feeder structurally broken until Hawkes wiring fixed. | `depends_on_signals` in YAML |
| **HIGH** | Operator bootstrap | Repo `platform.yaml` lacks `scheduled_flow_window` registration; MOC alpha requires calendar injection per `bootstrap.py`. | `platform.yaml`; `src/feelies/bootstrap.py` |
| **HIGH** | `pofi_benign_midcap_v1` | Declared sensors/mechanism fingerprints do not match signal state (`micro_price` unused; `kyle_lambda_60s` in fingerprint but not in `depends_on_sensors`). | Alpha YAML |
| **HIGH** | PORTFOLIO alphas | `max_position_per_symbol: 5000`, `max_gross_exposure_pct: 50.0` — unsafe defaults for personal capital without global caps. | Alpha YAML |

---

## Repository inspection (audit prerequisites)

**Reviewed for this audit:** `AGENTS.md`, `README.md`, `pyproject.toml`, `platform.yaml`, `alphas/SCHEMA.md`, `alphas/_template/*`, `src/feelies/alpha/{discovery,loader,validation,layer_validator,registry,promotion_evidence}.py` (spot-checked), `src/feelies/bootstrap.py`, `src/feelies/signals/horizon_engine.py`, `src/feelies/features/impl/{sensor_passthrough,rolling_stats}.py`, sensor implementations under `src/feelies/sensors/impl/`, `scripts/run_backtest.py` (existence), test suites under `tests/alpha`, `tests/sensors`, `tests/integration`, workspace rules `.cursor/rules/platform-invariants.mdc`.

**Discovery rules:** `discover_alpha_specs` returns `*.alpha.yaml` at directory root and one level deep, **excluding** any path component starting with `_` (so `_template/` is excluded). Nested example: both `pofi_xsect_v1/pofi_xsect_v1.alpha.yaml` and `pofi_xsect_v1/pofi_xsect_v1.with_decay.alpha.yaml` are active.

---

## Alpha Inventory

| Alpha ID | File | Layer | Schema | Horizon | Mechanism Family | Sensors | Regime Gate | Cost Margin | Risk Budget | Load Status | Audit Status | Decision |
|----------|------|-------|--------|---------|------------------|---------|-------------|-------------|-------------|-------------|--------------|----------|
| pofi_benign_midcap_v1 | `alphas/pofi_benign_midcap_v1/pofi_benign_midcap_v1.alpha.yaml` | SIGNAL | 1.1 | 120 | KYLE_INFO | ofi_ewma, micro_price, spread_z_30d | HMM + spread_z | 1.8 | conservative defaults | OK | WARN | RESEARCH_MORE |
| pofi_inventory_revert_v1 | `alphas/pofi_inventory_revert_v1/pofi_inventory_revert_v1.alpha.yaml` | SIGNAL | 1.1 | 30 | INVENTORY | quote_replenish_asymmetry, spread_z_30d, quote_hazard_rate | HMM + asym/spread | 1.6 | conservative | OK | WARN | RESEARCH_MORE |
| pofi_kyle_drift_v1 | `alphas/pofi_kyle_drift_v1/pofi_kyle_drift_v1.alpha.yaml` | SIGNAL | 1.1 | 300 | KYLE_INFO | kyle_lambda_60s, ofi_ewma, micro_price, spread_z_30d | HMM + spread | 1.8 | moderate | OK | WARN | RESEARCH_MORE |
| pofi_hawkes_burst_v1 | `alphas/pofi_hawkes_burst_v1/pofi_hawkes_burst_v1.alpha.yaml` | SIGNAL | 1.1 | 30 | HAWKES_SELF_EXCITE | hawkes_intensity, trade_through_rate, ofi_ewma, spread_z_30d | HMM + spread | 1.6 | tighter caps | OK | **FAIL** | **KILL** |
| pofi_moc_imbalance_v1 | `alphas/pofi_moc_imbalance_v1/pofi_moc_imbalance_v1.alpha.yaml` | SIGNAL | 1.1 | 120 | SCHEDULED_FLOW | scheduled_flow_window, ofi_ewma | calendar-driven (no HMM posteriors in on_condition) | 2.0 | moderate | OK | WARN | RESEARCH_MORE |
| pofi_xsect_v1 | `alphas/pofi_xsect_v1/pofi_xsect_v1.alpha.yaml` | PORTFOLIO | 1.1 | 300 | consumes KYLE + INVENTORY | — | N/A (no regime_gate) | 3.43 | **very loose** | OK | WARN | PASS_STRUCTURAL_ONLY |
| pofi_xsect_v1_with_decay | `alphas/pofi_xsect_v1/pofi_xsect_v1.with_decay.alpha.yaml` | PORTFOLIO | 1.1 | 300 | consumes KYLE + INVENTORY | — | N/A | 3.43 | **very loose** | OK | WARN | PASS_STRUCTURAL_ONLY |
| pofi_xsect_mixed_mechanism_v1 | `alphas/pofi_xsect_mixed_mechanism_v1/pofi_xsect_mixed_mechanism_v1.alpha.yaml` | PORTFOLIO | 1.1 | 300 | consumes KYLE + INVENTORY + HAWKES | — | N/A | 4.0 | **very loose** | OK | WARN | PASS_STRUCTURAL_ONLY |

---

## Sensor and Feature Mathematical Rigor

### Sensor Coverage Matrix

| Sensor / Feature | Used By Alphas | Formula Documented | Causal | Unit Safe | Numerically Stable | Microstructure Valid | Tested | Status |
|------------------|----------------|-------------------|--------|-----------|-------------------|---------------------|--------|--------|
| ofi_ewma | benign, kyle, hawkes, moc | Yes (docstring) | Yes | Yes | Yes | Plausible L1 OFI | Yes | PASS |
| micro_price | benign, kyle | Yes | Yes | Yes | Yes | Proxy only | Yes | PASS |
| spread_z_30d | benign, inventory, kyle, hawkes | Yes | Yes | Yes | Yes (min_std) | Quote-count window | Yes | PASS |
| quote_replenish_asymmetry | inventory | Yes | Yes | Mixed | Yes | Thin L1 proxy | Yes | WARN |
| quote_hazard_rate | inventory | Yes | Yes | Interpretation risk | Yes | Intensity not probability | Yes | WARN |
| kyle_lambda_60s | kyle | Yes | Yes | Clarify units | Low-n fragile | Tick-rule volume | Yes | WARN |
| trade_through_rate | hawkes | Yes | Yes | Yes | Yes | NBBO/trade ordering | Yes | WARN |
| hawkes_intensity | hawkes | Yes | Yes | Tuple semantics | Branching ratio metadata | Tick-rule | Yes | **FAIL** (wiring) |
| scheduled_flow_window | moc | Yes | Yes | Yes | Yes | Calendar-driven | Yes | PASS (config caveat) |

### Per-Sensor Mathematical Findings (abbrev.)

#### `ofi_ewma`

- **Implementation:** `src/feelies/sensors/impl/ofi_ewma.py`
- **Formula:** Cont–Kukanov–Stoikov-style discrete OFI + EWMA (documented inline).
- **Causality:** Event-time on NBBO stream only.
- **Numerical stability:** Sliding-window warm-up avoids perpetual warm after gaps.
- **Tests:** `tests/sensors/test_ofi_ewma.py`

#### `hawkes_intensity` (**FAIL overall — platform wiring**)

- **Implementation:** `src/feelies/sensors/impl/hawkes_intensity.py` — tuple `(λ_buy, λ_sell, intensity_ratio, branching_ratio_est)`.
- **Failure mode:** `RollingZscoreFeature` drops tuple readings → **no z-score history** for default horizon feature wiring.
- **Tests:** Unit tests cover sensor recursion; **they do not** close L1→L2→signal path for z-score.

*(Additional sensor write-ups are inlined in `alpha_audit_findings.json`.)*

### Alpha-to-Sensor Coherence Matrix

| Alpha | Declared Mechanism | Required Sensor Evidence | Actual Sensor Evidence | Missing / Weak | Coherence |
|-------|-------------------|--------------------------|-------------------------|----------------|-----------|
| pofi_benign_midcap_v1 | KYLE_INFO | Impact / pressure footprint | OFI z-score + spread gate; micro_price unused | Lambda/micro-price absent from decision | PARTIALLY_COHERENT |
| pofi_inventory_revert_v1 | INVENTORY | Replenishment asymmetry, stress | Asymmetry z + hazard + spread | Hazard scale ad hoc | COHERENT |
| pofi_kyle_drift_v1 | KYLE_INFO | λ̂ + flow sign | λ percentile/z + raw OFI magnitude | micro_price unused | PARTIALLY_COHERENT |
| pofi_hawkes_burst_v1 | HAWKES_SELF_EXCITE | Intensity burst + aggression | Intended: Hawkes z + TTR + OFI | **Hawkes z non-functional in pipeline** | MECHANISM_UNSUPPORTED |
| pofi_moc_imbalance_v1 | SCHEDULED_FLOW | Calendar window + flow agreement | scheduled_flow tuple features + OFI | Calendar provenance risk | COHERENT |

---

## Per-Alpha Findings

### `pofi_benign_midcap_v1`

#### Summary

- **File:** `alphas/pofi_benign_midcap_v1/pofi_benign_midcap_v1.alpha.yaml`
- **Layer / schema / horizon:** SIGNAL / 1.1 / 120s
- **Mechanism family:** KYLE_INFO (`expected_half_life_seconds`: 120)
- **Hypothesis (actor):** Informed-flow footprint on L1 (OFI + micro-price tilt) in benign regime.
- **Falsification:** Forward-return correlation, DSR, structural regime shifts (documented — not wired to CI).
- **Load status:** OK
- **Score (heuristic 0–100):** ~58
- **Decision:** RESEARCH_MORE

#### Findings table

| Severity | Category | Status | Finding | Evidence | Recommended Action |
|----------|----------|--------|---------|----------|-------------------|
| HIGH | coherence | WARN | Signal uses only `ofi_ewma_zscore`; `micro_price` unused; fingerprint lists `kyle_lambda_60s` not in `depends_on_sensors`. | YAML | Align narrative, sensors, and evaluate(). |
| MEDIUM | promotion | WARN | Falsification uses forward labels — OK ethically if offline, but no automation. | YAML bullets | Map to measurable replay metrics. |
| LOW | cost | PASS | margin_ratio ≥ 1.5 | `cost_arithmetic` | — |

#### Kill / Freeze / Research / Promote Notes

- **Kill if:** N/A at structural level (loads cleanly).
- **Research more if:** Hypothesis-signal mismatch unresolved; no OOS cost-survival evidence supplied.
- **Paper-trade only if:** After sensor-signal coherence fixed and passive-fill stress tested at horizon 120s.
- **Small deployment only if:** Not supported by this audit (no evidence bundle).

---

### `pofi_inventory_revert_v1`

- **Decision:** RESEARCH_MORE · **Score:** ~62
- **Key issues:** Gate hardcodes z threshold vs parameterised signal threshold; hazard rate is an intensity, not a probability — `hazard_floor` calibration is under-specified.

---

### `pofi_kyle_drift_v1`

- **Decision:** RESEARCH_MORE · **Score:** ~60
- **Key issues:** `micro_price` unused; platform `min_samples: 5` for λ is statistically noisy; tick-rule signing.

---

### `pofi_hawkes_burst_v1`

- **Decision:** **KILL** · **Score:** ~22 · **Status:** FAIL
- **Kill if:** Immediate — primary feature `hawkes_intensity_zscore` cannot be produced from shipped wiring.
- **Evidence:** `tests/features/test_rolling_zscore_skips_tuple_sensor_values.py`; existing alpha tests inject z-score manually (`tests/alpha/test_pofi_hawkes_burst_v1.py`).

---

### `pofi_moc_imbalance_v1`

- **Decision:** RESEARCH_MORE · **Score:** ~48
- **Key issues:** Requires `scheduled_flow_window` spec + `event_calendar_path` — absent from repo-root `platform.yaml`; hypothesis depends on calendar prior quality.

---

### `pofi_xsect_v1` / `pofi_xsect_v1_with_decay` / `pofi_xsect_mixed_mechanism_v1`

- **Decision:** PASS_STRUCTURAL_ONLY · **Scores:** ~52 / ~52 / ~45
- **PORTFOLIO notes:** `factor_neutralization: true`; upstream horizons 300s match for kyle; inventory feeder at 30s horizon vs portfolio 300s is **allowed** by design (fan-in per boundary) but dilutes synchronicity — research topic.
- **Mixed mechanism portfolio:** BLOCKER dependency on broken Hawkes feeder until fixed.

---

## Cross-Alpha Findings

- **Sensor concentration:** `spread_z_30d` + `ofi_ewma` dominate — shared vulnerability to spread spikes / quote flicker.
- **Horizon clustering:** Multiple alphas at 30s / 120s / 300s — diversify regime tests.
- **Cost margins:** Declared margins pass G12 floors; **economic survival unproven** (no backtest evidence in scope).

---

## Backtest / Pipeline Compatibility

| Path element | Status | Notes |
|--------------|--------|-------|
| YAML → `AlphaLoader` | PASS | All 8 active specs |
| Repo `platform.yaml` → `_load_alphas` | WARN | Only explicit benign alpha; not full `alphas/` tree |
| Sensors for MOC | FAIL vs stock YAML | Add `scheduled_flow_window` spec + calendar |
| Hawkes → aggregator → signal | **FAIL** | Tuple/z-score wiring |
| PORTFOLIO composition | PASS structural | See `tests/integration/test_xsect_v1_e2e.py`, `test_mixed_mechanism_e2e.py` |

`scripts/run_backtest.py` exists; **no historical data** was mounted for this audit — **no claim** of executed profitable backtests.

---

## Test Coverage Assessment

| Area | Tests found | Result (this audit) |
|------|-------------|---------------------|
| Alpha YAML load / metadata | `tests/alpha/test_pofi_*.py` | PASS |
| Discovery load-all | `tests/alpha/test_discovered_alpha_specs_load.py` (**added**) | PASS |
| Sensors math / replay vectors | `tests/sensors/test_*.py` | PASS |
| Hawkes tuple vs rolling z-score | `tests/features/test_rolling_zscore_skips_tuple_sensor_values.py` (**added**) | PASS (documents defect) |
| Full suite | Not run (~2095 tests) | **Deferred** — targeted `tests/alpha` (583 passed) + `tests/sensors` (139 passed, 1 skipped) |

Known from `AGENTS.md`: two acceptance tests on `main` may fail due to baseline alpha / strict-mode expectation drift — **not re-run** as part of this audit slice.

---

## Recommended Action Plan

| Priority | Action |
|----------|--------|
| **P0** | Fix Hawkes horizon feature wiring so a scalar series feeds rolling z-score (or change sensor contract — coordinated change). |
| **P0** | Provide canonical `platform.yaml` fragment registering `scheduled_flow_window` + calendar path for MOC alpha. |
| **P1** | Reconcile `pofi_benign_midcap_v1` sensors with evaluate(); align `depends_on_sensors` with `l1_signature_sensors` intent. |
| **P1** | Downscale PORTFOLIO reference `risk_budget` defaults or document explicit “institutional reference only”. |
| **P2** | Quantitative falsification hooks for PORTFOLIO symbolic criteria. |

---

## Final Alpha Decision Table

| Alpha | Score | Status | Decision | Main Reason | Next Action |
|-------|------:|--------|----------|-------------|-------------|
| pofi_benign_midcap_v1 | 58 | WARN | RESEARCH_MORE | Mechanism/signal sensor mismatch | Align evaluate + sensors |
| pofi_inventory_revert_v1 | 62 | WARN | RESEARCH_MORE | Hazard calibration + gate/param coupling | Calibrate / unify thresholds |
| pofi_kyle_drift_v1 | 60 | WARN | RESEARCH_MORE | Low-n λ; unused micro_price | Research + config hygiene |
| pofi_hawkes_burst_v1 | 22 | FAIL | **KILL** | Tuple sensor incompatible with rolling z-score wiring | Fix bootstrap/features |
| pofi_moc_imbalance_v1 | 48 | WARN | RESEARCH_MORE | Missing sensor/calendar in stock platform YAML | Operator config |
| pofi_xsect_v1 | 52 | WARN | PASS_STRUCTURAL_ONLY | No performance evidence; loose risk | Evidence + risk overrides |
| pofi_xsect_v1_with_decay | 52 | WARN | PASS_STRUCTURAL_ONLY | Same | Same |
| pofi_xsect_mixed_mechanism_v1 | 45 | WARN | PASS_STRUCTURAL_ONLY | Depends on broken Hawkes feeder | Fix upstream |

---

## Sensor Math Risk Table (summary)

| Sensor | Formula / causal | Primary risk | Audit grade |
|--------|-------------------|--------------|-------------|
| OFI EWMA | Documented discrete OFI | Quote flicker | OK |
| Micro-price | Stoikov formula | Not executable price | OK |
| Spread z-score | Welford window | Misnamed “30d” (quote count) | OK |
| Kyle λ | OLS slope streaming | Tick rule; low n | Caution |
| Hawkes λ tuple | Self-exciting decay | **Feature wiring broken** | **Broken** |
| Trade-through | NBBO @ trade | SIP ordering | Caution |
| Scheduled flow | Calendar tuple | External calendar dependency | OK |

---

## Known Limitations

- No live/paper PnL, no CPCV/DSR tables, and no data-backed backtest runs were executed in this audit environment.
- Mandatory **KILL** on `pofi_hawkes_burst_v1` is **structural / wiring**, not a claim that Hawkes math is wrong in isolation.
- Full `pytest` suite was not executed end-to-end; subset results are recorded above.
