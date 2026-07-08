<!--
  File:   docs/research/prompt_pack_00c_eval_canon.md
  Status: NORMATIVE — FROZEN WITH TASK 8. Canonical evaluation
          configuration for Phase-B/C evidence runs (Task FQ-2,
          2026-07-07). Resolves OQ-4 and OQ-6 of
          docs/research/prompt_pack_00_architecture_verification.md.
  Owner:  backtest-engine (realism profile) / cross-cutting (evidence
          validity); prompt-pack Task FQ-2, Phase A.
-->

# Prompt-pack Task FQ-2 — Canonical evaluation configuration

## Decisions codified

**(A) Zero fill latency is forbidden in evidence-producing runs.**
With `backtest_fill_latency_ns = 0` both routers fill immediately on the
**submit-time quote** — the same tick that produced the signal
(`execution/backtest_router.py:286-297`;
`execution/passive_limit_router.py:390-400` aggressive path; resting
passive posts are gated only by `ack_timestamp_ns`, which collapses to
the submit tick at zero latency, `passive_limit_router.py:589-593`).
That is the optimistic immediate-fill mode (drift item D5), not a
realism setting. Evidence configs pin the BT-17 reference latencies —
`backtest_fill_latency_ns = 50_000_000`, `market_data_latency_ns =
20_000_000` (`platform.yaml:115-117`; defaults
`core/platform_config.py:36-38, 176-178`) — doubled under
`--inv12-stress` (`core/inv12_stress.py:41-55`;
`harness/backtest_cli.py:91-99`). Zero latency remains permitted ONLY in
unit-test fixtures that need it, never in a config whose output feeds
the ledger.

**(B) The canonical realism profile is a PINNED COPY, not "platform.yaml
at run time".** The root `platform.yaml` is mutable and acceptance/
determinism fixtures couple to it (its own header notes the APP baseline
was re-baked when the realism knobs flipped, `platform.yaml:195-202`).
The profile below is pinned at commit
**`825a7bc3bda48d3a819fed0a498dbf9d65e711c4`** (2026-07-05, working tree
clean for `platform.yaml` at capture time). Task 9 instantiates
`configs/bt_<ALPHA_ID>.yaml` from this profile.

**Pinning method:** `PlatformConfig.snapshot()` serialises the
normalised config dict (paths reduced to basenames) as sorted JSON and
takes a SHA-256 `checksum` (`core/platform_config.py:974-995,
997-1005`); every knob in the table below is folded into that dict
(`:1091-1155`), so any drift from the pinned profile changes the
snapshot checksum. `timestamp_ns` is never folded into the checksum
(`:983-984`), so the pin is replay-stable (Inv-5). The Task-9 config
guard (amendment below) asserts the loaded profile's checksum against
the value recorded when `configs/bt_<ALPHA_ID>.yaml` is created.

---

## 1. Canonical realism profile (pinned knob table)

Reference `platform.yaml` at the pinned commit vs `PlatformConfig` code
defaults. "yaml" citations are `platform.yaml` lines; "default"
citations are `src/feelies/core/platform_config.py` lines.

### Latency + execution mode

| Knob | Pinned value | Default | Citations |
|---|---|---|---|
| `execution_mode` | `passive_limit` | `market` | yaml:185; default:254 |
| `backtest_fill_latency_ns` | 50_000_000 (50 ms) | same | yaml:116; default:37, 176 |
| `market_data_latency_ns` | 20_000_000 (20 ms) | same | yaml:117; default:38, 178 |

### Passive fill model

