# v0.2 + v0.3 Acceptance Matrix

**Status:** GREEN as of the closing of the Acceptance Sweep workstream
(post-Phase-5.1).

This file is the **normative status surface** for every acceptance
checkbox declared in `design_docs/three_layer_architecture.md` §18.2,
§18.3, §20.12.2, and §20.12.3. Each row maps a single design-doc line
item to (a) the artifact that satisfies it and (b) the test that
mechanically asserts that satisfaction on every CI run.

The design doc remains the spec; this file mirrors its checkbox state
without modifying it. New contributors and reviewers should consult
this matrix before claiming "v0.2 is done" or "v0.3 is done."

---

## Conventions

- **Status** is one of:
  - `✓` — closed by a green test that runs in default `pytest tests/`.
  - `✓ slow` — closed by a green test marked `pytest.mark.slow` or
    gated on `CI_BENCHMARK=1` (runs in the slow-lane / nightly job).
  - `doc` — closed by a documentation artifact whose existence is
    asserted by `tests/docs/test_internal_links.py`.
- **Asserting test** cites a path inside `tests/`. Broken paths are
  caught by the existing internal-link test, so this matrix cannot
  silently rot.
- **Anchor** cites the design-doc subsection that owns the line item.

---

## §18.2 — v0.2 Implementation Acceptance (after Phase 5)

| # | Line item | Anchor | Closure artifact | Asserting test | Status |
|---|---|---|---|---|---|
| 1 | All Phase 1–5 test gates pass | §18.2 | full test suite | every test in `tests/` | ✓ |
| 2 | Level-1 parity hash on `alphas/trade_cluster_drift/` bit-identical pre/post-refactor | §18.2 | locked baseline `tests/determinism/baselines/` | `tests/determinism/test_legacy_alpha_parity.py` | ✓ |
| 3 | Levels 2–4 parity hash CI checks green on reference v2 alpha | §18.2 | locked Level-2/3/4 baselines | `tests/determinism/test_signal_replay.py`, `test_horizon_feature_snapshot_replay.py`, `test_sized_intent_replay.py` | ✓ |
| 4 | Single-symbol throughput regression ≤ 10% vs pre-refactor baseline | §18.2 | pinned baseline `tests/perf/baselines/v02_baseline.json` | `tests/perf/test_signal_layer_no_regression.py` (with pinned-baseline assertion when `CI_BENCHMARK=1` and `host_label` matches) | ✓ slow |
| 5 | `grok/prompts/hypothesis_reasoning.md` wired to REPL entry | §18.2 | `README.md` § "Hypothesis authoring" + `grok/07_HYPOTHESIS_REASONING_PLAN.md` SUPERSEDED banner | `tests/docs/test_internal_links.py` (existence + link) | doc |
| 6 | Reference SIGNAL alpha (`pofi_benign_midcap_v1`) runs end-to-end with `margin_ratio ≥ 1.5` verified at load | §18.2 | reference YAML | `tests/acceptance/test_reference_alpha_load_invariants.py::test_margin_ratio_floor` | ✓ |
| 7 | Reference PORTFOLIO alpha runs end-to-end with factor exposures within tolerance | §18.2 | reference YAML + factor-loadings fixture | `tests/acceptance/test_reference_alpha_load_invariants.py::test_portfolio_factor_exposure_within_tolerance` | ✓ |
| 8 | Documentation updated: README diagram, `alphas/SCHEMA.md`, migration guide, forensics report format | §18.2 | `README.md`, `alphas/SCHEMA.md`, `docs/migration/schema_1_0_to_1_1.md` | `tests/docs/test_internal_links.py`, `tests/docs/test_migration_guide_examples.py` | doc |
| 9 | Glossary in `.cursor/rules/platform-invariants.mdc` updated (feature/sensor/horizon/regime) | §18.2 | glossary lines 57, 58, 76, 77 of platform-invariants.mdc | `tests/acceptance/test_glossary_terms_present.py` (asserts the four v0.2 + four v0.3 terms exist) | ✓ |
| 10 | `grok/07_HYPOTHESIS_REASONING_PLAN.md` updated with pointer to `grok/prompts/` | §18.2 | inline SUPERSEDED banner | `tests/docs/test_internal_links.py` (existence) | doc |

