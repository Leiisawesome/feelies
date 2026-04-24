"""Unit tests for AlphaLoader and LoadedAlphaModule."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from feelies.alpha.loader import AlphaLoadError, AlphaLoader, LoadedAlphaModule
from feelies.core.clock import SimulatedClock
from feelies.core.events import FeatureVector, NBBOQuote, SignalDirection

from tests.alpha.conftest import clock, sample_quote


# ── Minimal valid specs for testing ───────────────────────────────────────

MINIMAL_SPEC = {
    "schema_version": "1.1",
    "layer": "LEGACY_SIGNAL",
    "alpha_id": "test_alpha",
    "version": "1.0.0",
    "description": "Test alpha",
    "hypothesis": "Test hypothesis",
    "falsification_criteria": ["fail"],
    "features": [
        {
            "feature_id": "mid_price",
            "version": "1.0",
            "description": "Mid price",
            "depends_on": [],
            "warm_up": {"min_events": 0},
            "computation": """
def initial_state():
    return {}
def update(quote, state, params):
    bid, ask = float(quote.bid), float(quote.ask)
    return (bid + ask) / 2.0 if (bid and ask) else 0.0
""",
        }
    ],
    "signal": """
def evaluate(features, params):
    if not features.warm:
        return None
    v = features.values.get("mid_price", 0.0)
    if v < params.get("threshold", 0):
        return None
    return Signal(
        timestamp_ns=features.timestamp_ns,
        correlation_id=features.correlation_id,
        sequence=features.sequence,
        symbol=features.symbol,
        strategy_id="test_alpha",
        direction=SignalDirection.LONG,
        strength=0.5,
        edge_estimate_bps=params.get("edge_estimate_bps", 2.0),
    )
""",
}

SPEC_WITH_PARAMS = {
    **MINIMAL_SPEC,
    "parameters": {
        "threshold": {"type": "float", "default": 0.0, "description": "Min value"},
        "edge_estimate_bps": {"type": "float", "default": 2.5, "range": [0.5, 10.0]},
    },
}

SPEC_DICT_FEATURES = {
    **MINIMAL_SPEC,
    "features": {
        "spread": {
            "version": "1.0",
            "description": "Spread",
            "depends_on": [],
            "warm_up": {"min_events": 0},
            "computation": """
def initial_state():
    return {}
def update(quote, state, params):
    return float(quote.ask - quote.bid)
""",
        }
    },
}

SPEC_COMPOUND_FEATURE = {
    **MINIMAL_SPEC,
    "features": [
        {
            "feature_id": "regime_state",
            "version": "1.0",
            "description": "Regime probs",
            "depends_on": [],
            "warm_up": {"min_events": 0},
            "return_type": "list[3]",
            "computation": """
def initial_state():
    return {"count": 0}
def update(quote, state, params):
    state["count"] += 1
    return [0.33, 0.33, 0.34]
""",
        }
    ],
    "signal": """
def evaluate(features, params):
    if not features.warm:
        return None
    p0 = features.values.get("regime_state_0", 0.0)
    if p0 < 0.5:
        return None
    return Signal(
        timestamp_ns=features.timestamp_ns,
        symbol=features.symbol,
        strategy_id="test_alpha",
        direction=SignalDirection.LONG,
        strength=p0,
        edge_estimate_bps=2.0,
    )
""",
}

SPEC_DYNAMIC_WARMUP = {
    **MINIMAL_SPEC,
    "parameters": {"ema_span": {"type": "int", "default": 20}},
    "features": [
        {
            "feature_id": "ema",
            "version": "1.0",
            "description": "EMA",
            "depends_on": [],
            "warm_up": {"min_events": "params['ema_span']"},
            "computation": """
def initial_state():
    return {"ema": 0.0, "n": 0}
def update(quote, state, params):
    mid = (float(quote.bid) + float(quote.ask)) / 2.0
    span = params["ema_span"]
    alpha = 2.0 / (span + 1)
    state["n"] += 1
    if state["n"] == 1:
        state["ema"] = mid
    else:
        state["ema"] += alpha * (mid - state["ema"])
    return state["ema"]