| Knob | Pinned value | Default | Citations |
|---|---|---|---|
| `passive_fill_delay_ticks` | 3 | 3 | yaml:186; default:272 |
| `passive_max_resting_ticks` | 8000 | 50 | yaml:187; default:274 |
| `passive_queue_position_shares` | 200 | 0 | yaml:189; default:279 |
| `passive_fill_hazard_max` | 0.5 | 0.5 | yaml:192; default:283 |
| `passive_cancel_fee_per_share` | 0.0 | 0.0 | yaml:193; default:285 |
| `passive_through_fill_size_cap_enabled` | **true** | false | yaml:206; default:457 |
| `passive_require_trade_for_level_fill` | **true** | false | yaml:210; default:462 |
| (`passive_rebate_per_share`) | not set (0.002 default, **parsed but ignored** with deprecation warning — maker economics live in `cost_maker_exchange_per_share`) | 0.002 | default:276; `platform_config.py:1267-1272` |

### Impact / slippage realism

| Knob | Pinned value | Default | Citations |
|---|---|---|---|
| `cost_market_impact_factor` | not set → 0.5 | 0.5 | default:414 |
| `cost_max_impact_half_spreads` | 4.0 | 10.0 | yaml:183; default:421 |
| `cost_within_l1_impact_factor` | 0.3 | 0.0 | yaml:213; default:439 |
| `cost_permanent_impact_coefficient` | 0.0 (deliberately not flipped — needs calibration) | 0.0 | yaml:222; default:444 |
| `cost_stop_depth_depletion_factor` (forced-exit depletion) | 2.0 | 1.0 | yaml:216; default:453 |
| `cost_stop_slippage_half_spreads` | not set → 2.0 | 2.0 | default:241 |
| `cost_moc_penalty_bps` | 3.0 (inert for non-MOC alphas) | 0.0 | yaml:219; default:448 |

### Cost model — commissions, fees, adverse selection

| Knob | Pinned value | Default | Citations |
|---|---|---|---|
| `cost_min_spread_bps` | 0.3 | 0.3 | yaml:125; default:209 |
| `cost_commission_per_share` | 0.0035 | 0.0035 | yaml:126; default:210 |
| `cost_taker_exchange_per_share` | 0.003 | 0.003 | yaml:127; default:212 |
| `cost_maker_exchange_per_share` | 0.0 | 0.0 | yaml:130; default:213 |
| `cost_min_commission` | 0.35 | 0.35 | yaml:141; default:227 |
| `cost_max_commission_pct` | 1.0 | 1.0 | yaml:142; default:228 |
| `cost_passive_adverse_selection_bps` (LEVEL/drain) | 2.0 | 2.0 | yaml:133; default:219 |
| `cost_through_fill_adverse_selection_bps` (THROUGH) | 5.0 | 5.0 | yaml:134; default:220 |
| `cost_adverse_selection_through_bps` / `_drain_bps` (legacy aliases, kept aligned) | 5.0 / 2.0 | 5.0 / 2.0 | yaml:136-137; default:223-224 |
| `cost_sell_regulatory_bps` | 0.5 | 0.5 | yaml:139; default:225 |
| `cost_stress_multiplier` | 1.0 (baseline; ×1.5 under `--inv12-stress`) | 1.0 | yaml:140; default:226 |
| `cost_finra_taf_per_share` / `_max_per_order` | not set → 0.000166 / 8.30 | same | default:233-234 |
| `cost_min_commission_applies_to_per_share_only` | not set → true | true | default:235 |
| `cost_spread_floor_taker_only` | not set → true | true | default:236 |
| `cost_htb_borrow_annual_bps` | 0.0 (HTB fee off — optimistic for SHORT alphas, documented) | 0.0 | yaml:174-177; default:426 |

### Regulatory / session constraints

