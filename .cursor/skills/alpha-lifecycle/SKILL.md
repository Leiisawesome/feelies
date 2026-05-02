---
name: alpha-lifecycle
description: >
  Alpha promotion, quarantine, and capital-tier lifecycle management
  for the feelies platform. Owns the 5-state `AlphaLifecycle` SM
  (RESEARCH → PAPER → LIVE → QUARANTINED → DECOMMISSIONED) plus the
  F-6 LIVE @ SCALED self-loop, the F-2 declarative gate matrix, the
  F-1 promotion ledger contract, the F-5 three-layer threshold merge,
  and the F-3 read-only operator CLI (`feelies promote ...`). Use
  when wiring promotion / quarantine evidence, defining new gate
  thresholds, debugging ledger schema, building forensic CLI surfaces,
  or extending the gate matrix with new evidence types.
---

# Alpha Lifecycle — Promotion, Quarantine, Capital Tier

Every deployed alpha is a versioned, immutable bundle that flows
through a gated lifecycle from RESEARCH to LIVE @ SCALED, with
fail-safe demotion to QUARANTINED on forensic trigger. The
`AlphaLifecycle` 5-state SM, the F-2 declarative gate matrix, the
F-1 append-only promotion ledger, and the F-3 read-only operator CLI
together form the platform's promotion-evidence backbone — the
operational realization of Inv-3 (evidence over intuition) and
Inv-13 (full provenance).

This skill owns the promotion contract end-to-end. The
testing-validation skill defines the underlying acceptance criteria
that produce evidence; the post-trade-forensics skill consumes
forensic data to build `QuarantineTriggerEvidence`; this skill is
the wiring between them and the lifecycle SM.

## Core Invariants

Inherits Inv-3, Inv-11 (fail-safe), Inv-13 (provenance).
Additionally:

1. **Append-only ledger** — every committed transition writes one
   JSONL line; no in-place mutation; `LEDGER_SCHEMA_VERSION` asserted
   on every read.
2. **Atomic SM + ledger** — ledger writes are wired via
   `StateMachine.on_transition`; a write failure rolls the SM back
   atomically.
3. **Forensic-only consumer** — production code paths must never read
   the ledger to make per-tick decisions (audit `A-DET-02`).
4. **Quarantine fail-safe** — `validate_gate(QUARANTINED, ...)`
   errors are logged at WARNING level but the demotion always
   commits.
5. **Immutable thresholds per alpha** — F-5 three-layer merge runs
   once at registration time; an alpha's effective `GateThresholds`
   are immutable for its lifetime (replay determinism).

---

## The 5-State Lifecycle SM

`feelies.alpha.lifecycle.AlphaLifecycle` (`alpha/lifecycle.py`) wraps
the generic `StateMachine[AlphaLifecycleState]` with gate dispatch
and ledger callbacks.

```
RESEARCH → PAPER → LIVE → QUARANTINED → DECOMMISSIONED
                  └─→ LIVE (self-loop, F-6 capital-tier escalation)
QUARANTINED → PAPER (revalidate)
QUARANTINED → DECOMMISSIONED (retire)
```

Triggers (the `trigger:` string on every ledger entry):

| Trigger | Gate | Method |
|---------|------|--------|
| `promote_to_paper` | RESEARCH_TO_PAPER | `promote_to_paper(...)` |
| `promote_to_live` | PAPER_TO_LIVE | `promote_to_live(...)` |
| `promote_capital_tier` | LIVE_PROMOTE_CAPITAL_TIER | `promote_capital_tier(evidence)` (LIVE → LIVE self-loop) |
| `quarantine` | LIVE_TO_QUARANTINED (consistency-only) | `quarantine(...)` |
| `revalidate_to_paper` | QUARANTINED_TO_PAPER | `revalidate_to_paper(...)` |
| `decommission` | QUARANTINED_TO_DECOMMISSIONED | `decommission(...)` |

`AlphaLifecycle.current_capital_tier: CapitalStageTier | None` scans
`history` backwards from the most recent record to the most recent
transition into LIVE, returning `SCALED` if any
`promote_capital_tier` self-loop is present in that epoch and
`SMALL_CAPITAL` otherwise (returning `None` for non-LIVE states).
Quarantine + revalidate + re-promote starts a new LIVE epoch that
resets to `SMALL_CAPITAL` — operators must re-justify SCALED per
epoch.

