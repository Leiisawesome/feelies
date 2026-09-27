# Reference trace (rail rows, P-22a1)

Engine rows land in P-22a2. Line numbers are `contracts.md` at the P-22a1 spec commit.

| Behaviour | Contract |
|---|---|
| One update per quote, both orientations, executable-side marks | §1:75–93 |
| `forced_exit_mark` is `worst_side_mark` worsened by `S` ticks (long lower, short higher) | §1:87; §9:421–423 |
| Dwell window `(t − D, t]` plus the current quote; `D = 0` holds only the current quote and `warmed_up` is true from the first quote | §1:103–106; §9:424–426 |
| `dwell_window_clean` is false when the window holds an absence, a cross, or a feed gap | §1:89 |
| `symbol_quiet_ns` is feed silence and resets on any quote | §1:95–96; §9:463–464 |
| Ages advance only when that side's price changes | §1:92; §1:114–115 |
| Non-VALID class: both rail sides absent; absence clock from the last usable value | §9:461–478 |
| Absent side republishes the last present price | §9:483–485 |
| Before any usable value the price is `None` and the absence clock runs from the symbol's first quote | §9:483–485 |
| `feed_gap_before` is false on the rail; the battery seam sets it | §1:103; §8:399–401 |
| `D` and `S` read in the constructor from `FEELIES_RAIL_DWELL_NS` and `FEELIES_RAIL_SLIPPAGE_TICKS` until P-40's `PlatformConfig` | §9:421–423 |
| Whole-cent prices; a sub-cent price raises | §9:480–482 |
