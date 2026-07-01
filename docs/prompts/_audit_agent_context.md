# Shared audit agent-context blocks

Per-prompt inserts live in each `audit_*.md` under **Agent context (mandatory)**.
This file is the maintenance source when adding a new audit prompt.

## Standard footer (all prompts)

Every finding with severity P0/P1 must cite:

- at least one **Inv-N** from `.cursor/rules/platform-invariants.mdc`, and
- `path:line` evidence from the repo.

Behavioral constraints for the audit pass come from
`.cursor/rules/karpathy-guidelines.mdc` (read-only, no speculative fixes,
falsifiable claims, surface assumptions).

Before running commands, follow `AGENTS.md` for environment/test guidance. If Claude Code
also loads `CLAUDE.md`, `AGENTS.md`, the current prompt, and `.cursor/rules/` /
`.cursor/skills/` context take precedence for audit execution.

**Shipped vs Not shipped:** When the owning skill marks a section **Not shipped**,
treat it as a design target — do not file P0 for absence unless code, tests, or
operator docs claim it is live. Cross-check the skill's **Not shipped** markings,
inline design-target notes, or **Design Targets** section before escalating.

**Canonical tables (do not re-derive from memory):**

| Topic | Skill | Code |
|-------|-------|------|
| Parity hashes L1–L6 | `testing-validation` | `tests/determinism/parity_manifest.py` |
| Promotion F-1..F-6 | `alpha-lifecycle` | `src/feelies/alpha/promotion_evidence.py` |
| Layer topology / SMs | `system-architect` | `src/feelies/kernel/` |

Full index: `.cursor/skills/README.md`.

## Per-audit read order

| Prompt | Owner skill | Also read | Primary Inv | Glossary terms |
|--------|-------------|-----------|-------------|----------------|
| `audit_data_ingestion` | data-engineering | backtest-engine (replay) | 5,6,9,10,11,13 | replay, backtest, strict typing |
| `audit_sensor` | feature-engine | microstructure-alpha (G16 sensors) | 5,6,10,11 | sensor, feature, horizon, warm-up, staleness |
| `audit_regime` | regime-detection | microstructure-alpha (gate), risk-engine (hazard) | 5,6,11 | regime gate, hazard spike, regime |
| `audit_signal_alpha` | microstructure-alpha | feature-engine (snapshot input) | 1,2,5,6,7,12 | horizon signal, cost arithmetic, trend mechanism |
| `audit_composition` | composition-layer | microstructure-alpha, risk-engine | 5,6,11 | portfolio alpha, sized position intent, mechanism concentration |
| `audit_risk_engine` | risk-engine | regime-detection, composition-layer | 5,11 | hazard exit, sized position intent |
| `audit_position_management` | risk-engine + live-execution | composition-layer (position reads), system-architect (ordering touchpoint) | 5,11,12,13 | sized position intent, hazard exit |
| `audit_execution_fills` | backtest-engine | live-execution (parity) | 6,9,12 | backtest, simulation |
| `audit_live_execution` | live-execution | backtest-engine (ExecutionBackend) | 9,11 | simulation, hazard exit |
| `audit_alpha_lifecycle` | alpha-lifecycle | testing-validation (gate bars) | 3,5,13 | promotion, gate matrix, promotion ledger, layer gate |
| `audit_forensics` | post-trade-forensics | alpha-lifecycle (quarantine path) | 1,4,11,13 | quarantine, quarantine-trigger evidence, decay |
| `audit_research_validation` | research-workflow | testing-validation (CPCV/DSR) | 2,3 | CPCV evidence, DSR evidence |
| `audit_kernel` | system-architect | — | 5,6,7,8,9,10 | replay, strict typing |
| `audit_determinism` | testing-validation | system-architect (ordering) | 5 | replay, strict typing |
| `audit_core_clock_config` | system-architect | — | 5,7,10 | replay, strict typing |
| `audit_performance` | performance-engineering | system-architect (hot path) | 5 | replay |
| `audit_monitoring_safety` | live-execution | risk-engine (hazard) | 11 | hazard exit |
| `audit_harness_cli` | backtest-engine | alpha-lifecycle (`promote`), research-workflow | 5,13 | operator CLI, replay |

When updating a prompt, copy the row above into its **Agent context** table and
trim duplicate skill/invariant bullets from **Platform context**.
