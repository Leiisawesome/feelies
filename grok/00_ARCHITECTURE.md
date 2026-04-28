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

Everything downstream (sensor registry, horizon aggregation, signal engine,
composition, execution, risk, and orchestrator) runs from repo source unchanged.

In current-main terms, the live downstream path is:

```
sensor -> horizon -> signal -> composition -> execution/risk/orchestrator
```

---

## Session Flow

```
Prompt 1: Paste once at session start (downloads repo ZIP at pinned commit SHA,
                                       extracts BOTH src/feelies/ AND repo-root files
                                       — including platform.yaml — sets sys.path)
Prompt 2: Paste once to activate data layer (PolygonFetcher + RTH logic)
Prompt 3: Paste once to activate alpha development (schema-1.1 SIGNAL builder,
                                                    reference-alpha cloning,
                                                    sensor catalog, AlphaLoader)
Prompt 4: Paste once to activate backtest execution (build_platform, CPCV, IC, MHT,
                                                     SELFCHECK, three-hash parity,
                                                     layer-aware metadata)
Prompt 5: Paste once to activate export and lifecycle (registry, parity verify,
                                                       metadata-aware export)
Prompt 6: Paste once to activate evolution (schema-safe MUTATE, RECOMBINE,
                                            EXPLORE, EVOLVE, LINEAGE)
Prompt 7: Paste once to activate hypothesis reasoning (embedded protocol,
                                                       proposal gates, axis mapping)

After setup, the PI issues commands:
  INITIALIZE                       → set API key, bootstrap workspace dirs
  LOAD "AAPL" "2026-01-15"         → fetch RTH data, populate InMemoryEventLog
  LIST_SENSORS                       → show the shipped Layer-1 sensor catalog
  DESCRIBE_SENSOR_RULES              → print embedded sensor binding, fingerprint,
                                       and half-life rules from Prompt 3
  TEST <hypothesis>                → run directed hypothesis test (7 steps)
  BACKTEST <alpha_id>              → run full backtest (explicit-spec ingress)
  RUN_ACTIVE                       → backtest the currently ADOPTed alpha via the
                                     production discovery path (alpha_spec_dir)
  SELFCHECK <alpha_id>             → assert Inv-5 (deterministic replay) on this alpha
  SELFCHECK_ADOPTION <spec_path>   → assert explicit-spec ≡ alpha_spec_dir ingress
                                     (Grok ↔ scripts/run_backtest.py path equivalence)
  PROPOSE <template_alpha_id>      → clone a shipped reference alpha and apply bounded
                                     hypothesis-driven edits before validation
  SHOW_PROTOCOL_OVERVIEW           → print the embedded generation contract from Prompt 7
  SHOW_OUTPUT_CONTRACT_EXAMPLES    → print generation/mutation REPL output templates
  MUTATE_BY_AXIS <parent_spec> <n> → dispatch the normative mutation axes onto Prompt 6
  SHOW_MUTATION_PROTOCOL           → print the embedded mutation trigger/axis/checklist rules
  MUTATE <parent_spec> <op>        → produce one typed, deterministic child (auto-ADOPTs)
  RECOMBINE <a_spec> <b_spec>      → binary splice (auto-ADOPTs the validated child)
  EXPLORE <parent_spec> n=8        → Holm-corrected family of mutated siblings
  EVOLVE <seed_spec> n_generations → multi-generation loop (auto-ADOPTs each champion)
  ADOPT <spec> <source='manual'>   → write spec to ALPHA_ACTIVE_DIR/<id>/<id>.alpha.yaml
                                     and flip SESSION["active_alpha_id"] (the platform's
                                     view of "which alpha is live")
  LIST_ACTIVE                      → show currently adopted alpha + adoption history
  AUDIT <signal_id>                → post-promotion CPCV+IC re-run; stamp audit_status in registry
  LINEAGE <signal_id>              → walk the registry's parent_id chain + IC stability summary
  EXPORT <signal_id>               → produce .alpha.yaml + .py + parity_fingerprint.json
                                     (also auto-ADOPTs the exported alpha as the live spec
                                     when Prompt 6 is loaded; warns and continues otherwise)
  VERIFY <signal_id> <pnl_hash>    → compare Grok vs scripts/run_backtest.py (3-hash contract)
                <config_hash>
```

---

## PI Workflow (paste order + success signals)

The prompts are pasted once each, in numeric order, into a single Grok REPL
session. After each paste, wait for the listed sentinel string in Grok's
output before pasting the next file. If a cell fails, fix the error before
continuing — every later prompt depends on symbols defined earlier.

| Step | Action                       | Sentinel to wait for                  |
|------|------------------------------|---------------------------------------|
| 1    | Paste `01_BOOTSTRAP.md`      | `SOURCE BOOTSTRAP: OK`                |
| 2    | Paste `02_DATA_INGESTION.md` | `Data Ingestion module: ACTIVE`       |
| 3    | Paste `03_ALPHA_DEVELOPMENT.md` | `Alpha Development module: ACTIVE` |
| 4    | Paste `04_BACKTEST_EXECUTION.md` | `Backtest Execution module: ACTIVE` |
| 5    | Paste `05_EXPORT_LIFECYCLE.md` | `Export & Lifecycle module: ACTIVE` |
| 6    | Paste `06_EVOLUTION.md`      | `Evolution module: ACTIVE`            |
| 7    | Paste `07_HYPOTHESIS_REASONING.md` | `Hypothesis Reasoning Module: ACTIVE` |
| 8    | Call `INITIALIZE("<polygon_api_key>")` | All 7 modules report `ACTIVE` |

