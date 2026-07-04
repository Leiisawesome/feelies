# Alpha Lifecycle / Promotion / Capital-Tier Audit — 2026-07-02

**Scope:** promotion / quarantine / capital-tier machinery — the 5-state `AlphaLifecycle`
SM, the F-2 declarative gate matrix, the F-1 promotion ledger, the F-5 three-layer
threshold merge, the G2–G16 `LayerValidator`, and the read-only `feelies promote` CLI.
Read-only, evidence-based. No production code, config, baseline, or ledger was modified.

**This is a follow-up audit.** A prior pass, `docs/audits/alpha_lifecycle_audit_2026-06-23.md`
(branch `claude/cool-mccarthy-po75qg`), found one P0 and four P1 issues and recorded a
"Resolution status (updated 2026-06-26)" note claiming three of them were fixed. This
report **independently re-verifies every one of those claims against the current working
tree** (branch `claude/alpha-lifecycle-audit-q94j7x`, HEAD `929e9fb`, 2026-07-02) rather
than trusting the prior note, re-runs the read-only test suites, and audits the delta for
new regressions or new gaps.

**Method:** static read of every in-scope module (line-cited below), fresh sitewide greps
for ledger-read call sites and bypass surfaces (not reused from the prior report), the
mandated read-only pytest sweeps plus several supplementary ones (full `tests/alpha/`,
`tests/cli/`, `tests/research/*promotion*`, `tests/acceptance/`), `ruff check` and
`mypy --strict` on the in-scope modules, and a `git log --since` scan of the scope paths
to identify exactly which commits changed behavior since 2026-06-23.

**Read-only checks executed**

| Check | Result |
|-------|--------|
| `pytest tests/alpha/test_lifecycle.py test_lifecycle_f6.py test_promotion_evidence.py test_promotion_ledger.py` | **231 passed** |
| `pytest tests/alpha/test_layer_validator_g2_g13.py test_gate_g16.py test_registry_per_alpha_thresholds.py` | **102 passed** |
| `pytest tests/cli/ tests/bootstrap/test_gate_thresholds_wiring.py tests/alpha/test_gate_g16_props.py tests/acceptance/test_g16_rule_completeness.py` | **67 passed** |
| `pytest tests/alpha/ tests/research/test_promotion_pipeline_e2e.py tests/research/test_strict_mode_promotion_e2e.py tests/acceptance/` (supplementary, full-scope) | **836 passed, 2 skipped, 1 failed** (failure is unrelated — see EX-15) |
| `feelies promote gate-matrix --json` (console script) | **OK** — all 6 `GateId` rendered, no import error |
| `ruff check` on `src/feelies/alpha/`, `src/feelies/cli/{promote,main}.py`, `src/feelies/core/state_machine.py` | **All checks passed** |
| `mypy --strict` on the same paths | **clean, 0 errors** |

Legend: **[FIXED]** verified resolved since 2026-06-23 · **[OPEN]** confirmed still present ·
**[NEW]** first raised in this pass · **[GOOD]** re-verified correct, no action needed ·
**[LIM]** documented/intentional limitation · **[BUG]** implementation defect.

---

## 1. Executive summary

1. **[FIXED, P0] Unauthorized per-alpha threshold loosening is closed.**
   `AlphaRegistry._enforce_threshold_floor` (`registry.py:176–205`) calls
   `assert_per_alpha_overrides_respect_floor` (`promotion_evidence.py:1426–1471`)
   unconditionally inside `register()` (`registry.py:127`), before any state mutation,
   in every mode including BACKTEST. A per-field `_GATE_THRESHOLD_DIRECTIONS` map
   (`:1366–1404`, MIN/MAX/FREE) classifies monotonicity, and a new construction-time
   check `_check_threshold_direction_coverage` (`:1530–1553`, wired at `:1550–1553`)
   fails import if a future `GateThresholds` field ships without a direction — so the
   floor rule is provably total over the schema, not just over today's fields. Verified
   wired end-to-end from `bootstrap.py:327–334` (`platform_gate_threshold_overrides=
   config.gate_thresholds_overrides` — exactly the operator-pinned field set, not the
   materialised defaults) through to the registry. 231/231 green in the lifecycle/evidence/
   ledger suite; `test_registry_per_alpha_thresholds.py` exercises the floor directly.
2. **[FIXED, P1] The quarantine-evidence false-FAIL bug is closed.**
   `RESERVED_METADATA_KEYS = frozenset({"schema_version", "reason"})`
   (`promotion_evidence.py:1061–1078`) is consulted by `metadata_to_evidence`'s
   unknown-key check (`:1191–1199`), so a quarantine-with-evidence entry — which always
   carries `{"reason": ...}` merged with any F-2 section (`lifecycle.py:416,430`) — now
   round-trips cleanly instead of raising. New regression test
   `test_quarantine_with_structured_evidence_replays_ok`
   (`tests/cli/test_promote_cli.py:761`) drives this through the real CLI handler and
   asserts exit 0.
3. **[FIXED, P1] CLI import coupling to the `ib` extra is closed.**
   `cli/main.py:_build_parser` (`:38–91`) imports `feelies.cli.backtest` — which pulls in
   `harness → bootstrap → broker.ib → ibapi` — **only** when `backtest` is the selected
   subcommand (`:81–84`); the `promote` subtree is always wired standalone (`:65–78`) and
   its handlers import only `promotion_evidence` / `promotion_ledger` / `core.errors` /
   `core.platform_config` (`cli/promote.py:38–55`). `feelies promote gate-matrix --json`
   ran clean in this session.
4. **No new P0 found.** Gate bypass, ledger mutation/loss, a per-tick production read of
   the ledger, and non-atomic SM+ledger commits were all independently re-checked negative
   on this pass (§3–§6) with fresh greps, not carried over from the prior report.
5. **[OPEN, P1] Effective `GateThresholds` are still not recorded in the ledger.**
   `evidence_to_metadata` persists only `schema_version` + evidence-kind sections
   (`promotion_evidence.py:972–1011`); `replay-evidence` still validates against a raw
   `GateThresholds()` (`cli/promote.py:664`), not the per-alpha-resolved thresholds
   actually in force at promotion time. A promotion is still not reproducible from the
   ledger alone, and `replay-evidence`'s verdict can disagree with the policy that was
   actually applied.
