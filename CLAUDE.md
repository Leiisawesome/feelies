# feelies — Claude Code Context

Deterministic intraday trading platform (SENSOR → SIGNAL → PORTFOLIO on L1 NBBO).
Backtest/live parity is contractual; replay is bit-identical.

**Shared commands, testing, linting, and gotchas:** see [`AGENTS.md`](AGENTS.md).

**Platform invariants and glossary:** `.cursor/rules/platform-invariants.mdc`
(always applied — do not restate a shortened subset here).

**Coding behavior:** `.cursor/rules/karpathy-guidelines.mdc` (always applied).

**Domain skills:** `.cursor/skills/README.md` — start here for alpha authoring,
regime, risk, backtest, promotion, etc.

## Claude Code setup

```bash
uv sync --all-extras                                    # recommended
uv sync --extra dev --extra massive                     # dev + Massive feed
uv sync --extra dev --extra massive --extra ib          # + IB Gateway adapter
```

MCP server template: `mcp-config.template.json` (copy locally; never commit secrets).

## Directory map

```
src/feelies/          Core library
  core/               Events, MonotonicClock, config
  kernel/             Orchestrator, macro/micro state machines
  bus/                Synchronous event bus
  ingestion/          Massive normalizer, replay feed, live WS
  sensors/            Layer-1 sensor framework
  features/           Horizon aggregator
  signals/            Layer-2 horizon signal engine + regime gate DSL
  composition/        Layer-3 portfolio construction
  risk/               Risk engine, sizer, hazard exits
  execution/          Execution backends, order routers
  broker/ib/          IB Gateway adapter (paper/live)
  research/           CPCV, DSR, experiment tracking
  forensics/          Post-trade attribution
  cli/                Operator CLI (`feelies promote`, `feelies backtest`)
alphas/               Alpha YAML specs + `_template/` + `SCHEMA.md`
configs/              Run configuration YAML
scripts/              Backtest, paper, smoke entry points
tests/                Pytest suite + determinism + perf
docs/                 Architecture specs and audits
```

## Alpha development (pointers only)

- New SIGNAL alphas: copy `alphas/_template/template_signal.alpha.yaml`
- Schema 1.1 is current; full gate table in `alphas/SCHEMA.md`
- Authoring depth: `.cursor/skills/microstructure-alpha/SKILL.md`
- PORTFOLIO alphas: `.cursor/skills/composition-layer/SKILL.md`

## Cross-platform notes

- Event cache: `~/.feelies/cache/`
- IB Gateway: `127.0.0.1:4002`
- Use forward slashes in docs; paths resolve on macOS and Windows
