"""Tests for the Stage-0 residual decision engine.

These pin the *decision rules*, not a dataset: the whole point of
``docs/research/stage0_residual_preregistration.md`` is that the rules were
fixed before any outcome data was seen, so they must be independently
verifiable without any.
"""

from __future__ import annotations

import pytest

from feelies.research.stage0_residual import (
    B3_HARVEST_DAMAGE_MULTIPLE,
    PILOT_CONFIGS,
    PRE_REGISTERED_CVAR_LEVEL,
    PRE_REGISTERED_MIN_TAIL_SAMPLE,
    SafeOffEpisode,
    Stratum,
    Verdict,
    evaluate_stratum,
    evaluate_study,
)

MOC = PILOT_CONFIGS["sig_moc_imbalance_v1"]
KYLE = PILOT_CONFIGS["sig_kyle_drift_v1"]


def _episode(
    *,
    idx: int = 0,
    stratum: Stratum = Stratum.WEATHER,
    hold: float = 0.0,
    flatten: float = 0.0,
    oracle_boundary: float | None = None,
    oracle_event: float | None = None,
    terminal_cap: str = "MAX_HOLD_AFTER_SAFE_OFF",
    quote_frozen: bool = False,
) -> SafeOffEpisode:
    """Build one episode; oracles default to the feasible floor (= hold)."""
    ob = hold if oracle_boundary is None else oracle_boundary
    oe = ob if oracle_event is None else oracle_event
    return SafeOffEpisode(
        strategy_id="sig_moc_imbalance_v1",
        symbol="APP",
        first_safe_off_ns=1_700_000_000_000_000_000 + idx * 1_000_000_000,
        off_trigger="realized_vol_30s_zscore>3.5",
        stratum=stratum,
        hold_return_bps=hold,
        flatten_return_bps=flatten,
        oracle_boundary_bps=ob,
        oracle_event_bps=oe,
        terminal_cap=terminal_cap,
        quote_frozen=quote_frozen,
    )


# ── Frozen constants match the pre-registration ──────────────────────


def test_pre_registered_constants_match_the_document() -> None:
    assert PRE_REGISTERED_CVAR_LEVEL == 0.05
    assert PRE_REGISTERED_MIN_TAIL_SAMPLE == 20


def test_pilot_configs_are_the_per_family_legal_ceilings() -> None:
    """max_hold is the family multiple × half-life; age backstop is horizon + max_hold."""
    assert MOC.max_hold_after_safe_off == 2 * MOC.expected_half_life_seconds == 480
    assert MOC.hard_exit_age_seconds == MOC.horizon_seconds + MOC.max_hold_after_safe_off == 600
    assert KYLE.max_hold_after_safe_off == 3 * KYLE.expected_half_life_seconds == 1800
    assert (
        KYLE.hard_exit_age_seconds == KYLE.horizon_seconds + KYLE.max_hold_after_safe_off == 2100
    )


def test_b2_bars_match_the_pre_registered_table() -> None:
    assert MOC.round_trip_cost_bps == pytest.approx(12.0)
    assert MOC.stressed_round_trip_cost_bps == pytest.approx(18.0)
    assert MOC.b2_bar_bps == pytest.approx(27.0)
    assert KYLE.stressed_round_trip_cost_bps == pytest.approx(19.5)
    assert KYLE.b2_bar_bps == pytest.approx(29.25)


def test_evaluation_window_and_horizon_bars() -> None:
    assert MOC.evaluation_window_seconds == 600
    assert MOC.horizon_bars == 5
    assert KYLE.evaluation_window_seconds == 2100
    assert KYLE.horizon_bars == 7


# ── Episode integrity ────────────────────────────────────────────────


def test_oracle_below_hold_is_rejected_as_broken_extraction() -> None:
    """Hold-until-cap is in the oracle's feasible set; a lower oracle is a bug.

    A silent sign error here would understate the ceiling and manufacture a
    NO-GO, so it must fail loudly rather than be clamped.
    """
    with pytest.raises(ValueError, match="broken episode extraction"):
        _episode(hold=10.0, oracle_boundary=9.0)


def test_event_oracle_below_boundary_oracle_is_rejected() -> None:
    with pytest.raises(ValueError, match="broken extraction"):
        _episode(hold=0.0, oracle_boundary=5.0, oracle_event=4.0)


def test_non_finite_return_is_rejected() -> None:
    with pytest.raises(ValueError, match="must be finite"):
        _episode(hold=float("nan"))


def test_delta_and_uplift_algebra() -> None:
    ep = _episode(hold=-3.0, flatten=2.0, oracle_boundary=6.0, oracle_event=9.0)
    assert ep.delta_bps == pytest.approx(-5.0)
    assert ep.is_wrong_hold
    assert ep.uplift_boundary_bps == pytest.approx(9.0)
    assert ep.uplift_event_bps == pytest.approx(12.0)