6. **[OPEN, P1/LIM, materially narrowed] Evidence is still self-asserted, but CPCV/DSR
   now has real internal-integrity checking.** A separate hardening commit
   (`44702ec`, outside this audit's direct scope) added to `validate_cpcv`/`validate_dsr`
   (`promotion_evidence.py:515–633`): non-finite rejection, `p_value`/`dsr_p_value` domain
   checks, a well-formed-hash check on `fold_pnl_curves_hash`, and — the strongest
   addition — **recomputing `mean_sharpe`/`median_sharpe` from `fold_sharpes` and
   rejecting a mismatch** (`:550–563`), so a fabricated or drifted CPCV summary can no
   longer pass on the operator's word alone. `ResearchAcceptanceEvidence`,
   `PaperWindowEvidence`, and the raw per-path `fold_sharpes` / `observed_sharpe` inputs
   themselves remain trust-on-submit with no binding to a reproducible run.
7. **[OPEN, P2] `replay-evidence` still classifies an evidence-reconstruction failure as a
   gate FAIL (exit 3), not a data error (exit 2)** (`cli/promote.py:604–617,673`). This is
   distinct from the now-fixed item 2 above (which was a *false-positive* reconstruction
   failure on perfectly healthy quarantine data); this residual gap is about the exit-code
   taxonomy for a *genuinely* malformed evidence shape.
8. **[OPEN, P2] Ledger `schema_version` is still not asserted in `entries()`**
   (`promotion_ledger.py:202–218`) — only the explicit `validate` subcommand compares it
   (`cli/promote.py:720–727`). `inspect` / `list` / `replay-evidence` read unversioned.
9. **[OPEN, P2] No ledger integrity hash/chain.** `PromotionLedger` exposes only `append`
   plus read methods (`promotion_ledger.py:161–241`) — genuinely append-only — but a
   syntactically well-formed in-place edit of one metadata value is undetectable; only
   malformed JSON / missing fields are caught.
10. **[OPEN, P2, doc drift — confirmed still unresolved, one more instance found]**
    `docs/three_layer_architecture.md:1177–1178` still reads *"If false, only G12-G15 are
    blocking; G1-G11 warnings logged"* — contradicted by the canonical invariants glossary
    and by code (`enforce_layer_gates` gates only G1/G3; G9–G16 always block,
    `layer_validator.py:265–292,313–342`). Per this audit's mandate this is flagged, not
    "resolved" in the doc's favor. Two in-code comments in the same file repeat the same
    false framing: `layer_validator.py:311–312` ("G1-G13 — scaffolded no-ops") **and**
    `:341–342` ("G16 — scaffolded no-op", directly above the call to a fully-active,
    10-rule, independently-tested gate) — the second location was not cited in the prior
    audit.
11. **[OPEN, P2/LIM, unchanged] `restore()` sets lifecycle state with no gate and no
    ledger entry** (`lifecycle.py:787–799`) — a checkpoint blob remains a gate-free,
    ledger-invisible state-set path; trust is anchored in the checkpoint store, not the
    ledger.
12. **[OPEN, P2/LIM, unchanged but now independently confirmed non-exploitable] CLI tier
    inference sorts by `timestamp_ns`; the SM uses raw append order**
    (`cli/promote.py:265–299` vs `lifecycle.py:596–616`). Confirmed this pass: a stable
    sort by timestamp over already-append-ordered rows is behaviorally identical to
    append order unless the clock runs backward, and `SimulatedClock.set_time()`
    explicitly rejects backward movement (`core/clock.py:45–46`) — so this divergence is
    latent, not live.
13. **[GOOD, re-verified fresh] Forensic-only contract and gate-matrix completeness both
    hold.** A fresh sitewide grep for `PromotionLedger(`, `.entries(`/`.entries_for(`, and
    `metadata_to_evidence(` (not reused from the prior audit) surfaces only
    `cli/promote.py` (read-only CLI), `bootstrap.py` (construction), and the `alpha/`
    definition modules — no risk/execution/sensor/signal/composition/kernel reader.
    `_check_matrix_completeness` / `_check_validator_coverage` /
    `_check_reconstructor_coverage` / `_check_threshold_direction_coverage` all run at
    import (`promotion_evidence.py:1550–1553`).
14. **[NEW since last audit, not a defect] G16 gained a 10th binding rule.**
    `UnbackedSignatureSensorError` (`layer_validator.py:124–132,982–998`) rejects a
    `l1_signature_sensors` entry that is absent from `depends_on_sensors` ("cosmetic
    fingerprint" — the alpha can't actually consume the sensor it claims as its
    mechanism's L1 signature). Tested across 4 files, including the G16-rule-completeness
    acceptance gate. `GateThresholds` also grew 5 fields since 2026-06-23
    (`paper_min_sample_size`, `paper_max_fill_rate_drift_pct`, `cpcv_min_embargo_bars`,
    `quarantine_min_microstructure_breaches`, `quarantine_min_crowding_symptoms`) — all
    correctly present in `_GATE_THRESHOLD_DIRECTIONS`, confirming the coverage check
    earns its keep.
15. **[Caveat, out of scope, flagged for transparency]** The supplementary full
    `tests/acceptance/` sweep surfaces one failure unrelated to this audit:
    `test_wall_clock_allowlist_has_no_stale_entries` — the DTZ allowlist entry for
    `core/platform_config.py` is stale (that module no longer makes any wall-clock call
    at all). This contradicts the "green as of 2026-06-11" claim in `CLAUDE.md`/
    `AGENTS.md`, but it is a DTZ/Inv-10 bookkeeping issue, not an alpha-lifecycle/
    promotion-governance defect — noted for visibility only, not investigated further.

---

## 2. Gate matrix snapshot

Rendered from `GATE_EVIDENCE_REQUIREMENTS` (`promotion_evidence.py:838–849`), validators
(`:862–873`), metadata kinds (`:876–884`) — cross-checked live against
`feelies promote gate-matrix --json` output, which matched byte-for-byte.

| `GateId` (value) | Lifecycle edge | Required evidence | Validator | metadata `kind` |
|---|---|---|---|---|
| `research_to_paper` | RESEARCH→PAPER | `ResearchAcceptanceEvidence` | `validate_research_acceptance` | `research_acceptance` |
| `paper_to_live` | PAPER→LIVE | `PaperWindowEvidence`, `CPCVEvidence`, `DSREvidence` | `validate_paper_window` / `validate_cpcv` / `validate_dsr` | `paper_window` / `cpcv` / `dsr` |
| `live_promote_capital_tier` | LIVE→LIVE (self-loop) | `CapitalStageEvidence` | `validate_capital_stage` | `capital_stage` |
| `live_to_quarantined` | LIVE→QUARANTINED | `QuarantineTriggerEvidence` *(consistency-only, Inv-11)* | `validate_quarantine_trigger` | `quarantine_trigger` |
| `quarantined_to_paper` | QUARANTINED→PAPER | `RevalidationEvidence` | `validate_revalidation` | `revalidation` |
| `quarantined_to_decommissioned` | QUARANTINED→DECOMMISSIONED | *(none)* | — | — |

All 6 `GateId` members present; `_check_matrix_completeness` / `_check_validator_coverage`
/ `_check_reconstructor_coverage` pass at import (verified: `import feelies.alpha.
promotion_evidence` succeeds as a side effect of every test run in this session).

### `GateThresholds` defaults (`promotion_evidence.py:364–453`) — 29 fields, all classified

5 fields new since the 2026-06-23 audit (marked **NEW**); all 29 are present in
`_GATE_THRESHOLD_DIRECTIONS` per `_check_threshold_direction_coverage`.

| Field | Default | Dir. | | Field | Default | Dir. |
|---|---|---|---|---|---|---|
| `research_min_branch_coverage_pct` | 90.0 | MIN | | `cpcv_min_folds` | 8 | MIN |
| `research_min_line_coverage_pct` | 80.0 | MIN | | `cpcv_min_mean_sharpe` | 1.0 | MIN |
| `research_min_fault_injection_pass_pct` | 100.0 | MIN | | `cpcv_max_p_value` | 0.05 | MAX |
| `paper_min_trading_days` | 5 | MIN | | `cpcv_min_embargo_bars` **NEW** | 1 | MIN |
| `paper_min_sample_size` **NEW** | 0 | MIN | | `dsr_min` | 1.0 | MIN |
| `paper_max_slippage_residual_bps` | 1.5 | MAX | | `dsr_max_p_value` | 0.05 | MAX |
| `paper_max_fill_rate_drift_pct` **NEW** | 10.0 | MAX | | `small_min_deployment_days` | 10 | MIN |
| `paper_min_latency_ks_p` | 0.10 | MIN | | `small_min_pnl_compression_ratio` | 0.5 | MIN |
| `paper_min_pnl_compression_ratio` | 0.6 | MIN | | `small_max_pnl_compression_ratio` | 1.0 | MAX |
| `paper_max_pnl_compression_ratio` | 1.2 | MAX | | `small_max_slippage_residual_bps` | 2.5 | MAX |
| `paper_max_anomalous_events` | 0 | MAX | | `small_max_hit_rate_residual_pp` | −5.0 | MIN\* |
| `quarantine_max_net_alpha_negative_days` | 10 | FREE | | `small_max_fill_rate_drift_pct` | 10.0 | MAX |
| `quarantine_max_hit_rate_residual_pp` | −15.0 | FREE | | `revalidation_min_oos_sharpe` | 1.0 | MIN |
| `quarantine_max_pnl_compression_ratio_5d` | 0.3 | FREE | | | | |
| `quarantine_min_microstructure_breaches` **NEW** | 2 | FREE | | | | |
| `quarantine_min_crowding_symptoms` **NEW** | 3 | FREE | | | | |

\* `small_max_hit_rate_residual_pp` is classified MIN despite the "max" name — the
validator's pass condition is `residual >= threshold` on a negative-stored floor, so a
*higher* value is stricter (`promotion_evidence.py:1391–1394` comment makes this explicit).

---

## 3. Lifecycle SM audit

### 3.1 Transition table & illegal-transition rejection — **PASS**

`_LIFECYCLE_TRANSITIONS` (`lifecycle.py:60–80`):

| from | allowed to | trigger / gate |
|---|---|---|
| RESEARCH | {PAPER} | `pass_paper_gate` / `RESEARCH_TO_PAPER` |
| PAPER | {LIVE} | `pass_live_gate` / `PAPER_TO_LIVE` |
| LIVE | {LIVE, QUARANTINED} | `promote_capital_tier` / `LIVE_PROMOTE_CAPITAL_TIER` **·** `edge_decay_detected` / `LIVE_TO_QUARANTINED` |
| QUARANTINED | {PAPER, DECOMMISSIONED} | `revalidation_passed` / `QUARANTINED_TO_PAPER` **·** `decommissioned` / (no gate — empty evidence requirement) |
| DECOMMISSIONED | {} (terminal) | — |

`StateMachine.__init__` enforces enum completeness (`state_machine.py:90–101`; every
`AlphaLifecycleState` member must have a table entry, even if empty) and
`can_transition`/`transition` reject anything not in the table via `IllegalTransition`
(`state_machine.py:124–160`). RESEARCH→LIVE, PAPER→QUARANTINED, LIVE→PAPER, etc. are all
rejected. No exposed bypass: `AlphaLifecycle` never calls the generic
`StateMachine.reset()` (which *does* skip transition-table validation, by design, for the
macro/micro/kill-switch/regime-hazard SMs elsewhere in the platform) — grep confirms only
`kernel/orchestrator.py` and `services/regime_hazard_detector.py` invoke `.reset()`;
`alpha/lifecycle.py` does not.

**F-6 self-loop vs. demotion (same `from_state == "LIVE"`)** — distinguished by `trigger`,
not by state pair. `promote_capital_tier` stamps `PROMOTE_CAPITAL_TIER_TRIGGER`
(`lifecycle.py:539`); `_gate_for_entry` in the CLI resolves `("LIVE","LIVE")` to
`GateId.LIVE_PROMOTE_CAPITAL_TIER` **only** when `entry.trigger ==
PROMOTE_CAPITAL_TIER_TRIGGER`, else `None`/skipped (`cli/promote.py:237–257`). Correct and
matches the glossary.

### 3.2 `current_capital_tier` vs. ledger replay — **PASS, with the same latent caveat as before (still latent, not live)**

The SM scans `history` (`lifecycle.py:599–616`) backwards, returning `SCALED` on the first
`PROMOTE_CAPITAL_TIER_TRIGGER` record encountered, else `SMALL_CAPITAL` at the first
LIVE-entry edge. Quarantine → revalidate → re-promote starts a new epoch (the
`to_state==LIVE and from_state!=LIVE` branch fires first) → resets to `SMALL_CAPITAL`.
Confirmed correct by both static reading and the 231-test green run.

The CLI mirror `_capital_tier_from_entries` (`cli/promote.py:265–299`) computes the same
result but **sorts by `timestamp_ns`** first (`:290`) before walking backwards, whereas the
SM walks raw `history` append order. As documented in EX-12: because `entries_for()`
already yields rows in append order and Python's `sorted()` is stable, a sort by
`timestamp_ns` only changes the result relative to append order if some later-appended
entry carries a strictly smaller timestamp than an earlier one — i.e. a real clock
regression. `SimulatedClock.set_time()` raises on backward movement
(`core/clock.py:44–46`), and `restore()` never writes ledger entries, so this holds for
every code path that can produce a ledger today. Still worth noting as a latent
structural difference (two independent implementations of the same algorithm, one
sort-based, one not) rather than a proven bug.

### 3.3 Atomicity on ledger-write failure — **PASS (Inv-13), now with an explicit multi-callback boundary test**

`StateMachine.transition()` (`state_machine.py:128–177`): validate → build immutable
`TransitionRecord` → fire `on_transition` callbacks → **then** append to history and flip
`self._state`. If a callback raises, the exception propagates *before* the commit step —
state and history are untouched. `AlphaLifecycle._record_to_ledger`
(`lifecycle.py:678–693`) is the **only** callback registered on the alpha-lifecycle SM
(`lifecycle.py:282–283`, conditional on a ledger being supplied), so for this SM the
rollback is exact: a raising `ledger.append` leaves the SM at its pre-transition state
with no history entry and no line written (append is a single `open("a")` + write + flush,
`promotion_ledger.py:187–198`, so a raise before the write means nothing hits disk).

New this pass: `test_multi_callback_rollback_boundary`
(`tests/core/test_state_machine.py:108–130`) formalizes the documented caveat in
`state_machine.py:149–157` — if a *second* callback were ever registered on this SM and it
raised, the first callback's already-executed external side effect would **not** be
undone (the SM can only roll back state it owns). This is correct, generic SM behavior,
tested at the SM level; it does not currently bite `AlphaLifecycle` because exactly one
callback is registered. Flagged as a **design note for future maintainers**, not a defect
today: if a second `on_transition` callback is ever added to `AlphaLifecycle`, it must be
idempotent/reversible on its own.

One remaining test gap (carried over, unchanged): there is still no
`AlphaLifecycle`-level (as opposed to generic-`StateMachine`-level) test that drives a
real `PromotionLedger`-shaped failure through `AlphaLifecycle.promote_to_paper(...)` and
asserts the SM rolls back — grep of `tests/alpha/` and `tests/bootstrap/` for
"atomic"/"rollback" returns nothing. The underlying mechanism is proven at the generic SM
layer and the wiring is a single, directly-read 12-line callback
(`lifecycle.py:678–693`), so confidence is high, but the integration path itself is
untested. See §9.

---

## 4. Gate validation audit

### 4.1 Matrix / validator / reconstructor / direction completeness — **PASS**

Four import-time checks now run (`promotion_evidence.py:1550–1553`, up from three at the
prior audit): `_check_matrix_completeness`, `_check_validator_coverage`,
`_check_reconstructor_coverage`, and the new `_check_threshold_direction_coverage`
(`:1530–1547`, added alongside the P0-1 fix). A new `GateId`, evidence type, or
`GateThresholds` field that isn't fully wired into all four now fails at import — the
floor rule is structurally protected against silent regression, not just tested today.

### 4.2 `validate_gate` ordering — **PASS, same one footgun as before**

`validate_gate` (`promotion_evidence.py:900–964`) indexes supplied evidence by type,
rejects unsupported types (`:934–939`) and duplicate types (`:941–946`), then reports
missing-required types (`:949–954`), then runs per-type validators (`:956–963`).
Structural rejections precede per-evidence errors — correct order.

**[OPEN, P2]** Extra supported-but-not-required evidence is still silently accepted into
`by_type` and never checked against `required` (`:949`), yet
`evidence_to_metadata(*structured_evidence)` (`lifecycle.py:672`) still writes it to the
ledger unconditionally. Not a bypass (required evidence is still fully enforced) — a
quiet correctness gap, unchanged since 2026-06-23.

### 4.3 Empty / self-asserted evidence; XOR enforcement — **PASS / OPEN (narrowed)**

- **XOR still enforced.** `_select_evidence` raises `ValueError` for both-or-neither
  (`lifecycle.py:639–650`). `promote_capital_tier` remains structured-evidence-only, no
  legacy shape (`lifecycle.py:481–543`).
- **Empty evidence still fails every real gate** — all five non-trivial gates have
  non-empty `required` tuples; only `QUARANTINED_TO_DECOMMISSIONED` is empty, and
  `decommission()` doesn't call `validate_gate` at all (`lifecycle.py:545–557`) —
  intentional, matching the SKILL's documented design (free-form reason is the audit
  substrate for terminal retirement).
- **[OPEN, P1/LIM, narrowed — see EX-6]** Self-asserted evidence for
  `ResearchAcceptanceEvidence` / `PaperWindowEvidence` / raw CPCV inputs remains
  unverified against a real run. CPCV/DSR summary-statistic *consistency* (not
  *provenance*) is now checked (`promotion_evidence.py:550–563,605–615`).

---

## 5. Threshold merge audit (F-5)

### 5.1 Determinism — **PASS, unchanged**

- Non-mutating: `apply_gate_thresholds_overrides` → `dataclasses.replace`
  (`promotion_evidence.py:1324–1338`); `GateThresholds` is `frozen`
  (`:364–365`).
- Resolved once at registration: `AlphaRegistry.register` → `_resolve_gate_thresholds`
  (`registry.py:103,146–174`); the merged value is frozen onto `AlphaLifecycle` at
  construction (`registry.py:131–139`) and never re-resolved at promotion time. The
  platform layer itself is built once in bootstrap
  (`_build_platform_gate_thresholds`, `bootstrap.py:822–844`).
- Order-independent (pure field replacement); confirmed no code path re-applies overrides
  after registration.

### 5.2 Grammar parity — **PASS, unchanged**

Both entry points share `parse_gate_thresholds_overrides`
(`promotion_evidence.py:1242–1291`): per-alpha via `loader._parse_promotion_block`
(`loader.py:1217–1270`) and platform-wide via
`PlatformConfig._parse_gate_thresholds_block` (`platform_config.py:1746–1785`). Strict
coercion in `_coerce_threshold_value` (`:1294–1321`): `bool` is not accepted for an `int`
field (`:1307–1312`) or vice versa (`:1301–1306`), strings are never auto-parsed
(`:1313–1320`), unknown field names raise (`:1279–1284`). Identical grammar regardless of
source — verified by reading both call sites.

### 5.3 Unauthorized loosening — **FIXED (was P0, now closed)**

See EX-1 above for the full fix chain. Mechanically: `AlphaRegistry._enforce_threshold_floor`
(`registry.py:176–205`) is a no-op only when the operator pinned *nothing* in
`platform.yaml: gate_thresholds:` (`self._platform_threshold_overrides` empty) or the alpha
declares no overrides (`:191–193`) — otherwise it calls
`assert_per_alpha_overrides_respect_floor` (`promotion_evidence.py:1426–1471`), which walks
only the fields the operator *explicitly* pinned (`platform_pinned_fields`, sourced from
`config.gate_thresholds_overrides` at `bootstrap.py:334`, **not** the fully-materialised
`GateThresholds` — so skill-default fields the operator never touched remain freely
loosenable per-alpha, preserving the documented "per-alpha wins over skill defaults"
flexibility) and raises `GateThresholdFloorError` → wrapped as `AlphaRegistryError`
(`registry.py:201–205`) on any MIN-direction decrease or MAX-direction increase relative to
the pinned floor.

**Verified from the running system, not just the code:** the *shipped* `platform.yaml`
currently sets `gate_thresholds: {}` (`platform.yaml:227`) — the operator has pinned
nothing yet, so `_enforce_threshold_floor` is presently a no-op for every shipped
configuration (`platform.yaml`, `configs/paper_run.yaml`, `configs/paper_smoke_rth.yaml`
all set `gate_thresholds: {}`), and no shipped alpha under `alphas/*/` declares a
`promotion.gate_thresholds` override (only the two `_template/` files document the
grammar in a comment). **This is not a bug** — the floor mechanism is fully wired, tested
(`test_registry_per_alpha_thresholds.py`, `test_promotion_evidence.py`), and will engage
the moment an operator pins a real floor — but it is worth recording that the fix is
currently inert in the platform's actual deployed configuration, so this pass could not
observe it rejecting a live misconfiguration end-to-end outside the test suite.

---

## 6. Ledger audit (Inv-13, Inv-5)

### 6.1 Append-only & schema-on-read — **PASS (append) / OPEN, P2 (read)**

`PromotionLedger` exposes only `append` (opens in `"a"` mode, flushes per call,
`promotion_ledger.py:187–198`) and read methods (`entries`, `entries_for`, `latest_for`,
`__len__`, `__iter__`, `:202–241`) — there is no rewrite/truncate/clear path anywhere in
the class. Confirmed by reading the full 248-line module: `__slots__ = ("_path",)`
(`:173`) leaves no room for a hidden mutable buffer either.

**[OPEN, P2, unchanged]** `LEDGER_SCHEMA_VERSION` is still not asserted in `entries()`
(`:202–218`) — the field is parsed and stored verbatim by `from_json_line` (`:106–143`)
without comparison. Only the explicit `validate` subcommand checks it
(`cli/promote.py:720–727`); `inspect`/`list`/`replay-evidence` read unversioned.

**[OPEN, P2, unchanged]** No per-line integrity hash/chain — a syntactically valid
in-place edit of one metadata value is undetectable; only malformed JSON / missing
required fields raise (`promotion_ledger.py:106–143`).

### 6.2 Round-trip — **FIXED for the quarantine shape (was P1); PASS elsewhere, unchanged**

`_evidence_to_jsonable` (`promotion_evidence.py:1014–1041`) flattens `Enum → .value`,
`tuple → list`; all seven evidence dataclasses are flat scalars/tuples so
promote/capital/revalidation shapes round-trip losslessly. Legacy `{"evidence": {...}}`
(no `schema_version`) still correctly returns `[]` → SKIPPED (`:1170–1172`).

The quarantine-with-evidence shape — `{"reason", "schema_version", "quarantine_trigger"}`
(`lifecycle.py:416,430`) — previously failed reconstruction because `metadata_to_evidence`
rejected any key that was neither `schema_version` nor a known kind. **Now fixed**: the
`RESERVED_METADATA_KEYS` allow-list (`promotion_evidence.py:1061–1078`) explicitly carries
`reason` alongside `schema_version`, and the unknown-key check at `:1191–1199` excludes
both. `test_quarantine_with_structured_evidence_replays_ok`
(`tests/cli/test_promote_cli.py:761–~800`) drives this through the real
`_handle_replay_evidence` CLI path on a scratch ledger and asserts exit 0 — verified this
test is present and green in this session's run.

### 6.3 Forensic-only contract — **PASS (Inv-5 / A-DET-02), independently re-verified**

Fresh grep (not reused from the prior audit) of `src/feelies` for `PromotionLedger(`,
`.entries(`, `.entries_for(`, `.latest_for(`, and `metadata_to_evidence(` returns exactly:
`cli/promote.py` (read-only CLI, multiple call sites), `bootstrap.py:314` (construction),
`alpha/promotion_ledger.py` / `alpha/promotion_evidence.py` (definitions and internal
self-calls). No hit in `risk/`, `execution/`, `sensors/`, `signals/`, `composition/`,
`kernel/`. Ledger presence does not perturb replay; backtest deployments construct no
lifecycle tracking by default (`bootstrap.py:312`, `registry_clock = None if ... BACKTEST
else clock`) and the ledger itself is only constructed when `promotion_ledger_path` is set
(`bootstrap.py:313–317`) — the shipped `platform.yaml` sets no `promotion_ledger_path`.

---

## 7. Layer validator audit (G2–G16)

### 7.1 Gate-by-gate (`layer_validator.py`) — **unchanged from 2026-06-23 except G16 rule 10**

| Gate | Enforces | Block? | Error type |
|---|---|---|---|
| G1 | SIGNAL/PORTFOLIO field independence | soft (`_softly`, `:313`) | `LayerValidationError` |
| G2 | SIGNAL inline `signal:` non-empty (`:522`) | block | `LayerValidationError` |
| G3 | scalar `horizon_seconds` (`:435`) | soft (`:320`) | `LayerValidationError` |
| G4 | regime-gate DSL safe-compile (`:545`) | block | `LayerValidationError` |
| G5 | signal-purity AST scan (`:584`) | block | `LayerValidationError` |
| G6 | `depends_on_sensors` non-empty/unique/resolves (`:616`) | block | `LayerValidationError` |
| G7 | `horizon_seconds` in registered set (`:669`) | block | `LayerValidationError` |
| G8 | no wall-clock/lookahead identifiers (`:695`) | block | `LayerValidationError` |
| G9 | PORTFOLIO session-alignment — **self-documented placeholder** (`:455–469`, docstring: "the gate is otherwise a structural placeholder") | n/a at this layer | `LayerValidationError` (unreachable body) |
| G10 | PORTFOLIO non-empty `universe` of strings (`:471`) | block | `LayerValidationError` |
| G11 | PORTFOLIO `factor_neutralization` bool disclosed (`:488`) | block | `LayerValidationError` |
| G12 | SIGNAL `cost_arithmetic` parses, `margin_ratio ≥ 1.5` (`:728`) | block | `LayerValidationError` |
| G13 | warm-up doc — no-op for surviving layers (`:760`) | n/a | — |
| G14 | data-source scope ⊆ L1 NBBO/trades (`:346`) | block | `LayerValidationError` |
| G15 | `fill_model.router` ∈ shipped routers (`:376`) | block | `LayerValidationError` |
| G16 | mechanism-horizon binding, rules 1–10 (`:843`) | block | `TrendMechanismValidationError` + 11 subclasses — 10 numbered rules + `MissingTrendMechanismError` for the strict-mode missing-block case (`:73–138`) |

On G9: `SCHEMA.md:194` documents "G9" as a *runtime* cross-sectional-completeness check
against `CrossSectionalContext.completeness` — that check lives in the composition layer
(out of this audit's scope; see `audit_composition.md`), not in
`LayerValidator._check_g9_session_alignment`. The load-time stub here genuinely is a
placeholder (its own docstring says so) — this is a scope split across two modules, not a
missing enforcement, and matches how the prior audit characterized it ("block (no-op
body)").

**[NEW since 2026-06-23]** G16 rule 10 — `UnbackedSignatureSensorError`
(`layer_validator.py:124–132,982–998`): a `l1_signature_sensors` entry not present in
`depends_on_sensors` is rejected as a "cosmetic fingerprint" (the alpha's `evaluate()`
cannot actually read a sensor it doesn't depend on, so declaring it as the mechanism's L1
signature would be unverifiable). Runs independently of `known_sensor_ids` injection.
Tested in `test_gate_g16.py`, `test_gate_g16_props.py`,
`test_platform_config_v03_strict.py`, and `test_signal_layer_loader.py`; covered by the
G16-rule-completeness acceptance gate (`test_g16_rule_completeness.py`, green).

No gate silently "logs and continues where it should block" — the only WARNING-downgrade
path is `_softly` (`:265–292`), applied only to G1 and G3.

### 7.2 `enforce_layer_gates` semantics — **PASS, matches the canonical glossary**

`_softly` re-raises when `_enforce_layer_gates` is True, downgrades to a logged WARNING
when False (`:283–292`); it wraps only G1 and G3 (`:313,320`). G9–G16 are called directly
and always block regardless of the flag. This matches
`.cursor/rules/platform-invariants.mdc`'s `enforce_layer_gates` glossary entry and
`alphas/SCHEMA.md:186,188,194–197` (which is internally consistent and current) — and
contradicts `docs/three_layer_architecture.md:1177–1178` ("only G12-G15 are blocking;
G1-G11 warnings logged"), which is **stale** and was already flagged by the prior audit as
P2-9. **Confirmed still unfixed on this pass** — flagged again, not resolved in the doc's
favor, per this audit's explicit mandate.

Two more stale comments *inside* `layer_validator.py` itself make the identical false
claim and were not individually cited in the prior report:
- `:311–312` — "G1-G13 — scaffolded no-ops (Phase 3+)" directly above the call sequence
  that includes G2, G4–G12 (all genuinely blocking) and only G1/G3/G13 as actual no-ops/
  soft gates.
- `:341–342` — "G16 — scaffolded no-op (Phase 3.1, mechanism enforcement)" directly above
  `self._check_g16_trend_mechanism_compliance(...)`, a fully active check with 10 binding
  rules, its own exception hierarchy (`:62–138`), and dedicated property-based tests.
- The module docstring (`:6–14`) and class docstring (`:226–229`) both also describe G16
  and G1/G3/G9–G11 as "stay[ing] scaffolded" under a "Phase 3-α status" header that
  predates the current, fully-active implementation.

### 7.3 G16 strict-mode default — **PASS at platform level; unchanged LIM at library level**

`PlatformConfig.enforce_trend_mechanism` defaults **True** (`platform_config.py:527`) and
threads through bootstrap (`bootstrap.py:338`, `AlphaLoader(..., enforce_trend_mechanism=
config.enforce_trend_mechanism, ...)`) into the loader (`loader.py:932,951`) and validator. The shipped
`platform.yaml` itself pins `enforce_trend_mechanism: false` for the documented v0.2
baseline compatibility with `sig_benign_midcap_v1` (see `AGENTS.md`/`CLAUDE.md` — no
currently-known failures reference this, contrary to the June audit's note; the platform
suite is otherwise green modulo EX-15).

**[OPEN, P2/LIM, unchanged]** `LayerValidator.__init__` and `AlphaLoader.__init__` both
still default `enforce_trend_mechanism=False` (`layer_validator.py:237`, `loader.py:267`)
— a directly-constructed loader (tests, ad-hoc tooling) is permissive by default; only the
bootstrap path is strict. Documented limitation, not a regression.

---

## 8. CLI audit (read-only / fail-safe)

### 8.1 Read-only / no eager production imports — **FIXED (was P1)**

`cli/promote.py` handlers import only `feelies.alpha.promotion_evidence`,
`feelies.alpha.promotion_ledger`, `feelies.core.errors`, `feelies.core.platform_config`
(`:38–55`) — never the orchestrator/risk/broker stack, never write the ledger, and render
timestamps via `datetime.fromtimestamp(..., tz=utc)` from a stored ns value with no
wall-clock read of their own (`:180–188`).

The prior violation was in the *dispatcher*, not the handlers: `cli/main.py` used to
eagerly `from feelies.cli import backtest, promote`, and `backtest` transitively pulled in
`harness → bootstrap → execution.paper_backend → broker.ib → ibapi`, so *any*
`feelies promote ...` invocation imported the full orchestrator/risk/execution/broker
stack and failed outright without the `ib` extra. **Fixed**: `_build_parser`
(`cli/main.py:38–91`) always wires `promote` (`:65–78`) but only imports
`feelies.cli.backtest` when `argv[0] == "backtest"` (`:80–89`); otherwise it registers a
placeholder subparser so `feelies --help` still lists `backtest` without paying the import
cost. Verified: `feelies promote gate-matrix --json` ran clean in this session.

### 8.2 Exit codes & OK/SKIPPED/FAIL — **PASS, one blemish remains (unchanged)**

Codes 0/1/2/3 are pinned and consistently mapped (`cli/main.py:32–35`,
`cli/promote.py:57–60`): user error (missing `--ledger`/`--config` at `:138–141`,
non-existent ledger file at `:146–149`, config with no `promotion_ledger_path` at
`:131–134`) → 1; data error (corrupt ledger in `_handle_inspect` at `:373–376`, in
`_handle_replay_evidence` at `:669–671`, parse errors surfaced by `_handle_list` at
`:511`, and schema/parse failure in `_handle_validate` at `:760`) → 2;
`replay-evidence` gate violations → 3 (`:673,703`).
`replay-evidence` correctly distinguishes OK / SKIPPED / FAIL for legacy metadata (no
`schema_version` → SKIPPED, `:557–572`), version mismatch (SKIPPED, `:573–587`), and a
non-capital `LIVE→LIVE` self-loop (`gate_id is None` → SKIPPED, `:589–602`).

**[OPEN, P2, unchanged]** A reconstruct failure (genuinely corrupt evidence shape) is
still classified as FAIL → exit 3 (`:604–617`, folded into `any_failed` at `:673`), not a
data error (exit 2). Before the P1-1 fix this misfired on *every* healthy
quarantine-with-evidence entry (now fixed, §6.2); the residual gap is narrower — it now
only affects genuinely malformed metadata — but the exit-code taxonomy itself (reconstruct
failure vs. threshold-violation failure both mapping to 3) is unchanged.

**[OPEN, P1, unchanged — restated from EX-5]** `_handle_replay_evidence` constructs
`thresholds = GateThresholds()` (`:664`) — the raw skill defaults — rather than the
per-alpha-resolved thresholds that were actually in force at promotion time. Combined with
§6.1's ledger-doesn't-record-effective-thresholds gap, `replay-evidence`'s verdict can
diverge from the policy that actually gated the historical promotion.

---

## 9. Test gap matrix

| Invariant / behaviour | Tests | Status |
|---|---|---|
| Append-only across reopens | `test_promotion_ledger.py::test_append_only_across_reopens` | **covered** |
| Ledger round-trip (incl. quarantine+evidence shape) | `test_promotion_evidence.py` (RESERVED_METADATA_KEYS), `test_promote_cli.py::test_quarantine_with_structured_evidence_replays_ok` | **covered (newly closed gap)** |
| Corrupt-line detection | `test_promotion_ledger.py::TestPromotionLedgerCorruptInput` | **covered** |
| Gate-matrix / validator / reconstructor / **direction** completeness | import-time checks (4, up from 3) + `test_promotion_evidence.py` | **covered (strengthened)** |
| `validate_gate` missing/unsupported/duplicate | `test_promotion_evidence.py` | **covered** |
| XOR evidence path | `test_lifecycle_f4.py`, `test_lifecycle.py` | **covered** |
| SM legal/illegal transitions, F-6 self-loop, tier reset | `test_lifecycle.py`, `test_lifecycle_f6.py` | **covered** |
| F-5 merge wiring (skill/platform/per-alpha) | `test_registry_per_alpha_thresholds.py`, `test_gate_thresholds_wiring.py` | **covered** |
| **Per-alpha override loosening below a platform floor** | `test_registry_per_alpha_thresholds.py`, `test_promotion_evidence.py` | **covered (newly closed gap)** |
| CPCV/DSR internal-integrity checks (fabricated summary) | `test_promotion_evidence.py`, `tests/research/test_cpcv_unit.py` | **covered (newly closed gap)** |
| G2–G16 block/warn, G16 rules incl. rule 10, strict mode | `test_layer_validator_g2_g13.py`, `test_gate_g16*.py`, `test_g16_rule_completeness.py`, `test_strict_mode_*` | **covered** |
| SM callback-raise rollback (generic) + multi-callback boundary | `test_state_machine.py::test_callback_raises_prevents_transition`, `::test_multi_callback_rollback_boundary` (new) | **covered (generic layer)** |
| **`AlphaLifecycle`-integration atomic rollback (real ledger failure)** | — | **still missing** (mechanism proven at generic-SM layer only) |
| CLI import isolation (`promote` without `ib` extra) | — | **not test-enforced** (fix verified by static read + green run with extras installed; no test asserts `promote` works with `ib` absent) |
| Ledger `schema_version` enforced on `entries()` read | — | **still missing** (only `validate` subcommand) |
| Ledger tamper (well-formed in-place mutation) detection | — | **still missing** |
| Effective thresholds recorded in ledger / replay parity | — | **still missing** |
| `replay-evidence` reconstruct-failure exit code (2 vs 3) | — | **still missing** |
| Forensic-only: no per-tick ledger read | — | **verified manually this pass (fresh grep)**, no static/architectural test enforces it |

### Proposed minimal new tests (specs only — not implemented this pass)

1. **`AlphaLifecycle` + real `PromotionLedger` atomic-rollback integration test** — wrap a
   `PromotionLedger` whose underlying path is made unwritable (or monkeypatch `.append` to
   raise) mid-`promote_to_paper`; assert `lifecycle.state` is unchanged, `history == []`,
   and the ledger file gained no new line. Closes the one remaining integration-level gap
   now that the generic SM mechanism and the CLI-facing quarantine round-trip are both
   covered.
2. **CLI import-isolation test** — in a subprocess/environment without the `ib` extra
   importable, assert `feelies promote gate-matrix` exits 0 (guards against a future
   regression re-introducing an eager `backtest` import).
3. **Ledger schema-on-read** — append an entry with a bumped `schema_version`; assert
   `entries()` itself (not just `validate`) surfaces it.
4. **Ledger tamper** — mutate one metadata value in an already-written line; assert a
   (future) integrity check detects it.
5. **Effective-thresholds-in-ledger** — once implemented, assert `replay-evidence`
   recovers the exact `GateThresholds` used at promotion time rather than today's
   `GateThresholds()` defaults.
6. **Reconstruct-failure exit code** — corrupt one evidence-kind payload (wrong field
   type) in a ledger entry; assert `replay-evidence` returns exit 2, not 3.

---

## 10. Prioritized backlog

Effort: **S** ≤ ½ day · **M** ~1–2 days · **L** > 2 days. Items already fixed this pass are
listed under "Resolved" for traceability, not as outstanding work.

### Resolved since 2026-06-23 (verified, not re-opened)

| # | Component | `file:line` | Fix verified |
|---|---|---|---|
| ~~P0-1~~ | F-5 merge unauthorized loosening | `registry.py:127,176–205`; `promotion_evidence.py:1346–1471` | `_enforce_threshold_floor` + `assert_per_alpha_overrides_respect_floor`, wired at registration in all modes, construction-time direction-coverage check added |
| ~~P1-1~~ | `metadata_to_evidence` rejected quarantine `reason` | `promotion_evidence.py:1061–1078,1191–1199` | `RESERVED_METADATA_KEYS` allow-list; CLI regression test green |
| ~~P1-3~~ | CLI import coupling / `ib` hard dep | `cli/main.py:38–91` | Lazy per-selected-subcommand import |

### P0 — **none open**

### P1

| # | Component | `file:line` | One-sentence fix | Impact |
|---|---|---|---|---|
| P1-2 | Effective thresholds not in ledger | `promotion_evidence.py:972–1011`; `cli/promote.py:664`; `lifecycle.py:343,672` | Persist the resolved `GateThresholds` (or a hash + override delta) onto each promotion ledger entry; have `replay-evidence` validate against the recorded thresholds instead of raw defaults. | Promotion becomes reproducible from the ledger alone; `replay-evidence` verdicts reflect the policy actually applied. Effort **M**. |
| P1-4 | Self-asserted evidence (no run binding) — narrowed | `promotion_evidence.py:460–503` (research), `:636–690` (paper window) | Require a content-addressed artefact/run-id on research-acceptance and paper-window evidence, mirroring the integrity checks CPCV/DSR now have. | Extends the CPCV/DSR internal-integrity hardening to the remaining two self-asserted evidence types; reduces trust-on-submit. Effort **L**. |

### P2

| # | Component | `file:line` | One-sentence fix | Impact |
|---|---|---|---|---|
| P2-1 | Schema not asserted on read | `promotion_ledger.py:202–218` | Compare `schema_version` to `LEDGER_SCHEMA_VERSION` in `entries()` and raise/flag on mismatch. | Makes every read path (not just `validate`) schema-safe. Effort **S**. |
| P2-2 | No ledger integrity chain | `promotion_ledger.py:161–241` | Add a per-line `prev_hash`/`entry_hash` chain or detached signature, verified in `validate`. | In-place metadata tampering becomes detectable. Effort **M**. |
| P2-3 | `validate_gate` ignores extra evidence | `promotion_evidence.py:949` | Reject or warn on supported-but-not-required evidence types per gate. | Stops silently writing mis-targeted evidence to the ledger. Effort **S**. |
| P2-4 | Reconstruct failure → exit 3 not 2 | `cli/promote.py:604–617,673` | Classify reconstruct/corruption failures as data errors (exit 2); reserve 3 for genuine threshold violations. | Cleaner CI semantics. Effort **S**. |
| P2-5 | Library strict-mode default = False | `layer_validator.py:237`; `loader.py:267` | Default `enforce_trend_mechanism=True` to match `PlatformConfig`, with explicit opt-out. | Removes the permissive default for directly-constructed loaders/tests. Effort **S**. |
| P2-6 | Tier algorithm sorts vs. history order | `cli/promote.py:290` vs `lifecycle.py:600` | Document/assert the monotonic-clock precondition, or make the CLI consume raw append order. | Removes the latent divergence (confirmed non-exploitable this pass, but still two independent implementations of one algorithm). Effort **S**. |
| P2-7 | `restore()` gate-free state set | `lifecycle.py:787–799` | Optionally emit a `restore` ledger marker and/or validate the rehydrated state against the last ledger entry. | Records the otherwise-invisible checkpoint→state path for provenance. Effort **M**. |
| P2-8 | Stale docs/comments (3 locations, 1 new) | `docs/three_layer_architecture.md:1177–1178`; `layer_validator.py:311–312,341–342`; module/class docstrings `:6–14,226–229` | Update the doc to the `enforce_layer_gates` glossary semantics; replace "scaffolded no-op" banners with the actual per-gate active/soft status. | Removes misleading guidance that directly contradicts enforced, tested behavior. Effort **S**. |
| P2-9 | Missing `AlphaLifecycle`-integration atomic-rollback test | — (test gap only) | Add the integration test specified in §9 item 1. | Closes the last remaining gap between "mechanism proven" and "wiring proven." Effort **S**. |

---

### Appendix A — invariant verdicts

| Invariant | Verdict | Basis |
|---|---|---|
| Inv-13 provenance (atomic transition record) | **HOLDS** for recorded fields; **narrowed gaps** remain (thresholds not recorded — P1-2; self-asserted research/paper evidence — P1-4, though CPCV/DSR now materially strengthened; `restore()` — P2-7) | §3.3, §5.3, §4.3 |
| Inv-5 forensic-only (no per-tick ledger read) | **HOLDS**, re-verified with a fresh grep this pass | §6.3 |
| Inv-11 fail-safe quarantine always commits | **HOLDS** (validator only warns, `lifecycle.py:416–430`); loosening-requires-reauthorization sense **now enforced in code** (was the P0 gap, now closed) for any field the operator actually pins | §3, §5.3 |
| Gate-matrix completeness | **HOLDS**, now with a 4th construction-time check (threshold-direction coverage) | §4.1 |

### Appendix B — commits in scope since the 2026-06-23 audit

Identified via `git log --since=2026-06-23 -- src/feelies/alpha/ src/feelies/cli/promote.py src/feelies/cli/main.py src/feelies/core/state_machine.py`:

- `b6e3e36` — Enforce operator gate-threshold floors against per-alpha loosening (P0-1 fix)
- `7125ebe` — Fix promotion-CLI import coupling and quarantine evidence round-trip (P1-1 + P1-3 fix)
- `44702ec` — Harden CPCV/DSR research-validation math (touches `promotion_evidence.py` validators; primarily a different audit's scope, cross-referenced in §4.3/EX-6)
- `39d7707` — remediate clock/config/serialization/SM audit P1+P2 (added `test_multi_callback_rollback_boundary`; added `PlatformConfig.from_yaml(strict=...)`, adjacent to but not fully closing this audit's ledger-path-typo concern — `bootstrap.py` and `cli/promote.py` still call `from_yaml` without `strict=True`)

*End of audit. No production code, config, baseline, or ledger was modified during this
pass.*
