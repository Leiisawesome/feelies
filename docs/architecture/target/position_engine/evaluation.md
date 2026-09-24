# Evaluation — how this campaign's results are judged

Operator decisions D-14..D-17, 2026-09-24. This file fixes the bar before any engine-on
result exists. Changing it follows the amendment rule in `battery.md`.

## 1. Questions and evidence

| Question | Evidence | Gate |
|---|---|---|
| Legacy unchanged? | Legacy oracle: frozen at exec-tools-v1, 64 parity constants, APP 2026-03-26 = 20 fills, net 103.93, trade hash 0601295a…17df3 | every rung; hold unless a declared break passes §2 |
| Engine correct? | The battery: eleven members, synthetic known answers, broken engines B1–B11 | stage gates A–E |
| Engine-on unchanged after pinning? | Position oracle: APP 2026-03-26 through `configs/bt_position_arbitrary_not_calibrated.yaml`, pinned at P-99 | every rung after P-99; §2 applies |
| Engine-on differences explained? | P-95 attribution diff (§3) | P-99 report; campaign 15 review |
| Engine better? | Campaign 14E (§4) | gate for campaign 15 |

No real-session result from this campaign is evidence that the engine is better. The APP day
is a regression oracle, never a fitness function. No parameter is changed in response to an
APP result.

Why "better" is not "higher PnL": on a driftless price, every exit rule has zero expected
gross result (optional stopping; battery member 3 tests exactly this). Exit management adds
value only by (a) matching holding time to the signal's measured decay, (b) exiting when the
entry premise is invalidated, (c) cutting the loss tail, which raises risk-adjusted return at
fixed capital, (d) taking profit at a reversion target where the archetype justifies one
(`liquidity_provision`, load check L5). Honest-accounting changes — executable-side
valuation, worst-price booking — move marks and booked results weakly down, never up.

## 2. Declared-break protocol (pre-registration)

A rung that may move a pinned constant of either oracle states, in its prompt, before the
pre-capture:

- PREDICTED MOVES: each constant expected to move, with direction (up / down / changed), or "none".
- FILLS: whether fills are predicted to change (yes / no) and through which mechanism.
- MECHANISM: why, citing contracts or amendments, with no reference to results.

After the post-capture:

- a constant moved that was not predicted: blocked;
- a predicted direction is contradicted: blocked;
- a predicted move did not occur: reported; the operator decides;
- an honest-accounting change that improves a result: treated as a defect signal, blocked
  until explained.

An improved result is never a reason to accept a break. The operator declares the break only
after this check passes. The ledger records the prediction and the outcome side by side.

## 3. P-95 attribution diff

Report-only tool; location fixed by the P-95 census. It runs one tape through two
configurations that share the alpha's entry logic: legacy exits and engine-on.

- Episodes are matched by (symbol, strategy_id, entry signal sequence).
- Each episode gets one class:
  - SAME: identical fills;
  - EXIT_CHANGED: same entry, different exit; carries the engine reason (ADVERSE / HORIZON /
    INVALIDATION / FAVORABLE / EXTERNAL / END_OF_TAPE) and the legacy exit reason;
  - ENTRY_REFUSED: the engine arm refused the entry; carries the refusal reason;
  - ENGINE_ONLY: entry present only in the engine arm. Must be empty; non-empty is a defect.
- Per episode: entry and exit prices, net result, holding time, maximum adverse excursion,
  for both arms.
- Per class: count and totals.
- No p-values and no "better" statement. Every report is labelled descriptive, with its day count.
- Tested first on a synthetic tape whose classes are constructed in advance.

## 4. Campaign 14E — calibration and evaluation (gate for campaign 15)

Not built in this campaign. Registered here so that its bar is fixed before any engine-on
result exists.

- Data: a census of cached days comes first. The in-sample / out-of-sample split is fixed by
  date before any run.
- Calibration, in-sample only, from measurement:
  - T from the alpha's measured forward-return decay;
  - adverse band from the in-sample maximum-adverse-excursion distribution of the alpha's own entries;
  - favorable target from the measured reversion distance, for liquidity-provision alphas only.
  - `curve_ref` replaces ARBITRARY_NOT_CALIBRATED.
- Evaluation, out-of-sample:
  - paired and episode-matched: same entries in both arms, P-95 matching;
  - CPCV with purge and embargo;
  - strata at minimum volatility × tick-constraint;
  - deflated Sharpe with N = every configuration tried, counted in the ledger;
  - full cost stack;
  - exits MARKET in both arms until the passive fill-eligibility audit passes.
- Switch-on bar, all required:
  1. Mean: the paired net difference per episode (engine − legacy) has a 95% CI lower
     bound above −δ. δ is fixed in the 14E plan before any out-of-sample data is read.
  2. Tail: the 5% CVaR of episode net result is strictly better in the engine arm, with a
     bootstrap CI excluding zero.
  3. Risk-adjusted: the deflated Sharpe probability that the engine arm's Sharpe exceeds
     the legacy arm's is at least 0.95.
  4. No stratum has a paired mean difference significantly negative at 5% after Holm correction.
  5. The battery is green on the calibrated configuration.
- On failure: campaign 15 does not start. Fix the engine or the calibration, never the bar.

## 5. Where real-session battery members run

The main `check` job excludes the APP cache; the `parity oracle` job has it. Battery members
that use the real session carry the pytest marker `battery_real`. The `parity oracle` job
collects them with `FEELIES_REQUIRE_BASELINE_CACHE=1`, so that a missing cache fails rather
than skips. The marker registration and the CI job change land with the first such member
(P-21). (D-20)
