# Composition Layer (PORTFOLIO / Layer-3) Audit — 2026-06-17

Read-only, evidence-based audit of the feelies PORTFOLIO composition layer.
Scope: `src/feelies/composition/*`, the PORTFOLIO wiring in `src/feelies/bootstrap.py`,
the L3 event contracts in `src/feelies/core/events.py`, the three `layer: PORTFOLIO`
alpha YAMLs, and the L3/L4 determinism tests. No production code was modified.

Classification legend: **[BUG]** implementation defect, **[MODEL]** modeling choice
worth revisiting, **[LIB]** library/environment nondeterminism, **[CONTRACT]**
documented contract not matched by code.

> **Resolution update (2026-06-17, post-audit):** All six **P0** findings,
> **P1-1, P1-3, P1-4, P1-5, P1-6 (decay), P1-7, P1-8**, and the **P2** cohort
> (**P2-1, P2-2, P2-3, P2-4, P2-5, P2-6**) have been addressed in-tree — behavioral
> P2s as fixes, modeling/layer P2s as documented decisions.
> **P1-2** (closed-form turnover penalty) and the **per-alpha-capital** remainder of
> **P1-6** are intentionally deferred — they are modeling/calibration changes that
> also require re-baselining locked determinism hashes, so they need an explicit
> convention decision before implementation. See **Section 11 — Resolution log** for
> the per-finding fix, the files touched, and the verifying tests. Findings below are
> preserved as the point-in-time audit; resolved items are tagged inline as
> **`[RESOLVED]`**.

---

## 1. Executive summary

Top determinism / safety risks:

1. **[BUG/LIB] Optimizer path selection ignores `require_solver`** — `TurnoverOptimizer.optimize`
   branches on `_HAS_CVXPY` alone (`turnover_optimizer.py:139-149`). Whether the cvxpy/ECOS
   path or the closed-form path runs depends purely on *whether the `[portfolio]` extra is
   installed*, so two environments replaying the same event log can emit different intents.
   This silently violates Inv-5 (deterministic replay) and Inv-9 (backtest/live parity). **P0.**
2. **[LIB] ECOS is invoked with no pinned tolerances/iteration cap** — `problem.solve(solver=cp.ECOS,
   verbose=False)` (`turnover_optimizer.py:236`). `abstol/reltol/feastol/max_iters` are left at
   library defaults, so the solution can drift across ECOS/BLAS builds. **P0.**
3. **[BUG] The locked Level-3 baseline is produced by the *fallback*, not the optimizer it
   documents.** Empirically, ECOS *fails on every boundary* of the Level-3 fixture and falls
   back to closed-form (evidence below), so the golden hash `eca21cb1...` is a closed-form
   artifact even though `test_sized_intent_replay.py:14-16` claims "closed-form ... no CVXPY
   needed in CI by design" while the code would have used cvxpy if it had solved. The cvxpy
   path's determinism is therefore **unverified**. **P0.**
4. **[BUG] When ECOS *does* solve, the objective is miscalibrated and returns empty books.**
   `sigma_diag = (0.01*capital)**2` (`turnover_optimizer.py:219`) dominates the alpha term, so a
   well-scaled solve returns `{}` (hold) — demonstrated below. The cvxpy optimizer is effectively
   broken when it succeeds. **P0 (modeling) / P1 (impact).**
5. **[BUG/CONTRACT] Mechanism caps declared in alpha YAML are never enforced at emit.** Bootstrap
   builds the ranker with the default `mechanism_max_share_of_gross=1.0` (cap disabled) and never
   threads the alpha-declared caps through (`bootstrap.py:1921-1923`); `pro_burst_revert_v1`
   declares `0.6/0.6/0.7` caps that have no runtime effect. This contradicts the glossary's
   "the ranker enforces realisation at emission time" (G16 rule 8) and the alpha's own
   falsification criterion. **P0.**
6. **[BUG/CONTRACT] `mechanism_breakdown` is computed *before* neutralization, sector matching,
   and optimization.** `run_default_pipeline` copies `rank_result.mechanism_breakdown`
   (`engine.py:318`) — the ranker's pre-construction shares — yet the glossary defines it as the
   realised gross-share "post-neutralization, post-optimization". The forensic crowding diagnostic
   consumes an inaccurate breakdown. **P0/P1.**
7. **[CONTRACT] `decision_basis_hash` does not exist.** The glossary, `alphas/SCHEMA.md`, the
   platform invariants, and this audit prompt all reference a `decision_basis_hash` on
   `SizedPositionIntent`, but no such field exists (`events.py:675-700`); the only grep hits are
   docs. Determinism is enforced solely by *test-side* full-stream hashing, not by any in-band
   provenance hash on the emitted event. **P0 (provenance gap).**
8. **[BUG] `SectorMatcher` does not neutralize sector net exposure.** Scaling every weight in a
   sector by `(gross-|net|)/gross` leaves `net' = scale*net != 0` (`sector_matcher.py:97-101`);
   it only shrinks gross. Sector "neutralization" is cosmetic. **P1.**
9. **[BUG] No `Alert` on solver failure / non-OPTIMAL / empty allocation.** Failures are logged at
   WARNING and silently degraded (`turnover_optimizer.py:237-253`), so an operator gets no
   signal that the configured optimizer is degraded on every barrier. **P1.**
10. **[MODEL] Closed-form path ignores `lambda_tc` and `lambda_risk` entirely** — the turnover
    penalty that is the optimizer's stated purpose has zero effect in the path that actually runs
    (`turnover_optimizer.py:153-196`). **P1.**
11. **[BUG] Stale-loadings guard uses filesystem mtime and a wall-clock fallback** — `time.time()`
    when `session_open_ns is None` (`bootstrap.py:2157-2161`); the loadings file carries no
    embedded as-of date, so causality/freshness of loadings is judged by FS metadata, not content. **P1.**
12. **[BUG] Per-alpha config is silently dropped.** `pro_burst_revert_v1` declares
    `composition_completeness_threshold: 0.7` in `parameters:`, but the engine only consults the
    global `PlatformConfig` value (`engine.py:158`, `bootstrap.py:1939`). Decay is a global
    `any(...)` flag shared across all PORTFOLIO alphas (`bootstrap.py:1918-1920`). **P1.**
