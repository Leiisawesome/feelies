# Research Protocol — Detailed Methodology

## Codebase Alignment

Research features defined below feed into the Layer-1 sensor framework
(`feelies.sensors`) — implementations of the `Sensor` protocol
(`sensors/protocol.py`) emitting `SensorReading` events
(`core/events.py`). `HorizonAggregator` (`features/aggregator.py`)
fans them into `HorizonFeatureSnapshot` events on `HorizonTick`
boundary crossings. Signal logic feeds into the `HorizonSignal`
contract (`signals/horizon_protocol.py`) declared inline in a
schema-1.1 SIGNAL alpha YAML — `evaluate(snapshot, regime, params)
-> Signal | None`.

Layer-2 input is `HorizonFeatureSnapshot` only; D.2 retired `FeatureVector` / `LEGACY_SIGNAL`.

The formalization path from research prototype to engine component is
governed by the research-workflow skill. Sensors must implement
incremental `update(event, state, params) -> SensorReading | None`
semantics (per-symbol `state` is owned by the registry and threaded
through each call); batch pandas/numpy prototypes must be re-implemented
incrementally before backtesting via `Orchestrator.run_backtest()`.

Schema-1.1 SIGNAL alphas additionally declare:

- `depends_on_sensors:` (G6 sensor-DAG validity)
- `horizon_seconds:` (single-horizon binding)
- `trend_mechanism:` (G16 — required since Workstream E)
- `regime_gate:` (AST-DSL purity boundary)
- `cost_arithmetic:` (G12 — margin_ratio ≥ 1.5, reconciles ±0.05 absolute; `alpha/cost_arithmetic.py`)

---

## Hypothesis-Driven Research Framework

Every proposal instantiates the deliverable template
([proposal-template.md](proposal-template.md)) — its sections map onto
the phases below and the alpha YAML fields they feed.

### Phase 0: Reformalization Gate (folk language → state variable)

Folk/TA pattern language ("support", "resistance", "the level holds",
"breakout") is **inadmissible as a hypothesis input** until restated
as all three of:

- (a) an exact sensor-expressible L1 state variable **with units**;
- (b) a conditional-distribution claim over forward returns (or a
  named intermediate observable);
- (c) a falsifying forward test.

A folk claim that cannot complete (a)–(c) is not rejected — it is not
yet a hypothesis. Do not proceed to Phase 1 without the restatement.

Worked example:

| Folk claim | Restatement |
|-----------|-------------|
| "Price is approaching a prior extreme" | (a) Distance, in **ticks** (`execution/tick_size.py` grid), from the current best bid/ask to the prior N-bar local extremum of mid |
| "The level holds" | (b) Conditional on distance ≤ k ticks, quote-replenishment intensity (`quote_replenish_asymmetry`, `sensors/impl/quote_replenish_asymmetry.py`) rises vs its unconditional baseline |
| Falsifier | (c) The stated conditional forward-return test via `research/forward_ic.py` (`spearman_ic`, `bucketed_forward_return`) at the declared horizon; no significant conditional shift ⇒ the claim dies |

### Phase 1: Hypothesis Formation

Every research initiative begins with a structural hypothesis:

```
HYPOTHESIS TEMPLATE:
- Observable: [What L1 phenomenon do we observe?]
- Mechanism: [What latent process generates this observation?]
- Prediction: [What forward return distribution does this imply?]
- Counterfactual: [What would we observe if the hypothesis is false?]
- Decay model: [How does this edge degrade under exploitation?]
```

Reject hypotheses that:
- Cannot specify the mechanism
- Have no testable counterfactual
- Require data you don't have (L2, direct feed timestamps)
- Assume stable parameters across regimes

#### Archetype & structural counterparty (rider on the mechanism taxonomy)

The closed `TrendMechanism` families (`core/events.py`; table in
[SKILL.md](SKILL.md)) encode **mechanisms, not archetypes**. In
addition to the family declaration, every candidate must state:

- **Archetype** — one of: liquidity provision,
  informed-flow-following, or an explicitly argued third case. Naming
  the family does not answer this; state it separately.
- **Structural counterparty** — who is on the other side, and **why
  they trade against THIS signal rather than the market at large**
  (constraint, mandate, information deficit, or urgency that makes
  their flow systematically exploitable). "The market" is not a
  counterparty.

