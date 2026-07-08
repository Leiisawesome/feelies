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

## 4. Extend internal-link checking to `.cursor/skills/**/*.md`

Attempted as a pure `_DOC_FILES` data addition
(`tests/docs/test_internal_links.py`) during Task 3 (2026-07-08) and
reverted: two pre-existing citations fail under the extended scope —
composition-layer `SKILL.md` cites `loadings_dir/loadings.json` (a
config-dir-relative illustration, needs a `_PLACEHOLDER_PATH_TOKENS`
entry or rewording) and testing-validation `SKILL.md` links
`docs/acceptance/v02_v03_matrix.md`, which is deleted in the current
working tree (uncommitted deletion — intent unresolved). The thread
resolves both citations, then adds the one-line glob to `_DOC_FILES`.
Spec pointer: this entry; code anchor
`tests/docs/test_internal_links.py` (`_DOC_FILES`,
`_PLACEHOLDER_PATH_TOKENS`).

## 5. C3 — Schema-require `structural_actor` (loader change)

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