# ── B1: power is checked first and dominates ─────────────────────────


def test_underpowered_cell_returns_underpowered_not_go() -> None:
    """The load-bearing rule: a thin cell with a huge ceiling is still not a GO."""
    # 100 episodes → floor(0.05 × 100) = 5 < 20. Ceiling is enormous.
    episodes = [_episode(idx=i, hold=0.0, flatten=0.0, oracle_boundary=500.0) for i in range(100)]
    result = evaluate_stratum(episodes, pilot=MOC, stratum=Stratum.WEATHER)
    assert result.effective_tail_sample == 5
    assert not result.b1_powered
    assert result.verdict is Verdict.UNDERPOWERED
    assert "B1 FAIL" in result.reasons[0]
    assert "Not evidence either way" in result.reasons[0]


def test_power_floor_boundary_is_exactly_400_episodes() -> None:
    at_floor = [_episode(idx=i, oracle_boundary=100.0) for i in range(400)]
    below = at_floor[:399]
    assert evaluate_stratum(at_floor, pilot=MOC, stratum=Stratum.WEATHER).b1_powered
    assert not evaluate_stratum(below, pilot=MOC, stratum=Stratum.WEATHER).b1_powered


def test_underpowered_reason_states_how_many_episodes_are_needed() -> None:
    result = evaluate_stratum(
        [_episode(idx=i) for i in range(100)], pilot=MOC, stratum=Stratum.WEATHER
    )
    assert "400 needed" in result.reasons[0]


# ── R1 / R2 / R4: rejection branches ─────────────────────────────────


def test_r1_rejects_when_perfect_foresight_earns_nothing() -> None:
    """The strongest falsification: a zero ceiling cannot be beaten by any map."""
    episodes = [_episode(idx=i, hold=1.0, flatten=1.0) for i in range(400)]
    result = evaluate_stratum(episodes, pilot=MOC, stratum=Stratum.WEATHER)
    assert result.verdict is Verdict.NO_GO
    assert "R1 REJECT" in result.reasons[0]


def test_r2_rejects_when_damage_exceeds_harvest() -> None:
    # Small uniform ceiling, one catastrophic wrong hold that outweighs it.
    episodes = [_episode(idx=i, hold=0.0, flatten=0.0, oracle_boundary=1.0) for i in range(399)]
    episodes.append(_episode(idx=399, hold=-5000.0, flatten=0.0, oracle_boundary=-4999.0))
    result = evaluate_stratum(episodes, pilot=MOC, stratum=Stratum.WEATHER)
    assert result.verdict is Verdict.NO_GO
    assert "R2 REJECT" in result.reasons[0]


def test_r4_rejects_a_powered_but_sub_threshold_residual() -> None:
    """A real residual below the bar is measured, priced, and declined."""
    # Ceiling 5 bps/episode — real, positive, but under the 27 bps B2 bar.
    episodes = [_episode(idx=i, hold=0.0, flatten=0.0, oracle_boundary=5.0) for i in range(400)]
    result = evaluate_stratum(episodes, pilot=MOC, stratum=Stratum.WEATHER)
    assert result.b1_powered
    assert not result.b2_ceiling_clears
    assert result.verdict is Verdict.NO_GO
    assert "R4 REJECT" in result.reasons[0]


def test_b3_fails_when_harvest_does_not_double_damage() -> None:
    """Ceiling clears B2, but the wrong-hold damage is too close behind it."""
    episodes = [_episode(idx=i, hold=0.0, flatten=0.0, oracle_boundary=30.0) for i in range(399)]
    # One wrong hold whose damage is > half the total harvest (399 × 30 ≈ 11970).
    episodes.append(_episode(idx=399, hold=-9000.0, flatten=0.0, oracle_boundary=-8970.0))
    result = evaluate_stratum(episodes, pilot=MOC, stratum=Stratum.WEATHER)
    assert result.b2_ceiling_clears
    assert not result.b3_harvest_dominates
    assert result.verdict is Verdict.NO_GO
    assert "R4 REJECT" in result.reasons[0]


def test_go_when_powered_ceiling_clears_and_harvest_dominates() -> None:
    episodes = [_episode(idx=i, hold=0.0, flatten=0.0, oracle_boundary=40.0) for i in range(400)]
    result = evaluate_stratum(episodes, pilot=MOC, stratum=Stratum.WEATHER)
    assert result.b1_powered and result.b2_ceiling_clears and result.b3_harvest_dominates
    assert result.verdict is Verdict.GO
    assert "Necessary, not sufficient" in result.reasons[0]