Record both in the alpha YAML's `structural_actor` field
(`alphas/SCHEMA.md`, optional Phase-3 field) and in the proposal's
ARCHETYPE & COUNTERPARTY section
([proposal-template.md](proposal-template.md)). This is authoring
discipline enforced at review, **not** a loader gate — the field
remains schema-optional today (schema-requiring it is a backlogged
`LayerValidator` change, `docs/research/prompt_pack_backlog.md`). The
hypothesis line's `[actor]` names the actor whose behavior *generates*
the L1 signature; the counterparty is whoever *funds* the edge — do
not conflate them, and the conservation check (Phase 3, test 6) must
be argued against the counterparty.

### Phase 2: Feature Engineering from L1

#### Spread-Based Features

| Feature | Construction | Rationale |
|---------|-------------|-----------|
| Spread level | ask - bid | Liquidity cost proxy |
| Spread z-score | (spread - rolling_mean) / rolling_std | Regime detection |
| Spread velocity | d(spread)/dt | Liquidity withdrawal speed |
| Spread acceleration | d²(spread)/dt² | Second-order liquidity shock |
| Spread percentile | Rolling rank of current spread | Non-parametric regime |

#### Quote-Based Features

| Feature | Construction | Rationale |
|---------|-------------|-----------|
| Quote update intensity | Updates per unit time | Information arrival proxy |
| Bid/ask update asymmetry | (ask_updates - bid_updates) / total | Directional pressure |
| Quote duration | Time between updates per side | Liquidity stability |
| Quote flicker rate | Rapid cancel-replace sequences | Spoofing / uncertainty proxy |
| Size imbalance | (bid_size - ask_size) / (bid_size + ask_size) | Micro-price adjustment |

#### Trade-Based Features

| Feature | Construction | Rationale |
|---------|-------------|-----------|
| Trade aggressor | Classify via Lee-Ready or similar | Flow direction |
| VPIN proxy | Volume-bucketed aggressor imbalance | Toxicity measure |
| Trade clustering | Hawkes process intensity estimate | Self-exciting flow |
| Trade-to-quote ratio | Trades / quote updates in window | Information vs noise |
| Effective spread | 2 * |trade_price - mid| | Execution cost realization |

#### Micro-Price Features

| Feature | Construction | Rationale |
|---------|-------------|-----------|
| Weighted mid-price | bid + spread * (ask_size / (bid_size + ask_size)) | Fair value proxy |
| Micro-price momentum | Rolling change in weighted mid | Short-horizon trend |
| Micro-price mean reversion | Deviation from EWMA of weighted mid | Reversion signal |

### Phase 3: Statistical Validation

#### Test Hierarchy

1. **Univariate predictive regressions**
   - Regress forward returns on each feature
   - Use Newey-West standard errors (account for serial correlation)
   - Report t-stats, R², information coefficient

2. **Cross-validation protocol**
   - Walk-forward with expanding or rolling window
   - Never look ahead — strictly causal feature construction
   - Minimum 3 non-overlapping out-of-sample periods

3. **Regime stratification**
   - Test separately in low-vol, medium-vol, high-vol regimes
   - Test separately in tight-spread vs wide-spread regimes
   - Report if alpha concentrates in one regime (fragility signal)

   Manual procedure (**Not shipped as a harness** — no stratified
   runner exists; execute by hand, cross-linked from the
   testing-validation skill):

   1. Partition horizon boundaries by HMM dominant state
      (`RegimeState.dominant_name` from `HMM3StateFractional`,
      `services/regime_engine.py`; 3 states) × `spread_z_30d` strata
      (implemented sensor; e.g. terciles of the boundary-time value).
   2. Repeat the IC test per stratum
      (`scripts/sensor_feature_ic.py` output paired with the stratum
      labels; `research/forward_ic.py` for the statistics).
   3. Repeat CPCV per stratum (`research/cpcv.py`) where the stratum
      has enough boundaries to form the configured groups.
   4. Minimum per-stratum sample rule: a stratum with fewer than
      ~100 boundary observations is reported as INSUFFICIENT, not
      pooled away silently (`spearman_ic`'s internal ≥ 3-pair floor
      is a computability bound, not adequacy). State the per-stratum
      n alongside every per-stratum statistic.
   5. Pass rule: the ≥ 2 vol × ≥ 2 spread regime requirement
      (research-workflow skill, Mandatory Controls) is evaluated on
      the per-stratum results; single-stratum concentration is a
      fragility flag, not an automatic kill — but it must be stated
      in the proposal's STATISTICAL RESULT section.

   Beware the tick-grid artifact (Phase 4 below) when defining
   spread strata for low-priced midcaps.

4. **Transaction cost hurdle**
   - Compute realistic round-trip cost: spread + slippage + market impact
   - Alpha must exceed cost by a margin (minimum Sharpe contribution > 0.5 after costs)
   - Model fill probability for limit orders at various queue positions

