# Contracts

Final state of every contract, all renames applied. Each constraint carries its reason,
because an unexplained constraint is a candidate for "helpful" simplification.
Departures from v2 are tagged `[A-nn]` and justified in `amendments.md`.

Units everywhere inside the engine: prices in **whole cents** (int), times in **whole ns**
(int), distances in **whole ticks** (int, tick = 1 cent for this universe). No float, no
Decimal arithmetic on the decision path. *Reason:* a fractional tick can only mean a
price was averaged, interpolated or damaged, and a decimal cannot hold a 19-digit ns
timestamp exactly.

Ordering: by the platform event `sequence`, never by timestamp. Durations: by
`exchange_timestamp_ns` of the quote, the one declared feed clock [A-06]. *Reason:* the
measured feed has timestamp ties (854 in one session, `feed.md` F2); sequence does not tie.

---

## 0. Placement and wiring (feelies)

| Part | Owner | Module set | Talks to others by |
|---|---|---|---|
| Mark rail | engine 7 portfolio | `portfolio` | publishes `MarkRailUpdate` (core event) |
| Position cell, both gates, precedence | engine 13 position [A-01] | `position` (new, 13th independence set) | subscribes `MarkRailUpdate`, `PositionUpdate`, `Signal`; publishes `PositionSnapshot`, `GateDecision`, `PositionClosed`, `DeRiskRequirement` |
| Entry refusal at birth | engine 9 execution, admission [A-04] | `execution` | reads the latest `MarkRailUpdate` fact for the name |
| Exit plan | engine 9 execution | `execution` / kernel copy site | consumes `DeRiskRequirement` with `source_layer="POSITION"` |
| Veto and safety exits | engine 8 risk | `risk` | unchanged: `check_order` on every order; `FORCE_FLATTEN`, `DATA_*`, kill switch outrank everything here |

Engine 13 imports only `core` (and `bus` if the tier contract allows it for engines).
Zero engine-to-engine pairs, same as the other twelve. *Reason:* the battery runs on an
isolated engine; an import from engine 7 would make every rail change a cell change.

**Ownership rule.** A strategy slice `(strategy_id, symbol)` is *owned* by engine 13 if and
only if its alpha declares `exit_policy`. For an owned slice, no other author may emit an
exit except engine 8's safety exits [A-08]. Build rejects an alpha with `exit_policy` that
also declares `hazard_exit` or `safety_exit_policy`, and rejects any config with
`exit_policy` alphas while the platform stop/trail policy is enabled. *Reason:* two authors
that can both reduce exposure, on different triggers, with no arbitration, is how a
platform double-flattens (phase2 F.4).

**Mode rule.** `build_platform` raises `ConfigurationError` if any loaded alpha declares
`exit_policy` and the mode is not BACKTEST [A-02]. Loud refusal, never a silent run
without the engine.

---

## 1. Mark rail (engine 7)

**Job.** For one name, on every quote, publish what can be paid, what the position is
worth, what a forced exit would get, and every fact needed to judge whether to trust
those prices. It reports; it never judges.

**Reads.** `NBBOQuote`: `symbol`, `bid`, `ask`, `bid_size`, `ask_size`,
`exchange_timestamp_ns`, platform `sequence`. The feed-interruption fact from ingestion
(`feed_gap_before`). Run config: `S` (declared slippage, ticks) and `D` (dwell interval, ns)
[A-07].

**Emits.** One `MarkRailUpdate` per quote, per name, unconditionally, carrying **both**
orientations. *Reason (every quote):* "nothing changed" is never true — ages move and the
silence timer resets. *Reason (both orientations):* the rail never learns that positions
exist, so it can be run and replayed with zero positions open.

Per orientation (`long`, `short`; shown for long, mirrored for short):

| Field | Definition | Consumer |
|---|---|---|
| `paying_mark` | ask | admission (birth), cell (`entry_spread_ticks`) |
| `valuation_mark` | bid | cell arithmetic |
| `worst_side_mark` | worse of the two quoted sides for the exit direction (long: `min(bid, ask)`); a held price stands in for an absent side | adverse gate comparison [A-09] |
| `forced_exit_mark` | `worst_side_mark` worsened by `S` ticks | adverse, horizon, invalidation proposed price |
| `dwelled_exit_mark` | worst valuation-side quote over the trailing `D` (long: min bid in window) | favorable proposed price |
| `dwell_window_clean` | no absence, crossing or feed gap anywhere in the window | favorable gate |
| `paying_size`, `valuation_size` | sizes at those quotes | diagnostic, audit |
| `paying_age_ns`, `valuation_age_ns` | since that side's price last **changed** | context |
| `paying_side_absent`, `valuation_side_absent` | no price, or price with zero size | gates |
| `paying_absent_for_ns`, `valuation_absent_for_ns` | 0 while present | gates |

