# Battery

The only fitness function this campaign permits. Eleven members, frozen before the build.
Six block the build and exist, red, before any engine code lands; five are written
alongside the build because they need the engine's own records. Changing a member after
freeze follows the amendment rule at the end, with a ledger entry.

Tests live under `tests/position_engine/`. The implementer never edits a landed test; a
diff touching that path in a build rung is a STOP.

---

## Fixtures (shared)

- **Synthetic tape generator** `tests/position_engine/tapes.py`. Driftless, prices on the
  cent lattice, barriers on lattice points, known spreads, seeded. It is an oracle, so it
  is itself tested first (`test_tape_generator.py`): measured drift within tolerance over
  a long run, every price and every barrier on a lattice point, seeds reproducible.
- **Injection helpers**: hold a quote past its time; remove a side (zero size); cross the
  book at a chosen level; set `feed_gap_before`. Paired with the clean tape they came from.
- **Feed-gap injection** (D-28, D-31): tests wrap `MarkRail.on_quote` and return the update
  with `feed_gap_before=True` for chosen quote sequences (`dataclasses.replace`), leaving every
  other field unchanged.
- **Fixture alpha** `sig_position_fixture_v1` (test-only): enters on a deterministic
  schedule independent of sensor values, stamps its own `strategy_id`
  (`sig_position_fixture_v1`), declares `exit_policy`, and is used by every member that
  needs positions. The copy landed at P-15 is data-gated and stamps
  `sig_contra_fixture_v1`; P-21 corrects both (D-19).
- **Real session**: the APP 2026-03-26 cache day, through the harness door `bt_*` configs
  boot by, execution mode `market`.
- **Where real-session members run**: marker `battery_real`, collected by the
  `parity oracle` CI job with the cache required (`evaluation.md` §5, D-20).
- **Null configuration**: `S = 0`, `D = 0`, fees 0 or independently computed, deadline as
  stated per member.
- **Enabling in tests**: `build_platform(..., enable_position_engine=True)` until P-15; from
  P-15, a fixture alpha declaring `exit_policy`.

## Structural checks already in force (not battery members)

- **T7** (`tests/position_engine/test_p10_contract_surface.py`): the S15 runtime-subset check
  on an enabled build. T7 reuses S15's `_measure_phase4` by re-pointing that module's
  `build_platform`; if S15 stops exposing either, T7 must fail loudly, never pass vacuously.
- **S14 dynamic forbidden-reads probe** builds with the engine enabled, so engine 13's runtime
  reads are probed (negative probe on record: a `RegimeState` subscription in `PositionEngine`
  fails it).
- **S-09 / manifest fingerprint**: the five event types and their payloads are pinned; any
  field change is a pin edit with a fail-first.
- **Attribution (D-96, D-97).** The recorder advances its attribution cursor from a
  `MarkRailUpdate` type handler registered before the engine attaches. A record carrying
  `rail_sequence` is attributed to that sequence; a mismatch raises. After replay the harness
  calls `engine.finalize()` when that method is defined. Records published then carry replay
  index `N = len(replay)` and attribution cursor `EOT`. They are never attributed to a quote
  and never fall inside a replay-index prefix.

## The six that block the build

```
MEMBER:            1 Reproducibility
DEFENDS AGAINST:   results depending on anything other than the data
TAPE:              real session, plus one synthetic
SETUP:             identical configuration across all runs
ASSERTS:           byte-identical rail updates, snapshots, gate decisions, requirements
                   and closing records across: a deliberately wrong system clock
                   (time.time/monotonic patched); reversed gate evaluation order; the name
                   alone versus inside a multi-name universe whose other name is quoted
                   but not traded (synthetic tapes; D-36, D-38); a fresh process; sinks
                   detached (non-sink outputs only). Published records are immutable:
                   at most one PositionSnapshot per (cell_id, rail_sequence). It catches B10.
                   Engine events are frozen, slotted and tuple-only, so an in-place rewrite
                   is impossible and the digest-at-end half is dropped (D-103). Conformance:
                   tests/conformance/test_engine_events_frozen.py.
                   green_from as member 1
FAILURE LOOKS LIKE:a diff; the first divergent sequence localises it
BLOCKS THE BUILD:  yes — green from stage B onward, never red again
```