5. **Multiple testing correction**
   - Track number of features tested
   - Apply Bonferroni or Benjamini-Hochberg correction
   - Report both raw and adjusted significance
   - Every variant tried anywhere in the workflow increments the
     living trial ledger N (research-workflow skill, Multiple
     Testing & Overfitting Controls) — features are one kind of
     trial, not the whole count

6. **Zero-integrated-edge conservation check (mandatory, one per signal)**
   - Over a long regime-balanced sample, the integrated edge must be
     consistent with the stated mechanism's economics: the declared
     structural counterparty (Phase 1 archetype rider) must plausibly
     supply it. A mechanism whose counterparty cannot fund the
     integrated PnL is a free lunch and therefore a misattribution —
     the edge, if real, comes from something you have not named.
   - Procedure: integrate the per-fill edge estimate (or the
     conditional forward-return edge pre-cost) over the full sample;
     compare its sign, magnitude, and regime distribution against
     what the counterparty's stated constraint can pay. State the
     argument in the proposal's PROCESS MODEL section; a hand
     estimate is acceptable, hand-waving is not.
   - This is an economics-consistency test, distinct from the PnL
     decomposition accounting identity in the testing-validation
     skill (alpha + beta + costs = total).

#### Backtest Standards

```
BACKTEST REQUIREMENTS:
- Entry point: `Orchestrator.run_backtest()` with `SimulatedClock` (core/clock.py)
- Latency model: minimum 10ms processing + network delay (injected via SimulatedClock)
- Fill model: no immediate fills at NBBO; model queue position (OrderRouter protocol)
- Slippage model: function of size relative to displayed liquidity
- Market impact: even for small orders, model temporary impact
- Cost model: explicit commission + SEC/FINRA fees
- Timestamp alignment: use exchange timestamps via NBBOQuote.exchange_timestamp_ns
- Determinism: SHA-256-derived order IDs via `derive_order_id(seed)` — first 16 hex chars of the hashed provenance seed; the signal path seeds with f"{correlation_id}:{seq}" (core/identifiers.py)
```

### Phase 4: Robustness Checks

| Test | Purpose | Red Flag |
|------|---------|----------|
| Parameter perturbation | Vary lookback windows ±20% | Sharp performance cliff |
| Subsample stability | Test on first/second half separately | Sign reversal |
| Ticker rotation | Test on in-sample and out-of-sample tickers | Only works on trained tickers |
| Calendar effects | Test across days-of-week, month-end, FOMC | Alpha clusters on events only |
| Regime conditioning | Stratify by VIX level | Works only in one regime |
| Data vintage | Test on different data periods | Recent-only alpha (overfitting) |
| Tick-grid artifact | See below | Spread-state "regimes" are grid states |

#### Tick-constraint artifact test (required for spread-state claims)

When the minimum tick (`execution/tick_size.py`: $0.01 above $1.00,
$0.0001 below — Reg NMS sub-penny grid) is a large fraction of the
quoted midcap spread, spread-state dynamics compress into a few
discrete states (spread = 1, 2, 3 ticks) and apparent regime
persistence — or spread-regime structure, or the spread strata of
Phase 3 test 3 — can be a grid artifact rather than a liquidity
phenomenon.

- Required test: report the sample's spread-in-ticks distribution;
  if a claimed spread state coincides with a single grid value,
  re-derive the claim on a sub-universe where spread ≥ ~4 ticks (or
  demonstrate the effect survives conditioning on spread-in-ticks).
- Any scheduled tick-regime change (e.g. a tick-size pilot touching
  the universe) is a **pre-registered structural sample boundary**:
  never pool across it; treat pre/post as separate samples with the
  boundary declared before looking at the data.

### Phase 5: Alpha Decay Modeling

Model the half-life of the signal:
- Measure information coefficient as a function of horizon
- Estimate decay curve: IC(t) = IC_0 * exp(-lambda * t)
- If half-life < execution latency, the signal is not tradeable
- Monitor decay in production: compare realized IC vs expected IC

---

## Validation Protocol & Slate Design Discipline

Per-candidate validation protocols (e.g.
`docs/research/sig_inventory_fade_v1_validation_protocol.md`)
freeze before implementation and before outcome contact. Three
freeze-blocking items below; incident citations from cycle-1
retrospective Task 7-R (H8 census arc — see
`docs/research/sig_dislocation_lambda_drift_v1_result.md`).

### Magnitude-vs-power labeling (backlog 12)

Every pre-registered bar in a validation protocol must declare at
freeze:

