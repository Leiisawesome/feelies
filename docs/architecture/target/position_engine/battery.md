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
                   detached (non-sink outputs only)
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
                   only events at or before k
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
FAILURE LOOKS LIKE:one event and which assertion
BLOCKS THE BUILD:  yes — red until stage C (rail) / D (birth)
```

```
MEMBER:            5 Precedence
DEFENDS AGAINST:   ties resolved the flattering way; exits filed under the wrong reason
TAPE:              real session, plus synthetic forcing collisions: a gap through both a
                   trail line and a stop; a deadline landing on an event beyond the stop;
                   an invalidation arriving on the event a take-profit fires
SETUP:             trailing favorable armed; invalidation fixture signal
ASSERTS:           for every closed cell: proposed price = worst among triggered_paths, and
                   reason = highest-ranked triggered path (ADVERSE > HORIZON > INVALIDATION
                   > FAVORABLE); exactly one requirement per episode
FAILURE LOOKS LIKE:cell, deciding event, candidate list
BLOCKS THE BUILD:  yes — red until stage E
```

Implementation (P-21d): `tests/position_engine/test_battery_m5_precedence.py`.
Tests `test_m5_invalidation_at_take_profit`, `test_m5_deadline_beyond_stop`,
`test_m5_gap_through_trail_and_stop` (seed 29, 4_000 quotes; V3a / V3b / V5),
and `test_m5_real` (`battery_real`). `green_from` E.

```
MEMBER:            6 Injection
DEFENDS AGAINST:   holes in the gates' data-quality rules
TAPE:              one clean real session and paired injected copies: held quotes, removed
                   sides, crossed books placed both to flatter the take-profit and to hide
                   a stop breach, feed_gap_before set directly
SETUP:             identical configuration on clean and injected runs
ASSERTS:           favorable exits do not increase; adverse exits do not decrease; the
                   overall result does not improve; suppression and hold counts non-zero
                   on every injected tape
FAILURE LOOKS LIKE:which injection moved which count, by how much
BLOCKS THE BUILD:  yes — red until stage E
NOTE (D-48): under design review for P-21e. "Held quotes" must mean a quiet name (quotes
excised), not repeated quotes; whether "the overall result does not improve" is implied for a
correct engine on a single path is to be settled under the amendment rule before the member is
written.
```

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
own `green_from`. Every member asserts non-vacuity first (records of the kind it judges exist)
with a message beginning `NONVACUOUS:`, then its property.

## Broken engines (stage A gate)

Each is a deliberately wrong implementation behind the same contract. Each must be caught,
and by the named member. A broken engine nothing catches is a hole in the suite.

| # | Defect | Must be caught by |
|---|---|---|
| B1 | rail values at mid | 4 |
| B2 | tie resolves toward FAVORABLE | 5 |
| B3 | adverse exit proposed at the configured level, not the quote | 3 or 5 |
| B4 | cell reads the system clock for the deadline | 1 |
| B5 | excursion accumulated instead of recomputed | 3 or 11 |
| B6 | best-so-far seeded at zero | 11 |
| B7 | adverse gate skips when a side is absent | 6 or 8 |
| B8 | clean peak absorbs a crossed event | 6 |
| B9 | second requirement emitted while EXITING | 5 or 10 |
| B10 | resolve phase rewrites a published move | 1 |
| B11 | window trimmed lazily (on read, not in the step) | 2 |

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
