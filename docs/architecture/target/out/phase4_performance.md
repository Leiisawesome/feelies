# Phase 4 — Axis E: Performance and efficiency

**Deliverable E2.** Consumes `phase1_plumbing.md` (determinism substrate),
`phase2_contracts.md` (latency class per engine), `phase3_flow_gating.md`
(hop-by-hop path). Governed by `00_CORE.md` v1.1.

**The result:** the tick-critical path costs a measured **136.2 µs per quote**
(42.2 µs per event), **4.2× the platform's own declared 10 µs/event target**
(`.cursor/skills/performance-engineering/SKILL.md:93`) and inside its 100 µs
"acceptable" bound. Three findings, in descending order of consequence:

1. **That 136.2 µs is the best case the repo can produce, not a typical one.**
   The workload registers 4 of 15 declared sensors because
   `prune_unused_sensors: true` intersects them with one alpha's dependencies.
   Registering all of them — measured, not projected — costs **335.3 µs/quote,
   2.54×, at 22.6 µs per added sensor**, with the parity hash and fill count
   unchanged. That is 103.9 µs/event, which breaches the platform's own
   *acceptable* bound of 100 µs, not just its target. One additional sensor
   consumes 70% of the entire per-quote budget, making engine 2's per-sensor cost
   the binding constraint on how many alphas the platform can carry.
2. **~12.8 µs/quote (9.4%) is provably unread** — work whose output no
   production consumer reads, led by 7.2 µs/quote publishing `StateTransition`
   events to zero subscribers, at 8.007 publishes per quote. 58.7% of all bus
   publishes have no subscriber.
3. **There is no budget in the code.** No branch anywhere in `src/feelies`
   compares a measured latency to a threshold, so breach behaviour is undefined
   rather than fail-safe. CORE §F.6's "differ only in observability" requirement
   holds vacuously, and the one observed 16 ms tick passed unremarked.

The allow list is authored against the measured path: of the 13 unconditional
per-event hits on prohibited categories, **9 sit in `kernel/` or `core/`** rather
than in an engine — the tick path's own scaffolding is the main violator.

---

## 0. Measurement basis

Every number below is produced by a committed script and re-derivable. Nothing
in this document is estimated unless the row says `TARGET` or `PROJECTED`.

| Tool | Evidence file | What it measures |
|---|---|---|
| `tools/arch/perfmeasure.py --mode both` | `tools/arch/evidence/perf.json` | Per-probe inclusive/exclusive ns under replay, probed vs unprobed, calibrated |
| `tools/arch/perfmeasure.py --mode scale` | `tools/arch/evidence/perf_scale.json` | Same at N=1 and N=8 symbols |
| `tools/arch/perfmeasure.py --mode sensorscale` | `tools/arch/evidence/perf_sensorscale.json` | Tick cost at the pruned sensor count vs all 15 declared, with parity check |
| `tools/arch/perfmeasure.py --mode census` | `tools/arch/evidence/perf_census.json` | Publish counts by type with live subscriber counts; metric names actually recorded |
| `tools/arch/perfmeasure.py --mode profile` | `tools/arch/evidence/hotpath_executed.json` | Every function executed inside `run_backtest`, with call counts |
| `tools/arch/hotpath.py` | `tools/arch/evidence/hotpath.json` | Static prohibition scan ∩ dynamic hot set; guard-aware; dead-compute census |
| `tools/arch/microcost.py` | `tools/arch/evidence/microcost.json` | Unit cost of each primitive the findings rest on |
| — (written by `--mode both`) | `tools/arch/evidence/perf_report_tail.txt` | Raw CLI report from the last unprobed run, kept so the platform's own numbers are auditable next to the probe's |

**Workload.** `configs/bt_app.yaml`, APP, 2026-03-26 — the parity oracle
(`AGENTS.md`). 266,754 events, of which 82,678 (31.0%) are `NBBOQuote`. Scaling
uses 2026-04-22, N=1 vs N=8.

**One property of this workload governs how far its numbers generalise.**
`platform.yaml` declares 15 sensors, 13 of which subscribe to `NBBOQuote`, but
`configs/bt_sig_benign_midcap.yaml:21` sets `prune_unused_sensors: true`, and the
single loaded alpha declares four dependencies —
`['ofi_ewma', 'book_imbalance', 'spread_z_30d', 'realized_vol_30s']`
(`alphas/sig_benign_midcap_v1/sig_benign_midcap_v1.alpha.yaml`). Exactly four
sensor probes fire, each at 1.000 calls/quote, and `SensorReading` is published
3.997 times per quote. VERIFIED. **So every engine-2 number below is measured at
S=4, not at the 13 the platform can register**, and pruning weakens precisely as
alphas accumulate — the axis CORE §A says the design must be authored to. §2.5
measures the difference rather than leaving it a footnote.

**Host and conditions.** Python 3.12.13, Windows-11-10.0.26200,
Intel64 Family 6 Model 197. Replay runs with GC disabled and
`HIGH_PRIORITY_CLASS`, because `feelies.harness.backtest_runner` sets both
around `orchestrator.run_backtest()` — these are the harness's conditions, not a
bare interpreter's. VERIFIED.

**Run-to-run spread.** Three consecutive unprobed runs in one session:
130,475 / 131,893 / 130,715 ns/quote. Three in another: 138,702 / 136,207 /
136,168. Within-session spread is ±1%, between-session ±3%. **No conclusion in
this document rests on a difference smaller than 5%.**

**Probe accounting.** Probes are wrappers around 66 resolved call sites. Raw
probed cost is 213,511 ns/quote — 56.8% overhead — so raw per-probe numbers are
useless as budget inputs. The wrapper cost lands in the *parent's* exclusive
time, not the child's, so it is calibrated as 909 ns per nested probe call over
85.1 nested calls/quote and subtracted from each probe by its own child-call
count. Corrected total: **136,167 ns/quote against an unprobed 136,168** — a
1 ns residual on a 136 µs measurement. That agreement is the calibration's only
claim to validity, and it is the reason the corrected column is used throughout.
VERIFIED (`tools/arch/evidence/perf.json:derived`).

**Determinism of the instrument.** The probed run and all unprobed runs produce
`parity_hash = 0601295a20b5…`, identical. Instrumenting 66 call sites and adding
56.8% wall-clock cost does not move one bit of output. VERIFIED — this is the §5
exclusion proof, measured rather than argued.

