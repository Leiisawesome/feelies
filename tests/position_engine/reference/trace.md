# Reference trace

One row per behaviour. Contract lines are current `contracts.md`. The function is
`module:qualname` in `tests/position_engine/reference`. The test id is a function
under `tests/position_engine`. Rail rows are P-22a1. Engine rows are P-22a2.

| Behaviour | Contract | Function | Test |
|---|---|---|---|
| One update per quote, both orientations, executable-side marks | §1:75–93 | rail.py:ReferenceRail.on_quote | test_slippage_worsens_forced_mark |
| forced_exit_mark is worst_side_mark worsened by S ticks, long lower and short higher (D-40) | §1:87; §9:428–430 | rail.py:ReferenceRail.on_quote | test_slippage_worsens_forced_mark |
| Dwell window (t − D, t] plus the current quote; D = 0 holds only the current quote and warmed_up is true from the first quote (D-41) | §1:103–106; §9:431–433 | rail.py:ReferenceRail.on_quote | test_dwell_window_drops_quote_older_than_t_minus_d |
| dwell_window_clean is false when the window holds an absence, a cross, or a feed gap | §1:89 | rail.py:ReferenceRail.on_quote | test_dwell_window_drops_quote_older_than_t_minus_d |
| symbol_quiet_ns is feed silence and resets on any quote | §1:95–96; §9:468–471 | rail.py:ReferenceRail.on_quote | test_quiet_clock_triplet |
| Ages advance only when that side's price changes | §1:92; §1:114–115 | rail.py:ReferenceRail.on_quote | test_rail_age_advances_only_when_the_price_changes |
| Non-VALID class: both rail sides absent; absence clock from the last usable value (D-62) | §9:468–475 | rail.py:ReferenceRail.on_quote | test_d62_class_marks_both_sides_absent |
| Absent side republishes the last present price (D-82) | §9:490–492 | rail.py:ReferenceRail.on_quote | test_held_price_republishes_last_present |
| Before any usable value the price is None and the absence clock runs from the symbol's first quote (D-82) | §9:490–492 | rail.py:ReferenceRail.on_quote | test_none_before_any_usable_value |
| feed_gap_before is false on the rail; the battery seam sets it | §1:103; §8:417–418 | rail.py:ReferenceRail.on_quote | test_d62_class_marks_both_sides_absent |
| D and S are read in the constructor from FEELIES_RAIL_DWELL_NS and FEELIES_RAIL_SLIPPAGE_TICKS until P-40 PlatformConfig (D-40) | §9:428–430 | rail.py:ReferenceRail.__init__ | test_env_read_in_a_fresh_child |
| Whole-cent prices; a sub-cent price raises (D-78) | §9:487–489 | rail.py:_cents | test_rail_subcent_price_raises |
| A later clean dwell window is not blocked by an earlier cross (D-87) | §1:103–106; §9:431–433 | rail.py:ReferenceRail.on_quote | test_dwell_window_drops_quote_older_than_t_minus_d |
| cell_id is symbol, strategy, birth quote, side (D-44) | §2:197 | engine.py:cell_id_for | test_band_draw_and_cell_id |
| Band draw L is recomputed from cell_id; never stored (D-44, D-83) | §9:440–444 | engine.py:band_level | test_band_draw_and_cell_id |
| BLIND fires only when an absence or quiet is strictly greater than A (D-42) | §9:434–436 | engine.py:evaluate_adverse | test_blind_is_strictly_greater_than_a |
| Favorable tokens stay in order; reason is the first and suppressions keeps all (D-43, D-80) | §9:437–439 | engine.py:suppression_tokens | test_favorable_tokens_in_order |
| A clean dwell flag does not carry an earlier cross into the favorable gate (D-87) | §9:437–439 | engine.py:suppression_tokens | test_precondition_clean_window_after_a_cross |
| Extremes, including best_clean, seed on the first clean reading and never at zero (D-79, D-100) | §2:231–241 | engine.py:Cell.update_extremes | test_extremes_seed_on_the_first_clean_reading |
| Give-back R floors at 1; k is Fraction(repr(k)) (D-83, D-101) | §9:445–447 | engine.py:giveback_r | test_giveback_r_floors_at_one |
| Precedence is ADVERSE, HORIZON, INVALIDATION, FAVORABLE; the price is the worst (D-47) | §2:265–279 | engine.py:worst_price | test_precedence_picks_adverse_and_the_worst_price |
| Path rank is total | §2:265–268 | engine.py:path_rank | test_precedence_picks_adverse_and_the_worst_price |
| In EXITING a higher path is ESCALATION_NOOP and emits no order (D-95) | §2:167–169 | engine.py:_escalate | test_one_requirement_and_escalation_noop |
| An exit fill reduces open quantity; a partial fill emits no second requirement (D-76) | §2:170–173 | engine.py:Cell.consume | test_partial_exit_reduces_the_next_snapshot |
| The same entry order extends the cell; a different same-direction order is refused (D-77) | §2:203–208 | engine.py:Cell.extend | test_same_order_extends_and_scale_in_is_refused |
| An opposite fill closes the overlap and births the excess (D-81) | §2:174–176 | engine.py:PositionEngine._on_slice | test_sign_flip_closes_the_overlap_and_births_the_excess |
| A non-whole-cent fill price raises (D-78) | §9:487–489 | engine.py:whole_cents | test_subcent_price_raises |
| A move is None exactly when its mark is None (D-99) | §2:222–223 | engine.py:move_cents | test_none_marks_produce_none_moves |
| Entry spread is the paying mark minus the valuation mark | §2:198–199 | engine.py:entry_spread_ticks | test_giveback_r_floors_at_one |
| Economics stay integer cents on the legs; the close carries no net (D-46, D-104) | §2:298–300; §9:462–467 | engine.py:Cell.entry_cost | test_same_order_extends_and_scale_in_is_refused |
| order_id is cell_id, EXIT, attempt from 1; the side reduces the cell (D-98, D-106) | §2:286–291 | engine.py:PositionEngine._emit_requirement | test_n3_attempt_suffix |
| A REJECTED live exit is re-emitted on the next usable rail event; reason and deciding event stay (D-106, D-62) | §2:157–161 | engine.py:PositionEngine._on_ack | test_g11_reemits_on_the_next_usable_rail_event |
| Usable means the executable exit side is present (D-62, D-106) | §2:159; §9:468–470 | engine.py:_exit_side_usable | test_g11_reemits_on_the_next_usable_rail_event |
| No second requirement while one is live (D-106) | §2:161; §2:172 | engine.py:PositionEngine._emit_requirement | test_g11_no_reemission_without_a_rejection |
| Attempts count from 1 and each attempt is recorded (D-106) | §2:159–161 | engine.py:PositionEngine._emit_requirement | test_g11_attempt_numbering |
| END_OF_TAPE uses the last usable executable side, or None with closed_on_stale_data, and emits no requirement (D-84, D-102, D-109) | §2:178–186 | engine.py:PositionEngine._close_end | test_end_of_tape_and_missing_exit_side |
| finalize closes open cells after the last replay event (D-97) | §8:422–424 | engine.py:PositionEngine.finalize | test_end_of_tape_and_missing_exit_side |
| The last usable rail update is the one whose exit side was present (D-84, D-102) | §2:178–180 | engine.py:Cell.note_rail | test_end_of_tape_and_missing_exit_side |
| Exit reasons are the closed set, mapped onto requirement reasons (D-47) | §9:450–453 | engine.py:PositionEngine._resolve | test_precedence_picks_adverse_and_the_worst_price |
| Closing flags are taken at the deciding event, or at the last usable update for END_OF_TAPE (D-47) | §9:454–461 | engine.py:PositionEngine._emit_close | test_end_of_tape_and_missing_exit_side |
| With no session close the deadline is the birth timestamp plus T (D-45) | §9:448–449 | engine.py:PositionEngine._birth | test_deadline_is_birth_plus_horizon |
| Reversed gate order publishes the same events | §8:413–414 | engine.py:PositionEngine._evaluate | test_gate_order_does_not_change_published_events |
| At most one snapshot per cell and rail event (D-86, D-103) | §2:255–256 | engine.py:PositionEngine._publish_snapshot | test_one_snapshot_per_rail_event |
| A FLAT or opposite signal latches invalidation for the next rail event | §2:247–251 | engine.py:PositionEngine._on_signal | test_precedence_picks_adverse_and_the_worst_price |
| The engine subscribes in attach, which the attribution cursor handler precedes (D-96) | §8:419–421 | engine.py:PositionEngine.attach | test_band_draw_and_cell_id |
| Rails alone birth no cell; an entry fill does, and the next rail is that cell's boundary | §2:145–148 | engine.py:PositionEngine._birth | test_precondition_entry_fill_births_the_cell |
| After a close, a later entry fill births a new cell | §2:145–148 | engine.py:PositionEngine._on_slice | test_precondition_later_entry_births_a_new_cell |