Cell 1 of Prompt 1 fetches a ~3 MB ZIP over HTTPS; expect 10–30 seconds.
`RUN_ACTIVE()` and `SELFCHECK_ADOPTION()` from Prompt 4 require Prompt 6 to
be pasted (they call `ADOPT`, defined in Prompt 6). Prompt 7 assumes Prompts 3
and 6 are already loaded because it wraps `clone_reference_alpha()`,
`validate_alpha()`, and `MUTATE()`.

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

## Adoption Flow (autonomy ↔ production-discovery handoff)

**Goal.** Make a freshly generated or mutated alpha *live to the platform* without
manual file copying — so the next backtest exercises the same `alpha_spec_dir`
discovery code path `scripts/run_backtest.py` uses with `platform.yaml`.

```
┌─────────────────┐   validated   ┌─────────────────────────────┐   discovery    ┌──────────────────┐
│ MUTATE / RECOMB │ ───────────► │ ADOPT(spec) writes:          │ ─────────────► │ build_platform() │
│ EXPLORE / EVOLVE│   spec dict   │ ALPHA_ACTIVE_DIR/<id>/<id>   │  via           │ scans alpha_spec │
│ EXPORT          │              │     .alpha.yaml              │  alpha_spec_   │ _dir, registers  │
└─────────────────┘              │ + optional <id>/<dep>/<dep>  │  dir = above   │ via AlphaLoader  │
                                  │     .alpha.yaml sidecars     │                │                  │
                                  │ + SESSION["active_alpha_id"] │                │                  │
                                  └─────────────────────────────┘                └──────────────────┘
                                                                                          │
                                  ┌─────────────────────────────┐                         ▼
                                  │ RUN_ACTIVE() runs the        │ ◄─────── identical hashes to ───────
                                  │ backtest via this path       │          BACKTEST(spec_path) — proven
                                  └─────────────────────────────┘          by SELFCHECK_ADOPTION
```

**Auto-adoption policy.** Every validated `MUTATE` / `RECOMBINE` child and every
`EVOLVE` strict-improvement winner flips the live spec automatically. `EXPORT`
also re-adopts so the post-export world is observable. Manual `ADOPT(spec)` is
available for hand-crafted specs.

**One live bundle.** `ALPHA_ACTIVE_DIR` holds exactly one adopted alpha subtree
at a time (atomic swap on every `ADOPT`). The subtree may include one-level
nested dependency SIGNAL specs for a live PORTFOLIO alpha, but only one
primary adopted root is live in production at any moment. Lineage lives in
`WORKSPACE["alphas"]` (the dev tree) and the registry — never here.

**Equivalence proof.** The local platform's `bootstrap._load_alphas` has two
ingress branches: explicit-spec (`alpha_specs=[...]`, used by Grok's
`TEST`/`EXPLORE`/`EVOLVE`) and directory-scan (`alpha_spec_dir`, used by
production and `RUN_ACTIVE`). They *should* produce identical results because
both end at `AlphaLoader.load()`, but "should" is not "verified".
`SELFCHECK_ADOPTION(spec_path)` asserts bit-identical `pnl_hash` + `config_hash`
across both ingresses. Run it once after any change to `_load_platform_config`
or to `bootstrap._load_alphas`.

---

## File Map

| File | Role | Paste into Grok? |
|------|------|-----------------|
| `00_ARCHITECTURE.md` | This document — PI reference | No |
| `01_BOOTSTRAP.md` | Prompt 1: source + platform.yaml download, system identity, registry schema | Yes (first) |
| `02_DATA_INGESTION.md` | Prompt 2: Polygon RTH fetcher (the one allowed substitution) | Yes (second) |
| `03_ALPHA_DEVELOPMENT.md` | Prompt 3: schema-1.1 SIGNAL assembly, reference-alpha cloning, sensor catalog, mechanism family catalog | Yes (third) |
| `04_BACKTEST_EXECUTION.md` | Prompt 4: `build_platform`, CPCV, IC, Holm/BH, SELFCHECK, three-hash parity, TEST, metadata | Yes (fourth) |
| `05_EXPORT_LIFECYCLE.md` | Prompt 5: EXPORT, VERIFY (three-hash), registry upsert, lifecycle, metadata carry-through | Yes (fifth) |
| `06_EVOLUTION.md` | Prompt 6: schema-safe mutation operators, RECOMBINE, EXPLORE (Holm family), EVOLVE, LINEAGE | Yes (sixth) |
| `07_HYPOTHESIS_REASONING.md` | Prompt 7: embedded reasoning contract with proposal audit and mutation-axis mapping | Yes (seventh) |

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
| Reference-alpha-first development flow | Better anchor than inventing specs from scratch |
| Mechanism-family catalog | Research guidance, independent of fill model |
| Statistical validation (CPCV, DSR, bootstrap, IC) | Research-layer logic, correct |
| Signal registry, lifecycle states, artifact storage | Was correct |
| Hypothesis formalization workflow | Was correct |