""",
        }
    ],
}


class TestAlphaLoaderLoadFromDict:
    """Tests for load_from_dict."""

    def test_load_minimal_spec(self) -> None:
        loader = AlphaLoader()
        alpha = loader.load_from_dict(MINIMAL_SPEC)
        assert alpha.manifest.alpha_id == "test_alpha"
        assert alpha.manifest.version == "1.0.0"
        assert len(alpha.feature_definitions()) == 1
        assert alpha.feature_definitions()[0].feature_id == "mid_price"

    def test_load_with_params(self) -> None:
        loader = AlphaLoader()
        alpha = loader.load_from_dict(SPEC_WITH_PARAMS)
        assert alpha.manifest.parameters["threshold"] == 0.0
        assert alpha.manifest.parameters["edge_estimate_bps"] == 2.5

    def test_load_param_overrides(self) -> None:
        loader = AlphaLoader()
        alpha = loader.load_from_dict(
            SPEC_WITH_PARAMS,
            param_overrides={"threshold": 5.0, "edge_estimate_bps": 3.0},
        )
        assert alpha.manifest.parameters["threshold"] == 5.0
        assert alpha.manifest.parameters["edge_estimate_bps"] == 3.0

    def test_load_dict_format_features(self) -> None:
        loader = AlphaLoader()
        alpha = loader.load_from_dict(SPEC_DICT_FEATURES)
        fids = [f.feature_id for f in alpha.feature_definitions()]
        assert "spread" in fids

    def test_load_compound_feature_auto_flatten(self) -> None:
        loader = AlphaLoader()
        alpha = loader.load_from_dict(SPEC_COMPOUND_FEATURE)
        fids = [f.feature_id for f in alpha.feature_definitions()]
        assert "regime_state_0" in fids
        assert "regime_state_1" in fids
        assert "regime_state_2" in fids

    def test_compound_feature_cache_hit_on_second_update(
        self, sample_quote: NBBOQuote, clock: SimulatedClock
    ) -> None:
        """Second update for same symbol hits _SharedCompoundComputation cache (lines 189-191)."""
        from feelies.alpha.composite import CompositeFeatureEngine
        from feelies.alpha.registry import AlphaRegistry

        loader = AlphaLoader()
        alpha = loader.load_from_dict(SPEC_COMPOUND_FEATURE)
        registry = AlphaRegistry()
        registry.register(alpha)
        clock.set_time(sample_quote.timestamp_ns)
        engine = CompositeFeatureEngine(registry=registry, clock=clock)

        fv1 = engine.update(sample_quote)
        assert fv1 is not None
        assert fv1.values["regime_state_0"] == pytest.approx(0.33, abs=0.01)
        assert fv1.values["regime_state_1"] == pytest.approx(0.33, abs=0.01)
        assert fv1.values["regime_state_2"] == pytest.approx(0.34, abs=0.01)

        # Second quote for same symbol: compound compute_once returns cached result
        q2 = NBBOQuote(
            symbol="AAPL",
            timestamp_ns=sample_quote.timestamp_ns + 1,
            correlation_id="c2",
            sequence=2,
            bid=150.02,
            ask=150.04,
            bid_size=100,
            ask_size=100,
            exchange_timestamp_ns=sample_quote.timestamp_ns + 1,
        )
        fv2 = engine.update(q2)
        assert fv2 is not None
        # Values reflect second update (count=2) from shared state
        assert fv2.values["regime_state_0"] == pytest.approx(0.33, abs=0.01)
        assert fv2.values["regime_state_1"] == pytest.approx(0.33, abs=0.01)
        assert fv2.values["regime_state_2"] == pytest.approx(0.34, abs=0.01)

    def test_load_dynamic_warmup(self) -> None:
        loader = AlphaLoader()
        alpha = loader.load_from_dict(SPEC_DYNAMIC_WARMUP)
        fd = alpha.feature_definitions()[0]
        assert fd.warm_up.min_events == 20


class TestAlphaLoaderLoadFromPath:
    """Tests for load() from file path."""

    def test_load_from_path(self) -> None:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            import yaml

            yaml.dump(MINIMAL_SPEC, f, default_flow_style=False)
            path = f.name
        try:
            loader = AlphaLoader()
            alpha = loader.load(path)
            assert alpha.manifest.alpha_id == "test_alpha"
        finally:
            Path(path).unlink(missing_ok=True)

    def test_load_from_path_file_not_found(self) -> None:
        loader = AlphaLoader()
        with pytest.raises(AlphaLoadError, match="Failed to read"):
            loader.load("/nonexistent/path.alpha.yaml")

    def test_load_from_path_invalid_yaml(self) -> None:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write("invalid: [[[ yaml")
            path = f.name
        try:
            loader = AlphaLoader()
            with pytest.raises(AlphaLoadError, match="Failed to read"):
                loader.load(path)
        finally:
            Path(path).unlink(missing_ok=True)


class TestAlphaLoaderValidation:
    """Tests for schema and parameter validation."""

    def test_missing_top_level_keys(self) -> None:
        loader = AlphaLoader()
        spec = {k: v for k, v in MINIMAL_SPEC.items() if k != "hypothesis"}
        with pytest.raises(AlphaLoadError, match="missing required"):
            loader.load_from_dict(spec)

    def test_root_not_dict(self) -> None:
        loader = AlphaLoader()
        with pytest.raises(AlphaLoadError, match="root must be a YAML mapping"):
            loader.load_from_dict("not a dict", source="<test>")  # type: ignore[arg-type]

    def test_parameter_missing_default(self) -> None:
        spec = {
            **MINIMAL_SPEC,
            "parameters": {
                "x": {"type": "float", "description": "x"},
            },
        }
        loader = AlphaLoader()
        with pytest.raises(AlphaLoadError, match="missing 'default'"):
            loader.load_from_dict(spec)

    def test_parameter_validation_fails(self) -> None:
        loader = AlphaLoader()
        with pytest.raises(AlphaLoadError, match="parameter validation failed"):
            loader.load_from_dict(
                SPEC_WITH_PARAMS,
                param_overrides={"edge_estimate_bps": 999.0},
            )

    def test_feature_syntax_error(self) -> None:
        spec = {
            **MINIMAL_SPEC,
            "features": [
                {
                    **MINIMAL_SPEC["features"][0],
                    "computation": "def initial_state(\n    return 1  # bad",
                }
            ],
        }
        loader = AlphaLoader()
        with pytest.raises(AlphaLoadError, match="syntax error"):
            loader.load_from_dict(spec)

    def test_feature_missing_initial_state(self) -> None:
        spec = {
            **MINIMAL_SPEC,
            "features": [
                {
                    "feature_id": "x",
                    "version": "1",
                    "description": "x",
                    "warm_up": {"min_events": 0},
                    "computation": "def update(quote, state, params): return 0.0",
                }
            ],
        }
        loader = AlphaLoader()
        with pytest.raises(AlphaLoadError, match="initial_state"):
            loader.load_from_dict(spec)

    def test_feature_missing_update(self) -> None:
        spec = {
            **MINIMAL_SPEC,
            "features": [
                {
                    "feature_id": "x",
                    "version": "1",
                    "description": "x",
                    "warm_up": {"min_events": 0},
                    "computation": "def initial_state(): return {}",
                }
            ],
        }
        loader = AlphaLoader()
        with pytest.raises(AlphaLoadError, match="update"):
            loader.load_from_dict(spec)

    def test_features_not_list_or_dict(self) -> None:
        spec = {**MINIMAL_SPEC, "features": "invalid"}
        loader = AlphaLoader()
        with pytest.raises(AlphaLoadError, match="list or mapping"):
            loader.load_from_dict(spec)

    def test_feature_list_item_missing_feature_id(self) -> None:
        spec = {
            **MINIMAL_SPEC,
            "features": [
                {
                    "version": "1",
                    "description": "x",
                    "warm_up": {"min_events": 0},
                    "computation": "x",
                }
            ],
        }
        loader = AlphaLoader()
        with pytest.raises(AlphaLoadError, match="feature_id"):
            loader.load_from_dict(spec)

    def test_signal_syntax_error(self) -> None:
        spec = {**MINIMAL_SPEC, "signal": "def evaluate(\n    return"}
        loader = AlphaLoader()
        with pytest.raises(AlphaLoadError, match="signal.*syntax"):
            loader.load_from_dict(spec)

    def test_signal_missing_evaluate(self) -> None:
        spec = {**MINIMAL_SPEC, "signal": "x = 1"}
        loader = AlphaLoader()
        with pytest.raises(AlphaLoadError, match="evaluate"):
            loader.load_from_dict(spec)

    def test_warm_up_expression_fails(self) -> None:
        spec = {
            **MINIMAL_SPEC,
            "features": [
                {
                    **MINIMAL_SPEC["features"][0],
                    "warm_up": {"min_events": "params['nonexistent']"},
                }
            ],
        }
        loader = AlphaLoader()
        with pytest.raises(AlphaLoadError, match="min_events"):
            loader.load_from_dict(spec)

    def test_parameter_not_dict_raises(self) -> None:
        spec = {
            **MINIMAL_SPEC,
            "parameters": {"x": "not_a_dict"},
        }
        loader = AlphaLoader()
        with pytest.raises(AlphaLoadError, match="parameter.*mapping"):
            loader.load_from_dict(spec)

    def test_regimes_engine_null_returns_injected(self) -> None:
        """When regimes.engine is 'null', use loader's regime_engine."""
        from feelies.services.regime_engine import HMM3StateFractional
        reg_eng = HMM3StateFractional()
        loader = AlphaLoader(regime_engine=reg_eng)
        spec = {**MINIMAL_SPEC, "regimes": {"engine": "null"}}
        alpha = loader.load_from_dict(spec)
        assert alpha.manifest.alpha_id == "test_alpha"

    def test_regime_engine_unknown_raises(self) -> None:
        spec = {
            **MINIMAL_SPEC,
            "regimes": {"engine": "nonexistent_engine", "state_names": []},
        }
        loader = AlphaLoader()
        with pytest.raises(AlphaLoadError, match="nonexistent"):
            loader.load_from_dict(spec)

    def test_feature_list_item_not_dict_raises(self) -> None:
        spec = {
            **MINIMAL_SPEC,
            "features": ["not a dict"],
        }
        loader = AlphaLoader()
        with pytest.raises(AlphaLoadError, match="features.*mapping"):
            loader.load_from_dict(spec)

    def test_feature_dict_value_not_dict_raises(self) -> None:
        spec = {
            **MINIMAL_SPEC,
            "features": {"bad_feature": "not a dict"},
        }
        loader = AlphaLoader()
        with pytest.raises(AlphaLoadError, match="feature.*mapping"):
            loader.load_from_dict(spec)

    def test_regimes_engine_none_returns_injected_engine(self) -> None:
        """When regimes.engine is None, use loader's injected regime_engine."""
        from feelies.services.regime_engine import HMM3StateFractional

        reg_eng = HMM3StateFractional()
        loader = AlphaLoader(regime_engine=reg_eng)
        spec = {**MINIMAL_SPEC, "regimes": {"engine": None}}
        alpha = loader.load_from_dict(spec)
        assert alpha.manifest.alpha_id == "test_alpha"

    def test_regimes_engine_null_string_returns_injected_engine(self) -> None:
        """When regimes.engine is 'null', use loader's injected regime_engine."""
        from feelies.services.regime_engine import HMM3StateFractional

        reg_eng = HMM3StateFractional()
        loader = AlphaLoader(regime_engine=reg_eng)
        spec = {**MINIMAL_SPEC, "regimes": {"engine": "null"}}
        alpha = loader.load_from_dict(spec)
        assert alpha.manifest.alpha_id == "test_alpha"

    def test_load_with_regime_engine_injects_into_namespace(self) -> None:
        """Spec with regimes.engine injects read-only regime accessors."""
        from feelies.services.regime_engine import HMM3StateFractional

        loader = AlphaLoader(regime_engine=HMM3StateFractional())
        spec = {
            **MINIMAL_SPEC,
            "regimes": {"engine": "hmm_3state_fractional"},
            "features": [
                {
                    "feature_id": "regime_probs",
                    "version": "1.0",
                    "description": "HMM posteriors",
                    "depends_on": [],
                    "warm_up": {"min_events": 0},
                    "return_type": "list[3]",
                    "computation": """
def initial_state():
    return {}
def update(quote, state, params):
    p = regime_posteriors(quote.symbol)
    return p if p is not None else [0.33, 0.33, 0.34]
""",
                }
            ],
        }
        alpha = loader.load_from_dict(spec)
        fdefs = alpha.feature_definitions()
        assert any("regime_probs_0" in f.feature_id for f in fdefs)