Shared: `symbol_quiet_ns` (since any quote on this name), `locked` (bid == ask),
`crossed` (bid > ask), `feed_gap_before`, `warmed_up` (window spans the full `D`),
`event_timestamp_ns`, `event_sequence`.

**Carries between events.** Current bid/ask and sizes; last-changed ts per side;
absent-since ts per side; last-quote ts; a rolling window of executable quotes bounded by
`D`. Nothing else.

**Step order (fixed).** feed-gap flag → update book sides (appear/disappear) → update
timers → push this quote into the window, then trim everything older than `D` → compute
both orientations → emit. *Reason:* trimming anywhere else makes the answer depend on when
the trim ran, not on the data.

**Forbidden to read.** Mid; any smoothed, modelled or interpolated price; trade prints;
wall clock; belief/indicator input; any other name's quotes.
*Reasons:* mid hands back half a spread per leg, silently, forever; a print is what
happened, not what is available; another name's quote makes the rail cross-sectional.

**Forbidden to do.** Interpolate across a gap; substitute the opposite side for an absent
one; fall back to a trade price; repair, clamp or discard a crossed book; reset an age
without a real price change; suppress an emission; order by anything but sequence.

**Book mark (engine 7 contract, phase2 L733/L765).** The book of record values positions
from the rail's `valuation_mark` for the position's direction. A crossed, locked or
zero-side quote does not move the book mark: retain the last valid mark, flag it stale,
emit. The stored mid mark is retired as a valuation input. Any consumer that needs a
reference price for sizing rather than valuation must name it as such; which consumers
those are is measured in the campaign 3 census, not decided here.

---

## 2. Position cell (engine 13)

**Job.** One per owned slice episode. The only stateful object for a position. Holds what
was paid, the deadline, the running extremes; computes excursion; takes in invalidation;
resolves the exit; writes the closing record.

**Lifecycle** [A-03]:

```
            PositionUpdate flat -> nonzero (owned slice)
                              |
                              v
   OPEN --(resolve picks a winner; one DeRiskRequirement emitted)--> EXITING
     |                                                                  |
     |  PositionUpdate -> 0 caused by any other author                  |  PositionUpdate -> 0
     v  (engine 8 safety exit)                                          v
  CLOSED (reason EXTERNAL:<token>)                                    CLOSED (reason = winner)
```

- `CLOSED` is absorbing and deaf. *Reason:* without it a second path fires a moment later on
  a position already flat — two sells for one buy.
- In `EXITING`, gates still evaluate and every triggered path is logged, but no second
  requirement is emitted. A higher-ranked path may escalate only if the live exit order is
  non-marketable; in this campaign every engine-13 exit is MARKET, so escalation is a no-op
  that is recorded, never acted on.
- A fill that crosses through zero closes the cell `EXTERNAL:SIGN_FLIP` and births a new one.
- Every opened cell eventually closes. A cell open at end of tape closes `END_OF_TAPE`,
  counted and reported separately.

**Reads.** `MarkRailUpdate` for its name (valuation, worst-side, forced, dwelled marks and
all flags, passed through unaltered). `PositionUpdate` for its slice (quantity, entry fills
with price, qty, timestamp, sequence). `Signal` for its slice (invalidation intake). The
session close fact for the birth date [A-11]. Both gate decisions (resolve phase only).
Run config.

**Frozen at birth** (never changes):
`cell_id` = `symbol|strategy_id|birth_fill_sequence|side` — derived from the tape, never
random or clock-based. `side`. `declared_archetype`. `entry_spread_ticks` =
`paying_mark − valuation_mark` from the last rail update at or before the birth fill.
`horizon_deadline_ns = min(birth_fill_ts + T, session_close_ns − cutoff_before_close_ns)`.
*Reason:* a deadline you can nudge becomes a dial tuned until the backtest looks nice.

**Entry mark** [A-05]. The exact quantity-weighted average of the episode's entry fills,
held as an exact rational (`sum(price_cents × qty) / sum(qty)`). Entry fills after birth
come only from partial fills of the same entry order; a same-side increase from a new
signal is refused at admission. Every entry fill is in the closing record.

**Excursion accounting** (pure functions, recomputed from the entry origin every event,
never accumulated). `sign = +1` long, `−1` short.

```
move_now_ticks    = sign × (valuation_mark   − entry_mark) / tick
move_worst_ticks  = sign × (worst_side_mark  − entry_mark) / tick
move_forced_ticks = sign × (forced_exit_mark − entry_mark) / tick
move_now_bps      = 10000 × move_now_ticks × tick / entry_mark
```

*Reason (recompute):* nothing drifts, and a dropped event costs only the extremes.
*Reason (frozen bps denominator):* a moving denominator makes a fixed bps threshold drift.

