# Composition Layer Audit — 2026-07-02

Scope: read-only audit of the Layer-3 PORTFOLIO cross-sectional construction path —
`UniverseSynchronizer` fan-in, `CrossSectionalRanker` (+ decay, mechanism caps),
`FactorNeutralizer`, `SectorMatcher`, `TurnoverOptimizer`, `CompositionEngine`, and
the position-store touchpoints — from `Signal` events through `CrossSectionalContext`
to `SizedPositionIntent`. No production code, baselines, configs, or ledgers were
modified.

**This is a third-generation audit of this layer** (`composition_audit_2026-06-17.md`,
`composition_audit_2026-06-20.md` precede it). Nearly every P0 and several P1 items
from the 2026-06-20 pass are now fixed in the code, tagged inline with `audit P0-N` /
`audit P1-N` comments. Section 0 verifies those fixes with fresh evidence before this
report's own findings (Sections 3-9), so the reader can trust the "still open" list
without re-deriving it. **The headline new finding (Finding N-1) is a latent
correctness gap in the very cap-enforcement machinery the 2026-06-20 fix introduced** —
not yet triggered by any shipped alpha, but a real, empirically-confirmed miscount
under configurations the platform's own load-time gate (G16 rule 8) explicitly allows.

## Verification run (read-only)

- `uv sync --all-extras` (cvxpy/ecos/numpy/scipy/pyarrow were not previously installed
  in this environment; installed per `AGENTS.md`/`CLAUDE.md` setup instructions).
- `uv run pytest tests/composition/ tests/portfolio/ -q` → **106 passed**.
- `PYTHONHASHSEED=0 uv run pytest tests/determinism/test_sized_intent_replay.py tests/determinism/test_sized_intent_with_decay_replay.py tests/determinism/test_portfolio_order_replay.py tests/determinism/test_sized_intent_solver_replay.py tests/determinism/test_cross_sectional_context_replay.py -q` → **17 passed** (ECOS/cvxpy path exercised — extras were present).
- `PYTHONHASHSEED=0 uv run pytest tests/integration/test_xsect_v1_e2e.py -q` → **6 passed**.
- `PYTHONHASHSEED=0 uv run pytest tests/integration/test_mixed_mechanism_e2e.py tests/integration/test_mixed_mechanism_universe.py tests/integration/test_dual_scale_down_e2e.py -q` → **10 passed**.
- `PYTHONHASHSEED=0 uv run pytest tests/acceptance/test_bt13_portfolio_research_only.py -q` → **5 passed**.
- `PYTHONHASHSEED=0 uv run pytest tests/integration/test_phase4_e2e.py -q` → **11 passed**.
- `uv run ruff check src/feelies/composition/ src/feelies/portfolio/` → clean.
- `uv run mypy src/feelies/composition/ src/feelies/portfolio/` → clean (14 files).
- Additional evidence-gathering: a scratch instrumentation script (not committed) drove
  one real `CompositionEngine.run_default_pipeline` boundary end-to-end and a second
  script empirically tested the mechanism-cap scaling loop's convergence behavior
  under controlled inputs. Concrete numbers from both are cited throughout below.
- No `.github/` directory (or any CI workflow file) exists anywhere in this repository —
  confirmed by direct filesystem search. This is material to Finding P1-2.

---

## 0. Fixes verified from the 2026-06-20 audit

| 2026-06-20 finding | Status now | Fresh evidence |
|---|---|---|
| P0: `factor_neutralization: false` silently overridden when `factor_loadings_dir` set | **Fixed** | `CompositionEngine.run_default_pipeline(neutralize=...)` bypasses the neutralizer per-alpha (`src/feelies/composition/engine.py:401-405`); threaded from `LoadedPortfolioLayerModule.factor_neutralization_disclosed` → `_DefaultPortfolioConstructor` (`src/feelies/alpha/portfolio_layer_module.py:210-211, 237`). Regression test `test_factor_neutralization_opt_out_bypasses_configured_loadings` (`tests/composition/test_composition_p0_fixes.py:117-148`) passes and asserts the opt-out book equals the true no-op path even with loadings configured. |
| P0: `decision_basis_hash` omits factor/sector/optimizer inputs | **Fixed** | `_compute_decision_basis_hash` (`src/feelies/composition/engine.py:59-107`) now folds in `neutralizer.provenance_digest()`, `sector_matcher.provenance_digest()`, `optimizer.provenance_digest()`, and `solver_status` (engine.py:487-502), each digest itself covering the model/loadings/sector-map/capital/caps content (factor_neutralizer.py:125-139, sector_matcher.py:78-88, turnover_optimizer.py:177-189). Verified empirically in this audit's trace: hash is stable across two independent engine instances given identical inputs, and changes when *only* `current_positions` (via `position_lookup`) differs — see Section 7. |
| P0: mechanism cap enforced pre-transform only, final breakdown "diagnostic not enforced" | **Fixed, with a new caveat (Finding N-1)** | Construction is now sleeve-based: `rank_sleeves` → per-family neutralize → `cap_family_vectors` (structural cap **before** combining) → combine → sector-match the combined book → optimize → an **emit-time cap backstop** re-derives per-family dollar attribution and re-caps if the realized breakdown still exceeds cap after the optimizer's per-name clip (`src/feelies/composition/engine.py:373-473`). This is a real architectural fix — see Section 4/5 for the residual gap this audit found in the shared cap-scaling primitive both the sleeve path and the backstop call into. |
| P0: multi-feeder mechanism attribution assigns whole symbol to largest contributor | **Fixed** | `compute_sleeve_breakdown` (`src/feelies/composition/cross_sectional.py:799-826`) attributes a symbol's *final* dollar exposure across families in proportion to each family's pre-sector weight share, so a mixed-mechanism symbol splits rather than being assigned to one "winner" family. `test_sleeve_attribution_splits_mixed_mechanism_symbol` (`tests/composition/test_composition_p0_fixes.py:257-283`) confirms both families appear in `mechanism_breakdown` and shares sum to 1.0. |
| P0: synchronizer completeness counts arbitrarily-old cached signals | **Fixed** | `_pick_feeder_signal` / `_emit_context` now apply a `signal_max_age_seconds` window (defaults to the portfolio horizon) in addition to the causal `ts <= boundary_ts_ns` filter (`src/feelies/composition/synchronizer.py:247-290, 363-365`), tagged "audit P0-5". Tests `test_stale_signal_dropped_from_completeness_legacy`, `test_explicit_max_age_override_drops_signal`, `test_stale_feeder_dropped_multi_feeder` (`tests/composition/test_synchronizer.py:214, 242, 267`) pass. |
| P0: `consumes_mechanisms` whitelist exposed but not runtime-enforced | **Fixed** | `CrossSectionalRanker.rank`/`rank_sleeves` accept `consumes_mechanisms` and zero out any contribution from a family outside the whitelist (`src/feelies/composition/cross_sectional.py:202-233, 419-428, 495-505`), threaded from the loaded module (`src/feelies/alpha/portfolio_layer_module.py:238`). `test_consumes_whitelist_excludes_undeclared_family`, `test_consumes_whitelist_drops_only_undeclared_feeder_contribution` (`tests/composition/test_composition_p0_fixes.py:154-203`) pass. |
| P1: optimizer path implicit (`_HAS_CVXPY`-driven) | **Fixed** | `TurnoverOptimizer.optimize` branches on the constructor's `require_solver` flag, set explicitly from `PlatformConfig.composition_optimizer_mode` (`"closed_form"` default, `"ecos"` opt-in) — never from whether cvxpy happens to be importable (`src/feelies/composition/turnover_optimizer.py:191-218`, `src/feelies/bootstrap.py:2013-2022`, `src/feelies/core/platform_config.py:592, 961-964`). |
| P1: factor exposures reported pre-sector/pre-optimizer | **Fixed** | `run_default_pipeline` now computes `factor_exposures` from the *final* emitted dollar book, normalized back to weights, after sector matching and optimization (`src/feelies/composition/engine.py:475-484`, tagged "audit P1-2"). |
| P1: reference `loadings.json` fixture has no `_meta.as_of_ns` | **Fixed** | The committed fixture now embeds `"_meta":{"as_of_ns":1768446000000000000}` (`src/feelies/storage/reference/factor_loadings/loadings.json`), matching `REFERENCE_AS_OF_NS` in `scripts/build_reference_factor_loadings.py:97`, and `FactorNeutralizer._load_loadings` explicitly skips the `_meta` key rather than treating it as a symbol row (`src/feelies/composition/factor_neutralizer.py:239-240`). |
| P1: no future-signal regression test | **Fixed** | `test_future_signal_not_captured_legacy`, `test_future_signal_not_captured_multi_feeder` (`tests/composition/test_synchronizer.py:294, 325`) pass. |
| P1: target-dollar rounding used binary-float `round(...,2)` | **Fixed** | `round_cents` uses `Decimal(str(x)).quantize(Decimal("0.01"), ROUND_HALF_UP)` in both the closed-form and ECOS paths (`src/feelies/composition/turnover_optimizer.py:65-74, 254-255, 361-363`), matching the risk layer's own rounding convention. |
| **P1: cross-platform solver parity unproven** | **Still open** | See Finding P1-2 below — now confirmed with the additional fact that this repository has **no CI configuration at all**, so the gate is enforced only by a code comment and a same-host test, not by any actual multi-platform run. |

