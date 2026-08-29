"""A3 — attaching an alpha costs zero core edits.

CORE §G / I-18: a new alpha is a YAML file. ``kernel/``, ``bus/``,
``core/``, ``composition/``, ``risk/`` and ``execution/`` must not name
an alpha, and an alpha that declares ``session: closing_auction`` must
divert to the closing auction without those packages mentioning it.
"""

from __future__ import annotations

from pathlib import Path

from feelies.bootstrap import build_platform
from feelies.core.events import NBBOQuote, Side
from feelies.core.platform_config import OperatingMode, PlatformConfig
from feelies.execution.order_policy import _resolve_order_route
from feelies.sensors.impl.ofi_ewma import OFIEwmaSensor
from feelies.sensors.spec import SensorSpec
from feelies.storage.memory_event_log import InMemoryEventLog
from tests.fixtures.event_logs._generate import SESSION_OPEN_NS
from tests.kernel.test_orchestrator import _make_quote
from tools.arch.gapscan import alpha_literal_leaks

_SRC = Path(__file__).resolve().parents[2] / "src" / "feelies"
_CORE_PACKAGES = frozenset({"kernel", "bus", "core", "composition", "risk", "execution"})
_PROBE_ID = "a3_probe_closing_auction"

_PROBE_YAML = """\
schema_version: "1.1"
layer: SIGNAL
alpha_id: a3_probe_closing_auction
version: "1.0.0"
lifecycle_state: RESEARCH
description: |
  A3 probe. Declares closing-auction session so attachment is a YAML
  file, not a core identity list.
hypothesis: |
  None. Conformance probe; exploits no structural mechanism.
falsification_criteria:
  - The probe is named in kernel, bus, core, composition, risk, or execution.
depends_on_sensors:
  - ofi_ewma
parameters: {}
horizon_seconds: 30
session: closing_auction
risk_budget:
  max_position_per_symbol: 1
  max_gross_exposure_pct: 0.1
  max_drawdown_pct: 0.1
  capital_allocation_pct: 0.1
regime_gate:
  regime_engine: hmm_3state_fractional
  on_condition: "True"
  off_condition: "False"
cost_arithmetic:
  edge_estimate_bps: 9.0
  half_spread_bps: 2.0
  impact_bps: 2.0
  fee_bps: 1.0
  margin_ratio: 1.8
  cost_basis: one_way
signal: |
  def evaluate(snapshot, regime, params):
      return None
"""

_SENSOR_SPECS: tuple[SensorSpec, ...] = (
    SensorSpec(
        sensor_id="ofi_ewma",
        sensor_version="1.1.0",
        cls=OFIEwmaSensor,
        params={"alpha": 0.1, "warm_after": 5},
        subscribes_to=(NBBOQuote,),
    ),
)


def _core_leak_sites() -> list[dict[str, str]]:
    report = alpha_literal_leaks()
    leaks: list[dict[str, str]] = []
    for hit in report["leak_sites"]:
        parts = Path(hit["path"]).parts
        if len(parts) >= 3 and parts[2] in _CORE_PACKAGES:
            leaks.append(hit)
    return leaks


def test_a3_core_packages_name_no_alpha() -> None:
    leaks = _core_leak_sites()
    assert not leaks, (
        f"{len(leaks)} alpha-id literal(s) under {sorted(_CORE_PACKAGES)}; "
        f"attaching an alpha must not edit these. First: {leaks[0]}"
    )


def test_a3_declared_closing_auction_routes_without_core_edits(tmp_path: Path) -> None:
    spec = tmp_path / f"{_PROBE_ID}.alpha.yaml"
    spec.write_text(_PROBE_YAML, encoding="utf-8")
    config = PlatformConfig(
        symbols=frozenset({"AAPL"}),
        mode=OperatingMode.BACKTEST,
        alpha_specs=[spec],
        regime_engine="hmm_3state_fractional",
        sensor_specs=_SENSOR_SPECS,
        horizons_seconds=frozenset({30}),
        session_open_ns=SESSION_OPEN_NS,
        moc_session_date="2026-01-15",
        account_equity=1_000_000.0,
        enforce_trend_mechanism=False,
    )
    orchestrator, _ = build_platform(config, event_log=InMemoryEventLog())
    _, _, is_moc = _resolve_order_route(
        orchestrator,
        strategy_id=_PROBE_ID,
        symbol="AAPL",
        side=Side.BUY,
        quantity=100,
        quote=_make_quote(),
        is_short=False,
        is_exit_or_stop=False,
        edge_bps=5.0,
    )
    assert is_moc is True

    for pkg in _CORE_PACKAGES:
        for path in (_SRC / pkg).rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            assert _PROBE_ID not in text, (
                f"{path.as_posix()} names the attached alpha — attachment "
                "required a core edit"
            )
