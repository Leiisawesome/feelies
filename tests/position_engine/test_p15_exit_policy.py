"""P-15 exit_policy load checks and enabling rule.

``_load_alpha_yaml`` is the loader call used by
``tests/acceptance/test_falsifiability_inv2.py``:
``AlphaLoader(enforce_trend_mechanism=False).load``.
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest
import yaml

from feelies.alpha.layer_validator import LayerValidationError
from feelies.alpha.loader import AlphaLoadError, AlphaLoader
from feelies.bootstrap import build_platform
from feelies.bus.event_bus import EventBus
from feelies.core.errors import ConfigurationError
from feelies.core.platform_config import OperatingMode, PlatformConfig
from feelies.portfolio.mark_rail import MarkRail
from feelies.position.engine import PositionEngine, PositionRecordSink
from tests.conformance.test_null_alpha_conservation import _NULL_ALPHA
from tests.fixtures.event_logs._generate import SESSION_OPEN_NS

_FIXTURE = Path("tests/position_engine/fixtures/sig_position_fixture_v1.alpha.yaml")
_NS = 1_000_000_000
_REPO = Path(".")


def _alpha_yaml_paths() -> list[Path]:
    found = list((_REPO / "alphas").rglob("*.alpha.yaml"))
    found.extend((_REPO / "tests").rglob("*.alpha.yaml"))
    return sorted(set(found))


def _load_alpha_yaml(path: Path) -> object:
    return AlphaLoader(enforce_trend_mechanism=False).load(str(path))


def _spec() -> dict:
    loaded = yaml.safe_load(_FIXTURE.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _write(tmp_path: Path, spec: dict) -> Path:
    path = tmp_path / "case.alpha.yaml"
    path.write_text(yaml.safe_dump(spec, sort_keys=False), encoding="utf-8")
    return path


def _load_mutated(tmp_path: Path, spec: dict) -> object:
    return AlphaLoader().load(str(_write(tmp_path, spec)))


def _platform(mode: object = OperatingMode.BACKTEST, **overrides: object) -> PlatformConfig:
    # Sensors from the config that loads sig_contra_fixture_v1
    # (configs/bt_netting_contest.yaml:32, extends platform.yaml).
    contra = PlatformConfig.from_yaml(Path("configs/bt_netting_contest.yaml"))
    needed = frozenset({"ofi_ewma", "book_imbalance", "spread_z_30d", "realized_vol_30s"})
    sensors = tuple(spec for spec in contra.sensor_specs if spec.sensor_id in needed)
    kwargs: dict[str, object] = {
        "symbols": frozenset({"AAPL"}),
        "mode": mode,
        "alpha_specs": [_FIXTURE],
        "sensor_specs": sensors,
        "regime_engine": None,
        "enforce_trend_mechanism": False,
        "session_open_ns": SESSION_OPEN_NS,
    }
    kwargs.update(overrides)
    return PlatformConfig(**kwargs)  # type: ignore[arg-type]


def test_e1_fixture_parses_exit_policy() -> None:
    from feelies.core.exit_policy import ExitPolicy

    loaded = _load_alpha_yaml(_FIXTURE)
    policy = loaded.manifest.exit_policy  # type: ignore[attr-defined]
    assert isinstance(policy, ExitPolicy)
    assert policy.archetype == "liquidity_provision"
    assert policy.curve_ref == "ARBITRARY_NOT_CALIBRATED"
    assert policy.fee_round_trip_ticks == 1
    assert policy.declared_shape is None
    assert policy.horizon.T_ns == 120 * _NS
    assert policy.horizon.cutoff_before_close_ns == 300 * _NS
    assert policy.adverse.centre_ticks == 10
    assert policy.adverse.band_ticks == 4
    assert policy.adverse.lo_ticks == 5
    assert policy.adverse.hi_ticks == 20
    assert policy.adverse.blind_limit_ns == 30 * _NS
    assert policy.adverse.crossing_ticks is None
    assert policy.adverse.premium_bps is None
    assert policy.favorable.form == "fixed"
    assert policy.favorable.target_ticks == 6
    assert policy.favorable.giveback_spread_multiple is None
    assert policy.favorable.ceiling_ticks is None
    assert policy.favorable.quiet_limit_ns == 5 * _NS


@pytest.mark.parametrize(
    "where",
    ["exit_policy", "horizon", "adverse", "favorable"],
)
def test_e2_unknown_key_inside_exit_policy(tmp_path: Path, where: str) -> None:
    spec = _spec()
    if where == "exit_policy":
        spec["exit_policy"]["not_a_field"] = 1
    else:
        spec["exit_policy"][where]["not_a_field"] = 1
    with pytest.raises(AlphaLoadError, match="not_a_field"):
        _load_mutated(tmp_path, spec)


def test_e3_unknown_top_level_key(tmp_path: Path) -> None:
    spec = _spec()
    spec["exit_polcy"] = spec.pop("exit_policy")
    with pytest.raises(AlphaLoadError, match="exit_polcy"):
        _load_mutated(tmp_path, spec)


@pytest.mark.parametrize("path", _alpha_yaml_paths(), ids=lambda p: p.as_posix())
def test_e3_every_alpha_yaml_loads(path: Path) -> None:
    _load_alpha_yaml(path)


@pytest.mark.parametrize(
    "field",
    [
        "T_seconds",
        "cutoff_before_close_seconds",
        "blind_limit_seconds",
        "quiet_limit_seconds",
        "centre_ticks",
        "lo_ticks",
    ],
)
def test_e4_l8_zero_rejected(tmp_path: Path, field: str) -> None:
    spec = _spec()
    block = spec["exit_policy"]
    if field in block["horizon"]:
        block["horizon"][field] = 0
    elif field in block["adverse"]:
        block["adverse"][field] = 0
    else:
        block["favorable"][field] = 0
    with pytest.raises(LayerValidationError, match=rf"EXIT_POLICY L8.*{field}"):
        _load_mutated(tmp_path, spec)


@pytest.mark.parametrize("band", [3, -2])
def test_e4_l8_band_ticks_odd_or_negative(tmp_path: Path, band: int) -> None:
    spec = _spec()
    spec["exit_policy"]["adverse"]["band_ticks"] = band
    with pytest.raises(LayerValidationError, match=r"EXIT_POLICY L8.*band_ticks"):
        _load_mutated(tmp_path, spec)


def test_e5_l1_fixed_target_must_clear_fee(tmp_path: Path) -> None:
    spec = _spec()
    fee = spec["exit_policy"]["fee_round_trip_ticks"]
    spec["exit_policy"]["favorable"]["target_ticks"] = fee + 1
    with pytest.raises(LayerValidationError, match="EXIT_POLICY L1"):
        _load_mutated(tmp_path, spec)
    spec = _spec()
    spec["exit_policy"]["favorable"]["target_ticks"] = fee + 2
    _load_mutated(tmp_path, spec)


def test_e6_l2_band_inside_lo_hi(tmp_path: Path) -> None:
    below = _spec()
    below["exit_policy"]["adverse"]["lo_ticks"] = 9
    with pytest.raises(LayerValidationError, match="EXIT_POLICY L2"):
        _load_mutated(tmp_path, below)
    above = _spec()
    above["exit_policy"]["adverse"]["hi_ticks"] = 11
    with pytest.raises(LayerValidationError, match="EXIT_POLICY L2"):
        _load_mutated(tmp_path, above)
    tight = _spec()
    tight["exit_policy"]["adverse"]["lo_ticks"] = 2
    with pytest.raises(LayerValidationError, match="EXIT_POLICY L2"):
        _load_mutated(tmp_path, tight)


def test_e7_l3_curve_premium(tmp_path: Path) -> None:
    with_cross = _spec()
    with_cross["exit_policy"]["adverse"]["crossing_ticks"] = 8
    with pytest.raises(LayerValidationError, match="EXIT_POLICY L3"):
        _load_mutated(tmp_path, with_cross)
    with_premium = _spec()
    with_premium["exit_policy"]["adverse"]["premium_bps"] = 5
    with pytest.raises(LayerValidationError, match="EXIT_POLICY L3"):
        _load_mutated(tmp_path, with_premium)
    named = _spec()
    named["exit_policy"]["curve_ref"] = "measured_v1"
    with pytest.raises(LayerValidationError, match="EXIT_POLICY L3"):
        _load_mutated(tmp_path, named)
    tighter = _spec()
    tighter["exit_policy"]["curve_ref"] = "measured_v1"
    tighter["exit_policy"]["adverse"]["crossing_ticks"] = 15
    with pytest.raises(LayerValidationError, match="EXIT_POLICY L3"):
        _load_mutated(tmp_path, tighter)
    insured = copy.deepcopy(tighter)
    insured["exit_policy"]["adverse"]["premium_bps"] = 5
    _load_mutated(tmp_path, insured)


def test_e8_l4_curve_ref_required(tmp_path: Path) -> None:
    missing = _spec()
    del missing["exit_policy"]["curve_ref"]
    with pytest.raises(LayerValidationError, match="EXIT_POLICY L4"):
        _load_mutated(tmp_path, missing)
    empty = _spec()
    empty["exit_policy"]["curve_ref"] = ""
    with pytest.raises(LayerValidationError, match="EXIT_POLICY L4"):
        _load_mutated(tmp_path, empty)


def test_e9_l5_archetype_form(tmp_path: Path) -> None:
    trailing = _spec()
    trailing["exit_policy"]["favorable"]["form"] = "trailing"
    trailing["exit_policy"]["favorable"]["giveback_spread_multiple"] = 1.5
    with pytest.raises(LayerValidationError, match="EXIT_POLICY L5"):
        _load_mutated(tmp_path, trailing)
    fixed = _spec()
    fixed["exit_policy"]["archetype"] = "informed_flow_following"
    _load_mutated(tmp_path, fixed)
    follow = _spec()
    follow["exit_policy"]["archetype"] = "informed_flow_following"
    follow["exit_policy"]["favorable"]["form"] = "trailing"
    follow["exit_policy"]["favorable"]["giveback_spread_multiple"] = 1.5
    _load_mutated(tmp_path, follow)
    other = _spec()
    other["exit_policy"]["archetype"] = "declared_other"
    with pytest.raises(LayerValidationError, match="EXIT_POLICY L5"):
        _load_mutated(tmp_path, other)
    bare = _spec()
    bare["exit_policy"]["favorable"]["form"] = "trailing"
    del bare["exit_policy"]["favorable"]["target_ticks"]
    with pytest.raises(LayerValidationError, match="EXIT_POLICY L5"):
        _load_mutated(tmp_path, bare)


def test_e10_l6_alpha_excludes_other_exit_authors(tmp_path: Path) -> None:
    hazard = _spec()
    hazard["hazard_exit"] = {"enabled": True, "hazard_score_threshold": 0.8}
    with pytest.raises(LayerValidationError, match="EXIT_POLICY L6"):
        _load_mutated(tmp_path, hazard)
    safety = _spec()
    safety["safety_exit_policy"] = {"mode": "gate_close_flat"}
    with pytest.raises(LayerValidationError, match="EXIT_POLICY L6"):
        _load_mutated(tmp_path, safety)


@pytest.mark.parametrize(
    "field",
    [
        "stop_loss_pct",
        "stop_loss_per_share",
        "trail_activate_pct",
        "trail_activate_per_share",
    ],
)
def test_e11_l6_platform_stop_or_trail(field: str) -> None:
    with pytest.raises(ConfigurationError, match="EXIT_POLICY L6"):
        build_platform(_platform(**{field: 0.01}))


def test_e11_l6_session_flatten_buffer() -> None:
    with pytest.raises(ConfigurationError, match="EXIT_POLICY L6"):
        build_platform(
            _platform(
                session_flatten_enabled=True,
                session_flatten_seconds_before_close=300,
            )
        )
    build_platform(
        _platform(
            session_flatten_enabled=True,
            session_flatten_seconds_before_close=299,
        )
    )


def _spy_components() -> tuple[list[str], list[PositionEngine], dict[type, object]]:
    constructed: list[str] = []
    engines: list[PositionEngine] = []
    originals: dict[type, object] = {
        EventBus: EventBus.__init__,
        MarkRail: MarkRail.__init__,
        PositionEngine: PositionEngine.__init__,
        PositionRecordSink: PositionRecordSink.__init__,
    }

    def _wrap(label: str, original: object, bucket: list[PositionEngine] | None = None) -> object:
        def _init(self: object, *args: object, **kwargs: object) -> None:
            constructed.append(label)
            if bucket is not None:
                bucket.append(self)  # type: ignore[arg-type]
            original(self, *args, **kwargs)  # type: ignore[operator]

        return _init

    EventBus.__init__ = _wrap("EventBus", originals[EventBus])  # type: ignore[method-assign]
    MarkRail.__init__ = _wrap("MarkRail", originals[MarkRail])  # type: ignore[method-assign]
    PositionEngine.__init__ = _wrap(  # type: ignore[method-assign]
        "PositionEngine", originals[PositionEngine], engines
    )
    PositionRecordSink.__init__ = _wrap(  # type: ignore[method-assign]
        "PositionRecordSink", originals[PositionRecordSink]
    )
    return constructed, engines, originals


def _restore(originals: dict[type, object]) -> None:
    EventBus.__init__ = originals[EventBus]  # type: ignore[method-assign]
    MarkRail.__init__ = originals[MarkRail]  # type: ignore[method-assign]
    PositionEngine.__init__ = originals[PositionEngine]  # type: ignore[method-assign]
    PositionRecordSink.__init__ = originals[PositionRecordSink]  # type: ignore[method-assign]


def test_e12_enabling_rule() -> None:
    from feelies.core.exit_policy import ExitPolicy

    constructed, engines, originals = _spy_components()
    try:
        build_platform(_platform())
    finally:
        _restore(originals)
    assert constructed[0:1] == ["PositionEngine"] or "PositionEngine" in constructed
    assert len(engines) == 1
    policy = engines[0].policies["sig_position_fixture_v1"]
    assert isinstance(policy, ExitPolicy)
    assert engines[0].policies == {"sig_position_fixture_v1": policy}

    for mode in (
        OperatingMode.PAPER,
        type("LiveMode", (), {"name": "LIVE"})(),
    ):
        constructed, engines, originals = _spy_components()
        try:
            with pytest.raises(ConfigurationError):
                build_platform(_platform(mode))
        finally:
            _restore(originals)
        assert constructed == []

    dark = PlatformConfig(
        symbols=frozenset({"AAPL"}),
        mode=OperatingMode.BACKTEST,
        alpha_specs=[_NULL_ALPHA],
        regime_engine=None,
        enforce_trend_mechanism=False,
        session_open_ns=SESSION_OPEN_NS,
    )
    constructed, engines, originals = _spy_components()
    try:
        build_platform(dark)
    finally:
        _restore(originals)
    assert "PositionEngine" not in constructed
    assert engines == []
