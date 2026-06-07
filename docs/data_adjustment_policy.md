# Data adjustment policy

This repository keeps replay and backtest inputs in their raw, unadjusted form within a single session.

- Raw L1 NBBO is preserved for in-session backtests.
- Replays must not cross a known split or dividend ex-date for a universe symbol unless the boundary prices are explicitly adjusted.
- The ex-date integrity guard in the corporate-actions reference tables enforces this policy before a replay window is accepted.

The policy is intentionally strict: ex-date discontinuities are real market events and must not be silently smoothed or ignored during replay.