### Two Promotion Paths

`AlphaLifecycle.promote_to_paper / promote_to_live /
revalidate_to_paper` accept **either**:

1. **Legacy positional** `PromotionEvidence` (validated via
   `check_*_gate` against `GateRequirements`) — persists `{"evidence":
   {...}}` to ledger metadata.
2. **Keyword-only `structured_evidence: Sequence[object] | None`**
   (validated via `validate_gate(<GateId>, evidences,
   gate_thresholds)` against the F-2 schemas) — persists
   `evidence_to_metadata(*evs)`.

Supplying both or neither raises `ValueError`. The structured path is
the modern surface; legacy is preserved for backwards compatibility.

### Quarantine Fail-Safe (Inv-11)

`AlphaLifecycle.quarantine` is the consistency-only path:
`validate_gate(QUARANTINED, ...)` errors are logged at WARNING level
(spurious-trigger flag) but the demotion **always commits** so a
forensic-layer auto-trigger can never be blocked by the validator.

---

## F-2: Declarative Gate Matrix

`alpha/promotion_evidence.py` exposes the canonical mapping:

```python
GATE_EVIDENCE_REQUIREMENTS: Mapping[GateId, tuple[type, ...]]
```

| `GateId` | Required evidence |
|----------|-------------------|
| `RESEARCH_TO_PAPER` | `ResearchAcceptanceEvidence`, `CPCVEvidence`, `DSREvidence` |
| `PAPER_TO_LIVE` | `PaperWindowEvidence` |
| `LIVE_PROMOTE_CAPITAL_TIER` | `CapitalStageEvidence` |
| `LIVE_TO_QUARANTINED` | `QuarantineTriggerEvidence` (consistency-only) |
| `QUARANTINED_TO_PAPER` | `RevalidationEvidence` |
| `QUARANTINED_TO_DECOMMISSIONED` | (none required) |

### Construction-Time Invariants

`alpha/promotion_evidence.py` enforces three matrix-completeness
checks at module import:

- `_check_matrix_completeness` — every `GateId` member has an entry
- `_check_validator_coverage` — every required type has BOTH a
  registered validator AND a metadata `kind` string
- `_check_reconstructor_coverage` — every metadata kind has a
  registered reconstructor for round-tripping through
  `evidence_to_metadata` / `metadata_to_evidence`

A contributor adding a new gate or evidence type without wiring all
three triggers a hard **import failure** — the platform refuses to
boot.

### Evidence Schemas

| Schema | Carries | Validator |
|--------|---------|-----------|
| `ResearchAcceptanceEvidence` | acceptance-suite outcomes | `validate_research_acceptance` |
| `CPCVEvidence` | fold count (≥ `cpcv_min_folds`), embargo bars, fold sharpes, mean / median sharpe (≥ `cpcv_min_mean_sharpe`), mean PnL, p-value (≤ `cpcv_max_p_value`), `fold_pnl_curves_hash` | `validate_cpcv` (also enforces `len(fold_sharpes) == fold_count`) |
| `DSREvidence` | observed sharpe, trials count (> 0), skew, kurtosis (default 3.0), deflated `dsr` (≥ `dsr_min`), `dsr_p_value` | `validate_dsr` (refuses `trials_count == 0`) |
| `PaperWindowEvidence` | trading days, sample size, slippage residual bps, fill-rate drift pct (signed; **two-sided** band so unexpectedly-good drift also flags), latency KS p, PnL compression ratio (alert on either side of `[0.6, 1.2]`), anomalous event count | `validate_paper_window` |
| `CapitalStageEvidence` | tier (`SMALL_CAPITAL`), deployment days (≥ `small_min_deployment_days`), PnL compression band (`[0.5, 1.0]`), exec-quality envelopes (slippage residual ≤ 2.5 bps, hit-rate residual ≥ −5 pp, fill-rate drift within ±10%) | `validate_capital_stage` |
| `QuarantineTriggerEvidence` | net-alpha negative days, hit-rate residual pp, microstructure metrics breached (tuple), crowding symptoms (tuple), PnL compression 5d | `validate_quarantine_trigger` (does not gate; flags spurious-looking) |
| `RevalidationEvidence` | `hypothesis_re_derived: bool`, OOS walk-forward sharpe (≥ `revalidation_min_oos_sharpe`), `parameter_drift_resolved: bool`, non-empty `human_signoff`, free-form `revalidation_notes` | `validate_revalidation` |

