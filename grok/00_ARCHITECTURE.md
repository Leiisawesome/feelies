# MASTER PROMPT SYSTEM — REVISION ARCHITECTURE

## What Changed and Why

### The Core Problem with the Draft Prompts

The draft prompts (1-7) built a capable research lab inside Grok REPL,
but the alphas it produced were in a **Grok-native format** — Python
dicts, ad-hoc signal functions, custom backtest loops. These could not
be directly loaded by the feelies platform without manual translation.

The translation step introduces errors. Errors destroy parity.

### The Core Insight of This Revision

**Grok REPL must output alphas in feelies-native `.alpha.yaml` format.**

The `.alpha.yaml` schema is the canonical contract between discovery
(Grok REPL) and deployment (feelies). If Grok produces a valid
`.alpha.yaml` file, feelies' `AlphaLoader` will parse it, compile it,
validate it, and execute it — identically.

This means every prompt must be aware of:

1. **The `.alpha.yaml` schema** — field names, types, constraints
2. **The feature computation protocol** — `initial_state()`, `update(quote, state, params)`
3. **The signal evaluation protocol** — `evaluate(features, params)` → `Signal | None`
4. **The NBBOQuote interface** — `quote.bid`, `quote.ask` (Decimal), `quote.bid_size`, `quote.ask_size` (int)
5. **The regime engine** — HMM3StateFractional with states: compression_clustering, normal, vol_breakout
6. **The parity backtest config** — spread-crossing fills, 70% fill probability, 100ms latency

### What Changed Per Prompt

| Prompt | Draft Status | Revision |
|--------|-------------|----------|
| **1 — Governance** | Generic lab rules | Added `.alpha.yaml` as CANONICAL output format. Added NBBOQuote field mapping. Added feelies AlphaLoader compatibility as a hard constraint. |
| **2 — Data** | OK but disconnected from feelies data layer | Aligned cache format. Added Massive (Polygon) REST/WS field mapping matching `MassiveNormalizer`. |
| **3 — Market State** | Custom HMM, different state names | **Rewired** to match `HMM3StateFractional` exactly: 3 states (compression_clustering, normal, vol_breakout), log-spread emission model, Bayesian posterior updates. |
| **4 — Alpha Factory** | Feature graphs → ad-hoc Python | **Rewired** to output `.alpha.yaml` specs. Feature computation code uses `initial_state()`/`update()` protocol. Signal code uses `evaluate(features, params)` protocol. |
| **5 — Hypothesis Testing** | Good pipeline, custom output | Added parity backtest as Step 13. Report now includes `.alpha.yaml` export. |
| **6 — Portfolio/Risk/Archive** | Good architecture | Aligned lifecycle states with feelies: RESEARCH→PAPER→LIVE→QUARANTINED→DECOMMISSIONED. Risk budget matches `AlphaRiskBudget` schema. |
| **7 — Parity Bridge** | Standalone, weakly connected | Integrated into Prompts 4-6. Canonical backtest parameters locked. Export produces feelies-loadable files. |

### The Copy-Paste Contract

After this revision, the workflow is:

```
Grok REPL                           feelies local repo
─────────                           ──────────────────
1. Discover alpha                   
2. TEST hypothesis                  
3. EXPORT signal_id                 
   ↓                                
   alpha_spec.alpha.yaml    ──────→  alphas/my_alpha/my_alpha.alpha.yaml
   feature_module.py        ──────→  alphas/my_alpha/feature_module.py
   parity_fingerprint.json  ──────→  (verification)
                                     
                                    4. python scripts/run_parity_backtest.py
                                    5. VERIFY pnl_hash matches
                                    6. feelies paper → live pipeline
```

No translation step. No manual rewriting. Copy the files, run the test.

### Prompt Execution Order (unchanged)

```
Prompt 1 → 2 → 3 → 4 → 5 → 6 → 7
```

Each prompt activates one module and declares dependencies on prior modules.