| Knob | Pinned value | Default | Citations |
|---|---|---|---|
| `halt_on_condition_codes` / `halt_off_condition_codes` | `[]` / `[]` (**halt modeling inert** on this profile) | `()` | yaml:73-74; default:132-133 |
| `halt_resolution_blackout_seconds` | 60 | 60 | yaml:75; default:134 |
| `ssr_active_symbols` / `ssr_trigger_condition_codes` | `[]` / `[]` (SSR inert) | `()` | yaml:83-84; default:144-145 |
| `ssr_mode` | `refuse_short` | same (only implemented value) | yaml:85; default:146 |
| `borrow_availability` | `{}` (all symbols easy-to-borrow) | `{}` | yaml:91; default:153 |
| `borrow_default_tier` | not set → `available` | `available` | default:466 |
| `account_type` | `margin_25k` (PDT-exempt; only implemented value) | `margin_25k` | yaml:101; default:184 |
| `pdt_min_equity_usd` | 25000.0 | 25000.0 | yaml:105; default:188 |
| `platform_min_order_shares` | 50 | 1 | yaml:224; `platform_config.py:1569` |

**Profile caveats that carry into evidence interpretation:** halt/SSR
modeling is inert (empty code lists) and HTB fees are off — candidate
evaluation on this profile does not price halts, SSR refusals, or borrow
cost. Task-6 cards for SHORT-biased or halt-prone candidates must say
so. Note also `signal_min_edge_cost_ratio: 1.0` on the reference profile
is documented as intentionally permissive; deployment configs override
to 1.5 (`platform.yaml:144-156`) — Task 9's instantiated config must
adopt the deployment value 1.5, consistent with the FQ-1 floor
arithmetic (which used the stressed 1.5× bar).

---

## 2. Through-fill size-cap characterization (fill-model doc gap, D6)

All citations `src/feelies/execution/passive_limit_router.py`. The cap
is active on the canonical profile
(`passive_through_fill_size_cap_enabled: true`, `platform.yaml:206`;
constructor `:170, 199-201`).

**Trigger.** A resting passive limit order through-fills when the
opposite BBO crosses its level — BUY: `ask <= limit`; SELL: `bid >=
limit` (`_evaluate_fill:703-715`). Fill price is the limit **or better**
(gapped-through BBO), snapped on the maker grid (`:614-625, 918-923`).

**Cap arithmetic.** `remaining_qty = request.quantity −
pending.filled_quantity`; with the cap enabled, `fill_qty =
min(remaining_qty, crossing_size)` where `crossing_size` is the crossing
quote's opposite-side displayed size (`ask_size` for BUY, `bid_size` for
SELL) (`:627-637`). Degenerate case: `crossing_size <= 0` falls back to
filling the **full remainder** (`:638-639`).

**Partial-fill semantics.** When `fill_qty < remaining_qty` the router
emits an `OrderAck` with `status=PARTIALLY_FILLED`,
`reason="FILLED_BY_THROUGH"`, `filled_quantity=fill_qty` (`:651-663`)
and the **remainder keeps resting at the original limit** — no re-post,
no new order id; `pending.filled_quantity` accumulates (`:663`,
`_PendingOrder.filled_quantity:119-123`). The remainder can then
terminate by: (i) subsequent through-ticks (each capped again; the final
one emits `FILLED` for the last slice, `:640-650`), (ii) a **drain fill
of the remainder** (level fill defaults to `remaining` quantity via
`fill_quantity=None`, `:664-674, 914-917`), or (iii) timeout cancel
after `max_resting_ticks` total ticks → `EXPIRED` ack (`:729-730,
675-683, 1001-1010`).

**Outcome classification / stats.** Partial slices carry
`FILLED_BY_THROUGH` on the ack but only the **terminal** event is
tallied by `passive_fill_stats()`: `_record_fill` fires on the final
full-fill slice or drain (`:649, 673, 816-825`), `_record_cancel` on
timeout (`:682, 827-831`). A partially-filled-then-expired order counts
as a **cancel** in the stats despite having filled shares.

