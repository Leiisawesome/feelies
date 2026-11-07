# Standing results

The design rests on these. They are not re-derived during the build and not relitigated
without a written amendment.

**R1. Exits cannot manufacture edge.** Under a driftless (martingale) price and any bounded
stopping time, expected P&L equals minus costs, whatever the barrier geometry. Exits only
redistribute the entry's mean across hit rate, holding-time tail, skew and variance.
Consequence: any backtest improvement from moving an exit parameter is fitting.

**R2. Barrier attribution.** Driftless tape, adverse barrier at distance `a` below entry,
favorable at `b` above: `P(favorable first) = a / (a + b)` — proportional to the distance of
the *other* barrier. Test with an asymmetric pair (1:2 separates 1/3 from 2/3); the
symmetric case hides an inverted formula.

**R3. Holding time needs a wall.** `E[τ] = ab/σ²` and the tail time constant scales with
`(a+b)²/σ²`. Without a declared deadline, holding time is a by-product of barrier spacing
(double both barriers, quadruple the hold), and every finite backtest censors anyway, by
entry time and regime. A declared `T` swaps an uncontrolled censor for a chosen one and makes
the stopping time bounded, so R1 and R2 hold exactly.

**R4. Precedence resolves toward the worse outcome.** A single event can breach both a
trailing give-back and a stop. Resolving favorable-first is optimistic by exactly the worst
realizations.

**R5. Touch-implies-fill is optimistic on both gates at once.** Stop booked at its level
ignores gapping through it; take-profit booked on a touch ignores queue position. Same sign,
so they compound. The split exit prices (`forced_exit_mark`, `dwelled_exit_mark`) remove the
sign-consistency; they are not a fill model.

**R6. Staleness travels with the adverse regime.** Quotes go stale and sides vanish when
participants pull back, which is when the large moves happen. Treating age as a warning is
correct conditioning, not caution. Corollary: a fail-passive take-profit goes quiet exactly
when the big gains are available; that cost is intentional and must be measured
(suppression counts), not loosened.

**R7. Gate geometry is archetype-coupled.** The take-profit, the stop and the deadline are
three readings of two measurements on the signal: forward return against distance moved
(both sides of entry) and against elapsed time. The engine is not archetype-neutral.

**R8. Mechanical levels are an observable.** Fixed stop levels land on shared focal points
(congestion, any size) and form an inferable footprint (predation, at size). Hence the
drawn level.

**R9. The entry starts one spread behind.** Entry at the paying side, valuation at the
receiving side: the first reading of an aggressive entry is minus the spread at entry,
exactly. A cell that opens at zero has lost the spread from its accounting.

**R10. Coverage boundary.** The battery protects building the engine correctly (phase 1).
It is structurally blind to whether the measured curves were fitted (phase 2) and to fill
realism (phase 4). Those phases need their own instruments.