13. **[BUG] Causality-guard asymmetry in the synchronizer.** The multi-feeder path explicitly
    filters `ts <= boundary_ts_ns` (`synchronizer.py:254`); the legacy single-signal path has no
    explicit future-ts guard and relies on bus ordering (`synchronizer.py:324-332`). **P1/P2.**

Top opportunities:

- Force a single deterministic optimizer path (closed-form by default; gate cvxpy behind an
  explicit, pinned, parity-tested flag) and pin ECOS tolerances + iteration cap.
- Thread alpha-declared mechanism caps and completeness thresholds through bootstrap; compute
  `mechanism_breakdown` on the final emitted weights.
- Add an in-band `decision_basis_hash` to `SizedPositionIntent` (or formally retire the term
  from the glossary/SCHEMA so the contract matches reality).
- Fix or remove `SectorMatcher` net-exposure neutralization.

---

## 2. PORTFOLIO alpha inventory

All three loadable `layer: PORTFOLIO` specs are **research-only** (BT-13 decommissioned
composition at sub-$250k scale; `lifecycle_state: RESEARCH`). They exist for integration
tests and future scale-up.

| alpha_id | universe | depends_on_signals | declared mech caps | factor_neutralization | completeness thr | decay default |
|---|---|---|---|---|---|---|
| `pro_kyle_benign_v1` | AAPL, MSFT, NVDA | `sig_benign_midcap_v1`, `sig_kyle_drift_v1` | KYLE_INFO 1.0; global 1.0 | `false` | global (0.80) | `false` |
| `pro_burst_revert_v1` | AAPL, MSFT, NVDA | `sig_hawkes_burst_v1`, `sig_inventory_revert_v1` | HAWKES_SELF_EXCITE 0.6, INVENTORY 0.6; global 0.7 | `false` | param `0.7` (declared, **ignored** at runtime) | `false` |
| `_template/template_portfolio` | template | template | template | template | template | template |

Decision horizon for both real alphas is `300 s`. Both opt OUT of factor neutralization
(`factor_neutralization: false`) and the reference `platform.yaml` configures no
`factor_loadings_dir` / `sector_map_path`, so in the shipped configuration the
`FactorNeutralizer` and `SectorMatcher` are **both no-ops** and only the ranker + optimizer
shape the book.

Key inventory observations:

