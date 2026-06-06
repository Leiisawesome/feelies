# V-1 — Emission Separation `d` + State Occupancy (memo)

**Status:**       SCAFFOLD — fill in after running the script.
**Author:**       _(your name)_
**Date run:**     _(yyyy-mm-dd)_
**Audit ref:**    `docs/audits/regime_stack_audit_2026-06-04.md` §3, V-1
**Script:**       `V-1_emission_separation.py`
**Data window:**  _(yyyy-mm-dd → yyyy-mm-dd; pinned in the script header)_
**Universe:**     20 symbols across three liquidity tiers
                  (top: SPY/QQQ/AAPL/MSFT/NVDA; midcap × 10; thin × 5)
**Engine config:** `HMM3StateFractional(order_emissions_by_increasing_mean=True)`
                   with default transition matrix; no time scaling.

## Decision rule (frozen at design time — DO NOT amend after seeing results)

* `d = |μᵢ − μⱼ| / √(σᵢ² + σⱼ²)`, computed per-symbol over the three
  state pairs (0,1), (1,2), (0,2).
* A symbol **passes** when **all three** pairs have `d ≥ 0.5`.
* The rule:
  * **≥ 80% of symbols pass ⇒ PASS.**  Default-enable
    `enforce_min_pairwise_emission_separation` in `platform.yaml`
    `regime_engine_options:`.
  * **50–80% pass ⇒ PARTIAL.**  Default off; recommend per-cohort
    opt-in (top tier on, midcap/thin off).
  * **< 50% pass ⇒ FAIL.**  Default off and prioritise V-3
    (forward-return bucketing) before any taxonomy change.

## Results

_Fill in from `V-1_emission_separation_data.csv`._

| Metric | Value |
|---|---|
| Symbols scored | _N_ |
| Symbols passing | _K_ |
| Share pass | _K/N = ?_ |
| Median min pairwise `d` | _?_ |
| 10th-percentile min pairwise `d` | _?_ |

### Per-tier breakdown

| Tier | Symbols | % pass | Median min `d` |
|---|---|---|---|
| Top (SPY, QQQ, AAPL, MSFT, NVDA) | 5 | ? | ? |
| Midcap (F, GE, INTC, BAC, WFC, T, PFE, CSCO, C, ORCL) | 10 | ? | ? |
| Thin (UAL, HAL, DVN, PSX, MRO) | 5 | ? | ? |

### State occupancy (% of ticks where state i is argmax)

_Watch for degenerate cases — a symbol with state-1 occupancy
> 95% means the engine is collapsing to "everything is normal" and
`d` is meaningless even when it numerically passes._

## Chart

`V-1_emission_separation_min_d.png` — min pairwise `d` per symbol;
green bars meet the 0.5 floor, red miss.

## Decision

> _(One sentence — PASS / PARTIAL / FAIL — and the action it triggers.)_

## Follow-ups triggered

* If **PASS**: open a one-line config PR flipping
  `enforce_min_pairwise_emission_separation: true` in `platform.yaml`'s
  `regime_engine_options:` block.  Pair with a CI test that calibrates
  on the same window and asserts ≥ 80% pass.
* If **PARTIAL**: write a follow-up memo proposing the cohort
  partition (likely by liquidity tier, but check whether the failing
  symbols share another feature).
* If **FAIL**: skip the config change and prioritise V-3.  Capture
  why (likely candidates: emissions overlap because spread
  distributions are unimodal; engine is mostly a label, not a
  signal).

## Cross-refs

* PR #96 — the audit that surfaced this validation.
* Retro: `docs/audits/regime_stack_audit_2026-06-04.md` §3, V-1.
* L5 hazard-replay parity hash should be **unchanged** by any
  config-only follow-up; if it shifts, the follow-up is doing more
  than configuring a flag.
