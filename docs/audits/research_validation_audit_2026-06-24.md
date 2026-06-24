# Research-Validation Math Audit (CPCV / DSR / pre-registration) — 2026-06-24

**Scope:** the statistical-significance bar before capital — `feelies.research.cpcv`,
`feelies.research.dsr`, `feelies.research.hypothesis`, `feelies.research.experiment`,
`feelies.research.forward_ic`, and the consuming evidence schemas / validators in
`feelies.alpha.promotion_evidence` (`CPCVEvidence`, `DSREvidence`, `validate_cpcv`,
`validate_dsr`, `GateThresholds`). Read-only, evidence-based. **No production code,
test, or ledger was modified.**

**Method:** static read of every in-scope module against the cited literature
(López de Prado 2018 *AFML* §7 + §12; Bailey & López de Prado 2014 *The Deflated Sharpe
Ratio*, JPM 40(5):94–107), plus read-only numerical repros via `uv run python` and the
targeted test suites. All `path:line` citations are against the working tree at branch
`claude/dazzling-cori-rygvoz`.

**Read-only checks executed**

| Check | Result |
|-------|--------|
| `pytest tests/research/test_cpcv_unit.py test_cpcv_reference.py test_cpcv_props.py` | **passed** (part of 198) |
| `pytest tests/research/test_dsr_unit.py test_dsr_reference.py test_dsr_props.py` | **passed** (198 total) |
| `pytest tests/research/` (full) | **collection ERROR** — `tests/research/test_promotion_pipeline_e2e.py` imports `feelies.cli.main` → `backtest` → `harness` → `kernel.orchestrator`, which has a pre-existing `SyntaxError: keyword argument repeated: reason` at `kernel/orchestrator.py:4795` (out of scope; blocks the in-scope C-3 e2e suite from running at all) |
| Repro: identity-model CPCV path degeneracy | **confirmed** — 9 paths, 1 distinct return series, `p_value == 1/(B+1)` for strong *and* weak alpha |
| Repro: purge leaves pre-test neighbour in train | **confirmed** — `train ∪ test == full range` at `embargo=0` |
| Repro: fabricated `CPCVEvidence` passes `validate_cpcv` | **confirmed** |

Legend: **[BUG]** implementation defect · **[LIM]** documented simplification /
limitation · **[DESIGN]** intentional modeling choice (flagged where it carries
false-confidence risk). Each finding tags **implementation-bug** vs **modeling-choice**
vs **documented-simplification** per the brief.

---

## 1. Executive summary

The **math kernels are correct.** CPCV combinatorics (`C(N,k)` combinations,
`C(N-1,k-1)` paths), the embargo arithmetic, the PSR closed form (Bailey-LdP eq. 1), and
the expected-max-Sharpe closed form (eq. 7) all match the cited literature term-for-term
and are well tested (198 passing C-1/C-2 tests). The false-confidence risk is **not** in
the formulas — it is concentrated in (a) unverified *inputs*, (b) an incomplete purge,
(c) a degenerate p-value, and (d) incommensurate threshold units. Ranked by likelihood of
promoting an overfit strategy:

1. **[P1][DESIGN] DSR deflation is self-reported and runs at its weakest.** `trials_count`
   is operator-supplied and only checked for `> 0` (`promotion_evidence.py:531`); nothing
   ties it to a real count of variants (the experiment/hypothesis registries are
   unimplemented stubs). The default trial-Sharpe variance `1/(n_obs-1)` (`dsr.py:368-369`)
   is the *smallest* plausible dispersion, so `E[max]` and thus the deflation are minimal.
   Repro: default `E[max]=0.160` vs realistic `var=0.02 → E[max]=0.358`. DSR *looks*
   rigorous but its key lever is an unverified number deflated by a floor variance.
2. **[P1][BUG] `validate_cpcv` / `validate_dsr` are trust-on-submit.** The only internal
   CPCV check is `len(fold_sharpes)==fold_count` (`promotion_evidence.py:495`).
   `mean_sharpe`, `median_sharpe`, `p_value` are **never recomputed** from `fold_sharpes`;
   `embargo_bars` is **never gated**; an empty `fold_pnl_curves_hash` is accepted.
   Repro: `CPCVEvidence(fold_count=8, fold_sharpes=(0.01,)*8, mean_sharpe=2.0,
   p_value=0.0001, embargo_bars=0, hash="")` → `validate_cpcv` returns `[]` (passes).
3. **[P1][BUG] The CPCV bootstrap p-value is degenerate in the only integration path that
   exists.** The C-3 e2e and `_identity_test_returns_by_split` feed perfect-foresight OOS
   returns, so every reconstructed path is byte-identical → all fold Sharpes equal → the
   centred bootstrap sample is all-zero → `p_value` collapses to the floor `1/(B+1)`
   (`cpcv.py:599`). Repro: strong (`mean_sharpe=1.15`) and weak (`mean_sharpe=0.067`)
   alpha **both** get `p_value=0.000999 ≤ 0.05`. The `cpcv_max_p_value` gate is a no-op;
   only `mean_sharpe` discriminates signal from noise.
4. **[P1][DESIGN] CPCV `mean_sharpe` is per-bar and incommensurate with the annualized DSR
   bar.** `sharpe_ratio` applies no annualization (`cpcv.py:504-511`); `build_dsr_evidence`
   annualizes (`dsr.py:514-521`). Same series: per-bar `mean_sharpe=1.15` checked vs
   `cpcv_min_mean_sharpe=1.0`, while annualized `dsr=15.9` vs `dsr_min=1.0`. The CPCV bar
   is ~16× stricter in annualized terms; its meaning depends on the caller's bar size and
   is undocumented at the gate.