The remaining 2026-06-20 P2 items (real risk model in the optimizer, sector-map
provenance metadata, property-based cap tests, portfolio-alpha purity guard for inline
`construct:` blocks) are unchanged and are re-listed in Section 9 for continuity rather
than re-derived.

---

## 1. Executive summary

- **New P0 (this audit): the mechanism-cap scaling primitive both cap-enforcement paths share (`_apply_mechanism_cap`, `cap_family_vectors`) hard-codes a 5-iteration budget that is provably sufficient only when at most one family is over cap at a time; empirically, a G16-rule-8-*valid* configuration (per-family caps summing to exactly the load-time minimum of 1.0) with 3+ simultaneously over-cap families needs 50-120 iterations to converge, so the code silently emits a `mechanism_breakdown` that materially breaches the declared cap** (`src/feelies/composition/cross_sectional.py:658-690, 765-786`; reused by the emit-time backstop at `src/feelies/composition/engine.py:462`). Not triggered by either shipped alpha (≤2 families each, with caps loose enough that simultaneous breach is arithmetically impossible); reachable by any future 3+-family PORTFOLIO alpha. Violates the "true emit-time enforcement" intent of the 2026-06-20 fix and the risk-control spirit of Inv-11. Full derivation and numbers in Section 5.
- **Documentation drift, high-value fix:** `.cursor/skills/composition-layer/SKILL.md`'s G16 table row says per-family caps must "sum ≤ 1.0"; the actual validator (`src/feelies/alpha/layer_validator.py:1098-1103`) requires the **opposite** — `sum >= 1.0 - 1e-9` — to guarantee full-book deployment is reachable. The same skill file's "Known gap" paragraph claiming mechanism caps are "not wired through at runtime" is also stale: they are (see Section 0). Both should be corrected so future audits and alpha authors do not rely on either claim.
- **P1, carried forward and reconfirmed:** the ECOS/cvxpy solver path's cross-platform (OS/BLAS) determinism remains **unverified in this repository** — there is no `.github/` directory or any CI workflow at all, so the test file's own stated condition for production use ("must not be enabled... until this module passes on at least Linux x86_64 and macOS arm64 CI runners", `tests/determinism/test_sized_intent_solver_replay.py:132-136`) has no structural enforcement, only a comment. Currently safe: `composition_optimizer_mode` defaults to `"closed_form"` and neither shipped alpha nor the reference `platform.yaml` selects `"ecos"`.
- **New P1: the turnover-penalty "current position" reference is account-level, not per-PORTFOLIO-alpha.** `_create_composition_layer`'s `_position_lookup` closure reads the single global `MemoryPositionStore` shared by the whole platform (`src/feelies/bootstrap.py:510, 2031-2036`), not a per-alpha book. Both shipped research alphas already declare the identical 3-symbol universe (`AAPL, MSFT, NVDA`); if either were ever promoted past `RESEARCH` (currently hard-blocked, see Section 2) alongside another PORTFOLIO alpha trading the same names, each alpha's `expected_turnover_usd` and L1 turnover penalty would be computed against the *other* alpha's contribution too.
- **New P1: wall-clock fallback in the factor-loadings freshness gate.** When `config.session_open_ns` is `None`, `_enforce_factor_loadings_freshness` falls back to `time.time()` (`src/feelies/bootstrap.py:2295-2304`) — self-documented in the same docstring as breaking Inv-5 bit-identical replay. Triple-gated (only fires when an operator sets `factor_loadings_dir`, which neither shipped alpha nor the reference `platform.yaml` does, **and** only when `session_open_ns` is unset), so currently dormant, but the fallback should fail closed rather than silently read the wall clock.
- **New P2, concretely demonstrated:** for small universes (the shipped alphas' N=3), the `TurnoverOptimizer`'s **default** `per_name_cap_pct=0.05` binds for *every* name simultaneously, collapsing the ranker's carefully cross-sectionally-standardized weights into a pure equal-notional, sign-only book — this audit's trace shows raw standardized weights of `0.371 / -1.367 / 0.997` all landing at exactly `±$7,500` once through the optimizer. This is flagged as a deliberate composition-shaping/risk-budget separation in the code's own docstring (turnover_optimizer.py:118-133), but the concrete magnitude of information loss is worth operator awareness — it is very likely the practical reason the shipped alphas' own YAML notes say "IR = IC × √N with N=3 does not justify composition-layer complexity."
- **Sound (verified, not just re-stated):** sector matching and the optimizer's per-name/gross clips act only on a per-symbol scalar (never per-family), so `compute_sleeve_breakdown`'s post-hoc, ratio-based dollar attribution across families remains exactly correct under any such rescale — confirmed by tracing the data flow, not merely by the passing test suite.
- **Sound:** causality is enforced twice — the synchronizer's signal cache does not filter on ingestion, but both the legacy (`s.timestamp_ns > tick.timestamp_ns → continue`, synchronizer.py:361) and multi-feeder (`s.timestamp_ns <= boundary_ts_ns`, synchronizer.py:278) context-construction paths filter causally before a signal can enter a `CrossSectionalContext`, and this is now covered by dedicated future-signal tests.
- **Sound:** `decision_basis_hash` coverage is genuinely comprehensive post-fix (Section 0); this audit independently re-verified it changes when only the turnover-penalty reference position differs, and is stable across independently-constructed engine instances for identical inputs.
- **Sound:** the fail-safe completeness design correctly separates the *quality gate* (per-alpha/platform `composition_completeness_threshold`, checked once at the engine) from the *construction math* (z-score standardization computed over "active" symbols only) — a single active symbol always produces a zero weight (population std of one point is 0), so sparse data cannot manufacture false conviction even below the gate.
- **Confirmed sound:** the reference `platform.yaml` configures neither `factor_loadings_dir` nor `sector_map_path`, so `FactorNeutralizer` and `SectorMatcher` are no-ops in the default deployment; both shipped PORTFOLIO alphas are hard-capped at `lifecycle_state: RESEARCH` and excluded from production alpha discovery, verified by `tests/acceptance/test_bt13_portfolio_research_only.py` (all 5 assertions pass).
- Full read-only verification (11 pytest invocations across composition/portfolio/determinism/integration/acceptance suites, ruff, mypy) is green; no findings in this report were surfaced by a failing test — all were found by direct code reading and targeted, out-of-band scratch scripts (see Sections 4-5, 7).

---

## 2. PORTFOLIO alpha inventory

The reference `platform.yaml` does not set `composition_optimizer_mode`, `factor_loadings_dir`,
or `sector_map_path`, so every `PlatformConfig` composition default applies unmodified
(`src/feelies/core/platform_config.py:575-592`): `composition_completeness_threshold=0.80`,
`factor_model="FF5_momentum_STR"` (inert — no loadings configured), `factor_loadings_max_age_seconds=604800`,
`composition_lambda_tc=1.0`, `composition_lambda_risk=0.1` (both inert under the default
`closed_form` optimizer mode — see Section 5), `composition_max_universe_size=50`,
`composition_optimizer_mode="closed_form"`.

| alpha_id | lifecycle | universe (N) | horizon_s | depends_on_signals | trend_mechanism.consumes caps | global cap | factor_neutralization | completeness threshold |
|---|---|---:|---:|---|---|---:|---|---|
| `pro_kyle_benign_v1` | `RESEARCH` | AAPL, MSFT, NVDA (3) | 300 | `sig_benign_midcap_v1`, `sig_kyle_drift_v1` | KYLE_INFO: 1.0 | 1.0 | `false` | platform default (0.80) — no per-alpha override declared |
| `pro_burst_revert_v1` | `RESEARCH` | AAPL, MSFT, NVDA (3) | 300 | `sig_hawkes_burst_v1`, `sig_inventory_revert_v1` | HAWKES_SELF_EXCITE: 0.6, INVENTORY: 0.6 | 0.7 | `false` | alpha param default 0.7 |

Both alphas live under `alphas/research/` and are excluded from production alpha
discovery (`discover_alpha_specs`); only `discover_research_alpha_specs` finds them
(`tests/acceptance/test_bt13_portfolio_research_only.py:32-38`, verified passing). Both
declare `lifecycle_state: RESEARCH`, which `AlphaLifecycle.promote_to_paper()` rejects
outright (`tests/acceptance/test_bt13_portfolio_research_only.py:48-61`, verified
passing) — so the cross-strategy position-store finding (P1, Section 6) and the
per-name-cap collapse (P2, Section 5) are both currently dormant, not live-production
risks, but are exactly the kind of gap the alphas' own YAML notes flag as "future
scale-up" territory (`pro_kyle_benign_v1.alpha.yaml:8-13`).

Both alphas' `trend_mechanism.consumes` caps satisfy G16 rule 8 (`sum >= 1.0 - 1e-9`,
not `<= 1.0` as the skill doc states — see Finding P0-1 below) and, critically, involve
at most 2 families each with caps loose enough (0.6+0.6, or a single 1.0) that
simultaneous multi-family cap breach is arithmetically impossible for either shipped
alpha — see Section 5 for why this matters.