class TestLoadedAlphaModule:
    """Tests for LoadedAlphaModule behavior."""

    def test_evaluate_returns_signal(
        self, sample_quote: NBBOQuote, clock: SimulatedClock
    ) -> None:
        loader = AlphaLoader()
        alpha = loader.load_from_dict(MINIMAL_SPEC)

        from feelies.alpha.registry import AlphaRegistry
        from feelies.alpha.composite import CompositeFeatureEngine

        reg = AlphaRegistry()
        reg.register(alpha)
        clock.set_time(sample_quote.timestamp_ns)
        fe = CompositeFeatureEngine(reg, clock)
        fv = fe.update(sample_quote)

        signal = alpha.evaluate(fv)
        assert signal is not None
        assert signal.direction == SignalDirection.LONG
        assert signal.symbol == "AAPL"
        assert signal.correlation_id == fv.correlation_id
        assert signal.sequence == fv.sequence

    def test_evaluate_returns_none_when_cold(self, sample_quote: NBBOQuote) -> None:
        loader = AlphaLoader()
        alpha = loader.load_from_dict(SPEC_WITH_PARAMS)

        fv = FeatureVector(
            timestamp_ns=sample_quote.timestamp_ns,
            correlation_id="c1",
            sequence=1,
            symbol="AAPL",
            feature_version="v1",
            values={"mid_price": -1.0},
            warm=False,
        )
        signal = alpha.evaluate(fv)
        assert signal is None

    def test_evaluate_patches_provenance(self) -> None:
        loader = AlphaLoader()
        spec = {
            **MINIMAL_SPEC,
            "signal": """
def evaluate(features, params):
    return Signal(
        timestamp_ns=features.timestamp_ns,
        correlation_id="",
        sequence=0,
        symbol=features.symbol,
        strategy_id="test_alpha",
        direction=SignalDirection.LONG,
        strength=0.5,
        edge_estimate_bps=2.0,
    )
""",
        }
        alpha = loader.load_from_dict(spec)
        fv = FeatureVector(
            timestamp_ns=1,
            correlation_id="cid",
            sequence=42,
            symbol="X",
            feature_version="v",
            values={"mid_price": 1.0},
            warm=True,
        )
        signal = alpha.evaluate(fv)
        assert signal is not None
        assert signal.correlation_id == "cid"
        assert signal.sequence == 42

    def test_evaluate_returns_none_for_non_signal(self) -> None:
        spec = {
            **MINIMAL_SPEC,
            "signal": "def evaluate(features, params): return 123",
        }
        loader = AlphaLoader()
        alpha = loader.load_from_dict(spec)
        fv = FeatureVector(
            timestamp_ns=1, correlation_id="c", sequence=1,
            symbol="X", feature_version="v", values={"mid_price": 1.0}, warm=True,
        )
        signal = alpha.evaluate(fv)
        assert signal is None

    def test_validate_passes(self) -> None:
        loader = AlphaLoader()
        alpha = loader.load_from_dict(SPEC_WITH_PARAMS)
        assert alpha.validate() == []

    def test_validate_fails_on_invalid_param(self) -> None:
        loader = AlphaLoader()
        alpha = loader.load_from_dict(SPEC_WITH_PARAMS)
        alpha._params["edge_estimate_bps"] = 999.0
        errors = alpha.validate()
        assert len(errors) > 0
        assert "outside range" in str(errors)

    def test_validate_uses_default_when_param_missing_in_params(self) -> None:
        """LoadedAlphaModule.validate uses pdef.default when param not in _params."""
        from feelies.alpha.module import AlphaManifest, AlphaRiskBudget, ParameterDef

        manifest = AlphaManifest(
            alpha_id="x",
            version="1",
            description="d",
            hypothesis="h",
            falsification_criteria=(),
            required_features=frozenset(),
            parameter_schema=(
                ParameterDef(name="p", param_type="int", default=42),
            ),
        )
        alpha = LoadedAlphaModule(
            manifest=manifest,
            feature_defs=[],
            evaluate_fn=lambda f, p: None,
            params={},  # p not in params
        )
        assert alpha.validate() == []

    def test_load_with_regime_engine_in_namespace(
        self, sample_quote: NBBOQuote, clock: SimulatedClock
    ) -> None:
        """Load spec with regimes.engine so read-only regime accessors are in feature ns."""
        from feelies.alpha.composite import CompositeFeatureEngine
        from feelies.alpha.registry import AlphaRegistry
        from feelies.services.regime_engine import HMM3StateFractional

        engine = HMM3StateFractional()
        engine.posterior(sample_quote)

        spec = {
            **MINIMAL_SPEC,
            "regimes": {"engine": "hmm_3state_fractional"},
            "features": [
                {
                    **MINIMAL_SPEC["features"][0],
                    "feature_id": "regime_state",
                    "return_type": "list[3]",
                    "computation": """
def initial_state():
    return {"posterior": [0.33, 0.33, 0.34]}
def update(quote, state, params):
    p = regime_posteriors(quote.symbol)
    if p is None:
        p = [0.33, 0.33, 0.34]
    state["posterior"] = p
    return p
""",
                }
            ],
        }
        loader = AlphaLoader(regime_engine=engine)
        alpha = loader.load_from_dict(spec)
        reg = AlphaRegistry()
        reg.register(alpha)
        clock.set_time(sample_quote.timestamp_ns)
        fe = CompositeFeatureEngine(reg, clock)
        fv = fe.update(sample_quote)
        assert "regime_state_0" in fv.values
        assert "regime_state_1" in fv.values
        assert "regime_state_2" in fv.values
