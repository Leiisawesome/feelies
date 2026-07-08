# Proposal Template — Deliverable for Every SIGNAL Candidate

Every research proposal instantiates all twelve sections below, in
order. A section that is genuinely not yet reachable (e.g. EXECUTION
RESULT before any backtest ran) is written as `PENDING`, never
omitted. The right-hand column names the alpha YAML field the section
feeds (schema reference: `alphas/SCHEMA.md`); sections without a YAML
target are review artifacts.

Status values come from the research-stage vocabulary
(research-workflow skill): {hypothesis, candidate, trap-quadrant,
accepted, rejected}. "working" is banned.

| # | Section | Contents | Feeds |
|---|---------|----------|-------|
| 1 | SIGNAL | The reformalized claim (research-protocol.md Phase 0): exact L1 state variable with units, conditional-distribution claim, declared horizon from `{30, 120, 300, 900, 1800}` s | `hypothesis`, `horizon_seconds` |
| 2 | ARCHETYPE & COUNTERPARTY | Archetype (liquidity provision / informed-flow-following / argued third case); structural counterparty and why they trade against THIS signal (research-protocol.md Phase 1 rider); `TrendMechanism` family + expected half-life | `structural_actor`, `trend_mechanism.family`, `trend_mechanism.expected_half_life_seconds` |
| 3 | STATE VARIABLES | Sensors consumed (implemented `sensor_id`s only — feature-engine skill catalog), with the mirage-risk rank of each observable family (research-protocol.md, L1 Data Limitations) | `depends_on_sensors`, `trend_mechanism.l1_signature_sensors` |
| 4 | PROCESS MODEL | The latent process generating the signature; the zero-integrated-edge conservation argument (research-protocol.md Phase 3 test 6) — the counterparty must be able to supply the integrated edge | — (review artifact) |
| 5 | ENTRY-EXIT RULE | Gate conditions (regime gate DSL), entry trigger, exit paths (gate OFF / hazard / half-life age), warm/stale handling | `regime_gate`, `hazard_exit` |
| 6 | L2 LOSS ACCOUNTING | What the L1 projection hides for THIS signal; stricter for high-mirage inputs; the "what breaks if L2 reality diverges" statement + divergence monitor | — (review artifact) |
| 7 | STATISTICAL RESULT | IC / CPCV per regime stratum (research-protocol.md Phase 3 test 3, with per-stratum n), trial-ledger N and noise ceiling `E[max Sharpe \| null, N]` alongside every Sharpe (research-workflow skill, Living Trial-Count Ledger) | promotion evidence (CPCV / DSR) |
| 8 | EXECUTION RESULT | Post-cost, post-latency result under the canonical realism profile; Inv-12 stress (`--inv12-stress`) survival. Tier-1 naive-fill numbers are never presented as results (backtest-engine `fill-model.md`) | `cost_arithmetic` reconciliation vs realized |
| 9 | CAPACITY & CROWDING | ADV-based ceiling, Sharpe-max vs profit-max target, correlated-unwind reasoning (SKILL.md, Pre-Trade Capacity & Crowding Envelope). Caveat (OQ-3): runtime mechanism-share enforcement is not active — no deployment claim may rely on it (composition-layer skill) | — (review artifact) |
| 10 | FALSIFICATION CONDITION | Mechanism-tied forward test that kills the claim (Inv-2); the G16 failure signature | `falsification_criteria`, `trend_mechanism.failure_signature` |
| 11 | STATUS | One value from {hypothesis, candidate, trap-quadrant, accepted, rejected}; `accepted` = ready to seek RESEARCH→PAPER via `validate_gate` with `ResearchAcceptanceEvidence` (alpha-lifecycle skill) | lifecycle entry |
| 12 | NEXT ACTION | The single next falsifying or gate-clearing step; `none` only for rejected | — |

Cost lines anywhere in the proposal state **one-way (per-fill) bps**
quantities — the units-convention rider in SKILL.md (Cost Arithmetic
section) applies verbatim.
