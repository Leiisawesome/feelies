# Signal-Logic Audit (focused pass) — 2026-06-16

Scope: **signal quality and logic soundness** of the five `layer: SIGNAL`
`evaluate` bodies and how the emitted `Signal` is consumed by arbitration.
Read-only; no fixes proposed inline. Cost-arithmetic / mechanism binding and
the realized-edge loop are **out of scope** (covered by prior passes). Branch:
`claude/intelligent-ritchie-pqb4vk` @ `fd13518`.

Verdict: the gating/None-handling/direction-derivation is mostly sound and
defensive. The real issues are about **what the numbers mean** — the edge is
an ungrounded heuristic, one alpha's strength scale is out of family, and one
direction sign is unconfirmed.

## Findings

| # | Sev | Alpha / module | `file:line` | Finding |
|---|-----|----------------|-------------|---------|
| L-1 | P1 | all 5 | each `evaluate` | `edge_estimate_bps` is `feature_zscore × hand-set slope` (capped), not a return forecast — yet arbitration/sizing/B4 consume it as bps. |
| L-2 | P1 | sig_inventory_revert_v1 | `...inventory_revert_v1.alpha.yaml:237-239` | Direction `LONG if asym_z>0` is self-flagged unconfirmed; the forward-return IC study found ρ≈0 / contra. The directional claim is unsupported. |
| L-3 | P1 | sig_benign_midcap_v1 | `...benign_midcap_v1.alpha.yaml:90,211` vs `arbitration.py:79` | `strength` scales to **2.0** while every other alpha caps at **1.0**; arbitration ranks on `edge×strength`, so benign gets up to 2× weight per unit edge. |
| L-4 | P2 | kyle / hawkes / moc | `kyle:...:178`, `hawkes:...:182`, `moc:...:212` | `edge` and `strength` are driven by *different* features (edge from λ-z / intensity-z / time-remaining; strength from OFI), so `edge×strength` mixes unrelated magnitudes. |
| L-5 | P2 | sig_moc_imbalance_v1 | `...moc_imbalance_v1.alpha.yaml:65,82,94` | `min_seconds_to_close=60` is effectively dead: `cost_floor_bps=6.0` at `1.5 bps/min` needs ~240 s remaining to emit. The 60 s param misleads. |
| L-6 | P2 | sig_inventory_revert_v1 | `...inventory_revert_v1.alpha.yaml` (vol_weight / hazard_weight) | 8 free knobs; the `vol_weight`/`hazard_weight` tapers duplicate the regime gate's hard cutoffs (`rv_z>3.5`, `hazard<4.0`). Redundant smoothing. |
| L-7 | P2 | kyle / hawkes | `kyle:...:165`, `hawkes:...:174` | Direction is taken from `sign(ofi_ewma)` (a quote-flow proxy) rather than the mechanism's own directional observable. |

## P1 detail

**L-1 — the edge is a score, not a forecast (fleet-wide).**
Every alpha computes `edge_bps = min(magnitude × slope, cap)` where
`magnitude` is a feature z-score (or minutes remaining) and `slope`
(`edge_per_z_bps`, `edge_per_lambda_bps`, `edge_per_remaining_minute_bps`) is
a hand-set constant. Nothing ties these slopes to realized forward return, so
`edge_estimate_bps` is "feature surprise × an arbitrary constant" wearing bps
units. This is the root reason disclosed edge ≠ realized edge. *Recommendation
(no code here):* fit the slopes to realized forward returns offline (the
`forward_ic` harness is the seed), or treat `edge` as an **ordinal** score and
stop interpreting it as bps in cost/sizing math. This is the single most
important signal-quality issue and it is a **modeling** gap, not a bug.

**L-2 — inventory direction sign unconfirmed.**
The author comment (`:237`) says the sign "must be re-confirmed against
forward 30 s micro-price returns before relying on this alpha live"; the
later 6-session IC study found the relationship indistinguishable from zero
and the SHORT leg contra-indicated. Until confirmed, this alpha's directional
output is noise regardless of its gating. (Already quarantined on `main`; on
this branch it is still active.)

**L-3 — benign strength is out of family.**
`strength_cap=2.0` (`:90`) lets benign emit `strength` up to 2.0
(`:211`), while kyle/hawkes/moc clamp to 1.0 (`:178/:182/:212`).
`EdgeWeightedArbitrator` ranks on `edge_estimate_bps × strength`
(`arbitration.py:79`) and dead-zones on the same product (`:82`), so at equal
edge benign systematically out-ranks the others and is less likely to be
dead-zoned. Unless a downstream sizer re-normalizes, benign also sizes up to
2× at max conviction. *Recommendation:* put `strength` on a common scale
across alphas (or justify the asymmetry explicitly).

## P2 detail (brief)

- **L-4** Edge/strength feature decoupling means a high-edge / low-strength
  signal and a low-edge / high-strength signal are common; the arbitration
  product is then hard to reason about. Drive both from one conviction proxy
  or document it.
- **L-5** Align `min_seconds_to_close` with the cost-implied threshold
  (~240 s) or drop it; today it advertises a 60 s floor the cost gate overrides.
- **L-6** Let the regime gate own the vol/hazard cutoffs; the signal-side
  tapers add two knobs for marginal smoothing already bounded by the gate.
- **L-7** Derive direction from the mechanism fingerprint (hawkes buy/sell
  aggressor asymmetry; kyle micro-price / λ-weighted drift) instead of the OFI
  proxy — tighter coupling between the named mechanism and the trade.

## What is sound (kept short)

- None/missing-feature guards are present and correct in all five.
- No divide-by-zero at valid parameter defaults; `moc` already guards its
  strength denominator.
- Direction signs for kyle/hawkes/benign are *plausible* (follow informed /
  self-exciting / imbalance flow); only inventory's is unsupported.
- `benign_midcap`'s OFI-z + book-imbalance-confirmation is the cleanest,
  best-formed signal of the five.

*No remediation implemented. L-1 and L-3 are the items worth a decision; the
P2 items are clarity/coherence cleanups, not correctness bugs.*
