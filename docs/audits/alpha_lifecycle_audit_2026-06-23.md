# Alpha Lifecycle / Promotion / Capital-Tier Audit — 2026-06-23

**Scope:** promotion / quarantine / capital-tier machinery — the gate between research and
capital. Read-only, evidence-based. No production code or ledger was modified.

**Method:** static read of all in-scope modules, plus read-only repros (scratch ledger,
direct handler calls) and the targeted test suites. All `path:line` citations are against
the working tree at branch `claude/cool-mccarthy-po75qg`.

**Read-only checks executed**

| Check | Result |
|-------|--------|
| `pytest tests/alpha/test_lifecycle.py test_lifecycle_f6.py test_promotion_evidence.py test_promotion_ledger.py` | **211 passed** |
| `pytest tests/alpha/test_layer_validator_g2_g13.py test_gate_g16.py test_registry_per_alpha_thresholds.py tests/cli/test_promote_cli*.py tests/bootstrap/test_gate_thresholds_wiring.py` | **146 passed** (only after installing the `ib` extra — see CLI-1) |
| `feelies promote gate-matrix --json` (console script) | **FAILED to import** (`ModuleNotFoundError: ibapi`) — see CLI-1; matrix rendered directly from `GATE_EVIDENCE_REQUIREMENTS` instead |

Legend for classification: **[BUG]** implementation defect · **[LIM]** documented
limitation · **[DESIGN]** intentional design (flagged where it carries governance risk).

---

## 1. Executive summary

Top provenance / bypass risks first.

1. **[P0/DESIGN] Per-alpha `gate_thresholds` overrides can loosen any gate below the
   platform floor with no authorization check.** The F-5 merge is strictly "last wins"
   (`apply_gate_thresholds_overrides` via `dataclasses.replace`,
   `promotion_evidence.py:1206`), order skill → platform.yaml → per-alpha
   (`registry.py:122`, `bootstrap.py:328`). Verified: a per-alpha override drops
   `cpcv_min_mean_sharpe` from a platform floor of `2.0` to `0.1`, and `dsr_min` from
   `1.5` to `0.0`, with no error. Because alpha YAMLs are "the external quant lab's
   deliverables" (`loader.py:1`), the entity being governed can lower its own promotion
   bar relative to operator policy. Inv-11 ("loosening requires human re-authorization")
   is satisfied only in the weak sense that the YAML is git-committed.
2. **[P1/BUG] `replay-evidence` reports a false `FAIL` (exit 3) for every
   quarantine-with-evidence entry.** `AlphaLifecycle.quarantine` writes
   `{"reason", "schema_version", "<kind>"}` (`lifecycle.py:416,430`) but
   `metadata_to_evidence` rejects any non-kind, non-`schema_version` key
   (`promotion_evidence.py:1076`). Verified end-to-end through the real CLI handler:
   `error: could not reconstruct evidence: metadata carries unknown kind(s) ['reason']`
   → `EXIT CODE: 3`. The documented forensic verb mislabels healthy provenance as a
   validation failure.