### Defaults (`GateThresholds`)

```python
@dataclass(frozen=True)
class GateThresholds:
    cpcv_min_folds: int = 8
    cpcv_min_mean_sharpe: float = 1.0
    cpcv_max_p_value: float = 0.05
    dsr_min: float = 1.0
    revalidation_min_oos_sharpe: float = 1.0
    small_min_deployment_days: int = 10
    # ... plus paper-window / capital-stage / quarantine fields
```

---

## F-5: Three-Layer Threshold Merge

The default `GateThresholds` consumed by the structured-evidence
path is the result of a three-layer merge (lowest → highest):

1. **Skill-pinned** `GateThresholds()` defaults
2. **Operator-wide** `platform.yaml: gate_thresholds:` overrides
3. **Per-alpha** `promotion: { gate_thresholds: { ... } }` overrides
   in the alpha YAML (stored on `AlphaManifest.gate_thresholds_overrides`)

Implementation:

```python
# at AlphaRegistry registration time:
registry_base = _build_platform_gate_thresholds(config)
                # = apply_gate_thresholds_overrides(GateThresholds(),
                #                                   config.gate_thresholds_overrides)
effective = apply_gate_thresholds_overrides(registry_base,
                                            manifest.gate_thresholds_overrides)
```

The merge is **non-mutating** (`dataclasses.replace`) and runs once
at registration time — replay determinism preserved
(audit `A-DET-02`).

The override surface (`parse_gate_thresholds_overrides(raw)`,
`apply_gate_thresholds_overrides(base, overrides)`) is shared
between platform and per-alpha entry points, so the YAML grammar is
identical regardless of source. Cross-field invariants
(e.g., `min ≤ max`) are deferred to the F-2 validators — the
override layer is purely structural.

The grammar enforces:
- Field-name validation against the `GateThresholds` schema
- Scalar-type coercion with bool-not-int strictness
- No string-to-number auto-parsing

---

## F-1: Promotion Ledger

`alpha/promotion_ledger.py` provides an append-only JSONL audit log
recording every committed lifecycle transition.

```python
@dataclass(frozen=True)
class PromotionLedgerEntry:
    schema_version: int             # LEDGER_SCHEMA_VERSION
    alpha_id: str
    from_state: str
    to_state: str
    trigger: str                    # "promote_to_paper" | "promote_capital_tier" | ...
    timestamp_ns: int               # clock-derived (Inv-10)
    correlation_id: str
    metadata: dict[str, Any]        # legacy {"evidence": ...} or F-2 evidence_to_metadata(*evs)
```

Wired into `AlphaLifecycle` via a `StateMachine.on_transition`
callback so a ledger-write failure rolls the SM back atomically
(Inv-13 + Inv-11).

The ledger is constructed from the optional
`PlatformConfig.promotion_ledger_path` field. Backtest deployments
typically disable per-alpha lifecycle tracking via `registry_clock=None`
and leave the file untouched.

### Forensic-Only Consumer Contract

Production code paths **must never** read the ledger to make per-tick
decisions, so ledger presence does not perturb replay determinism.
Allowed consumers:

- F-3 operator CLI (read-only)
- Workstream-C CPCV+DSR gate (reads the ledger for evidence and history)
- Forensic dashboards (offline)

Forbidden consumers: orchestrator, risk engine, sensors, signals,
composition, execution.

---

## F-3: Operator CLI (`feelies promote`)

`cli/promote.py` provides the read-only operator surface, registered
as `[project.scripts] feelies = "feelies.cli.main:main"` in
`pyproject.toml` (equivalently `python -m feelies` or `python -m
feelies.cli`).

| Subcommand | Purpose |
|------------|---------|
| `inspect <alpha_id>` | Per-alpha chronological timeline (text or `--json`); renders `LIVE @ <tier>` for live alphas; renders `LIVE @ SMALL_CAPITAL → LIVE @ SCALED` self-loops |
| `list` | Every alpha + current state + transition count; live alphas show `LIVE @ <tier>` |
| `replay-evidence <alpha_id>` | Re-run `validate_gate` against every F-2-shaped evidence package recorded for the alpha against today's `GateThresholds`. Distinguishes OK / SKIPPED / FAIL transitions for legacy reason-only metadata vs F-2-shaped metadata vs evidence that no longer satisfies current thresholds. Exit code 3 on validation failure |
| `validate` | Preflight ledger file (parse + `LEDGER_SCHEMA_VERSION` check) |
| `gate-matrix` | Render the F-2 declarative gate matrix |

