<!--
  File:   docs/research/prompt_pack_00b_edge_units_convention.md
  Status: NORMATIVE — edge-units convention verified end-to-end 2026-07-07
          (Task FQ-1). Resolves OQ-2 of
          docs/research/prompt_pack_00_architecture_verification.md.
          No hop contradicts the pre-registered decision; no
          STOP-AND-DECIDE required. Binding on Tasks 3, 5, 6, 7, 8, 9,
          12, 13.
  Owner:  cross-cutting (microstructure-alpha disclosure ↔ execution
          cost model ↔ forensics); prompt-pack Task FQ-1, Phase A.
-->

# Prompt-pack Task FQ-1 — Edge-units convention, end-to-end

## THE CONVENTION (codified)

> **`edge_estimate_bps` is disclosed as expected ONE-WAY (per-fill) edge, in
> bps of fill notional, everywhere** — alpha YAML `cost_arithmetic` blocks,
> the `Signal.edge_estimate_bps` field, Task-6 plausibility cards, the
> honest-accounting ledger, and every later comparison. The three
> `cost_arithmetic` cost components (`half_spread_bps`, `impact_bps`,
> `fee_bps`) are likewise ONE-WAY (single-crossing) quantities. Round-trip
> figures are always **derived** (`×2` approximation at disclosure level;
> the entry+taker-exit cost model at runtime), never disclosed.

Rationale (verified below): the B4 runtime gate as implemented
(`basis="round_trip"` default) doubles the disclosed edge before comparing
it to modeled round-trip cost (`execution/position_manager.py:563`). A
candidate disclosing round-trip edge would be doubled **again** and would
clear the gate with half the true margin — systematically loosened relative
to every shipped alpha. The forensics calibration loop
(`realized_mean / disclosed`) would likewise report a spuriously low factor
(~0.5) for a round-trip discloser, corrupting the close-the-loop haircut.

Every hop below was verified against source on 2026-07-07. **No hop
contradicts the pre-registered decision.**

---

## Hop-by-hop units table

