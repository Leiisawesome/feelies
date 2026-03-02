---
name: research-workflow
description: >
  Research environment conventions for reproducible quantitative experiments.
  Covers experiment tracking, notebook discipline, the path from exploratory
  analysis to backtest-ready artifacts, and research artifact versioning.
  Use when setting up research infrastructure, designing experiment workflows,
  managing notebook-to-production handoff, tracking hypotheses, or reasoning
  about research reproducibility, experiment provenance, or artifact promotion.
---

# Research Workflow — Experiment Lifecycle

Bridge the gap between exploratory research (notebooks, ad-hoc analysis) and
the production pipeline (backtest engine, feature engine, live execution).
Every insight that reaches capital must pass through a reproducible,
auditable path — no exceptions.

## Core Invariants

1. **Reproducible** — every experiment is re-runnable from versioned inputs and produces identical outputs
2. **Auditable** — every hypothesis, experiment, and conclusion has a traceable record
3. **Separated** — research environment never imports production execution code; production never imports notebook utilities
4. **Promotable** — clear, gated path from notebook exploration to backtest-ready artifact
5. **Disposable** — failed experiments are preserved (for learning) but never promoted

---

## Experiment Lifecycle

```
Hypothesis → Exploration → Formalization → Backtest → Promotion
```

| Phase | Environment | Output | Gate |
|-------|-------------|--------|------|
| Hypothesis | Document (markdown or notebook cell) | Written hypothesis with falsification criteria | Hypothesis registered in experiment log |
| Exploration | Notebooks (Jupyter) | Plots, preliminary statistics, feature prototypes | Evidence justifies proceeding (not confirmation bias) |
| Formalization | Python modules (not notebooks) | Feature definitions, signal logic, parameter specs | Code passes lint, type-check, unit tests |
| Backtest | Backtest engine | PnL curves, integrity checks, sensitivity analysis | All backtest acceptance criteria met (testing-validation skill) |
| Promotion | Promotion pipeline | Versioned strategy artifact | Full promotion gate (testing-validation skill) |

No phase may be skipped. Exploration without a prior hypothesis is
undirected data mining — flag it as such and apply stricter multiple-testing
corrections.

---

## Experiment Tracking

### Experiment Log

Every experiment is registered before execution:

```
ExperimentRecord:
  experiment_id: str (unique, human-readable slug + auto-incrementing number)
  hypothesis_id: str (links to hypothesis registry)
  author: str
  created: datetime
  status: "proposed" | "exploring" | "formalizing" | "backtesting" | "promoted" | "failed" | "abandoned"
  hypothesis: str (the structural mechanism being tested)
  falsification: str (what would disprove this)
  data_version: str (hash of input data used)
  code_ref: str (git SHA or branch of experiment code)
  notebook_path: str (relative path to primary notebook)
  results_summary: str (filled after completion)
  outcome: "supported" | "falsified" | "inconclusive" | null
  promoted_to: str | null (strategy artifact ID if promoted)
```

### Hypothesis Registry

Hypotheses are tracked independently from experiments. Multiple experiments
may test the same hypothesis from different angles.

```
HypothesisRecord:
  hypothesis_id: str
  statement: str (the structural mechanism)
  source: str (what observation or theory motivated this)
  falsification_criteria: list[str]
  related_experiments: list[experiment_id]
  status: "open" | "supported" | "falsified" | "retired"
  confidence: float (0–1, updated as evidence accumulates)
```

A hypothesis is falsified when any registered falsification criterion is met.
A hypothesis is supported (never "proven") when multiple independent
experiments fail to falsify it under varied conditions.

---

## Notebook Conventions

### Structure

Every research notebook follows this structure:

| Section | Content |
|---------|---------|
| Header | Experiment ID, hypothesis, date, author, data version |
| Setup | Imports, data loading, parameter definitions |
| Exploration | Analysis, plots, intermediate findings |
| Results | Summary statistics, key plots, conclusion |
| Decision | Proceed / abandon / revise hypothesis — with justification |

### Rules

1. **No production imports** — notebooks import from a `research` package, never from `core`, `engine`, or `execution` packages
2. **No hardcoded paths** — data paths resolved via a config or environment variable
3. **Pinned data versions** — the data version hash is recorded in the notebook header
4. **Seed everything** — all random operations use explicit seeds recorded in the header
5. **No side effects** — notebooks do not write to production databases, submit orders, or modify shared state
6. **Narrative flow** — markdown cells explain reasoning, not just code; a reader unfamiliar with the hypothesis should understand the notebook end-to-end

### Naming Convention

```
notebooks/
  {YYYY-MM-DD}_{experiment_id}_{short_description}.ipynb
```

Example: `notebooks/2026-03-02_exp042_spread_compression_signal.ipynb`

Old notebooks are never deleted. Failed experiments are kept for reference
and marked with outcome in the experiment log.

---

## Notebook-to-Production Handoff

The most dangerous transition in quantitative research is moving from
"it works in a notebook" to "it works in the engine." This boundary is
managed explicitly.

### What Stays in Notebooks

