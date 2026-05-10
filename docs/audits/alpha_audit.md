# Feelies Alpha Audit

**Repository:** [Leiisawesome/feelies](https://github.com/Leiisawesome/feelies)  
**Scope:** `alphas/` (active specs discovered by `discover_alpha_specs`; `_template/` excluded by underscore rule)  
**Audit date:** 2026-05-10 (UTC)  
**Loader verification:** `AlphaLoader(enforce_trend_mechanism=False|True)` loads all eight shipped specs without error.

This audit is **not** a performance guarantee. No walk-forward Sharpe, live-slippage, or fill-model evidence was evaluated beyond tracing platform wiring and running a focused pytest subset.

### Remediation applied (in-repo, same date)

The following items from this audit were implemented in the codebase (BLOCKER / HIGH / operator config); numeric scores in the JSON snapshot below are **not** recomputed until a full re-audit.

- **BLOCKER — PORTFOLIO vs feeder horizons:** `UniverseSynchronizer` now unions portfolio and upstream SIGNAL horizons, caches per-feeder `Signal`s, and at portfolio barriers selects same-horizon feeders by boundary alignment and cross-horizon feeders by latest `timestamp_ns ≤ barrier`. `CrossSectionalContext` carries `signals_by_strategy_by_symbol`; bootstrap wires `signal_horizons`, `upstream_strategy_ids`, and `feeder_strategy_ids` into the composition pipeline; `CrossSectionalRanker` sums marginal raw scores across feeders when configured.
- **HIGH — benign KYLE narrative / fingerprint:** `pofi_benign_midcap_v1` hypothesis reframed toward Kyle-style footprint; `trend_mechanism.l1_signature_sensors` includes `kyle_lambda_60s` (alongside existing sensors).
- **HIGH — inventory margin floor:** `pofi_inventory_revert_v1` cost block adjusted (`margin_ratio` above Inv-12 floor; falsification half-life band tightened per audit).
- **HIGH — mixed typo:** `pofi_xsect_mixed_mechanism_v1` mechanism enum spelling corrected to `HAWKES_SELF_EXCITE`.
- **MEDIUM — `platform.yaml`:** Additional `sensor_specs` entries for `kyle_lambda_60s`, `trade_through_rate`, `hawkes_intensity`.

---

## Executive Summary

| Metric | Value |
|--------|------:|
| `.alpha.yaml` files found (active) | 8 |
| Template / underscore-dir specs (excluded from discovery) | 2 |
| Loaded successfully (strict + loose) | 8 |
| Failed load | 0 |
| Audit status **PASS** | 0 |
| Audit status **WARN** | 5 |
| Audit status **FAIL** | 3 |
| Decision **KILL** | 0 |
| Decision **RESEARCH_MORE** | 8 |
| Decision **PAPER_TRADE_CANDIDATE** | 0 |
| Decision **DEPLOY_SMALL_CANDIDATE** | 0 |
| Decision **PASS_STRUCTURAL_ONLY** (SIGNAL subset) | 5 |

**Interpretation:** Every shipped SIGNAL alpha is **structurally loadable** and passes inline AST purity gates at load time, but none carries audited profitability or execution evidence. At audit time, all three PORTFOLIO reference alphas **FAILED** the composition-feed contract because **30s** feeders did not reach **300s** barriers through the synchronizer; that wiring gap is **remediated** in-tree (see **Remediation applied** above). Table counts below reflect the pre-remediation audit pass unless refreshed.

---

## Critical Findings

BLOCKER and HIGH items appear first.

| Severity | Category | Finding |
|----------|----------|---------|
| **BLOCKER** | backtest_compatibility | `pofi_xsect_v1`, `pofi_xsect_v1_with_decay`, `pofi_xsect_mixed_mechanism_v1` declare `depends_on_signals` that include SIGNAL alphas at **30s** horizon while `horizon_seconds: 300`. `UniverseSynchronizer` filters bus `Signal` events with `sig.horizon_seconds == tick.horizon_seconds`; **30s signals never populate `CrossSectionalContext.signals_by_symbol` at 300s barriers.** Integration tests explicitly allow **degenerate** (empty) intents — see `tests/integration/test_xsect_v1_e2e.py`. |
| **HIGH** | economic_mechanism | `pofi_benign_midcap_v1` declares `trend_mechanism.family: KYLE_INFO` while the hypothesis emphasizes VWAP/TWAP slicing — narrative mismatch vs taxonomy; fingerprint list omits `kyle_lambda_60s` (G16 satisfied by `micro_price` only). |
| **HIGH** | cost_execution | `pofi_inventory_revert_v1` declares `margin_ratio: 1.5`, exactly the platform floor — zero headroom vs Inv-12 stress doctrine. |
| **HIGH** | backtest_compatibility | Same horizon mismatch implies **inventory / hawkes feeders do not actually reach** the reference PORTFOLIO ranker at 300s — multi-mechanism diversification claimed in YAML is **not executed** by current wiring. |
| **MEDIUM** | configuration | `platform.yaml` pins a single `alpha_specs` entry (`pofi_benign_midcap_v1`) and a partial `sensor_specs` list — other shipped alphas need explicit operator bundles. |
| **MEDIUM** | test_coverage | Documented acceptance drift: baseline alpha YAML vs v0.2 parity tests (`AGENTS.md`). |

---

## Alpha Inventory

| Alpha ID | File | Layer | Horizon (s) | Mechanism Family | Sensors | Regime Gate | Cost Arithmetic | Risk Budget | Status | Decision |
|----------|------|-------|------------:|------------------|---------|-------------|-----------------|-------------|--------|----------|
| pofi_benign_midcap_v1 | `alphas/pofi_benign_midcap_v1/pofi_benign_midcap_v1.alpha.yaml` | SIGNAL | 120 | KYLE_INFO | ofi_ewma, micro_price, spread_z_30d | Yes | Yes | Conservative caps | WARN | RESEARCH_MORE |
| pofi_kyle_drift_v1 | `alphas/pofi_kyle_drift_v1/pofi_kyle_drift_v1.alpha.yaml` | SIGNAL | 300 | KYLE_INFO | kyle_lambda_60s, ofi_ewma, micro_price, spread_z_30d | Yes | Yes | Moderate | WARN | RESEARCH_MORE |
| pofi_inventory_revert_v1 | `alphas/pofi_inventory_revert_v1/pofi_inventory_revert_v1.alpha.yaml` | SIGNAL | 30 | INVENTORY | quote_replenish_asymmetry, spread_z_30d, quote_hazard_rate | Yes | Yes (floor margin) | Conservative | WARN | RESEARCH_MORE |
| pofi_hawkes_burst_v1 | `alphas/pofi_hawkes_burst_v1/pofi_hawkes_burst_v1.alpha.yaml` | SIGNAL | 30 | HAWKES_SELF_EXCITE | hawkes_intensity, trade_through_rate, ofi_ewma, spread_z_30d | Yes | Yes | Tight | WARN | RESEARCH_MORE |
| pofi_moc_imbalance_v1 | `alphas/pofi_moc_imbalance_v1/pofi_moc_imbalance_v1.alpha.yaml` | SIGNAL | 120 | SCHEDULED_FLOW | scheduled_flow_window, ofi_ewma | Yes | Yes | Moderate | WARN | RESEARCH_MORE |
| pofi_xsect_v1 | `alphas/pofi_xsect_v1/pofi_xsect_v1.alpha.yaml` | PORTFOLIO | 300 | (multi consume) | — | N/A | Yes | Very loose (fixture-scale) | FAIL | RESEARCH_MORE |
| pofi_xsect_v1_with_decay | `alphas/pofi_xsect_v1/pofi_xsect_v1.with_decay.alpha.yaml` | PORTFOLIO | 300 | (multi consume) | — | N/A | Yes | Very loose | FAIL | RESEARCH_MORE |
| pofi_xsect_mixed_mechanism_v1 | `alphas/pofi_xsect_mixed_mechanism_v1/pofi_xsect_mixed_mechanism_v1.alpha.yaml` | PORTFOLIO | 300 | (multi consume) | — | N/A | Yes | Very loose | FAIL | RESEARCH_MORE |

---

## Per-Alpha Findings

### pofi_benign_midcap_v1

**Summary**

- **File:** `alphas/pofi_benign_midcap_v1/pofi_benign_midcap_v1.alpha.yaml`
- **Layer:** SIGNAL — **schema_version:** 1.1
- **Horizon:** 120 s
- **Mechanism:** KYLE_INFO (declared) vs VWAP/TWAP narrative (hypothesis)
- **Declared actor:** implicit — `structural_actor` field absent
- **Declared hypothesis:** persistent OFI drift in “normal” microstructure
- **Falsification criteria:** correlation decay, DSR, structural regime shift — substantive
- **Cost margin:** 1.8 (reconciles with `9 / (2+2+1)`)
- **Regime gate:** HMM posteriors + `spread_z_30d`
- **Final decision:** RESEARCH_MORE

**Findings**

| Severity | Category | Finding | Evidence | Recommended Action |
|----------|----------|---------|----------|-------------------|
| HIGH | economic_mechanism | Mechanism label KYLE_INFO vs VWAP/TWAP institutional slicing story — taxonomy tension | `trend_mechanism` + `hypothesis` | Align family + sensors with Kyle λ story or rewrite hypothesis |
| MEDIUM | promotion_readiness | No `promotion:` thresholds | YAML | Add when promoting |
| LOW | schema_loader_compliance | Loads with strict `enforce_trend_mechanism` | Loader smoke | None |

**Kill / Freeze / Promote Notes**

- **Kill if:** N/A (no leakage detected in `signal:` block)
- **Freeze if:** Operator enables strict economics and mechanism coherence checks fail research board
- **Research more if:** Mechanism narrative, Kyle sensor inclusion, execution realism vs passive router
- **Paper trade only if:** After horizon-aligned portfolio fixes elsewhere — single-name SIGNAL path only

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
| HIGH | cost_execution | margin_ratio == MIN (1.5) | `cost_arithmetic` | Stress costs |
| MEDIUM | documentation | Falsification mentions half-life [1,60]s; code table uses [5,60] for INVENTORY | YAML vs `layer_validator.py` | Align copy |
| HIGH | portfolio_feeder | 30s feeder cannot populate 300s `CrossSectionalContext` | synchronizer | Fix portfolio horizon design |

---

### pofi_hawkes_burst_v1

**Summary**

- **Hazard exit:** enabled — **Horizon:** 30 s
- **Final decision:** RESEARCH_MORE

**Findings**

| Severity | Category | Finding | Evidence | Recommended Action |
|----------|----------|---------|----------|-------------------|
| HIGH | portfolio_feeder | Same 30s vs 300s PORTFOLIO mismatch when used as mixed feeder | synchronizer | Align horizons |
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
- **Final decision:** RESEARCH_MORE — audit status **FAIL**

**Findings**

| Severity | Category | Finding | Evidence | Recommended Action |
|----------|----------|---------|----------|-------------------|
| BLOCKER | backtest_compatibility | Inventory feeder signals excluded from 300s cross-sectional fan-in | `synchronizer.py` | Remediate horizon contract |
| HIGH | risk_budget | 50% gross / 100% capital_allocation fixture posture | YAML | Do not deploy literally |

---

### pofi_xsect_v1_with_decay

Same BLOCKER as `pofi_xsect_v1`; decay weighting does not inject missing feeder signals.

---

### pofi_xsect_mixed_mechanism_v1

Same BLOCKER; **two** feeders at 30s (`inventory`, `hawkes`) never surface at 300s barriers.

---

## Cross-Alpha Findings

- **Horizon contract:** PORTFOLIO composition is single-horizon per `CrossSectionalContext`; multi-horizon `depends_on_signals` is misleading without synchronizer changes.
- **Sensor coverage:** Loader-level G6/G16 rule 4 abstains when `known_sensor_ids` is unset; bootstrap resolves sensors — ship minimal `sensor_specs` per bundle.
- **Acceptance drift:** Baseline alpha vs strict-mode parity tests — see `AGENTS.md`.

---

## Backtest / Pipeline Compatibility

**SIGNAL path traced:** `alpha YAML` → `AlphaLoader` → `AlphaRegistry` → `HorizonAggregator` / snapshot → `HorizonSignalEngine` → `Signal` → orchestrator / risk → `ExecutionBackend` (mode-dependent router).

**PORTFOLIO path traced:** upstream `Signal` → `UniverseSynchronizer` → `CrossSectionalContext` → `CompositionEngine` → `SizedPositionIntent` → `RiskEngine.check_sized_intent` → per-leg orders.

**Gap:** Synchronizer horizon filter breaks declared multi-feeder PORTFOLIO specs (see Critical Findings).

**Execution realism:** `README.md` documents mid-price fills for `execution_mode: market` backtests — disclosed edges are **not** proof of profit under passive queue or live adverse selection.

---

## Test Coverage Assessment

**Existing tests (sample):** `tests/alpha/*`, `tests/integration/test_xsect_v1_e2e.py`, determinism replay suites, reference alpha load invariants.

**Missing tests (audit flag):** Assertion that each `depends_on_signals` alpha’s `Signal.horizon_seconds` equals PORTFOLIO `horizon_seconds`, or explicit multi-horizon aggregation contract.

**Tests added:** `tests/alpha/test_shipped_alpha_specs_load.py` — discovers eight specs; loads each under `enforce_trend_mechanism` on/off.

**Commands run**

```bash
uv run pytest tests/alpha tests/integration/test_xsect_v1_e2e.py \
  tests/integration/test_mixed_mechanism_e2e.py \
  tests/acceptance/test_reference_alpha_load_invariants.py -q
# 598 passed

uv run pytest tests/alpha/test_shipped_alpha_specs_load.py -q
# 3 passed
```

Full `uv run pytest` was **not** executed in this audit slice (~2095 tests).

---

## Scoring Model (transparent)

Weights (max 115): schema_loader 15, economic_mechanism 10, dependency_validity 10, causality 15, regime_gate 10, trend_binding 10, cost_execution 15, signal_safety 10, risk_budget 5, promotion 5, backtest_compat 10, test_coverage 5.

**PASS** = full weight; **WARN** = half; **FAIL** = zero for that category; **mandatory overrides** zero-out overall trust regardless of subscores.

Detailed numeric scores per alpha are in `alpha_audit_findings.json`.

---

## Recommended Action Plan

**P0 — must fix before trusting PORTFOLIO multi-feeder specs** *(done in-tree)*

- ~~Align feeder `horizon_seconds` with PORTFOLIO horizon **or** extend `UniverseSynchronizer` / context schema for explicit multi-horizon fan-in **or** trim `depends_on_signals` to match reality.~~ Implemented: multi-horizon fan-in + per-strategy map + ranker aggregation.

**P1 — must fix before promotion narrative**

- ~~Reconcile `pofi_benign_midcap_v1` mechanism taxonomy with hypothesis.~~ Addressed in YAML; acceptance drift vs baseline YAML (`AGENTS.md`) remains an open test/YAML alignment item.

**P2 — research quality** *(done for margin headroom)*

- ~~Raise inventory cost margin headroom or disclose stress failure.~~ Margin raised above floor in `pofi_inventory_revert_v1`.

**P3 — ergonomics** *(done)*

- ~~Fix `HAWKES_SELF_EXCITING` typo in mixed PORTFOLIO description.~~ Corrected to `HAWKES_SELF_EXCITE`.

---

## Final Alpha Decision Table

| Alpha | Score | Status | Decision | Main Reason | Next Action |
|-------|------:|--------|----------|-------------|-------------|
| pofi_benign_midcap_v1 | 72 | WARN | RESEARCH_MORE | Mechanism/hypothesis tension | Align KYLE_INFO story |
| pofi_kyle_drift_v1 | 82 | WARN | RESEARCH_MORE | No PnL evidence | CPCV / OOS workflow |
| pofi_inventory_revert_v1 | 78 | WARN | RESEARCH_MORE | Margin at floor; feeder/portfolio mismatch | Cost stress + horizon fix |
| pofi_hawkes_burst_v1 | 80 | WARN | RESEARCH_MORE | Feeder/portfolio mismatch | Horizon fix |
| pofi_moc_imbalance_v1 | 76 | WARN | RESEARCH_MORE | Prior latency unverified | Sensor functional proof |
| pofi_xsect_v1 | 38 | FAIL† | RESEARCH_MORE | Was BLOCKER: horizon fan-in | Remediated in synchronizer/ranker; re-score on re-audit |
| pofi_xsect_v1_with_decay | 38 | FAIL† | RESEARCH_MORE | Same BLOCKER | Same |
| pofi_xsect_mixed_mechanism_v1 | 35 | FAIL† | RESEARCH_MORE | Same BLOCKER (×2 feeders) | Same |

† **Status column** reflects the original audit scoring artifact; structural BLOCKER is addressed in code — expect higher `backtest_compat` on refresh.

---

## Machine-Readable Output

Structured findings: `docs/audits/alpha_audit_findings.json`.
