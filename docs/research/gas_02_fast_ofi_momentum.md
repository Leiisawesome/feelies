<!--
  File:   docs/research/gas_02_fast_ofi_momentum.md
  Status: GAS DECISION #2 — open. Sign + cost-gate tooling shipped; edge/cost
          measurement on multi-day data pending. No alpha created.
  Owner:  feature-engine / microstructure-alpha.
-->

# Gas decision #2 — integrated OFI as a fast-horizon (~30 s) momentum input

Opened by the one statistically robust result from gas decision #1
(`docs/research/gas_01_integrated_ofi.md`): at **30 s**, `ofi_integrated` has
**RankIC +0.101 (n≈810, t≈+2.9)** — ~2.2× `ofi_ewma_zscore`, and significant.
That win is **below** the KYLE half-life band where it failed, so it is its own
question: is integrated OFI a tradeable *fast-horizon* signal?

## Hypothesis

Net signed flow integrated over a short (~30 s) window predicts **continuation**
(positive `ofi_integrated` → positive 30 s forward return). Mechanism: short-
horizon order-flow autocorrelation / self-excitation — **HAWKES_SELF_EXCITE**-
adjacent (5–60 s band), *not* KYLE permanent impact. Consistent with the gas-#1
finding that the same feature is momentum-like at short horizons and reverts
long (the CKS price-direction effect).

## The binding gate here is COST, not RankIC

30 s sits at the edge of cost-arithmetic feasibility (round-trip ≈ 3–3.5 bps;
30 s σ ≈ 8–12 bps on liquid names). A RankIC of 0.10 can be *significant* yet
imply a **captured edge well below the cost hurdle**. So the gate is Inv-12:

> the gross long-short edge must exceed ~1.5× round-trip cost.

**Measurement primitive — shipped.** `forward_ic.long_short_edge_bps` returns the
top-minus-bottom-bucket forward-return spread in bps — the gross edge a
market-neutral long-top/short-bottom book earns per decision. It is now emitted
by the harness as the **`edgeBps`** column for the `ofi_kyle_input` rows.

## Run the cost gate (operator, on the disk cache; pool many days)

```bash
PYTHONHASHSEED=0 uv run python scripts/sensor_feature_ic.py \
    --cache-dir ~/.feelies/cache \
    --symbol APP --date 2026-03-26 --symbol APP --date 2026-03-27 ... \
    --horizons 30,120 --csv ofi_fast.csv
```

Read the **pooled** `ofi_kyle_input`, `variant=ofi_integrated`, `horizon=30` row:
`RankIC` (is the signal real and positive?) **and** `edgeBps` (does the gross edge
clear ~1.5× round-trip?). One day (n≈810) is enough for RankIC but pool for a
stable `edgeBps`.

## Decision criteria — adopt only if ALL hold (pooled, multi-day)

1. `RankIC(ofi_integrated, 30 s) > 0` and significant — ✅ on APP/2026-03-26, to
   be confirmed across days.
2. `edgeBps(30 s) > 1.5 × round_trip_cost_bps` (≈ 4.5–5 bps) — **unmeasured; the
   crux.** A fast-horizon RankIC of 0.10 may not clear this.
3. The edge survives a regime gate (it should be conditional, e.g. HAWKES burst
   active) and isn't pure latency-arbitrage that an L1 book can't capture.

## If it passes — this is a NEW alpha, not a re-point

No current alpha is a fast-OFI-momentum strategy. A pass would justify a new
`layer: SIGNAL` alpha in the **HAWKES_SELF_EXCITE** family at `horizon_seconds:
30`, reading `ofi_integrated`, with a `cost_arithmetic` block whose disclosed
edge is backed by the measured `edgeBps`, gated to burst regimes. That is a
larger step — authored only after criteria 1–3 are met.

## Status

Sign golden ✅ (gas #1), cost-gate primitive + harness `edgeBps` column ✅,
unit-certified (`tests/research/test_gas_fast_ofi.py`). **Awaiting the multi-day
RankIC + `edgeBps` measurement.** Most likely outcome to pre-register honestly:
the 30 s edge is real but **too small to clear costs** — in which case this
closes as "real signal, not tradeable on L1," and that negative result is itself
the deliverable. Nothing is built until the cost gate passes.