```
MEMBER:            2 No-lookahead
DEFENDS AGAINST:   using information that had not yet arrived
TAPE:              real session through a truncating harness
SETUP:             none
ASSERTS:           for sampled events k, a run on the tape truncated after k produces an
                   identical rail update, snapshot and decisions at k; the dwell window
                   holds exactly the quotes inside (t − D, t], and always the current
                   quote (D-41); running extremes absorb
                   only events at or before k. The dwell window is trimmed in the step:
                   with D > 0, a dirty (crossed) quote older than t−D never blocks a
                   favorable decision at t. Construction: D = 2 s via FEELIES_RAIL_DWELL_NS;
                   a crossed quote at t−D−100 ms; the favorable condition met at t
                   (quote sequence 401). The decision at that quote is outcome fire, and
                   its reason is not DWELL_NOT_CLEAN (J5, D-131). It catches B11.
                   At P-40 the D source becomes PlatformConfig and this test switches.
                   green_from C, the stage at which P-40 lands:
                   | P-40 | C | rail complete (ages, absences, window, warm-up, worst-side, forced, dwelled); PlatformConfig position_rail_slippage_ticks and position_rail_dwell_ns (D-40). rail side usability per D-62: classify once in the orchestrator mark path, pass the result to store and rail; no second classify call site |
FAILURE LOOKS LIKE:the first event where truncated and full runs differ
BLOCKS THE BUILD:  yes — green from stage B onward
```

```
MEMBER:            3 Known-answer conservation
DEFENDS AGAINST:   sign errors, off-by-one barriers, hidden costs, the draw breaking the
                   arithmetic
TAPE:              synthetic driftless, lattice prices, lattice barriers
SETUP:             null configuration; (a) barriers only, no deadline (T longer than the tape); (b) barriers plus
                   deadline; (c) adverse level drawn from a band
ASSERTS:           (a) with the favorable trigger u ticks and the adverse trigger d ticks from the valuation
mark at birth, share exiting favorable first = d / (u + d) within tolerance, with at least one
pair at u:d = 1:2 (expected 2/3). Thresholds stated as moves from entry cost translate as
u = X + s and d = L − s, where X and L are the favorable and adverse thresholds in ticks and s
is the entry spread in ticks (the first reading is −s). (D-32); (b) the three exit groups' realized moves
                   integrate to zero within tolerance; (c) (a) holds averaged over draws;
                   all three: mean displacement = 0 within 4 standard errors, equivalently mean result =
                   −mean cost, with result, displacement and cost as defined in contracts.md §9 (D-46),
                   computed from the fills and the tape without reading any engine figure, at every swept
                   threshold
FAILURE LOOKS LIKE:which configuration, which side of the identity
BLOCKS THE BUILD:  yes — red until stage E
```

Implementation (P-21d): `tests/position_engine/test_battery_m3_known_answer_conservation.py`.
Tests `test_m3_barriers_only` (V3a, seed 11), `test_m3_barriers_swapped` (V3a2, seed 17),
`test_m3_barriers_and_deadline` (V3b, seed 19), `test_m3_band_draw` (V3c, seed 23).
Tape length 120_000 quotes. `green_from` E. (a) and (c) use `T_seconds` 16000 (D-50).

```
MEMBER:            4 Side correctness
DEFENDS AGAINST:   the spread disappearing from the accounting
TAPE:              real session, plus synthetic with known spreads
SETUP:             long and short positions present; market-mode entries
ASSERTS:           every rail update: paying and valuation on opposite sides, differing by
                   exactly the quoted spread (unless crossed); worst_side_mark and
                   forced_exit_mark never better than valuation_mark. At birth: the first
                   move_now_cents = sign × (valuation at the birth fill × size −
                   entry_cost_cents) exactly, and = −entry_spread_ticks × size exactly for a
                   MARKET entry filled at the touch, long and short alike
The touch clause applies only to cells whose every entry fill printed at the birth paying mark;
the number of such cells is reported, and a count of zero is recorded as untested, not passed.
The general identity holds for every cell. (D-34)
                   On every non-VALID quote the rail marks absent exactly the sides the store
                   refuses; absence clocks run; symbol_quiet_ns resets. green_from C, the stage
                   letter at which P-40 lands:
                   | P-40 | C | rail complete (ages, absences, window, warm-up, worst-side, forced, dwelled); PlatformConfig position_rail_slippage_ticks and position_rail_dwell_ns (D-40) |
FAILURE LOOKS LIKE:one event and which assertion
BLOCKS THE BUILD:  yes — red until stage C (rail) / D (birth)
```

