# Research statistical validation audit (CPCV / DSR) (Claude Code)

Use this prompt in a **Claude Code** session with full repo access. Scope: feelies
pre-deployment statistical validation — Combinatorial Purged Cross-Validation (`cpcv.py`),
Deflated Sharpe Ratio (`dsr.py`), and the hypothesis/experiment tracking that feeds the
promotion gates.

---

## Mission

You are a senior quantitative-research methodologist and statistical auditor (López de
Prado / Bailey lineage). Perform a **read-only, evidence-based audit** of the feelies
research-validation math.

**Primary focus:** This is the statistical-significance bar before capital. Inv-2
(falsifiability before testing) and Inv-3 (evidence over intuition) live here. A leaky
CPCV fold, an incorrect embargo, or a DSR that under-deflates for multiple testing
manufactures false confidence and promotes overfit strategies.

**Goal:** Identify where the CV / significance math is correct vs. subtly wrong, where
purging/embargo prevents leakage vs. leaks, where DSR honestly deflates by trials count,
and where the methodology matches the cited literature — without breaking invariants.

**Do not implement fixes in this pass.** Deliver a structured audit report with
file/line citations, severity, and prioritized recommendations.

---

## Platform context (read first)

1. Read `.cursor/skills/research-workflow/SKILL.md` end-to-end.
2. Read `.cursor/skills/testing-validation/SKILL.md` § on CPCV/DSR evidence schemas.
3. Read `.cursor/rules/platform-invariants.mdc` glossary: **CPCV evidence**, **DSR
   evidence**, and Inv-2 / Inv-3.
4. Primary literature (verify the code against these, not vibes):
   - López de Prado (2018) *Advances in Financial Machine Learning* — purged k-fold,
     combinatorial purged CV, embargo.
   - Bailey & López de Prado (2014) *The Deflated Sharpe Ratio*.

**Architecture (contractual):**

```
hypothesis.py  → experiment.py (tracked runs)
cpcv.py        → fold_sharpes, mean/median, p_value, fold_pnl_curves_hash → CPCVEvidence
dsr.py         → observed_sharpe, trials_count, skew, kurtosis → dsr, dsr_p_value → DSREvidence
→ promotion_evidence.validate_cpcv / validate_dsr → gate thresholds
```

**Hard invariants (non-negotiable):**

- Inv-2: define falsification before testing; no retrospective narrative fitting.
- Inv-3: promotion requires statistical evidence; measure first.
- Inv-5: validation runs deterministic given the same inputs (seeded).
- No lookahead: purge + embargo prevent train/test leakage across the horizon.

---

## Scope — files to audit

### Statistical core

- `src/feelies/research/cpcv.py` — combinatorial purged CV (folds, purge, embargo)
- `src/feelies/research/dsr.py` — deflated Sharpe ratio
- `src/feelies/research/hypothesis.py` — hypothesis registration / falsification rule
- `src/feelies/research/experiment.py` — experiment tracking / provenance

### Evidence schemas (consumers)

- `src/feelies/alpha/promotion_evidence.py` — `CPCVEvidence`, `DSREvidence`,
  `validate_cpcv`, `validate_dsr`, default `GateThresholds`

### Tests (spec + gap analysis)

- `tests/research/test_cpcv_unit.py`, `test_cpcv_reference.py`, `test_cpcv_props.py`
- `tests/research/test_dsr_unit.py`, `test_dsr_reference.py`, `test_dsr_props.py`
- `tests/research/test_promotion_pipeline_e2e.py`, `test_strict_mode_promotion_e2e.py`

**Out of scope:** gate-matrix wiring (see `audit_alpha_lifecycle.md`), live decay
detection (see `audit_forensics.md`), runtime trading logic.

---

## Audit dimensions (answer each with evidence)

### A. CPCV correctness — highest priority

1. Reproduce the combinatorial scheme: N groups, k test groups per combination → number
   of paths. Does `fold_count` / combination count match López de Prado's formula?
2. **Purging:** are training observations whose labels overlap the test period removed?
   State the overlap window in terms of the label horizon. Off-by-one at boundaries?
3. **Embargo:** `embargo_bars` applied *after* each test fold? Is the embargo size
   justified relative to serial correlation / horizon?
4. Leakage probe: can any training sample share information with its test fold (the exact
   failure purging/embargo exists to prevent)?
5. `fold_sharpes` / `mean_sharpe` / `median_sharpe` / `p_value`: definitions and the null
   hypothesis behind `p_value`. Is the consistency check `len(fold_sharpes)==fold_count`
   the *only* internal check, and is that enough?