All accept:
- `--ledger PATH` (explicit)
- `--config PATH` (loads `PlatformConfig` and resolves
  `promotion_ledger_path`)
- `--json` for stable machine-readable output

### Pinned Exit Codes

| Code | Meaning |
|------|---------|
| `0` | OK |
| `1` | User error (missing args / non-existent file / config without `promotion_ledger_path`) |
| `2` | Data error (corrupt ledger / malformed YAML / schema-version mismatch) |
| `3` | Validation failure (`replay-evidence` found gate violations) |

CI integrations chain these safely.

### Read-Only Discipline

The CLI **never writes** to the ledger and **never imports**
orchestrator / risk-engine production code, preserving Inv-5 replay
determinism (audit `A-DET-02`) and Inv-10 clock-abstraction
(timestamps are *rendered* via `datetime.fromtimestamp` from
ns-since-epoch the writer captured — the CLI itself takes no
wall-clock readings).

### F-6 CLI Extensions

The F-6 capital-tier escalation extended the CLI:

- `_STATE_PAIR_TO_GATE` maps `("LIVE", "LIVE") → GateId.LIVE_PROMOTE_CAPITAL_TIER`
  so `replay-evidence` validates round-tripped `CapitalStageEvidence`
  against today's thresholds
- `inspect` renders a `tier=SCALED` / `tier=SMALL_CAPITAL` suffix in
  the per-alpha header and formats the self-loop arrow as
  `LIVE @ SMALL_CAPITAL → LIVE @ SCALED`
- `list` renders the state column as `LIVE @ <tier>` for live alphas
- JSON outputs of both subcommands carry a top-level
  `current_capital_tier` field

---

## F-6: Capital-Tier Escalation

The LIVE @ SMALL_CAPITAL → LIVE @ SCALED escalation is wired as a
`LIVE → LIVE` state-machine self-loop on `AlphaLifecycle` —
`_LIFECYCLE_TRANSITIONS[LIVE]` now contains `LIVE` itself. The
lifecycle state name does not change but the F-1 ledger receives a
metadata-only entry whose `trigger == PROMOTE_CAPITAL_TIER_TRIGGER`
(the constant `"promote_capital_tier"` defined in
`promotion_evidence.py` and re-exported from `feelies.alpha`)
distinguishes the escalation from the LIVE → QUARANTINED demotion
(both share `from_state == "LIVE"`).

`PROMOTE_CAPITAL_TIER_TRIGGER` lives in `promotion_evidence.py`
(re-exported from `feelies.alpha`) rather than in
`feelies.alpha.lifecycle` so the writer (lifecycle) and readers (CLI
/ forensics) share a single source of truth without re-introducing a
layering edge.

The `AlphaLifecycle.promote_capital_tier(evidence)` method:

1. Validates `validate_gate(GateId.LIVE_PROMOTE_CAPITAL_TIER,
   [evidence], thresholds)` against per-alpha resolved thresholds
   (the F-5 three-layer merge)
2. Issues a `LIVE → LIVE` state-machine self-loop with `trigger ==
   PROMOTE_CAPITAL_TIER_TRIGGER`
3. Persists the F-2 metadata-only audit entry

`AlphaRegistry.promote_capital_tier(alpha_id, evidence)` is the
delegate-via-registry surface for CLI / orchestrator-adjacent
callers.

### Capital-Tier Field

`AlphaLifecycle.current_capital_tier: CapitalStageTier | None`
inspects history. Returns:
- `SCALED` if the most recent LIVE epoch contains a
  `promote_capital_tier` self-loop
- `SMALL_CAPITAL` if the most recent LIVE epoch has no self-loop
- `None` for non-LIVE states

Quarantine + revalidate + re-promote starts a new LIVE epoch that
resets to `SMALL_CAPITAL` — operators must re-justify the SCALED
escalation per epoch.

---

## End-to-End Promotion Workflow

