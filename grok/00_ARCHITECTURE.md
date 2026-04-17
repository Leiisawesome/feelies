# GROK MICROSTRUCTURE RESEARCH LAB — V2 ARCHITECTURE

## This document is NOT pasted into Grok. It is a reference for the PI.

---

## Why V1 Failed

V1 invented a second source of truth: a `PARITY_CONFIG` dict (spread-crossing fills, 70%
fill rate, seed=42, 100ms latency) and a `GrokParityBacktester` class conforming to it.
Neither Grok nor the local `GrokParityBacktester` ran the repo's actual pipeline.
Parity between two wrong implementations is still wrong.

The root cause: V1 guessed at repo behavior rather than executing repo code.

---

## V2 Governing Principle

**The `feelies` repo is the single source of truth.**

Grok executes the repo's actual Python code — 87 source files downloaded from GitHub
at session start. There is no reimplemented fill model, no reimplemented cost formula,
no reimplemented risk engine. One substitution is allowed and explicitly named.

---

## The One Allowed Substitution

```
REPO:  MassiveHistoricalIngestor  →  GROK:  PolygonFetcher
```

The local repo uses a `massive` SDK client (`MassiveHistoricalIngestor`) to pull
L1 NBBO data. Grok's sandbox cannot install that SDK. Instead Prompt 2 provides a
`PolygonFetcher` that calls the Polygon REST API directly and emits **identical**
`NBBOQuote` / `Trade` dataclasses — same field types, same nanosecond timestamps,
same resequencing logic.

Everything downstream (feature engine, signal engine, backtest router, cost model,
risk engine, orchestrator) runs from repo source unchanged.

---

## Session Flow

```
Prompt 1: Paste once at session start (downloads repo ZIP at pinned commit SHA,
                                       extracts BOTH src/feelies/ AND repo-root files
                                       — including platform.yaml — sets sys.path)
Prompt 2: Paste once to activate data layer (PolygonFetcher + RTH logic)
Prompt 3: Paste once to activate alpha development (schema, feature library, AlphaLoader)
Prompt 4: Paste once to activate backtest execution (build_platform, CPCV, IC, MHT,
                                                     SELFCHECK, three-hash parity)
Prompt 5: Paste once to activate export and lifecycle (registry, parity verify)
Prompt 6: Paste once to activate evolution (MUTATE, EXPLORE, EVOLVE, LINEAGE)

After setup, the PI issues commands:
  INITIALIZE                       → set API key, bootstrap workspace dirs
  LOAD "AAPL" "2026-01-15"         → fetch RTH data, populate InMemoryEventLog
  TEST <hypothesis>                → run directed hypothesis test (7 steps)
  BACKTEST <alpha_id>              → run full backtest via build_platform()
  SELFCHECK <alpha_id>             → assert Inv-5 (deterministic replay) on this alpha
  MUTATE <parent_spec> <op>        → produce one typed, deterministic child (unary)
  RECOMBINE <a_spec> <b_spec>      → binary splice (union features/params, signal from one)
  EXPLORE <parent_spec> n=8        → Holm-corrected family of mutated siblings
  EVOLVE <seed_spec> n_generations → multi-generation hypothesis → mutation → selection loop
  AUDIT <signal_id>                → post-promotion CPCV+IC re-run; stamp audit_status in registry
  LINEAGE <signal_id>              → walk the registry's parent_id chain + IC stability summary
  EXPORT <signal_id>               → produce .alpha.yaml + .py + parity_fingerprint.json
  VERIFY <signal_id> <pnl_hash>    → compare Grok vs scripts/run_backtest.py (3-hash contract)
                <config_hash>
```

---

## Parity Contract (V3 — three-hash)

Running the same `.alpha.yaml` on the same date range through:

- **Grok REPL** (Prompt 4's `build_platform()` pipeline, config loaded from
  the platform.yaml that Prompt 1 extracted from the pinned ZIP)
- **Local repo** (`python scripts/run_backtest.py --config platform.yaml ...`)

must produce three identical hashes:

| Hash | Definition | What it locks down |
|------|------------|--------------------|
| `pnl_hash`    | `SHA256(JSON([{order_id, symbol, side, quantity, fill_price, realized_pnl}]))` ordered by sequence | Trade-by-trade fill outcome |
| `config_hash` | `PlatformConfig.snapshot().checksum` | Every dataclass field used by `build_platform()` |
| `parity_hash` | `SHA256(pnl_hash + ":" + config_hash)` | Single rollup of trades **and** config |

Verdicts produced by `VERIFY()`:

- `PARITY_VERIFIED` — both hashes match
- `PARITY_VERIFIED_TRADES_ONLY` — `pnl_hash` matches, `config_hash` differs (or local
  hash not supplied) → trade sequence is reproduced but the `platform.yaml` differs;
  treat as warning, not pass
- `PARITY_FAILED` — `pnl_hash` differs → defect; investigate before any deployment

Any divergence is a defect. The only permitted divergence source is the data layer
substitution (e.g., minor timestamp field differences between `sip_timestamp` and
`participant_timestamp`).

---

## File Map

| File | Role | Paste into Grok? |
|------|------|-----------------|
| `00_ARCHITECTURE.md` | This document — PI reference | No |
| `01_BOOTSTRAP.md` | Prompt 1: source + platform.yaml download, system identity, registry schema | Yes (first) |
| `02_DATA_INGESTION.md` | Prompt 2: Polygon RTH fetcher (the one allowed substitution) | Yes (second) |
| `03_ALPHA_DEVELOPMENT.md` | Prompt 3: `.alpha.yaml`, FEATURE_LIBRARY, MECHANISM_CATALOG, hypothesis formalization | Yes (third) |
| `04_BACKTEST_EXECUTION.md` | Prompt 4: `build_platform`, CPCV, IC, Holm/BH, SELFCHECK, three-hash parity, TEST | Yes (fourth) |
| `05_EXPORT_LIFECYCLE.md` | Prompt 5: EXPORT, VERIFY (three-hash), registry upsert, lifecycle | Yes (fifth) |
| `06_EVOLUTION.md` | Prompt 6: MUTATION_OPERATORS, MUTATE, EXPLORE (Holm family), EVOLVE, LINEAGE | Yes (sixth) |

---

## What Was Removed vs V1

| V1 Element | Reason Removed |
|---|---|
| `PARITY_CONFIG` dict | Invented constants not in repo |
| `ParityBacktester` class | Wrong fill model (spread-crossing, 70% fill probability) |
| `GrokParityBacktester` local harness | Repo's `scripts/run_backtest.py` is the verifier |
| Phase A / Phase B Prompt 7 | No separate harness needed |
| Custom HMM Python code | Imported from `HMM3StateFractional` source |
| 87 individual GitHub file fetches | Replaced with single ZIP download |

## What Was Preserved from V1

| V1 Element | Reason Preserved |
|---|---|
| `.alpha.yaml` schema + AlphaLoader validation | Was correct — these match repo source |
| Feature/signal protocols (`initial_state`, `update`, `evaluate`) | Was correct |
| Feature library (6 reusable modules) | Was correct |
| Mechanism catalog (10 entries) | Research guidance, independent of fill model |
| Statistical validation (CPCV, DSR, bootstrap, IC) | Research-layer logic, correct |
| Signal registry, lifecycle states, artifact storage | Was correct |
| Hypothesis formalization workflow | Was correct |