5. **[P0][DESIGN, latent] The "purge" is index-overlap only — it does not implement López
   de Prado's label-overlap purge and has no label-horizon parameter.** `_purged_train_indices`
   removes only the exact test indices plus a *post-test* embargo (`cpcv.py:241-282`).
   For any alpha whose label/holding horizon exceeds one bar (the platform's horizons are
   30–1800 s), training observations *immediately before* the test set leak their
   forward-looking labels into the test period, and the one-sided embargo (`cpcv.py:256-260`)
   does not cover that side. This is the exact failure purging exists to prevent. It is
   **latent today** because no production caller retrains per fold — every test and the e2e
   use the identity projection — but the moment a real per-fold model is wired, this
   manufactures false OOS alpha.
6. **[P1][LIM] Inv-2 (falsifiability before testing) has zero code enforcement.**
   `hypothesis.py` and `experiment.py` are Protocol stubs (`hypothesis.py:26`,
   `experiment.py:27`) with no registry, no append-only log, and no guarantee that a
   falsification rule is recorded *before* results. The only machine-checked falsification
   rule is `dsr_min` (`promotion_evidence.py:393`). `trials_count` has no provenance chain.
7. **[P1][DESIGN] The field named `dsr` is not the canonical Bailey-LdP DSR.** The paper's
   DSR is `PSR(SR_0)`, a probability in `[0,1]`. The code reports `dsr = observed − E[max]`
   (a Sharpe-excess, `dsr.py:390`) and `dsr_p_value = 1 − PSR` (`dsr.py:391`). The canonical
   DSR equals `1 − dsr_p_value`. So `dsr_min = 1.0` ("DSR ≥ 1") is a Sharpe-excess bar that
   is *impossible* to read as the cited probability. Documented as a redefinition, but the
   "Bailey-LdP DSR ≥ 1" citation in the skill/glossary is misleading.
8. **[GOOD] The statistical half of the DSR gate is rigorous and matches the paper.**
   `dsr_p_value ≤ dsr_max_p_value (0.05)` is exactly the one-sided Bailey-LdP DSR test
   `PSR(E[max]) ≥ 0.95`. `probabilistic_sharpe_ratio` (`dsr.py:213-226`) and
   `expected_max_sharpe` (`dsr.py:275-279`) reproduce eq. 1 and eq. 7 term-for-term,
   including the non-excess-kurtosis convention and the Euler-Mascheroni constant.
9. **[GOOD] CPCV combinatorics + embargo arithmetic are correct.** `n_combinations=C(N,k)`,
   `n_paths=C(N-1,k-1)` (`cpcv.py:154-167`) match AFML §12.4; path reconstruction matches
   the §12.5 procedure and the pinned `N=4,k=2` reference; the embargo is post-test,
   length-`embargo_bars`, truncated at `n_bars`, and never excises test bars (verified
   against `test_cpcv_reference.py:66-94`). No off-by-one found.
10. **[GOOD] Determinism (Inv-5) holds for the math.** No unseeded RNG: the only
    stochastic element is the CPCV bootstrap, seeded via `random.Random(seed)`
    (`cpcv.py:592`); DSR is pure closed-form. Determinism is asserted by property tests
    (`test_cpcv_props.py`, `test_dsr_props.py`).
11. **[P1][DESIGN] The bootstrap docstring's "conservative-leaning" claim is backwards.**
    CPCV paths share most bars (positively correlated); the iid bootstrap *understates*
    the standard error of the mean → p-value too *small* (anti-conservative). In the
    degenerate-identical case it returns the floor (most-significant) value. The docstring
    (`cpcv.py:77-85`, `564-571`) asserts the opposite.
12. **[P2][LIM] `fold_pnl_curves_hash` is a dangling pointer.** No research-artefact store
    exists; the hash is never resolved or verified (`promotion_evidence.py:202-209` notes
    it is "optional"). It hashes per-bar *returns*, not cumulative PnL curves despite the
    name (`cpcv.py:629-655`). Provenance integrity exists only if someone re-runs the
    builder.
13. **[P2][DESIGN] No family-wise (cross-alpha) multiple-testing deflation.** DSR deflates
    each alpha by its own `trials_count` only. Running N alphas and promoting the best is
    a selection bias the pipeline does not correct.
14. **[P2][LIM] Cross-version determinism caveat for DSR.** `statistics.NormalDist.inv_cdf`
    can differ by a ULP across CPython minor releases — the DSR reference suite itself
    compares to the running interpreter rather than pinned literals
    (`test_dsr_reference.py:1-11`). Cross-machine Inv-5 holds only within one CPython minor
    version. CPCV pins exact literals (a tripwire, `test_cpcv_reference.py:228-232`).
15. **[P2][DESIGN] Naming: "folds" are paths.** `CPCVEvidence.fold_count` /
    `fold_sharpes` hold the **path** count `C(N-1,k-1)` and per-path Sharpes
    (`cpcv.py:726-727`), not the combination count `C(N,k)`. `cpcv_min_folds=8` therefore
    gates **paths**. An operator reading "8 folds" as "8 combinations" is misled.

---

## 2. Method inventory

