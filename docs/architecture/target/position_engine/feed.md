# Feed facts

Measured, not assumed. Each entry states what was measured, on what, and what it changes.

## F1. Sequence numbers: unique, increasing, not consecutive per name

Measured 2026-08 on one full session (09:45–15:45 ET), 8 midcap names across both tapes,
Massive `/v3/quotes`: unique within a name PASS; strictly increasing PASS (partly circular
at timestamp ties, where the sort breaks ties by sequence); consecutive NO — median share
of the number range used by one name 0.0242%. Zero values shared between names on one
tape: the counter belongs to the whole tape.

Consequence: a dropped message for one name cannot be told apart from another name's
traffic. `feed_gap_before` comes from the connection (a reported interruption), never from
the numbers. On replay it is always false, correctly.

Feelies today (census 2026-09-23 at `e2b2745f`): `MassiveNormalizer._check_gap` flags a gap
when `seq > prev_seq + 1` keyed by `(symbol, feed_type)` (`massive_normalizer.py:840-857`).
On the APP 2026-03-26 cache day that predicate is true for 70,599 of 87,898 quotes. It is
unreachable on cache replay (no normalizer is built in BACKTEST) and live on the WebSocket
path, where `degrade_on_data_gap` (default true) flattens. **Out of scope here (backtest
only); first item of the paper/live campaign.** Whether WebSocket `q` shares the REST
counter is inferred, not yet measured.

## F2. Timestamp ties

854 within-name timestamp ties in the F1 session. Ordering is by sequence; timestamps
measure durations only.

## F3. Odd lots are in the published best price

27,973 quotes below 100 shares in the F1 session (an earlier ten-minute sample suggested
zero; that conclusion was wrong). The published best is the true best; sizes are published
so thin quotes are visible. Open: the denominator (fraction of all quotes), and higher-priced
names, where odd lots concentrate. Bad-case direction if wrong: results understated, not
flattered. Phase 2 item, not a blocker.

## F4. Crossed and locked quotes

F1 session (auctions excluded): 17 crossed-or-locked combined. APP 2026-03-26 cache day,
all 87,899 quotes: bid > ask 60; bid == ask 66; a side ≤ 0 4; a size of 0 4. Of 7,489 quotes
arriving while the APP position was open on the oracle run: 1 locked, 0 crossed, 0 zero-side.
Consequence: the book-mark retain-last rule (campaign 3) is expected to move little on the
oracle day; measured by capture, not argued.

## F5. Two clocks

`sip_timestamp − participant_timestamp` measured as consolidation latency in the F1 work.
Replay has one clock (feelies advances the simulated clock to exchange ts + latency before
yield); live has two. Deadline exits shift with unmodelled latency; one reason nothing here
is execution-validated.

## Coverage gap (standing)

F1–F4 come from calm days, liquid names, auctions excluded. Crossed-book rates, tie counts
and odd-lot fractions are floors, not typical values. Phase 2 measurement must not reuse
these as its basis.