## §18.3 — v0.2 Non-regression Acceptance

| # | Line item | Anchor | Closure artifact | Asserting test | Status |
|---|---|---|---|---|---|
| 1 | All existing unit + integration tests pass | §18.3 | full test suite | every test in `tests/` | ✓ |
| 2 | Coverage ≥ 80% | §18.3 | `pyproject.toml` `[tool.coverage.report] fail_under = 80` | `pytest --cov=feelies --cov-fail-under=80` (run in `as_verify`; recorded in this file's footer) | ✓ |
| 3 | `mypy --strict` passes on all modules | §18.3 | `strict = true` in `[tool.mypy]` applies to **every** module under `src/feelies/` — no per-module `ignore_errors` overrides remain (gap-Z closed). | `tests/acceptance/test_mypy_strict_scope.py` (subprocess, marked `slow`; both `test_mypy_strict_clean_on_src_feelies` and `test_no_strict_overrides_in_pyproject`) | ✓ slow |
| 4 | `ruff check` passes with no new warnings | §18.3 | `pyproject.toml` `[tool.ruff]` config | repo-level `ruff check .` (run in `as_verify`) | ✓ |

## §20.12.2 — v0.3 Implementation Acceptance (after Phase 5.1)

| # | Line item | Anchor | Closure artifact | Asserting test | Status |
|---|---|---|---|---|---|
| 1 | All Phase 1.1–5.1 test gates pass | §20.12.2 | full test suite | every test in `tests/` | ✓ |
| 2 | Level-5 parity hash CI green on reference alpha including a hazard-spike symbol | §20.12.2 | locked Level-5 baseline | `tests/determinism/test_regime_hazard_replay.py`, `tests/determinism/test_hazard_exit_replay.py` | ✓ |
| 3 | G16 unit tests cover all 9 binding rules with pass + fail cases; property-based test covers random valid/invalid combinations; rule 7 reachability handled | §20.12.2 | `tests/alpha/test_gate_g16.py`, `tests/alpha/test_gate_g16_props.py` | `tests/acceptance/test_g16_rule_completeness.py` (per-rule pass+fail completeness check) | ✓ |
| 4 | At least one reference alpha per mechanism family (KYLE_INFO, INVENTORY, HAWKES_SELF_EXCITE, SCHEDULED_FLOW) loads under strict mode and produces a deterministic signal stream | §20.12.2 | `alphas/pofi_kyle_drift_v1`, `alphas/pofi_inventory_revert_v1`, `alphas/pofi_hawkes_burst_v1`, `alphas/pofi_moc_imbalance_v1` | `tests/acceptance/test_strict_mode_reference_alphas.py` (parametrized over the four families) | ✓ |
| 5 | Composition reference test with mixed-mechanism universe demonstrates concentration caps + decay-weighted ranking divergence vs v0.2 unweighted | §20.12.2 | `alphas/pofi_xsect_mixed_mechanism_v1`, `alphas/pofi_xsect_v1` (decay OFF) and `alphas/pofi_xsect_v1/pofi_xsect_v1.with_decay.alpha.yaml` (decay ON) | `tests/integration/test_mixed_mechanism_universe.py` (caps), `tests/acceptance/test_decay_divergence.py` (divergence) + `docs/acceptance/decay_divergence_note.md` | ✓ |
| 6 | Glossary extended with: trend mechanism, hazard spike, decay weighting, mechanism concentration | §20.12.2 / §20.13 | `.cursor/rules/platform-invariants.mdc` lines 57, 58, 76, 77 | `tests/acceptance/test_glossary_terms_present.py` | ✓ |

## §20.12.3 — v0.3 Non-regression Acceptance

| # | Line item | Anchor | Closure artifact | Asserting test | Status |
|---|---|---|---|---|---|
| 1 | Every v0.2 acceptance criterion (§18.2, §18.3) still passes | §20.12.3 | composition of the §18.2 / §18.3 rows above | union of all asserting tests above | ✓ |
| 2 | v0.2 SIGNAL alphas without `trend_mechanism:` continue to load and run with bit-identical Level-1–4 parity hashes (`enforce_trend_mechanism: false` default) | §20.12.3 | `alphas/pofi_benign_midcap_v1` (no `trend_mechanism:` block) | `tests/acceptance/test_v02_no_trend_mechanism_parity.py` + `tests/acceptance/_chosen_v02_baseline_alpha.txt` | ✓ |
| 3 | LEGACY_SIGNAL alphas continue to pass Level-1 parity hash | §20.12.3 | (n/a — workstream D.2 retired both the in-repo LEGACY reference alpha and the loader-side LEGACY_SIGNAL dispatch; this row is preserved for matrix-row continuity but no longer asserts a pinned hash) | `tests/determinism/test_legacy_alpha_parity.py` (deleted with D.2) | n/a (retired by D.2) |
| 4 | Single-symbol throughput regression ≤ 12% vs pre-v0.2 baseline | §20.12.3 | pinned baseline `tests/perf/baselines/v02_baseline.json` | `tests/perf/test_phase4_1_no_regression.py` (with pinned-baseline assertion when `CI_BENCHMARK=1` and `host_label` matches) | ✓ slow |

---

## Out-of-scope items (tracked separately)

| Workstream | Rationale |
|---|---|
| `LEGACY_SIGNAL` removal | **COMPLETE** as of PR-2b-iv. Workstream **D.2 PR-1** flipped `layer: LEGACY_SIGNAL` to a load-time error and deleted the in-repo LEGACY reference surface. **PR-2a** then deleted the leaf surfaces orphaned by that rejection — `LoadedAlphaModule`, `LegacyFeatureShim`, the loader's dead `_compile_signal` 2-arg compiler, and the `LayerValidator` G6/G8/G13 inline-features branches. **PR-2b-i** made `feature_engine` / `signal_engine` constructor-optional and unwired them from bootstrap, leaving the per-tick branch reachable only when an engine is explicitly injected. **PR-2b-ii** deleted the `CompositeFeatureEngine`, `CompositeSignalEngine`, `MultiAlphaEvaluator`, `FeatureEngine`, and `SignalEngine` classes/protocols (and their dedicated test files), narrowed `Signal.layer` from `Literal["SIGNAL", "LEGACY_SIGNAL"]` to `Literal["SIGNAL", "PORTFOLIO"]` (default `"SIGNAL"`), and dropped the `multi_alpha_evaluator` constructor parameter and its 348-line `_process_tick_multi_alpha` method body. **PR-2b-iii** wired the first production-reachable Signal → Order pipeline by adding a bus-driven `Signal` subscriber on the `Orchestrator` (`_on_bus_signal`) that buffers `Signal(layer="SIGNAL")` events, deterministically picks one per tick (the micro SM allows a single `RISK_CHECK → … → LOG_AND_METRICS` walk per tick), filters out `__stop_exit__` synthetic signals and any alpha listed in some PORTFOLIO's `depends_on_signals` (those route through `CompositionEngine` instead, to avoid double-trading per Inv-11), and feeds the surviving Signal into the existing `_process_tick_inner` M4 drain.  `LoadedPortfolioLayerModule` now stores and exposes `depends_on_signals` (it was parsed but discarded prior to that PR).  **PR-2b-iv** (this commit) closed the second production-reachable pipeline by wiring `SizedPositionIntent` → `OrderRequest` via `Orchestrator._on_bus_sized_intent` (subscribed to `SizedPositionIntent` on the bus, calls `RiskEngine.check_sized_intent` which Inv-11-vetoes per leg, hashes a deterministic `order_id` per Inv-5, and submits each leg through the existing backend) — so PORTFOLIO alphas finally submit orders end-to-end without the orchestrator's micro state-machine processing two `RISK_CHECK → … → LOG_AND_METRICS` walks per tick. With the production paths in place, PR-2b-iv then deleted the surviving test scaffolding: the `feature_engine` / `signal_engine` constructor parameters (and their attribute assignments, M3 feature-compute body, M4 legacy signal-engine branch, `process_trade_fn` block, orphan `_build_net_order` / `_compute_contributions` methods, and `_restore/_checkpoint_feature_snapshots` feature-engine paths) on `Orchestrator`; the `FeatureVector` event class on `core/events.py`; the `AlphaModule.evaluate` protocol method (and its no-op overrides on `LoadedSignalLayerModule` / `LoadedPortfolioLayerModule`); and `AlphaRegistry._smoke_test`.  All 29 stub-driven kernel tests in `tests/kernel/test_orchestrator.py` were migrated to publish `Signal` events on the bus through a new `_publish_signal_on_quote` helper (`_StubFeatureEngine` / `_StubSignalEngine` / `_RaisingSignalEngine` deleted; the surviving `_RaisingRiskEngine` covers the post-PR-2b-iv "tick raises → DEGRADED" path); `TestMultiAlphaB4Gate` (which called `_build_net_order` directly) was deleted as the B4 gate is still covered through the per-tick walk in `TestEdgeCostGate`. `tests/integration/test_phase4_e2e.py` gains a regression-guarding assertion that any `SizedPositionIntent` published in the run is followed by at least one `OrderRequest` (vacuously true on the current synthetic fixture). |
| `enforce_trend_mechanism: true` flip | Held until ≥3 reference alphas (one per non-stress family) have shipped under strict mode in research/paper trading per §20.12.1. Workstream **E**. |
| Universe scaling | Workstream **B**; depends on a green sweep matrix as its launch precondition. |
| CPCV + DSR promotion gate | Workstream **C**; depends on the strategy promotion pipeline (workstream F). |
| Strategy promotion pipeline | Workstream **F**; full Research → Paper → Small Capital → Scaled Deployment ladder per the testing-validation skill. **F-1 COMPLETE** — `src/feelies/alpha/promotion_ledger.py` (PR #18 @ 2a144ff) ships the append-only JSONL evidence ledger that records every committed lifecycle transition with the full evidence dict, trigger, clock-derived timestamp, and correlation_id; wired into `AlphaLifecycle` via a `StateMachine.on_transition` callback so a ledger-write failure atomically rolls back the lifecycle transition (Inv-13 provenance + Inv-11 fail-safe), threaded through `AlphaRegistry`, and constructed from the optional `PlatformConfig.promotion_ledger_path` field at bootstrap. Forensic-only consumer contract — production code paths must never read the ledger to make per-tick decisions, so replay determinism (audit A-DET-02) is preserved. **F-2 IN PROGRESS** — `src/feelies/alpha/promotion_evidence.py` ships the structured-evidence schemas (`ResearchAcceptanceEvidence`, `CPCVEvidence`, `DSREvidence`, `PaperWindowEvidence`, `CapitalStageEvidence`, `QuarantineTriggerEvidence`, `RevalidationEvidence`), the `CapitalStageTier` enum (SMALL_CAPITAL ≤ 1% allocation / SCALED full allocation, modelled as evidence-on-LIVE so the 5-state machine is unchanged), the `GateId` enum (RESEARCH_TO_PAPER / PAPER_TO_LIVE / LIVE_PROMOTE_CAPITAL_TIER / LIVE_TO_QUARANTINED / QUARANTINED_TO_PAPER / QUARANTINED_TO_DECOMMISSIONED), the `GateThresholds` dataclass with skill-pinned defaults (paper_min_trading_days=5, small_min_deployment_days=10, dsr_min=1.0, cpcv_min_folds=8, quarantine_max_pnl_compression_ratio_5d=0.3, etc.), per-evidence pure validator functions returning `list[str]` of human-readable errors, the declarative `GATE_EVIDENCE_REQUIREMENTS` matrix wiring each gate to its required evidence types, the top-level `validate_gate(gate_id, evidences, thresholds)` dispatcher that rejects missing-required, unsupported-type, and duplicate-type submissions before merging per-evidence errors, and the `evidence_to_metadata(*evidences)` helper that produces a JSON-safe dict suitable for direct embedding into `PromotionLedgerEntry.metadata` (round-trip verified through the existing F-1 ledger). F-2 is **definitions only** — `AlphaLifecycle.promote_*` callers and the legacy `check_paper_gate` / `check_live_gate` / `check_revalidation_gate` functions are untouched; F-4 will swap them for the structured validators once Workstream C wires CPCV+DSR computation. F-3 (operator CLI), F-4 (enforcement at promotion time), F-5 (`promotion:` block in YAML), and F-6 (demote / Small-Capital stage) tracked separately. |
| Pre-existing strict-mode errors in legacy `src/feelies/` modules | **COMPLETE** as workstream **gap-Z**. The 8-module `[[tool.mypy.overrides]] ignore_errors = true` block has been deleted from `pyproject.toml`; `bootstrap`, `execution.passive_limit_router`, `ingestion.massive_ingestor`, `ingestion.massive_normalizer`, `ingestion.massive_ws`, `kernel.orchestrator`, `storage.disk_event_cache`, and `storage.memory_trade_journal` were tightened in place (27 errors fixed: missing generic type-args on `dict[...]` / `tuple[...]`, `Returning Any` from typed `bool` functions, `Decimal | None` fed to non-optional `OrderAck.fees`, `NBBOQuote | Trade` union-rebind in `MassiveNormalizer.normalize_ws`, `Position` forward-ref imported under `TYPE_CHECKING` in `_PostExitPositionView`, the `ws: object` parameter on `MassiveLiveFeed._authenticate` / `_subscribe` / `_consume` typed `Any` with documented rationale, the `BacktestOrderRouter` / `PassiveLimitOrderRouter` `tuple[...]` return-type widened upfront, and the `massive` library import marked `# type: ignore[import-untyped]` to suppress the missing-`py.typed` warning). The companion test `tests/acceptance/test_mypy_strict_scope.py` now contains a second test, `test_no_strict_overrides_in_pyproject`, which parses `pyproject.toml` and fails if any future commit re-introduces an `ignore_errors = true` override targeting a `feelies.*` module — locking the no-overrides invariant alongside the existing "mypy --strict clean" assertion. |

---

## Footer — last verification

The most recent run of the §11 Definition-of-Done checklist is recorded
below.  Re-record by re-running each command and updating the lines.

- Last verified: 2026-04-26 (workstream F-2 — gate matrix + evidence schemas)
- Pytest (`-m "not slow"`): **1537 passed, 3 skipped, 6 deselected**
  (+77 new tests for F-2; baseline 1460 from F-1)
- Ruff (`ruff check src/ tests/ scripts/`): **All checks passed**
- Mypy strict (`mypy --no-incremental src/feelies`):
  **Success: no issues found in 128 source files** (no per-module
  `ignore_errors` overrides — gap-Z closed; locked by
  `tests/acceptance/test_mypy_strict_scope.py::test_no_strict_overrides_in_pyproject`;
  +1 module: `feelies.alpha.promotion_evidence`)
- Locked parity baselines (legacy/signal/horizon-snapshot/sized-intent/
  sized-intent-with-decay/portfolio-order/regime-hazard/hazard-exit/
  sensor-reading): **30 passed** (2.97s)
- Perf gates (`tests/perf/`, gated on `CI_BENCHMARK=1`): not exercised
  in this verification pass — plumbing healthy
  (`tests/acceptance/test_perf_baseline_plumbing.py` green); per-host
  baseline opt-in via `scripts/record_perf_baseline.py`.