**Labels.** VERIFIED = read the code or measured it. INFERRED = derived from
something verified. ASSUMED = not checkable here; goes to the register.

---

## 1. Hot-path allow list

The tick-critical path is engines 1, 2, 3, 4, 6, 7, 8, 9, 10 (CORE §D). This
section is a closed list: **an operation not named as permitted is prohibited
there.**

### 1.1 Permitted

| # | Permitted operation | Why it is permitted |
|---|---|---|
| A1 | Attribute reads and writes on `__slots__` objects | The representation the engines' state is already in |
| A2 | Arithmetic on `int`, `float`, and `Decimal` | Money is `Decimal` end to end; that is what makes P&L reductions order-free (Phase 1, determinism budget row 4). Costed at 71.7 ns for a hoisted-divisor `Decimal` divide |
| A3 | `dict` / `list` / `deque` **lookup, append, and in-place mutation** on a container allocated at construction | O(1), no allocation |
| A4 | Construction of exactly one declared output event per emission | The contract boundary itself. Costed: 1,241.6 ns for a 19-field frozen event |
| A5 | Comparison of an event timestamp against a stored event timestamp | Staleness and causality gating (Inv-2). Distinct from P11: the operand is event time, never wall clock |
| A6 | Bounded-K numeric kernels declared in the engine contract | Sensor and regime math. `math.sqrt`/`exp`/`log` permitted where K is a compile-time constant |
| A7 | Counter increment on a pre-allocated metric slot | The kill-switch and health inputs must be readable per event (CORE §E.11). Increment only — **not** name construction, not aggregation |
| A8 | Raising a typed exception | Fail-closed boundary rejection (Inv-9) |

### 1.2 Prohibited, with measured violation status

`hotpath.json` intersects a static AST scan of `src/feelies` with the set of
functions **proven to execute** inside `run_backtest`, then splits each hit by
control flow. `unconditional` means the statement is reached on every entry to
its function — no `if`, no `try`, no loop guard. `per_event` means the enclosing
function was measured at ≥ 0.5 calls per quote. A hit that is both is a cost
paid on essentially every tick; that is the only class strong enough to call a
violation without further work, and it is the column below.

| # | Prohibition | Unconditional per-event hits | Verdict |
|---|---|---|---|
| P1 | Logging with formatting | **0** (11 guarded) | **Clean on the measured path.** All 11 per-event-rate sites sit behind a level check or an error branch — e.g. `src/feelies/features/aggregator.py:301`, `src/feelies/sensors/registry.py:325`. VERIFIED |
| P2 | Per-event `dict` construction | **3** | **VIOLATED.** `src/feelies/portfolio/memory_position_store.py:160` (1.002/q), `src/feelies/kernel/orchestrator.py:1525` (1.000/q), `src/feelies/kernel/orchestrator.py:2128` (1.000/q) |
| P3 | Per-event `set`/`frozenset` construction | **2** | **VIOLATED.** `src/feelies/core/state_machine.py:159` at **8.007/q** — the `.get(state, frozenset())` default, allocated to be discarded; `src/feelies/kernel/orchestrator.py:2127` (1.000/q) |
| P4 | Dynamic dispatch through a registry or `getattr` | **2** | **VIOLATED.** `src/feelies/alpha/risk_wrapper.py:329` (1.000/q), `src/feelies/kernel/orchestrator.py:2128` (1.000/q). Eight further sites are guarded |
| P5 | Governance evaluation | **0** | **Clean.** No `promotion/` or lifecycle symbol appears in the executed set. Inv-10 holds on the measured path. VERIFIED |
| P6 | Disk I/O | **0** | **Clean.** 58 sites, every one cold. VERIFIED |
| P7 | Serialization (`json`, `pickle`, `repr` of a structure) | **0** unconditional (2 hot functions) | **Clean at per-event rate.** VERIFIED |
| P8 | String formatting — f-string, `%`, `.format`, `str.join` | **3** | **VIOLATED.** `src/feelies/core/identifiers.py:15` at **4.078/q** (`make_correlation_id`), `src/feelies/sensors/registry.py:333` at 3.997/q, `src/feelies/monitoring/in_memory.py:74` at 3.042/q (metric key). 57.9 ns each measured |
| P9 | `dataclasses.replace` | **0** (5 guarded) | **Clean at per-event rate.** The 5 guarded sites are order-state transitions, correctly rare. VERIFIED |
| P10 | `copy.copy` / `copy.deepcopy` | **0** | **Clean.** One site, cold. VERIFIED |
| P11 | Wall-clock read | **3** (+2 guarded at 8.007/q) | **Not violated in substance.** All 6 hits are the timing instrument, permitted under §5; no read reaches an event payload. But enforcement is file-granular, so this is clean by inspection, not by test. See §1.3 |
| P12 | Regex | **0** | **Clean.** VERIFIED |
| P13 | Sorting | **0** (4 guarded) | **Clean at per-event rate.** `src/feelies/features/aggregator.py:283`/`:289`/`:309` are boundary-only. VERIFIED |
| P14 | Unbounded iteration over a collection that grows with universe or session length | **see §2.4** | **VIOLATED** — not detectable by AST scan; established by scaling measurement instead |

**Two prohibitions are explicitly lifted** (A2, A6), and the scanner records
them as `allowed` so the count is not mistaken for a clean bill: `Decimal`
construction has 3 unconditional per-event hits (`src/feelies/risk/basic_risk.py:761-763`)
and transcendental math has 1 (`src/feelies/services/regime_engine.py:380`, 3.000/q). Both
are permitted by the list above. The `src/feelies/services/regime_engine.py:380` site is nonetheless
a §6 removal candidate for a different reason — its *result* is unread.

**Where the violations live.** 13 unconditional per-event hits fall on prohibited
categories, and **9 of them are in `kernel/` or `core/`**: `src/feelies/kernel/orchestrator.py`
accounts for 7 (lines 1524, 1525, 2104, 2127, 2128 twice, 3940) and `core/` for 2
(`src/feelies/core/state_machine.py:159`, `src/feelies/core/identifiers.py:15`). Only 4 are in an engine —
`src/feelies/alpha/risk_wrapper.py:329`, `src/feelies/portfolio/memory_position_store.py:160`,
`src/feelies/sensors/registry.py:333`, `src/feelies/monitoring/in_memory.py:74`. The engines are
comparatively disciplined; the scaffolding that carries every tick is not.