`alphas/_template/template_portfolio.alpha.yaml` documents 2 families
(KYLE_INFO 0.6, INVENTORY 0.5, global 0.6, sum=1.1) — also a 2-family, non-adversarial
case.

---

## 3. Synchronizer/barrier audit

**Fan-in and emission order.** `_universe_sorted = tuple(sorted(set(universe)))`
(`synchronizer.py:138`) makes every downstream map (`snapshots_by_symbol`,
`signals_by_symbol`, `signals_by_strategy_by_symbol`) stable under input-universe
permutation. Contexts are keyed and emitted `(horizon_seconds, boundary_index)` →
exactly once (`_emitted` set, `synchronizer.py:172-173, 241-245`), triggered by the
**UNIVERSE-scope `HorizonTick`**, not "all symbols reported" — matching the
architecture contract (`docs/three_layer_architecture.md:1016-1019`). The
`CompositionEngine` separately sorts registered alphas by `(horizon_seconds, alpha_id)`
(`engine.py:176`) for stable per-context dispatch order. Both orderings are correct and
independently verified by the passing `test_deterministic_replay` /
`test_two_replays_produce_identical_intent_hash` suites.

**Causality (dimension A.4).** The signal cache itself does *not* filter on ingestion —
`_on_signal` only supersedes-by-timestamp for the same `(horizon, symbol, strategy_id)`
key (`synchronizer.py:223-234`) — but causality is enforced at context-construction time
in both paths: the multi-feeder selector filters to
`s.timestamp_ns <= boundary_ts_ns and boundary_ts_ns - s.timestamp_ns <= max_age_ns`
(`synchronizer.py:275-279`), and the legacy single-slot loop explicitly `continue`s past
any cached signal with `s.timestamp_ns > tick.timestamp_ns`
(`synchronizer.py:361-362`, commented "Causality guard (Inv-6, audit P1-7)"). No path
in this file lets a future-stamped signal enter an emitted `CrossSectionalContext`.
`test_future_signal_not_captured_legacy` / `test_future_signal_not_captured_multi_feeder`
cover this directly and pass.