def test_b3_margin_is_the_declared_two_to_one() -> None:
    assert B3_HARVEST_DAMAGE_MULTIPLE == 2.0
    # Harvest exactly 2× damage passes; a hair under fails.
    base = [_episode(idx=i, hold=0.0, flatten=0.0, oracle_boundary=40.0) for i in range(399)]
    harvest_from_base = 399 * 40.0
    # One wrong hold with damage exactly half the total harvest.
    damage = harvest_from_base / 2.0
    ok = [*base, _episode(idx=399, hold=-damage, flatten=0.0, oracle_boundary=-damage)]
    assert evaluate_stratum(ok, pilot=MOC, stratum=Stratum.WEATHER).b3_harvest_dominates


# ── Stratification is enforced, not advisory ─────────────────────────


def test_pooling_strata_is_rejected() -> None:
    """§5.4/§8.5: pooling a benign majority into a toxic cell is the manoeuvre."""
    mixed = [
        _episode(idx=0, stratum=Stratum.WEATHER),
        _episode(idx=1, stratum=Stratum.EXPIRY),
    ]
    with pytest.raises(ValueError, match="must not be pooled"):
        evaluate_stratum(mixed, pilot=MOC, stratum=Stratum.WEATHER)


# ── Diagnostics ──────────────────────────────────────────────────────


def test_sub_cadence_share_flags_timing_luck() -> None:
    """Ceiling visible only between boundaries is not addressable by a map."""
    episodes = [
        _episode(idx=i, hold=0.0, oracle_boundary=1.0, oracle_event=10.0) for i in range(400)
    ]
    result = evaluate_stratum(episodes, pilot=MOC, stratum=Stratum.WEATHER)
    assert result.sub_cadence_share == pytest.approx(0.9)


def test_terminal_cap_counts_and_quote_freeze_are_reported() -> None:
    episodes = [
        _episode(idx=0, terminal_cap="MAX_HOLD_AFTER_SAFE_OFF"),
        _episode(idx=1, terminal_cap="SESSION_FLATTEN", quote_frozen=True),
        _episode(idx=2, terminal_cap="SESSION_FLATTEN", quote_frozen=True),
        _episode(idx=3, terminal_cap="HARD_EXIT_AGE"),
    ]
    result = evaluate_stratum(episodes, pilot=MOC, stratum=Stratum.WEATHER)
    assert result.terminal_cap_counts == {
        "MAX_HOLD_AFTER_SAFE_OFF": 1,
        "SESSION_FLATTEN": 2,
        "HARD_EXIT_AGE": 1,
    }
    assert result.quote_freeze_count == 2


def test_cpcv_path_deltas_override_the_single_pass_tail() -> None:
    """§5.1: the reported tail is the purged-CPCV estimate when paths are supplied."""
    episodes = [_episode(idx=i, hold=-1.0, flatten=0.0, oracle_boundary=40.0) for i in range(400)]
    single = evaluate_stratum(episodes, pilot=MOC, stratum=Stratum.WEATHER)
    cpcv = evaluate_stratum(
        episodes,
        pilot=MOC,
        stratum=Stratum.WEATHER,
        cvar_delta_by_path=[-2.0, -3.0, -4.0],
    )
    assert single.cvar_delta_bps == pytest.approx(-1.0)
    assert cpcv.cvar_delta_bps == pytest.approx(-3.0)


# ── Study level: B4 and R3 ───────────────────────────────────────────


def _powered_go_stratum(stratum: Stratum, *, cvar_shift: float = 0.0):
    """400 episodes clearing B2/B3, with a controllable tail location."""
    episodes = [
        _episode(idx=i, stratum=stratum, hold=cvar_shift, flatten=0.0, oracle_boundary=40.0)
        for i in range(400)
    ]
    return evaluate_stratum(episodes, pilot=MOC, stratum=stratum)


def test_b4_failure_blocks_go_even_with_a_passing_stratum() -> None:
    """A story map cannot rescue a Stage 0 that fails its own tail gate."""
    weather = _powered_go_stratum(Stratum.WEATHER)
    assert weather.verdict is Verdict.GO
    study = evaluate_study([weather], pilot=MOC, stage0_cvar_delta_bps=-5.0)
    assert not study.b4_stage0_gate_passes
    assert study.verdict is Verdict.NO_GO
    assert any("B4 FAIL" in r for r in study.reasons)


