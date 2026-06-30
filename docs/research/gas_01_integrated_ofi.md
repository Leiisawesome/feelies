<!--
  File:   docs/research/gas_01_integrated_ofi.md
  Status: GAS DECISION #1 — open (correctness gate passed; edge gate pending data).
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
2. **Edge — RankIC pass through the certified harness — ⏳ PENDING (needs data).**
   On real cached L1, `ofi_integrated` must show the **higher |RankIC|** with the
   **correct positive sign** at the KYLE horizons (300 / 900 / 1800 s) vs
   `ofi_ewma_zscore`.

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

## Status

Correctness gate ✅ and tooling ✅ shipped. **Awaiting the real-data RankIC pass**
(operator-run on the disk cache) before any alpha is re-pointed. Paste the
harness's `ofi_kyle_input` RankIC rows and this decision can be closed either way.
