<!--
  File:   docs/research/prompt_pack_backlog.md
  Status: LIVING — consolidated register of separate-thread candidates
          spun out of the prompt pack (Tasks FQ-0…FQ-4, 2, 3). Entries
          are pointers to their authoritative specs, not re-specs.
          Created 2026-07-08 (Task 3 prefix, addition (b)).
  Owner:  cross-cutting; prompt-pack Phase A bookkeeping.
-->

# Prompt-pack backlog — separate-thread candidates

Platform threads identified during the pack but explicitly NOT part
of its alpha delivery (the four separate-thread candidates from the
Task-3 prefix, plus the link-check extension deferred by Task-3
addition (a)). Each entry points at the existing spec; scheduling,
ownership, and parity-impact assessment happen in the thread, not
here.

## 1. OQ-3 — Mechanism-cap runtime closure (PORTFOLIO layer)

G16 PORTFOLIO rule 8 validates `trend_mechanism.consumes[*].
max_share_of_gross` at load time, but bootstrap wires
`CrossSectionalRanker` with `mechanism_max_share_of_gross=1.0`, so
runtime enforcement of alpha-declared caps is disabled. Accepted risk
for this pack (SIGNAL-layer delivery; the gap bites only multi-alpha
PORTFOLIO deployment), with the standing obligation that every
capacity/crowding claim carries the not-active caveat. The thread
closes the gap by passing declared caps through bootstrap to the
ranker, with its own tests and a parity-impact assessment. Spec:
`docs/research/prompt_pack_00_architecture_verification.md` §(e)
OQ-3 row; code anchors in the composition-layer skill's
`CrossSectionalRanker` "Known gap" note
(`src/feelies/composition/cross_sectional.py`, `bootstrap.py`).

## 2. OQ-1 — `Signal.strength` engine-level enforcement (00e Track B)

`strength ∈ [0,1]` is a documented-but-unenforced contract (drift
D10), violated by design in shipped alphas (`sig_benign_midcap_v1`
convex scaling, cap 2.0) and baked into the locked
`reference_alpha_signal_fires` parity hash — so an engine clamp is a
known parity-breaking change requiring the mandatory assessment and a
(re-pin + alpha version bump) vs (contract amendment) decision.
Pre-registered semantics (NaN/negative drop, >1 clamp, FLAT kept at
0.0) and enforcement point (`HorizonSignalEngine` post-evaluate) are
fully specified. Spec:
`docs/research/prompt_pack_00e_strength_rider_and_thread.md`
Track B (PROPOSED; not a dependency of any pack task).

## 3. OQ-5 — Parity-manifest host/libm fingerprint FOLLOW-UP

Locked parity hashes are bit-identical only per (platform, libm)
pair; the manifest's own FOLLOW-UP (per-baseline host/libm
provenance) is unimplemented. The thread adds a provenance sidecar
(never a baseline-value change; `EXPECTED_MANIFEST_FINGERPRINT`
byte-identical before/after) plus two caveat-list corrections (add
`ofi_ewma`; annotate `liquidity_stress_score` as unexercised). Spec:
`docs/research/prompt_pack_00d_reproducibility_policy.md` §4; code
anchor `tests/determinism/parity_manifest.py` (FOLLOW-UP note in its
module docstring).

## 4. Extend internal-link checking to `.cursor/skills/**/*.md` — DONE

Landed in Task 3a (2026-07-08) as a pure `_DOC_FILES` data addition
(`tests/docs/test_internal_links.py`): one `rglob` line covering
`.cursor/skills/**/*.md`. The two blockers from the first attempt
(Task 3) were resolved first: the composition-layer `SKILL.md`
`loadings_dir/loadings.json` illustration was reworded so it no
longer parses as a checkable path, and the uncommitted deletion of
`docs/acceptance/v02_v03_matrix.md` was restored from HEAD (worktree
drift, disposition: restore). No checker-logic changes were needed.

## 5. Platform-wide session-admissibility guard (unknown ids + units sanity)

Task FQ-5A (2026-07-09) found the vendor's quote condition/indicator
population changed between the 2026-06-03 and 2026-06-29 cached
sessions (new indicator set 501–604; quote condition 34 absent from
`/v3/reference/conditions`), demonstrating that id vocabularies drift
under DI-09's ingest-everything design with no detection anywhere.
The pack scopes the defense to the new candidate's evidence pipeline
(unknown-id guard + units-sanity check,
`docs/research/prompt_pack_03b_print_eligibility.md` §6, joining the
Task-9 test plan). Extending it platform-wide — a per-session
ingest-health annotation or manifest field consumed by
`backtest_enforce_ingest_terminal_health`-style gating — touches
data-integrity behavior shared by every shipped alpha and needs its
own thread with parity-impact assessment. Spec pointer: 03b §6 and
§7.3 (open vendor questions on id 34, live-WS correction
dissemination, and the June-2026 population change).

## 6. C3 — Schema-require `structural_actor` (loader change)

Task 3 landed the archetype & structural-counterparty requirement as
authoring discipline in skill text only
(`.cursor/skills/microstructure-alpha/research-protocol.md`, Phase 1
rider), per the approved C3 disposition. Making `structural_actor` a
schema-required field is a `LayerValidator` / loader change with its
own test surface (new or amended gate, template + shipped-alpha
audit, load-failure tests) and is out of the doc-pack's scope. Spec
pointer: `docs/research/prompt_pack_01_skill_gap_report.md` §3 C3;
field definition `alphas/SCHEMA.md` (`structural_actor`, optional
Phase-3 field); validator anchor
`src/feelies/alpha/layer_validator.py`.

## 7. Cost-floor pre-filter for hypothesis-slate ranking (skill edit candidate)

Hypothesis-slate ranking must apply the realized cost-floor check
(dossier check d) as a hard pre-filter BEFORE ranking — the current
formula measures explanation quality but not economic viability (H1
lesson, 2026-07-10). Candidate skill edit for
`.cursor/skills/microstructure-alpha/research-protocol.md`; batch with
the next skill maintenance pass. Spec pointers:
`docs/research/prompt_pack_04a_slate_review.md` (check d method +
per-symbol floor table);
`docs/research/prompt_pack_04_hypothesis_slate.md` DISPOSITIONS Q1.