| Quantity | Where | Definition as implemented | Literature check |
|----------|-------|---------------------------|------------------|
| `n_groups (N)`, `k_test_groups (k)`, `embargo_bars (e)` | `cpcv.py:138-152` | hyperparameters; `N≥2`, `1≤k<N`, `e≥0` | AFML §12.4 partition params |
| `n_combinations` | `cpcv.py:154-159` | `C(N,k)` | ✓ φ = C(N,k) |
| `n_paths` | `cpcv.py:161-167` | `C(N-1,k-1)` | ✓ (k/N)·C(N,k) = C(N-1,k-1) |
| group assignment | `cpcv.py:206-233` | contiguous; remainder to early groups; sizes differ ≤1 | ✓ KFold convention |
| purge | `cpcv.py:241-282` | **exact test-index removal only** (no label horizon) | ✗ AFML §7.4.1 purges label-overlap |
| embargo | `cpcv.py:264-280` | `e` bars *after* each contiguous test region, truncated at `n_bars` | ✓ direction (AFML §7.4.2); but no pre-test side and `e` not tied to horizon |
| path reconstruction | `cpcv.py:328-379` | for each group, `p`-th split that tests it; zip-by-position; sorted | ✓ AFML §12.5 |
| `sharpe_ratio` | `cpcv.py:486-527` | `fmean/pstdev` (ddof=0), scale-normalized, **no annualization** | population Sharpe; units = input |
| `lo_bootstrap_p_value` | `cpcv.py:535-599` | two-sided iid bootstrap of centred path-Sharpes, `H0: mean=0`, `+1/+1` floor | iid bootstrap; **ignores path correlation** |
| `fold_pnl_curves_sha256` | `cpcv.py:629-655` | sha256 over canonical float-repr of per-bar **returns** | content hash; no store |
| `CPCVEvidence` | `promotion_evidence.py:186-218` | `fold_count, embargo_bars, fold_sharpes, mean/median_sharpe, mean_pnl, p_value, hash` | `p_value` doc says "Stouffer", impl is bootstrap |
| `probabilistic_sharpe_ratio` | `dsr.py:173-226` | `Φ((SR-SR*)√(T-1) / √(1-γ₃SR+((γ₄-1)/4)SR²))` | ✓ Bailey-LdP eq. 1 |
| `expected_max_sharpe` | `dsr.py:234-279` | `√V·((1-γ)Φ⁻¹(1-1/N)+γΦ⁻¹(1-1/(Ne)))` | ✓ Bailey-LdP eq. 7 |
| `deflated_sharpe` | `dsr.py:329-392` | `dsr_value = SR-E[max]`; `dsr_p_value = 1-PSR(E[max])` | ✗ canonical DSR = PSR(E[max]) |
| default trial variance | `dsr.py:368-369` | `1/(n_obs-1)` when caller omits it | AFML eq. 4 null estimation variance (weakest) |
| `standardised_moments` | `dsr.py:400-437` | non-excess skew/kurt, Gaussian fallback `(0,3)` | ✓ used by `..._from_returns` |
| annualization | `dsr.py:514-521` | scales `observed_sharpe` and `dsr` by `annualization_factor`; PSR left per-period | ✓ linear; gate units mixed |
| `GateThresholds` | `promotion_evidence.py:387-396` | `cpcv_min_folds=8, cpcv_min_mean_sharpe=1.0, cpcv_max_p_value=0.05, dsr_min=1.0, dsr_max_p_value=0.05` | per-bar vs annualized mismatch |
| `validate_cpcv` | `promotion_evidence.py:479-507` | folds≥min, `len==fold_count`, mean≥min, p≤max | no recompute / no embargo / no hash check |
| `validate_dsr` | `promotion_evidence.py:510-538` | `dsr≥min`, `p≤max`, `trials_count>0` | trials self-reported |
| Hypothesis / Experiment | `hypothesis.py:14-43`, `experiment.py:14-53` | frozen dataclasses + Protocol stubs (no impl) | Inv-2 unenforced |

---

## 3. CPCV audit (deep dive)

### 3.1 Combinatorics — CORRECT (modeling matches AFML §12.4)

`n_combinations = C(N,k)` (`cpcv.py:159`) and `n_paths = C(N-1,k-1)` (`cpcv.py:167`).
The path identity `(k/N)·C(N,k) = C(N-1,k-1)` holds, and the canonical AFML worked example
(`N=6,k=2` → 15 combinations, 5 paths) is exercised by `test_cpcv_unit.py:236-240`. Group
counts (each group tests in `C(N-1,k-1)` combinations) are checked
(`test_cpcv_unit.py:216-227`, `test_cpcv_props.py:153-166`). **No defect.**

Path reconstruction (`reconstruct_paths`, `cpcv.py:328-379`) follows AFML §12.5: build
`splits_by_group[g]` in lex-combination order, then path `p = (splits_by_group[g][p] for g)`.
The pinned `N=4,k=2` enumeration `((0,0,1,2),(1,3,3,4),(2,4,5,5))` matches the design-doc
derivation (`test_cpcv_reference.py:107-119`) and every path-split actually tests its
assigned group (`test_cpcv_props.py:196-207`). **No defect.**

### 3.2 Purge — INCOMPLETE (P0, latent; documented-simplification with a leakage hole)

`_purged_train_indices` (`cpcv.py:241-282`) computes training indices as
`{0..n_bars} \ test_set \ embargoed`. The purge is **only** the set-difference of the exact
test indices (`cpcv.py:282`). There is **no label-horizon parameter anywhere in the module**.

AFML §7.4.1 defines purging as removing every training observation whose **label window**
`[t_j, t_j + h]` overlaps the test interval. With a holding/label horizon `h > 0`, a
training observation immediately *before* the test set has a forward-looking label that
reaches into the test period and must be purged. The implementation does not do this, and
the embargo only covers the *post*-test side (`cpcv.py:256-260`, "one-sided (post-test
only)").

Repro (`embargo=0`, test group `{2}` over `n_bars=10`):

```
test_indices=(4, 5)   train_indices=(0,1,2,3,6,7,8,9)
bar 3 (immediately BEFORE test bar 4) in train? True
train ∪ test == full range? True   # nothing purged on the pre-test side
```

The docstring (`cpcv.py:248-255`) is explicit that this is "the simple index-overlap purge
appropriate when *labels* are computed at the bar boundary itself" and pushes label-window
purging onto the caller. That makes it a **documented simplification** — but:

- It is structurally impossible for the caller to express a horizon through this API; the
  only knob is `embargo_bars`, which is **post-test only**, so it cannot fix the pre-test
  label leak even if the operator wanted to.
- Nothing connects `embargo_bars` to the alpha's declared `horizon_seconds` /
  `expected_half_life_seconds` (G16). An operator must hand-tune a bar count with no
  guidance.
- The platform's own alphas all have multi-second horizons, so the `h=0` assumption under
  which this purge is correct never actually holds for a real alpha.