- Only `pro_burst_revert_v1` exercises a **non-trivial** mechanism cap (0.6/0.6/0.7). Because
  the runtime cap is disabled (Finding P0-4), this alpha's caps and its second falsification
  criterion ("Either mechanism's share of gross exposure exceeds its declared cap for >= 3
  consecutive composition barriers") are unenforceable by construction.
- `composition_completeness_threshold` appears as a per-alpha `parameters:` entry in
  `pro_burst_revert_v1.alpha.yaml:94-101` but is read only from `PlatformConfig`
  (`bootstrap.py:1939`), never from the alpha params — a silent no-op (Finding P1-5).

---

## 3. Synchronizer / barrier audit (`synchronizer.py`)

### 3.1 Emission order — OK

Each `(horizon_seconds, boundary_index)` emits exactly one context, idempotent via
`_emitted` (`synchronizer.py:230-234`). Universe is lex-sorted once at construction
(`synchronizer.py:136`); per-symbol iteration uses that sorted tuple
(`synchronizer.py:274, 308`). The downstream `CompositionEngine` iterates alphas sorted by
`(horizon_seconds, alpha_id)` (`engine.py:118`). Emission order is deterministic and stable
under symbol-set permutation. The prompt's stated key `(boundary_ts_ns, alpha_id,
horizon_seconds)` is realised as the per-handler `(horizon, boundary)` keying plus the
engine's alpha sort — equivalent in effect.

### 3.2 Completeness computation — partial

`completeness = non_none / len(universe)` (`synchronizer.py:336`). The numerator counts
symbols with *any* selected signal. Two caveats:

- **[MODEL] "non-stale" is not literally enforced.** The module docstring and the event field
  comment say completeness is the fraction with a *non-stale* signal, but the multi-feeder
  branch increments `non_none` whenever `any(v is not None for v in row.values())`
  (`synchronizer.py:320-321`), i.e. any feeder produced a causal signal. Snapshot-staleness
  alignment is applied for same-horizon feeders (`synchronizer.py:258-262`) but a cross-horizon
  feeder signal counts toward completeness without a staleness check. Net effect: completeness
  can be *over*-counted relative to the documented "non-stale" definition.
- The legacy path applies a contemporaneity filter (`s.timestamp_ns < snap.timestamp_ns ->
  skip`, `synchronizer.py:328`) so a symbol whose latest signal predates its snapshot is mapped
  to `None` and excluded from the numerator — consistent with "hold".

### 3.3 Barrier / threshold fail-safe — OK (fail-safe), with a wiring gap

The synchronizer **always emits** the context (no silent drop). The engine compares
`ctx.completeness < self._completeness_threshold` and emits a *degenerate empty* intent
("hold positions"), not an inflated one (`engine.py:158-167, 229-257`). This is correctly
fail-safe (Inv-11). No path proceeds on partial universe and inflates weights: the standardizer
computes moments over `active` symbols only and zero-fills the rest (`cross_sectional.py:309-352`),
and the optimizer L1-normalizes to a fixed gross cap, so missing symbols cannot inflate gross.
Gap: the threshold is global only (Finding P1-5).

### 3.4 Causality — mostly OK, with an asymmetry

The multi-feeder selector filters `candidates = [... if s.timestamp_ns <= boundary_ts_ns]`
(`synchronizer.py:254`) — explicitly causal (Inv-6). The legacy single-signal path
(`synchronizer.py:324-332`) has **no explicit future-timestamp guard**; it relies on the bus
delivering events in timestamp order so that a `ts > boundary` signal is never in `_signal_cache`
at tick time. Under deterministic in-order replay this holds, but the guard should be symmetric
so an out-of-order injection cannot leak a future signal. **[BUG] P1/P2.**

---

## 4. Ranker & decay audit (`cross_sectional.py`)

### 4.1 Ranking / standardization math — sound and numerically stable

- Raw score: `raw = sign(direction) * strength * edge_estimate_bps` (`cross_sectional.py:192,
  252`). `sign` is +1 LONG / -1 SHORT / 0 otherwise (`cross_sectional.py:301-307`).
- Standardization: sample mean, population std over the `active` subset only, then z and clip to
  +/-`clip` (default 4.0) (`cross_sectional.py:309-352`). Zero-variance universe and single-symbol
  cases return all-zeros (`std == 0.0 -> out` of zeros), which is the correct degenerate "no
  cross-sectional view" behavior. Computing moments over `active` only (not zero-imputed) is the
  right call and is documented (`cross_sectional.py:316-327`). All math is Python `float`, fixed
  iteration order; no NumPy reductions whose pairwise-sum order could differ across builds.
- Multi-feeder aggregation sums per-feeder contributions in `feeder_strategy_ids` order
  (`cross_sectional.py:239-266`) — deterministic given the sorted feeder tuple from bootstrap.

### 4.2 Decay weighting — correct, clamp present, but a units subtlety

- `decay = max(decay_floor, exp(-age_s / hl))` with `age_s = max(0, ctx.ts - sig.ts)/1e9`,
  `hl = expected_half_life_seconds` (`cross_sectional.py:194-199, 254-259`). The `decay_floor`
  clamp (default 1e-6, validated to (0,1) `cross_sectional.py:136-137`) is present and guards
  against `hl -> 0` blow-ups; `expected_half_life_seconds == 0` is treated as "unspecified" and
  skips decay (raw retained), matching the glossary default.
- **[MODEL]** The skill text frames decay as `exp(-age_s / horizon_seconds)`, but the code uses
  the *signal's per-mechanism half-life* (`expected_half_life_seconds`), which is the more
  defensible quantity and matches the glossary "decay weighting" entry. Note this differs from
  the alpha YAML parameter doc strings (e.g. `pro_kyle_benign_v1.alpha.yaml:101-103` says
  `exp(-age_seconds / horizon_seconds)`) — a **doc drift** worth fixing in the YAMLs.
- Decay-ON vs decay-OFF produces a different intent stream and the cross-check guard
  (`test_sized_intent_with_decay_replay.py:57+ test_decay_changes_hash_vs_baseline`) asserts the
  hashes do not collide. Verified passing. However the difference is exercised only through the
  **closed-form fallback** (see Section 5), so decay's interaction with cvxpy is untested.

### 4.3 Mechanism breakdown & cap — two defects

- **[BUG/CONTRACT] P0-4 (cap not enforced).** `_apply_mechanism_cap` is correct in isolation:
  it iterates (max 5 passes) scaling each over-cap family to exactly `cap_share` before
  re-normalizing, and the unit test `test_cross_sectional.py:136` constructs a ranker with
  `mechanism_max_share_of_gross=0.5` to exercise it. But **bootstrap never passes a cap**
  (`bootstrap.py:1921-1923` -> default `1.0` -> `_mech_cap >= 1.0` short-circuit
  `cross_sectional.py:372-377`). The alpha-declared caps live on
  `LoadedPortfolioLayerModule.max_share_of_gross` / `consumes_mechanisms`
  (`portfolio_layer_module.py:128-130`) and are simply discarded for runtime use. End-to-end
  wiring (alpha YAML cap -> ranker) is therefore **untested and inactive**.
- **[BUG/CONTRACT] P0-6 (breakdown computed pre-construction).** Even when the cap is active, the
  breakdown is computed in the ranker on *standardized* weights, before `FactorNeutralizer`,
  `SectorMatcher`, and `TurnoverOptimizer` reshape the book. `run_default_pipeline` then reports
  `mechanism_breakdown=dict(rank_result.mechanism_breakdown)` (`engine.py:318`). The glossary
  defines the breakdown as the realised gross-share "after weight construction (post-neutralization,
  post-optimization)". Consequences: (a) the cap, if it were enabled, would be applied to a vector
  that the optimizer subsequently discards/rescales, so the cap would not bound the *emitted*
  gross either; (b) `CrossSectionalTracker` and the forensic crowding diagnostic
  (`cross_sectional_tracker.py:1-25`) record a breakdown that does not match the actual
  `target_positions`.

---

## 5. Optimizer determinism audit (`turnover_optimizer.py`) — deep dive

This is the highest-risk component. Four compounding defects break, or could break, Inv-5 and
Inv-9.

### 5.1 [BUG/LIB] Path selection ignores `require_solver` (P0)

```139:149:src/feelies/composition/turnover_optimizer.py
        if _HAS_CVXPY:
            return self._optimize_cvxpy(
                weights,
                universe,
                current_positions_usd or {},
            )
        return self._optimize_closed_form(
            weights,
            universe,
            current_positions_usd or {},
        )
```

`require_solver` only gates a *constructor* error (`turnover_optimizer.py:115-119`); it does NOT
force the closed-form path. So the path is chosen by whether `cvxpy` imports at module load
(`turnover_optimizer.py:36-44`). The same code + same event log emits **different intents** on a
machine with the `[portfolio]` extra vs without — a direct Inv-5 / Inv-9 violation. There is no
config flag to pin the path.

### 5.2 [LIB] ECOS invoked with default tolerances (P0)

```234:236:src/feelies/composition/turnover_optimizer.py
        problem = cp.Problem(objective, constraints)
        try:
            problem.solve(solver=cp.ECOS, verbose=False)