Discount the 3 `src/feelies/kernel/orchestrator.py` wall-clock reads as instrument (§1.3) and 10
substantive hits remain, 6 of them in those two packages. Either way the shape
holds: this is a handful of edits in `kernel/` and `core/`, not a campaign across
the engine set.

### 1.3 Every hot wall-clock read is the instrument, which is the finding

P11's hits need separating, because the substance is not what the category name
suggests. All six are telemetry:

- `src/feelies/kernel/orchestrator.py:1524`, `:2104`, `:3940` are the tick timers.
- `src/feelies/core/state_machine.py:180` and `:198` bracket `StateMachine.transition` to
  populate the timing sink, and both are guarded on
  `sink is not None and key is not None`.

**None of them reaches an event payload.** `TransitionRecord.timestamp_ns` is set
from `self._clock.now_ns()` at `src/feelies/core/state_machine.py:187` — the injected clock,
which is the correct design and not a P11 hit at all. Phase 1 reached the same
conclusion from the other direction, classifying these as "telemetry-only raw
reads confined to an allowlist" (determinism budget row 7). So P11 is **not
violated in substance**: it is fully accounted for by the measurement instrument,
which §5 permits.

Two consequences follow, and they are the reason this section exists rather than
simply marking P11 clean:

1. **The guard cannot tell an instrument from a violation.** Phase 1's row 7 gap
   is that `tests/acceptance/test_no_walltime_outside_clock.py:83` skips whole
   files, and `src/feelies/kernel/orchestrator.py` is allowlisted for exactly this telemetry.
   A `datetime.now()` added anywhere in those 4,778 lines passes. P11 is clean
   today by inspection, not by enforcement.
2. **The instrument's own choice of clock is what §4.3 turns on.** These reads
   cost 48.1 ns each and are wall clock, not CPU time, which is why the observed
   16 ms maximum cannot be attributed to compute rather than preemption.

---

## 2. Per-engine per-event budget

### 2.1 Deriving the total

The platform declares two numbers. End-to-end tick-to-decision budget: < 3 ms
non-boundary, < 8 ms boundary, hard ceiling < 10 ms / < 25 ms
(`.cursor/skills/performance-engineering/SKILL.md:81`). Replay throughput:
< 10 µs per event target, < 100 µs acceptable (`:93`).

Measured against both, using the platform's own instrument
(`tick_to_decision_latency_ns`, emitted at M10 for every tick from
`src/feelies/kernel/orchestrator.py:2120`) and the CLI report:

| Declared | Measured | Verdict |
|---|---|---|
| Tick-to-decision p99 < 3 ms | **0.432 ms** | Inside, 7× margin |
| Tick-to-decision hard ceiling < 10 ms / < 25 ms boundary | **16.000 ms max**, at APP tick #44937 @ 12:00:00.276 ET | Inside the 25 ms boundary ceiling — 12:00:00 is a boundary for every horizon in the canonical set. Not a breach; see §4.3 for why the number is still not trustworthy |
| Single event processing < 10 µs, acceptable < 100 µs | **42.2 µs/event** at S=4; **103.9 µs/event** at full sensor registration (§2.5) | **Target missed by 4.2×** as shipped, and the *acceptable* bound is breached at full registration |
| Sensor fan-out segment < 500 µs, ceiling < 2 ms (`SKILL.md:72`) | ~74 µs at S=4; ~277 µs at S=13 | Inside — see the note below on why this is not reassuring |
| Full-day replay, 1 ticker < 30 s | **11.26 s** | Inside |
| Full-day replay, 100 tickers < 10 min | **3.6 min** PROJECTED from the N=8 per-event cost, unprobed-equivalent | Inside |

**The declared budgets are mutually inconsistent, which is why one had to be
chosen rather than simply applied.** The per-segment table allows sensor fan-out
500 µs and the whole tick 3 ms, while the replay table asks for 10 µs per event.
A tick that spent its full 500 µs sensor allowance would miss the 10 µs/event
target by 50× and still be reported as inside budget. The two tables measure
different things — a p99 tick segment versus a mean per event — but nothing
reconciles them, so "the budget" is ambiguous as declared. That ambiguity is a
finding in its own right: the per-segment numbers are loose enough to be
unfalsifiable, which is why §2.2 is not built on them.

So live latency is not the binding constraint, and replay wall-clock is not
either. **The binding declared constraint is the 10 µs/event target** — the
tightest of the declared numbers and the only one the platform fails as shipped.
It is therefore what the budget is set to.

Scaling 136,168 ns/quote by 10/42.204 gives **32 µs per quote-tick** as the
total budget. This is a derivation from a number the platform already committed
to, not a new invention.

### 2.2 The allocation

Allocated to irreducible work at the target scale (N alphas, N symbols), not
pro-rata to current cost — the point of a budget is to be a constraint. `TARGET`
in the budget column; `measured` is corrected exclusive ns/quote from
`perf.json`.

