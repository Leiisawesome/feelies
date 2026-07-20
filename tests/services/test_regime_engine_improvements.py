"""Regression tests for HMM3StateFractional robustness improvements."""

from __future__ import annotations

import json
import math
from decimal import Decimal

import pytest

from feelies.core.events import NBBOQuote
from feelies.services.regime_engine import (
    HMM3StateFractional,
    regime_posterior_entropy_nats,
)


def _q(
    symbol: str = "AAPL",
    bid: str = "150.00",
    ask: str = "150.01",
    timestamp_ns: int = 1_000_000_000,
    sequence: int = 1,
) -> NBBOQuote:
    return NBBOQuote(
        timestamp_ns=timestamp_ns,
        correlation_id="c",
        sequence=sequence,
        symbol=symbol,
        bid=Decimal(bid),
        ask=Decimal(ask),
        bid_size=100,
        ask_size=100,
        exchange_timestamp_ns=timestamp_ns - 1000,
    )


def test_regime_posterior_entropy_uniform_three_state() -> None:
    h = regime_posterior_entropy_nats([1.0 / 3.0, 1.0 / 3.0, 1.0 / 3.0])
    assert abs(h - math.log(3.0)) < 1e-12


def test_regime_posterior_entropy_pure_mass_is_zero() -> None:
    assert regime_posterior_entropy_nats([1.0, 0.0, 0.0]) == 0.0


def test_regime_posterior_entropy_renormalizes_negative_and_nan() -> None:
    h = regime_posterior_entropy_nats([0.5, float("nan"), -0.1, 0.6])
    assert h > 0.0
    assert h == regime_posterior_entropy_nats([0.5, 0.0, 0.0, 0.6])


def test_scale_transition_matrix_more_mixing_at_higher_scale() -> None:
    engine = HMM3StateFractional(
        emission_params=[(-4.5, 0.3), (-3.5, 0.5), (-2.5, 0.7)],
    )
    low_scale = engine._scale_transition_matrix(0.01)
    high_scale = engine._scale_transition_matrix(25.0)
    for i in range(3):
        assert low_scale[i][i] > high_scale[i][i]


def test_enforce_pairwise_separation_rejects_degenerate_calibration() -> None:
    engine = HMM3StateFractional(
        enforce_min_pairwise_emission_separation=True,
        min_pairwise_emission_separation=2.0,
    )
    quotes = [_q(sequence=i + 1, timestamp_ns=(i + 1) * 1000) for i in range(100)]
    assert engine.calibrate(quotes) is False
    assert engine.calibrated is False


def test_per_symbol_calibration_populates_map() -> None:
    engine = HMM3StateFractional(per_symbol_calibration=True)
    cal: list[NBBOQuote] = []
    for i in range(50):
        cal.append(
            _q(
                symbol="AAPL",
                bid="150.00",
                ask="150.01",
                sequence=i + 1,
                timestamp_ns=(i + 1) * 1000,
            )
        )
    for i in range(50):
        cal.append(
            _q(
                symbol="MSFT",
                bid="300.00",
                ask="301.00",
                sequence=100 + i,
                timestamp_ns=(50 + i + 1) * 1000,
            )
        )
    assert engine.calibrate(cal)
    assert "AAPL" in engine._emission_by_symbol
    assert "MSFT" in engine._emission_by_symbol