**Running extremes.** Seeded at the first reading after birth, never at zero. Updated
**before** the snapshot is frozen.

| Field | Absorbs | Carries |
|---|---|---|
| `best_so_far_ticks` / `worst_so_far_ticks` | every event, on `move_now_ticks` | the `sequence` that set it, plus the provenance of that event: `valuation_age_ns`, `valuation_side_absent`, `crossed`, `feed_gap_before` |
| `best_so_far_clean_ticks` | only events with valuation side present, not crossed, no feed gap | its `sequence` and `valuation_age_ns` |

*Reason (clean peak):* a crossed book flatters the favorable side; a trailing exit anchored
on it would chase a peak that never existed for the rest of the position's life. The
filter is facts, not thresholds, so no gate policy leaks into the cell.

**Invalidation intake** [A-10]. A `Signal` for an owned slice whose direction is FLAT or
opposite to the position latches `invalidation_pending` with the signal's sequence. It is
resolved at the next rail event for the name, inside one step with one frozen snapshot. A
REVERSE for an owned slice is treated as invalidation only; re-entry needs a later signal
after the cell closes.

**Step, two phases per rail event, per open cell, in `cell_id` order.**

1. *Advance.* Recompute moves, update extremes, freeze one immutable `PositionSnapshot`,
   publish it.
2. *Gates.* Both gates evaluate the **same** snapshot object as pure functions. Neither sees
   the other's output.
3. *Resolve.* Read the adverse decision, the favorable decision, the horizon predicate
   (`event_timestamp_ns ≥ horizon_deadline_ns`, unconditional on data quality) and
   `invalidation_pending`. Apply precedence. Transition. Emit at most one requirement.
   **The resolve phase may not alter any published value.** *Reason:* otherwise the snapshot
   the gates saw and the state that is written down drift apart.

**Precedence (total).** `ADVERSE > HORIZON > INVALIDATION > FAVORABLE`. Engine 8's safety
exits sit above all four by construction (they act on the book; the cell records the
result as `EXTERNAL`).

| Path | Proposed price | Wins over lower paths because |
|---|---|---|
| ADVERSE | `forced_exit_mark` | price vs FAVORABLE; label vs HORIZON/INVALIDATION (same price) |
| HORIZON | `forced_exit_mark` | label: the declared censor is the identification device |
| INVALIDATION | `forced_exit_mark` | price vs FAVORABLE |
| FAVORABLE | `dwelled_exit_mark` | never wins a tie |

The requirement's proposed price is the worst among triggered candidates, and its reason is
the highest-ranked triggered path. *Reason:* resolving toward the better outcome is
optimistic by exactly the worst events in the sample, and a wrong label corrupts the exit
mix the levels are judged by.

**Emits.**
- `PositionSnapshot`, every rail event, every open cell: `cell_id`, `state`,
  `event_timestamp_ns`, `event_sequence`, the four moves, the three extremes with their
  stamps, `size`, `side`, `declared_archetype`, `entry_spread_ticks`, `horizon_deadline_ns`,
  and every rail flag, unaltered. Cleans nothing, defaults nothing.
- `DeRiskRequirement` (once per episode): `source_layer="POSITION"`, slice-scoped, reason
  one of `ADVERSE_EXCURSION`, `HORIZON`, `INVALIDATION`, `FAVORABLE_EXCURSION`, quantity =
  full slice, order type MARKET [A-12].
- `PositionClosed`, once, write-once: `cell_id`, symbol, strategy, side; every entry fill
  (price, qty, ts, seq); `entry_spread_ticks`; `horizon_deadline_ns`; drawn stop level;
  exit reason; `triggered_paths` (each path triggered on the deciding event, its proposed
  price and trigger); proposed price; every exit fill (price, qty, ts, seq); the three
  extremes and the `sequence` that set each; flags `closed_on_stale_data`,
  `exited_on_unusable_data`, `lived_through_feed_gap`, `first_event_exit`,
  `stop_inside_round_trip`; `uncalibrated`; `supersedes`. **Raw prices only. No net figure,
  no winner flag, no fee applied.** *Reason:* the audit must be recomputable without asking
  the engine.

**Forbidden to read.** Wall clock; the raw quote feed (rail outputs only); mid; any other
cell's state or P&L; any fee schedule beyond the declared fee figure; the count of events
seen; any random source not seeded from the tape.

**Forbidden to do.** Buffer or queue emissions; clean, default or fill a flag; amend a
written record (a correction writes a superseding record); store the drawn stop level.

---

## 3. Favorable-excursion gate (engine 13) — fail-passive

**Asserts.** Where expected further return, given distance already moved in the position's
favor, stops accruing. Measured upstream on the signal, never tuned on results.

