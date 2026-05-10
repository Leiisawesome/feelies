# Feelies Alpha Audit

**Repository:** [Leiisawesome/feelies](https://github.com/Leiisawesome/feelies)  
**Scope:** `alphas/` (active specs discovered by `discover_alpha_specs`; `_template/` excluded by underscore rule)  
**Audit dates:** Pass 1 — 2026-05-10 (UTC); **Pass 2 (this revision)** — 2026-05-10 (UTC)  
**Loader verification:** `AlphaLoader(enforce_trend_mechanism=False|True)` loads all eight shipped specs without error (`tests/alpha/test_shipped_alpha_specs_load.py`).

This audit is **not** a performance guarantee. No walk-forward Sharpe, live-slippage, or fill-model evidence was evaluated beyond tracing platform wiring and running a focused pytest subset.

### Pass 1 remediation (implemented before pass 2)

Code and YAML changes that motivated the second pass:

- **BLOCKER — PORTFOLIO vs feeder horizons:** `UniverseSynchronizer` unions portfolio and feeder horizons; cross-horizon feeders use latest `timestamp_ns ≤ barrier`; `CrossSectionalContext.signals_by_strategy_by_symbol`; bootstrap `signal_horizons` / `upstream_strategy_ids`; `CrossSectionalRanker` multi-feeder aggregation when `feeder_strategy_ids` is set.
- **Benign / inventory / mixed / platform.yaml:** Hypothesis + G16 fingerprint updates; inventory margin and falsification band; `HAWKES_SELF_EXCITE` spelling; extra `sensor_specs` in `platform.yaml`.

### Pass 2 verification

- Re-ran loader discovery for all eight specs (strict + loose).
- Confirmed synchronizer cross-horizon fan-in via `tests/composition/test_synchronizer.py::test_fan_in_cross_horizon_feeders_into_portfolio_context` and PORTFOLIO integration tests (`test_xsect_v1_e2e`, `test_mixed_mechanism_e2e`).
- Rescored alphas in `alpha_audit_findings.json` (BLOCKER cleared; residual WARNs documented).

---

## Executive Summary

| Metric | Value (pass 2) |
|--------|---------------:|
| `.alpha.yaml` files found (active) | 8 |
| Template / underscore-dir specs (excluded from discovery) | 2 |
| Loaded successfully (strict + loose) | 8 |
| Failed load | 0 |
| Audit status **PASS** | 0 |
| Audit status **WARN** | 8 |
| Audit status **FAIL** | 0 |
| Decision **KILL** | 0 |
| Decision **RESEARCH_MORE** | 8 |
| Decision **PAPER_TRADE_CANDIDATE** | 0 |
| Decision **DEPLOY_SMALL_CANDIDATE** | 0 |
| Decision **PASS_STRUCTURAL_ONLY** (SIGNAL subset) | 5 |

**Interpretation:** Every shipped alpha remains **RESEARCH_MORE** — no profitability or live execution audit. Pass 1’s **composition-feed BLOCKER** is **closed**: **30s** feeders **do** reach **300s** `CrossSectionalContext` through the updated synchronizer and bootstrap wiring. Residual issues are **fixture-scale PORTFOLIO risk**, **operator bundle documentation**, **benign fingerprint vs `evaluate()` sensor usage**, and **AGENTS.md acceptance drift** (unchanged).

---

## Critical Findings

Pass 2 — residual BLOCKER/HIGH list (pass 1 BLOCKER/HIGH composition-feed and inventory margin items are **resolved**).

| Severity | Category | Finding |
|----------|----------|---------|
| **HIGH** | risk_budget | Reference PORTFOLIO alphas (`pofi_xsect_*`) retain **fixture-scale** gross exposure and capital allocation — unsafe verbatim for capital-bearing configs. |
| **MEDIUM** | dependency_validity | `pofi_benign_midcap_v1`: `trend_mechanism.l1_signature_sensors` lists **`kyle_lambda_60s`** but **`depends_on_sensors` / `evaluate()`** do not read Kyle λ — fingerprint vs runtime mechanism traceability gap (Inv-1 research hygiene). |
| **MEDIUM** | configuration | `platform.yaml` still defaults `alpha_specs` to a **single** shipped SIGNAL id; multi-alpha / PORTFOLIO bundles require explicit operator lists (sensor_specs expanded for common sensors only partially offsets this). |
| **MEDIUM** | test_coverage | `AGENTS.md` documents acceptance drift: baseline alpha YAML vs v0.2 parity tests. |
| **LOW** | test_coverage | E2E tests may still admit sparse or empty intents when replay does not emit feeder signals — orthogonal to horizon wiring. |

**Resolved since pass 1 (for traceability):** synchronizer horizon filter excluding **30s** feeders at **300s** barriers; inventory **`margin_ratio: 1.5`** at Inv-12 floor; falsification half-life text vs G16 table drift; benign **VWAP/TWAP vs KYLE** narrative tension; mixed-alpha **HAWKES_SELF_EXCITE** typo.

---

## Alpha Inventory

| Alpha ID | File | Layer | Horizon (s) | Mechanism Family | Sensors | Regime Gate | Cost Arithmetic | Risk Budget | Status | Decision |
|----------|------|-------|------------:|------------------|---------|-------------|-----------------|-------------|--------|----------|
| pofi_benign_midcap_v1 | `alphas/pofi_benign_midcap_v1/pofi_benign_midcap_v1.alpha.yaml` | SIGNAL | 120 | KYLE_INFO | ofi_ewma, micro_price, spread_z_30d | Yes | Yes | Conservative caps | WARN | RESEARCH_MORE |
| pofi_kyle_drift_v1 | `alphas/pofi_kyle_drift_v1/pofi_kyle_drift_v1.alpha.yaml` | SIGNAL | 300 | KYLE_INFO | kyle_lambda_60s, ofi_ewma, micro_price, spread_z_30d | Yes | Yes | Moderate | WARN | RESEARCH_MORE |
| pofi_inventory_revert_v1 | `alphas/pofi_inventory_revert_v1/pofi_inventory_revert_v1.alpha.yaml` | SIGNAL | 30 | INVENTORY | quote_replenish_asymmetry, spread_z_30d, quote_hazard_rate | Yes | Yes (margin 1.6) | Conservative | WARN | RESEARCH_MORE |
| pofi_hawkes_burst_v1 | `alphas/pofi_hawkes_burst_v1/pofi_hawkes_burst_v1.alpha.yaml` | SIGNAL | 30 | HAWKES_SELF_EXCITE | hawkes_intensity, trade_through_rate, ofi_ewma, spread_z_30d | Yes | Yes | Tight | WARN | RESEARCH_MORE |
| pofi_moc_imbalance_v1 | `alphas/pofi_moc_imbalance_v1/pofi_moc_imbalance_v1.alpha.yaml` | SIGNAL | 120 | SCHEDULED_FLOW | scheduled_flow_window, ofi_ewma | Yes | Yes | Moderate | WARN | RESEARCH_MORE |
| pofi_xsect_v1 | `alphas/pofi_xsect_v1/pofi_xsect_v1.alpha.yaml` | PORTFOLIO | 300 | (multi consume) | — | N/A | Yes | Very loose (fixture-scale) | WARN | RESEARCH_MORE |
| pofi_xsect_v1_with_decay | `alphas/pofi_xsect_v1/pofi_xsect_v1.with_decay.alpha.yaml` | PORTFOLIO | 300 | (multi consume) | — | N/A | Yes | Very loose | WARN | RESEARCH_MORE |
| pofi_xsect_mixed_mechanism_v1 | `alphas/pofi_xsect_mixed_mechanism_v1/pofi_xsect_mixed_mechanism_v1.alpha.yaml` | PORTFOLIO | 300 | (multi consume) | — | N/A | Yes | Very loose | WARN | RESEARCH_MORE |

---

## Per-Alpha Findings

### pofi_benign_midcap_v1

**Summary**

- **File:** `alphas/pofi_benign_midcap_v1/pofi_benign_midcap_v1.alpha.yaml`
- **Layer:** SIGNAL — **schema_version:** 1.1
- **Horizon:** 120 s
- **Mechanism:** KYLE_INFO — hypothesis aligned to Kyle-style footprint (pass 2); **residual:** `kyle_lambda_60s` in fingerprint but not in `evaluate()`
- **Declared actor:** implicit — `structural_actor` field absent
- **Declared hypothesis:** Kyle-style informed-flow footprint (OFI + micro-price) in normal regime; VWAP/TWAP as execution modality only
- **Falsification criteria:** correlation decay, DSR, structural regime shift — substantive
- **Cost margin:** 1.8 (reconciles with `9 / (2+2+1)`)
- **Regime gate:** HMM posteriors + `spread_z_30d`
- **Final decision:** RESEARCH_MORE

**Findings**

| Severity | Category | Finding | Evidence | Recommended Action |
|----------|----------|---------|----------|-------------------|
| MEDIUM | dependency_validity | G16 `l1_signature_sensors` includes `kyle_lambda_60s` but signal logic never reads λ — fingerprint ahead of runtime claim | YAML `depends_on_sensors` + `signal:` | Add λ to deps + snapshot or drop from fingerprint |
| MEDIUM | promotion_readiness | No `promotion:` thresholds | YAML | Add when promoting |
| LOW | schema_loader_compliance | Loads with strict `enforce_trend_mechanism` | Loader smoke | None |

**Kill / Freeze / Promote Notes**

- **Kill if:** N/A (no leakage detected in `signal:` block)
- **Freeze if:** Operator enables strict economics and mechanism coherence checks fail research board
- **Research more if:** Runtime use of declared fingerprint sensors (λ), execution realism vs passive router
- **Paper trade only if:** After CPCV/OOS evidence — single-name SIGNAL path only unless PORTFOLIO bundle explicitly promoted

---

### pofi_kyle_drift_v1

**Summary**

- **Horizon:** 300 s — **Mechanism:** KYLE_INFO — **Half-life:** 600 s (ratio 0.5, G16 lower bound)
- **Final decision:** RESEARCH_MORE — strongest structural alignment of the SIGNAL set

**Findings**

| Severity | Category | Finding | Evidence | Recommended Action |
|----------|----------|---------|----------|-------------------|
| MEDIUM | causality_lookahead | Falsification cites forward 300s returns — OK as research metric; must never enter features | YAML text vs pure `evaluate` | Keep research metrics out of snapshot |
| INFO | trend_mechanism_binding | Boundary ratio 300/600 | G16 | Accept if intentional |

---

### pofi_inventory_revert_v1

**Summary**

- **Horizon:** 30 s — **Mechanism:** INVENTORY
- **Final decision:** RESEARCH_MORE

**Findings**

| Severity | Category | Finding | Evidence | Recommended Action |
|----------|----------|---------|----------|-------------------|
| LOW | cost_execution | Margin 1.6 clears floor; still modest vs aggressive stress | `cost_arithmetic` | Stress at 2× cost before promotion |
| INFO | backtest_compatibility | 30s feeder reaches 300s PORTFOLIO via cross-horizon fan-in | synchronizer tests | None |

---

### pofi_hawkes_burst_v1

**Summary**

- **Hazard exit:** enabled — **Horizon:** 30 s
- **Final decision:** RESEARCH_MORE

**Findings**

| Severity | Category | Finding | Evidence | Recommended Action |
|----------|----------|---------|----------|-------------------|
| INFO | portfolio_feeder | Cross-horizon fan-in supplies hawkes at 300s barriers | integration tests | None |
| INFO | hazard_exit | Opt-in hazard policy declared | YAML | Monitor Level-5 replay tests |

---

### pofi_moc_imbalance_v1

**Summary**

- **Mechanism:** SCHEDULED_FLOW — gate driven by calendar sensor scalars
- **Final decision:** RESEARCH_MORE

**Findings**

| Severity | Category | Finding | Evidence | Recommended Action |
|----------|----------|---------|----------|-------------------|
| MEDIUM | causality_lookahead | Economic validity hinges on whether direction prior is observable at decision time without hindsight | Sensor design | Verify latency + calendar determinism |

---

### pofi_xsect_v1

**Summary**

- **PORTFOLIO** — **horizon_seconds:** 300 — **depends_on_signals:** kyle (300) + inventory (30)
- **Final decision:** RESEARCH_MORE — audit status **WARN** (pass 2)

**Findings**

| Severity | Category | Finding | Evidence | Recommended Action |
|----------|----------|---------|----------|-------------------|
| INFO | backtest_compatibility | Multi-horizon fan-in supplies inventory feeder at 300s barriers | synchronizer + e2e | None |
| HIGH | risk_budget | 50% gross / 100% capital_allocation fixture posture | YAML | Do not deploy literally |
| MEDIUM | economic_mechanism | Harness hypothesis is performance-target without standalone structural claim beyond feeders | YAML hypothesis | CPCV/OOS before promotion |

---

### pofi_xsect_v1_with_decay

Same wiring as `pofi_xsect_v1`; decay applies **after** feeders populate context (pass 2 **WARN**).

---

### pofi_xsect_mixed_mechanism_v1

Dual **30s** feeders (`inventory`, `hawkes`) plus **300s** kyle feeder — all reach composition via `signals_by_strategy_by_symbol` + multi-feeder ranker (pass 2 **WARN**; fixture risk unchanged).

---

## Cross-Alpha Findings

- **Horizon contract:** **PASS 2:** Multi-horizon `depends_on_signals` is supported by synchronizer + bootstrap union horizons and ranker aggregation.
- **Sensor coverage:** Operator must still align `alpha_specs` and sensors per deployment; reference `platform.yaml` lists extra trade-backed sensors but not every bundle.
- **Acceptance drift:** Baseline alpha vs strict-mode parity tests — see `AGENTS.md`.

---

## Backtest / Pipeline Compatibility

**SIGNAL path traced:** `alpha YAML` → `AlphaLoader` → `AlphaRegistry` → `HorizonAggregator` / snapshot → `HorizonSignalEngine` → `Signal` → orchestrator / risk → `ExecutionBackend` (mode-dependent router).

**PORTFOLIO path traced:** upstream `Signal` → `UniverseSynchronizer` → `CrossSectionalContext` → `CompositionEngine` → `SizedPositionIntent` → `RiskEngine.check_sized_intent` → per-leg orders.

**Gap (pass 2):** None on horizon fan-in — residual gap is **economic evidence** (no audited PnL) and **fixture risk_budget** on reference PORTFOLIO YAML.

**Execution realism:** `README.md` documents mid-price fills for `execution_mode: market` backtests — disclosed edges are **not** proof of profit under passive queue or live adverse selection.

---

## Test Coverage Assessment

**Existing tests (sample):** `tests/alpha/*`, `tests/integration/test_xsect_v1_e2e.py`, determinism replay suites, reference alpha load invariants.

**Pass 2 regression tests:** `tests/composition/test_synchronizer.py::test_fan_in_cross_horizon_feeders_into_portfolio_context`, `tests/composition/test_ranker_multi_feeder.py`, plus shipped-spec loader and xsect / mixed e2e modules.

**Commands run (pass 2 slice)**

```bash
uv run pytest tests/alpha/test_shipped_alpha_specs_load.py \
  tests/composition/test_synchronizer.py::test_fan_in_cross_horizon_feeders_into_portfolio_context \
  tests/integration/test_xsect_v1_e2e.py \
  tests/integration/test_mixed_mechanism_e2e.py -q
# 16 passed (representative slice)

uv run pytest tests/alpha/test_shipped_alpha_specs_load.py -q
# 3 passed
```

Full `uv run pytest` was **not** executed for pass 2 (~2095 tests).

---

## Scoring Model (transparent)

Weights (max 115): schema_loader 15, economic_mechanism 10, dependency_validity 10, causality 15, regime_gate 10, trend_binding 10, cost_execution 15, signal_safety 10, risk_budget 5, promotion 5, backtest_compat 10, test_coverage 5.

**PASS** = full weight; **WARN** = half; **FAIL** = zero for that category; **mandatory overrides** zero-out overall trust regardless of subscores.

Detailed numeric scores per alpha are in `alpha_audit_findings.json` (**pass 2** rescoring; see `second_pass_at` and `methodology_pass_2`).

---

## Recommended Action Plan

**P0 — must fix before trusting PORTFOLIO multi-feeder specs** *(done in-tree)*

- ~~Align feeder `horizon_seconds` with PORTFOLIO horizon **or** extend `UniverseSynchronizer` / context schema for explicit multi-horizon fan-in **or** trim `depends_on_signals` to match reality.~~ Implemented: multi-horizon fan-in + per-strategy map + ranker aggregation.

**P1 — promotion narrative / mechanism traceability**

- **Open (pass 2):** Wire `kyle_lambda_60s` into `pofi_benign_midcap_v1` `depends_on_sensors` + `evaluate()` **or** narrow `l1_signature_sensors` to sensors the signal actually consumes.
- Acceptance drift vs baseline YAML (`AGENTS.md`) remains open.

**P2 — research quality** *(done for margin headroom)*

- ~~Raise inventory cost margin headroom or disclose stress failure.~~ Margin raised above floor in `pofi_inventory_revert_v1`.

**P3 — ergonomics** *(done)*

- ~~Fix `HAWKES_SELF_EXCITING` typo in mixed PORTFOLIO description.~~ Corrected to `HAWKES_SELF_EXCITE`.

---

## Final Alpha Decision Table

Pass 2 scores (see JSON).

| Alpha | Score | Status | Decision | Main Reason | Next Action |
|-------|------:|--------|----------|-------------|-------------|
| pofi_benign_midcap_v1 | 74 | WARN | RESEARCH_MORE | Fingerprint vs runtime λ usage | Wire λ or narrow fingerprint |
| pofi_kyle_drift_v1 | 82 | WARN | RESEARCH_MORE | No PnL evidence | CPCV / OOS workflow |
| pofi_inventory_revert_v1 | 88 | WARN | RESEARCH_MORE | No OOS proof | Stress costs + research gates |
| pofi_hawkes_burst_v1 | 85 | WARN | RESEARCH_MORE | No PnL evidence | CPCV / hazard monitoring |
| pofi_moc_imbalance_v1 | 76 | WARN | RESEARCH_MORE | Prior latency unverified | Sensor functional proof |
| pofi_xsect_v1 | 63 | WARN | RESEARCH_MORE | Fixture risk_budget; weak harness hypothesis | Tighten YAML for real use |
| pofi_xsect_v1_with_decay | 63 | WARN | RESEARCH_MORE | Same | Same |
| pofi_xsect_mixed_mechanism_v1 | 64 | WARN | RESEARCH_MORE | Same | Same |

---

## Machine-Readable Output

Structured findings: `docs/audits/alpha_audit_findings.json`.