```

No `abstol`, `reltol`, `feastol`, `max_iters` are pinned. ECOS' interior-point solution can drift
in low-order digits across ECOS / OpenBLAS versions and CPU architectures. The cents-rounding at
`turnover_optimizer.py:257` absorbs some drift but cannot guarantee bit-identical output near a
half-cent boundary; and rounding does nothing about the empty-vs-populated divergence below.

### 5.3 [BUG] The locked baseline is a fallback artifact; cvxpy determinism is unverified (P0)

Empirical evidence (read-only, this environment, `cvxpy/numpy/ecos` all installed):

- Recomputing the Level-3 fixture, ECOS **fails on every boundary**:
  `TurnoverOptimizer: ECOS solve failed (Solver 'ECOS' failed...); falling back to closed-form`
  (printed 4x for the 4-boundary fixture). The cvxpy and forced-closed-form replays produce the
  **same** hash `eca21cb1...` — but only because both ran closed-form.
- So the docstring claim that the baseline uses closed-form "by design"
  (`test_sized_intent_replay.py:14-16`) is accidentally true via *solver failure*, not via the
  `require_solver`/path logic. The cvxpy path is never successfully exercised in the L3/L4
  determinism baselines.

Falsifiable risk: an ECOS build on which the Level-3 problem *does* solve would produce a
different allocation than closed-form, flipping the locked hash and breaking the test
cross-environment. The parity is currently load-bearing on "ECOS happens to fail here."

### 5.4 [BUG/MODEL] When ECOS succeeds, the objective is miscalibrated -> empty book (P0/P1)

```219:233:src/feelies/composition/turnover_optimizer.py
        sigma_diag = (0.01 * self._capital) ** 2 * _np.ones(n)

        x = cp.Variable(n)
        per_name_cap = self._per_name_cap * self._capital
        gross_cap = self._gross_cap * self._capital

        objective = cp.Minimize(
            -mu @ x
            + self._lambda_risk * cp.sum(cp.multiply(sigma_diag, cp.square(x)))
            + self._lambda_tc * cp.norm(x - p_cur, 1)
        )
```

`mu` are standardized z-scores (O(1)); `x` is in dollars. The risk term scales as
`lambda_risk * (0.01*capital)^2 * x^2`. With `capital=100k`, `lambda_risk=0.1`, that is
`1e5 * x^2`, swamping the linear `-mu @ x` (and the `lambda_tc * |x|` turnover term) for any
non-tiny `x`. The unconstrained optimum is `x ~ mu / (2*1e5)`, i.e. sub-cent, which rounds to
zero. Demonstrated: a well-scaled 3-name solve returns `solver status: optimal` with
`target = {}` while the closed-form returns `{AAPL: 5000, MSFT: -5000, NVDA: 5000}`. The cvxpy
optimizer, when it solves, is effectively a no-op (always "hold"). The units of the alpha term
(z-score x USD) and the risk term (USD^2) are not commensurable — this is a modeling bug, not
just a tolerance issue.

### 5.5 [MODEL] Closed-form path ignores both penalties (P1)

`_optimize_closed_form` (`turnover_optimizer.py:153-196`) L1-normalizes to `gross_cap`, clips per
name, rounds to cents, then re-shrinks if over gross. It never reads `lambda_tc` or `lambda_risk`
and uses `current_positions_usd` *only* to report turnover (`turnover_optimizer.py:187-189`), not
to bias the allocation. So in the path that actually runs, the turnover penalty — the optimizer's
entire stated purpose ("penalizes turnover against the previous boundary's intent") — has zero
effect on the chosen positions.

Additional closed-form nit: `scale = min(capital*gross_cap/gross, capital)`
(`turnover_optimizer.py:166`) clamps the intermediate scale at `1*capital` regardless of
`gross_cap_pct` (e.g. 2.0); step-4 re-shrink (`turnover_optimizer.py:182-185`) makes the final
gross correct, so this is benign but confusing. **[MODEL] P2.**

### 5.6 [BUG] Silent degradation — no Alert (P1)

```237:253:src/feelies/composition/turnover_optimizer.py
        except (cp.SolverError, ValueError) as exc:  # pragma: no cover
            _logger.warning(
                "TurnoverOptimizer: ECOS solve failed (%s); falling back to closed-form",
                exc,
            )
            return self._optimize_closed_form(...)
        if x.value is None or problem.status not in ("optimal", "optimal_inaccurate"):
            _logger.warning(
                "TurnoverOptimizer: solver status=%s; returning empty allocation",
                problem.status,
            )
            return OptimizerResult({}, 0.0, 0.0, problem.status or "UNKNOWN")
```

A solver failure on *every* barrier (as observed) produces only DEBUG/WARNING logs and no `Alert`
event. Per Inv-11 the fail-safe direction (fall back / empty) is correct, but the platform should
*surface* persistent solver failure as an `Alert` so an operator knows the configured optimizer is
inert. A non-OPTIMAL status returning empty is also fail-safe but equally invisible.

### 5.7 Tie-breaking / variable ordering — OK

Decision variables map to `universe` index order (`turnover_optimizer.py:206-212, 256`), which is
lex-sorted upstream; float->quantity rounding is `round(_, 2)` cents at a single site
(`turnover_optimizer.py:178, 257`). Given a *fixed* solver path and pinned tolerances these are
deterministic; the nondeterminism is entirely in path selection (5.1) and solver tolerance (5.2).

---

## 6. Neutralization / sector audit

### 6.1 FactorNeutralizer (`factor_neutralizer.py`) — math OK; ingestion/causality weak

- **Math: OK.** The neutralizer computes the OLS residual `residual = w - B @ (B^T B)^-1 B^T w`
  via normal equations with an `lstsq` fallback on `LinAlgError`
  (`factor_neutralizer.py:144-152`). This is the minimum-distance factor-neutral projection;
  `B^T residual ~ 0` is reported as `factor_exposures`. NumPy float64, lex-sorted iteration
  (`factor_neutralizer.py:161-167`). Singular `B^T B` falls back to `lstsq(rcond=None)` — robust.
- **[MODEL] Degenerate-matrix exposure leakage.** When `B^T B` is singular the `lstsq` solution
  is min-norm, which does *not* guarantee `B^T residual == 0`; residual factor exposure can be
  non-zero. The class docstring claims it "falls back to projecting onto the largest non-zero
  singular vectors", but the code uses plain `lstsq`, not a truncated-SVD projection — a
  doc/impl mismatch. Low impact in the shipped config (neutralization is off).
- **[BUG] Causality / freshness by filesystem mtime (P1).** `_load_loadings` reads
  `loadings.json` (`{symbol:{factor:float}}`) with no embedded as-of timestamp
  (`factor_neutralizer.py:188-213`). The freshness guard lives in bootstrap and uses
  `path.stat().st_mtime` vs `session_open_ns` (or `time.time()` when no session anchor)
  (`bootstrap.py:2157-2161`). Two issues: (i) the same loadings *content* can pass or fail
  depending on FS mtime (re-clone, copy, checkout) -> non-reproducible bootstrap verdict;
  (ii) the `time.time()` fallback is a wall-clock read in the boot path (the code comment itself
  acknowledges this "breaks bit-identical replay"). The loadings should carry an explicit
  `as_of_ns` validated against the session clock (Inv-10).
- Construction raises `MissingFactorLoadingsError` only when the *file* is missing/unreadable;
  symbols/factors absent from the file are zero-filled (`factor_neutralizer.py:165-166`), which
  the bootstrap freshness check compensates for by requiring every universe symbol to be present
  (`bootstrap.py:2132-2168`). That cross-check is good.

### 6.2 SectorMatcher (`sector_matcher.py`) — [BUG] does not neutralize (P1)

```96:101:src/feelies/composition/sector_matcher.py
            scale = (gross - abs(net)) / gross
            if scale < 0.0:
                scale = 0.0
            for s in symbols:
                out[s] = out.get(s, 0.0) * scale