- Exploratory plots and ad-hoc statistics
- One-off data quality investigations
- Hypothesis brainstorming and preliminary feature prototyping
- Post-hoc analysis of backtest results

### What Gets Formalized

When exploration produces a promising signal or feature, it must be
re-implemented as a proper module before backtesting:

| Notebook Artifact | Formalized As | Destination |
|------------------|--------------|-------------|
| Feature prototype (pandas/numpy) | `FeatureDefinition` with incremental update | Feature engine (feature-engine skill) |
| Signal logic (threshold + condition) | Pure function in signal module | Signal engine |
| Entry/exit rules | Typed strategy config + logic | Strategy module |
| Parameter values | Config file with valid ranges | Strategy artifact |

### Handoff Checklist

Before a notebook artifact is considered formalized:

- [ ] Re-implemented as a standalone module (not copy-pasted from notebook)
- [ ] Unit tests written covering normal, edge, and adversarial cases
- [ ] Incremental computation verified (for features): matches full-recompute
- [ ] No pandas in the hot path — formalized code uses the engine's data structures
- [ ] Parameters externalized to config — no magic numbers in code
- [ ] Type-annotated and linted
- [ ] Reviewed by someone who did not write the notebook

---

## Research Artifact Versioning

### What Is Versioned

| Artifact | Versioning Method | Storage |
|----------|------------------|---------|
| Notebooks | Git (committed with experiment ID in filename) | Repository |
| Experiment log | Append-only structured file (JSON lines) | Repository |
| Hypothesis registry | Append-only structured file | Repository |
| Feature definitions (formalized) | Semantic version in `FeatureDefinition` | Repository (feature-engine) |
| Strategy configs | Versioned alongside strategy code | Repository |
| Data snapshots (for reproduction) | Content-addressed hash | Data store |
| Backtest results | Keyed to `(strategy_version, data_version, engine_version)` | Storage layer |

### Provenance Chain

Every promoted strategy artifact carries a full provenance chain:

```
promoted_artifact:
  strategy_version: git SHA
  originating_experiment: experiment_id
  originating_hypothesis: hypothesis_id
  data_version: hash of training/validation data
  feature_versions: dict[feature_id, version]
  backtest_run_id: deterministic hash of backtest config + data
  notebook_path: path to the exploratory notebook
  promotion_date: datetime
  promoter: author who approved promotion
```

This chain is immutable. If any input changes, a new artifact is created.

---

## Multiple Testing & Overfitting Controls

Research environments are overfitting factories. Guard against it.

### Mandatory Controls

| Control | Implementation |
|---------|---------------|
| Pre-registration | Hypothesis and falsification criteria registered before data analysis |
| Out-of-sample holdout | Minimum 30% of data reserved; never touched during exploration |
| Walk-forward validation | No single in-sample/out-of-sample split; rolling windows |
| Bonferroni / BH correction | Applied when testing multiple features or signals from the same dataset |
| Stability requirement | Signal must work across ≥ 2 volatility regimes and ≥ 2 spread regimes |
| Transaction cost stress | Must survive at 1.5x realistic transaction costs |
| Lottery ticket detection | If signal works only for a narrow parameter range, classify as fragile |

### Red Flags

Reject or flag experiments that exhibit:
- Sharpe ratio that improves monotonically with in-sample optimization
- Signal that works only on a specific date range without structural justification
- Feature importance dominated by a single highly-tuned parameter
- Backtested alpha that vanishes when latency assumptions change by 2x
- "Worked in the notebook" but fails the formalization checklist

---

## Failure Modes

| Failure | Detection | Response |
|---------|-----------|----------|
| Unregistered experiment | Code review; CI check for experiment ID in notebook header | Block promotion; register retroactively |
| Data version mismatch | Hash comparison at notebook load | Alert; re-run with correct data or update experiment record |
| Notebook imports production code | Import linter / CI check | Block merge; refactor to research package |
| Promoted artifact without provenance | Artifact validation at promotion gate | Block deployment; reconstruct provenance or re-run |
| Hypothesis drift (changing hypothesis after seeing results) | Experiment log audit (hypothesis registered before results) | Flag experiment; apply stricter validation |
| Orphaned notebooks (no experiment record) | Periodic scan of notebook directory vs experiment log | Register or archive |

---

## Integration Points

| Dependency | Interface |
|------------|-----------|
| Microstructure Alpha (microstructure-alpha skill) | Research protocol (hypothesis → features → tests → validation → failure criteria) |
| Feature Engine (feature-engine skill) | Formalized feature definitions; versioning; incremental computation contract |
| Backtest Engine (backtest-engine skill) | Backtest execution of formalized strategies; integrity checks |
| Testing & Validation (testing-validation skill) | Acceptance criteria, promotion pipeline, artifact management |
| Data Engineering (data-engineering skill) | Versioned data snapshots for experiment reproducibility |
| System Architect (system-architect skill) | Layer boundaries (research vs production separation) |

The research workflow skill governs the left side of the pipeline — from
idea to backtest-ready artifact. The testing-validation skill governs the
right side — from backtest to live capital. Together they form the full
strategy lifecycle.