**Cost treatment of split legs.** Each slice is costed independently by
`cost_model.compute(quantity=fill_qty, is_taker=False, half_spread=0,
fill_type="THROUGH", adverse_notional_price=crossing BBO)` (`:933-944`):
zero spread cost, maker exchange rate, and the THROUGH adverse-selection
charge (5.0 bps on this profile) per slice. **Consequence: the IBKR
$0.35 minimum-commission floor applies per slice** (each `compute()`
call floors its own per-share commission, `cost_model.py:300-316`), so
an N-slice split can pay up to N× the per-order floor — conservative
(overstates cost) but diverges from IBKR's per-order billing. At
`platform_min_order_shares = 50` and 0.0035/sh, every slice below 100
shares is floored.

**Determinism.** The through path is RNG-free (trigger, price, and
`fill_qty` are pure functions of the quote and order state); the drain
path's Bernoulli trial is a SHA-256 seeded uniform over replay-stable
keys (`:793-814`); resting-order iteration is insertion-ordered per
symbol (`:226-229`). Split sequences replay bit-identically (Inv-5).

**Ambiguities → Task 12 synthetic-tape cases** (do not resolve by
reading code alone; pin behavior with tapes):

- **T12-SC1 (partial-then-expire accounting):** partial through-fill
  followed by timeout. Verify the `EXPIRED` ack carries the cancel fee
  computed on the **full original quantity**, not the unfilled
  remainder (`_append_cancel_ack` uses `pending.request.quantity`,
  `:985`) — inert on this profile (`cancel_fee = 0.0`) but wrong-basis
  if a fee is ever configured; and verify orchestrator position state
  ends at the partial quantity.
- **T12-SC2 (per-slice commission floor):** two-slice split of a
  50-share order; assert total commission = 2 × $0.35 floor (documents
  the conservative divergence from IBKR per-order billing).
- **T12-SC3 (partial-then-RTH-suppression):** partial fill, then the
  next through-tick lands outside RTH entry bounds → `_reject` emits
  `REJECTED` for an order with `filled_quantity > 0` (`:597-612`).
  Verify downstream position/journal handling of a reject-after-partial.
- **T12-SC4 (degenerate zero-size crossing):** through-tick with
  `crossing_size == 0` → full-remainder fill fallback (`:638-639`).
  Confirm intended vs. treating zero displayed size as no fill.
- **T12-SC5 (drain-of-remainder):** partial through-fill, then drain
  fill; assert the drain ack quantity equals the remainder and adverse
  selection switches to the LEVEL rate (2.0 bps) for that slice.

---

## 3. Amendments (owning tasks adopt verbatim when they run)

- **Task 8, step 6 gains:** "Evaluation runs use the pinned profile of
  `docs/research/prompt_pack_00c_eval_canon.md` (commit
  `825a7bc3bda48d3a819fed0a498dbf9d65e711c4`); configs with
  `backtest_fill_latency_ns == 0` are invalid for evidence."
- **Task 9's test plan gains a config-guard test:** loading any
  `configs/bt_<ALPHA_ID>*.yaml` asserts `backtest_fill_latency_ns > 0`
  and `market_data_latency_ns > 0`, and that the
  `PlatformConfig.snapshot().checksum` of the realism-knob subset
  matches the profile checksum recorded when the config was
  instantiated from this document (any knob drift fails the guard).
  Task 9's config also overrides `signal_min_edge_cost_ratio: 1.5`
  per the deployment convention (`platform.yaml:149-156`).
- **Task 12's precondition battery gains** the size-cap split cases
  T12-SC1 through T12-SC5 from §2, plus the existing zero-latency
  prohibition check (a Task-12 run against a config with zero fill
  latency is a precondition failure, per decision A / OQ-4).
- **Task 3's skill edit plan gains:** document the shipped through-fill
  size-cap behavior (trigger, `min(remaining, crossing_size)` cap,
  PARTIALLY_FILLED + rest-in-place remainder, terminal-only stats
  tally, per-slice cost/floor treatment) in
  backtest-engine/fill-model.md per the Shipped / Not-shipped
  convention — closing drift item D6.

**OQ-4 and OQ-6 are RESOLVED (deferred obligations discharged into the
amendments above). This profile is FROZEN WITH TASK 8.**