```

Scaling *every* symbol in a sector by the same factor `scale` yields
`net' = scale * net != 0` whenever `net != 0` and `scale != 0`. The docstring claims the long/short
weights are "scaled down so within-sector net exposure is zero" — but it is not: the
within-sector net/gross *ratio* is invariant under a uniform scale. The operation only shrinks
gross (and thus the directional component in absolute terms), it does not pair longs against
shorts or drive net to zero. To actually neutralize, the dominant side must be scaled relative to
the offsetting side (e.g. scale the larger leg so leg sums match), not all names uniformly. No
mechanism caps or neutralization are *broken* by this (it is gentle and order-stable), but it does
not deliver the advertised sector neutrality. In the shipped config it is a no-op (no
`sector_map_path`), so this is latent.

---

## 7. decision_basis_hash & provenance audit

### 7.1 [CONTRACT] `decision_basis_hash` is unimplemented (P0)

The platform glossary (`.cursor/rules/platform-invariants.mdc`), `alphas/SCHEMA.md`, and this
audit prompt all describe a `decision_basis_hash` carried on `SizedPositionIntent` that "must be
bit-identical across replays". A repo-wide grep finds the term **only** in those doc files — never
in `src/`. The actual `SizedPositionIntent` (`events.py:675-700`) carries `strategy_id`, `layer`,
`horizon_seconds`, `target_positions`, `factor_exposures`, `expected_turnover_usd`,
`expected_gross_exposure_usd`, `mechanism_breakdown`, `disclosed_cost_total_bps_by_symbol` — and
**no** `decision_basis_hash`.

Implication: there is no in-band, per-intent provenance digest. Determinism is asserted purely by
*test-side* serialization-and-hash of the full intent stream
(`test_sized_intent_replay.py:180-201`). That is a valid replay check, but it means:
(a) at runtime/forensics there is no way to detect that two "identical" decisions used different
inputs; (b) the documented contract over-promises. Either add the field (hashing the canonical
input set) or strike it from the glossary/SCHEMA so the contract matches code.

### 7.2 What the test hash covers vs what affects target_positions

`_hash_intent_stream` covers `sequence, timestamp_ns, strategy_id, layer, horizon_seconds,
correlation_id, expected_gross_exposure_usd, expected_turnover_usd, target_positions (symbol,
target_usd, urgency), factor_exposures, mechanism_breakdown` (`test_sized_intent_replay.py:180-201`).
This is a good coverage of intent outputs. It does **not** independently cover the *inputs*
(signals, current positions, loadings) — those are fixed constants in the fixture. Notably the
hash would not catch the cvxpy-vs-closed-form divergence as a *defect* — it would simply lock
whichever path the CI environment happens to run (see 5.3).

### 7.3 Correlation IDs — unique and stable (OK)

- Context: `xsect:{h}:{bi}` (`synchronizer.py:341`).
- Intent: `intent:{alpha_id}:{horizon_seconds}:{boundary_index}` and degenerate intents append
  `:degenerate` (`engine.py:220, 240`). Unique per (alpha, horizon, boundary).
- Sequence numbers are drawn from dedicated generators (`_ctx_seq`, `_intent_seq`) that never
  share the main signal sequencer (`synchronizer.py:20-24`, `engine.py:219`), preserving the
  isolated-stream invariant.
- **[MODEL] minor:** non-degenerate and degenerate intents for the same boundary differ only by
  the `:degenerate` suffix; they cannot both occur for one (alpha, boundary), so no collision —
  but a consumer keying solely on the prefix should normalize the suffix.

---

## 8. Test gap matrix

Read-only runs performed for this audit (all green):

- `uv run pytest tests/composition/ tests/portfolio/ -q` -> 70 passed.
- `uv run pytest tests/determinism/test_sized_intent_replay.py
  tests/determinism/test_sized_intent_with_decay_replay.py
  tests/determinism/test_portfolio_order_replay.py tests/integration/test_xsect_v1_e2e.py -q`
  -> 16 passed (23 s).

| Invariant / behavior | Test(s) | Status |
|---|---|---|
| L3 intent stream byte-identical (decay OFF) | `test_sized_intent_replay.py` (golden + 2x replay) | **Covered** — but locks the *closed-form fallback only* (5.3) |
| L3 intent stream byte-identical (decay ON) | `test_sized_intent_with_decay_replay.py` | **Covered** (closed-form path); decay x cvxpy **missing** |
| decay-ON != decay-OFF | `test_decay_changes_hash_vs_baseline` | Covered |
| L4 per-leg OrderRequest byte-identical | `test_portfolio_order_replay.py` | Covered |
| Completeness fail-safe (degenerate intent) | `tests/composition/test_engine.py` | Covered (engine unit) |
| Mechanism cap math (ranker, cap < 1.0) | `test_cross_sectional.py:136`, `test_mixed_mechanism_universe.py:158` | **Partial** — cap injected manually; **no test that an alpha-YAML cap reaches the runtime ranker** (P0-4 is invisible to the suite) |
| mechanism_breakdown == realised post-optimization gross | (none) | **Missing** (P0-6) |
| Optimizer determinism under cvxpy success | (none) | **Missing** — ECOS never succeeds in fixtures (5.3) |
| Optimizer path stability (cvxpy present vs absent) | (none) | **Missing** (5.1) — golden hash silently env-dependent |
| Optimizer determinism under perturbed BLAS/OS | (none) | **Missing** (5.2) |
| Sector net-exposure neutrality | (none asserting net~0) | **Missing** (sector matcher bug, 6.2) |
| Factor-loadings freshness reproducibility | bootstrap unit (mtime-based) | **Partial** — tests mtime, not content as-of (P1) |
| Per-alpha completeness threshold honored | (none) | **Missing** (P1-5) — declared param silently ignored |
| Causality: no signal with ts > boundary | implicit (multi-feeder filter) | **Partial** — legacy path unguarded (3.4) |