**Severity P0 by the brief's tiering** (a purge that cannot prevent label leakage), tagged
**latent**: today no caller retrains per fold (every test and the C-3 e2e feed the
identity projection `_identity_test_returns_by_split`, `test_promotion_pipeline_e2e.py:108-123`),
so no false alpha is produced *yet*. The defect bites the instant a real per-fold model is
wired to `train_indices`.

### 3.3 Embargo — CORRECT arithmetic, INCOMPLETE coverage

The embargo loop (`cpcv.py:264-280`) walks bars, detects the end of each contiguous test
region, and excludes `[region_end+1, region_end+1+embargo_bars)` (skipping any that are
themselves test bars), capped at `n_bars`. The pinned reference confirms correctness:
`N=4,k=2,e=1`, test groups `(0,2)` → test `{0,1,4,5}` → embargo `{2,6}` → train `{3,7}`
(`test_cpcv_reference.py:78`). Truncation at `n_bars` and the "don't excise test bars"
property are both pinned (`test_cpcv_reference.py:82-94`, `test_cpcv_unit.py:183-201`).
**The arithmetic is correct and free of off-by-one.**

Coverage gaps (modeling, not arithmetic): (a) one-sided only — see §3.2; (b) `embargo_bars`
is a raw count with no link to serial-correlation length or horizon; (c) `embargo_bars` is
carried onto `CPCVEvidence` but the validator never enforces a minimum (§3.6), so `e=0`
(no embargo at all) passes the gate silently.

### 3.4 Leakage probe — the machinery is decorative for the evidence it produces

Critical architectural observation: `build_cpcv_evidence` computes **all** reported
statistics (`fold_sharpes`, `mean_sharpe`, `p_value`, `mean_pnl`, hash) purely from the
caller-supplied `test_returns_by_split` (`cpcv.py:716-742`). The purge/embargo affect
**only** `CPCVSplit.train_indices`, which the module itself never reads when building
evidence. Therefore:

- If the caller honours `train_indices` when training, purge/embargo matter — but that
  caller does not exist in-repo (§3.2).
- If the caller ignores `train_indices` (or there is no model — the identity projection),
  purge/embargo have **zero effect** on the evidence, yet the evidence still advertises a
  non-zero `embargo_bars`, implying a leakage control that did nothing.

No test trains a deliberately leaky model and checks that purge/embargo removes a
*measurable* Sharpe inflation. The purge/embargo are verified **only structurally**
(index-set membership), never **functionally**. This is the single biggest test gap (§7).

### 3.5 `fold_sharpes` / `mean` / `median` / `p_value` and the null

`fold_sharpes` are per-**path** Sharpes (`cpcv.py:726`), `mean_sharpe = fmean(...)`,
`median_sharpe = median(...)` (`cpcv.py:738-739`) — straightforward and internally
consistent.

`p_value` (`lo_bootstrap_p_value`, `cpcv.py:535-599`) bootstraps the centred path-Sharpes
under `H0: mean Sharpe = 0`, two-sided, with the Davison–Hinkley `+1/+1` floor
(`cpcv.py:599`). Two problems:

1. **Degenerate in the integration path (P1).** The C-3 e2e and all convenience wrappers
   use the identity OOS projection, under which every reconstructed path is byte-identical
   (every bar's return is sourced as `returns[bar]` regardless of which split supplies it,
   `assemble_path_returns`, `cpcv.py:462-478`). All fold Sharpes are then equal → centred
   sample is all-zero → every resample mean is 0 → `p_value` = floor `1/(B+1)`. Repro:

   ```
   #paths=9  #distinct path-return-series=1   fold_sharpes all equal? True
   STRONG: mean_sharpe=1.1462  p_value=0.000999...   (== 1/1001)
   WEAK  : mean_sharpe=0.0668  p_value=0.000999...   <= 0.05? True
   ```

   The weak (noise) alpha clears the `cpcv_max_p_value` gate identically to the strong one.
   The p-value gate is a **no-op** in practice; only `cpcv_min_mean_sharpe` discriminates.
   The e2e even bakes this in (`test_promotion_pipeline_e2e.py:540-551`).

2. **Anti-conservative, not "conservative-leaning" (P1, doc bug).** Even with a real model
   producing path variation, CPCV paths are strongly positively correlated (they share
   most bars). Treating them as iid in the bootstrap understates the SE of the mean →
   p-value biased *small* → false significance. The docstrings (`cpcv.py:77-85`, `564-571`)
   claim the opposite ("conservative-leaning"); the degenerate floor result is the extreme
   case of this anti-conservatism.

Also note: `CPCVEvidence.p_value`'s schema docstring says "combined p-value across folds
(e.g. Stouffer)" (`promotion_evidence.py:204`) but the implementation is a bootstrap on the
mean — **doc/impl drift**.

### 3.6 Is `len(fold_sharpes)==fold_count` the only internal check, and is it enough? — No (P1)

`validate_cpcv` (`promotion_evidence.py:479-507`) performs exactly four checks: `fold_count
≥ cpcv_min_folds`; `len(fold_sharpes)==fold_count` (the *only* internal-consistency check,
`:495`); `mean_sharpe ≥ cpcv_min_mean_sharpe`; `p_value ≤ cpcv_max_p_value`. It does **not**:

- recompute `mean_sharpe`/`median_sharpe` from `fold_sharpes`;
- recompute or sanity-bound `p_value` against `fold_sharpes`;
- require `embargo_bars > 0`;
- require a non-empty / well-formed `fold_pnl_curves_hash`;
- reject non-finite `fold_sharpes`.

Repro — a fabricated package whose summary stats contradict its folds **passes**:

```python
CPCVEvidence(fold_count=8, embargo_bars=0, fold_sharpes=(0.01,)*8,
             mean_sharpe=2.0, median_sharpe=2.0, mean_pnl=0.0,
             p_value=0.0001, fold_pnl_curves_hash="")
# validate_cpcv(...) -> []   (PASSES)
```