Implementation (P-21f): unusable-side clause in
`tests/position_engine/test_battery_m4_side_correctness.py` `test_m4_unusable_side`.
One tape per class (NONPOS_BID, NONPOS_ASK, CROSSED, LOCKED, ZERO_SZ_BID, ZERO_SZ_ASK)
via `force_class` (D-72), seed 11, injected after a valid quote. `green_from` C,
`red_reason` UNUSABLE_SIDE. Both rail sides absent; absence clocks run from the last
usable quote; `symbol_quiet_ns` resets.

```
MEMBER:            5 Precedence
DEFENDS AGAINST:   ties resolved the flattering way; exits filed under the wrong reason
TAPE:              real session, plus synthetic forcing collisions: a gap through both a
                   trail line and a stop; a deadline landing on an event beyond the stop;
                   an invalidation arriving on the event a take-profit fires
SETUP:             trailing favorable armed; invalidation fixture signal
ASSERTS:           for every closed cell: proposed price = worst among triggered_paths, and
                   reason = highest-ranked triggered path (ADVERSE > HORIZON > INVALIDATION
                   > FAVORABLE); one live requirement at a time; a re-emission only after a
                   REJECTED ack for the previous attempt (G11, D-106). The three synthetic
                   collisions are tape-computed (J1, D-127): the first quote that holds
                   FAVORABLE also holds a higher path (INVALIDATION, HORIZON, or ADVERSE)
                   on that same rail event (contracts §2:265-274). The close's exit_reason
                   is that higher path, and triggered_paths holds both.
FAILURE LOOKS LIKE:cell, deciding event, candidate list
BLOCKS THE BUILD:  yes — red until stage E
```

Implementation (P-21d): `tests/position_engine/test_battery_m5_precedence.py`.
Tests `test_m5_invalidation_at_take_profit`, `test_m5_deadline_beyond_stop`,
`test_m5_gap_through_trail_and_stop` (seed 29, 4_000 quotes),
and `test_m5_real` (`battery_real`). `green_from` E.
The invalidation tape is held at the birth touch through index 900; the
favorable price is on index 901, the rail after the opposing signal.
The horizon tape (T = 10 s) is held flat until the deadline quote, which is
also the favorable price. The trailing tape ramps nine one-tick steps from
the birth quote, then one quote jumps through the trail and the adverse
level. (J1, D-127)

```
MEMBER:            6 Injection
DEFENDS AGAINST:   holes in the gates' data-quality rules: decisions taken on unusable data, stops
                   concealed by unusable data, exits credited at prices not on the tape
TAPE:              (R) one clean real session and three injected copies — a crossed book that flatters
                   the valuation side; one side removed; feed_gap_before set on a rail event (rail seam,
                   D3) — placed by rule P.
                   (S) synthetic constructions: gap through the adverse barrier (excise + shift_from);
                   BLIND boundary triplets (just under A / exactly A / just over A) for symbol_quiet_ns
                   (excise), valuation_absent_for_ns and paying_absent_for_ns (remove_side_run); a crossed
                   book flattering the peak inside a trailing (V5) cell; a stop breach concealed by
                   unusable data, shorter and longer than A.
PLACEMENT (P):     an injection sits at event e inside a live cell's life where the clean run makes no
                   exit decision at e or e+1. Eligible cells are ranked by sha256(cell_id); up to 5
                   injections per copy. Deterministic.
SETUP:             identical configuration on clean and injected runs; synthetic runs use the C_SYN harness
                   (per-alpha drawdown 100, D6)
ASSERTS:           A1 every FAVORABLE exit, in every run, is decided on an event with all six §9
                      suppression reasons clear
                   A2 ignorable injections change no exit: (cell_id, reason, deciding sequence, exit price)
                      equal the clean run for every cell; the expected flag is set (lived_through_feed_gap on
                      cells alive at a feed-gap event); ≥1 suppression record per injected copy
                   A3 for an END_OF_TAPE close, proposed_price_cents equals the executable exit side of
                      the last usable rail update, or None with closed_on_stale_data (N7, D-102, D-109).
                      For every other close, A3a: each exit-leg price equals that leg's fill ack,
                      whole cents (§2:294–295, §9:487–489). A3b: the leg is published after the
                      deciding gate and is no better than the executable side of the quote being
                      processed when the fill is published (the current pricing model, R2)
                   A4 gap through the adverse barrier with gap < A: reason ADVERSE; exit no better than
                      the executable side of q_g+1; strictly worse than the barrier price; all values
                      computed from the tape
                   A5 for each of the three absence measures: no BLIND just under A or at exactly A; BLIND
                      just over A (strict >, §9)
                   A6 a breach concealed by unusable data is exited on the first usable event that shows it,
                      or by BLIND once the concealment exceeds A
FAILURE LOOKS LIKE:injection, cell, clean vs injected exit tuple, missing flag or suppression record
BLOCKS THE BUILD:  yes — red until stage E
CATCHES:           B3 (A3, A4), B7 (A5), B8 (A2 on the V5 construction)
NOTE (D-48):       Resolved by D-54..D-62 (P-21e).
```

