# Research-Validation Math Audit (CPCV / DSR / pre-registration) — 2026-07-02

**Scope:** the statistical-significance bar before capital — `feelies.research.cpcv`,
`feelies.research.dsr`, `feelies.research.hypothesis`, `feelies.research.experiment`, and
the consuming evidence schemas / validators in `feelies.alpha.promotion_evidence`
(`CPCVEvidence`, `DSREvidence`, `validate_cpcv`, `validate_dsr`, `GateThresholds`).
Read-only, evidence-based. **No production code, test, config, baseline, or ledger was
modified.**

**This is a follow-up / verification audit.** A prior audit
(`docs/audits/research_validation_audit_2026-06-24.md`, branch `claude/dazzling-cori-rygvoz`)
found 2 P0s and 6 P1s. Commit `44702ec` ("Harden CPCV/DSR research-validation math
(P0/P1/P2 surgical fixes)", 2026-06-27) claims to have fixed most of them. **This audit does
not take that claim on trust** — every fix is independently re-derived against the cited
literature, numerically reproduced, and cross-checked against its test coverage, exactly as
if the June 24 findings did not exist. New defects found during that independent pass are
reported alongside the verification verdicts.

**Method:** static read of every in-scope module at `HEAD = 929e9fb6` (branch
`claude/research-validation-audit-2k69na`) against López de Prado (2018) *AFML* §7 + §12 and
Bailey & López de Prado (2014) *The Deflated Sharpe Ratio*, JPM 40(5):94–107; read-only
numerical repros via `uv run python`; the targeted and full `tests/research/` suites; `mypy
--strict` and `ruff` on the five in-scope modules. All `path:line` citations are against this
working tree.

**Read-only checks executed**

| Check | Result |
|-------|--------|
| `uv run python -c "import ast; ast.parse(...)"` on `kernel/orchestrator.py` | **parses clean** — the June-24 audit's blocking `SyntaxError` at `orchestrator.py:4795` is gone (fixed by unrelated commits `7125ebe`/`b923201` before this session) |
| `PYTHONHASHSEED=0 uv run pytest tests/research/ -q` (repo's contractually-pinned seed, `conftest.py:34`) | **277 passed**, 0 failed, 0 errors (was: collection **ERROR** on 2026-06-24 — e2e suite now runs) |
| `uv run pytest tests/research/test_promotion_pipeline_e2e.py tests/research/test_strict_mode_promotion_e2e.py -q` | **31 passed** (previously blocked from collection entirely) |
| `uv run mypy --strict` on all 5 in-scope modules | **Success: no issues found** |
| `uv run ruff check` on all 5 in-scope modules + `tests/research/` | **All checks passed** |
| Repro: 2026-06-24 §9.1 fabricated-`CPCVEvidence` bypass | **no longer passes** — `validate_cpcv` now returns 3 errors (mean/median mismatch + embargo floor) |
| Repro: purge multi-region "reach-across-gap" edge case (`N=6,k=2,h=3`, non-adjacent test groups) | brute-force ground truth **matches** the implementation exactly — no defect, see §3.2 |
| Repro (**new**): fabricated `DSREvidence` with `dsr=999.0 ≫ observed_sharpe=0.5` | **passes `validate_dsr` with zero errors** — see §4.4, a gap the hardening pass did not close |
| Repro: `evidence_to_metadata` / `metadata_to_evidence` round-trip for `CPCVEvidence` + `DSREvidence` | **lossless** |

Legend: **[BUG]** implementation defect · **[LIM]** documented simplification/limitation ·
**[DESIGN]** intentional modeling choice · **[FIXED]** verified resolved since 2026-06-24 ·
**[OPEN]** verified still present, unchanged or explicitly deferred · **[NEW]** not raised by
the prior audit.

---

## 1. Executive summary

1. **[FIXED][P0→closed] The purge is now label-overlap aware and I verified it correct,
   including an adversarial case the test suite doesn't cover.** `CPCVConfig.label_horizon_bars`
   (`cpcv.py:160`) drives a two-sided purge in `_purged_train_indices` (`cpcv.py:266-324`)
   that excises `[a-h, a-1]` and `[b+1, b+h+embargo_bars]` around every contiguous test
   region. I re-derived the "two length-`h` windows overlap iff `|j-t|<=h`" identity
   independently, then hand-traced a **multi-region, non-adjacent-test-group** case
   (`N=6, k=2, h=3`, test groups `(0,2)` → two regions separated by a gap) that the purge's
   per-region-independent implementation could plausibly get wrong; a brute-force
   ground-truth check confirms it is **exactly correct** (§3.2, §9.1). `h=0` is proven to
   reproduce the legacy behavior, so the previously-pinned references are unaffected.
2. **[FIXED][P0→closed] A functional leakage probe now exists and passes.**
   `TestPurgeFunctionalLeakageProbe` (`test_cpcv_unit.py:853-907`) builds a toy model that
   earns a return bonus from leaking training bars; with `label_horizon_bars=0` the spurious
   Sharpe is `>1.0`, with the true horizon it collapses to `<0.5` — a real, not just
   structural, demonstration that the purge does what it claims.
3. **[FIXED][P1→closed] The CPCV bootstrap p-value is no longer degenerate.**
   `block_bootstrap_p_value` (`cpcv.py:678-747`) is a circular moving-block bootstrap on the
   **per-bar pooled OOS return** (`mean_path_return_per_bar`, `cpcv.py:654-675`), not the
   correlated per-path Sharpes. I confirmed `test_identity_model_noise_does_not_floor_p_value`
   (`test_cpcv_unit.py:953-974`) reproduces the exact 2026-06-24 degeneracy scenario
   (identity-model OOS projection, all paths byte-identical) and now yields `p_value > 0.05`
   for pure noise instead of the old `1/(B+1)` floor. The legacy `lo_bootstrap_p_value` is
   retained for backward compatibility only, and its docstring's "conservative-leaning" claim
   is corrected to "anti-conservative" (`cpcv.py:610-623`).
4. **[FIXED][P1→closed] `validate_cpcv` recomputes instead of trusting.** It now recomputes
   `mean_sharpe`/`median_sharpe` from `fold_sharpes`, rejects non-finite folds, bounds
   `p_value` to `(0,1]`, requires `embargo_bars >= cpcv_min_embargo_bars` (new field, default
   1), and format-validates any non-empty `fold_pnl_curves_hash`
   (`promotion_evidence.py:515-586`). I re-ran the exact fabricated-evidence repro from the
   prior audit (`fold_sharpes=(0.01,)*8, mean_sharpe=2.0, embargo_bars=0`) — it now produces
   **3 errors** instead of `[]` (§9.1, item 1).
5. **[NEW][P1] The hardening is asymmetric: `validate_dsr` got range checks, not a
   consistency check, and a fabricated `dsr` still passes.** Unlike `CPCVEvidence` (which
   carries raw `fold_sharpes` to recompute against), `DSREvidence` does not carry `n_obs`,
   `threshold_sharpe`, or `trial_sharpe_variance` (`promotion_evidence.py:229-261`) — so
   `validate_dsr` (`promotion_evidence.py:589-633`) **cannot** recompute `dsr`/`dsr_p_value`
   from anything and only checks finiteness + range. I constructed
   `DSREvidence(observed_sharpe=0.5, trials_count=1000, dsr=999.0, dsr_p_value=0.0001, ...)`
   — a value that is mathematically impossible (`dsr = observed_sharpe − E[max]` and
   `E[max] >= 0` always, per `expected_max_sharpe`'s own contract, `dsr.py:246-291`) — and it
   **passes `validate_dsr` with zero errors** (§4.4, §9.1 item 4). A schema-free, immediate
   fix exists: gate `dsr <= observed_sharpe`.
6. **[FIXED, mechanism only][P1] CPCV/DSR units can now be made commensurate, but nothing
   forces it.** `build_cpcv_evidence` and `build_dsr_evidence` both gained
   `annualization_factor` (default `1.0`) (`cpcv.py:816`, `dsr.py:465`), so a caller *can*
   emit both evidences in the same annualized unit. But the default is still per-bar, and —
   see finding 8 below — **no caller in the repository invokes either builder for a real
   alpha**, so nothing exercises, defaults, or enforces consistent annualization end-to-end.
7. **[FIXED, honest-labeling only][P1] The DSR excess-vs-canonical naming confusion is now
   documented, not resolved.** `dsr.py:71-80`'s new "Naming vs. the paper" note and
   `DSREvidence`'s docstring (`promotion_evidence.py:244-248`) both now state plainly that
   the platform's `dsr` field is a Sharpe **excess**, and the canonical Bailey-LdP probability
   equals `1 − dsr_p_value`. The glossary (`.cursor/rules/platform-invariants.mdc:74`) is
   corrected to match. The underlying quantity is **unchanged** — this is a documentation fix,
   not a redefinition — which is the right call given `dsr_min=1.0` cannot be a probability
   bound, but a reader of only the glossary before this fix could not have known that.
8. **[NEW][P2] Every fix in this pass is a library capability, not a wired pipeline —
   confirmed via exhaustive grep.** The only non-test, non-library reference to
   `CPCVConfig`/`build_cpcv_evidence`/`build_dsr_evidence` anywhere in the repository is a
   `README.md` usage snippet using all defaults. There is still no operator/research script
   that derives `label_horizon_bars` from an alpha's declared `horizon_seconds` /
   `expected_half_life_seconds`, and no orchestration that threads one consistent
   `annualization_factor` into both builders for the same alpha. Before this fix, correct
   usage wasn't even *expressible*; now it is expressible, but nothing yet enforces it.
9. **[OPEN, unchanged][P1] Inv-2 pre-registration remains entirely unenforced.**
   `hypothesis.py` and `experiment.py` are still pure `Protocol` stubs, byte-for-byte
   unchanged from 2026-06-24 (confirmed by direct diff — this was explicitly deferred as
   "P1-6" in the hardening commit, not silently dropped).
10. **[OPEN, unchanged][P2] `fold_pnl_curves_hash` is still a dangling pointer.** No
    research-artefact store exists; the hash is now format-validated (`sha256:` + 64 hex
    chars, `promotion_evidence.py:506-512`) when present, but an **empty** hash is still
    accepted (`cpcv_min_folds`/embargo gates don't require it), and even a well-formed one
    resolves to nothing retrievable. `CPCVEvidence`'s own docstring
    (`promotion_evidence.py:211-213`) still asserts the hash is "persisted in the
    research-artefact store" — a store that, per the research-workflow skill's own "Not
    shipped" section, does not exist.
11. **[OPEN, unchanged][P2] No family-wise (cross-alpha) multiple-testing correction.**
    Confirmed by exhaustive grep — zero hits for Bonferroni/Benjamini-Hochberg/family-wise
    logic anywhere in `src/`. DSR still deflates each alpha only by its own `trials_count`.
12. **[OPEN, unchanged][P2] DSR cross-version determinism caveat stands.**
    `standard_normal_quantile` (`dsr.py:163-177`) still delegates to
    `statistics.NormalDist().inv_cdf`, whose last-ULP can move across CPython minor versions;
    nothing pins this. Partially offset by finding 13 below (a new independent known-answer
    test), which at least confirms *correctness*, though not byte-exact cross-version replay.
13. **[NEW][GOOD] A genuine literature known-answer test now exists for DSR.**
    `TestExpectedMaxSharpeKnownAnswer` (`test_dsr_reference.py:239-278`) checks
    `expected_max_sharpe` against tabulated order-statistic values for `E[max of N iid
    N(0,1)]` (Harter 1961 / Royston 1982) — independent of the module's own formula, unlike
    every other `*_reference.py` check. I independently cross-checked the three tabulated
    constants (`N=10,100,1000`) against the standard asymptotic extreme-value approximation
    and they are consistent (§9.2). This closes the prior audit's P2-5.
14. **[NEW][P2] The new purge parameter has zero property-based (Hypothesis) coverage.**
    `test_cpcv_props.py`'s shared strategy `_cpcv_config_and_n_bars()` (`test_cpcv_props.py:42-50`)
    never varies `label_horizon_bars` — it is always the default `0`. All coverage of the
    single most safety-critical fix in this pass (the purge) is 6 hand-picked example tests
    (`test_cpcv_unit.py:801-907`), none of which use `k_test_groups >= 2` with regions close
    enough for their purge windows to interact. I found and closed this exact gap by hand
    (finding 1); it should be a property, not an audit footnote.
15. **[OPEN, minor][P2] `CPCVEvidence.mean_pnl` remains completely unchecked** — not even a
    finiteness check, let alone a recompute (`promotion_evidence.py:515-586` has no `mean_pnl`
    validation). Lower severity than finding 5 because no `GateThresholds` field reads
    `mean_pnl`, so a fabricated value cannot flip a gate — it can only mislead a human
    reader/forensic reviewer.

**Bottom line:** the 2026-06-24 P0s are genuinely closed, and I could not find a way to
reopen them. The P1 backlog is mostly closed for CPCV and only partially closed for DSR — the
DSR validator's hardening is cosmetic (range checks) rather than structural (no recompute is
possible given the current schema), which is a materially different risk posture than the
commit message's grouped description suggests. The deferred P1/P2 items (pre-registration,
artefact store, family-wise correction, cross-version pinning) are exactly as open as the
hardening commit says they are — nothing was silently dropped or silently worsened.

---

## 2. Method inventory

| Quantity | Where | Definition as implemented | Status vs. 2026-06-24 | Literature check |
|----------|-------|---------------------------|------------------------|-------------------|
| `n_groups (N)`, `k_test_groups (k)`, `embargo_bars (e)`, `label_horizon_bars (h)` | `cpcv.py:123-177` | hyperparameters; `N≥2`, `1≤k<N`, `e≥0`, `h≥0` (new) | `h` is **new** | AFML §12.4 partition params + §7.4.1 label horizon |
| `n_combinations` | `cpcv.py:180-184` | `C(N,k)` | unchanged | ✓ φ = C(N,k) |
| `n_paths` | `cpcv.py:186-192` | `C(N-1,k-1)` | unchanged | ✓ (k/N)·C(N,k) = C(N-1,k-1) |
| group assignment | `cpcv.py:231-258` | contiguous; remainder to early groups | unchanged | ✓ KFold convention |
| purge | `cpcv.py:266-324` | **two-sided, label-horizon-aware**: `[a-h,a-1] ∪ [b+1,b+h+e]` per contiguous test region | **FIXED** (was index-overlap only) | ✓ now matches AFML §7.4.1 for fixed-horizon labels |
| embargo | folded into the forward purge window, `cpcv.py:316-321` | `e` bars *after* `h`, post-test only | unchanged arithmetic, now composed with `h` | ✓ AFML §7.4.2 |
| path reconstruction | `cpcv.py:375-426` | unchanged | unchanged | ✓ AFML §12.5 |
| `sharpe_ratio` | `cpcv.py:533-574` | `fmean/pstdev` (ddof=0), scale-normalized, **no annualization by itself** | unchanged | population Sharpe |
| `block_bootstrap_p_value` | `cpcv.py:678-747` | circular moving-block bootstrap (Politis-Romano 1992) on per-bar pooled OOS returns, `H0: mean=0` | **NEW**, replaces the gate's use of `lo_bootstrap_p_value` | correctly targets serial correlation; block length = `embargo_bars` |
| `lo_bootstrap_p_value` | `cpcv.py:582-651` | legacy per-path iid bootstrap; **no longer feeds the gate** | retained, docstring corrected (anti-conservative) | reference/back-compat only |
| `fold_pnl_curves_sha256` | `cpcv.py:777-803` | sha256 over canonical float-repr of per-bar returns | unchanged | content hash; no store (still) |
| `build_cpcv_evidence` | `cpcv.py:811-932` | now takes `annualization_factor` (default 1.0), scales `fold_sharpes` | **annualization added** | mechanism correct; default unchanged |
| `CPCVEvidence` | `promotion_evidence.py:188-226` | unchanged fields | docstrings corrected (path vs fold, p-value method) | — |
| `probabilistic_sharpe_ratio` | `dsr.py:185-238` | `Φ((SR-SR*)√(T-1)/√(1-γ₃SR+((γ₄-1)/4)SR²))` | unchanged | ✓ Bailey-LdP eq. 1 |
| `expected_max_sharpe` | `dsr.py:246-291` | `√V·((1-γ)Φ⁻¹(1-1/N)+γΦ⁻¹(1-1/(Ne)))` | unchanged | ✓ Bailey-LdP eq. 7; **new** independent known-answer test |
| `deflated_sharpe` | `dsr.py:341-404` | `dsr_value=SR-E[max]`; `dsr_p_value=1-PSR(E[max])` | unchanged (documented, not redefined) | naming caveat now documented |
| default trial variance | `dsr.py:380-381` | `1/(n_obs-1)` when omitted | **now warns** (`build_dsr_evidence`, `dsr.py:524-533`) | still the weakest honest deflation when used |
| `DSREvidence` | `promotion_evidence.py:229-261` | unchanged fields — **still no `n_obs`** | docstring corrected | structurally cannot support a consistency recompute |
| `GateThresholds` | `promotion_evidence.py:364-449` | **new** `cpcv_min_embargo_bars=1`; all else unchanged | field added | — |
| `validate_cpcv` | `promotion_evidence.py:515-586` | folds≥min, embargo≥min (new), mean/median **recomputed and matched** (new), non-finite rejected (new), p∈(0,1] (new), hash format checked (new) | **materially hardened** | closes the 2026-06-24 fabrication repro |
| `validate_dsr` | `promotion_evidence.py:589-633` | dsr≥min, p≤max, trials>0, **all fields finite** (new), p∈[0,1] (new) | **range-hardened only** | **no consistency check exists or is possible with the current schema** |
| Hypothesis / Experiment | `hypothesis.py`, `experiment.py` | frozen dataclasses + Protocol stubs | **byte-identical to 2026-06-24** | Inv-2 still unenforced |

---

## 3. CPCV audit (deep dive)

### 3.1 Combinatorics and path reconstruction — unchanged, still correct

Not touched by the hardening commit and not re-litigated in depth here; the 2026-06-24
audit's derivation (`n_combinations=C(N,k)`, `n_paths=C(N-1,k-1)`, path reconstruction per
AFML §12.5) still holds by inspection of the unchanged code (`cpcv.py:180-192, 375-426`) and
passing tests (`test_cpcv_unit.py`, `test_cpcv_props.py`, `test_cpcv_reference.py`, all
green). I confirmed via `git diff 44702ec^ 44702ec -- tests/research/test_cpcv_reference.py`
that this file has **zero changes** in the hardening commit, so the pinned `N=4,k=2` path
enumeration and reference Sharpes are untouched — consistent with the commit's claim that
`h=0` reproduces legacy behavior exactly.

### 3.2 Purge — FIXED, and independently verified beyond the shipped tests

`_purged_train_indices` (`cpcv.py:266-324`) now takes `label_horizon_bars` (`h`) and computes,
per contiguous test region `[a,b]`:

```
backward purge:  [max(0, a-h), a-1]                          (cpcv.py:314)
forward purge + embargo: [b+1, min(b+1+h+embargo_bars, n_bars))  (cpcv.py:318-321)
```

**Re-derivation.** Two length-`h` label windows `[j,j+h]` and `[t,t+h]` overlap iff
`j <= t+h ∧ t <= j+h`, i.e. `|j-t| <= h` — I re-derived this independently before reading the
docstring and it matches `cpcv.py:277-283`'s claim exactly. For a single test bar `t`, the
purge set is `{j : |j-t| <= h} \ {t}` = `[t-h,t-1] ∪ [t+1,t+h]`, which is exactly what the
code computes; for a contiguous region `[a,b]`, the union of per-bar `h`-balls collapses to
`[a-h,b+h]` because the region is convex — also exactly what the code computes. `h=0`
collapses to "remove only the test bars," reproducing the legacy behavior (verified:
`test_label_horizon_zero_is_legacy_behavior`, `test_cpcv_unit.py:806-812`).

**The case I checked that the shipped tests don't: multiple, non-adjacent test regions with
`h` large enough to reach across the gap between them.** The implementation computes each
region's purge window independently and takes the union via a Python `set` (`cpcv.py:311,
322`). This is only correct if `⋃ᵢ h-ball(regionᵢ) == h-ball(⋃ᵢ regionᵢ)` — true in general
because purge membership is existential ("`j` is purged if *some* test bar `t` is within `h`"
= "`j` is purged if some region's ball contains it"), so per-region independent computation,
unioned, is always correct regardless of region proximity. I verified this is not just a
paper argument by constructing the adversarial case directly:

```
CPCVConfig(n_groups=6, k_test_groups=2, label_horizon_bars=3, embargo_bars=0), n_bars=12
test_group_ids=(0,2) -> test_indices=(0,1,4,5)   [two regions: (0,1) and (4,5), gap={2,3}]
implementation train_indices = (9, 10, 11)
brute-force ground truth (∀j: purged iff ∃t∈test with |j-t|<=3) = (9, 10, 11)
MATCH: True
```

(reproduced in §9.1 item 6). **No defect found.** This is the same conclusion the shipped
`TestPurgeFunctionalLeakageProbe` and `TestLabelHorizonPurge` classes support, but those tests
only exercise `k_test_groups=1` (a single test group ⇒ always one contiguous region) or
widely-separated regions where the interaction never occurs (`test_no_train_bar_within_horizon_of_any_test_bar`,
`test_cpcv_unit.py:834-845`, uses `N=6,k=2,h=3,n_bars=60` — group size 10, so even
non-adjacent test groups leave a 10-bar gap, far exceeding `h=3`; the interaction case never
triggers). See §7 for the resulting test-gap finding.

### 3.3 Functional leakage probe — FIXED, closes the prior P0-2

`TestPurgeFunctionalLeakageProbe` (`test_cpcv_unit.py:853-907`) is a genuine functional check,
not just an index-membership check: a toy "leaky model" adds a `+0.02` return bonus to any
test bar whose true label window (horizon 2) overlaps a *surviving* training bar. With
`label_horizon_bars=0` (blind purge), the leak survives and `mean_sharpe > 1.0`
(`test_horizon_blind_purge_leaks_spurious_alpha`); with `label_horizon_bars=2` (the true
horizon), the leaking neighbors are excised and the Sharpe collapses to near zero
(`test_horizon_aware_purge_collapses_the_leak`, asserting `abs(purged) < 0.5` and
`purged < leaky - 1.0`). This is exactly the "known-answer" leakage probe the 2026-06-24
audit's P0-2 backlog item asked for, and it demonstrates causally (not just structurally)
that the purge prevents the failure it's designed to prevent — for the single-region case
(see §3.2/§7 for the multi-region gap).

### 3.4 Embargo — unchanged arithmetic, now composed correctly with the purge

The embargo's own arithmetic (post-test, length `embargo_bars`, truncated at `n_bars`, never
excising a test bar) is unchanged from 2026-06-24 and was already verified correct there. The
new composition — forward exclusion is `[b+1, b+h+embargo_bars]`, i.e., the label-purge window
and the embargo window are computed as one contiguous range (`cpcv.py:318-321`) — is correct
because the two exclusions are adjacent with no gap (`h` purge ends at `b+h`, embargo starts
at `b+h+1`) and serve conceptually different purposes (label-overlap vs. serial-correlation
buffer) but require no different treatment mathematically. `test_label_horizon_and_embargo_stack_forward`
(`test_cpcv_unit.py:826-832`) pins this exactly: `h=1, embargo=2` on a `{4,5}` test region
purges `{3}` backward and `{6,7,8}` forward (`h+embargo=3` bars) — I re-verified this by hand
and it is correct.

### 3.5 The block-bootstrap p-value — FIXED, and the fix targets the right quantity

The 2026-06-24 audit's most damaging CPCV finding was that the gate's p-value collapsed to
the `1/(B+1)` floor for **both** strong and weak (noise) alpha under the identity-model OOS
projection used by every existing integration path, because the per-path Sharpes were
byte-identical and an iid bootstrap over identical values is degenerate by construction.

`block_bootstrap_p_value` (`cpcv.py:678-747`) fixes this at the root by changing *what* is
bootstrapped: instead of the `n_paths` correlated per-path Sharpes, it operates on the
`n_bars`-length **per-bar mean-across-paths return series** (`mean_path_return_per_bar`,
`cpcv.py:654-675`) — which, even under an identity-model projection, is simply the original
per-bar return series and is not degenerate. It resamples in length-`block_size` contiguous
(circular-wrapped) blocks rather than iid draws, so it also correctly preserves the serial
correlation the embargo is meant to model (Politis & Romano 1992) — a fix to the
"anti-conservative" bias identified in the prior audit's §3.5.2, not just the degeneracy.
`build_cpcv_evidence` wires `block_size = max(1, config.embargo_bars)` (`cpcv.py:917`) — using
the platform's own stated serial-correlation length as the block length is a reasonable,
literature-consistent default.

**Verification.** I ran `test_identity_model_noise_does_not_floor_p_value`
(`test_cpcv_unit.py:953-974`) directly — it reconstructs the *exact* degenerate scenario from
the 2026-06-24 repro (`N=10,k=2,embargo=5`, identity OOS projection, pure Gaussian noise) and
asserts `len({round(s,12) for s in ev.fold_sharpes}) == 1` (paths are still degenerate, as
before) **and** `ev.p_value > 0.05` (the gate no longer floors). This passed. Separately,
`test_discriminates_signal_from_noise` (`test_cpcv_unit.py:916-924`) confirms `p_strong < 0.05`
and `p_noise > 0.20` on independently-generated strong-vs-noise series. **The
`cpcv_max_p_value` gate is no longer a no-op.**

One residual observation: `block_size = max(1, config.embargo_bars)` silently becomes `1`
(iid per-bar bootstrap) whenever `embargo_bars = 0` — but `cpcv_min_embargo_bars = 1` is now
enforced by `validate_cpcv` (§3.6), so in practice a passing evidence package always has
`embargo_bars >= 1` and thus `block_size >= 1` reflecting at least some serial-correlation
structure. This is a reasonable interlock, though it is implicit (via the separate gate) not
explicit in `block_bootstrap_p_value`'s own contract.

### 3.6 Validator hardening — FIXED for CPCV, and I could not find a bypass

`validate_cpcv` (`promotion_evidence.py:515-586`) now performs, in order: `fold_count`
threshold; `len(fold_sharpes)==fold_count`; non-finite rejection on every fold Sharpe;
**recomputation** of `mean_sharpe`/`median_sharpe` from `fold_sharpes` via
`math.isclose(rel_tol=1e-6, abs_tol=1e-9)` (`promotion_evidence.py:552-563`); the
`cpcv_min_mean_sharpe` threshold; `p_value ∈ (0,1]` **and** `<= cpcv_max_p_value`
(`:569-572`); `embargo_bars >= cpcv_min_embargo_bars` (new field, default `1`, `:573-577`);
and format validation of any non-empty `fold_pnl_curves_hash` via `_is_well_formed_curve_hash`
(`promotion_evidence.py:506-512`, `:578-584`).

I re-ran the exact 2026-06-24 §9.1 repro:

```python
CPCVEvidence(fold_count=8, embargo_bars=0, fold_sharpes=(0.01,)*8,
             mean_sharpe=2.0, median_sharpe=2.0, p_value=0.0001, fold_pnl_curves_hash="")
validate_cpcv(...) ->
  ['CPCV mean_sharpe 2.0000 does not match mean(fold_sharpes)=0.0100 (fabricated/drifted summary?)',
   'CPCV median_sharpe 2.0000 does not match median(fold_sharpes)=0.0100 (fabricated/drifted summary?)',
   'CPCV embargo_bars 0 < 1 required (a zero-embargo run applies no serial-correlation guard)']
```

Three errors, not zero. I also tried a syntactically-plausible-but-fake hash
(`"not-a-real-hash"`) and it is correctly rejected as malformed (§9.1 item 2). **I could not
construct an internally-consistent-looking `CPCVEvidence` that bypasses the gate** short of
supplying `fold_sharpes` that are simply real-looking-but-fabricated numbers with a correct
mean/median and a syntactically valid (but content-unverifiable) hash — which is an inherent
limit of validating a summary object rather than re-deriving from raw returns, not a defect in
this pass (see §7 for the residual "internal consistency ≠ ground truth" caveat, which is
structural and would require re-running CPCV from the raw return series to close entirely).

**One residual, minor, unguarded field:** `mean_pnl` (`CPCVEvidence.mean_pnl`,
`promotion_evidence.py:224`) is never validated — not recomputed, not even checked for
finiteness. Lower severity than the DSR gap in §4.4 because no `GateThresholds` field reads
`mean_pnl`, so a fabricated value cannot flip a pass/fail decision; it can only mislead a
human reading the evidence package (forensics, `feelies promote inspect`).

---

## 4. DSR audit — term-by-term vs Bailey & López de Prado (2014)

### 4.1 PSR (eq. 1) and expected-max-Sharpe (eq. 7) — unchanged, still correct

Neither formula was touched by the hardening commit. I independently re-derived both:

```
var_term = 1 - γ₃·SR̂ + ((γ₄-1)/4)·SR̂²                    (dsr.py:225-229)
z = (SR̂ - SR*)·√(T-1) / √(var_term);  PSR = Φ(z)          (dsr.py:237-238)
```

matches eq. 1 verbatim (`γ₃`=skew, `γ₄`=non-excess kurtosis, Gaussian `γ₄=3 ⇒ var_term =
1+SR̂²/2`). The non-positive-variance guard (`dsr.py:230-236`) matches the paper's §3
misspecification note.

```
E[max SR] = √V · ((1-γ)·Φ⁻¹(1-1/N) + γ·Φ⁻¹(1-1/(N·e)))     (dsr.py:287-291)
```

matches eq. 7 verbatim, `γ = 0.5772156649015328606` (`dsr.py:146`) correct to the digits
shown. Edge cases `N=1 → 0`, `V=0 → 0` (`dsr.py:285-286`) are the right degenerate limits — I
confirmed `expected_max_sharpe`'s formula can never return a negative value for any valid
input (`N>=2 ⇒ 1-1/N >= 0.5 ⇒ Φ⁻¹(...) >= 0`, similarly for the second term, and `γ ∈ (0,1)`
so the convex combination is non-negative) — this fact directly underpins finding §4.4 below.

**No defect. No regression.**

### 4.2 New: an independent, literature-sourced known-answer test — closes prior P2-5

`TestExpectedMaxSharpeKnownAnswer` (`test_dsr_reference.py:239-278`) checks
`expected_max_sharpe(n_trials=N, trial_sharpe_variance=1.0)` — which, at `V=1`, is exactly
the closed-form estimate of `E[max of N iid N(0,1)]` — against tabulated order-statistic
values (`N=10 → 1.53875`, `N=100 → 2.50759`, `N=1000 → 3.24147`; cites Harter 1961 / Royston
1982) within a documented `rel_tol=0.03`. This is qualitatively different from every other
`*_reference.py` check in the codebase (which pin a value computed by re-implementing the
*same* formula — a drift tripwire, not an independent check). I independently sanity-checked
the three tabulated constants against the standard crude asymptotic extreme-value
approximation `E[max_n] ≈ √(2 ln n) − (ln ln n + ln 4π)/(2√(2 ln n))` (§9.2) and they land in
the expected range and ordering; I did not have offline access to reproduce Harter/Royston's
exact tables byte-for-byte, but the values are consistent with well-known order-statistic
constants I can independently corroborate (e.g., `E[max of 10]≈1.539` and `E[max of
100]≈2.51` are commonly-cited figures for the standard normal maximum). **This materially
strengthens the DSR test suite's claim to be checking something other than its own algebra.**

### 4.3 DSR composition and the excess-vs-canonical naming — now honestly documented (unchanged math)

`deflated_sharpe` (`dsr.py:341-404`) still returns `dsr_value = observed - E[max]` (an excess,
not a probability) and `dsr_p_value = 1 - PSR(E[max])`. This is now clearly flagged in three
places: the module docstring's "Naming vs. the paper" note (`dsr.py:71-80`), the
`DSREvidence` field docstring (`promotion_evidence.py:244-248`, explicitly: "NOTE: this is
the platform's redefinition, NOT the canonical Bailey-LdP DSR"), and the glossary
(`.cursor/rules/platform-invariants.mdc:74`: "Platform `dsr` is Sharpe units, not canonical
BLP probability"). I confirmed numerically that the canonical-vs-excess relationship is
exactly as documented (§9.1 item 3): for `observed=0.5, n_obs=252, n_trials=100`,
`dsr_value=0.3403`, `psr=1.0000`, `dsr_p_value≈0.0000`, and `1-dsr_p_value=1.0000` is the
canonical Bailey-LdP DSR — matching the 2026-06-24 audit's own numbers exactly (no
regression). This is a **documentation fix**, correctly scoped — changing the underlying
quantity would break `dsr_min=1.0`'s meaning as a Sharpe-excess bar, and the fix's authors
evidently made that judgment call explicitly rather than silently. The statistical half
(`dsr_p_value <= 0.05 ⇔ canonical DSR >= 0.95`) was already correct and remains so.

### 4.4 [NEW] `validate_dsr`'s hardening is range-only; a mathematically-impossible `dsr` still passes

This is the most significant finding of this follow-up audit. The hardening commit's message
groups CPCV and DSR validator changes together ("`validate_cpcv` is no longer trust-on-submit
… `validate_dsr` rejects non-finite moments/DSR and a `dsr_p_value` outside `[0, 1]`"), which
reads as a matched pair of fixes. **They are not equivalent.** `validate_cpcv`'s hardening is
a genuine internal-consistency check (recompute `mean`/`median` from the raw `fold_sharpes`
the evidence itself carries). `validate_dsr`'s hardening (`promotion_evidence.py:605-615`) is
purely range/finiteness — `math.isfinite` on five fields and a `[0,1]` bound on
`dsr_p_value`. It has **no way** to check whether `dsr`/`dsr_p_value` are actually consistent
with `observed_sharpe`/`trials_count`/`skewness`/`kurtosis`, because — unlike
`CPCVEvidence.fold_sharpes` — **`DSREvidence` does not carry the sample size `n_obs`, the
threshold `E[max]`, or the `trial_sharpe_variance` used to compute it**
(`promotion_evidence.py:229-261`; confirmed by inspecting `DSREvidence.__dataclass_fields__`
directly, §9.1 item 4: `n_obs` is absent). `build_dsr_evidence` computes a `DSRComputation`
(`dsr.py:299-338`) that *does* carry `n_obs`, `threshold_sharpe`, and `psr` — but
`build_dsr_evidence` (`dsr.py:534-543`) discards all three before constructing the
`DSREvidence`, keeping only `dsr_value` and `dsr_p_value`. The richer, checkable
intermediate result is computed and thrown away.

**Repro** (§9.1 item, reproduced exactly):

```python
fab = DSREvidence(observed_sharpe=0.5, trials_count=1000, skewness=0.0, kurtosis=3.0,
                   dsr=999.0, dsr_p_value=0.0001)
validate_dsr(fab) -> []   # PASSES

fab2 = DSREvidence(observed_sharpe=0.2, trials_count=5, skewness=0.0, kurtosis=3.0,
                    dsr=50.0, dsr_p_value=0.001)
validate_dsr(fab2) -> []   # PASSES
```

Both are mathematically impossible for a real computation: `dsr_value = observed_sharpe -
E[max]` and `E[max] >= 0` always (§4.1), so `dsr <= observed_sharpe` must hold for any
honestly-derived `DSREvidence` — yet the validator has no way to know that, and no way to
enforce it. This is functionally the *same* class of gap the June-24 audit found in
`validate_cpcv` (finding #2 there) and that this pass explicitly, successfully closed for
CPCV — but for DSR it remains wide open, and is structurally harder to close because it needs
a schema change, not just a validator change.

**Severity:** P1, on the same basis as the (now-fixed) CPCV finding it mirrors — it directly
weakens confidence in the PAPER→LIVE gate today, for any caller that doesn't independently
guard its own `DSREvidence` construction.

### 4.5 Default trial-variance warning — FIXED (soft), same underlying weakness

`build_dsr_evidence` now emits a `UserWarning` whenever `trial_sharpe_variance` is omitted and
`trials_count > 0` (`dsr.py:509-533`), naming the exact failure mode: the iid-Gaussian null
floor `1/(n_obs-1)` is "the WEAKEST honest deflation." I confirmed the warning fires
(`test_iid_null_variance_default_warns`, `test_dsr_unit.py:560-563`) and is suppressed
correctly when an explicit variance is passed or `trials_count=0`
(`test_explicit_variance_does_not_warn`, `test_zero_trials_does_not_warn`,
`test_dsr_unit.py:566-583`). This is a **soft** fix — a warning, not a validator-level block
— so a caller that ignores Python warnings (the default in most non-interactive pipelines)
gets the same weak deflation as before with no enforcement difference at the gate. The
underlying mathematical weakness (documented already in 2026-06-24 §4.7 and unchanged here)
is exactly as strong/weak as before; only the operator-facing signal improved. Given there is
still no real caller of `build_dsr_evidence` for an actual alpha (§1 finding 8), this warning
currently has no audience in production.

### 4.6 `trials_count` honesty — unchanged, still self-reported

`validate_dsr` still only checks `trials_count > 0` (`promotion_evidence.py:626-631`); the
count remains entirely operator-supplied with no link to a real experiment registry (which
doesn't exist — see §5.3). Unchanged from 2026-06-24, not addressed by this pass, not claimed
to be.

---

## 5. Determinism & provenance audit

### 5.1 RNG / seeding — still good, extended correctly to the new bootstrap

`block_bootstrap_p_value` (`cpcv.py:678-747`) uses `random.Random(seed)` exactly like the
legacy `lo_bootstrap_p_value`, threaded through `build_cpcv_evidence`'s `seed` parameter
(`cpcv.py:818, 919`). `test_deterministic_under_same_seed`
(`test_cpcv_unit.py:926-931`) confirms bit-identical output across two calls. DSR remains
pure closed-form, no PRNG. I found no new unseeded randomness introduced by this pass.

### 5.2 Test suite runs clean under the contractually-pinned hash seed

`conftest.py:34` asserts `PYTHONHASHSEED=0` is required for full Inv-5 compliance (set/dict
iteration order). I re-ran the full `tests/research/` suite under `PYTHONHASHSEED=0`
explicitly: **277 passed**, matching the unpinned run. I additionally checked `cpcv.py`'s use
of `set`/`dict` internally (`_purged_train_indices`'s `test_set`/`excluded` sets,
`reconstruct_paths`'s `splits_by_group` dict) — every one of them is only used for membership
testing or is built via ordered iteration (`range`, `sorted`) before being converted back to a
tuple, so none of the public outputs are actually hash-order-dependent. This is a
by-inspection confirmation, not a new defect.

### 5.3 Pre-registration (Inv-2) — confirmed unchanged, still fully unenforced

`git diff 44702ec^ 44702ec -- src/feelies/research/hypothesis.py src/feelies/research/experiment.py`
shows **zero changes**. Both remain `Protocol` stubs with frozen-dataclass records and no
concrete registry implementation (`hypothesis.py:14-43`, `experiment.py:14-53`). Every
2026-06-24 finding here — no append-only log, no enforced pre-results registration, no link
from `trials_count` to a real experiment count — still applies verbatim. This is explicitly
listed as deferred ("P1-6 … deferred") in the hardening commit message, so its continued
absence is not a surprise, but it remains the single largest structural gap against Inv-2
("falsifiability before testing").

### 5.4 `fold_pnl_curves_hash` — format-checked now, still not a verified pointer

New: `_is_well_formed_curve_hash` (`promotion_evidence.py:506-512`) requires the `sha256:` +
64-lowercase-hex-chars shape when the hash is non-empty. This closes the "any garbage string
passes" gap. It does **not** close, and was not claimed to close, the deeper gap: there is
still no research-artefact store (confirmed: no `ArtifactStore`/`research_artifact` module
anywhere in `src/`, only a docstring reference), so a syntactically well-formed hash still
resolves to nothing retrievable, and an **empty** hash is still fully acceptable (the field
default is `""`, and no `GateThresholds` field requires non-empty). Provenance integrity is
therefore "re-run the builder and compare bytes," not "fetch and verify" — unchanged from
2026-06-24.

### 5.5 Cross-version determinism (DSR) — unchanged caveat, partially offset

`standard_normal_quantile` (`dsr.py:163-177`) is untouched; it still delegates to
`statistics.NormalDist().inv_cdf`, whose last-ULP behavior is only documented as stable within
a CPython minor version. `test_dsr_reference.py`'s original reference tests still compare
against the running interpreter's own re-derivation (a formula-drift tripwire, not a
cross-version guarantee). The **new** `TestExpectedMaxSharpeKnownAnswer` (§4.2) is a step in
the right direction for *correctness* confidence but does not change the *byte-identical
cross-machine replay* contract — its `rel_tol=0.03` tolerance is far looser than bit-identical
replay requires. This P2 item is exactly as open as the hardening commit says it is.

---

## 6. Statistical soundness

### 6.1 Annualization — mechanism fixed, still not wired end-to-end

Both builders now support an `annualization_factor` that would make `cpcv_min_mean_sharpe`
and `dsr_min` commensurate (§1 finding 6, §2 method-inventory row). I verified the DSR side
scales `observed_sharpe` and `dsr` but correctly leaves `dsr_p_value` unscaled
(`test_annualization_scales_observed_and_dsr`, `test_dsr_unit.py:425-449`), and the CPCV side
scales every `fold_sharpe` (hence `mean_sharpe`/`median_sharpe`) but correctly leaves
`p_value` unscaled (`cpcv.py:896, 911-920`). Both defaults remain `1.0` (per-bar), and — per
§1 finding 8 — there is no real caller threading a single consistent factor into both for the
same alpha, so the previously-identified ~16× (√252) unit mismatch is **avoidable now, not yet
avoided**. This is a meaningfully different, more precise characterization than 2026-06-24's
"the two gates are in different units" — the gates *can* now share units; whether they *do*
depends entirely on a caller that doesn't yet exist.

### 6.2 Sample-size adequacy per fold and CPCV path correlation — unchanged framing, less risky in practice

The 2026-06-24 observation that CPCV's `C(N-1,k-1)` paths cover the same bars and can be
highly correlated (effective sample size far below the nominal path count) is a structural
property of the algorithm, not something this hardening pass touches or could touch. Its
practical bite is reduced, though not eliminated, by the block-bootstrap fix (§3.5): the gate
p-value is no longer derived from the correlated per-path Sharpes at all, so the specific
"effective size ≈ 1" degeneracy from 2026-06-24 no longer manufactures false significance.
`cpcv_min_folds=8` (`promotion_evidence.py:403`) still gates the raw path *count*, which
remains a correlated-samples-dressed-as-independent-samples framing at the `mean_sharpe`
threshold (not the p-value) — this residual is unchanged and not previously flagged as a
separate item, so I list it here for completeness rather than as a new backlog entry.

### 6.3 Multiple testing — per-alpha only, confirmed unchanged

Exhaustive grep for `bonferroni|benjamini|family.wise|familywise` (case-insensitive) across
`src/` returns zero hits outside test/doc files. DSR still deflates only by the single
alpha's own `trials_count`; there is no cross-alpha correction. Unchanged from 2026-06-24,
explicitly deferred (P2-2) by the hardening commit.

### 6.4 Independence assumptions — CPCV side improved, DSR side unchanged

The 2026-06-24 audit noted CPCV's bootstrap treated correlated paths as iid (anti-conservative)
while DSR treats correlated trials as iid-counted. The CPCV side is substantially improved:
the block-bootstrap (§3.5) explicitly models serial correlation via `block_size`, rather than
ignoring it. The DSR side (`expected_max_sharpe`'s `Φ⁻¹(1-1/N)` term assuming independent
trials) is untouched — for CPCV-derived `trials_count` (paths/folds), the trials are known to
be correlated by construction, and nothing in `deflated_sharpe` or `build_dsr_evidence`
accounts for that. Unchanged, not addressed by this pass.

---

## 7. Test gap matrix (delta vs. 2026-06-24)

| Invariant / property | Test(s) | 2026-06-24 status | 2026-07-02 status |
|----------------------|---------|--------------------|--------------------|
| CPCV combinatorics, path reconstruction | `test_cpcv_unit.py`, `test_cpcv_props.py` | covered | **unchanged, covered** |
| Embargo arithmetic (post-test, truncation) | `test_cpcv_unit.py`, `test_cpcv_props.py` | covered | **unchanged, covered** |
| Purge prevents label-overlap leakage (structural) | — | MISSING | **covered** — `TestLabelHorizonPurge` (`test_cpcv_unit.py:801-845`), incl. an exhaustive-style check `test_no_train_bar_within_horizon_of_any_test_bar` |
| Purge prevents label-overlap leakage (**property-based**, wide random sweep) | — | MISSING | **still MISSING** — `label_horizon_bars` is never varied by `_cpcv_config_and_n_bars()` (`test_cpcv_props.py:42-50`); see finding §1.14 |
| Purge/embargo prevent a *measurable* Sharpe inflation (functional leakage probe) | — | MISSING | **covered** — `TestPurgeFunctionalLeakageProbe` (`test_cpcv_unit.py:853-907`), but only for `k_test_groups=1` (single contiguous region); multi-region leakage is untested |
| CPCV p-value discriminates signal vs. noise on the actual integration path | misleading (used independent hand-made Sharpes) | partial/misleading | **covered and fixed** — `test_identity_model_noise_does_not_floor_p_value` reproduces the exact prior degeneracy and confirms it's gone |
| `validate_cpcv` rejects internally-inconsistent evidence | only `len==fold_count` | partial | **covered** — mean/median recompute, non-finite, p-range, embargo floor, hash format all tested (`test_promotion_evidence*`, confirmed via direct repro in this audit) |
| `validate_dsr` rejects internally-inconsistent evidence | not tested (schema can't support it) | MISSING | **still MISSING, and now proven exploitable** — see §4.4; no test in `test_dsr_unit.py`/`test_promotion_evidence*` attempts a `dsr`-vs-`observed_sharpe` sanity bound because the validator has no such check to test |
| PSR eq. 1, `E[max]` eq. 7 | internal reimplementation only | covered (internal) | **unchanged**, plus new independent check below |
| DSR vs. a literature known-answer | — | MISSING | **covered** — `TestExpectedMaxSharpeKnownAnswer` (`test_dsr_reference.py:239-278`) vs. tabulated order statistics |
| `trials_count` honesty/provenance | rejects 0 only | partial | **unchanged, partial** |
| Default-variance weak-deflation signal | none | — (not yet a finding) | **covered** — `test_iid_null_variance_default_warns` (`test_dsr_unit.py:560-563`) |
| Annualization scaling (CPCV, DSR) | — | MISSING | **covered independently on each side** — `test_annualization_scales_observed_and_dsr` (DSR), inline `annualization_factor` assertions (CPCV); **no test exercises both builders together for one alpha with a shared factor** (because no such caller exists — §1.8) |
| Determinism (Inv-5), incl. new bootstrap | covered | covered | **covered, extended to `block_bootstrap_p_value`** |
| Pre-registration ordering (Inv-2) | MISSING | MISSING | **still MISSING**, unchanged |
| Family-wise multiple testing | MISSING | MISSING | **still MISSING**, unchanged |
| Multi-region purge interaction (adjacent/overlapping windows) | N/A (feature didn't exist) | N/A | **MISSING** — verified correct by this audit's manual + brute-force check (§3.2), but not encoded as a regression test |

---

## 8. Prioritized backlog

Effort: **S** ≤ ½ day · **M** ≈ 1–2 days · **L** > 2 days. "FP-rate impact" = effect on the
false-promotion rate. Items already resolved by `44702ec` are listed in §1/§3/§4/§5 with
**[FIXED]** tags and are not repeated here.

### P0 — none open

Both 2026-06-24 P0s (label-horizon-blind purge; missing functional leakage probe) are
verified closed (§3.2, §3.3). I found no new P0 in this pass.

### P1 — weakens the bar / false confidence today

| # | Component | `file:line` | One-sentence fix | FP-rate impact | Effort |
|---|-----------|-------------|------------------|-----------------|--------|
| P1-A **(new)** | `validate_dsr` cannot detect a fabricated/impossible `dsr` | `promotion_evidence.py:589-633`, `DSREvidence` at `:229-261` | Immediate: add `if evidence.dsr > evidence.observed_sharpe: error(...)` (always true for a real computation, schema-free); fuller: add `n_obs` (+ `trial_sharpe_variance` or `threshold_sharpe`) to `DSREvidence` so `validate_dsr` can recompute `dsr_p_value` the way `validate_cpcv` now recomputes `mean_sharpe`. | High — closes a fabrication vector on the PAPER→LIVE gate structurally identical to the one just closed for CPCV. | Immediate check: **S**; schema extension: **M** |
| P1-B (carried, deferred by the hardening commit) | Inv-2 pre-registration unenforced | `hypothesis.py`, `experiment.py` | Implement an append-only hypothesis/experiment log that timestamps `falsification_criteria` before results and feeds `trials_count`. | Medium — backs Inv-2/Inv-3 with provenance instead of trust. | **L** |
| P1-C (carried) | `trials_count` still self-reported, no honesty link | `dsr.py:461-553`, `promotion_evidence.py:626-631` | Bind `trials_count` to a recorded experiment count once P1-B lands. | Medium. | **M** (depends on P1-B) |

### P2 — soundness / provenance hardening / operationalization

| # | Component | `file:line` | One-sentence fix | Effort |
|---|-----------|-------------|------------------|--------|
| P2-A **(new)** | New purge parameter has no property-based coverage | `test_cpcv_props.py:42-50` | Add `label_horizon_bars` to `_cpcv_config_and_n_bars()`'s draw and add a property asserting no surviving train bar is within `h` of any test bar, across the existing random `(N,k,n_bars)` sweep — this is exactly the multi-region case this audit checked by hand (§3.2). | **S** |
| P2-B **(new)** | Neither fix is wired to a real caller | none (absence) | Stand up (or extend an existing script) a research-driver path that derives `label_horizon_bars` from an alpha's `horizon_seconds`/`expected_half_life_seconds` and threads one `annualization_factor` into both `build_cpcv_evidence` and `build_dsr_evidence` for the same alpha. | **M** |
| P2-C (carried) | Dangling `fold_pnl_curves_hash` / no artefact store | `cpcv.py:777-803`, `promotion_evidence.py:211-213` | Stand up the research-artefact store and verify the hash resolves at gate time; require non-empty for promotion. | **M** |
| P2-D (carried) | No family-wise multiple testing | `promotion_evidence.py:589-633` | Add a platform-level Bonferroni/BH deflation across promoted alphas. | **M** |
| P2-E (carried) | DSR cross-version determinism | `dsr.py:163-177` | Pin the CPython minor version for replay, or vendor a stable `inv_cdf`. | **M** |
| P2-F **(new, minor)** | `CPCVEvidence.mean_pnl` fully unchecked | `promotion_evidence.py:224, 515-586` | Add a finiteness check at minimum; recompute is not possible without the raw per-path PnL, which isn't on the schema. | **S** |
| P2-G (carried) | "folds"=paths naming, docstring drift | — | Already substantially addressed by this pass's docstring corrections; consider a field rename in a future schema-version bump. | **S** |

---

## 9. Appendix

### 9.1 Worked confirmations (read-only `uv run python`, this session)

1. **Old fabricated-CPCV-evidence repro, re-run:**
   `CPCVEvidence(fold_count=8, fold_sharpes=(0.01,)*8, mean_sharpe=2.0, median_sharpe=2.0,
   p_value=0.0001, embargo_bars=0, fold_pnl_curves_hash="")` → `validate_cpcv` now returns
   3 errors (mean/median mismatch ×2, embargo floor), where it returned `[]` on 2026-06-24.
2. **Malformed-hash repro:** a non-empty, non-sha256-shaped `fold_pnl_curves_hash` is rejected
   with an explicit "malformed" error.
3. **DSR canonical-vs-excess, re-run (no regression):** `observed=0.5, n_obs=252,
   n_trials=100, var=1/251` → `E[max]=0.1597`, `dsr_value=0.3403`, `psr=1.0000`,
   `dsr_p_value≈0.0000`; canonical DSR `= 1 - dsr_p_value = 1.0000` — identical to the
   2026-06-24 numbers.
4. **`DSREvidence` schema field audit:** `sorted(DSREvidence.__dataclass_fields__.keys())` =
   `['dsr', 'dsr_p_value', 'kurtosis', 'observed_sharpe', 'skewness', 'trials_count']` — no
   `n_obs`. Directly substantiates §4.4.
5. **`evidence_to_metadata`/`metadata_to_evidence` round-trip:** built a real `CPCVEvidence`
   via `build_cpcv_evidence` and a real `DSREvidence` via `build_dsr_evidence`, round-tripped
   both through the F-1 ledger metadata helpers — both compare equal to the originals
   (lossless).
6. **Multi-region purge brute-force check:** `CPCVConfig(n_groups=6, k_test_groups=2,
   label_horizon_bars=3, embargo_bars=0)`, `n_bars=12`, test groups `(0,2)` →
   `test_indices=(0,1,4,5)` (two regions, gap `{2,3}`) → implementation `train_indices=(9,10,11)`;
   brute-force ground truth (purge `j` iff `∃t∈test: |j-t|<=3`) also `(9,10,11)`. **Match.**
7. **New DSR-fabrication repro:** `DSREvidence(observed_sharpe=0.5, trials_count=1000,
   dsr=999.0, dsr_p_value=0.0001, ...)` → `validate_dsr` returns `[]`. A second variant
   (`observed_sharpe=0.2, dsr=50.0`) also returns `[]`. Both violate `dsr <= observed_sharpe`,
   which is always true for a real `deflated_sharpe` computation (§4.1, §4.4).
8. **`GateThresholds` CPCV/DSR defaults, current:** `cpcv_min_folds=8`,
   `cpcv_min_mean_sharpe=1.0`, `cpcv_max_p_value=0.05`, `cpcv_min_embargo_bars=1` (new),
   `dsr_min=1.0`, `dsr_max_p_value=0.05`.

### 9.2 Independent sanity-check of the new DSR known-answer constants

The order-statistic constants in `TestExpectedMaxSharpeKnownAnswer` (`E[max of N iid
N(0,1)]`: `N=10→1.53875`, `N=100→2.50759`, `N=1000→3.24147`) were cross-checked against the
standard crude asymptotic extreme-value approximation
`E[max_n] ≈ √(2 ln n) − (ln(ln n) + ln 4π) / (2√(2 ln n))`:

| N | asymptotic approx. | tabulated (test) | consistent? |
|---|--------------------:|-------------------:|:-----------:|
| 10 | ≈ 1.362 | 1.53875 | yes (asymptotic under-estimates at small N, known behavior) |
| 100 | ≈ 2.366 | 2.50759 | yes |
| 1000 | ≈ 3.116 | 3.24147 | yes |

The asymptotic formula is known to converge slowly and systematically under-estimate at these
sample sizes, so the direction and magnitude of the gap is exactly what's expected — this is a
rough corroboration, not a byte-exact verification (I did not have the original Harter
1961/Royston 1982 tables on hand to check to more digits), but it is enough to say the cited
constants are plausible, correctly-ordered, and in the right regime, rather than typos or
sign errors.

### 9.3 Open questions for the research owners (carried + new)

1. (Carried) Is a per-fold-retraining caller for `build_cpcv_evidence` planned? Until one
   exists, `label_horizon_bars`/purge/embargo remain correct-but-unexercised machinery in
   production (§1.8).
2. (Carried) Should the `dsr` field be renamed (e.g. `deflated_sharpe_excess`) now that the
   redefinition is intentional and documented, to remove the residual "reads like the paper's
   DSR" risk for anyone who only skims the field name?
3. **(New)** Given `DSREvidence` cannot support a consistency recompute without `n_obs`, is a
   schema/`LEDGER_SCHEMA_VERSION` bump planned to add it? The gate-matrix completeness checks
   (`_check_matrix_completeness`, `_check_validator_coverage`, `_check_reconstructor_coverage`,
   `promotion_evidence.py`) would need the new field wired through
   `evidence_to_metadata`/`metadata_to_evidence` as well.
4. **(New)** Should `_cpcv_config_and_n_bars()` (`test_cpcv_props.py:42-50`) be extended to
   draw `label_horizon_bars` so the existing ~15 property tests automatically extend their
   wide-search-space coverage to the new purge parameter, given it is the highest-consequence
   fix in this pass?

### 9.4 Out of scope but observed

- `src/feelies/research/forward_ic.py` changed since 2026-06-24 (new `long_short_edge_bps`
  cost-gate primitive, per commit `174c352`) but remains a sensor/feature-selection ("gas
  decision") diagnostic tool, not part of the CPCV/DSR promotion-gate path and not consumed by
  any `GateId` validator — confirmed out of scope for this audit per the prompt's explicit
  file list, consistent with the 2026-06-24 audit's treatment.
- The `kernel/orchestrator.py:4795` `SyntaxError` that blocked e2e test collection on
  2026-06-24 is resolved (verified via `ast.parse`); this was fixed by unrelated commits
  (`7125ebe`, `b923201`) prior to this session, not by the research-validation hardening
  commit itself.