So `mean_sharpe`, `p_value`, and the integrity hash are **trust-on-submit**. Combined with
§3.4 (evidence is independent of purge/embargo) and §3.5 (p-value degenerate), the CPCV
gate's *effective* discriminator is a single self-reported `mean_sharpe` in an unspecified
unit (§4 / §6.1).

---

## 4. DSR audit — term-by-term vs Bailey & López de Prado (2014)

### 4.1 PSR (eq. 1) — CORRECT

`probabilistic_sharpe_ratio` (`dsr.py:213-226`):

```
var_term = 1 - γ₃·SR̂ + ((γ₄-1)/4)·SR̂²          # dsr.py:213-217
z        = (SR̂ - SR*)·√(n_obs-1) / √(var_term)   # dsr.py:225
PSR      = Φ(z)                                   # dsr.py:226
```

This is Bailey-LdP eq. 1 verbatim, with `γ₃` = skewness, `γ₄` = **non-excess** kurtosis
(Gaussian = 3 → `(γ₄-1)/4 = 0.5` → `var_term = 1 + SR̂²/2`, confirmed by
`test_dsr_unit.py:145-159`). The non-positive-`var_term` guard (`dsr.py:218-224`) matches
the paper's §3 misspecification note. `n_obs ≥ 2` enforced. **No defect.**

### 4.2 Expected-max Sharpe (eq. 7) — CORRECT

`expected_max_sharpe` (`dsr.py:275-279`):

```
E[max SR] = √V · ((1-γ)·Φ⁻¹(1-1/N) + γ·Φ⁻¹(1-1/(N·e)))
```

matches Bailey-LdP eq. 7. `γ = 0.5772156649015328606` (`dsr.py:134`) is correct to ~16
digits. Edge cases `N=1 → 0` and `V=0 → 0` (`dsr.py:273-274`) are the right degenerate
limits. The reference test reconstructs the closed form against the running interpreter and
matches exactly (`test_dsr_reference.py:95-112`). **No defect.**

### 4.3 DSR composition — DEVIATES from the canonical definition (P1, modeling-choice)

The paper's DSR is `DSR = PSR(SR_0) = Prob[true SR > E[max]]`, a probability in `[0,1]`.
The code instead returns (`dsr.py:382-392`):

```
dsr_value   = observed_sharpe − threshold_sharpe   # a Sharpe-EXCESS, not a probability
dsr_p_value = 1 − psr
```

So the **canonical DSR equals `psr = 1 − dsr_p_value`**, and the field literally named
`dsr` is a different quantity (the deflated Sharpe *excess*). Repro:

```
observed=0.5  E[max]=0.1597  dsr_value=0.3403  psr=1.0000  dsr_p_value=0.0000
canonical DSR == psr == 1 - dsr_p_value == 1.0000
```

Consequence: `GateThresholds.dsr_min = 1.0` and the schema-1.1 "OOS DSR < 1.0"
falsification rule are bars on the **annualized Sharpe-excess**, *not* on the cited
probability (which cannot exceed 1). The module's "Schema interpretation" section
(`dsr.py:52-70`) documents this redefinition, so it is a deliberate **modeling-choice** —
but the glossary's "Bailey-López de Prado deflated sharpe ≥ 1" framing
(`platform-invariants.mdc`, `DSR evidence`) and the skill's `dsr_min` rationale are
**inaccurate citations**: nobody can reconcile "DSR ≥ 1" with the paper without knowing the
platform silently swapped the definition.

The **statistical** half is, however, exactly the paper's test: `dsr_p_value ≤ 0.05`
⟺ `PSR(E[max]) ≥ 0.95` ⟺ canonical DSR ≥ 0.95. That part is **GOOD** (§1.8).

### 4.4 `trials_count` honesty — WEAK (P1)

`validate_dsr` refuses only `trials_count ≤ 0` (`promotion_evidence.py:531-536`). The count
is otherwise the operator's word. There is no automated variant counter, and the
experiment/hypothesis registries that would record it are unimplemented stubs (§5.3). DSR's
entire purpose is honest deflation by the true number of variants; under-reporting (say 5
when 500 were tried) directly weakens `E[max]` and lets an overfit alpha through. Nothing in
the pipeline can detect this.

### 4.5 Non-normality — USED on the real path, defaulted elsewhere

`build_dsr_evidence_from_returns` (`dsr.py:524-553`) extracts `standardised_moments` and
threads real skew/kurt into PSR — so the heavy-tail correction *is* applied on the
returns-driven path (the e2e uses this). However `build_dsr_evidence` (`dsr.py:445-521`)
and the `DSREvidence` schema (`promotion_evidence.py:240-246`) both default to Gaussian
`(skew=0, kurt=3)`, so a hand-constructed evidence or a summary-stats caller silently
assumes normality. `validate_dsr` does not flag `kurtosis == 3.0` as a possibly-unfilled
default. Minor, but a researcher can under-state tail risk by omission.

### 4.6 `dsr_p_value` test direction + threshold — CORRECT

`dsr_p_value = 1 − Φ(z) = Φ(−z) = P(Z > z)` is the right one-sided right-tail p-value for
"observed Sharpe exceeds the deflated benchmark," compared `> dsr_max_p_value` →
rejection (`promotion_evidence.py:527-530`). Consistent with the schema-1.1 rule. **No
defect.**

### 4.7 Default trial variance under-deflates (P1, modeling-choice)

When `trial_sharpe_variance` is omitted, `deflated_sharpe` substitutes `1/(n_obs-1)`
(`dsr.py:368-369`) — the variance of a single Sharpe estimator under the iid-Gaussian
*null* (AFML eq. 4). This is the **smallest** plausible cross-trial dispersion; real
trials (parameter sweeps, model variants) have additional genuine spread, so the empirical
`V[{SR_n}]` is larger → larger `E[max]` → stronger deflation. Repro:

```
default var=1/251 -> E[max]=0.1597, dsr_value=0.3403, dsr_p=0.0000
empirical var=0.02 -> E[max]=0.3579, dsr_value=0.1421, dsr_p=0.0169
```