def test_per_symbol_pairwise_gate_failure_logs_warning(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    import logging

    ncalls = {"n": 0}
    real_gate = HMM3StateFractional._emissions_pass_pairwise_gate

    def gated(self, emission, *, _real=real_gate, _n=ncalls):
        _n["n"] += 1
        if _n["n"] <= 1:
            return _real(self, emission)
        return False

    monkeypatch.setattr(
        HMM3StateFractional,
        "_emissions_pass_pairwise_gate",
        gated,
    )
    engine = HMM3StateFractional(per_symbol_calibration=True)
    cal: list[NBBOQuote] = []
    spreads = [0.01] * 100 + [0.05] * 100 + [0.50] * 100
    for i, sp in enumerate(spreads):
        cal.append(
            _q(
                bid="150.00",
                ask=f"{150.0 + sp:.4f}",
                sequence=i + 1,
                timestamp_ns=(i + 1) * 1000,
            )
        )
    base_seq = len(cal)
    for j in range(30):
        cal.append(
            _q(
                symbol="THIN1",
                bid="10.00",
                ask="10.01",
                sequence=base_seq + j + 1,
                timestamp_ns=(base_seq + j + 1) * 1000,
            )
        )
    for j in range(30):
        cal.append(
            _q(
                symbol="THIN2",
                bid="20.00",
                ask="20.01",
                sequence=base_seq + 30 + j + 1,
                timestamp_ns=(base_seq + 30 + j + 1) * 1000,
            )
        )
    with caplog.at_level(logging.WARNING, logger="feelies.services.regime_engine"):
        assert engine.calibrate(cal)
    skips = [r for r in caplog.records if "per-symbol calibration skipped" in r.message]
    thin_skips = [r for r in skips if "THIN" in r.message]
    assert len(thin_skips) == 2
    joined = " ".join(r.message for r in thin_skips)
    assert "THIN1" in joined and "THIN2" in joined


def test_restore_legacy_checkpoint_without_last_quote_ts() -> None:
    engine = HMM3StateFractional()
    blob = json.dumps(
        {
            "posteriors": {"AAPL": [1.0 / 3.0, 1.0 / 3.0, 1.0 / 3.0]},
            "last_update_seq": {"AAPL": 9},
        }
    ).encode()
    engine.restore(blob)
    assert engine._last_quote_ts_ns == {}


def test_checkpoint_roundtrips_last_quote_ts_ns() -> None:
    engine = HMM3StateFractional(
        emission_params=[(-4.5, 0.3), (-3.5, 0.5), (-2.5, 0.7)],
        transition_time_scaling_enabled=True,
    )
    engine.posterior(_q(sequence=1, timestamp_ns=1_000_000_000))
    blob = engine.checkpoint()
    engine2 = HMM3StateFractional(
        emission_params=[(-4.5, 0.3), (-3.5, 0.5), (-2.5, 0.7)],
        transition_time_scaling_enabled=True,
    )
    engine2.restore(blob)
    assert engine2._last_quote_ts_ns.get("AAPL") == 1_000_000_000


@pytest.mark.parametrize("bad", [True, 42, "x"])
def test_restore_rejects_non_dict_last_quote_ts_ns(bad: object) -> None:
    engine = HMM3StateFractional()
    payload = json.dumps(
        {
            "posteriors": {},
            "last_update_seq": {},
            "last_quote_ts_ns": bad,
        }
    ).encode()
    with pytest.raises(ValueError, match="last_quote_ts_ns"):
        engine.restore(payload)


def test_get_regime_engine_accepts_time_scaling_kwarg() -> None:
    from feelies.services.regime_engine import get_regime_engine

    eng = get_regime_engine(
        "hmm_3state_fractional",
        transition_time_scaling_enabled=True,
    )
    assert getattr(eng, "_transition_time_scaling_enabled") is True


def test_get_regime_engine_rejects_unknown_kwarg() -> None:
    from feelies.services.regime_engine import get_regime_engine

    with pytest.raises(TypeError):
        get_regime_engine("hmm_3state_fractional", not_a_valid_option=True)


def test_get_regime_engine_spread_filter_alias() -> None:
    from feelies.services.regime_engine import get_regime_engine

    eng = get_regime_engine("hmm_3state_spread_filter")
    assert type(eng).__name__ == "HMM3StateFractional"


def test_checkpoint_includes_schema_version() -> None:
    engine = HMM3StateFractional(
        emission_params=[(-4.5, 0.3), (-3.5, 0.5), (-2.5, 0.7)],
    )
    engine.posterior(_q(sequence=1))
    payload = json.loads(engine.checkpoint())
    # Schema 2 carries the flags fingerprint.
    assert payload["checkpoint_schema_version"] == 2
    assert "flags_fingerprint" in payload


def test_restore_rejects_unsupported_schema_version() -> None:
    engine = HMM3StateFractional()
    payload = json.dumps(
        {
            "checkpoint_schema_version": 999,
            "posteriors": {},
            "last_update_seq": {},
        }
    ).encode()
    with pytest.raises(ValueError, match="Unsupported checkpoint_schema_version"):
        engine.restore(payload)


def test_scaled_transition_matrix_cache_reused() -> None:
    engine = HMM3StateFractional(
        emission_params=[(-4.5, 0.3), (-3.5, 0.5), (-2.5, 0.7)],
        transition_time_scaling_enabled=True,
    )
    engine.posterior(_q(sequence=1, timestamp_ns=1_000_000_000))
    engine.posterior(_q(sequence=2, timestamp_ns=1_000_000_000 + 50_000_000))
    first = engine._scaled_transition_cache
    assert first is not None
    engine.posterior(_q(sequence=3, timestamp_ns=1_000_000_000 + 100_000_000))
    assert engine._scaled_transition_cache is first