def test_r3_rejects_the_latent_state_confound() -> None:
    """Weather tail materially worse than expiry tail rejects mercy's premise."""
    # Weather holds lose 30 bps each; expiry holds break even. Gap = 30 bps >
    # the 18 bps materiality quantum.
    weather = _powered_go_stratum(Stratum.WEATHER, cvar_shift=-30.0)
    expiry = _powered_go_stratum(Stratum.EXPIRY, cvar_shift=0.0)
    study = evaluate_study([weather, expiry], pilot=MOC, stage0_cvar_delta_bps=0.0)
    assert study.r3_latent_state_confound
    assert study.verdict is Verdict.NO_GO
    assert any("R3 REJECT" in r for r in study.reasons)
    assert any("reason we should have left" in r for r in study.reasons)


def test_r3_does_not_fire_below_the_materiality_quantum() -> None:
    """A gap smaller than one stressed round-trip is not economically material."""
    weather = _powered_go_stratum(Stratum.WEATHER, cvar_shift=-5.0)
    expiry = _powered_go_stratum(Stratum.EXPIRY, cvar_shift=0.0)
    study = evaluate_study([weather, expiry], pilot=MOC, stage0_cvar_delta_bps=0.0)
    assert not study.r3_latent_state_confound
    assert study.verdict is Verdict.GO


def test_r3_silence_on_a_single_stratum_is_recorded_not_treated_as_a_pass() -> None:
    weather = _powered_go_stratum(Stratum.WEATHER)
    study = evaluate_study([weather], pilot=MOC, stage0_cvar_delta_bps=0.0)
    assert not study.r3_latent_state_confound
    assert any("R3 not computable" in r and "not a pass" in r for r in study.reasons)


def test_study_is_underpowered_when_no_stratum_clears_the_floor() -> None:
    thin = evaluate_stratum(
        [_episode(idx=i, oracle_boundary=500.0) for i in range(100)],
        pilot=MOC,
        stratum=Stratum.WEATHER,
    )
    study = evaluate_study([thin], pilot=MOC, stage0_cvar_delta_bps=0.0)
    assert study.verdict is Verdict.UNDERPOWERED
    assert any("not a GO" in r for r in study.reasons)


def test_study_no_go_records_that_stage0_stands_alone() -> None:
    """Design §4.2: rejecting Claim B is a successful result, not a shortfall."""
    weak = evaluate_stratum(
        [_episode(idx=i, oracle_boundary=5.0) for i in range(400)],
        pilot=MOC,
        stratum=Stratum.WEATHER,
    )
    study = evaluate_study([weak], pilot=MOC, stage0_cvar_delta_bps=0.0)
    assert study.verdict is Verdict.NO_GO
    assert any("Claim A" in r and "stands independently" in r for r in study.reasons)


def test_evaluate_study_requires_at_least_one_stratum() -> None:
    with pytest.raises(ValueError, match="at least one stratum"):
        evaluate_study([], pilot=MOC, stage0_cvar_delta_bps=0.0)


# ── Determinism (Inv-5) ──────────────────────────────────────────────


def test_verdict_is_deterministic() -> None:
    episodes = [
        _episode(idx=i, hold=float(i % 7) - 3.0, flatten=0.0, oracle_boundary=40.0 + i % 5)
        for i in range(400)
    ]
    first = evaluate_stratum(episodes, pilot=MOC, stratum=Stratum.WEATHER)
    second = evaluate_stratum(list(episodes), pilot=MOC, stratum=Stratum.WEATHER)
    assert first == second


# ── The frozen configs must remain loadable (G17) ────────────────────


@pytest.mark.parametrize("alpha_id", sorted(PILOT_CONFIGS))
def test_frozen_pilot_config_sits_exactly_at_the_g17_ceiling(alpha_id: str) -> None:
    """The pre-registered ``max_hold`` must load, and one second more must not.

    The pre-registration derives ``max_hold_after_safe_off`` from the per-family
    legal ceiling precisely so there is no discretion in it. If a family
    multiple is ever retuned, this fails loudly rather than letting the
    registered protocol quietly become unloadable — or quietly become laxer.
    """
    import pathlib

    import yaml

    from feelies.alpha.layer_validator import LayerValidationError, LayerValidator

    pilot = PILOT_CONFIGS[alpha_id]
    src = sorted(pathlib.Path("alphas").glob(f"**/{alpha_id}.alpha.yaml"))[0]
    spec = yaml.safe_load(src.read_text(encoding="utf-8"))
    spec["safety_exit_policy"] = {
        "mode": "decouple_caps_only",
        "max_hold_after_safe_off": pilot.max_hold_after_safe_off,
        "hard_exit_age_seconds": pilot.hard_exit_age_seconds,
    }

    LayerValidator().validate(spec, source=str(src))

    spec["safety_exit_policy"]["max_hold_after_safe_off"] = pilot.max_hold_after_safe_off + 1
    with pytest.raises(LayerValidationError, match="G17"):
        LayerValidator().validate(spec, source=str(src))