3. **[P1/LIM] The effective `GateThresholds` used at promotion time is never recorded in
   the ledger.** `evidence_to_metadata` persists only `schema_version` + evidence kinds
   (`promotion_evidence.py:877`); thresholds are not captured. Consequences: (a) a
   promotion is not reproducible from the ledger alone (Inv-13 "config change → author +
   rollback path" gap), and (b) `replay-evidence` re-validates against raw skill defaults
   `GateThresholds()` (`promote.py:663`), which matches neither the promotion-time merged
   thresholds nor current platform policy.
4. **[P1/BUG] The read-only operator CLI is not import-isolated from production code and
   is unusable without the optional `ib` extra.** `cli/main.py:30` eagerly imports the
   sibling `backtest` subcommand, which transitively imports
   `harness → bootstrap → execution.paper_backend → broker.ib → ibapi`. So invoking any
   `feelies promote …` command imports the orchestrator/risk/execution/broker stack —
   contradicting the "never imports orchestrator / risk-engine production code" contract
   (`promote.py:12`, glossary `operator CLI`) — and fails outright when `ibapi` is absent.
5. **[P1/LIM] Promotion evidence is self-asserted with no binding to a reproducible run.**
   The validators check submitted values against thresholds
   (`promotion_evidence.py:433–731`); nothing ties those values to an actual CPCV/DSR run.
   Only `CPCVEvidence.fold_pnl_curves_hash` carries an artefact pointer, and it is
   optional and never verified. Inv-13's "reproducible chain" is therefore trust-on-submit.
6. **[GOOD] Forensic-only contract holds (Inv-5).** No production per-tick path reads the
   promotion ledger. The orchestrator's `ledger` references are `LotLedger` /
   `FillAttributionLedger` (`kernel/orchestrator.py:157,772`), not `PromotionLedger`. The
   only readers are the read-only CLI (`cli/promote.py`) and bootstrap wiring
   (`bootstrap.py:314`).
7. **[GOOD] SM + ledger transitions are atomic (Inv-13).** Callbacks fire *before* history
   /state commit (`state_machine.py:161–166`). Verified: a ledger whose `append` raises
   leaves the SM in `RESEARCH` with empty history (atomic rollback).
8. **[GOOD] Gate-matrix completeness is enforced at import.**
   `_check_matrix_completeness` / `_check_validator_coverage` /
   `_check_reconstructor_coverage` run at module import (`promotion_evidence.py:1279–1281`);
   all six `GateId` members are wired and every required type has a validator + kind + reconstructor.
9. **[GOOD] `enforce_layer_gates` matches the canonical glossary, not the stale doc.** Only
   G1 and G3 route through `_softly` (`layer_validator.py:313,321`); G9–G16 are always
   blocking. `docs/three_layer_architecture.md` §9 ("only G12–G15 blocking; G1–G11
   warnings") is **stale doc drift** — flagged, not resolved in the doc's favor.
10. **[P2/BUG] `LEDGER_SCHEMA_VERSION` is not "asserted on every read."** `entries()` and
    `from_json_line` never compare the per-line version (`promotion_ledger.py:106–143,202`);
    only the `validate` subcommand checks it (`promote.py:721`). `inspect` / `list` /
    `replay-evidence` read unversioned. The SKILL claim of per-read assertion is inaccurate.
11. **[P2/LIM] The ledger has no integrity hash/chain.** Append-only is writer discipline,
    not medium-enforced; a well-formed in-place edit of a metadata value round-trips
    cleanly (only malformed JSON is detected, `promotion_ledger.py:108–143`). Tamper-
    evidence is limited.
12. **[P2/BUG] `from_yaml` silently ignores unknown top-level config keys** (it is all
    `data.get(...)`, `platform_config.py:1207+`). A typo'd `promotion_ledger_path` or
    `enforce_trend_mechanism` is silently dropped — the former silently disables the
    provenance ledger.
13. **[P2/LIM] Library-level strict-mode default disagrees with platform default.**
    `LayerValidator`/`AlphaLoader` default `enforce_trend_mechanism=False`
    (`layer_validator.py:237`, `loader.py:267`) while `PlatformConfig` defaults `True`
    (`platform_config.py:527`). A directly-constructed loader is permissive; only the
    bootstrap path is strict. (Shipped `platform.yaml:23` itself pins `false` for the v0.2
    baseline — consistent with the documented known-failing acceptance tests.)
14. **[P2/LIM] `restore()` sets lifecycle state with no gate and no ledger entry.**
    `_restore_to_checkpoint` writes `self._sm._state` directly (`lifecycle.py:799`); the
    BT-13 research cap is re-checked (`lifecycle.py:754`) but no evidence/ledger record is
    produced. A checkpoint blob is a gate-free state-set path; trust is anchored in the
    checkpoint store.
15. **[P2/BUG] `validate_gate` silently ignores extra, supported-but-not-required
    evidence** (`promotion_evidence.py:854–867`): it is neither flagged nor validated, yet
    `evidence_to_metadata` still writes it to the ledger — a quiet footgun, not a bypass.

---

## 2. Gate matrix snapshot

Rendered from `GATE_EVIDENCE_REQUIREMENTS` (`promotion_evidence.py:743`), validators
(`:767`), kinds (`:781`). All six `GateId` members present; completeness checks pass at
import.

| `GateId` (value) | Lifecycle edge | Required evidence | Validator | metadata `kind` |
|---|---|---|---|---|
| `research_to_paper` | RESEARCH→PAPER | `ResearchAcceptanceEvidence` | `validate_research_acceptance` | `research_acceptance` |
| `paper_to_live` | PAPER→LIVE | `PaperWindowEvidence`, `CPCVEvidence`, `DSREvidence` | `validate_paper_window` / `validate_cpcv` / `validate_dsr` | `paper_window` / `cpcv` / `dsr` |
| `live_promote_capital_tier` | LIVE→LIVE (self-loop) | `CapitalStageEvidence` | `validate_capital_stage` | `capital_stage` |
| `live_to_quarantined` | LIVE→QUARANTINED | `QuarantineTriggerEvidence` *(consistency-only)* | `validate_quarantine_trigger` | `quarantine_trigger` |
| `quarantined_to_paper` | QUARANTINED→PAPER | `RevalidationEvidence` | `validate_revalidation` | `revalidation` |
| `quarantined_to_decommissioned` | QUARANTINED→DECOMMISSIONED | *(none)* | — | — |

### Default `GateThresholds` (`promotion_evidence.py:349`)

| Field | Default | | Field | Default |
|---|---|---|---|---|
| `research_min_branch_coverage_pct` | 90.0 | | `cpcv_min_folds` | 8 |
| `research_min_line_coverage_pct` | 80.0 | | `cpcv_min_mean_sharpe` | 1.0 |
| `research_min_fault_injection_pass_pct` | 100.0 | | `cpcv_max_p_value` | 0.05 |
| `paper_min_trading_days` | 5 | | `dsr_min` | 1.0 |
| `paper_max_slippage_residual_bps` | 1.5 | | `dsr_max_p_value` | 0.05 |
| `paper_min_latency_ks_p` | 0.10 | | `small_min_deployment_days` | 10 |
| `paper_min_pnl_compression_ratio` | 0.6 | | `small_min_pnl_compression_ratio` | 0.5 |
| `paper_max_pnl_compression_ratio` | 1.2 | | `small_max_pnl_compression_ratio` | 1.0 |
| `paper_max_anomalous_events` | 0 | | `small_max_slippage_residual_bps` | 2.5 |
| `quarantine_max_net_alpha_negative_days` | 10 | | `small_max_hit_rate_residual_pp` | −5.0 |
| `quarantine_max_hit_rate_residual_pp` | −15.0 | | `small_max_fill_rate_drift_pct` | 10.0 |
| `quarantine_max_pnl_compression_ratio_5d` | 0.3 | | `revalidation_min_oos_sharpe` | 1.0 |

---

## 3. Lifecycle SM audit

### A.1 Transition table & illegal-transition rejection — **PASS**

`_LIFECYCLE_TRANSITIONS` (`lifecycle.py:60–80`):

| from | allowed to | trigger / gate |
|---|---|---|
| RESEARCH | {PAPER} | `pass_paper_gate` / RESEARCH_TO_PAPER |
| PAPER | {LIVE} | `pass_live_gate` / PAPER_TO_LIVE |
| LIVE | {LIVE, QUARANTINED} | `promote_capital_tier` / LIVE_PROMOTE_CAPITAL_TIER **·** `edge_decay_detected` / LIVE_TO_QUARANTINED |
| QUARANTINED | {PAPER, DECOMMISSIONED} | `revalidation_passed` / QUARANTINED_TO_PAPER **·** `decommissioned` / (no gate) |
| DECOMMISSIONED | {} (terminal) | — |

Illegal transitions raise `IllegalTransition` via `can_transition` (`state_machine.py:124,
148`); construction enforces enum completeness (`state_machine.py:93–101`). RESEARCH→LIVE,
PAPER→QUARANTINED, etc. are rejected.

**F-6 self-loop vs demotion (same `from_state == "LIVE"`)** — distinguished by `trigger`,
not by state pair. The writer stamps `PROMOTE_CAPITAL_TIER_TRIGGER` on the self-loop
(`lifecycle.py:539`); the CLI resolves the pair to a gate *only* when the trigger matches
(`promote.py:251–256`). Correct and consistent with the glossary.

Minor inconsistency **[LIM]**: `promote_capital_tier` returns descriptive error strings for
wrong state / already-SCALED (`lifecycle.py:513–525`), but `quarantine`/`decommission` rely
on `IllegalTransition` raising from non-LIVE/non-QUARANTINED states (no graceful error
list). Acceptable since those are auto/operator paths, but the surfaces differ.

### A.2 `current_capital_tier` vs ledger replay — **PASS, with a latent caveat**

The SM scans `history` in **append order** backward, returning `SCALED` on a
`PROMOTE_CAPITAL_TIER_TRIGGER`, else `SMALL_CAPITAL` at the LIVE-entry edge
(`lifecycle.py:596–616`). Quarantine→revalidate→re-promote starts a new LIVE epoch (the
`to_state==LIVE and from_state!=LIVE` guard at `:603` is hit first) → resets to
`SMALL_CAPITAL`. Confirmed correct.

The CLI mirror `_capital_tier_from_entries` (`promote.py:264–298`) computes the same result
but first **sorts by `timestamp_ns`** (`:289`), whereas the SM uses raw history order. These
agree only under a monotonic clock (ties preserved by stable sort). The glossary claims the
two agree "byte-for-byte"; they are structurally different algorithms and would diverge if
ledger timestamps were ever non-monotonic relative to append order. **[LIM]** — latent, not
currently exploitable (clock is monotonic; `restore()` does not write ledger entries).

### A.3 Atomicity on ledger-write failure — **PASS (Inv-13)**

`StateMachine.transition` validates → builds record → fires callbacks → *then* appends
history and updates state (`state_machine.py:148–166`). `_record_to_ledger`
(`lifecycle.py:678–693`) is the only callback; if `ledger.append` raises, the exception
propagates before commit. **Repro:** a ledger whose `append` raises `OSError` left the SM at
`RESEARCH` with `history len: 0` ("atomic rollback"). Note the on-disk file may still carry
a torn trailing line on a mid-write failure (`promotion_ledger.py:187–198`), surfaced later
as a corrupt-line `ValueError` — the SM rollback is clean; the file is self-healing only via
loud read-time failure.

---

## 4. Gate validation audit

### B.1 Matrix / validator / reconstructor completeness — **PASS**

Three import-time checks (`promotion_evidence.py:1228–1281`) guarantee every `GateId` has a
matrix entry, every required type has a validator **and** a kind, and every kind has a
reconstructor. A new gate/evidence type without full wiring is a hard import failure
(`testing-validation` property "Gate-matrix completeness"). Verified import succeeds and the
matrix renders all six gates.

### B.2 `validate_gate` ordering — **PASS, one footgun**

`validate_gate` (`promotion_evidence.py:805–869`) indexes evidence by type, rejecting
unsupported types (`:839`) and duplicates (`:846`), then reports missing-required (`:854`),
then runs per-type validators (`:861`). Order is correct: structural rejections precede
per-evidence errors.

**[P2/BUG] Extra supported-but-not-required evidence is silently dropped** — e.g. a
`DSREvidence` passed to RESEARCH_TO_PAPER is added to `by_type`, never matched against
`required`, so never validated or flagged, yet `evidence_to_metadata(*structured_evidence)`
(`lifecycle.py:672`) still writes it to the ledger. Not a bypass (required evidence is still
enforced), but a quiet correctness gap.

### B.3 Empty / self-asserted evidence; XOR enforcement — **PASS / LIM**

- **XOR enforced.** `_select_evidence` raises `ValueError` for both-or-neither
  (`lifecycle.py:639–650`). `promote_capital_tier` is structured-only (no legacy shape,
  `lifecycle.py:481–543`). Confirmed by tests.
- **Empty evidence fails real gates.** Every promote gate has non-empty `required`, so
  `structured_evidence=[]` yields missing-required errors. Only QUARANTINED_TO_DECOMMISSIONED
  has empty requirements, and `decommission` does not call `validate_gate` at all
  (`lifecycle.py:545–557`) — intentional (free-form reason is the audit substrate).
- **[P1/LIM] Self-asserted evidence.** `ResearchAcceptanceEvidence(schema_valid=True,
  determinism_replay_passed=True, branch_coverage_pct=100, …)` passes
  `validate_research_acceptance` with no link to a real run. Gates validate *values*, not
  *provenance of values*. Only CPCV carries an (optional, unchecked) `fold_pnl_curves_hash`.

---

## 5. Threshold merge audit (F-5)

### C.1 Determinism — **PASS**

- Non-mutating: `apply_gate_thresholds_overrides` → `dataclasses.replace`
  (`promotion_evidence.py:1206–1220`); `GateThresholds` is `frozen`
  (`promotion_evidence.py:349`).
- Run once at registration: `AlphaRegistry.register` → `_resolve_gate_thresholds`
  (`registry.py:111,122–150`); the resolved value is frozen onto the `AlphaLifecycle` at
  construction and never re-resolved at promotion time. Platform layer is built once in
  bootstrap (`_build_platform_gate_thresholds`, `bootstrap.py:816–838`).
- Order-independent result (pure field replacement); YAML dict order does not affect output.

### C.2 Grammar parity — **PASS**

Both entry points share `parse_gate_thresholds_overrides` (`promotion_evidence.py:1124`):
per-alpha via `loader._parse_promotion_block` (`loader.py:1215–1270`) and platform via
`PlatformConfig._parse_gate_thresholds_block` (`platform_config.py:1598–1638`). Strict
coercion in `_coerce_threshold_value` (`promotion_evidence.py:1176–1203`): `bool` is **not**
`int` (`:1190`), strings are **not** parsed (`:1200`), unknown field names raise (`:1161`).
Identical grammar regardless of source.

### C.3 Unauthorized loosening — **P0 / DESIGN (governance gap)**

The merge is "more-specific wins" with **no floor/ceiling concept and no authorization
check.** Per-alpha (highest precedence) can lower any threshold the operator set in
platform.yaml. **Repro:**

```
skill default cpcv_min_mean_sharpe    : 1.0
platform.yaml floor cpcv_min_mean_sharpe: 2.0
after per-alpha override              : 0.1   <-- below platform floor, no error
dsr_min: skill=1.00 platform_floor=1.50 per_alpha=0.00
```

The skill documents this as intentional ("lowest → highest … purely structural",
SKILL.md F-5). It becomes a **P0 governance violation under the documented external-author
threat model** (`loader.py:1` — alpha YAMLs are external quant-lab deliverables): the party
with incentive to be promoted can lower its own bar relative to operator policy, and
(per finding #3) the loosened threshold is never recorded in the ledger, so a ledger-only
audit cannot see the policy that was actually applied. Inv-11 ("loosening requires human
re-authorization") is met only by git review of the YAML, with no separation of duties from
the platform operator.

---

## 6. Ledger audit (Inv-13, Inv-5)

### D.1 Append-only & schema-on-read — **PASS (append) / P2 BUG (read)**

`PromotionLedger` exposes only `append` (open mode `"a"`, `promotion_ledger.py:187–198`) and
read methods (`entries`, `entries_for`, `latest_for`, `__len__`, `__iter__`); there is **no**
rewrite/truncate/clear path. Append-only across re-opens is tested
(`test_promotion_ledger.py::test_append_only_across_reopens`).

**[P2/BUG]** `LEDGER_SCHEMA_VERSION` is *not* asserted on read. `from_json_line` stores the
version verbatim without comparison (`promotion_ledger.py:134–143`); `entries()` does not
check it (`:202–218`). Only the explicit `validate` subcommand compares
(`promote.py:721`). The SKILL's "asserted on every read" is inaccurate.

**[P2/LIM]** No per-line integrity hash / chain — a syntactically valid in-place mutation of
a metadata value (e.g. a recorded fold sharpe, or `from_state`) is undetectable; only
malformed JSON / missing fields are caught (`promotion_ledger.py:108–143`).

### D.2 Round-trip — **P1 BUG for the quarantine shape; PASS elsewhere**

`_evidence_to_jsonable` (`promotion_evidence.py:919`) flattens enum→value, tuple→list; all
seven evidence dataclasses are flat scalars/tuples, so promote/capital/revalidation shapes
round-trip losslessly (verified for `CapitalStageEvidence`). Legacy `{"evidence": {...}}`
(no `schema_version`) correctly returns `[]` → SKIPPED (`promotion_evidence.py:1055–1057`).

**[P1/BUG] The quarantine-with-evidence shape does NOT round-trip.**
`AlphaLifecycle.quarantine` writes `{"reason", "schema_version", "quarantine_trigger"}`
(`lifecycle.py:416,430`), but `metadata_to_evidence` raises on any key that is neither
`schema_version` nor a known kind (`promotion_evidence.py:1076–1081`). End-to-end repro via
the real CLI handler on a scratch ledger:

```
#02  LIVE->QUARANTINED  gate=live_to_quarantined  [FAIL]
      error: could not reconstruct evidence: metadata carries unknown kind(s) ['reason']
EXIT CODE: 3
```

So any alpha ever quarantined with structured evidence makes `feelies promote
replay-evidence` exit `3` (VALIDATION_FAILED) — a false provenance alarm. Writer and reader
contracts disagree about the `reason` co-key.

### D.3 Forensic-only contract — **PASS (Inv-5 / A-DET-02)**

Grep of `src/feelies` for ledger reads (`.entries()`, `entries_for`, `metadata_to_evidence`,
`PromotionLedger(`) yields only: `cli/promote.py` (read-only CLI), `bootstrap.py` (construct
+ wire), `lifecycle.py` (write callback), `promotion_evidence.py` / `promotion_ledger.py`
(definitions). The `kernel/orchestrator.py` hit is a **false positive** — it references
`LotLedger` / `FillAttributionLedger` (`orchestrator.py:157,772,5611`), not the promotion
ledger. No risk/execution/sensor/signal/composition module reads it. Ledger presence does
not perturb replay; backtest deployments construct no ledger (`registry_clock=None`,
`bootstrap.py:313`; shipped `platform.yaml:228 promotion_ledger_path: null`).

---

## 7. Layer validator audit (G2–G16)

### E.1 Gate-by-gate (`layer_validator.py`)

| Gate | Enforces | Block? | Distinct error subclass |
|---|---|---|---|
| G1 | SIGNAL/PORTFOLIO field independence (`universe` vs `depends_on_sensors`) | **soft** (`_softly`, `:313`) | `LayerValidationError` |
| G2 | SIGNAL inline `signal:` present & non-empty (`:522`) | block | `LayerValidationError` |
| G3 | single scalar `horizon_seconds` (`:435`) | **soft** (`:321`) | `LayerValidationError` |
| G4 | regime-gate DSL safe-compile (`:545`) | block | `LayerValidationError` |
| G5 | signal-purity AST scan (no import/exec/eval/globals) (`:584`) | block | `LayerValidationError` |
| G6 | non-empty unique `depends_on_sensors`; resolves if known set injected (`:616`) | block | `LayerValidationError` |
| G7 | `horizon_seconds` in registered set (`:669`) | block | `LayerValidationError` |
| G8 | no wall-clock/lookahead identifiers in signal (`:695`) | block | `LayerValidationError` |
| G9 | PORTFOLIO session-alignment placeholder (`:455`) | block (no-op body) | `LayerValidationError` |
| G10 | PORTFOLIO non-empty `universe` of strings (`:471`) | block | `LayerValidationError` |
| G11 | PORTFOLIO `factor_neutralization` bool disclosed (`:488`) | block | `LayerValidationError` |
| G12 | SIGNAL `cost_arithmetic` parses; `margin_ratio ≥ 1.5` (`:728`) | block | `LayerValidationError` |
| G13 | warm-up doc — no-op for surviving layers (`:760`) | n/a | — |
| G14 | data-source scope ⊆ L1 NBBO/trades (`:346`) | block | `LayerValidationError` |
| G15 | `fill_model.router` ∈ shipped routers (`:376`) | block | `LayerValidationError` |
| G16 | mechanism-horizon binding, rules 1–10 (`:843`) | block | `TrendMechanismValidationError` + 9 subclasses (`:73–138`) |

No gate "logs-and-continues where it should block": the only WARNING-downgrade path is
`_softly`, used exclusively for G1 and G3 (`:313,321`). G16 emits distinct subclasses per
rule (`:73–138`) so callers attribute failures without string parsing.

**[LIM] In-code comment drift:** the `validate()` banner comment "G1-G13 — scaffolded
no-ops (Phase 3+)" (`:311`) is stale — G2/G4–G13 are clearly active.

### E.2 `enforce_layer_gates` semantics — **PASS, matches glossary**

`_softly` re-raises when `_enforce_layer_gates` is True and downgrades to WARNING when False
(`:283–292`); it wraps only G1 and G3. G9–G16 (data-integrity + economic + provenance gates)
are invoked directly and always block regardless of the flag. This matches the canonical
glossary (`enforce_layer_gates` entry) and contradicts the **stale**
`docs/three_layer_architecture.md` §9 ("only G12–G15 blocking; G1–G11 warnings") —
**flagged as doc drift, not resolved in the doc's favor** per the auditor note.

### E.3 G16 strict-mode default — **PASS at platform level; LIM at library level**

`_check_g16_trend_mechanism_compliance` (`:843`) rejects a schema-1.1 SIGNAL/PORTFOLIO spec
lacking a `trend_mechanism:` block via `MissingTrendMechanismError` when
`_enforce_trend_mechanism` is True (`:872–878`). `PlatformConfig.enforce_trend_mechanism`
defaults **True** (`platform_config.py:527`) and bootstrap threads it into the loader
(`bootstrap.py:336`), which passes it to the validator (`loader.py:929–932,948–951`).

**[P2/LIM] Defense-in-depth gap:** the `LayerValidator` and `AlphaLoader` constructors
default `enforce_trend_mechanism=False` (`layer_validator.py:237`, `loader.py:267`), so a
directly-constructed loader (tests, tooling) is permissive; only the bootstrap path is
strict. The shipped `platform.yaml:23` itself pins `enforce_trend_mechanism: false` (the
documented v0.2-baseline opt-out for `sig_benign_midcap_v1`), which is exactly the situation
behind the three known-failing acceptance tests recorded in `CLAUDE.md` / `AGENTS.md`
(baseline drift in `alphas/sig_benign_midcap_v1/`). This is a documented limitation, not a
regression.

---

## 8. CLI audit (read-only / fail-safe)

### F.1 Read-only / no production imports — **PARTIAL (P1 BUG)**

The handlers in `cli/promote.py` are themselves clean: they import only
`promotion_evidence`, `promotion_ledger`, `core.errors`, `core.platform_config`
(`promote.py:38–54`), never write the ledger, and render timestamps via
`datetime.fromtimestamp(..., tz=utc)` from stored ns — no wall-clock reads
(`promote.py:179–187`). Verified `from feelies.cli import promote` imports standalone.

**However** the dispatcher `cli/main.py:30` does `from feelies.cli import backtest, promote`,
and `backtest` pulls in `harness → bootstrap → execution.paper_backend → broker.ib → ibapi`.
Verified: `import feelies.cli.main` raises `ModuleNotFoundError: No module named 'ibapi'`,
and `tests/cli/test_promote_cli*.py` + `tests/bootstrap/test_gate_thresholds_wiring.py`
**fail to even collect** without the `ib` extra. Net: the documented "CLI never imports
orchestrator / risk-engine production code" contract is violated transitively, and
`feelies promote` is unusable in a minimal/forensic environment. Fix is lazy per-subcommand
import. (No *write* side effect was found — the violation is import coupling, not ledger
mutation.)

### F.2 Exit codes & OK/SKIPPED/FAIL — **PASS, two blemishes**

Codes `0/1/2/3` are pinned and consistent (`promote.py:56–59`, `main.py:33–36`). Mapping:
user error (missing args / non-existent file / config without ledger path) → 1
(`promote.py:137,146,131`); data error (corrupt ledger / config load) → 2
(`:374,669,759`); `replay-evidence` violations → 3 (`:702`).

`replay-evidence` distinguishes OK / SKIPPED / FAIL correctly for legacy (no
`schema_version` → SKIPPED, `:557`), version-mismatch (SKIPPED, `:572`), and non-capital
`LIVE→LIVE` (gate `None` → SKIPPED, `:588`). Blemishes:

- **[P2]** A reconstruct failure (corrupt evidence shape) is classed as FAIL → exit **3**
  (`:603–616,702`), not a data error (2). For the quarantine case (D.2) this produces a
  *false* exit-3 on healthy data.
- **[P2]** `replay-evidence` validates against raw `GateThresholds()` (`:663`), so its
  verdict ignores the per-alpha/platform overrides actually applied at promotion (see #3).

---

## 9. Test gap matrix

| Invariant / behaviour | Tests | Status |
|---|---|---|
| Append-only across reopens | `test_promotion_ledger.py::test_append_only_across_reopens` | **covered** |
| Ledger round-trip (single/order/decimal) | `test_promotion_ledger.py` (round-trips, decimal-safety) | **covered** |
| Corrupt-line detection (malformed JSON / missing field) | `test_promotion_ledger.py::TestPromotionLedgerCorruptInput` | **covered** |
| Writer replay-determinism (identical file) | `test_promotion_ledger.py::test_repeated_append_produces_identical_file` | **covered** |
| Gate-matrix / validator / reconstructor completeness | import-time checks + `test_promotion_evidence.py` | **covered** |
| `validate_gate` missing/unsupported/duplicate | `test_promotion_evidence.py` | **covered** |
| XOR evidence path | `test_lifecycle_f4.py`, `test_lifecycle.py` | **covered** |
| SM legal/illegal transitions, F-6 self-loop, tier reset | `test_lifecycle.py`, `test_lifecycle_f6.py` | **covered** |
| F-5 merge wiring (skill/platform/per-alpha) | `test_registry_per_alpha_thresholds.py`, `test_gate_thresholds_wiring.py` | **covered** |
| G2–G16 block/warn, G16 rules, strict mode | `test_layer_validator_g2_g13.py`, `test_gate_g16*.py`, `test_strict_mode_*` | **covered** |
| Atomic rollback on ledger-write failure | — | **missing** |
| **Quarantine-with-evidence `replay-evidence` round-trip** | — | **missing** (bug D.2 uncaught) |
| Per-alpha override loosening below a platform floor | — | **missing** (no floor concept) |
| Ledger `schema_version` enforced on `entries()` read | — | **missing** (only `validate` subcmd) |
| Ledger tamper (well-formed in-place mutation) detection | — | **missing** |
| Effective thresholds recorded in ledger / replay parity | — | **missing** |
| Merge-determinism property (commutativity / idempotence) | — | **partial** (wiring only, no property test) |
| CLI import isolation (promote without `ib` extra) | — | **missing** (tests require `ib`) |
| Forensic-only: no per-tick ledger read | — | **missing** (verified manually here) |

### Proposed minimal new tests (specs only)

1. **Atomic rollback** — `AlphaLifecycle` with a stub ledger whose `append` raises; assert
   state unchanged, `history == []`, and no ledger line written.
2. **Quarantine replay round-trip** — drive `quarantine(structured_evidence=[Quarantine
   TriggerEvidence(...)])` into a real ledger, run `_handle_replay_evidence`; assert the
   row is OK/consistency-checked, not a reconstruct FAIL, and exit code 0. (Locks the D.2
   fix.)
3. **Threshold-floor property** — Hypothesis: for arbitrary platform + per-alpha override
   dicts, assert (post-fix) per-alpha may only tighten relative to platform; today this
   test documents the loosening and would fail, anchoring C.3.
4. **Merge determinism property** — Hypothesis over override dicts: `apply(apply(base, p),
   a)` equals applying the merged mapping; `apply(base, {})` is identity; base unmutated.
5. **Ledger schema-on-read** — append an entry with a bumped `schema_version`; assert
   `entries()` (not just `validate`) rejects or flags it.
6. **Ledger tamper** — mutate one metadata value in a written line; assert a (future)
   integrity check detects it.
7. **CLI import isolation** — in an env without `ib`, assert `feelies promote gate-matrix`
   exits 0 (requires lazy subcommand import).
8. **Forensic-only guard** — static test asserting no module under
   `risk/execution/sensors/signals/composition/kernel` imports `PromotionLedger`.

---

## 10. Prioritized backlog

Effort: **S** ≤ ½ day · **M** ~1–2 days · **L** > 2 days.

### P0

| # | Component | `file:line` | One-sentence fix | Impact |
|---|---|---|---|---|
| P0-1 | F-5 merge — unauthorized loosening | `promotion_evidence.py:1206`; `registry.py:122`; `bootstrap.py:328` | Treat platform-layer thresholds as monotone floors so per-alpha overrides may only *tighten* (reject a loosening with `AlphaLoadError`), or require an explicit operator-signed annotation to loosen. | Closes the Inv-11/Inv-13 governance gap where an external author lowers its own promotion bar below operator policy. Effort **M**. |

### P1

| # | Component | `file:line` | One-sentence fix | Impact |
|---|---|---|---|---|
| P1-1 | `metadata_to_evidence` rejects quarantine `reason` | `promotion_evidence.py:1076`; writer `lifecycle.py:430` | Ignore a documented set of non-kind co-keys (`reason`) instead of raising, or namespace evidence under a single `evidence:` sub-dict. | `replay-evidence` stops emitting false `FAIL`/exit-3 on every quarantine-with-evidence entry. Effort **S**. |
| P1-2 | Effective thresholds not in ledger | `promotion_evidence.py:877`; `lifecycle.py:343,672` | Persist the resolved `GateThresholds` (or a hash + override delta) onto each promotion ledger entry; have `replay-evidence` validate against the recorded thresholds. | Promotion becomes reproducible from the ledger alone; replay verdicts reflect the policy actually applied. Effort **M**. |
| P1-3 | CLI import coupling / `ib` hard dep | `cli/main.py:30` | Lazily import each subcommand module inside its `register`/handler so `promote` never pulls in `backtest → bootstrap → broker.ib`. | Restores the read-only/forensic-only import contract and lets `feelies promote` run in a minimal env. Effort **S**. |
| P1-4 | Self-asserted evidence (no run binding) | `promotion_evidence.py:433–731` | Require a content-addressed artefact/run-id on CPCV/DSR/paper evidence and (optionally) verify it against the research-artefact store at promotion. | Strengthens Inv-13's reproducible chain; reduces trust-on-submit. Effort **L**. |

### P2

| # | Component | `file:line` | One-sentence fix | Impact |
|---|---|---|---|---|
| P2-1 | Schema not asserted on read | `promotion_ledger.py:202,134` | Compare `schema_version` to `LEDGER_SCHEMA_VERSION` in `entries()` (or a strict reader) and raise/flag on mismatch. | Makes the SKILL's "asserted on every read" true; protects `inspect`/`replay-evidence`. Effort **S**. |
| P2-2 | No ledger integrity chain | `promotion_ledger.py:92,187` | Add a per-line `prev_hash`/`entry_hash` chain (or detached signature) and verify it in `validate`. | In-place value tampering becomes detectable. Effort **M**. |
| P2-3 | `from_yaml` ignores unknown keys | `platform_config.py:1207+` | Reject unknown top-level config keys (allow-list) so a typo'd `promotion_ledger_path`/`enforce_trend_mechanism` fails loudly. | Prevents silent disabling of the provenance ledger / strict mode. Effort **S**. |
| P2-4 | Library strict-mode default = False | `layer_validator.py:237`; `loader.py:267` | Default `enforce_trend_mechanism=True` to match `PlatformConfig`, with explicit opt-out. | Removes the permissive default for directly-constructed loaders. Effort **S**. |
| P2-5 | `validate_gate` ignores extra evidence | `promotion_evidence.py:854` | Reject (or warn on) supported-but-not-required evidence types per gate. | Stops silently dropping mis-targeted evidence that is still written to the ledger. Effort **S**. |
| P2-6 | Reconstruct failure → exit 3 not 2 | `promote.py:603,702` | Classify reconstruct/corruption failures as data errors (exit 2), reserve 3 for genuine threshold violations. | Cleaner CI semantics; complements P1-1. Effort **S**. |
| P2-7 | Tier algorithm sorts vs history order | `promote.py:289` vs `lifecycle.py:600` | Document/assert the monotonic-clock precondition, or make the CLI consume append order. | Removes the latent divergence behind the "byte-for-byte" claim. Effort **S**. |
| P2-8 | `restore()` gate-free state set | `lifecycle.py:787–799` | Optionally emit a `restore` ledger marker and/or validate the rehydrated state against the last ledger entry. | Records the otherwise-invisible checkpoint→state path for provenance. Effort **M**. |
| P2-9 | Stale docs / comments | `docs/three_layer_architecture.md` §9; `layer_validator.py:311` | Update §9 to the `enforce_layer_gates` glossary semantics; fix the "G1-G13 no-op" banner. | Removes misleading guidance contradicting enforced behaviour. Effort **S**. |

---

### Appendix — invariant verdicts

| Invariant | Verdict | Basis |
|---|---|---|
| Inv-13 provenance (atomic transition record) | **HOLDS** for the recorded fields; **GAPS** in completeness (thresholds not recorded P1-2; self-asserted evidence P1-4; restore P2-8) | §3.A3, §5.C3, §4.B3 |
| Inv-5 forensic-only (no per-tick ledger read) | **HOLDS** | §6.D3 |
| Inv-11 fail-safe quarantine always commits | **HOLDS** (validator only warns, `lifecycle.py:418–430`); **but** Inv-11 "loosening requires re-auth" weakened by P0-1 | §3, §5 |
| Gate-matrix completeness | **HOLDS** | §4.B1 |

*End of audit. No production code or ledger was modified during this pass.*