Implementation (P-21f): synthetic
`tests/position_engine/test_battery_m6_injection_syn.py` and real
`tests/position_engine/test_battery_m6_injection_real.py`. Checkers A1–A6 and
placement rule P live in `tests/position_engine/scenarios.py`. Synthetic seed 11,
`start_ns` T0: A1 and A3 on every run; A4 on V3a, 800 quotes (excise 20 from
index 302, `shift_from` −15); A5 quiet excise 298/299/300 and valuation-absent
and paying-absent `remove_side_run` 299/300/301, horizon 30; A6 short, 4000
quotes, horizon 120 (`shift_from` 3602 by +51, cross indices 3602–3900) and A6
long, 1800 quotes (`shift_from` 1202 by −47, cross indices 1202–1502); A2 on V5,
2000 quotes (cross index 400). Real fraction 0.5 (S0-1: 12 eligible lives).
One clean run plus three copies placed by rule P (D-74): crossed-flatter,
valuation side removed, `feed_gap_before` via the rail seam. A1 and A3 on all
four runs; A2 on each copy, including risk-verdict equality (D-75). `green_from` E.

## The five written alongside the build

```
MEMBER:            7 Monotonicity
ASSERTS:           one knob swept at a time, at least four settings: more S gives weakly
                   worse mean result and S = 0 is never beaten; longer D gives weakly fewer
                   favorable exits; wider give-back gives weakly fewer favorable exits, the
                   difference appearing as adverse/horizon exits; wider band gives no
                   systematic improvement (needs enough cells; weakest assertion)
BLOCKS THE BUILD:  no
```

```
MEMBER:            8 Decision record completeness
ASSERTS:           every rail event of every open cell has an adverse decision (fire or
                   hold); every blocked favorable comparison carries one of the six declared
                   block reasons; both counts non-zero on every injected tape
BLOCKS THE BUILD:  no — makes member 6 auditable rather than hopeful
```

```
MEMBER:            9 Held-price integrity
ASSERTS:           no age decreases without the underlying price changing; while a side is
                   absent its published price is bit-identical to the last one published
                   while present; absent-for spans increase monotonically through an
                   absence and reset only on reappearance
BLOCKS THE BUILD:  no
```

```
MEMBER:            10 Lifecycle
ASSERTS:           entry refusal with the correct reason for no paying price, crossed at
                   birth, cutoff passed, scale-in; the horizon fires on the first rail event
                   at or past the deadline, by sequence, including when a gap swallowed the
                   deadline; no state change and no requirement after CLOSED; no second
                   requirement in EXITING; every opened cell closes (END_OF_TAPE counted)
BLOCKS THE BUILD:  no
```

```
MEMBER:            11 Audit reconstruction
ASSERTS:           with the engine switched off, from closing records and the quote tape
                   alone: both moves, all three extremes, the proposed price and the gross
                   figure rebuild exactly; every price is a whole cent; every extreme traces
                   to a real event by sequence; no FAVORABLE exit books a move below the
                   round trip
BLOCKS THE BUILD:  no — needs closing records
```

In scope for P-22a1 (built in tests). ASSERTS unchanged. (D-85)
`test_m11_gap_through` reuses the A4 V3a gap (excise 20 from index 302,
`shift_from` −15) and asserts `check_m11_proposed` (J2, D-128). The tape
precondition is that the barrier level differs from the executable side of
q_g+1. NONVACUOUS requires at least one ADVERSE close.
Gross is checked as member 11's rebuild from the tape and the legs versus
`scenarios.cell_economics` (two independent computations must agree). No recorded gross
field exists (contracts §2). (D-104)

