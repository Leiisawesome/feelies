<!--
  File:   docs/research/gas_01_integrated_ofi.md
  Status: GAS DECISION #1 — RESOLVED: edge gate NOT passed at the KYLE horizons;
          KYLE alphas NOT re-pointed. Robust 30 s win recorded for follow-up.
  Owner:  feature-engine / microstructure-alpha.
-->

# Gas decision #1 — integrated OFI as the KYLE_INFO input

The engine is done (`docs/audits/engine_readiness_checklist_2026-06-19.md`, 10/10,
pairing-certified). The gas phase selects sensors/features on **IC evidence the
certified engine produces** — not intuition. This is the first such decision.

## Hypothesis

For a **KYLE_INFO** alpha, the right order-flow input is **integrated signed
flow over the decision horizon**, `ofi_integrated = Σ ofi_t`, not the event-paced
`ofi_ewma_zscore` the reference alphas currently read.

**Mechanism (literature).** Permanent price impact ∝ net signed order flow
(Kyle 1985; Cont–Kukanov–Stoikov 2014 for the L1 OFI form). The integral over
the horizon *is* that quantity. `ofi_ewma` decays per *quote* (α=0.1 ⇒ ~0.1–0.7 s
half-life), so at a 300–1800 s KYLE boundary its value is a near-instantaneous
flow snapshot of the last ~7 quotes — and z-scoring that re-standardises noise,
not the horizon-integrated pressure.

**Current consumers (the gap).** `sig_kyle_drift_v1` reads `ofi_ewma`;
`sig_benign_midcap_v1` reads `ofi_ewma_zscore`. Neither reads `ofi_integrated`,
though it is already wired (`ofi_raw` → `HorizonWindowedFeature(sum)`).

## Promotion gate

Per the policy in the engine-readiness checklist (ENG-3), no gas is promoted
without **both**:

1. **Sign golden — ✅ DONE.** `ofi_integrated` is signed correctly through the
   real pipeline: persistent net buy flow ⇒ positive, sell ⇒ negative
   (`tests/research/test_gas_ofi_integrated.py`).
2. **Edge — RankIC pass through the certified harness — ✗ NOT PASSED**
   (APP/2026-03-26; see Result below). `ofi_integrated` must show the **higher
   |RankIC|** with the **correct positive sign** at the KYLE horizons
   (300 / 900 / 1800 s) vs `ofi_ewma_zscore`; it does not on this tape.

## Run the edge measurement (operator, on the APP disk cache)

The head-to-head is wired into the harness (`_ofi_integrated_ab`,
`scripts/sensor_feature_ic.py`) — both features are measured in one replay
through the same certified `SensorRegistry → HorizonScheduler → HorizonAggregator`:

```bash
PYTHONHASHSEED=0 uv run python scripts/sensor_feature_ic.py \
    --cache-dir ~/.feelies/cache --symbol APP --date 2026-03-26 \
    --horizons 30,120,300,900,1800 --csv ofi_gas.csv
```

Read the `ofi_kyle_input` rows: `variant=ofi_integrated` vs
`variant=ofi_ewma_zscore`, RankIC per horizon. (Pool across more `(symbol,date)`
pairs before trusting the result — one tape is indicative, not conclusive.)

## Decision criteria

**Adopt `ofi_integrated`** for the KYLE alphas iff, pooled across days:
- `RankIC(ofi_integrated) > 0` at 300/900/1800 s (correct permanent-impact sign), **and**
- `|RankIC(ofi_integrated)| > |RankIC(ofi_ewma_zscore)|` by a material margin at those horizons.

Otherwise keep `ofi_ewma_zscore` and record the negative result here.

## Risk / nuance (why this must be measured, not assumed)

CKS OFI is **dominated by price-change events** (a best-price uptick contributes
`+bid_size`, a downtick `−bid_size_prev` — far larger than the size-delta term).
So `ofi_integrated` partly tracks *realised in-window price direction*, and its
*forward* predictiveness then hinges on price autocorrelation (momentum), which
is regime-dependent. The sign and magnitude of the edge are therefore genuinely
empirical — exactly what the certified harness is for.

## If the edge gate passes — downstream changes (staged, not yet done)

1. Re-point `sig_kyle_drift_v1` (and consider `sig_benign_midcap_v1`) to read
   `ofi_integrated`.
2. **Recalibrate the entry threshold** — units change from σ (z-score) to
   share-flow; the existing `|z|` thresholds do not transfer.
3. Re-bake the affected goldens (signal replay) and the data-gated APP PnL/fill
   baseline, in one commit (same procedure as prior alpha changes).

## Result — APP / 2026-03-26 (RankIC = Spearman, IC = Pearson)

| horizon | `ofi_integrated` RankIC (n, t) | `ofi_ewma_zscore` RankIC (n, t) |
|--------:|-------------------------------:|--------------------------------:|
|    30 s | **+0.101** (810, +2.89)        | +0.045 (718, +1.22)             |
|   120 s | +0.048 (215, +0.70)            | +0.012 (206, +0.17)             |
|   300 s | +0.006 (88, +0.06)             | +0.170 (85, +1.57)              |
|   900 s | +0.046 (32, +0.25)             | −0.021 (30, −0.11)              |
|  1800 s | **−0.409** (17, −1.74)         | −0.132 (16, −0.50)              |

## Decision — DO NOT adopt `ofi_integrated` for the KYLE alphas (this evidence)

The criterion ("RankIC(integrated) > 0 **and** materially beats `ofi_ewma_zscore`
at 300/900/1800 s") is **not met**: integrated is ≈0 at 300 s, and **wrong-signed
(−0.41) at 1800 s**. The KYLE alphas are **not re-pointed**.

Reading the evidence honestly:

- **Only the 30 s comparison is statistically robust** (n≈700–810, |t| > 2.5):
  there `ofi_integrated` wins decisively (+0.101 vs +0.045, ~2.2×). But **30 s is
  below the KYLE half-life band** (60–1800 s) — that win argues for a *fast*
  (INVENTORY/HAWKES-horizon) input, not a KYLE one, and is logged as a separate
  follow-up, not acted on here.
- **300 / 900 / 1800 s are underpowered** — n = 16–88 on a single day. The
  long-horizon RankICs (incl. the −0.41 at 1800 s, n=17) are noise; the Spearman
  vs Pearson disagreement at those n confirms instability. No KYLE-horizon claim
  can be made either way from one tape.
- The **1800 s sign flip** is consistent with the pre-registered **CKS
  price-direction risk**: integrated OFI partly tracks in-window price direction,
  so its forward edge is momentum-like at short horizons and reverts at long
  ones — i.e. *not* clean permanent impact. The risk was real, not theoretical.

**The gate did its job:** it blocked an evidence-free, literature-plausible
re-point that intuition would have made.

## Next steps (to actually settle the KYLE question)

1. **Pool across many `(symbol, date)` days** (the harness already pools — pass
   repeated `--symbol/--date`) until n at 300/900/1800 s is in the hundreds, then
   re-evaluate the KYLE-horizon criterion.
2. Separately, the robust **30 s** win motivates a *new* gas question — is
   integrated OFI a good INVENTORY/HAWKES-band input? — opened as gas decision #2,
   not folded into this one.

## Status

**RESOLVED for this tape.** Correctness gate ✅, tooling ✅, edge gate ✗ at the
KYLE horizons on APP/2026-03-26. No alpha changed. Re-open only with multi-day
pooled data; nothing is re-pointed until the KYLE-horizon edge is demonstrated
with adequate sample size and the correct sign.