| Field | Requirement |
|-------|-------------|
| **Label** | `n-invariant` (magnitude/κ-class — more evidence volume cannot cure the failure) or `power-class` (curable by census volume, occupancy, or session count) |
| **Consequence** | Must match the label: `n-invariant` magnitude failures → REJECTED-terminal; `power-class` failures may PARK as evidence-infrastructure only when the freeze says so |

An unlabeled bar, or a magnitude bar paired with a PARK-only
consequence, is a **freeze-blocking defect**.

Incident: H8 step-2b |RankIC| ≥ 0.03 (`n-invariant` at pooled
+0.0186); the A-2.1 safeguard PARK and the post-outcome S.8 ruling
were needed only because the label was absent at freeze
(`docs/research/sig_dislocation_lambda_drift_v1_result.md`;
`sig_dislocation_lambda_drift_v1_result.md`). Acceptance bars in the
testing-validation skill inherit the same label/consequence pairing.

### Consequence-precedence at freeze (backlog 13)

Whenever two pre-registered instruments can fire on the same execution
(primary gate row + safeguard, park condition + reject condition,
amendment + frozen census constant), the freeze must state which
governs at **every** intersection. Undefined precedence is a
**freeze-blocking defect** — post-outcome adjudication is forbidden.

Default precedence classes (state explicitly even when adopting these):

1. **Primary gate rows** (§9 consequence table) outrank safeguard/park
   instruments on the same statistic — a safeguard may tighten a pass,
   never loosen a primary fail.
2. **Amendments** may not silently override frozen census-derived
   constants — grid-amendment constant governance (data-engineering
   skill; backlog 16).
3. **Evidence-set axis definitions** (e.g. per-symbol vs pooled counting
   basis) must name the governing instrument when census outcome shrinks
   D.

Incidents: (a) H8 §9 "2b IC gate" REJECTED and A-2.1 APP-safeguard PARK
fired together with precedence undefined until S.8; (b) frozen "pooled
over D" needed the mid-flight A-2.1 ruling when D shrank to {APP}
(AMENDMENT A-2).

### Census-legal occupancy pre-read (backlog 15)

Distribution-theoretic occupancy priors (near-Gaussian tail mass,
assumed joint conditioning fractions) must be verified against a
**census-legal occupancy read** on the operative grid before any
slate-selection or power headline cites an episode count.
**Percentile-tail fractions are exempt** (true by construction).

Procedure (manual — **Not shipped** as a harness):

1. Run the census-pinned predicate on the operative `(symbol, session)`
   grid (or a return-free occupancy-only pass with the same constructor
   params).
2. Record marginal and joint occupancy at the declared conditioning
   threshold.
3. Design-central episode arithmetic in slate ranking or selection prose
   must use the measured occupancy, not the distributional prior.

A power projection in the frozen census section that relies on an
unverified occupancy prior is a **freeze-blocking defect**.

Incidents: H8 design 0.453 marginal / 0.226 joint vs realized 0.343 /
0.107 (protocol C.5); H6/H7 104-episode headline vs ≈ 52
design-central (`prompt_pack_06a_slate_b_review.md` §3).

### Grid amendments and frozen constants (backlog 16)

Any grid amendment must pre-register, before the amended census
executes, the disposition of every frozen census-derived constant
(spread-tercile cutpoints, per-symbol thresholds, viability floors):
**carry**, **recompute**, or **refreeze** with explicit new values.
Mid-flight ruling is forbidden. Operational detail: data-engineering
skill, Grid-Amendment Constant Governance. Incident: H8 A-1 silence on
§4.1/JC-4 spread-tercile cutpoints → A-2.2 ruling
(`prompt_pack_03c_universe_and_cache.md` AMENDMENT 1).

---

## L1 Data Limitations — What You Cannot See

Explicitly acknowledge these blind spots:

| Hidden Information | Impact | Mitigation |
|-------------------|--------|------------|
| Full order book depth | Cannot measure true liquidity beyond top | Infer from spread dynamics + trade sizes |
| Hidden/dark orders | Underestimate true liquidity | Track trade-to-displayed-size ratios |
| Cancel-to-trade ratio | Cannot directly observe full cancellation flow | Proxy via quote flicker rate |
| Queue position | Cannot know where your order sits | Model probabilistically |
| Cross-venue dynamics | Massive aggregates; you lose venue granularity | Accept as systematic noise |
| True latency | Variable websocket delay | Model as stochastic latency; add buffer |

Every model must include a section: "What breaks if the L2 reality diverges
from our L1 inference?" — and specify monitoring for this divergence.

### Mirage risk by observable family