### 8.1 Proposed minimal new tests (specs only)

1. **Optimizer path-parity guard.** Parametrize the Level-3 fixture over `_HAS_CVXPY` True/False
   (monkeypatch `turnover_optimizer._HAS_CVXPY`) and assert the intent-stream hash is identical, OR
   assert that a single pinned path is always chosen. Falsifies 5.1.
2. **ECOS success determinism.** Build a well-scaled problem on which ECOS solves to `optimal`,
   solve twice, assert bit-identical `target_usd`; and assert cvxpy result == closed-form result
   (this currently FAILS by 5.4 — the test would document/lock the intended equivalence and force
   the objective fix).
3. **Alpha-YAML mechanism cap -> emit.** Bootstrap a deployment with `pro_burst_revert_v1`, drive a
   barrier where one mechanism would exceed its declared 0.6 cap, assert
   `intent.mechanism_breakdown[family] <= 0.6 + eps`. Falsifies P0-4.
4. **Breakdown reflects emitted weights.** Property test: recompute gross-share per mechanism from
   `intent.target_positions` (mapping symbol->mechanism via consumed signals) and assert it equals
   `intent.mechanism_breakdown` within eps. Falsifies P0-6.
5. **Sector neutrality.** With a 2-symbol same-sector universe and a net-long input, assert
   post-matcher `sum(weights_in_sector) ~ 0`. Falsifies 6.2.
6. **Per-alpha completeness threshold.** Register an alpha with param threshold 0.95, feed
   completeness 0.9, assert a degenerate intent. Falsifies P1-5.

---

## 9. Prioritized backlog

Effort: S (<0.5d), M (~1-2d), L (>2d). Each item: component | `file:line` | one-line fix |
expected impact.

### P0 — determinism / safety (must fix before any live PORTFOLIO capital)

| # | Component | file:line | Fix | Impact | Effort |
|---|---|---|---|---|---|
| P0-1 | TurnoverOptimizer path selection | `turnover_optimizer.py:139-149` | Choose path on an explicit pinned flag (default closed-form); only use cvxpy when `require_solver=True`. | Removes env-dependent intent divergence; restores Inv-5/Inv-9. | S |
| P0-2 | ECOS tolerances | `turnover_optimizer.py:236` | Pin `abstol/reltol/feastol/max_iters` (and `verbose=False`); document the pinned values. | Bounds cross-build solution drift. | S |
| P0-3 | cvxpy determinism unverified | `turnover_optimizer.py:198-270` + tests | Add a fixture where ECOS solves and lock its hash; fix scaling so it does. | Closes the "ECOS-fails-so-parity-holds" trap. | M |
| P0-4 | Mechanism cap not wired | `bootstrap.py:1921-1923`; `portfolio_layer_module.py:128-130` | Thread per-alpha `max_share_of_gross` into a per-alpha ranker (or pass cap per `construct`). | Makes G16 rule 8 enforceable at emit. | M |
| P0-5 | mechanism_breakdown timing | `engine.py:318`; `cross_sectional.py:354-426` | Recompute breakdown from final `target_positions` after optimize. | Accurate crowding diagnostics; cap bounds the *emitted* book. | M |
| P0-6 | `decision_basis_hash` missing | `events.py:675-700` (+ glossary/SCHEMA) | Add the field hashing the canonical input set, or strike the term from docs. | Contract matches code; in-band provenance. | M |

### P1 — correctness / robustness

| # | Component | file:line | Fix | Impact | Effort |
|---|---|---|---|---|---|
| P1-1 | cvxpy objective units | `turnover_optimizer.py:219, 225-229` | Calibrate `sigma_diag` / penalties to weight-space, not USD^2; or optimize in weight units then scale. | cvxpy returns a real book instead of `{}`. | M |
| P1-2 | Closed-form ignores penalties | `turnover_optimizer.py:153-196` | Apply an L1 turnover penalty against `current_positions_usd`. | Turnover control actually functions. | M |
| P1-3 | SectorMatcher net != 0 | `sector_matcher.py:96-101` | Scale the dominant leg relative to the offsetting leg so sector net -> 0. | Delivers advertised sector neutrality. | M |
| P1-4 | Loadings freshness via mtime/wallclock | `bootstrap.py:2157-2161`; `factor_neutralizer.py:188-213` | Embed `as_of_ns` in `loadings.json`; validate against session clock; drop `time.time()`. | Reproducible bootstrap; Inv-10. | M |
| P1-5 | Per-alpha completeness ignored | `engine.py:158`; `bootstrap.py:1939` | Read threshold from alpha params with config fallback. | Alpha-declared safety honored. | S |
| P1-6 | Shared singletons / global decay | `bootstrap.py:1900-1941, 1918-1920` | Build per-alpha pipeline components (or pass per-alpha params into `construct`). | Per-alpha caps/decay/capital differentiation. | L |
| P1-7 | Legacy causality guard | `synchronizer.py:324-332` | Add `s.timestamp_ns <= tick.timestamp_ns` filter to match the multi-feeder path. | Symmetric Inv-6 defense. | S |
| P1-8 | No Alert on solver degradation | `turnover_optimizer.py:237-253` | Emit an `Alert` (rate-limited) on persistent solve failure / non-OPTIMAL. | Operator visibility. | S |

### P2 — modeling / quality

