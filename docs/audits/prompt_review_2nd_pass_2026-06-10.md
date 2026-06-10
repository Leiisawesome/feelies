# Prompt Review Report — 2nd Pass

**Date:** 2026-06-10
**Scope:** all 18 files under `docs/prompts/` (17 audit prompts + `README.md`), audited
against the repository state at `5687abd` (PR #112).
**Relation to 1st pass:** the 1st pass (2026-06-08, conversational) established the
coverage matrix and per-prompt findings. This pass (a) re-verifies every 1st-pass claim
against the current tree, (b) adds a citation-integrity sweep the 1st pass took on trust
(~140 cited test paths, all architecture-doc section references, `platform.yaml` keys),
and (c) audits **drift**: the prompt set is frozen at 2026-06-07
(`git log -1 -- docs/prompts/` → `2a020e1 2026-06-07`) while 29 commits have landed
since — most of them inside the exact coverage hole the 1st pass flagged.

---

## 1. Executive Verdict

- **Overall status: PARTIAL (unchanged) — and degrading.** No prompt was edited since
  the 1st pass; every 1st-pass defect stands. Meanwhile the G-3…G-7
  position-management remediation (PRs #105–#112) has shipped new capital-path
  modules, a **default-on** kernel safety behavior, and new determinism/emit surfaces —
  none referenced by any prompt (`grep` for `portfolio_netter|edge_weighted|lot_ledger|
  session_flatten|enable_portfolio_netting|analyze_net_divergence|analyze_size_divergence`
  across `docs/prompts/` returns zero hits).
- **Main reason:** the set remains structurally excellent — citation integrity is
  near-perfect (one missing path out of ~140, and that one is self-hedged) — but the
  pipeline stages "position decision" and "PnL ledger" are still unowned, and the code
  under those stages is now actively changing without audit coverage.
- **Highest-risk gap:** `session_flatten_enabled: bool = True`
  (`src/feelies/core/platform_config.py:340`, G-6) is a **new default-on close-path
  behavior in the kernel** — it flattens all open positions at RTH close. It is exactly
  the class of capital-affecting, Inv-11-adjacent control every prompt insists on
  auditing, and no prompt names it. Same for `execution/portfolio_netter.py` (G-5,
  cross-alpha netting, `enable_portfolio_netting` default False),
  `risk/edge_weighted_sizer.py` (G-7), and `portfolio/lot_ledger.py` (G-4 — FIFO lot
  accounting, i.e. **the PnL-ledger stage the 1st pass already flagged as unowned**).
- **Highest-value fix:** unchanged from the 1st pass, now broader — create
  `docs/prompts/audit_position_management.md` owning the SIGNAL-path decision/exit
  economics **plus** the new G-3…G-7 modules and the PnL/lot ledger; and add a
  staleness guard (P1-4 below) so the prompt set cannot silently drift again.

---

## 2. Verification Results (new in this pass)

### 2.1 Citation-integrity sweep

| Citation class | Checked | Result |
|---|---|---|
| Source paths in prompt scopes | all (1st pass) + re-spot-checked | all exist |
| Test paths cited in prompts | ~140 across all 17 prompts | **1 missing**: `tests/execution/test_market_fill.py` — but `audit_execution_fills.md:84` already hedges it "(if present)". No action needed. |
| `docs/three_layer_architecture.md` § refs (§5.5–5.7, §6.4/6.5/6.10, §7.2–7.5, §8.4, §8.5, §9, §12, §13, §14, §20.3–20.7, §20.11.2) | all | all resolve to real headings — **one mislabel**, see D-7 |
| `platform.yaml` keys (`sensor_specs`, `regime_engine`, `gate_thresholds`, `enforce_trend_mechanism`) | all | all present (`platform.yaml:23,41,168,193`) |
| Skill files referenced | all 13 | all exist under `.cursor/skills/` |
| Empirical claims (`tests/forensics/` holds only `test_tca.py`; `monitoring/health.py` has no dedicated test) | both | **both TRUE** (`ls tests/forensics/` → `test_tca.py` only; `tests/health/` is empty; `tests/monitoring/` has no health test) |
| Parity-baseline count | `tests/determinism/parity_manifest.py:65-98` | **11 baselines, 6 levels** — `audit_determinism.md` says "five" at lines 33, 43, 64, 94. Confirmed defect (D-1). |
| Micro-SM stage count | `src/feelies/kernel/micro.py:82-97` | **16 states** through `ORDER_SUBMIT → ORDER_ACK → POSITION_UPDATE → LOG_AND_METRICS`; "M1–M6" shorthand in kernel/regime/performance/signal prompts is incomplete. Confirmed defect (D-2). |

This grounding quality is exceptional for a hand-written prompt set; the defects below
are narrow and enumerable, not systemic sloppiness.

### 2.2 Drift audit — code that moved into the coverage hole (NEW)

Since the prompts were last touched (2026-06-07), 29 commits landed. The
position-management remediation sequenced by
`docs/audits/position_management_baseline_2026-06-08.md` Part 4 has been executing:

| Gap | Commits | New surface (no prompt owner) |
|---|---|---|
| G-3 working exits | `2d871b8` | working-exit MARKET fallback in `kernel/orchestrator.py` |
| G-4 lot accounting | `bf3c338` | `src/feelies/portfolio/lot_ledger.py` (FIFO open-lot ledger) + `tests/portfolio/test_lot_ledger.py` |
| G-5 cross-alpha netting | `3b563e4`…`c5c5240` (8 commits) | `src/feelies/execution/portfolio_netter.py`; `enable_portfolio_netting` (`platform_config.py:349`, default False); net-shadow logic in orchestrator; `--emit-net-divergence-jsonl` in `harness/backtest_jsonl.py`/`backtest_runner.py`; `scripts/analyze_net_divergence.py`; `configs/backtest_multialpha*.yaml`; `tests/execution/test_portfolio_netter.py`, `tests/determinism/test_emit_net_divergence_jsonl.py`, `test_analyze_net_divergence.py` |
| G-6 session flatten | `72771aa` | `session_flatten_enabled: bool = True` (**default ON**, `platform_config.py:336-341`) — EOD flatten + entry block in the kernel |
| G-7 sizing | `fdce3c1`, `9bd04d0` | `src/feelies/risk/edge_weighted_sizer.py`; size-divergence shadow stream; `scripts/analyze_size_divergence.py`; `configs/backtest_sizing_tilt.yaml`; `tests/risk/test_edge_weighted_sizer.py`, `tests/determinism/test_emit_size_divergence_jsonl.py`, `test_analyze_size_divergence.py` |
| multi-day RTH fix | `d520167` | per-day session-bound rebind in orchestrator (affects `audit_execution_fills.md` §E session mechanics and `audit_harness_cli.md` multi-day runs) |

Consequences:

1. The 1st pass's P0 ("position decision path unowned") is now an **actively widening**
   gap: ~15+ commits of unaudited capital-path code, including one default-on behavior
   change (G-6) that alters what every backtest and paper run does at the close.
2. `audit_determinism.md`'s enumerated test list is stale — four new
   `tests/determinism/test_emit_*_divergence_jsonl.py` / `test_analyze_*` files exist
   that the prompt's "the five baselines + supporting replays" section cannot see.
3. `audit_harness_cli.md`'s scope misses the new emit streams in `backtest_jsonl.py`
   (file is in scope, but the audit dimensions predate the divergence streams) and the
   two new `analyze_*` scripts.
4. The G-7 sizer scaffold sharpens the 1st-pass ownership ambiguity on
   `risk/position_sizer.py`: there are now **two** sizers, and `audit_risk_engine.md`
   names neither `edge_weighted_sizer.py` nor the divergence-shadow wiring.
5. The 1st-pass observation that the baseline doc's "no EOD flatten exists" is now
   **outdated** — G-6 shipped. Any auditor running `audit_kernel.md` or
   `audit_execution_fills.md` against the prompts' architecture blocks will find
   behavior the spec doesn't predict.

---

## 3. Consolidated Defect Register

| ID | Prompt(s) | Defect | Severity | Status vs 1st pass |
|---|---|---|---|---|
| D-1 | `audit_determinism.md:33,43,64,94` | "five locked parity hashes" — manifest pins **11 across 6 levels** (`parity_manifest.py:65-98`). Undercount invites false "coverage as documented" conclusions in the platform's immune-system audit. | P1 | confirmed, unchanged |
| D-2 | `audit_kernel.md:40-48`, `audit_regime.md:46-55`, `audit_performance.md:39-44`, `audit_signal_alpha.md:44-50` | "M1–M6" presented as contractual architecture; implemented `MicroState` has 16 states incl. `ORDER_SUBMIT/ACK/POSITION_UPDATE/LOG_AND_METRICS` (`micro.py:82-97`) — the fill-reconcile/PnL stages are absent from the canonical diagram. | P1 | confirmed, unchanged |
| D-3 | `audit_kernel.md` (out-of-scope clause), `audit_execution_fills.md:70,93`, `audit_composition.md` | SIGNAL→intent→order decision path unowned: `execution/intent.py` (`SignalPositionTranslator`), orchestrator stop/reverse/flatten/B4/B5/SSR/halt economics, `risk/position_sizer.py` economics. Violates README's one-owner rule for `intent.py`. | **P0** | confirmed, **worse** (see D-4) |
| D-4 | (set-level) | New G-3…G-7 modules with zero prompt ownership: `portfolio_netter.py`, `edge_weighted_sizer.py`, `lot_ledger.py`, `session_flatten_*` (default ON), working-exit fallback, divergence emit streams + scripts + configs + 7 new test files. | **P0** | **new** |
| D-5 | (set-level) | PnL-ledger stage unowned: `portfolio/memory_position_store.py` realized/unrealized math, `strategy_position_store.py` netted aggregate, `storage/{trade_journal,memory_trade_journal}.py`, now also `lot_ledger.py`. `audit_harness_cli.md` audits report-vs-fills reconciliation but treats store math as ground truth. | **P0** | confirmed, broader |
| D-6 | `README.md` coverage map | Nominal-vs-scoped drift: `storage/` → data_ingestion omits trade journals + snapshot stores from the prompt body; `features/` → sensor omits `library.py`/`definition.py`; domain scripts "distributed" but unenumerated; new `analyze_*` scripts and `execution/portfolio_netter.py`, `risk/edge_weighted_sizer.py`, `portfolio/lot_ledger.py` have no row at all. | P1 | confirmed, broader |
| D-7 | `audit_regime.md:38` | Cites "§12 (regime engine)" — §12 of `three_layer_architecture.md` is "Determinism and Parity Requirements" and contains zero occurrences of "regime". Mislabel; the writer/reader contract lives in the regime-detection skill. | P2 | **new** |
| D-8 | `audit_kernel.md:91-93` | Bootstrap test list stale: cites 5 of the 7 files in `tests/bootstrap/` — missing `test_gate_thresholds_wiring.py`, `test_per_alpha_risk_budget_wiring.py`. | P2 | **new** |
| D-9 | `audit_alpha_lifecycle.md` §E (informational) | Not a prompt defect, but an auditor trap: `three_layer_architecture.md:1177-1178` ("If false, only G12-G15 are blocking; G1-G11 warnings logged") contradicts the invariants glossary and the prompt's E.2 ("G9–G16 always block; only G1/G3 downgrade"). The prompt sides with the glossary (canonical); add a one-line note that §9 of the architecture doc is stale so the auditor flags doc drift instead of "resolving" the conflict wrongly. | P2 | **new** |
| D-10 | (set-level, process) | No staleness mechanism: prompts were grounded 2026-06-07 and have no maintenance trigger. 29 commits of drift in 3 days demonstrates the failure mode. The repo already has the precedent (`tests/docs/test_internal_links.py`); a coverage-map completeness check is feasible. | P1 | **new** |

Verified non-defects worth recording: all 11 lifecycle/forensics/research/composition
prompt claims re-checked this pass held (gate-matrix semantics, ledger forensic-only
contract, `tests/forensics/` thinness, `monitoring/health.py` test gap, CPCV/DSR file
paths, cvxpy optimizer scope, `decision_basis_hash` framing, the five platform SMs in
`audit_core_clock_config.md:128` — macro, micro, order, risk-escalation,
alpha-lifecycle — is correct).

---

## 4. Pipeline Coverage Matrix (updated)

| Pipeline Stage | Repo Evidence | Prompt File(s) | Coverage | Change vs 1st pass |
|---|---|---|---|---|
| ingest | `ingestion/*` | `audit_data_ingestion.md` | COMPLETE | — |
| EventLog/replay | `storage/event_log.py`, `event_resequence.py`, `replay_feed.py`, `disk_event_cache.py` | `audit_data_ingestion.md` | COMPLETE | — |
| sensors | `sensors/impl/*`, `registry.py`, `horizon_scheduler.py` | `audit_sensor.md` | COMPLETE | — |
| feature snapshots | `features/aggregator.py`, `storage/feature_snapshot.py` | `audit_sensor.md` | PARTIAL | — |
| regime/gate | `services/regime_engine.py`, `regime_hazard_detector.py`, `signals/regime_gate.py` | `audit_regime.md` | COMPLETE | D-7 mislabel only |
| SIGNAL | `signals/horizon_engine.py`, `alpha/cost_arithmetic.py` | `audit_signal_alpha.md` | COMPLETE | — |
| PORTFOLIO | `composition/*`, `alpha/portfolio_layer_module.py` | `audit_composition.md` | COMPLETE | — |
| **position decision** | `execution/intent.py`, `risk/position_sizer.py` + `edge_weighted_sizer.py`, orchestrator exit/reverse/flatten/gates, **`execution/portfolio_netter.py`**, **G-6 session flatten** | — | **MISSING** | **widened** (D-3, D-4) |
| RISK | `risk/*` | `audit_risk_engine.md` | PARTIAL | new sizer unowned |
| EXECUTION/FILLS | `execution/*fill*`, `cost_model.py`, routers, regulatory, broker, live path | `audit_execution_fills.md`, `audit_live_execution.md` | COMPLETE | multi-day RTH fix unreflected (minor) |
| **PnL** | `portfolio/{memory,strategy}_position_store.py`, **`lot_ledger.py`**, `storage/trade_journal.py`, `harness/backtest_report.py` | reconciliation only (`audit_harness_cli.md`) | **PARTIAL/MISSING** | **widened** (D-5) |
| FORENSICS | `forensics/*`, `alpha/fill_attribution.py` | `audit_forensics.md` | COMPLETE | — |
| LIFECYCLE | `alpha/lifecycle.py`, `promotion_ledger.py`, `layer_validator.py`, `cli/promote.py` | `audit_alpha_lifecycle.md` | COMPLETE | — |
| cross-cutting (kernel/determinism/core/perf/safety/harness) | per README | 6 prompts | COMPLETE | D-1 count error; D-2 diagram; determinism + harness lists now stale for divergence streams |

---

## 5. Minimal Edit Plan (updated priorities)

**P0 — must fix for correctness/coverage**

- **P0-1 (carried, scope expanded).** Create `docs/prompts/audit_position_management.md`
  owning: `execution/intent.py`, `execution/portfolio_netter.py`,
  `risk/position_sizer.py` + `risk/edge_weighted_sizer.py` (sizing economics),
  `portfolio/lot_ledger.py`, orchestrator decision/exit economics (`_check_stop_exit`,
  `_execute_reverse`, `_emergency_flatten_all`, B4/B5 gates, SSR/halt blackout,
  **G-6 session flatten — default ON**, working-exit fallback), and the PnL ledger
  (`memory_position_store.py` / `strategy_position_store.py` realized/unrealized math,
  `storage/{trade_journal,memory_trade_journal}.py`). Anchor to
  `position_management_baseline_2026-06-08.md` + the G-5 netting RFC; cite the new
  tests (`test_portfolio_netter.py`, `test_lot_ledger.py`, `test_edge_weighted_sizer.py`,
  the four divergence determinism tests). A full skeleton was provided in the 1st pass;
  extend its Scope and dimensions with the G-3…G-7 modules above.
- **P0-2 (carried).** Update `README.md`: add the new prompt to the index, run-order
  table (between rows 6 and 7), coverage map, and overlaps table (orchestrator
  decision-economics shared with kernel: kernel owns ordering, position_management owns
  economics; `intent.py` moves out of execution_fills' scope).

**P1 — should fix for coherence/effectiveness**

- **P1-1 (carried).** `audit_determinism.md`: "five" → "eleven across six levels" at
  lines 33, 43, 64, 94; enumerate from `parity_manifest.py`; add the four divergence
  emit/analyze determinism tests to the supporting-replays list.
- **P1-2 (carried).** `audit_kernel.md`: annotate the M1–M6 block as an abbreviation of
  the 16-state `MicroState` enum (`micro.py:82-97`), naming
  `ORDER_SUBMIT/ORDER_ACK/POSITION_UPDATE/LOG_AND_METRICS`; regime/performance/signal
  prompts reference it as "simplified — see audit_kernel.md". Also mention the G-6
  session-flatten and working-exit branches now reachable from the order path.
- **P1-3 (carried).** Resolve `execution/intent.py` and sizing ownership
  (execution_fills → touchpoint; risk_engine keeps limits/regime fail-safe; new prompt
  owns decision/sizing economics incl. `edge_weighted_sizer.py`).
- **P1-4 (new, D-10).** Add a staleness guard: either (a) a README maintenance rule —
  "any new module under `src/feelies/` must get a row in the coverage map in the same
  PR" — or, stronger, (b) a test in `tests/docs/` (precedent:
  `test_internal_links.py`) asserting every `src/feelies/**/*.py` module maps to an
  owning audit in the README table. (b) is what would have caught D-4 automatically.

**P2 — cleanup**

- **P2-1 (D-7).** `audit_regime.md:38`: "§12 (regime engine)" → "§12 (determinism &
  parity — regime-state hash)" or drop the parenthetical.
- **P2-2 (D-8).** `audit_kernel.md`: add `test_gate_thresholds_wiring.py`,
  `test_per_alpha_risk_budget_wiring.py` to the bootstrap test list.
- **P2-3 (D-9).** `audit_alpha_lifecycle.md` §E: add one line — "note:
  `three_layer_architecture.md` §9 (G1-G11 warnings claim) predates the glossary and is
  stale; the glossary is canonical."
- **P2-4 (carried).** `audit_sensor.md`: scope `features/definition.py`, `library.py`,
  `storage/feature_snapshot.py`, and the domain scripts (`sensor_feature_ic.py`,
  `calibrate_hawkes.py`). `audit_harness_cli.md`: add `analyze_net_divergence.py`,
  `analyze_size_divergence.py`, the divergence emit streams, and the new
  `configs/backtest_multialpha*.yaml` / `backtest_sizing_tilt.yaml` to scope.

---

## 6. Final Acceptance Checklist (2nd pass)

| # | Criterion | 1st pass | 2nd pass | Note |
|---|---|---|---|---|
| 1 | Every pipeline stage covered | FAIL | **FAIL (worse)** | position-decision gap widened by G-3…G-7 code |
| 2 | Every stage interface explicit | PARTIAL | PARTIAL | M7–M10 + new netting/flatten branches absent from canonical diagram |
| 3 | No hidden-state assumptions | PASS | PASS | |
| 4 | No lookahead leakage | PASS | PASS | |
| 5 | Replay/EventLog semantics preserved | PASS | PASS | baseline count still wrong (D-1) |
| 6 | SIGNAL/PORTFOLIO/RISK/EXEC responsibilities separated | PARTIAL | PARTIAL | `intent.py` seam unresolved; two sizers now |
| 7 | PnL & forensics traceable to fills/events | PARTIAL | PARTIAL | `lot_ledger.py` adds unowned PnL surface |
| 8 | Lifecycle states explicit | PASS | PASS | |
| 9 | Prompts concise | PASS | PASS | |
| 10 | Prompts non-duplicative | PASS | PASS | one-owner rule violated only at `intent.py` |
| 11 | Prompts operationally usable | PASS | PASS | citation integrity re-verified: 1 miss / ~140, self-hedged |
| 12 | Prompts current w.r.t. HEAD (new this pass) | — | **FAIL** | frozen 2026-06-07; 29-commit drift; no maintenance mechanism (D-10) |

**Gate to full acceptance:** P0-1 + P0-2 flip criteria 1, 6, 7; P1-1…P1-3 flip 2 and 5's
residual; P1-4 flips 12 and prevents recurrence. P2 items are hygiene.

---

## 7. Method Note

Read-only pass: no prompts, source, baselines, or ledger were modified. Evidence
gathered via: full read of all 18 prompt files; `git log` drift analysis since
2026-06-07; existence checks on every test path cited in any prompt (~140); heading
resolution of every `three_layer_architecture.md` § reference; key checks against
`platform.yaml` / `configs/`; direct reads of `tests/determinism/parity_manifest.py`,
`src/feelies/kernel/micro.py`, `src/feelies/core/platform_config.py`; and directory
listings of `tests/forensics/`, `tests/perf/`, `tests/health/`, `tests/bootstrap/`,
`tests/cli/`, `scripts/`. One item remains **UNCLEAR** (carried from pass 1): whether
the single-name SIGNAL path is a permanently supported deployment or transitional —
though the G-3…G-7 investment since 2026-06-08 is strong evidence it is supported,
which justifies keeping D-3/D-4/D-5 at P0.
