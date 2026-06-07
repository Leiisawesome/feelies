# Layer-1 sensors math & microstructure audit (Claude Code)

Use this prompt in a **Claude Code** session with full repo access. Scope: feelies Layer-1 sensors and horizon aggregation—not generic ML features.

---

## Mission

You are a senior quantitative microstructure researcher and systems auditor.
Perform a **read-only, evidence-based audit** of the feelies Layer-1 sensor
framework and its path into `HorizonFeatureSnapshot` features.

**Goal:** Identify where sensor math is rigorous vs. heuristic, where aggregation
dilutes or distorts signal, and what changes would yield **stronger, more
tradable feature inputs** for Layer-2 `HorizonSignal` alphas—without breaking
platform invariants.

**Do not implement fixes in this pass.** Deliver a structured audit report with
file/line citations, severity, and prioritized recommendations.

---

## Platform context (read first)

1. Read `.cursor/skills/feature-engine/SKILL.md` and
   `.cursor/skills/microstructure-alpha/SKILL.md` end-to-end.
2. Read `docs/three_layer_architecture.md` § on sensors / horizons / snapshots.
3. Skim `platform.yaml` `sensor_specs:` and G16 mechanism ↔ sensor fingerprints
   in the microstructure-alpha skill.

**Architecture (contractual):**

- **Layer 1 — Sensors** (`src/feelies/sensors/`): incremental, per-symbol,
  event-time; emit `SensorReading` on NBBOQuote/Trade.
- **Layer 1.5 — Horizons** (`sensors/horizon_scheduler.py`,
  `features/aggregator.py`): integer-math `HorizonTick` boundaries →
  `HorizonFeatureSnapshot` (the **only** Layer-2 feature input post-D.2).
- **Layer 2 — Signals** (`src/feelies/signals/`): stateless functions on
  snapshots + `RegimeState`; must not read raw quotes.

**Hard invariants (non-negotiable):**

- Inv-5: deterministic replay (same log + params → bit-identical outputs).
- Inv-6: causality (no lookahead; processing delay explicit).
- Per-symbol isolation in sensors; sensor DAG acyclic (`SensorRegistry`).
- Warm-up / staleness must gate **entries**, not exits (fail-safe).

---

## Scope — files to audit

### Core framework

- `src/feelies/sensors/protocol.py`, `spec.py`, `registry.py`, `errors.py`
- `src/feelies/sensors/horizon_scheduler.py`
- `src/feelies/features/aggregator.py` (snapshot construction from readings)
- `src/feelies/features/protocol.py`, `warmup.py` (if present)
- `src/feelies/bootstrap.py` (sensor registry wiring, throttle, metrics)

### Every sensor implementation

- `src/feelies/sensors/impl/*.py` (all modules; catalog in feature-engine skill)

### Tests (use as spec + gap analysis)

- `tests/sensors/test_*.py`, `tests/sensors/_helpers.py`, fixtures
- Determinism: `tests/determinism/test_sensor_reading_replay.py`,
  `test_v03_sensor_replay.py`, `test_horizon_feature_snapshot_replay.py`
- Any horizon aggregation tests under `tests/features/`

### Downstream consumers (read-only, for "does the feature help alpha?")

- Example alphas' `consumed_features` / `depends_on_sensors` in `alphas/`
- `src/feelies/signals/horizon_engine.py` (how snapshots are interpreted)

---

## Audit dimensions (answer each with evidence)

### A. Mathematical & statistical rigor (per sensor)

For **each** `sensor_id` in `platform.yaml`:

1. **Definition**
   - State the estimator in plain math (symbols, units, sign convention).
   - Cite the literature or standard market-microstructure definition used
     (e.g. Cont–Kukanov–Stoikov OFI, Kyle λ, Hasbrouck, Easley–O'Hara VPIN,
     Hawkes self-excitation, Glosten–Milgrom spread, etc.).
   - Flag if the code implements a **different** object than the docstring claims.

2. **Discretization & L1 limitations**
   - What latent L2 quantity is being proxied? What information is **lost** at L1?
   - Are bid/ask size changes interpreted as flow without trade confirmation?
   - Quote flicker, halts, NBBO consolidations, trade-throughs: handled or ignored?

3. **Numerical stability**
   - Division by zero, log(0), extreme z-scores, unbounded accumulators.
   - Float vs `Decimal` where PnL-sensitive; replay stability across platforms.
   - Parameter sensitivity (α, half-lives, bucket counts): stable or brittle?

4. **Time basis**
   - Event-time vs exchange-time vs wall-clock: which clock drives decay/windows?
   - Is decay aligned with **quote arrival** or **calendar time**? Is that correct
     for the claimed mechanism half-life (G16 envelopes)?

5. **Warm-up & cold-start**
   - Is `warm` statistically meaningful (enough observations for variance)?
   - Sliding-window warm-up (e.g. OFI): correct after gaps?
   - Does `warm=False` prevent garbage from entering snapshots?

6. **Throttling & sparsity**
   - `throttle_ns` on `SensorSpec`: does it alias high-frequency microstructure?
   - Missing readings vs. last-value hold in aggregator: lookahead risk?

### B. Sensor DAG & composition