| Engine | Budget µs/q (TARGET) | Measured µs/q | Ratio | Complexity per event | What makes it that class |
|---|---|---|---|---|---|
| 1 Market Data | 1.0 | **0.92** | 0.9× | O(1) | Fixed-field validation, append, three gate reads. No collection scan |
| 2 State / Feature | 12.0 | **73.55** | **6.1× over** | O(S·H) | **S=4 surviving sensors** × H horizon buckets — see §2.5. Largest single probe in the system: `HorizonAggregator._on_sensor_reading` at 3.997/q and **32.1 µs/q alone**, i.e. 8.0 µs per reading |
| 3 Regime | 4.0 | **15.47** | **3.9× over** | O(K²) | K=3 states; K(K−1)/2 pairwise separations per quote (`src/feelies/services/regime_engine.py:380`, 3.000/q) plus O(K) posterior |
| 4 Alpha | 3.0 | **2.86** | 0.95× | O(A) at boundary | A alphas × gate AST eval. Currently A=1; the budget is sized for growth, the measurement is not evidence about A>1 |
| 6 Portfolio Construction | 2.0 | **1.35** | 0.7× | O(N log N) at boundary | Cross-sectional rank over N symbols. Measured at N=1, so the ranking term is untested — see §2.4 |
| 7 Portfolio Accounting | 2.0 | **2.12** | 1.06× | O(1) per fill, **O(P) per read** | `all_positions` copies the whole dict (`src/feelies/portfolio/memory_position_store.py:160`, 1.002/q, 49.0 ns at P=8) |
| 8 Risk & Capital | 2.0 | **4.16** | **2.1× over** | O(P) | Equity and exposure recomputed by scanning positions every quote (`src/feelies/risk/basic_risk.py:761-763`) |
| 9 Execution Decision | 0.5 | **0.02** | 0.04× | O(1) | Runs only on a signal — 0.001/q measured. Effectively unmeasured; the number is real but the sample is 61 events |
| 10 Execution Routing | 1.5 | **1.66** | 1.11× | O(R) | R resting orders reconciled per quote (`reconcile_resting`, 1.000/q) |
| 11 Observability (hot part only) | 0.5 | **2.13** | **4.3× over** | O(1) | Should be a counter increment (A7). Is `MetricCollector.record` at 3.042/q including an f-string key (`src/feelies/monitoring/in_memory.py:74`) |
| 12 Research / Forensics | 0.0 | **0.48** | **must be zero** | — | Shadow traces on the tick path: `X.net_shadow` 1.000/q, `X.arbitration_trace` 1.000/q. Cold engine, hot cost |
| Kernel (not an engine) | 3.5 | **29.09** | **8.3× over** | O(M) | M=8.007 state-machine transitions per quote, each constructing a `TransitionRecord` (475.1 ns) and publishing a `StateTransition` (§6.1) |
| Harness (not an engine) | 0.0 live | **2.35** | replay-only | O(1) | `BusRecorder` + `backtest_prep`. Correctly absent in live; included here so the 136.2 µs total reconciles |
| **Total** | **32.0** | **136.17** | **4.3× over** | | |

Sum of the measured column is 136,167 ns/quote against an unprobed 136,168 —
the attribution is complete, with nothing hiding in an unprobed gap.

### 2.3 Where the overage actually is

Three rows carry 87% of the excess: engine 2 (+61.6 µs), the kernel (+25.6 µs),
and engine 3 (+11.5 µs). Nine of the thirteen rows are already inside budget or
within 11% of it. **This is not a diffuse performance problem and a broad
optimisation campaign is the wrong response.** Of the kernel's 25.6 µs overage,
7.2 µs is provably unread work (§6.1) — deletion, not optimisation, is the
first move.

### 2.4 The complexity classes that are asserted, not measured

Four rows above claim a complexity class that the N=1 workload cannot
demonstrate. Scaling to N=8 is the only evidence available, and it is honest
about its own limits.

| Probe | N=1 ns/q | N=8 ns/q | Ratio | Reading |
|---|---|---|---|---|
| `HorizonAggregator._on_horizon_tick` | 8,286.0 | 16,235.0 | **1.96×** | Boundary work that iterates the universe. The only clearly super-constant term |
| `E7.position_get` | 413.9 | 650.2 | **1.57×** | O(P) position-store access |
| `E2.horizon_scheduler` | 12,848.7 | 16,319.5 | 1.27× | Per-symbol boundary state |
| `bus:SensorReading->aggregator` | 28,264.9 | 31,272.7 | 1.11× | Cache pressure, not algorithmic |
| **Whole replay, per quote** | **197,410** | **214,365** | **1.086×** | |

Per-quote cost rises **8.6% for an 8× universe**. The platform is not
quadratic in symbol count at N=8. Two caveats, both material: per-event cost
rose 1.312× over the same step, but the N=8 symbol set has 46,736 events/symbol
against APP's 126,775, so that ratio confounds event-mix with scaling and the
per-quote figure is the cleaner one. And N=8 is far from the N=100 the design
must serve — the 1.96× row is the one that would dominate there, and it is
untested above 8.

**Two O(N) scans are in the code but not currently on the per-quote path**, and
they are the mechanism by which the 1.96× row would worsen:
`RegimeStateCache.latest` iterates every `(symbol, engine)` entry on each call
(`src/feelies/services/regime_state_cache.py:82-91`) and `HorizonSignalEngine` repeats the
pattern (`src/feelies/signals/horizon_engine.py:668`). Measured at 0.001 calls/quote, so
they cost nothing today — they are called per signal, not per quote. The
docstring at `src/feelies/services/regime_state_cache.py:78` states risk and the sizer "call this on
every tick", which the measurement contradicts. Code is truth: the doc is
wrong, and this is a finding, not a correction.

### 2.5 The measurement's headroom is borrowed from sensor pruning

Engine 2 is 54% of the tick cost at **S=4**, and S=4 is not a property of the
platform — it is `prune_unused_sensors: true` plus an alpha that happens to
declare four dependencies. The pruning is correct behaviour and should stay. The
problem is what it does to the budget as alphas accumulate: **every alpha added
with a distinct sensor dependency un-prunes another sensor**, and engine 2's cost
is linear in the surviving count.

Engine 2 spends 73.55 µs/quote at S=4, of which 11.19 µs is the four `update`
calls (3.74 + 3.44 + 2.84 + 1.74) and 32.1 µs is the aggregator fan-in at 8.0 µs
per reading. Both terms are per-sensor, so the question is what happens at full
registration — and that is measurable rather than arguable.
`maybe_prune_unused_sensors` (`src/feelies/alpha/dependency_graph.py:236`) is a pure
config→config function called once at `src/feelies/bootstrap.py:245`, so
`tools/arch/perfmeasure.py --mode sensorscale` neutralises it and replays both legs
unprobed. No source edit, no new config.

| Leg | Registered | On quote | ns/quote | Fills | Parity |
|---|---|---|---|---|---|
| pruned (as shipped) | 4 | 4 | **131,934** | 20 | `0601295a20b5` |
| all declared | 15 | 13 | **335,301** | 20 | `0601295a20b5` |

**Nine additional quote-subscribing sensors cost +203,367 ns/quote — 2.54× the
total tick cost, 22.6 µs/quote per sensor.** VERIFIED
(`tools/arch/evidence/perf_sensorscale.json`).

Two consequences, the second being the one that matters for the budget:

1. **Sensor registration is output-neutral.** Both legs produce identical parity
   hashes and identical fill counts. For this alpha, pruning is purely a
   performance optimisation and not a behavioural one — which validates the
   override as a measurement technique, and means the 2.54× buys nothing.