## Stage gates

| Stage | Lands | Gate |
|---|---|---|
| A | tape generator + its test; the six blocking members, red; the broken engines | every broken engine caught, each by a named member |
| B | walking skeleton on the P-10 surface (event types, wiring, streams and sinks landed in P-10): stub cell with birth/close from slice fills, stub gates, the two-phase step | members 1, 2 green |
| C | mark rail | members 1, 2, 9 green; 4 (rail half) green since A (D-37) |
| D | position cell | + 4 (birth), 10, 11 green |
| E | both gates, precedence | all eleven green |

Engine-on regression after P-99 is guarded by the position oracle, not by this battery
(`evaluation.md` §1).

Four of the six blocking members stay red until stage E. That is expected, not a signal
to soften them.

## Stage gate mechanism (D-18)

The current stage is one letter in `docs/architecture/target/position_engine/stage.txt`,
created at P-21. Each blocking member declares `GREEN_FROM` (a stage letter) and
`RED_REASON` (a regex). A conftest hook in `tests/position_engine/` enforces the rule:

- stage < `GREEN_FROM`: the member must fail with an `AssertionError` whose message matches
  `RED_REASON`. Any other outcome fails the run: a pass, or any other exception (including
  ImportError).
- stage ≥ `GREEN_FROM`: the member must pass.

Only a stage-gate rung edits `stage.txt`. No build rung edits a test. `xfail` is not used for
battery members.