| # | Component | file:line | Fix | Effort |
|---|---|---|---|---|
| P2-1 | Identity risk model | `turnover_optimizer.py:215-219` | Wire an intraday diagonal vol estimate (or document the static choice). | M |
| P2-2 | Completeness "non-stale" semantics | `synchronizer.py:320-336` | Apply staleness check to cross-horizon feeders before counting. | S |
| P2-3 | Per-name / gross caps not from alpha | `turnover_optimizer.py:159-160`; alpha `risk_budget` | Source `per_name_cap`/`gross_cap` from the alpha's `risk_budget`. | M |
| P2-4 | Confusing closed-form scale clamp | `turnover_optimizer.py:166` | Drop the `min(..., capital)` clamp; rely on step-4 shrink. | S |
| P2-5 | Neutralizer degenerate-matrix doc/impl | `factor_neutralizer.py:30-34, 144-152` | Either implement truncated-SVD projection or fix the docstring. | S |
| P2-6 | Decay doc drift in alpha YAMLs | `pro_kyle_benign_v1.alpha.yaml:101-103` | Correct the `exp(-age/horizon)` text to `exp(-age/half_life)`. | S |

---

## 10. Appendix — open questions needing data runs

1. **ECOS-solves environments.** On which ECOS/BLAS builds does the Level-3 fixture *solve*
   (rather than fail)? Reproduce the L3 golden hash on a clean `[portfolio]` install across
   macOS arm64 / Linux x86_64 to measure actual cross-environment divergence.
2. **Realistic-scale optimizer behavior.** With `account_equity` and the live universe, does the
   cvxpy objective ever produce a non-empty book? (5.4 suggests it does not.) Needs a backtest
   run with `require_solver=True` and instrumented `OptimizerResult.solver_status`.
3. **Mechanism-cap binding frequency.** On `pro_burst_revert_v1` over a representative session,
   how often would the 0.6 caps bind if enforced? Quantifies the realized-risk gap from P0-4.
4. **Breakdown drift magnitude.** Measure the difference between the pre-construction breakdown
   reported today and the realised post-optimization breakdown (P0-6) over a session — is it
   material to the crowding diagnostic thresholds?
5. **Sector-matcher impact.** With a real `sector_map_path`, quantify residual within-sector net
   exposure under the current uniform-scale implementation (6.2).

---

## 11. Resolution log (2026-06-17, post-audit)

All six P0 findings plus most P1s were fixed in the same session that produced this
audit. The existing locked Level-3 closed-form baselines (`test_sized_intent_replay.py`,
`test_sized_intent_with_decay_replay.py`) and the Level-4 portfolio-order baseline were
**not** re-baselined — the fixes preserve them bit-for-bit (single-mechanism fixtures keep
`mechanism_breakdown == {KYLE_INFO: 1.0}` before and after, and the new optional fields are
not serialized into those hashes).

### P0 — resolved

- **P0-1 (optimizer path selection).** `TurnoverOptimizer.optimize` now branches on
  `self._require_solver`, not `_HAS_CVXPY` (`turnover_optimizer.py`). Default
  `require_solver=False` always runs the deterministic closed-form path regardless of whether
  the `[portfolio]` extra is installed, so the intent stream no longer depends on the
  environment. Docstring updated.
- **P0-2 (ECOS tolerances).** Added pinned module constants `_ECOS_ABSTOL/_RELTOL/_FEASTOL=1e-8`,
  `_ECOS_MAX_ITERS=100`, passed explicitly to `problem.solve(...)`.
- **P0-1/P1-1 (cvxpy objective units).** `_optimize_cvxpy` rewritten to optimize in **weight
  space** (`-mu·w + λ_risk·Σwᵢ² + λ_tc·‖w−w_cur‖₁`, unit ridge, caps as fractions) and scale by
  `capital` at the end. ECOS now solves to real books instead of the empty allocation the old
  USD-space `(0.01·capital)²` ridge forced.
- **P0-3 (cvxpy determinism unverified).** New `tests/determinism/test_sized_intent_solver_replay.py`
  drives the L3 fixture with `require_solver=True`, locks the ECOS-solved stream hash
  (`7a5d74e7e51e369809f73d3c2ef48c732344de4ac2aa3dc549f9f71d20714fa5`), asserts two-replay
  stability, and guards against regression to empty allocations. Skipped when cvxpy is absent.
- **P0-4 (mechanism caps not enforced at emit).** Per-family `max_share_of_gross` caps are now
  retained by the loader (new `parse_mechanism_caps` in `portfolio_layer_module.py`) and threaded
  through `LoadedPortfolioLayerModule` → `_DefaultPortfolioConstructor` → `run_default_pipeline` →
  `CrossSectionalRanker.rank(mechanism_caps=, global_mechanism_cap=)`. `_apply_mechanism_cap`
  enforces `min(per-family, global)` per family. Wired in `bootstrap.py`.
- **P0-5 (breakdown timing).** New `compute_mechanism_breakdown(...)` computes the breakdown from
  the final `target_positions` (post-neutralize/sector/optimize); `run_default_pipeline` reports
  that instead of the ranker's pre-construction shares.
- **P0-6 (`decision_basis_hash`).** Added `decision_basis_hash: str = ""` to `SizedPositionIntent`
  and a deterministic `_compute_decision_basis_hash(...)` (engine) over per-symbol
  raw-score/decay/mechanism, turnover-reference positions, resolved caps, and alpha/boundary
  identity.

### P1 — resolved

- **P1-3 (SectorMatcher net ≠ 0).** `SectorMatcher.neutralize` now scales **only the dominant
  side** of each sector so within-sector net → 0 while preserving within-side ranking
  (`sector_matcher.py`). No-op in the shipped config (no `sector_map_path`), so no locked hash
  changed; covered by a new unit test asserting `sum(weights_in_sector) ≈ 0`.
- **P1-4 (loadings freshness / wall-clock).** `loadings.json` may now carry an optional
  `"_meta": {"as_of_ns": ...}` block; when present the freshness check (`bootstrap.py`) uses that
  content-embedded timestamp (reproducible) instead of filesystem mtime. The build script can emit
  it via the new opt-in `--as-of-ns` flag (default off so the committed fixture stays
  byte-identical). The `time.time()` reference is now reached only when `session_open_ns` is
  unset, and that path emits a WARNING that it breaks replay. `FactorNeutralizer._load_loadings`
  and the freshness check both skip the `_meta` key.