2. **At full registration the platform costs 335 µs/quote — 10.5× the 32 µs
   budget**, with engine 2 alone at roughly 277 µs. The 4.3× overage in §2.2 is
   the *most favourable* number the repo can currently produce, and it is
   produced by running one alpha that happens to need four sensors.

This reframes the engine-2 row. It is not 6.1× over budget; it is 6.1× over at
the most favourable sensor cardinality available, and the marginal cost of the
next sensor is 22.6 µs — **70% of the entire per-quote budget, for one sensor.**
Pruning only helps while the union of alpha dependencies stays small, so any
design serving N alphas across archetypes (CORE §A) registers most of those 13.
**Engine 2's per-sensor marginal cost is the binding constraint on alpha count,
and it binds harder than anything in §6.**

---

## 3. Hot/cold partition

### 3.1 The boundary mechanism

Cold engines are 5 (Governance), 11 (Observability, except the kill-switch
read), and 12 (Research/Forensics), per CORE §D. Three mechanisms separate them,
and they are not equally strong:

| Mechanism | Where | Strength |
|---|---|---|
| **M1. Offline process** | `promotion/`, `src/feelies/cli/promote.py`, `research/` | **Strong.** Never imported by the tick path. `hotpath_executed.json` contains no `promotion/` or `research/` symbol — proven by execution, not by inspection |
| **M2. Event-bus subscription** | `src/feelies/bus/event_bus.py:subscribe` | **Weak.** Publication is synchronous; a subscriber's cost lands inside `publish`, inside the tick. A cold consumer on the bus is cold by convention only |
| **M3. Post-run read of an accumulated buffer** | `src/feelies/harness/backtest_report.py`, forensics | **Strong.** Reads after `run_backtest` returns |

**M2 is where the partition leaks, and it leaks by design.** The bus has no
queue (CORE §F.6), so "publish and let a cold consumer handle it" is a
contradiction in terms: the handler runs on the publisher's stack, in the tick.
Engine 11's 2.13 µs/q and engine 12's 0.48 µs/q are both M2 leaks.

### 3.2 Proof the partition does not perturb determinism

Two independent proofs, one measured here and one structural:

1. **Measured.** The probed run installs 66 wrappers, adds 56.8% wall-clock
   cost, and calls `time.perf_counter_ns` 85 extra times per quote. Parity hash:
   `0601295a20b5…` — bit-identical to all six unprobed runs. Cold-path
   observation of arbitrary density does not change output. VERIFIED.
2. **Structural.** `compute_parity_hash` (`src/feelies/harness/backtest_report.py:765-819`)
   hashes a nine-field projection of the trade journal: `order_id`, `symbol`,
   `strategy_id`, `side`, `quantity`, `fill_price`, `realized_pnl`, `fees`,
   `cost_bps`. No timing, no metric, no log line, no `correlation_id` can enter
   it, because the payload is an allow list rather than a filter. Timings are
   excluded **by construction**, which is exactly what P4 §5 requires.

The second proof is the durable one: the first would break silently if someone
added a timing field to a `TradeRecord`, the second would not.

### 3.3 One partition claim that does not hold

Every quote sets `RegimeState.discriminability` (`src/feelies/core/events.py:163`) at
`src/feelies/kernel/orchestrator.py:2474`. The value comes from
`discriminability_for_symbol` (`src/feelies/services/regime_engine.py:266`), resolved
through `getattr` at `src/feelies/kernel/orchestrator.py:2451`; the pooled
`discriminability` property (`src/feelies/services/regime_engine.py:253`) is only the
fallback when that method is absent. Both funnel into
`_compute_min_pairwise_emission_separation`
(`src/feelies/services/regime_engine.py:385-395`), a double loop evaluating K(K-1)/2
pairs. Its only production reader is the regime gate
(`src/feelies/signals/regime_gate.py:356-358`), which runs at horizon boundaries —
0.002 calls/quote measured. **The value is computed roughly 500× more often than
it is read**, at O(K²) cost. That is not a hot/cold violation in the CORE §D
sense; it is a compute-rate/read-rate mismatch, and it belongs in §6.

---

## 4. Budget breach behaviour

### 4.1 What the system does today: nothing

**There is no budget in the code.** A search of `src/feelies` for a comparison
between a measured latency and a threshold returns no site. Every `_ns`
comparison found is an *event-time* staleness or gap check —
`src/feelies/composition/synchronizer.py:206`, `src/feelies/sensors/impl/ofi_ewma.py:157`,
`src/feelies/sensors/impl/spread_z_30d.py:138` — which is causality gating (Inv-2), not
latency gating. VERIFIED by absence, which is the weakest form of evidence and
is why it was done by exhaustive pattern search over all 196 files rather than
by reading.

Consequently:

| Question | Answer |
|---|---|
| What happens in **live** when an engine exceeds budget? | The duration is recorded to `tick_to_decision_latency_ns`. Nothing reads it in-process. No alert, no degradation, no load shed |
| What happens in **replay**? | Identical, plus the value reaches the CLI report |
| Do the two differ in output? | **No.** Confirmed by the parity-hash identity in §3.2 |
| Do the two differ in observability? | Yes, and only there — replay additionally prints the histogram |

So CORE §F.6's requirement — differ **only** in observability, never in output —
is **satisfied vacuously**. It holds because nothing acts on latency at all. That
is a correct-by-emptiness result, and it stops holding the moment any breach
behaviour is added. **This is the constraint any future breach mechanism must
respect, and it is the reason the specification below is shaped the way it is.**

### 4.2 The specification

A breach response that reads wall clock and changes an order is a determinism
violation: replay would take a different branch than live. The only shape that
preserves Inv-1 is one where **the breach signal is an input to an
exposure-reducing decision that is recorded in the event log, and replay
consumes the recorded signal rather than re-measuring it.**

| | Live | Replay |
|---|---|---|
| Detection | `tick_to_decision_latency_ns` vs per-engine budget, at M10 | Not re-measured |
| Record | `LatencyBreach` event appended to the log with the measured duration and the engine | Read from the log |
| Action | Kill switch escalation on sustained breach → reduce exposure only (Inv-11, CORE §E.11 names latency drift as a kill-switch input) | Same branch, driven by the recorded event |
| Output effect | Identical to replay, because both read the same recorded event | Identical |

This makes latency a first-class event rather than a side channel, which is what
lets a breach change behaviour without breaking replay. It costs one event type
and one comparison per tick. Status: **specified, not implemented.**