Marker: `@pytest.mark.battery_member(member=N, green_from="<A–E>", red_reason=r"...")`.
A member split by stage (member 4's rail and birth halves) is two test functions with their
own `green_from`. Assertion order is baseline, then PRECONDITION, then NONVACUOUS, then the
property (D-107). PRECONDITION asserts engine-independent facts (the run contains at least
one entry fill; the tape reaches a boundary the fixture enters on; an injected quote is
present). A message beginning `PRECONDITION:` is a real failure at every stage. The stage
gate never treats it as expected red. NONVACUOUS (records of the kind the member judges
exist) uses a message beginning `NONVACUOUS:`, then the property.

## Broken engines (stage A gate)

Each is a deliberately wrong implementation behind the same contract. Each must be caught,
and by the named member. A broken engine nothing catches is a hole in the suite.

| # | Defect | Must be caught by |
|---|---|---|
| B1 | rail values at mid | 4 |
| B2 | tie resolves toward FAVORABLE | 5 |
| B3 | adverse exit proposed at the configured level, not the quote | 3, 5, 6 or 11, including `test_m11_gap_through` |
| B4 | cell reads the system clock for the deadline | 1 |
| B5 | excursion accumulated instead of recomputed | 3 or 11 |
| B6 | best-so-far seeded at zero | 11 |
| B7 | adverse gate skips when a side is absent | 6 or 8 |
| B8 | the cell's clean peak reads the raw NBBOQuote instead of the rail on an unusable event | 6 (A2 on the V5 construction) |
| B9 | second requirement emitted while EXITING | 5 or 10 |
| B10 | the resolve phase publishes a second PositionSnapshot for the same (cell_id, rail_sequence) | 1 (immutability clause) |
| B11 | window trimmed lazily (on read, not in the step) | 2 (D > 0 clause) |

## Kill runner

A kill is at least one PROPERTY failure in a named catcher's test ids (J7, D-133).
CRASH, TIMEOUT, PRECONDITION and NONVACUOUS never count. Each mutant runs in its
own pytest process, at stage E, with the other seam set to the reference. When the
battery row names a clause, only that clause's tests run.

```
python tests/position_engine/kill.py
python tests/position_engine/kill.py --control
python tests/position_engine/kill.py --shard A
python tests/position_engine/kill.py --shard B
python tests/position_engine/kill.py --only B3
```

`--control` runs the reference through the same selections and requires 0 failures.
The process exits non-zero when any selected mutant is not KILLED.

Shard assignment from the P-22b kill walls. Each estimate is the sum of those
walls plus 11 s, and each is at most 300 s (D-71).

| Shard | Mutants | Walls (s) | Estimate (s) |
|---|---|---:|---:|
| A | B1, B4, B10 | 8.7 + 17.6 + 8.3 = 34.6 | 45.6 |

B4's selection is `test_m1_fresh_syn`. The in-process clock test freezes
`time.monotonic` for its second run; with this mutant that run does not finish
inside the 240 s limit, and a TIMEOUT is not a kill. The fresh process compares
two real clocks and fails `fresh records differ`.
| B | B2, B3, B5, B6, B7, B8, B9, B11 | 2.1 + 1.3 + 1.6 + 1.7 + 2.1 + 2.2 + 2.1 + 1.2 = 14.3 | 25.3 |

**Reference rail (P-22a1) and reference engine (P-22a2).** Built only from the contracts
text (§§0–9), not from §9 alone, with a spec-trace table (D-92). Rail rows land in P-22a1;
engine rows in P-22a2. It imports only event types, protocols,
`core/quote_quality.classify`, `core/exit_policy`, `core/identifiers` and `bus/event_bus`.
`src/` never imports it (AST guard).

The package is `tests/position_engine/reference/`: `engine.py` (cell, both gates, G11),
`rail.py`, and `trace.md` (one row per behaviour: contract line, function, test). To run
it, point `FEELIES_STAGE_FILE` at a file containing `E`, set `FEELIES_ENGINE` to
`tests.position_engine.reference.engine.PositionEngine` and `FEELIES_RAIL` to
`tests.position_engine.reference.rail.ReferenceRail`. Synthetic members 1–6 and 11 use
`-m "not battery_real"`. The real members also need `FEELIES_REQUIRE_BASELINE_CACHE=1`
and `-m battery_real`. CI runs those as "reference battery" (push and pull request) and
"reference battery (real)" (nightly and workflow_dispatch). D-71: the synthetic job
finishes no slower than check.

Acceptance is the trace commit plus this rung's member fixes. Fix log: G11 re-emits a
rejected live exit on the next usable rail (§2:157–161, D-106), traced to
`PositionEngine._on_ack`. The fill-timing amendment did not change the engine. J2 (D-117):
a window across event types uses bus order. The deadline comparison in the engine is a
duration and stays until P-23.

## Load-time checks

A configuration failing any of these does not load (`ConfigurationError`). It never warns.

| # | Check |
|---|---|
| L1 | fixed target `X > fee_round_trip_ticks + 1` (runtime: if `X ≤ round_trip_ticks` at birth, the fixed form is disarmed for that cell and counted) |
| L2 | adverse band `[centre − B/2, centre + B/2]` lies inside `[lo, hi]`, and `lo > fee_round_trip_ticks + 1` |
| L3 | a centre tighter than the measured crossing declares `premium_bps` |
| L4 | every level carries `curve_ref`; the literal `ARBITRARY_NOT_CALIBRATED` is accepted only in BACKTEST and stamps every record `uncalibrated` |
| L5 | declared form consistent with declared archetype (section 3 table of `contracts.md`) |
| L6 | ownership exclusivity: no `hazard_exit` / `safety_exit_policy` on an `exit_policy` alpha; platform stop/trail policy off when any alpha declares `exit_policy` |
| L7 | mode is BACKTEST |
| L8 | `T > 0`, `cutoff_before_close > 0`, `A > 0`, `Q > 0`, `D ≥ 0`, `S ≥ 0` |

Forbidden reads are enforced structurally, not tested: each component receives an input
type that cannot express what it may not read (the cell's inputs carry no mid; the
favorable gate's snapshot view carries no `forced_exit_mark`).

## Amendment rule

When a member fails, write down why the member (not the engine) is wrong. If the
justification can be stated without reference to results — no "too strict", no "fails on
trades that look fine" — the member may be amended, with a ledger entry and the whole
battery re-run. Otherwise fix the engine. Making a member stricter without changing its
words is not an amendment.

Amendments already made (carried from v2): member 1 "restart mid-run" replaced by "a fresh
process" (no state serialisation exists); member 6 injects the feed-gap flag directly (a
per-name sequence discontinuity can be neither produced nor detected from this feed).

## Running locally

Before pushing, run `python scripts/prepush.py` (the CI check order: ruff, mypy,
import contracts, then pytest with `scripts/ci_gate_expr.txt`). `--fast` stops after
the static steps.

Broker tests run only with `FEELIES_BROKER_TESTS=1`. Network tests run only with
`FEELIES_NETWORK_TESTS=1`. Without the flag, those tests are skipped (`opt-in`).