| Archetype | Declared shape | Consistent form |
|---|---|---|
| `liquidity_provision` | steep decay, zero after a short move | `fixed`, near, not trailing |
| `informed_flow_following` | persistent, decaying late | far `fixed`, or `trailing` |
| `declared_other` | stated and defended | shown consistent with the shape |

**Hard blocks, checked before any comparison:** `valuation_side_absent`; `crossed`;
`feed_gap_before`; not `dwell_window_clean`; not `warmed_up`; `symbol_quiet_ns > Q`.
**Does not block:** `valuation_age_ns` however large (an unmoved but still-confirmed price is
the firmest price there is); `locked` (allowed, recorded).
*Reason:* a phantom take-profit reads as a winning trade and nothing in the log says so; a
missed one shows up as a worse number and is bounded by the other exits.

**Forms.**
- `fixed`: fire when `move_now_ticks ≥ X`.
- `trailing`: armed only when `best_so_far_clean_ticks > R + round_trip_ticks`; then fire when
  `move_now_ticks ≤ best_so_far_clean_ticks − R`. `R = k × entry_spread_ticks`. Optional
  ceiling `C` only where the measured curve's sample runs out.
- `round_trip_ticks = entry_spread_ticks + fee_round_trip_ticks` (declared config).

**Emits** a `GateDecision`: `fire | none | suppressed(reason, flag state)`, form, proposed
price (`dwelled_exit_mark`, always), reference fired against (`X`, or peak + `R` with the
peak's sequence), `event_sequence`. Holds no state. Never reads the adverse gate,
`forced_exit_mark`, `worst_side_mark` or `paying_mark`.

---

## 4. Adverse-excursion gate (engine 13) — fail-safe

**Asserts.** The same measured curve, read on the adverse side of entry.
`liquidity_provision` rises then falls (crossing late); `informed_flow_following` declines
from the start (crossing early). A level tighter than the crossing is insurance, and its
premium (expected return given up, bps per trade) must be declared.

**Never skips.** Every rail event, every open cell, a recorded decision: `fire` or `hold`.
*Reason:* "never declines" is only auditable if the holds are written down.

**Comparison** on `move_worst_ticks`: fire when `move_worst_ticks ≤ −L` [A-09].

| Condition | Handling |
|---|---|
| crossed | none needed; `worst_side_mark` is already the worse side |
| side absent / name quiet | evaluate on the held price, unchanged |
| either for longer than `A` | fire unconditionally, trigger `BLIND`, flag `exited_on_unusable_data` |
| feed gap | evaluate on the visible price; flag `lived_through_feed_gap`; never infer an unobserved breach |
| locked | nothing special; recorded |

**Level.** `L` drawn once per cell from a flat distribution over the whole-tick band
`[centre − B/2, centre + B/2]`, seeded by SHA-256 of `cell_id`; **recomputed** each event
from `cell_id` and frozen run config, never stored, never re-drawn. The band must lie inside
`[lo, hi]` (checked at load, never clamped). *Reasons:* a fixed level lands on shared focal
points and fills worse (congestion, any size) and becomes an inferable footprint (predation,
at size); clamping rebuilds the focal point at the edge.

**Emits** a `GateDecision`: `fire | hold`, `L`, trigger (`LEVEL` / `BLIND`), proposed price
(`forced_exit_mark`, always), flag state, `event_sequence`. Holds no state. Never reads the
favorable gate or `dwelled_exit_mark`.

---

## 5. Exit plan and routing (engine 9)

- A `DeRiskRequirement` with `source_layer="POSITION"` is accepted by the same copy path as
  engine 8's requirements, slice-scoped, MARKET, through `check_order` [A-12].
- Every engine-13 exit is routed aggressive in this campaign, including FAVORABLE and
  INVALIDATION. *Reason:* the passive fill-eligibility audit has not passed; a passive
  take-profit inherits a bias that is optimistic, not noisy.
- `ADVERSE_EXCURSION` joins the stop-slippage reason set; `HORIZON`, `INVALIDATION` and
  `FAVORABLE_EXCURSION` do not [A-13].

## 6. Entry admission (engine 9) [A-04]

For an owned alpha, an **entry** order is refused, with a recorded reason, when the latest
rail update for the name shows: paying side absent (`NO_PAYING_PRICE`); crossed
(`CROSSED_AT_BIRTH`); or decision time at or past the session cutoff
(`CUTOFF_ALREADY_PASSED`). Also refused: any same-side increase while the slice's cell is
OPEN or EXITING (`NO_SCALE_IN`). Refusals are counted by reason and reported with results.
*Reason:* the entry price is the origin every later number counts from; refusals cluster in
stress, so a silent refusal is survivorship.

## 7. Sink

An object that reads engine outputs and cannot affect any engine output is a sink, not a
component. Delete it and every number is identical. The per-event decision log and the
closing-record store are sinks. Checked by battery member 1 (a run with sinks detached is
byte-identical on every non-sink output).