1. Topological order, `depends_on` edges: any implicit lookahead via upstream
   sensors reading future downstream state?
2. Composite sensors (e.g. OFI + micro_price + effective_spread): independence
   vs. redundant collinearity—would a single sufficient statistic be better?
3. G16 fingerprint coverage: does each `TrendMechanism` family have **orthogonal**
   L1 observables, or duplicate proxies?

### C. Horizon aggregation → feature quality (critical)

Audit `HorizonAggregator` (and related) for how `SensorReading` streams become
`snapshot.values[feature_id]`:

1. **Aggregation policy per horizon** {30, 120, 300, 900, 1800}s:
   - Last value, mean, EWMA, sum, max-abs, percentile? Document actual code paths.
   - Is the policy **optimal for the mechanism half-life** (ratio horizon/half-life
     in [0.5, 4.0] per G16)?

2. **Boundary alignment**
   - `session_open_ns` integer math: any off-by-one at open/close/RTH?
   - Partial buckets at session edges: bias in first/last snapshot of day?

3. **Multi-sensor fusion**
   - How are conflicting signs across sensors combined in one snapshot?
   - `warm` / `stale` flags per feature: propagated correctly?

4. **Signal-to-noise for Layer-2**
   - For each feature in a reference alpha (e.g. `sig_benign_midcap_v1`):
     hypothesize **conditional forward return** directionality; does aggregation
     preserve or smear the edge?
   - Recommend better aggregators (e.g. last-of-horizon for fast inventory;
     integrated OFI for Kyle; realized variance for vol) with justification.

### D. Quantitative trading grounding

1. **Economic mechanism map**
   - Table: `sensor_id` → microstructure force (inventory, information, liquidity
     provision, scheduled flow) → expected horizon of predictability → typical
     sign of short-horizon return relation **conditional on regime**.

2. **Tradability & costs**
   - For each sensor family: is the implied edge likely to survive
     `expected_edge > 1.5× round_trip_cost` (Inv-12)?
   - Features that predict noise or fleeting queue position vs. structural drift.

3. **Decay & crowding**
   - Which sensors are most vulnerable to adverse selection / crowding on L1?
   - Alignment with `expected_half_life_seconds` on emitted `Signal` (Phase 3.1).

### E. Test & validation gaps

1. Map each sensor to existing tests; list **untested** invariants (sign, bounds,
   warm transitions, gap recovery, determinism).
2. Propose **minimal** new tests (property-based or golden replay)—no implementation
   in this pass, only specs.
3. Propose offline validation harness ideas: sensor-level IC/RankIC vs forward
   mid returns on cached NBBO (APP/AAPL), by horizon—methodology only.

### F. Prioritized recommendations

Produce three tiers:

- **P0 (correctness):** math bugs, lookahead, non-determinism, unit/sign errors.
- **P1 (feature strength):** aggregation policy, redundant sensors, missing
  normalization (cross-sectional z within universe at boundary).
- **P2 (research):** new sensors or literature-aligned rewrites, parameter
  calibration from data.

Each item: `sensor_id` or module, file:line, one-sentence fix, expected impact
on feature SNR / alpha usability.

---

## Working method

1. Build an inventory table of all sensors (id, version, inputs, params, deps,
   throttle, warm spec) from code + YAML.
2. Audit implementations in dependency order (leaves of DAG first).
3. Audit aggregator last (downstream of all sensors).
4. Cross-check against `tests/sensors/` and determinism hashes—note any test
   that asserts behavior without economic justification.
5. Run **read-only** checks only:
   - `uv run pytest tests/sensors/ -q`
   - `uv run pytest tests/determinism/test_sensor_reading_replay.py tests/determinism/test_horizon_feature_snapshot_replay.py -q`
   Do not modify production code.

---

## Output format (strict)

Write the audit report to `docs/audits/sensor_audit_YYYY-MM-DD.md` with these sections:

1. **Executive summary** (≤15 bullets): top risks and top opportunities for
   stronger features.
2. **Sensor inventory** (markdown table).
3. **Per-sensor audit** (one subsection each, ≤1 page): math, L1 caveats, tests.
4. **Horizon aggregation audit** (deep dive on `HorizonAggregator`).
5. **Mechanism × horizon matrix** (G16 families vs horizons vs aggregation).
6. **Test gap matrix**.
7. **Prioritized backlog** (P0/P1/P2, estimated effort S/M/L).
8. **Appendix:** open questions needing data runs (symbol, date, metric).

Use code citations as `path:line` for every non-trivial claim.
When citing literature, give author-year-title, not vague "standard practice."

---

## Quality bar

- Prefer **falsifiable** statements ("if X then Y breaks") over adjectives.
- Distinguish **implementation bug** vs **modeling choice** vs **L1 identifiability limit**.
- Do not recommend L2/L3 features; stay Layer-1 + aggregation unless explaining
  consumer impact.
- Respect that the platform cannot use L2 book data—do not suggest "just add depth."

---

## Optional follow-ups (paste after the audit)

- *"After the report, draft P0 fixes only for `ofi_ewma` and `HorizonAggregator` as a follow-up PR plan."*
- *"Use disk cache APP/2026-03-26 for sensor IC analysis methodology in §E—still no code changes."*
