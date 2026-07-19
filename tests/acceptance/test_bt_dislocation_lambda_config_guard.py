"""Config guard for ``configs/bt_sig_dislocation_lambda_drift_v1.yaml``
(Task 9 commit 2; 00c Task-9 amendment adopted verbatim — data-free,
no cache).

Pins the evidence config to the 00c pinned realism profile
(docs/research/prompt_pack_00c_eval_canon.md, commit
825a7bc3bda48d3a819fed0a498dbf9d65e711c4): the realism-knob subset of
``PlatformConfig.snapshot()`` must hash to the checksum captured at
config instantiation, so any knob drift — including drift inherited
through ``extends: ../platform.yaml`` — fails loudly here instead of
silently invalidating steps 7–8 evidence.  Per-knob equality asserts
run alongside the checksum for readable failures.

Also enforces: the zero-latency ban (FQ-2 / OQ-4 — zero fill latency
is the optimistic immediate-fill mode, not a realism setting), the
spec §1.4 session-time constants, the deployment
``signal_min_edge_cost_ratio`` convention, the Lei ruling-a capital
base ($100k; impl plan §7.1 binding arithmetic), and the config-scope
guard (Lei ruling 1, 2026-07-14): ``symbols == ["APP"]`` exactly —
deployment scope cannot widen (RMBS, OLN, or anything else) without
this test tripping.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from feelies.core.platform_config import PlatformConfig

_CONFIG_PATH = Path("configs/bt_sig_dislocation_lambda_drift_v1.yaml")

# Sorted-JSON SHA-256 over the realism-knob subset below, captured at
# config instantiation under PYTHONHASHSEED=0 (00c O-1: no
# pre-recorded value existed to copy).  Recorded in the config header
# as REALISM_KNOB_CHECKSUM.
_PINNED_CHECKSUM = "5675c18eedd0cdff70f392ace9f89c45aaea31933bf41775e3e1b0c117a35565"

# The 00c §1 table, knob → pinned value (snapshot-data representation).
_PINNED_KNOBS: dict[str, object] = {
    # Latency + execution mode
    "execution_mode": "passive_limit",
    "backtest_fill_latency_ns": 50_000_000,
    "market_data_latency_ns": 20_000_000,
    # Passive fill model
    "passive_fill_delay_ticks": 3,
    "passive_max_resting_ticks": 8000,
    "passive_queue_position_shares": 200,
    "passive_fill_hazard_max": 0.5,
    "passive_cancel_fee_per_share": 0.0,
    "passive_through_fill_size_cap_enabled": True,
    "passive_require_trade_for_level_fill": True,
    # Impact / slippage realism
    "cost_market_impact_factor": 0.5,
    "cost_max_impact_half_spreads": 4.0,
    "cost_within_l1_impact_factor": 0.3,
    "cost_permanent_impact_coefficient": 0.0,
    "cost_stop_depth_depletion_factor": 2.0,
    "cost_stop_slippage_half_spreads": 2.0,
    "cost_moc_penalty_bps": 3.0,
    # Cost model — commissions, fees, adverse selection
    "cost_min_spread_bps": 0.3,
    "cost_commission_per_share": 0.0035,
    "cost_taker_exchange_per_share": 0.003,
    "cost_maker_exchange_per_share": 0.0,
    "cost_min_commission": 0.35,
    "cost_max_commission_pct": 1.0,
    "cost_passive_adverse_selection_bps": 2.0,
    "cost_through_fill_adverse_selection_bps": 5.0,
    "cost_adverse_selection_through_bps": 5.0,
    "cost_adverse_selection_drain_bps": 2.0,
    "cost_sell_regulatory_bps": 0.5,
    "cost_stress_multiplier": 1.0,
    "cost_finra_taf_per_share": 0.000166,
    "cost_finra_taf_max_per_order": 8.3,
    "cost_min_commission_applies_to_per_share_only": True,
    "cost_spread_floor_taker_only": True,
    "cost_htb_borrow_annual_bps": 0.0,
    # Regulatory / session constraints
    "halt_on_condition_codes": [],
    "halt_off_condition_codes": [],
    "halt_resolution_blackout_seconds": 60,
    "ssr_active_symbols": [],
    "ssr_trigger_condition_codes": [],
    "ssr_mode": "refuse_short",
    "borrow_availability": {},
    "borrow_default_tier": "available",
    "account_type": "margin_25k",
    "pdt_min_equity_usd": 25000.0,
    "platform_min_order_shares": 50,
}


def _load() -> PlatformConfig:
    return PlatformConfig.from_yaml(_CONFIG_PATH)


def _knob_subset(cfg: PlatformConfig) -> dict[str, object]:
    data = cfg.snapshot(ts_ns=0).data
    missing = sorted(k for k in _PINNED_KNOBS if k not in data)
    assert not missing, f"snapshot lost realism knobs: {missing}"
    return {k: data[k] for k in _PINNED_KNOBS}


def test_zero_latency_is_banned() -> None:
    cfg = _load()
    assert cfg.backtest_fill_latency_ns > 0
    assert cfg.market_data_latency_ns > 0


def test_realism_knobs_match_00c_pin_per_knob() -> None:
    subset = _knob_subset(_load())
    for knob, pinned in _PINNED_KNOBS.items():
        assert subset[knob] == pinned, (
            f"realism knob {knob!r} drifted from the 00c pin: "
            f"expected {pinned!r}, got {subset[knob]!r}"
        )


def test_realism_knob_subset_checksum_matches_instantiation_pin() -> None:
    subset = _knob_subset(_load())
    raw = json.dumps(subset, sort_keys=True, default=str)
    assert hashlib.sha256(raw.encode()).hexdigest() == _PINNED_CHECKSUM


def test_config_header_records_the_pinned_checksum() -> None:
    """The header comment is the instantiation-time record; keep it in
    lockstep with the test pin so neither can drift alone."""
    text = _CONFIG_PATH.read_text(encoding="utf-8")
    match = re.search(r"REALISM_KNOB_CHECKSUM:\s*([0-9a-f]{64})", text)
    assert match is not None, "config header lost the REALISM_KNOB_CHECKSUM record"
    assert match.group(1) == _PINNED_CHECKSUM


def test_deployment_and_session_time_constants() -> None:
    cfg = _load()
    assert cfg.signal_min_edge_cost_ratio == 1.5
    # Spec §1.4 session-time discipline (fixed constants; +1 N to vary).
    assert cfg.no_entry_first_seconds == 300
    assert cfg.session_flatten_enabled is True
    assert cfg.session_flatten_seconds_before_close == 600


def test_capital_base_matches_ruling_a_record() -> None:
    # Lei ruling a (2026-07-14): 80 sh × grid-max APP median bid
    # $729.51 = $58,360.80; the $100k BT-15 bracket-top base with the
    # alpha's 80/80 budget keeps the 80-share anchor binding
    # (impl plan §7.1).
    cfg = _load()
    assert cfg.account_equity == 100000.0


def test_config_scope_guard_symbols_exactly_app() -> None:
    # Lei ruling 1 (2026-07-14): deployment scope cannot widen without
    # this assertion tripping.  RMBS is step-2 harness-level evidence
    # only; OLN is tick-artifact only — neither enters a run config.
    cfg = _load()
    assert list(cfg.symbols) == ["APP"]

    alpha_basenames = [p.name for p in cfg.alpha_specs]
    assert alpha_basenames == ["sig_dislocation_lambda_drift_v1.alpha.yaml"]