### B. DSR correctness (Bailey & López de Prado 2014)

1. Reproduce the DSR formula: expected maximum Sharpe under `trials_count` independent
   trials, variance of the Sharpe estimator using `skewness` / `kurtosis`. Does `dsr.py`
   match the paper term-for-term?
2. `trials_count`: the validator refuses `0` — confirm. Is the count the *true* number of
   variants explored (honest deflation), or under-reported?
3. Non-normal returns: are skew/kurtosis actually used in the variance term, or defaulted
   to Gaussian (3.0) and ignored?
4. `dsr_p_value`: correct one-sided test? Threshold `dsr_min=1.0` matches the schema-1.1
   falsification rule?

### C. Determinism & provenance

1. Any RNG (fold shuffling, bootstrap)? Seeded for deterministic replay (Inv-5)?
2. `fold_pnl_curves_hash`: content-addressable pointer — does it actually cover the
   curves it claims? Round-trip integrity.
3. `experiment.py` / `hypothesis.py`: is the falsification rule recorded **before**
   results (Inv-2)? Any path to edit the hypothesis after seeing OOS?

### D. Statistical soundness

1. Are fold Sharpes annualized / scaled consistently? Sample-size adequacy per fold.
2. Multiple-testing: does the pipeline deflate for the number of alphas/variants tried,
   or only per-alpha DSR?
3. Independence assumptions in DSR vs the reality of overlapping CPCV paths — note the
   tension.

### E. Test & validation gaps + prioritized recommendations

1. Map invariants (purge/embargo no-leakage, DSR deflation honesty, determinism,
   pre-registered falsification) to tests — **covered / partial / missing**.
2. Do `*_reference.py` tests check against a known-answer from the literature, or just
   internal consistency?
3. Propose **minimal** new tests (synthetic-leakage probe with known answer, DSR vs a
   worked example from Bailey 2014) — specs only.
4. Tiers:
   - **P0:** CPCV leakage (purge/embargo bug), DSR formula error, RNG without seed,
     post-hoc hypothesis edit.
   - **P1:** weak `trials_count` honesty, ignored skew/kurtosis, annualization mismatch.
   - **P2:** family-wise multiple-testing deflation, richer experiment provenance.

Each item: component, `file:line`, one-sentence fix, expected impact on false-promotion
rate.

---

## Working method

1. Build a **method inventory** (CPCV params, DSR inputs, thresholds, RNG usage).
2. Reproduce the CPCV combinatorics and purge/embargo on paper, then check the code.
3. Reproduce the DSR formula on paper, then check `dsr.py` term-for-term.
4. Probe for leakage and non-determinism.
5. Run **read-only** checks only:
   - `uv run pytest tests/research/ -q`
   Do not modify production code.

---

## Output format (strict)

Write the audit report to `docs/audits/research_validation_audit_YYYY-MM-DD.md` with these sections:

1. **Executive summary** (≤15 bullets): top false-confidence risks first.
2. **Method inventory** (markdown table).
3. **CPCV audit** (combinatorics, purge, embargo, leakage probe — deep dive).
4. **DSR audit** (formula term-by-term vs Bailey 2014).
5. **Determinism & provenance audit** (seeding, hash integrity, pre-registration).
6. **Statistical soundness** (annualization, multiple testing, independence).
7. **Test gap matrix** (known-answer vs internal-consistency).
8. **Prioritized backlog** (P0/P1/P2, effort S/M/L).
9. **Appendix:** worked examples / open questions.

Use code citations as `path:line` for every non-trivial claim.
When citing literature, give author-year-title and the exact equation/section.
Distinguish **implementation bug** vs **modeling choice** vs **documented simplification**.

---

## Quality bar

- Prefer **falsifiable** statements ("embargo is applied before the test fold, not after,
  so the last `embargo_bars` of training leak into test") over adjectives.
- Treat any CPCV leakage or DSR formula error as a P0 — it manufactures false alpha.
- Check the code against the **actual equations** in López de Prado / Bailey, not a
  paraphrase.
- Respect deterministic replay: RNG without an explicit seed is a defect.

---

## Optional follow-ups (paste after the audit)

- *"After the report, draft P0 fixes only for the embargo direction and any unseeded RNG
  as a follow-up PR plan."*
- *"Reproduce the DSR worked example from Bailey & López de Prado (2014) and compare to
  `dsr.py` output numerically — methodology only, no code changes."*
- *"Design a synthetic-leakage CPCV probe with a known-correct answer — test spec only."*