L1 observables differ in how easily the latent state they proxy can
be revoked, hidden, or adversarially manufactured. Rank every
candidate's inputs (sensor catalog: feature-engine skill):

| Observable family | Mirage risk | Why |
|-------------------|-------------|-----|
| Spread state, trade prints | **LOW** | Trades are irrevocable; the quoted spread is executable at the instant observed |
| Micro-price / size imbalance | **MEDIUM** | Displayed size is strategic (icebergs, hidden liquidity); imbalance can misstate true depth |
| Quote-flow / cancellation (`quote_flicker_rate`, `quote_hazard_rate`) | **HIGH** | Revocable quotes, hidden-book dependence, adversarially manufacturable (spoof-shaped flow) |

Rules:

- High-mirage families demand **stricter L2-loss accounting** in the
  proposal's L2 LOSS ACCOUNTING section (what latent state is
  assumed, how an adversary or hidden book breaks it, what monitors
  detect the divergence) — **not disqualification**.
- The mirage rank **never settles the archetype question** (Phase 1
  rider): a high-mirage signal can still be genuine
  informed-flow-following, and a low-mirage one can still lack a
  counterparty. Argue archetype and mirage independently.

---

## Mathematical Toolkit Reference

### Point Processes for Order Arrivals

Model trade/quote arrivals as a Hawkes process:

```
lambda(t) = mu + sum_i alpha * exp(-beta * (t - t_i))
```

- mu: baseline intensity
- alpha: self-excitation (clustering)
- beta: decay rate
- Estimate via MLE on trade timestamps
- Use to detect regime shifts in flow intensity

### Micro-Price Dynamics

Weighted mid-price as Bayesian fair value:

```
p_micro = p_bid + spread * (V_ask / (V_bid + V_ask))
```

Under the assumption that displayed size reflects informational content.
Caveat: this breaks when displayed sizes are strategic (iceberg orders).

### Spread Process

Model spread as a mean-reverting jump-diffusion:

```
dS = kappa * (theta - S) * dt + sigma_S * dW + J * dN
```

- kappa: mean reversion speed
- theta: long-run spread level (regime-dependent)
- J: jump size distribution (spread dislocation events)
- N: Poisson process for liquidity shocks

### Order Flow Imbalance

Aggregate signed trade flow in volume buckets (not time buckets):

```
OFI_n = sum_{trades in bucket n} sign_i * volume_i
```

Use volume time to normalize for intraday seasonality.
Test predictive power of OFI on next-bucket return.

---

## Implementation Mapping

| Research concept | Codebase type | Location |
|------------------|---------------|----------|
| Sensor prototype (Layer 1) | `Sensor` protocol + `SensorSpec` | `sensors/protocol.py`, `sensors/spec.py`, `sensors/registry.py` |
| Sensor output | `SensorReading` (with `SensorProvenance`) | `core/events.py` |
| Layer-2 input | `HorizonFeatureSnapshot` (per-`feature_id` warm/stale dicts; z-score / percentile views are `feature_id` keys inside `values`, e.g. `ofi_ewma_zscore`) | `core/events.py` |
| SIGNAL alpha contract | `HorizonSignal.evaluate(snapshot, regime, params)` | `signals/horizon_protocol.py` |
| Signal output | `Signal` (with `SignalDirection`, `edge_estimate_bps`, `trend_mechanism`, `expected_half_life_seconds`) | `core/events.py` |
| Regime gate DSL | `RegimeGate` (AST-evaluated boolean DSL) | `signals/regime_gate.py` |
| Cost arithmetic | `CostArithmetic` (G12 enforcement at load time) | `alpha/cost_arithmetic.py` |
| Trend mechanism (G16) | `TrendMechanism` enum + family envelopes | `core/events.py`, `alpha/layer_validator.py` |
| Cross-sectional construction | `PortfolioAlpha` + `CompositionEngine` | `composition/protocol.py`, `composition/engine.py` |
| L1 quote / trade input | `NBBOQuote` / `Trade` | `core/events.py` |
| Backtest execution | `Orchestrator.run_backtest()` | `kernel/orchestrator.py` |
| Research execution | `Orchestrator.run_research(job)` | `kernel/orchestrator.py` |
| Deterministic time | `SimulatedClock` | `core/clock.py` |
| Config provenance | `Configuration.snapshot()` | `core/config.py` |
| Promotion lifecycle | `AlphaLifecycle` + F-2 gate matrix + F-1 ledger | `alpha/lifecycle.py`, `alpha/promotion_evidence.py`, `alpha/promotion_ledger.py` |
| Operator forensic CLI | `feelies promote ...` | `cli/promote.py` |