```
1. RESEARCH:
   Author runs CPCV + DSR + research-acceptance suite (Workstream C).
   Operator invokes:
     AlphaLifecycle.promote_to_paper(
         structured_evidence=[ResearchAcceptanceEvidence(...),
                              CPCVEvidence(...),
                              DSREvidence(...)])
   → Gate dispatch → validate_gate(RESEARCH_TO_PAPER, ...)
   → On success: SM transitions RESEARCH → PAPER
                ; ledger entry written with F-2 metadata
                ; trigger="promote_to_paper"

2. PAPER:
   ≥ 5 trading days; collect PaperWindowEvidence from sim-vs-live
   divergence metrics (testing-validation skill).
   Operator invokes:
     AlphaLifecycle.promote_to_live(
         structured_evidence=[PaperWindowEvidence(...)])
   → SM transitions PAPER → LIVE @ SMALL_CAPITAL
                ; ledger entry; trigger="promote_to_live"

3. LIVE @ SMALL_CAPITAL:
   ≤ 1% target allocation; ≥ 10 trading days.
   Collect CapitalStageEvidence (PnL compression in [0.5, 1.0],
   exec quality nominal).
   Operator invokes:
     AlphaLifecycle.promote_capital_tier(CapitalStageEvidence(...))
   → SM self-loop LIVE → LIVE
                ; ledger entry; trigger="promote_capital_tier"
                ; current_capital_tier flips to SCALED

4. LIVE @ SCALED:
   Target allocation. Continuous forensic monitoring
   (post-trade-forensics skill) emits QuarantineTriggerEvidence on
   threshold breach. Auto-trigger:
     AlphaLifecycle.quarantine(structured_evidence=[QuarantineTriggerEvidence(...)])
   → SM transitions LIVE → QUARANTINED (always commits, fail-safe)
                ; ledger entry; trigger="quarantine"

5. QUARANTINED:
   Continue paper-mode signal generation. Hypothesis revalidation
   produces RevalidationEvidence (with non-empty human_signoff).
   Operator invokes:
     AlphaLifecycle.revalidate_to_paper(
         structured_evidence=[RevalidationEvidence(...)])
   → SM transitions QUARANTINED → PAPER
                ; new LIVE epoch starts on next promotion (resets tier
                  to SMALL_CAPITAL)
   OR retire:
     AlphaLifecycle.decommission(...)
   → SM transitions QUARANTINED → DECOMMISSIONED (terminal)
```

---

## Failure Modes

| Failure | Detection | Response |
|---------|-----------|----------|
| Gate-matrix incomplete | `_check_matrix_completeness` at import | Hard import failure |
| Validator missing | `_check_validator_coverage` at import | Hard import failure |
| Reconstructor missing | `_check_reconstructor_coverage` at import | Hard import failure |
| Ledger-write failure | `StateMachine.on_transition` callback raises | Atomic SM rollback (Inv-13 + Inv-11) |
| Ledger schema-version mismatch | Read-time check | Bail with exit code 2 |
| Threshold-override grammar violation | `parse_gate_thresholds_overrides` | Reject alpha load |
| `quarantine` evidence flagged spurious | `validate_quarantine_trigger` | WARNING; demotion still commits |
| `RevalidationEvidence.human_signoff` empty | `validate_revalidation` | Reject re-promotion |

---

## Integration Points

| Dependency | Interface |
|------------|-----------|
| Testing & Validation | F-2 evidence schemas; gate-matrix dispatcher; sim-vs-live divergence metrics produce `PaperWindowEvidence` |
| Post-Trade Forensics | Quarantine auto-trigger via `QuarantineTriggerEvidence`; revalidation surface |
| System Architect | `AlphaLifecycle` SM is one of the platform's secondary state machines; `Clock`-derived timestamps for ledger entries |
| Risk Engine | Capital-tier scaling; quarantined alphas produce no live orders |
| Composition Layer | PORTFOLIO alphas obey the same lifecycle |
| Microstructure Alpha | SIGNAL alphas obey the same lifecycle |
| Storage Layer | Promotion ledger persistence (JSONL) |
| Operator (human) | F-3 CLI surface; `human_signoff` on revalidation |

The alpha lifecycle is the **only** path that grants an alpha access
to capital. No alpha gets to LIVE without all required evidence
clearing the F-2 gate; no alpha moves from LIVE @ SMALL_CAPITAL to
SCALED without demonstrated execution quality; no alpha lifts
quarantine without an explicit human sign-off. The platform
**defaults to deny**.
