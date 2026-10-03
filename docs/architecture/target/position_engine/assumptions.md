# Assumption register

Append-only. Format per entry: ASSUMES / TOLERABLE BECAUSE / FALSIFIED BY / EXPIRES WHEN /
BLAST RADIUS. Carried from v2 unless marked NEW.

**AS-01 Fills.** ASSUMES: an exit requirement becomes a fill at the router's touch price.
TOLERABLE BECAUSE: entry is priced at the paying side and adverse exits at the worse side
plus slippage, so the obvious optimism is removed. FALSIFIED BY: real fills systematically
worse than the quote at the deciding event. EXPIRES WHEN: a fill model exists.
BLAST RADIUS: every number, worst for stop exits, which fire when fills are hardest.

**AS-02 Consolidated best is reachable.** ASSUMES: the NBBO is a usable stand-in for prices
reachable by us. TOLERABLE BECAUSE: sizes are published beside every price.
FALSIFIED BY: position sizes routinely exceeding quoted size at the marking price.
EXPIRES WHEN: a fill model exists. BLAST RADIUS: total.

**AS-03 Quoted extremes.** ASSUMES: transactable prices = quoted prices. TOLERABLE BECAUSE:
it errs modest. FALSIFIED BY: fills better than the quoted extreme. EXPIRES WHEN: a fill
model exists. BLAST RADIUS: trailing exits.

**AS-04 Cent grid.** ASSUMES: every price is on a one-cent grid. TOLERABLE BECAUSE: true for
this universe above $1. FALSIFIED BY: any sub-penny quote or a name below $1.
EXPIRES WHEN: universe or tick regime changes. BLAST RADIUS: whole-tick checks become false
alarms; tick thresholds stop being comparable across names.

**AS-05 Deadline source.** ASSUMES: `T` is set from the signal's measured decay, upstream,
frozen before any exit logic runs. FALSIFIED BY: any record of `T` changed after seeing a
result. EXPIRES WHEN: an evidence-based decay exit exists. BLAST RADIUS: turnover, capacity,
the meaning of the exit mix.

**AS-06 Time vs updates.** ASSUMES: elapsed time is independent of the price path in a way
update counts are not. EXPIRES WHEN: never (structural). BLAST RADIUS: barrier attribution.

**AS-07 Held price.** ASSUMES: holding the last valid price is least wrong while a side is
absent. TOLERABLE BECAUSE: every alternative hides itself; a held price with a growing age
announces itself. FALSIFIED BY: what traded during absences being systematically off the
held price in one direction. BLAST RADIUS: every mark during a gap.

**AS-08 Name-level silence.** ASSUMES: name-level silence stands in for "this side is no
longer confirmed". FALSIFIED BY: favorable exits clustering just under `Q`.
EXPIRES WHEN: venue-level data. BLAST RADIUS: the frozen-quote phantom take-profit.

**AS-09 Dwell as queue position.** ASSUMES: a fixed dwell `D` stands in for queue position.
The weakest assumption in the design. FALSIFIED BY: fill rates varying with size, time of
day or spread in ways `D` ignores. EXPIRES WHEN: any live fill data. BLAST RADIUS: every
favorable exit.

**AS-10 Blind limit is bookkeeping.** ASSUMES: firing after `A` is honest bookkeeping, not
risk reduction. FALSIFIED BY: any claim that `A` bounds loss. BLAST RADIUS: any result that
blends flagged exits with ordinary ones.

**AS-11 No inferred breaches.** ASSUMES: not inferring unobserved breaches across a feed gap
is safer than assuming them. FALSIFIED BY: measured breach-and-return inside gaps at a rate
that matters. BLAST RADIUS: understated stop rates where gaps happen.

**AS-12 Congestion before predation.** ASSUMES: focal-point congestion is the operative cost
of a fixed level at current size. FALSIFIED BY: fills at fixed levels systematically worse
than at neighbouring prices. BLAST RADIUS: realized cost of every stop exit.

**AS-13 Archetype label correct.** ASSUMES: the declared archetype is right.
EXPIRES WHEN: never; needs standing scrutiny. BLAST RADIUS: severe and quiet — load check L5
verifies consistency with the label, never the label itself.

**AS-14 Quote-driven.** ASSUMES: the engine only needs to act on a quote event.
FALSIFIED BY: a deadline that should have fired materially before the next quote while an
exit was available. BLAST RADIUS: deadline exits fire late in quiet markets.

**AS-15 (NEW) Invalidation one quote late.** ASSUMES: resolving an invalidation at the next
rail event rather than at the signal event costs little. TOLERABLE BECAUSE: it keeps every
exit decision inside one step on one frozen snapshot. FALSIFIED BY: a measured gap between
signal and next quote that is material against the signal's horizon. BLAST RADIUS:
invalidation exit prices.

**AS-16 (NEW) Aggressive favorable exits.** ASSUMES: routing take-profits aggressive is the
honest choice until the passive fill-eligibility audit passes. TOLERABLE BECAUSE: an
aggressive exit pays the spread it really pays; a passive one here inherits an optimistic
bias. EXPIRES WHEN: the passive router audit passes. BLAST RADIUS: favorable-exit cost is
overstated relative to a correct passive exit.