### 4.3 Why the current instrument cannot support that yet

The observed maximum tick-to-decision is **16.000 ms** — exactly 16.000, against
a mean of 0.112 ms. Windows' default timer resolution is 15.625 ms. A value that
lands on the timer quantum is far more likely an OS scheduling artifact than a
144×-mean compute spike. The instrument reads wall clock
(`src/feelies/kernel/orchestrator.py:1524`), so **it cannot distinguish an in-process cost
from a preemption**, and a breach mechanism built on it would trip on the
scheduler.

This is a real gap, not a measurement nit: latency drift is a named kill-switch
input (CORE §E.11), and the only available signal currently conflates the thing
being monitored with the noise of the host. Whether a thread-CPU-time clock is
the fix is ASSUMED — it removes preemption from the signal but is not obviously
monotone across cores, and that trade-off is not resolvable from this repo.

---

## 5. Measurement harness

### 5.1 What exists

| Element | Implementation | Status |
|---|---|---|
| Collection point | M10, every tick: `src/feelies/kernel/orchestrator.py:2120` emits `tick_to_decision_latency_ns` | implemented |
| Per-segment timers | `_tick_timings` dict, allocated per tick at `src/feelies/kernel/orchestrator.py:1525` | implemented |
| Storage | `MetricEvent` (HISTOGRAM) → `MetricCollector` (`src/feelies/monitoring/telemetry.py`), in-memory | implemented |
| Report | `src/feelies/harness/backtest_report.py:333` reads the `kernel` / `tick_to_decision_latency_ns` summary; CLI prints avg/p95/p99/max | implemented |
| Hash exclusion | Allow-list projection in `compute_parity_hash` (§3.2) | implemented, and the correct design |
| **Per-engine histograms** | — | **absent.** One aggregate bucket for the whole tick |
| **CI regression gate** | — | **absent.** `.cursor/skills/performance-engineering/SKILL.md:19` states perf gates are wired into no CI workflow; `.github/workflows/ci.yml` confirms |

The gap is the important part: the platform measures the *total* and cannot
attribute it. Every per-engine number in §2 came from
`tools/arch/perfmeasure.py`, which is a review tool, not part of the platform.
**A budget the platform cannot measure is decoration** (P4 §5), and today engines
2, 3, and the kernel could each double their cost with no signal from any
committed test.

**The one per-sensor instrument that does exist cannot report.**
`tests/sensors/test_sensor_latency_budget.py:155` times every sensor over 100,000
events and builds a p50/p99/mean table (`:163-181`) — exactly the per-component
attribution §2.5 needed. It is then unreachable: `capsys.readouterr()` at `:184`
drains the buffer, and the only assertion on it is `"sensor" in captured.out`
(`:185`). Verified empirically — the module is gated on `CI_BENCHMARK=1` (`:36`),
and with that set the table appears under **none** of `-s`,
`--capture=tee-sys`, or `-rP`; all three runs report `1 passed` and print
nothing. The prior audit
(`docs/audits/performance_audit_2026-07-02.md:103-105`) claimed this; it is
confirmed, not merely repeated.

Two qualifications, in fairness to the test. It does assert `emitted > 0` per
sensor (`:182`), so it cannot pass against an inert sensor. And it makes no claim
to gate: its docstring says "informational only" (`:158`) and the module header
says "this is not a CI gate" (`:3`). The defect is not a false gate — it is that
the repo's only per-sensor latency measurement discards its output, so the
22.6 µs/sensor marginal cost in §2.5 had to be measured from outside the platform
when an instrument for it was already written. **Fix is one line: assert on the
table, or drop the `capsys` argument and let pytest report it.**

### 5.2 Specification for the missing part

Reuse what is proven rather than adding a framework:

1. **Per-engine buckets.** Replace the single `tick_to_decision_latency_ns`
   with one histogram per engine, keyed by the engine number already assigned in
   `phase2_contracts.md`. The `_tick_timings` dict at
   `src/feelies/kernel/orchestrator.py:1525` is 80% of this; what it lacks is a stable key
   set and an emission per key. Pre-allocate the dict at construction — that
   also clears prohibition P2.
2. **Percentiles, not means.** Budgets are p99 targets
   (`performance-engineering/SKILL.md:86`); a mean hides exactly the tail a
   budget exists to bound. The measured mean/p99 ratio here is 3.9× (0.112 ms
   vs 0.432 ms), so a mean-based gate would pass a system whose p99 had doubled.
3. **Exclusion by construction, not by convention.** Keep the allow-list
   projection in `compute_parity_hash`. Add a conformance test asserting the
   projection's field set, so adding a timing field to `TradeRecord` fails a test
   rather than silently entering the hash.
4. **Regression gate on the parity-oracle workload.** The APP baseline already
   runs in CI (`AGENTS.md`, `parity oracle` job). Recording per-engine p99 there
   costs one artifact and makes the §2 budget enforceable.

### 5.3 The harness's own determinism contract

Any probe added must satisfy the property this review's tool satisfies: the
parity hash is unchanged with instrumentation on. That was verified at 66 probes
and 56.8% overhead (§3.2). It is a cheap, strong test and it should be a
conformance case, not a one-off finding in this document.

---

## 6. Efficiency as deletion

Removal candidates only. CORE §H forbids acting, and dead-code removal requires
explicit scoped authorisation.

### 6.1 The largest item: publishing to nobody

`--mode census` counts every `EventBus.publish` alongside the live subscriber
count for that type in this configuration.

**828,946 of 1,410,977 publishes — 58.7% — have zero subscribers.**

| Event type | Publishes | Handlers | Reading |
|---|---|---|---|
| `StateTransition` | **661,992** | **0** | 8.007 per quote. No `subscribe(StateTransition)` anywhere in `src/feelies`; the only subscribers are in `tests/`. `tests/harness/test_backtest_runner.py:75` asserts the recorder *excludes* it |
| `Trade` | **166,862** | **0** | Two subscribers exist in code (`src/feelies/risk/deferral_cap.py:238`, `src/feelies/risk/hazard_exit.py:142`) but neither is wired in `bt_app.yaml`. Config-dependent, not universally dead |
| `SafetyStateChange` | 49 | 0 | Rare |
| `RiskVerdict` | 43 | 0 | Rare |