| # | Hop | Quantity | Units as consumed | Verdict | Citation |
|---|---|---|---|---|---|
| 1a | Disclosure — template | `edge_estimate_bps: 11.7`, `half_spread_bps: 2.5`, `impact_bps: 3.0`, `fee_bps: 1.0`, `margin_ratio: 1.8` | All one-way. Components sum to one crossing (half the quoted spread + one impact + one taker fee). 11.7 / 6.5 = 1.8 reconciles. | ONE-WAY ✓ | `alphas/_template/template_signal.alpha.yaml:109-114` |
| 1b | Disclosure — shipped alpha | `sig_benign_midcap_v1`: edge 9.0, hs 2.0, impact 2.0, fee 1.0, margin 1.8, **`cost_basis: one_way` declared explicitly**, with inline comment "one-way components. Round-trip ≈ 10.0 bps; edge/round-trip ≈ 0.90. The runtime B4 gate enforces the round-trip Inv-12 bar." | ONE-WAY ✓ (self-documenting) | `alphas/sig_benign_midcap_v1/sig_benign_midcap_v1.alpha.yaml:141-149` |
| 1c | Disclosure — schema authority | Module docstring "Cost basis (audit P1-1)": "`cost_total_bps` sums a **single** crossing … This is a **one-way** cost." `cost_basis` field accepts `{one_way, round_trip}`, default `one_way`; `round_trip_cost_bps` property = `ROUND_TRIP_FACTOR (2.0) × cost_total_bps` when one-way. | ONE-WAY ✓ (round-trip is derived, never assumed) | `alpha/cost_arithmetic.py:33-54, 97-104, 131, 139-152` |
| 2 | G12 load gate | `computed_margin_ratio = edge_estimate_bps / (half_spread + impact + fee)`; floor `MIN_MARGIN_RATIO = 1.5`; reconciliation `abs(computed − declared) ≤ 0.05` (absolute ratio units — see caveat C3). | Numerator and denominator are **commensurate one-way quantities** ✓ | `alpha/cost_arithmetic.py:90, 95, 234-255, 267-286` |
| 3 | B4 runtime gate | `entry_edge_clears_cost(edge_bps, rt_cost_bps, min_ratio, basis)`: with `basis="round_trip"` (default) the one-way edge is **doubled**; passes iff `2 × edge × calibration_factor ≥ min_ratio × rt_cost_bps`. `rt_cost_bps` is a genuine round-trip model figure (entry leg + always-taker exit leg). | ONE-WAY edge doubled onto round-trip basis vs round-trip cost ✓ | `execution/position_manager.py:550-564`; `kernel/orchestrator.py:3187-3207` |
| 4 | Inv-12 stress | 1.5× lands on `cost_stress_multiplier` (variable costs only), 2× on both latency legs. **The edge side is never touched.** | Cost-side only ✓ | `core/inv12_stress.py:25-26, 41-55`; `execution/cost_model.py:129-133, 228` |
| 5a | Realized — TCA | `analyze_fills`: per-fill edge = `realized_pnl / notional × 10⁴` where `realized_pnl` is the **per-fill differential** realized PnL (entries realize 0; exits carry the round trip's PnL). `mean_cost_bps` = mean of per-fill **one-way** modeled `TradeRecord.cost_bps`. | Per-fill (≈ one-way under balanced fills — see transformation) | `forensics/decay_detector.py:41-89`; `storage/trade_journal.py:29-33, 45` |
| 5b | Realized — SURVIVES verdict | `mean_edge_bps ≥ 1.5 × mean_cost_bps` (per-fill gross edge vs per-fill one-way modeled cost), after BLEED (`net ≤ 0`) and LOW_N (`n < 20`) checks. | Commensurate per-fill/one-way ratio ✓ | `forensics/cost_survival.py:31-42, 79-100, 123` |
| 5c | Realized — calibration | `haircut = clamp(realized_per_fill_mean / disclosed_edge_estimate_bps, 0, 1)`; `lcb_factor` same with `mean − z·std/√n`. `disclosed_edges` map is fed straight from `cost_arithmetic.edge_estimate_bps`. | Realized per-fill mean vs disclosed one-way — commensurate ✓ | `forensics/edge_calibration.py:50-62, 102-112`; `forensics/session_reconcile.py:93, 104-133` |
| 5d | Realized — runtime alert | Per-fill `ack.cost_bps` compared to `1.5 × g12_disclosed_cost_total_bps`, message says "G12 disclosed **one-way** cost_total_bps" — the runtime cost telemetry also treats the disclosure as one-way. | ONE-WAY ✓ | `kernel/orchestrator.py:5782-5828` |

### Hop 3 detail — B4 as wired

- **`basis` source:** `PlatformConfig.signal_edge_cost_basis`, default
  `"round_trip"` (`core/platform_config.py:310, 1604`; orchestrator default
  `kernel/orchestrator.py:737`, config override `:1449-1450`). Validated to
  `{one_way, round_trip}` (`platform_config.py:832-836`).
  `platform.yaml:156-157` sets `signal_min_edge_cost_ratio: 1.0` and
  `signal_edge_cost_basis: round_trip`, both equal to the code defaults,
  so no behavioral or units impact.
- **`min_ratio` source:** `PlatformConfig.signal_min_edge_cost_ratio`,
  default **1.0** = round-trip breakeven (`platform_config.py:304-309,
  1570`; orchestrator `:732, 1445-1446`). The config comment states the
  equivalences explicitly: "operators wanting G12-equivalent 1.5× one-way
  (≈ 0.75× round-trip) margin can set 0.75" (`platform_config.py:304-308`).
- **Calibration factor:** multiplies the edge *before* the ×2 —
  `effective_edge = edge_estimate_bps × factor` with
  `factor = _edge_calibration_factors.get(strategy_id, 1.0)`
  (`kernel/orchestrator.py:3200-3201`), factors loaded at construction from
  `EdgeCalibrationStore.factors()` (lcb_factor) via bootstrap.
- **`rt_cost_bps` contents at this call site**
  (`kernel/orchestrator.py:3189-3196` → `_round_trip_cost_bps:3223-3293` →
  `position_manager.round_trip_cost_bps:507-547` →
  `cost_model.estimate_round_trip_cost_bps:570-697`): entry leg (taker or
  maker per execution mode; `is_taker_entry=(not _use_passive_entries or
  _min_cost_policy is not None)`) **plus exit leg always priced as taker**
  (`position_manager.py:539`; rationale `cost_model.py:605-615`). Each leg
  includes: half-spread crossing cost (taker legs only, stressed),
  commission (0.0035/sh, min $0.35, 1% cap), taker exchange fee 0.003/sh,
  maker adverse selection (maker legs), SEC-side `sell_regulatory_bps` +
  FINRA TAF on the SELL leg, HTB on short-entry sells, and — because the
  orchestrator passes `bid_size`/`ask_size` + impact knobs — depth-aware
  walk-the-book impact and the within-L1 premium
  (`orchestrator.py:3250-3293`). This is a **genuinely round-trip** figure.
- **Call sites:** standalone entry intents (`orchestrator.py:4742-4754`)
  and the entry leg of a REVERSE (`:4485-4497`). Exits and stops bypass B4
  (`not is_exit_or_stop`, `:4739-4742`) — the gate never blocks risk
  reduction (Inv-11).

### Hop 2 detail — how G12 relates to Inv-12's "expected_edge > 1.5 × round_trip_cost"

G12 enforces `edge_ow ≥ 1.5 × C_ow` on commensurate one-way quantities.
Whether that "equals" Inv-12 depends on which basis you read Inv-12's
`expected_edge` in — the two readings differ by exactly 2× and the platform
resolves the ambiguity explicitly:

- **Same-basis reading (both sides round-trip):** `2·edge_ow ≥ 1.5 ×
  2·C_ow ⇔ edge_ow ≥ 1.5·C_ow` — **G12 is exactly Inv-12**. This is the
  reading the B4 gate operationalizes via the ×2 (`platform_config.py:
  297-302`).
- **Mixed reading (one-way edge vs round-trip cost):** would require
  `edge_ow ≥ 1.5 × 2·C_ow = 3·C_ow`, i.e. margin_ratio ≥ 3.0 — **2× stricter
  than G12 as shipped**. No code implements this reading.

The `cost_arithmetic.py` docstring quantifies the same fact from the other
side: "the disclosed `margin_ratio` is a one-way figure and is ~2× more
generous than the round-trip survival margin; a disclosed `margin_ratio` of
1.6 corresponds to an `edge / round_trip` of ~0.8" (`alpha/cost_arithmetic.py:
43-46`), and defers the authoritative round-trip check to B4 (`:50-54`).
**Discrepancy quantified, not papered over: under the mixed reading G12 is
2× looser than the invariant text; under the same-basis reading (which B4
implements) it is exact.** The one-way disclosure convention is what makes
the same-basis reading hold — which is precisely why a round-trip disclosure
would corrupt it.

Note also that the B4 **default** bar (`min_ratio=1.0`) is round-trip
*breakeven*, weaker than 1.5×: at runtime the 1.5 margin lives in G12 (load),
in the SURVIVES verdict (forensics), and in the Inv-12 stress run — not in
the un-stressed B4 default.

### Hop 5 detail — like-for-like transformation for realized vs disclosed

`TradeRecord.realized_pnl` is per-fill differential: entry fills realize 0;
a round trip's PnL lands on its exit fill(s) (`storage/trade_journal.py:
29-33`). Under the BT-3 convention fills execute at crossed prices, so
`realized_pnl` is already net of both spread crossings and gross of explicit
fees (`trade_journal.py:60-74`). Therefore:

- Per **round trip**: `realized_rt_bps ≈ mean_edge_bps × (n_fills /
  n_round_trips) ≈ 2 × mean_edge_bps` when entry/exit fill counts are
  balanced (one entry + one exit per round trip).
- The convention `edge_estimate_bps` = expected PnL **per fill** in bps
  means: **`mean_edge_bps ↔ edge_estimate_bps` compare directly, and
  `mean_cost_bps ↔ cost_total_bps` compare directly** — both per-fill
  one-way. Equivalently on the round-trip basis:
  `round_trip_disclosed = 2 × edge_estimate_bps` compares to
  `2 × mean_edge_bps ≈ realized_rt_bps`.
- The calibration factor `mean / disclosed` (`edge_calibration.py:111`) is
  therefore a dimensionless realization ratio of commensurate quantities —
  exactly what B4 multiplies back in.

**Caveat (C1):** the ≈ holds only when fill counts per round trip are
balanced. Partial entry fills (passive partials, scale-ins) inflate
`n_fills` without adding realized edge and bias `mean_edge_bps` **downward**
— a conservative bias for the SURVIVES verdict and calibration haircut, but
one Task-6 accounting must state when quoting realized-vs-disclosed ratios.

**Caveat (C2):** `pct_edge_covers_cost` counts fills with `edge > 2 ×
cost_bps` (`decay_detector.py:88`) — a per-fill edge against a doubled
one-way cost. This is a *stricter* per-fill screen than the SURVIVES mean
ratio; do not treat the two as the same statistic. `detect_edge_decay` uses
net-of-fees edge (`decay_detector.py:150-156`) while `analyze_fills` edge is
gross — also not interchangeable.

---

## Worked example (Task-6 plausibility floor)

Hypothetical midcap candidate, disclosure components:
`half_spread_bps = 2.5`, `impact_bps = 3.0`, `fee_bps = 1.0`
→ one-way `cost_total_bps C_ow = 6.5`; round-trip proxy `RT = 2 × 6.5 = 13.0`.
(These match the template's cost row exactly; the template's edge of 11.7
would carry margin 1.8.)

| Gate | Inequality (one-way edge `e`) | Minimum `e` |
|---|---|---|
| G12 load (`MIN_MARGIN_RATIO = 1.5`) | `e ≥ 1.5 × 6.5` | **9.75 bps** |
| B4 runtime, defaults (`min_ratio = 1.0`, basis round_trip, calibration factor 1.0) | `2e ≥ 1.0 × 13.0` | 6.50 bps |
| B4 under `--inv12-stress` (variable costs ×1.5 → RT ≈ 19.5) | `2e ≥ 1.0 × 19.5` | **9.75 bps** |

**Minimum one-way `edge_estimate_bps` that clears every gate: 9.75 bps**
(declared `margin_ratio` = 9.75 / 6.5 = **1.50**, exactly at the G12 floor).
This is the **Task-6 plausibility floor**. Note the identity that makes the
two binding rows agree: B4-under-1.5×-stress at `min_ratio = 1.0` is
arithmetically G12's 1.5× one-way bar (`2e ≥ 1.5·2C ⇔ e ≥ 1.5C`).

Qualifications on the floor:

1. It is the **disclosure-arithmetic** floor. The runtime B4 `rt_cost_bps`
   is the quote-dependent model figure (min-commission floor on small
   notional, depth-aware impact, sell-side regulatory/TAF, HTB) and can
   exceed the `2 × C_ow` proxy — clearance must be re-verified against the
   modeled round trip at candidate size/price during Task 8/9 runs.
2. A candidate disclosing exactly 9.75 has **zero headroom**: any positive
   calibration haircut (`factor < 1.0`) from the close-the-loop store
   fails the stressed gate on the next session. Task-6 cards should treat
   9.75 as the hard floor and something like the template's 1.8 margin
   (11.7 bps) as the working target.
3. `core/inv12_stress.py:58-70` also defines a stricter load-time survival
   helper (`disclosure_survives_inv12_cost_stress`: margin/1.5 ≥ 1.5 ⇔
   margin ≥ 2.25 ⇔ `e ≥ 14.625` on these costs), but **no production
   caller exists** — only `tests/core/test_inv12_stress.py` imports it. It
   does not bind; recorded here so Task 6 doesn't rediscover it as a phantom
   gate.

---

## Additional caveat found while tracing (C3 — tolerance wording)

The G12 reconciliation is `abs(computed − declared) ≤ 0.05` in **absolute
ratio units** (`alpha/cost_arithmetic.py:95, 248`), while the invariants
glossary and the code comment say "5%"/"±5%". At margin 1.5 the absolute
0.05 is ±3.3% relative; at 1.8 it is ±2.8%. Direction: code is *tighter*
than the documented ±5% for all margins above 1.0 — safe direction, but the
skill text should say "±0.05 absolute on the ratio". Folded into the Task-2
amendment below.

---

## Amendment for the Task-2 gap report (rider on cost-arithmetic skill text)

> **Units-convention rider (FQ-1, NORMATIVE).** The microstructure-alpha
> skill's cost-arithmetic section must state explicitly: (i)
> `edge_estimate_bps` and all three cost components are **one-way
> (per-fill) quantities in bps of fill notional**; declaring round-trip
> figures is a disclosure error that systematically loosens the B4 runtime
> gate, which doubles the disclosed edge onto the round-trip basis
> (`signal_edge_cost_basis: "round_trip"` default) before comparing against
> `min_ratio ×` modeled entry+taker-exit round-trip cost at
> `signal_min_edge_cost_ratio` default 1.0; (ii) the optional `cost_basis`
> YAML field (default `one_way`) records the basis and `round_trip` is
> accepted but reserved — no shipped alpha uses it and Task-6+ candidates
> must not; (iii) `margin_ratio ≥ 1.5` is a **one-way** figure ≈ 0.75× on
> the round-trip basis, and the reconciliation tolerance is ±0.05 absolute
> on the ratio (not ±5% relative); (iv) realized-edge comparisons
> (forensics TCA, SURVIVES verdict, calibration haircut) are per-fill
> quantities directly commensurate with the one-way disclosure under
> balanced entry/exit fill counts. Task 3 encodes this rider when editing
> the skill text.

**OQ-2 is RESOLVED. This convention is normative for Tasks 3, 5, 6, 7, 8,
9, 12, 13. Task 2 is cleared to run.**
