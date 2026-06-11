# G-7 Sizing — outcome note (edge-weighted sizing)

**Date:** 2026-06-11
**Gap:** G-7 (single-factor sizing), the last open item in
`position_management_baseline_2026-06-08.md`.
**Decision:** ship the capability **dark** (default-off); **do not enable**
edge-weighted sizing by default on the current universe.

---

## 1. What was built (S0 → S2)

- **S0 — `EdgeWeightedSizer`** (`risk/edge_weighted_sizer.py`): a drop-in
  `PositionSizer` that tilts the base `BudgetBasedSizer` target by a
  deterministic `edge × vol × inventory` product, re-capped at the alpha
  budget. Every factor default-off → byte-identical to the base (Inv-5).
- **S1 — shadow + measurement**: `_record_size_shadow` records a
  `SizeDivergence` per sized signal; `--emit-size-divergence-jsonl` →
  `SIZEDIV_JSONL` stream; `scripts/analyze_size_divergence.py` aggregates it.
  Plus the **exit gate** (see §3) and the reference calibration (§2).
- **S2 — drive + A/B**: `sizer_tilt_drive` routes the live decision through
  the tilted sizer; `configs/backtest_*_edge_drive.yaml` are the A/B "B" legs.

## 2. Calibration

`sig_benign_midcap_v1` discloses edge in **[9, 20] bps**
(`clamp(|z|·edge_per_z_bps, ·, edge_cap_bps)`, `edge_per_z_bps=6`,
`entry_threshold_z=1.5`). Empirical entry-signal edge (APP 2026-06-01, 6
entries): **median 9.34, mean 12.86 bps**, matching the analytic ~11 (z
truncated at 1.5σ). `sizer_edge_ref_bps=11.0` centers the factor for
two-sided discrimination. The first shadow (ref=20) saturated at the floor
because edge/20 < 1.0 always.

## 3. Correctness finding — never tilt exits

The base sizer sizes off `strength` and **ignores direction**, so the 96/102
FLAT exits (edge=0) were being edge-floored to 0.25× in the shadow —
driving that would have **shrunk closes to a quarter**. Fixed:
`tilt_breakdown` returns `combined=1.0` for FLAT-direction signals, and the
edge factor is a no-op for `edge ≤ 0`. The original shadow's combined-tilt
*minimum of 0.225* (impossible for a ≥9 bps entry) was the tell.

## 4. Factor attribution (APP 2026-06-01 shadow)

| Factor | Result |
|---|---|
| **Inventory taper** | **inert** — 0 divergences; holdings (~16 sh) never approach the 500-share cap, so `1−|inv|/cap ≈ 1.0` rounds back to base. Dropped from the drive. |
| **Edge, single-alpha** | ~50% median haircut, 93% downsize — de-weights a low-edge alpha. |
| **Edge, multi-alpha** | size-neutral on average (mean tilt 1.02), genuinely two-sided (31% up / 69% down, range 0.25–2.0); `sig_kyle_drift_v1` drives 77%. The real discrimination case. |

## 5. PnL A/B (edge-only drive, APP)

**Single day (2026-06-01)** — identical `pnl_hash`: the ~2–3 filled entries
sat at the reference (tilt ≈ 1.0). Confirmed not absorbed by min-order
(=1), position cap (500, non-binding), or risk-engine scaling (fires only
near the exposure cap). A single-day small-sample artifact.

**5-day (2026-06-01 → 06-05)** — `pnl_hash` differs (tilt active):

| Metric | A (equal-weight) | B (edge drive) | Δ |
|---|---|---|---|
| Net P&L | +$1,845.22 (+3.69%) | +$1,933.03 (+3.87%) | +$87.81 (+0.18pp) |
| Orders / fills | 68 / 64 | 68 / 64 | same |
| Shares | 3,200 | 3,258 | +58 |
| Win rate | 75.0% | 75.0% | same |
| **Max exposure** | **61.31%** | **85.75%** | **+24.4pp** |
| Max drawdown | −$250.97 (−0.48%) | −$250.97 (−0.48%) | same |

Return per unit of peak exposure: A 0.060 vs **B 0.045 (−25%)**.

## 6. Decision & rationale

**Keep `sizer_tilt_drive: false` (default).** The +0.18pp PnL is a **leverage
artifact** — same trades, same win rate, +58 shares concentrated into the
high-edge entries, peak exposure +24.4pp. Risk-adjusted it is *worse*. The
flat drawdown is window-specific luck, not a property of the change.

Structurally, the **B4 edge-cost gate** (`signal_min_edge_cost_ratio: 1.5`)
already applies a *binary* version of edge-weighting — it removes the
low-edge signals the tilt would shrink — so a continuous tilt mostly just
levers up the survivors, redundant with the gate + position cap.

## 7. What stays shipped (dark)

The sizer, shadow stream, analyzer, calibration, exit-gate, and A/B configs
remain in place behind the default-off flags. Edge-weighting can be revisited
for a universe/strategy where the entry gate and gross-exposure budget are
**not** the binding constraints (e.g. a continuous-signal alpha sized well
below its cap, or with the entry gate relaxed). Inventory taper needs a
tight per-symbol cap or a position-building strategy to become active. The
realized-vol provider remains an unwired seam.

**G-7 closed → the G-1…G-7 position-management overhaul is complete.**