**Measured cost of the `StateTransition` path: 7,247.5 ns/quote corrected**
(`kernel.emit_state_transition`, 8.007 calls/q) — **5.3% of measured tick cost**,
for events nothing consumes. Add the `TransitionRecord` construction that feeds
it (475.1 ns measured × 8.007 = 3,804 ns/q, `src/feelies/core/state_machine.py:28`) and
state-machine bookkeeping reaches **11.1 µs/quote, 8.1% of measured cost — a
third of the entire 32 µs budget.**

The emission is unconditional — `src/feelies/kernel/orchestrator.py:4694-4707` publishes on
every transition with no flag.

**This is not simply deletable, and the reason matters.**
`tests/determinism/test_state_transition_replay.py:138` pins a locked baseline
hash over the transition stream: it is the parity surface for the state-machine
layer. So 8.1% of the tick cost is spent maintaining a test oracle. The
recommendation is to make the emission opt-in — a recorder subscribed only when
enabled, off in live — which keeps the oracle and removes the production cost.
**Recommended. Blast radius: kernel + one determinism test.**

### 6.2 Event fields no reader touches

20 of 179 fields across `src/feelies/core/events.py` have no attribute read anywhere in
`src/feelies`. Cost is per construction: removing 7 unread fields from a
19-field frozen event measured **385.9 ns faster per construction** (1,241.6 →
855.7 ns), a 31% reduction on the single most-constructed object in the system.

Three `NBBOQuote` fields are in the list — `participant_timestamp_ns`,
`trf_timestamp_ns`, `received_ns` (`src/feelies/core/events.py:86-88`) — and so are four on
`Trade` (`:104`, `:111`, `:112`, `:114`).

**The sharpest single instance is `MetricEvent.metric_type`**
(`src/feelies/core/events.py:370`). It is written at 13 construction sites and read at none:
`COUNTER`, `GAUGE`, and `HISTOGRAM` are set on all 251,500 metric events per run
and never consulted. §5.1 describes the tick latency store as a HISTOGRAM because
`src/feelies/kernel/orchestrator.py:2122` says so, but nothing acts on that declaration —
the type is nominal. **Candidate: either make the collector branch on it or drop
the field.**

A separate false-positive class is real and handled: a field read only through a
name literal is not dead, and `hotpath.json` lists those 8 separately rather than
mixing them in. `RegimeState.discriminability` is one of them, reached via
`getattr` at `src/feelies/signals/regime_gate.py:358` — the same pattern §6.5 describes.
**Candidate; requires a per-field pass before action.**

### 6.3 Computed far more often than read

| Computation | Compute rate | Read rate | Evidence |
|---|---|---|---|
| `RegimeState.discriminability` — O(K²) pairwise separations | 1.000/quote | **0.002/quote** | `src/feelies/services/regime_engine.py:380` at 3.000/q; sole production reader `src/feelies/signals/regime_gate.py:356-358` at boundary only |

Worse than the rate mismatch: the gate compares against
`min_discriminability`, whose default is **0.0**
(`src/feelies/core/platform_config.py:258`), and no shipped config sets it. So with the
current configuration the comparison **cannot** reject — the value is computed
every quote and the branch that reads it is inert. Two findings in one site: a
compute-rate mismatch, and a gate whose default makes it a no-op. The second is
a gating concern that Phase 3 owns; recorded here because the measurement
surfaced it. **Candidate: compute on boundary only, or on demand.**

### 6.4 Metrics recorded and never read

The census captures the 9 metric names actually recorded (251,500 records over
the run) rather than trusting a static scan, because several are constructed
dynamically from a variable and no regex finds them.

**2 of 9 have no reader in `src/feelies`**, only in tests:

| Metric | Records in replay | Rate | Read by |
|---|---|---|---|
| `feature.feelies.feature.snapshot.stale_fraction` | 1,092 | 0.013/q | tests only |
| `scheduler.feelies.horizon.tick.emitted` | 2,184 | 0.026/q | tests only |

Both are low-rate, so the direct saving is negligible — under 25 ns/quote at
681.9 ns per `MetricCollector.record`. They are listed because a metric read only
by a test is an assertion channel, not observability, and the distinction matters
for §5: neither would tell an operator anything in live.

**The inverse case is the more interesting one.** `src/feelies/harness/backtest_report.py:334`
reads `kernel.feature_compute_ns`, and **nothing in the replay ever records it** —
the census finds no such name among the 9. That report field is permanently
`None`: a reporting slot for a measurement that does not exist. This is the same
defect class as an unread computation, mirrored, and it is invisible to any
static scan of either side alone. **Candidate: record it or drop the read.**

For completeness, the two highest-rate metrics — `kernel.sensor_fanout_ns` and
`kernel.sm_transition_ns`, each recorded once per quote — *are* read, by
`src/feelies/harness/backtest_report.py:336-337`. They are not deletion candidates.

The prior audit `docs/audits/performance_audit_2026-07-02.md:162` describes this
area differently; the count there does not match the 9 names measured now. Code
is truth, and the discrepancy is a finding against the audit.

### 6.5 Members with no reference anywhere

Of 564 public members (122 properties), **106 have no reference in
`src/feelies`**; 21 have none in `src/`, `tests/`, or `scripts/`. Seven of those
21 are reached only through a name literal — `getattr(engine,
"refresh_high_water_mark", None)` — which is the P4 prohibition on dynamic
dispatch showing its real cost: **the call graph cannot be analysed, so live
code is indistinguishable from dead code by any static tool.** That is a
stronger argument for the prohibition than the 13.3 ns the `getattr` probe
measures.

The remaining **14 have no reference of any kind:**