Every convenience wrapper and the e2e use the default, so deflation runs at its weakest in
practice. The docstring (`dsr.py:343-348`) does tell callers with "non-iid trial structure
(CPCV, walk-forward, etc.)" to pass an empirical variance — a **documented-simplification**
— but nothing enforces or even warns when they don't, and the count-based `Φ⁻¹(1-1/N)`
term additionally ignores trial correlation (§6.3).

---

## 5. Determinism & provenance audit

### 5.1 RNG / seeding — GOOD (Inv-5)

The only stochastic element is the CPCV bootstrap, seeded by an explicit caller parameter
(`random.Random(seed)`, `cpcv.py:592`; threaded through `build_cpcv_evidence`,
`cpcv.py:741`). DSR is pure closed-form (no PRNG). Replay determinism is asserted by
property tests at every layer (`test_cpcv_props.py:340-345,397-418`,
`test_dsr_props.py:333-351`). The bootstrap call pattern (`rng.choices(centred, k=n)`) is
pinned to an exact p-value literal (`test_cpcv_reference.py:270-276`), catching any silent
refactor of the draw sequence. **No unseeded RNG found.**

### 5.2 `fold_pnl_curves_hash` integrity — DANGLING (P2)

`fold_pnl_curves_sha256` (`cpcv.py:629-655`) is a deterministic content hash over the
canonical float-repr of the per-bar **return** series (not cumulative PnL, despite "PnL
curves" — `cpcv.py:640-647`). It is stable and order-sensitive (`test_cpcv_unit.py:527-559`).
But:

- No research-artefact store exists (`research-workflow` SKILL: "no dedicated
  research-artefact store exists yet … a content-hash pointer only"). The hash resolves to
  nothing; you cannot retrieve or verify the curves it claims to address.
- `validate_cpcv` accepts an empty hash (§3.6), so an operator can omit it entirely.

Round-trip integrity is therefore "re-run the builder and compare," not "fetch and verify."
A promotion is not reproducible from the ledger alone via this pointer.

### 5.3 Pre-registration / hypothesis ordering (Inv-2) — UNENFORCED (P1)

`Hypothesis` (`hypothesis.py:14-23`) and `ExperimentRecord` (`experiment.py:14-24`) are
frozen dataclasses; `HypothesisRegistry` (`hypothesis.py:26-43`) and `ExperimentTracker`
(`experiment.py:27-53`) are **Protocol stubs with no concrete implementation** (confirmed:
no non-stub importers in `src/`). Consequently:

- There is no append-only registry and **no guarantee that `falsification_criteria` is
  recorded before results** — the core of Inv-2. `status` is a free string with no
  transition control.
- There is a path to post-hoc hypothesis editing: the frozen dataclass gives
  *instance* immutability, but nothing stops constructing a *new* `Hypothesis` with a
  rewritten falsification rule after seeing OOS. No ordering/timestamp is enforced.
- `trials_count` (the DSR honesty lever) has no link to any experiment count, so the
  provenance chain "every strategy → a hypothesis, every promotion → a reproducible run"
  (Inv-13) is broken at the research layer.

The single machine-checked falsification rule that *does* exist is `dsr_min` (the OOS
DSR < 1.0 kill criterion), wired via `GateThresholds` — good, but narrow.

### 5.4 Cross-version determinism — caveat (P2)

`standard_normal_quantile` delegates to `statistics.NormalDist().inv_cdf` (`dsr.py:165`),
whose last-ULP can move across CPython minor versions; the DSR reference suite deliberately
compares to the running interpreter rather than pinned literals (`test_dsr_reference.py:1-11,
95-112`). So cross-machine Inv-5 for DSR holds only when all hosts share a CPython minor
version. CPCV, by contrast, pins exact float literals (`test_cpcv_reference.py:218-232`),
which will *break* on a repr/PRNG change — intended as a tripwire, but it means the two
modules have inconsistent cross-version contracts.

---

## 6. Statistical soundness

### 6.1 Annualization / scaling consistency — INCONSISTENT (P1)

CPCV `sharpe_ratio` is per-bar with no annualization (`cpcv.py:504-511`); DSR annualizes
`observed_sharpe`/`dsr` by `annualization_factor` (`dsr.py:514-521`). The two gates on the
**same alpha** are therefore in different units:

```
per-bar mean_sharpe = 1.15   vs cpcv_min_mean_sharpe = 1.0   (per-bar)
annualized dsr      = 15.86  vs dsr_min             = 1.0   (annualized)
```

A per-bar Sharpe of 1.0 is ≈ `√252 ≈ 15.9×` an annualized 1.0, so `cpcv_min_mean_sharpe`
is silently ~16× stricter than `dsr_min` for daily bars, and its absolute meaning flips
with the caller's bar size (sub-second ticks → an absurd bar). `sharpe_ratio`'s docstring
concedes the threshold is "stated in whatever unit the alpha hands in" (`cpcv.py:504-511`)
— i.e. undefined at the gate. Either gate could be made trivially passable or impossibly
strict by choice of bar frequency.

### 6.2 Sample-size adequacy per fold

With the platform default `N=10, k=2` over ~240 bars, each path is full-length (240 bars),
which is adequate for a single Sharpe. But there are only `C(9,1)=9` paths, all covering the
*same* 240 bars and (in the identity projection) identical — so the "distribution" the
p-value is computed over has **effective size ≈ 1** (§3.5). The CPCV apparatus produces the
*appearance* of 9 OOS folds while delivering one correlated estimate.

### 6.3 Multiple testing — per-alpha only (P2)

DSR deflates each alpha by its own `trials_count`. There is **no family-wise correction**
across the number of alphas/variants promoted platform-wide — promoting the best of N alphas
each individually "DSR-clean" reintroduces exactly the selection bias DSR exists to remove.
The `research-workflow` SKILL lists Bonferroni/BH as "mandatory controls," but no code
implements them. Additionally, DSR's `E[max]` assumes **independent** trials, while CPCV
paths and parameter sweeps are correlated; using a raw count `N` with the theoretical
variance `1/(T-1)` does not reflect that (Bailey-LdP advise using the empirical trial-Sharpe
variance, which captures correlation). The tension is undocumented at the gate.

### 6.4 Independence assumption vs CPCV-path reality

The CPCV bootstrap (§3.5) and the DSR `E[max]` (§6.3) both assume independence that the
data violate in opposite directions: the bootstrap treats correlated paths as iid
(anti-conservative), while DSR treats correlated trials as iid-counted (over-deflating *if*
`trials_count` were honest, but it is self-reported and the variance is floored, §4.7).
Net effect is indeterminate but the *documented* posture (CPCV "conservative," DSR
"rigorous deflation") overstates both.

---

## 7. Test gap matrix (known-answer vs internal-consistency)

| Invariant / property | Test(s) | Status | Note |
|----------------------|---------|--------|------|
| CPCV combinatorics `C(N,k)`, `C(N-1,k-1)` | `test_cpcv_unit.py:126-227`, `test_cpcv_props.py:89-193` | **covered** | structural, broad sweep |
| Path reconstruction correctness | `test_cpcv_reference.py:107-119`, `test_cpcv_props.py:196-207` | **covered (internal)** | "design-doc derivation", not a literature figure |
| Embargo arithmetic (post-test, truncation, no-excise) | `test_cpcv_unit.py:170-201`, `test_cpcv_props.py:106-138` | **covered** | golden index sets |
| Purge prevents **label-overlap** leakage | — | **MISSING** | no horizon concept; only index-disjointness tested |
| Purge/embargo prevent a **measurable** Sharpe inflation (functional leakage probe) | — | **MISSING** | evidence is independent of `train_indices` (§3.4) |
| CPCV p-value discriminates signal vs noise on **correlated** paths | `test_cpcv_unit.py:483-494` uses hand-made **independent** Sharpes | **partial / misleading** | integration path is degenerate (§3.5) |
| `validate_cpcv` rejects internally-inconsistent evidence | `test_promotion_evidence.py` (consistency case) | **partial** | only `len==fold_count`; fabricated summary passes (§3.6) |
| `embargo_bars > 0` enforced | — | **MISSING** | `e=0` passes the gate |
| PSR eq. 1 | `test_dsr_unit.py:145-159`, `test_dsr_reference.py:79-92` | **covered (internal)** | reimplements same formula vs running interpreter |
| `E[max]` eq. 7 | `test_dsr_unit.py:249-258`, `test_dsr_reference.py:95-112` | **covered; one hand-calc** | `≈0.1597` hand calc is the closest to a known-answer |
| DSR vs a **Bailey-LdP 2014 worked example** | — | **MISSING** | no paper-sourced golden vector |
| `trials_count` honesty / provenance | `test_dsr_unit.py:487-496` (rejects 0) | **partial** | cannot test honesty of a self-report |
| skew/kurt actually used | `test_dsr_unit.py:174-201,609-618` | **covered** | |
| Determinism (Inv-5) CPCV+DSR | `test_cpcv_props.py`, `test_dsr_props.py` | **covered** | byte-identical replay |
| Pre-registration ordering (Inv-2) | — | **MISSING** | registries unimplemented |
| Annualization-unit consistency CPCV↔DSR | — | **MISSING** | mismatch unguarded (§6.1) |
| Family-wise multiple testing | — | **MISSING** | per-alpha only |

**Reference-test character:** neither `*_reference.py` suite checks against a **literature
known-answer**. `test_cpcv_reference.py` pins values *computed once by this code then
locked* (golden regression). `test_dsr_reference.py` pins against an *inline
reimplementation of the same closed form* on the running interpreter (formula-drift
tripwire, not independent). The lone semi-external check is the `E[max] ≈ 0.1597` hand
calculation (`test_dsr_unit.py:249-258`). A DSR vector taken from Bailey-LdP 2014's own
worked example would be a genuine known-answer and is absent.

---

## 8. Prioritized backlog

Effort: **S** ≤ ½ day · **M** ≈ 1–2 days · **L** > 2 days. "FP-rate impact" = effect on
the false-promotion rate.

### P0 — manufactures false alpha (or would the moment a real caller exists)

| # | Component | `file:line` | One-sentence fix | FP-rate impact |
|---|-----------|-------------|------------------|----------------|
| P0-1 | Label-horizon-blind purge | `cpcv.py:241-282` | Add a `label_horizon_bars` (or wire `expected_half_life_seconds`/`horizon_seconds`) and purge training observations whose label window overlaps the test interval on **both** sides, per AFML §7.4.1. | High once per-fold retraining is wired; eliminates pre-test label leakage that inflates OOS Sharpe. |
| P0-2 | Functional leakage probe missing | tests (`tests/research/`) | Add a synthetic test that trains a deliberately leaky model, runs CPCV with/without purge, and asserts purge collapses the spurious Sharpe (known answer). | High — converts the purge from "structurally tested" to "proven to prevent leakage." |

### P1 — weakens the bar / false confidence today

| # | Component | `file:line` | One-sentence fix | FP-rate impact |
|---|-----------|-------------|------------------|----------------|
| P1-1 | `trials_count` self-reported; floor variance | `dsr.py:368-369`, `promotion_evidence.py:531` | Require an empirical `trial_sharpe_variance` (or derive it) and bind `trials_count` to a recorded experiment count; warn when the iid-null default is used. | High — restores honest deflation, the core DSR purpose. |
| P1-2 | Trust-on-submit validators | `promotion_evidence.py:479-538` | Recompute `mean_sharpe`/`median_sharpe` (and bound `p_value`) from `fold_sharpes`; require `embargo_bars>0` and a well-formed hash; reject non-finite folds. | High — closes fabricated/drifted-summary acceptance. |
| P1-3 | Degenerate / anti-conservative CPCV p-value | `cpcv.py:535-599` | Replace the iid path bootstrap with a block bootstrap on the underlying per-bar returns (or compute the p-value across genuinely independent CPCV draws); fix the "conservative-leaning" docstring. | High — makes `cpcv_max_p_value` a real gate instead of a no-op. |
| P1-4 | CPCV per-bar vs DSR annualized units | `cpcv.py:504-511`, `promotion_evidence.py:389` | Carry a frequency on `CPCVEvidence` and annualize `mean_sharpe` (or annualize at the gate) so `cpcv_min_mean_sharpe` and `dsr_min` share units. | Medium — removes a silent ~16× threshold inconsistency that mis-sets the bar. |
| P1-5 | Canonical-DSR naming/citation | `dsr.py:52-70,390`, `platform-invariants.mdc` glossary | Rename the excess field (e.g. `deflated_sharpe_excess`) and surface the canonical `DSR = 1 − dsr_p_value`; correct the "Bailey-LdP DSR ≥ 1" citation. | Low FP, high clarity — prevents reviewers mis-trusting the gate. |
| P1-6 | Inv-2 pre-registration unenforced | `hypothesis.py`, `experiment.py` | Implement an append-only hypothesis/experiment log that timestamps `falsification_criteria` before results and feeds `trials_count`. | Medium — backs Inv-2/Inv-3 with provenance instead of trust. |

Effort: P0-1 **M**, P0-2 **M**, P1-1 **M**, P1-2 **S**, P1-3 **M**, P1-4 **S**, P1-5 **S**, P1-6 **L**.

### P2 — soundness / provenance hardening

| # | Component | `file:line` | One-sentence fix | Effort |
|---|-----------|-------------|------------------|--------|
| P2-1 | Dangling `fold_pnl_curves_hash` | `cpcv.py:629-655`, `promotion_evidence.py:202` | Stand up the research-artefact store and verify the hash resolves at gate time; rename to reflect it hashes returns. | M |
| P2-2 | Family-wise multiple testing | `promotion_evidence.py:510-538` | Add a platform-level Bonferroni/BH deflation across promoted alphas, not only per-alpha `trials_count`. | M |
| P2-3 | "folds" = paths naming | `cpcv.py:726`, `promotion_evidence.py:388` | Rename `fold_count`→`path_count` (or document) so `cpcv_min_folds` is unambiguous. | S |
| P2-4 | DSR cross-version determinism | `dsr.py:165`, `test_dsr_reference.py` | Pin the CPython minor version (or vendor an `inv_cdf`) so cross-machine Inv-5 is unconditional. | M |
| P2-5 | DSR worked-example known-answer test | `tests/research/test_dsr_reference.py` | Add a golden vector from Bailey-LdP 2014's own example. | S |
| P2-6 | `p_value` schema doc says "Stouffer" | `promotion_evidence.py:204` | Correct the docstring to "two-sided bootstrap on the mean." | S |

---

## 9. Appendix

### 9.1 Worked confirmations (read-only `uv run python`)

- **CPCV path degeneracy:** `N=10,k=2,e=5`, 240-bar strong series, identity OOS projection
  → 9 paths, **1** distinct path-return series; `mean_sharpe=1.1462`, `p_value=1/1001`.
  Weak series (`μ=1e-4`) → `mean_sharpe=0.0668`, same `p_value=1/1001 ≤ 0.05`.
- **Purge pre-test leak:** `N=5,k=1,e=0`, test `{4,5}` → `train={0,1,2,3,6,7,8,9}`; bar 3
  retained; `train ∪ test == range(10)`.
- **Units:** same strong series → CPCV per-bar `mean_sharpe=1.146`; DSR annualized
  `observed_sharpe=18.195`, `dsr=15.858`.
- **DSR vs canonical:** `observed=0.5,n=252,N_trials=100` → `E[max]=0.1597`,
  `dsr_value=0.3403`, `psr=1.0000`, `dsr_p_value=0.0000`; canonical DSR `= 1 − dsr_p_value
  = psr = 1.0`.
- **Variance floor:** default `1/251 → E[max]=0.1597`; empirical `0.02 → E[max]=0.3579`
  (`dsr_p_value` rises 0.0000 → 0.0169).
- **Fabricated CPCV evidence passes:** `fold_sharpes=(0.01,)*8`, `mean_sharpe=2.0`,
  `p_value=1e-4`, `embargo_bars=0`, `hash=""` → `validate_cpcv == []`.

### 9.2 Open questions for the research owners

1. Is there a planned per-fold-retraining caller for `build_cpcv_evidence`? If not, the
   `train_indices`/purge/embargo machinery is presently inert and the leakage controls are
   advertised but unexercised (§3.4) — should the evidence stop reporting `embargo_bars`
   until a real caller honours it?
2. Is the redefinition of `dsr` as a Sharpe-excess (vs the paper's probability) intended to
   persist? If so, the glossary/skill citations need correcting (§4.3); if not, the gate
   should read the canonical `DSR = 1 − dsr_p_value`.
3. What is the intended frequency for `cpcv_min_mean_sharpe` (per-bar? annualized?), and
   should it be made commensurate with `dsr_min` (§6.1)?
4. Should `trials_count` be sourced from (and reconciled against) a real experiment
   registry before the gate trusts it (§4.4, §5.3)?

### 9.3 Out of scope but observed

- **`kernel/orchestrator.py:4795` `SyntaxError: keyword argument repeated: reason`** breaks
  collection of `tests/research/test_promotion_pipeline_e2e.py` (and any module importing
  `feelies.cli.main`). The in-scope C-3 e2e suite **cannot run** until that is fixed. This
  matches the import-coupling concern in `alpha_lifecycle_audit_2026-06-23.md` (CLI-1).
- `forward_ic.py` (a P2-1 diagnostic tool, not on the promotion path) is internally sound:
  average-rank Spearman with a Fisher-z normal-approx p-value (`forward_ic.py:74-111`),
  pairwise non-finite dropping, and a documented small-`n` caveat — no gate consumes it, so
  no promotion risk.