**Completeness (dimension A.2).** `completeness = non_none / len(universe)`
(`synchronizer.py:382`), where `non_none` only counts symbols with a signal that is
simultaneously present, causal, fresh-enough (`stale-feeder window`, defaulting to the
portfolio horizon itself — `_max_age_ns`, `synchronizer.py:247-252`), and no older than
the matching snapshot's timestamp. This is the fixed P0-5 gate from 2026-06-20 and is
now correct by inspection: an aged signal can only ever *reduce* `non_none`, never
inflate it, satisfying Inv-11.

**Fail-safe on low completeness (dimension A.3).** The synchronizer *always* emits the
context regardless of completeness — by design ("No silent drops", docstring lines
15-19) — and the fail-safe decision is made one hop downstream by
`CompositionEngine._dispatch_one`, which resolves a per-alpha-or-platform threshold and
publishes a degenerate empty intent below it (`engine.py:219-226`). No path in either
file proceeds on a partial universe and *inflates* weights: the standardizer computes
z-score moments over the `active` subset only (`cross_sectional.py:590-613`), which is
the mathematically correct choice — imputing zero for absent symbols would bias the
cross-section away from "hold," and a single active symbol always yields
`std == 0 → all-zero weights` (no false conviction from one data point).

**Minor, unchanged from 2026-06-20:** composition order is deterministic only as a
function of upstream `HorizonTick` emission order; the synchronizer does not itself
globally sort pending contexts across simultaneously-due horizons. This remains a
modeling assumption (the scheduler's own tick order is contractual), not a bug in this
file, and is unchanged since the last pass.

---

## 4. Ranker & decay audit

**Math.** Raw score is `sign(direction) * strength * edge_estimate_bps` for a single
signal (`cross_sectional.py:293, 438`), or the deterministic sum of per-feeder
marginal contributions in multi-feeder mode (`cross_sectional.py:512-522`), iterated
in `feeder_strategy_ids` order (itself a sorted tuple from
`_union_portfolio_upstream_strategy_ids`, `bootstrap.py:1875-1882`). Decay, when
enabled, is `max(decay_floor, exp(-age_s / expected_half_life_seconds))` with `age_s`
floored at 0 (`cross_sectional.py:295-300`) — the `max(0, ...)` clamp is a correct
defensive guard against a (should-be-impossible, given the causality filters above)
negative age producing amplification instead of decay.

**Standardization** is a population z-score over `active` symbols, clipped to `±clip`
(default 4.0), with an explicit `if std == 0.0: return out` early-out
(`cross_sectional.py:571-614`) — numerically stable for the single-symbol and
zero-variance-universe edge cases named in the audit brief; independently re-derived
in this pass, not merely re-asserted from the prior audit.

**Exit-only enforcement.** `LIQUIDITY_STRESS` contributions are zeroed on the entry
path in both the legacy and multi-feeder rankers (`cross_sectional.py:432-435,
506-509`), consuming the single source of truth `EXIT_ONLY_MECHANISMS`
(`core/events.py:521-525`) shared with the SIGNAL-layer runtime guardrail — correctly
avoiding a second, potentially-drifting definition.

**Mechanism-cap enforcement — the sleeve architecture is sound; the shared scaling
primitive it (and the legacy path) call into is not.** This is the most important
finding in this audit and is developed fully in Section 5 because the same primitive
(`cap_family_vectors`) is also the emit-time backstop the optimizer section depends on;
splitting it across two sections would fragment the evidence. Summary: the fix
correctly moved cap enforcement earlier (sleeve-level, before combining) and added a
backstop (dollar-level, after the optimizer) — but both calls share a hard-coded
5-iteration budget that a proof-by-example in Section 5 shows is provably insufficient
whenever 3 or more mechanism families are simultaneously over their cap, even under
configurations G16 rule 8 explicitly allows at load time.

**Decay-off vs decay-on divergence.** Locked by
`tests/determinism/test_sized_intent_with_decay_replay.py`; re-verified passing in this
audit's run, and `test_composition_p0_fixes.py::test_decision_basis_hash_distinguishes_decay`
additionally confirms the *provenance hash* (not just the target stream) differs
between the two modes — closing the exact gap the 2026-06-20 audit flagged ("does not
assert `decision_basis_hash` changes because parity serialization omits it").

---

## 5. Optimizer determinism audit (deep dive)

### 5.1 Default (`closed_form`) path — deterministic and correctly the production default

`_create_composition_layer` selects the optimizer path with
`require_solver=(config.composition_optimizer_mode == "ecos")`
(`bootstrap.py:2013-2022`), and `composition_optimizer_mode` defaults to
`"closed_form"` (`platform_config.py:592`, confirmed absent from the reference
`platform.yaml`, so the default is what actually runs). `_optimize_closed_form`
(`turnover_optimizer.py:222-273`) is a pure, four-step deterministic rescale over the
lex-sorted `universe`: scale to `capital * gross_cap_pct`, clip per name to
`per_name_cap_pct * capital`, round to whole cents via `round_cents` (Decimal,
`ROUND_HALF_UP` — matching the risk layer's own convention), then re-shrink post-rounding
if the gross cap is marginally exceeded. `lambda_tc` / `lambda_risk` are accepted by the
constructor but genuinely unused by this path (confirmed by reading the method body —
no reference to `self._lambda_tc`/`self._lambda_risk` in `_optimize_closed_form`); this
is the same 2026-06-20 observation, unchanged, and remains correctly labeled a modeling
choice rather than a bug — the closed-form path is not a turnover optimizer in the
objective sense, it is a deterministic-by-construction rescale, and the docstring
(`turnover_optimizer.py:12-18`) is honest about this.

### 5.2 ECOS/cvxpy path — deterministic per build, unverified across builds, no CI to check it

The solver path is selected by the explicit `require_solver` flag, never by
`_HAS_CVXPY` (`turnover_optimizer.py:191-218`) — this is the fixed audit P0-1/P1-1 from
2026-06-20 and remains correct. ECOS is invoked with pinned
`abstol=reltol=feastol=1e-8`, `max_iters=100` (`turnover_optimizer.py:51-59, 330-338`),
and the objective is formulated in **weight space** (dimensionless, capital-normalized)
specifically to avoid the previously-fixed bug where a USD-space risk term swamped the
alpha term by ~10 orders of magnitude and collapsed every solve to the empty book
(`turnover_optimizer.py:285-313`, "audit P0-1/P1-1"). Solver exceptions fall back to the
closed-form path with a distinct `"ECOS_FAILED_FALLBACK"` status
(`turnover_optimizer.py:339-352`) rather than propagating or silently substituting a
different value; a non-`optimal`/`optimal_inaccurate` status returns the empty
allocation with a logged warning (`turnover_optimizer.py:354-359`) — both are
fail-safe, both are distinguishable via `solver_status` on the emitted intent.

**Finding P1-2 (carried forward, reconfirmed with new evidence): the solver's
own test suite states a precondition for production use that nothing in this
repository enforces.** `tests/determinism/test_sized_intent_solver_replay.py:129-136`
states: *"`composition_optimizer_mode: ecos` must not be enabled in production until
this module passes on at least Linux x86_64 and macOS arm64 CI runners."* This audit
searched the repository for any CI configuration (`.github/`, any top-level `*.yml`
workflow) and found **none exists**. This means:

1. The stated precondition is enforced by a code comment and a same-host pytest run
   only — there is no structural (code-level) guard that would prevent an operator
   from setting `composition_optimizer_mode: ecos` in `platform.yaml` today, on a host
   that has never been validated against the claim.
2. The only thing keeping this safe today is that the default is `"closed_form"` and
   no shipped alpha or the reference `platform.yaml` opts into `"ecos"`.
3. Per this audit's brief ("treat any optimizer nondeterminism as a P0 — it breaks
   Inv-5 platform-wide"), the *latent* severity if this flag were ever flipped without
   the referenced (currently nonexistent) CI validation is P0-class — a
   cross-platform BLAS/ECOS-build difference changing the 8th significant digit of a
   solve would change `target_positions`, the Level-3/4 parity hashes, and every
   downstream order. This is classified P1 here (not P0) strictly because it is not
   the active default and is not selected by any shipped configuration — but it should
   be closed before any operator is tempted to flip the flag.
   - **Recommended fix (S effort):** add a structural guard — e.g. raise
     `MissingOptionalDependencyError` (or a new `UnverifiedSolverPlatformError`) at
     `TurnoverOptimizer.__init__` when `require_solver=True` unless an explicit
     environment variable or config allowlist confirms the current
     `(os, arch, ecos_version)` triple has been validated — so the "must not enable
     until tested" sentence becomes enforced code, not aspirational prose. Actually
     standing up cross-platform CI runners is a larger (L) effort and orthogonal to
     this repository's audit scope.

### 5.3 Ordering and rounding

Decision variables in both paths are built by iterating the already-sorted `universe`
tuple (`turnover_optimizer.py:247-252` closed-form, `turnover_optimizer.py:291-298`
ECOS `mu`/`w_cur` construction) — deterministic variable-to-symbol binding. Rounding
is centralized in `round_cents` and applied identically in both paths
(`turnover_optimizer.py:65-74, 254-262, 361-363`). `CompositionEngine` builds
`TargetPosition`s from `sorted(target_usd.items())` (`engine.py:486-488`). No gaps
found here beyond the already-fixed 2026-06-20 rounding item.

### 5.4 Finding P0-1: the mechanism-cap scaling loop does not converge for 3+ simultaneous over-cap families, even under G16-rule-8-valid configurations

Both `_apply_mechanism_cap` (legacy single-signal path, called from
`CrossSectionalRanker.rank`, `cross_sectional.py:616-702`) and `cap_family_vectors`
(sleeve path, called twice per `run_default_pipeline` invocation — once
pre-optimizer at `engine.py:412`, once as the emit-time backstop at `engine.py:462`)
implement the *same* iterative proportional-scaling idea: for each over-cap family,
compute a scale factor assuming it is the *only* family currently over cap, apply it,
and repeat "until stable," with a hard `for _ in range(5):` budget
(`cross_sectional.py:658, 765`) justified by the in-code comment "every family's share
is monotonically decreasing" (`cross_sectional.py:653-656`).

**This audit constructed and ran three concrete counter-examples** (not part of the
committed test suite — ad hoc verification scripts) directly against
`cap_family_vectors`:

1. **3 families, equal gross, caps 0.4/0.4/0.4 (sum 1.2, G16-valid), raw shares
   0.45/0.45/0.10** → after 5 iterations: `{KYLE_INFO: 0.4116, INVENTORY: 0.4116,
   HAWKES_SELF_EXCITE: 0.1767}` — **two families ~3 points over their 0.4 cap**, not a
   rounding artifact.
2. **4 families, caps 0.27/0.27/0.27/0.27 (sum 1.08, G16-valid), raw shares
   0.35/0.30/0.30/0.05** → after 5 iterations: `{KYLE_INFO: 0.2937, INVENTORY: 0.2945,
   HAWKES_SELF_EXCITE: 0.2945, SCHEDULED_FLOW: 0.1173}` — three families over their
   0.27 cap by ~2.4 points (about **9% relative overshoot**).
3. **Same 4-family setup with caps at exactly the G16 rule-8 minimum, sum = 1.0** →
   still `~0.278/0.279/0.279` vs. a 0.25 cap after 5 iterations.
4. **Re-running case 2 with the iteration budget artificially raised** (10 → 50 → 500
   iterations, same update rule) shows the algorithm *does* converge to the
   mathematically correct fixed point (`0.27/0.27/0.27/0.19`, satisfying every cap
   exactly) — but only after **50-120 iterations**, one to two orders of magnitude past
   the shipped budget of 5.

This confirms the failure is not "the fixed point doesn't exist" (it does, and the
update rule finds it eventually) — it is that **the per-family update formula is only
exactly correct when at most one family is over cap at a time** (it treats "all other
families" as fixed when solving for one family's scale factor); with 2+ simultaneously
over-cap families the formula is a slow-converging approximation, and 5 iterations is
nowhere near enough once 3+ families interact. Because
`if not adjusted: break` only exits early when a pass makes *zero* changes, the loop
never "gives up" prematurely in these examples — it genuinely runs out of budget mid-
convergence, silently, with no warning, log, or assertion that the returned breakdown
actually satisfies the caps it was asked to enforce. The **emit-time backstop in
`run_default_pipeline` (engine.py:449-462) inherits this exactly** — it calls
`cap_family_vectors` a second time with the identical 5-iteration budget, so a residual
breach that survives the first (sleeve-level) capping pass is not corrected by the
"backstop"; it is merely re-approximated with the same flawed convergence rate.

**Reachability.** G16 rule 8 (`layer_validator.py:1049-1103`) validates only that
`share_total >= 1.0 - 1e-9` and each individual cap is in `[0, 1]` — it does **not**
bound how many families may simultaneously exceed their own cap under realistic signal
skew, and does not require caps to be "loose" relative to the family count. All three
of this audit's counter-examples are configurations G16 would accept at load time.
Neither shipped alpha triggers this: `pro_kyle_benign_v1` has one family (no
simultaneity possible); `pro_burst_revert_v1` has two families capped at 0.6/0.6 —
since two shares summing to 1.0 cannot both exceed 0.6 simultaneously (0.6+0.6 > 1.0
leaves no room), that specific configuration is arithmetically immune. **Any future
PORTFOLIO alpha consuming 3 or more of the platform's 5 `TrendMechanism` families with
moderately tight caps is not immune.**

**Test-suite blind spot, confirmed.** `test_mixed_mechanism_universe.py` is the one
integration test that *does* exercise 3 simultaneously-active families (KYLE_INFO,
INVENTORY, HAWKES_SELF_EXCITE over a 9-symbol universe, one shared cap
`_MECHANISM_CAP = 0.4`, `tests/integration/test_mixed_mechanism_universe.py:48`) and it
asserts "every reported family share is ≤ the engine's configured per-family cap" — and
it passes. This is not a contradiction: with 3 symbols per family and a
deterministically-varied-but-roughly-balanced fixture (`_make_signal`,
`tests/integration/test_mixed_mechanism_universe.py:76-94`), realized shares land close
to the natural 1-in-3 split (~0.33), comfortably under 0.4, so **at most one family is
ever over cap in that fixture** — the same "single-family" regime the update rule
handles correctly in one pass. The passing test therefore provides no evidence against
this finding; it simply never constructs the adversarial multi-family skew needed to
expose the convergence gap. `tests/composition/test_composition_p0_fixes.py::test_sleeve_cap_holds_on_emitted_book`
is the other cap test that exercises the sleeve path directly, and it also uses only 2
families (KYLE_INFO ×4 symbols, INVENTORY ×2 symbols).

**Recommended fix (S/M effort):** either (a) raise the iteration budget substantially
(the 500-iteration experiment above still ran in milliseconds — this is cheap) and add
an explicit post-loop tolerance check that logs a warning (or raises, consistent with
Inv-11) when the returned breakdown still exceeds any cap by more than a small
epsilon, or (b) replace the per-family-independent update with a proper simultaneous
multi-constraint water-filling solve (more correct, more effort, not required for
correctness given (a) is cheap and sufficient). Either fix should re-baseline the
Level-3 decay-on/off and solver parity hashes in the same commit if the numeric output
of any *currently-passing* fixture changes (none of the fixtures audited in this pass
appear to be in the multi-simultaneous-breach regime, so a re-baseline is unlikely to
be needed, but should be checked).

---

## 6. Neutralization / sector audit

**Factor-loading ingestion, staleness, causality.** `FactorNeutralizer` is a no-op
(`dict(weights)` passthrough) when `loadings_dir=None` (`factor_neutralizer.py:154-157`)
— the case for the reference `platform.yaml` and both shipped alphas. When configured,
`_enforce_factor_loadings_freshness` (`bootstrap.py:2241-2319`) fail-stops the whole
bootstrap if any universe symbol is missing from `loadings.json` or if the file's
effective age exceeds `factor_loadings_max_age_seconds` — correctly Inv-11 (refuse to
boot rather than silently neutralize against a stale model). The freshness reference
timestamp prefers the file's own embedded `_meta.as_of_ns` (reproducible,
content-addressable) over filesystem mtime (`bootstrap.py:2283-2293`), and compares
against `config.session_open_ns` when available (deterministic, replay-safe).

**Finding P1-3: wall-clock fallback in the freshness gate.** When
`config.session_open_ns is None`, the comparison falls back to `time.time()`
(`bootstrap.py:2297-2298`), and the code's own log message states this "breaks
bit-identical replay (Inv-5)" (`bootstrap.py:2299-2304`) — the developers were aware of
this at the time it was written. The practical exposure is narrow but real: this
function only executes at all when an operator sets `factor_loadings_dir` (neither
shipped alpha nor the reference `platform.yaml` does), and within that, only when
`session_open_ns` is additionally unset. Under those two conditions, though, **the same
historical replay could pass or fail the freshness gate depending purely on the wall-
clock time at which it happens to be re-run** — a bootstrap-composition-time
non-determinism, not a per-tick one, but still a violation of "same inputs →
bit-identical outputs" at the level of "does the platform boot at all." Recommended fix
(S effort): raise `StaleFactorLoadingsError` outright when `session_open_ns` is `None`
and `factor_loadings_dir` is configured, rather than silently reading the wall clock —
forcing the operator to supply a deterministic reference time instead of accepting an
already-self-diagnosed Inv-5 violation.

**Neutralization math.** `w_neutral = w - B @ ((BᵀB)⁻¹ @ Bᵀ @ w)`
(`factor_neutralizer.py:143-181`) is the standard OLS-residual projection; singular
`BᵀB` falls back to `numpy.linalg.lstsq` rather than raising, and reports the
(possibly non-zero) residual exposure on degenerate subspaces rather than pretending it
is zero (`factor_neutralizer.py:168-181`) — correct and honest. All linear algebra runs
in NumPy `float64` over the lex-sorted universe, so replay is bit-stable modulo NumPy's
own BLAS-backend determinism (the same class of cross-platform caveat as Section 5.2,
but the platform's default reference config never exercises this path, since
`factor_loadings_dir` is unset).

**Sector matching.** No-op when `sector_map_path=None` (the reference config).
When active, the "scale only the dominant side" algorithm
(`sector_matcher.py:90-129`) is deterministic (sorted sector iteration) and
conservative (a one-sided sector is flattened to zero, not left net-exposed) — this is
the already-fixed 2026-06-20 P1-3 item (uniformly scaling both sides never reaches
`net=0`; the current code correctly scales only the dominant side).

**Verified sound (new to this audit, not previously stated): sector matching cannot
desynchronize the per-family cap attribution, because it only ever sees the *combined*
per-symbol scalar, never a per-family sub-vector.** `run_default_pipeline` combines
sleeves into `combined: dict[str, float]` *before* calling
`self._sector_matcher.neutralize(combined, ctx.universe)` (`engine.py:414-422`); the
matcher (and, similarly, the optimizer's per-name/gross rescale) can only multiply a
given symbol's *entire* weight by a single scalar — it has no way to treat one family's
contribution to a symbol differently from another's. Since `compute_sleeve_breakdown`
attributes final dollars back to families using the *pre-sector-match* per-family
weight ratio for that symbol (`cross_sectional.py:799-826`), and a uniform per-symbol
rescale preserves that ratio exactly, the post-hoc attribution remains exact through
sector matching and the optimizer's clipping — verified by tracing the data flow (both
functions only ever consume `dict[str, float]`, never a per-family-keyed structure),
not merely by the passing tests.

---

## 7. `decision_basis_hash` & provenance audit

**Coverage, re-verified in this pass.** `_compute_decision_basis_hash`
(`engine.py:59-107`) folds in, per symbol: raw score, decay factor, assigned mechanism
name, and current position (2dp); plus the resolved global/per-family caps, the
`neutralize` opt-out flag, the `consumes_mechanisms` whitelist, and three
component-provenance digests (`neutralizer.provenance_digest()`,
`sector_matcher.provenance_digest()`, `optimizer.provenance_digest()`) plus the
terminal `solver_status`. Each digest is itself content-addressable over the relevant
component's decision-affecting state (factor model name + full loadings table;
active/tolerance + sector map; capital/caps/lambdas/solver-path selection) — so the
factor/sector/optimizer inputs the 2026-06-20 audit found missing are now genuinely
present, not merely referenced by name.

This audit's own instrumentation (Section "Verification run") independently confirmed
two properties beyond what the committed unit tests assert directly:

1. **Stability across independent engine instances.** Two freshly-constructed
   `CompositionEngine`s (separate `EventBus`, separate `SequenceGenerator`, identical
   configuration) given the identical `CrossSectionalContext` produced byte-identical
   `decision_basis_hash` and `target_positions` — confirming the hash and the book are
   pure functions of the declared inputs, not of construction-order incidentals.
2. **Sensitivity to the one input most likely to be missed: the turnover-optimizer's
   `current_positions` reference.** Re-running the identical context through a third
   engine instance with a non-trivial `position_lookup` (nonzero starting positions in
   2 of 3 symbols) changed `expected_turnover_usd` (22,500 → 19,500, as expected — the
   optimizer's L1 term now has a nonzero reference point) **and** changed
   `decision_basis_hash`, confirming this input is genuinely covered and not silently
   dropped, closing exactly the "current positions formatted to 2dp — is that actually
   threaded through?" concern raised (but not fully closed) by the 2026-06-20 pass.

**Remaining minor gap (P2, not re-elevated).** The Level-3 golden parity-hash tests
(`test_sized_intent_replay.py`, `test_sized_intent_with_decay_replay.py`,
`test_portfolio_order_replay.py`) still intentionally exclude `decision_basis_hash` and
`solver_status` from their hashed content (`_hash_intent_stream`,
`tests/determinism/test_sized_intent_replay.py:180-201` — no reference to either field)
— by design, per the field's own docstring, so introducing the fields did not
retroactively break pre-existing baselines (`core/events.py:756-774`). This audit
confirms `decision_basis_hash`'s *own* determinism is separately and adequately covered
by `test_composition_p0_fixes.py`'s direct-call property tests (replay-equality,
sensitivity-to-each-input) and by this audit's own bus-level re-verification above — so
this is a completeness note for the golden-baseline suite, not an open correctness gap.

**Correlation IDs.** `intent:{alpha_id}:{horizon_seconds}:{boundary_index}` (degenerate:
`...:degenerate`) is unique per `(alpha_id, horizon_seconds, boundary_index,
degeneracy)` given unique alpha IDs (`engine.py:279, 317`) and stronger than the
`intent:<alpha_id>:<boundary_index>` format the original audit-prompt template
mentions (this format additionally disambiguates by horizon) — unchanged from
2026-06-20, re-confirmed.

**`CrossSectionalTracker`.** Records only the latest per-strategy snapshot, no
wall-clock reads, lex-sorted iteration for stable JSON emission
(`portfolio/cross_sectional_tracker.py:19-25, 111-113`); correctly parses
`boundary_index` from either correlation-ID format defensively
(`cross_sectional_tracker.py:168-194`). Its `mechanism_breakdown` is, by contract, the
*pre-veto* value recorded from the published `SizedPositionIntent`
(`cross_sectional_tracker.py:8-12`) — the risk-engine's per-leg veto can still change
realized exposure downstream; this is the documented risk-engine contract boundary
(out of scope here, correctly not re-computed in this layer).

---

## 8. Test gap matrix

| Invariant / risk | Coverage | Status | Gap |
|---|---|---:|---|
| Mechanism cap holds under 3+ simultaneously over-cap families | `test_sleeve_cap_holds_on_emitted_book` (2 families), `test_mixed_mechanism_universe.py` (3 families, near-balanced fixture) | **Gap** | No test constructs an adversarial skew with 3+ families where 2+ are simultaneously over cap — exactly the regime Finding P0-1 shows the 5-iteration budget cannot handle. Minimal new test: 3-4 families, hand-picked raw shares that put 2+ over a shared cap by construction, assert final `mechanism_breakdown` satisfies every cap within a small epsilon. |
| Mechanism-cap loop convergence bound | None | **Missing** | No unit test on `cap_family_vectors`/`_apply_mechanism_cap` in isolation asserts convergence within the shipped iteration budget for N≥3 families; today's coverage is only indirect (via fixtures that happen not to trigger it). |
| Cross-platform solver-path parity | `test_sized_intent_solver_replay.py` (same-host only, skipped without cvxpy) | Partial | No CI (or any multi-host harness) actually runs this on >1 OS/BLAS combination; the test's own docstring says production use is gated on this. |
| ECOS-mode structural safety guard | None | **Missing** | Nothing prevents `composition_optimizer_mode: ecos` from being set without the referenced cross-platform validation having occurred; recommend a code-level guard (Finding P1-2). |
| `decision_basis_hash` bus-level replay stability | Direct-call property tests (`test_composition_p0_fixes.py`); this audit's own bus-level re-verification | Covered (via this audit + existing unit tests) | The golden Level-3/4 parity baselines still exclude the field by design; consider a dedicated bus-level golden hash that *does* include it, separate from the legacy baselines. |
| Turnover-penalty reference position scoped per-alpha (not account-level) | None | **Missing** | No test exercises two PORTFOLIO alphas trading the same symbol simultaneously through one `CompositionEngine`/shared `position_lookup`; recommend a test once/if a second PORTFOLIO alpha is promoted past `RESEARCH`, or a design decision to scope `position_lookup` per-alpha. |
| Factor-loadings freshness wall-clock fallback | None | **Missing** | No test exercises `factor_loadings_dir` set + `session_open_ns=None` to confirm (or characterize) the wall-clock fallback path; recommend either removing the fallback (Finding P1-3) or adding a test that pins it. |
| Small-universe per-name-cap collapse | None (not asserted either way) | **Missing** (documentation/awareness gap, not a correctness gap) | No test documents or asserts the expected degenerate-to-equal-weight behavior for small universes under default caps; recommend a regression test asserting the *documented* behavior so a future change to the default caps is a deliberate, visible decision. |
| Skill-doc accuracy (G16 rule 8 direction; "caps not wired" claim) | N/A (doc, not code) | **Stale** | `.cursor/skills/composition-layer/SKILL.md` should be corrected on both points (Finding "Documentation drift" in Section 1) so future audits do not need to re-derive the actual validator semantics from source. |
| Everything verified fixed in Section 0 | See Section 0 row-by-row | Covered | No new gaps found; re-verified with fresh line citations in this pass. |

---

## 9. Prioritized backlog

### P0

| Item | Component | Evidence | Effort | One-sentence fix | Expected impact |
|---|---|---|---:|---|---|
| Mechanism-cap scaling loop fails to converge for 3+ simultaneously over-cap families | `cross_sectional.py:658-690` (`_apply_mechanism_cap`), `cross_sectional.py:765-786` (`cap_family_vectors`), reused at `engine.py:462` | Empirically confirmed: G16-valid 3-4-family configs need 50-120 iterations, budget is 5; concrete ~9% relative cap overshoot reproduced (Section 5.4) | S/M | Raise the iteration budget (cheap — 500 iterations still runs in milliseconds) and add a post-loop epsilon check that logs/raises if any cap is still breached. | Makes G16 rule 8's "enforced at emit" promise actually hold for any 3+-family PORTFOLIO alpha; currently dormant, so no urgency to re-baseline existing parity hashes, but should land before any such alpha ships. |

### P1

| Item | Component | Evidence | Effort | One-sentence fix | Expected impact |
|---|---|---|---:|---|---|
| No structural guard on the ECOS/cvxpy solver path's unverified cross-platform determinism | `turnover_optimizer.py`, `bootstrap.py:2013-2022`, `tests/determinism/test_sized_intent_solver_replay.py:129-136` | No `.github/`or any CI config exists in this repo; the "must not enable in production until tested" claim is comment-only | S (guard) / L (actual CI) | Add a code-level guard (env/config allowlist) that raises unless the current platform triple is marked validated, converting the comment into an enforced precondition. | Closes the only remaining path to a platform-wide Inv-5 violation if an operator ever flips `composition_optimizer_mode: ecos`. |
| Turnover-penalty reference position is account-level, not per-PORTFOLIO-alpha | `bootstrap.py:510, 2031-2036` | Both shipped research alphas already declare an identical 3-symbol universe | M | Scope `_position_lookup` per-`strategy_id` (e.g. via a per-alpha slice of `StrategyPositionStore`, which already exists) rather than reading the single global `MemoryPositionStore`. | Prevents one PORTFOLIO alpha's turnover economics from being silently distorted by another alpha's fills in the same symbol once more than one PORTFOLIO alpha is ever promoted concurrently. |
| Wall-clock fallback in factor-loadings freshness gate | `bootstrap.py:2295-2304` | Self-documented as breaking Inv-5; triple-gated but still reachable | S | Raise `StaleFactorLoadingsError` instead of falling back to `time.time()` when `session_open_ns` is unset and `factor_loadings_dir` is configured. | Removes a self-acknowledged, still-open non-determinism in the bootstrap composition gate. |
| Composition-layer skill doc is stale on two points | `.cursor/skills/composition-layer/SKILL.md` | G16 rule 8 direction is backwards ("sum ≤ 1.0" vs. actual `>= 1.0 - 1e-9`); "caps not wired at runtime" is fixed but still claimed | S | Correct both statements in the skill file with a reference to `layer_validator.py:1098-1103` and `portfolio_layer_module.py:296-329`. | Prevents future audits/alpha authors from relying on two now-incorrect claims about the platform's own safety gate. |

### P2

| Item | Component | Evidence | Effort | One-sentence fix | Expected impact |
|---|---|---|---:|---|---|
| Default per-name/gross caps collapse small-universe books to equal-notional, discarding ranking signal | `turnover_optimizer.py:145-173` (defaults), this audit's trace (Section 1) | Concretely reproduced: weights 0.371/-1.367/0.997 → identical ±$7,500 | S (test) / M (operator-facing config) | Add a regression test documenting the expected small-N degenerate behavior, and consider exposing `gross_cap_pct`/`per_name_cap_pct` as an operator-tunable `platform.yaml` knob (already flagged as the natural extension in the code's own docstring). | Turns a currently-implicit, easy-to-miss behavior into an explicit, tested, and (optionally) operator-controllable one. |
| Real risk model in the optimizer (carried from 2026-06-20, unchanged) | `turnover_optimizer.py:314` (identity `sigma_diag`) | Static unit-diagonal ridge, not a true covariance model | L | Feed a deterministic static covariance or diagonal-vol artifact with its own provenance digest. | Makes `lambda_risk` economically meaningful in the ECOS path. |
| Sector-map provenance metadata (carried from 2026-06-20, unchanged) | `sector_matcher.py`, `scripts/build_reference_factor_loadings.py` | Sector map has no `_meta`/as-of anchor | S | Add a `_meta` block to the sector-map fixture, mirroring the loadings fixture. | Improves auditability of sector-neutral decisions; low urgency since `sector_map_path` is unset by default. |
| Property-based cap tests (carried from 2026-06-20, sharpened by this audit's finding) | `tests/composition/` | Current cap tests are fixture-specific and none exercise 3+-family simultaneous breach | M | Generate randomized deterministic mechanism sleeves (3-5 families, varied caps) and assert final `mechanism_breakdown` never exceeds any cap beyond epsilon, specifically targeting the regime Finding P0-1 identifies. | Converts this audit's ad hoc counter-examples into a permanent regression guard. |
| Portfolio-alpha purity guard for inline `construct:` blocks (carried from 2026-06-20, unchanged) | `alpha/loader.py` | Inline YAML `construct` code is executed without the AST restrictions applied to SIGNAL `evaluate` blocks | L | Apply the same purity/AST allowlist used for SIGNAL alphas if custom PORTFOLIO `construct:` blocks become production-used. | Reduces custom-constructor nondeterminism/side-effect risk; low urgency since no shipped alpha uses an inline `construct:` block today. |

---

## 10. Appendix: open questions needing data runs

1. Once a second PORTFOLIO alpha is authored with 3+ `trend_mechanism.consumes`
   families, does *any* realistic (not hand-constructed) signal distribution actually
   land in the simultaneous-multi-family-over-cap regime Finding P0-1 describes, or is
   it a purely adversarial/edge-case concern in practice? This audit demonstrated the
   regime is reachable and G16-valid, but did not have a real 3+-family alpha's
   historical signal distribution to test against.
2. Is the small-universe per-name-cap collapse (Section 1, P2) actually the intended
   behavior for N=3 research alphas, or should `gross_cap_pct`/`per_name_cap_pct`
   scale with universe size by design? The code frames this as an open extension
   point, not a decided answer.
3. If/when a second PORTFOLIO alpha is promoted toward PAPER/LIVE, should the
   turnover-penalty reference position (the cross-strategy position-store finding in
   Section 9's P1 backlog) be scoped per-alpha, per-symbol-across-strategies, or is
   account-level turnover actually the economically correct thing to optimize against
   (since real trades execute against the real, shared book)? This audit flags the
   ambiguity but the "correct" answer depends on execution/allocation policy outside
   this layer's scope.
4. Should the ECOS solver path be pursued for production at all, or does the
   platform's small-capital, small-universe reference deployment make the closed-form
   rescale the permanent production path (in which case, the L-effort cross-platform
   CI work in the P1 backlog could be de-prioritized entirely rather than merely
   guarded)?
5. Does the platform intend `factor_loadings_dir`/`sector_map_path` to ever be
   configured in a real deployment, or are `FactorNeutralizer`/`SectorMatcher`
   permanently no-ops at the platform's current scale? Several findings in Section 6
   (freshness wall-clock fallback, sector-map provenance) are only reachable once an
   operator configures these — worth knowing whether that is a near-term or
   hypothetical scenario.