| Member | Site | Note |
|---|---|---|
| `RegimeStateCache.forget` | `src/feelies/services/regime_state_cache.py:108` | **Eviction hook, never called** |
| `HorizonSignalEngine.forget` | `src/feelies/signals/horizon_engine.py:629` | **Eviction hook, never called** |
| `RegimeStateCache.for_engine` | `src/feelies/services/regime_state_cache.py:63` | |
| `SensorRegistry.collect_into` | `src/feelies/sensors/registry.py:439` | |
| `CrossSectionalTracker.all_snapshots` | `src/feelies/portfolio/cross_sectional_tracker.py:109` | |
| `AlphaBudgetRiskWrapper.checkpoint_risk_state` | `src/feelies/alpha/risk_wrapper.py:299` | Paired with the next row |
| `AlphaBudgetRiskWrapper.restore_risk_state` | `src/feelies/alpha/risk_wrapper.py:308` | Checkpoint/restore pair, neither called |
| `AlphaRegistry.has_signal_alphas` | `src/feelies/alpha/registry.py:216` | |
| `TradingSessionBounds.is_within_rth` | `src/feelies/execution/trading_session.py:82` | |
| `FeatureComputation.update_trade` | `src/feelies/features/definition.py:74` | |
| `BasicRiskEngine.buying_power_phase` | `src/feelies/risk/basic_risk.py:154` | property |
| `StopExitController.policy` | `src/feelies/risk/stop_exit.py:160` | property |
| `CostArithmetic.declared_round_trip_cost_bps` | `src/feelies/alpha/cost_arithmetic.py:78` | property |
| `LoadedPortfolioLayerModule.mechanism_caps` | `src/feelies/alpha/portfolio_layer_module.py:109` | property |

The two `forget` methods are the consequential pair. `RegimeStateCache._by_key`
grows on every `record` (1.000/quote) and the only removal path is never
invoked, so per-symbol state accumulates for the process lifetime — bounded by
distinct symbols seen, not by the live universe. For an intraday process that is
harmless; for a long-lived process over a rotating universe it is monotone
growth with a working eviction API nobody calls. **Candidate: wire it, do not
delete it.**

### 6.6 Cheap per-event allocations with a measured unit cost

| Site | Rate | Measured saving | Note |
|---|---|---|---|
| `src/feelies/core/state_machine.py:159` — `.get(state, frozenset())` | 8.007/q | **16.5 ns/call → ~132 ns/quote** | Default allocated then discarded. Hoist to a module constant |
| `src/feelies/kernel/orchestrator.py:1606` — `Decimal("2")` inline divisor | guarded | **58.2 ns/call** | Hoist |
| `src/feelies/kernel/orchestrator.py:1525` — `_tick_timings = {}` | 1.000/q | 11.9 ns/quote | Pre-allocate; also clears P2 |
| `src/feelies/portfolio/memory_position_store.py:160` — `dict(positions)` | 1.002/q | 49.0 ns at P=8, **O(P)** | Defensive copy. The cost is the scaling, not the constant |

These total under 300 ns/quote — 0.2% of measured cost. **They are listed for
completeness and are explicitly not worth doing on performance grounds.** They
matter only where they also clear a §1 prohibition, which the first and third
do. Ranking them above §6.1 would be optimising the wrong end by a factor of 40.

### 6.7 Summary: the available speedup from deletion alone

| Item | µs/quote | % of measured (S=4) |
|---|---|---|
| `StateTransition` emission + `TransitionRecord` (§6.1) | 11.1 | 8.1% |
| Unread event fields, if all 20 confirmed (§6.2) | ~1.2 | 0.9% |
| `discriminability` at boundary rate instead of per quote (§6.3) | ~0.2 | 0.2% |
| Unread metric records (§6.4) | ~0.02 | <0.1% |
| Micro-allocations (§6.6) | ~0.3 | 0.2% |
| **Total from deletion** | **~12.8** | **~9.4%** |

Deletion alone does not reach the 32 µs budget — it closes 9.4% of a 4.3× gap at
S=4, and only 3.8% of the 10.5× gap at full sensor registration (§2.5). The
remaining distance is engine 2, whose 73.6 µs at S=4 and 22.6 µs per additional
sensor is real sensor computation, not dead work: it needs a different algorithm
or a different cadence, which is Phase 5 and Phase 7 territory.

What deletion buys is not the size of the saving but its risk profile: **it
requires no algorithmic change and no change to what the system computes**, so
the parity hash must not move, which makes each item independently verifiable
against the oracle. That is the opposite of the engine-2 work, where any fix
changes computed features and the oracle can only tell you that something moved.
**Sequence deletion first for that reason, not because 9.4% is a lot.**

---

## Assumption register additions

| ID | Assumption | Why not checkable here | What would decide it |
|---|---|---|---|
| A4.1 | The N=8 scaling ratio (1.086×/quote) extrapolates toward N=100 | No cached multi-symbol data beyond 8 symbols | A replay at N=25 and N=50; the 1.96× `_on_horizon_tick` row is the one to watch |
| A4.2 | A thread-CPU-time clock would separate compute cost from OS preemption in the tick timer | Requires changing `src/`, forbidden this phase | Measure both clocks side by side on the same replay |
| A4.3 | The 20 unread event fields are genuinely unread and not reached via serialization | Static analysis cannot see `__dict__`-style access | Per-field removal against the parity oracle |
| A4.4 | Event construction cost (1,241.6 ns for `NBBOQuote`) is a live-path cost, not just a replay setup cost | In backtest, events are constructed before the replay loop and excluded from the 136.2 µs; in live they are constructed per message inside it | Measure the live/paper ingestion path, which this harness does not cover |
| A4.5 | The 22.6 µs/quote marginal cost per sensor is representative of sensors not in the measured set — the 13 registered differ in internal cost | Measured as an average over 9 added sensors, not per sensor individually | Per-sensor probes at full registration; `--mode sensorscale` already installs the arming hook needed |
| A4.6 | Sensor registration remains output-neutral for alphas other than `sig_benign_midcap_v1` | Verified for one alpha (identical parity hash and fills across both legs). An alpha reading a feature whose warm-up depends on registration order could differ | Run `--mode sensorscale` against a second alpha once one exists |

## Findings against prior documents

| Document | Claim | Measurement |
|---|---|---|
| `docs/audits/performance_audit_2026-07-02.md:162` | Metric count per tick | 9 distinct names, 251,500 records; the audit's figure does not match |
| `src/feelies/services/regime_state_cache.py:78` (docstring) | "risk and the sizer call this on every tick" | `RegimeStateCache.latest` measured at **0.001 calls/quote** |
| `.cursor/skills/performance-engineering/SKILL.md:93` | Single event processing < 10 µs | **42.2 µs/event** at S=4; **103.9 µs/event** at full sensor registration |
| `.cursor/skills/performance-engineering/SKILL.md:72` | "16 sensors ship in v0.3; 13 registered in the reference `platform.yaml`" | `platform.yaml` declares **15** specs, 13 of them on `NBBOQuote`; the shipped backtest registers **4** |

---

**HARD STOP** — Phase 4 complete. Phase 5 (gap table) not started.