- **P1-5 (per-alpha completeness threshold).** `CompositionEngine` reads
  `composition_completeness_threshold` from the registered alpha's params (falling back to the
  platform config) per alpha (`engine.py`, `bootstrap.py`).
- **P1-6 (decay leakage).** The per-alpha `decay_weighting_enabled` flag is threaded through the
  constructor → `run_default_pipeline` → `rank(decay_weighting_enabled=)`, so one alpha enabling
  decay no longer flips it for all. (Per-alpha *capital* allocation remains shared from
  `account_equity` — see Deferred.)
- **P1-7 (legacy causality guard).** The legacy single-signal synchronizer path now applies the
  same explicit `s.timestamp_ns <= tick.timestamp_ns` filter as the multi-feeder path
  (`synchronizer.py`).
- **P1-8 (solver-degradation alert).** The optimizer marks an ECOS-failure fallback with a
  distinct `solver_status="ECOS_FAILED_FALLBACK"`; `SizedPositionIntent.solver_status` carries it;
  `HorizonMetricsCollector` emits a `composition.solver_degraded` WARNING alert (per-alpha
  state-change throttle) on any degraded status.

### P2 — resolved (fixes) / documented (modeling & layer decisions)

- **P2-1 (identity risk model).** Documented the static unit-diagonal Σ choice in
  `_optimize_cvxpy` (`turnover_optimizer.py`): it is a convexity/dispersion regularizer, not a
  true risk model (no intraday Σ per design Q5); wiring an estimated diagonal vol is the noted
  extension and would re-baseline the L3 solver hash.
- **P2-2 (completeness "non-stale" semantics).** Documented in `synchronizer.py` that completeness
  counts *present-and-causal* signals (subject to the `ts ≤ barrier` guard and the `ts ≥ snapshot`
  floor), not a staleness window. A true staleness gate changes completeness → the gate → the
  intent stream, so it is deferred behind an explicit window choice + L3 re-baseline rather than
  introduced silently.
- **P2-3 (caps not from alpha `risk_budget`).** Documented the layer separation in the
  `TurnoverOptimizer` docstring: `gross_cap_pct` / `per_name_cap_pct` are composition-shaping
  (USD / fraction-of-capital) defaults; the alpha `risk_budget` (`max_position_per_symbol` in
  *shares*, `max_gross_exposure_pct`) is enforced authoritatively and per-leg by
  `RiskEngine.check_sized_intent` (verified) / `AlphaBudgetRiskWrapper`. Feeding the shares-domain
  budget into the USD optimizer would double-count and leak the risk layer into composition
  (Inv-8), so it was **not** wired; operator-tunable shaping caps are the noted extension.
- **P2-4 (confusing closed-form scale clamp).** Removed the `min(…, capital)` clamp in
  `_optimize_closed_form` (`turnover_optimizer.py`). The clamp silently under-levered whenever the
  raw weight gross fell below `gross_cap`; the per-name cap (step 2) and post-rounding gross shrink
  (step 4) already bound the book from above, so the clamp added no safety. **The locked L3
  (decay-off/on) and L4 hashes are unchanged** — the canonical fixtures have weight-gross above
  `gross_cap`, so the clamp never bound there; only the previously-incorrect small-gross regime is
  affected. Covered by `tests/composition/test_turnover_optimizer.py`.
- **P2-5 (neutralizer degenerate-matrix doc/impl).** Corrected the `FactorNeutralizer` docstring to
  describe the actual `numpy.linalg.solve` → `lstsq` (min-norm, `rcond`-truncated) fallback and the
  fact that `post_exposure` may be non-zero along degenerate directions (reported, not zeroed).
- **P2-6 (decay doc drift).** Fixed `pro_kyle_benign_v1.alpha.yaml` — the `decay_weighting_enabled`
  description now reads `exp(-Δt / expected_half_life_seconds)` (per-mechanism half-life), matching
  the `CrossSectionalRanker` implementation, not the previous `exp(-age / horizon_seconds)`.

### Deferred — needs an explicit convention decision

- **P1-2 (closed-form turnover penalty).** Making the default closed-form path honor `λ_tc`
  requires choosing a units convention (the closed-form works in dollars; `λ_tc` is calibrated for
  the weight-space QP) and **re-baselining** the L3 decay-off/on and L4 portfolio-order hashes.
  Because this changes default trading economics on an arbitrary calibration, it is held for an
  explicit decision rather than guessed at (Inv-3 evidence-over-intuition). Proposed approach:
  port the closed-form to weight space and apply a proximal soft-threshold of the trade
  `w − w_cur` so `λ_tc` has the same meaning in both paths, then re-baseline in one commit.
- **P1-6 remainder (per-alpha capital / components).** The ranker/neutralizer/sector-matcher/
  optimizer are still shared singletons sized by the platform-wide `account_equity`. Per-alpha
  capital is a risk-budget (`capital_allocation_pct`) question spanning the risk engine; deferred
  pending that design.

### Verifying tests

New/updated coverage for the fixes above:
`tests/composition/test_sector_matcher.py` (P1-3), `tests/composition/test_cross_sectional.py`
(P1-6 decay override), `tests/composition/test_engine.py` (P1-5 per-alpha completeness),
`tests/monitoring/test_solver_degraded_alert.py` (P1-8),
`tests/bootstrap/test_factor_loadings_freshness.py` (P1-4),
`tests/composition/test_turnover_optimizer.py` (P2-4 + closed-form statuses),
`tests/determinism/test_sized_intent_solver_replay.py` (P0-3), and the re-fixtured
`tests/acceptance/test_decay_divergence.py`. `ruff` + strict `mypy` clean; the locked
L3/L4 determinism baselines are unchanged by every fix above.

---

*Methodology: static review of `src/feelies/composition/*`, `bootstrap.py` PORTFOLIO wiring,
`core/events.py`, the three PORTFOLIO alpha YAMLs, `core/platform_config.py`, and the L3/L4
determinism + composition/portfolio/integration tests; plus read-only test execution and two
read-only Python experiments (cvxpy-vs-closed-form hash comparison and an ECOS-success divergence
probe) for the audit pass. The Resolution log (§11) documents the subsequent fixes.*

