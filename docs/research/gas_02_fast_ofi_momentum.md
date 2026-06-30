<!--
  File:   docs/research/gas_02_fast_ofi_momentum.md
  Status: GAS DECISION #2 — RESOLVED: cost gate FAILED. Real 30 s signal, edge
          ~0.85 bps << round-trip cost. Not tradeable on L1. No alpha created.
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
2. `edgeBps(30 s) > 1.5 × round_trip_cost_bps` (≈ 4.5–5 bps) — **✗ FAILED:
   measured 0.85 bps** (see Result). The crux, and it does not clear.
3. The edge survives a regime gate (it should be conditional, e.g. HAWKES burst
   active) and isn't pure latency-arbitrage that an L1 book can't capture.

## If it passes — this is a NEW alpha, not a re-point

No current alpha is a fast-OFI-momentum strategy. A pass would justify a new
`layer: SIGNAL` alpha in the **HAWKES_SELF_EXCITE** family at `horizon_seconds:
30`, reading `ofi_integrated`, with a `cost_arithmetic` block whose disclosed
edge is backed by the measured `edgeBps`, gated to burst regimes. That is a
larger step — authored only after criteria 1–3 are met.

## Result — multi-symbol harness run (30 s, `ofi_kyle_input`)

| variant | RankIC (t) | **edgeBps** (gross long-short, 30 s) |
|---------|-----------:|-------------------------------------:|
| `ofi_integrated`   | +0.035 (+2.58) | **+0.85** |
| `ofi_ewma_zscore`  | +0.033 (+2.17) | +1.39 |

## Decision — DO NOT build a fast-OFI alpha; close gas #2

**Cost gate ✗ (decisive).** The 30 s integrated-OFI signal is *statistically
real* (RankIC +0.035, t +2.58) but its **gross long-short edge is 0.85 bps** —
against a ~3.5 bp 30 s round-trip cost (architecture spec §2.2) and the ~5 bp
Inv-12 hurdle (1.5× round-trip), that is **~4–6× too small**. The edge does not
survive costs on L1.

Reinforcing points:
- `ofi_integrated`'s tradable edge (0.85 bps) is **below** the incumbent
  `ofi_ewma_zscore`'s (1.39 bps) — so it is not even better on the tradability
  metric, despite ~equal RankIC.
- This run's RankIC (0.035) is **a third of gas #1's single-day +0.101** — the
  earlier number was an optimistic small-sample estimate; the more robust value
  confirms there is no large fast-horizon edge to chase.

This is exactly the pre-registered most-likely outcome: **real signal, too small
to clear costs.** It is also the textbook reason the platform pushed decision
horizons to 30 s–5 min in the first place (architecture §2.2): sub-minute L1
edges are real but cost-arithmetic-infeasible.

## Status

**RESOLVED — closed negative.** Sign golden ✅, cost-gate primitive + harness
`edgeBps` ✅, edge gate ✗ (0.85 bps << ~5 bp hurdle). **No alpha built.** The
gate did its job a second time: a statistically-significant signal was correctly
*not* turned into a strategy because it cannot survive transaction costs.

Re-open only if a materially different construction (e.g. a longer accumulation
window, a regime-conditioned burst gate that raises the per-decision edge, or a
maker/queue-position execution that cuts the cost) plausibly lifts `edgeBps`
above the hurdle — and even then, only through this same gate.
