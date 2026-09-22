"""DIRECT_PROBES resolves completely, and an unresolved name is an error.

``_install_direct_probes`` setattr's live classes and records ``_INSTALLED``.
These tests install against a copy of the list and restore every patched
attribute so the rest of the process keeps the original callables.
"""

from __future__ import annotations

import importlib
import re
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest

from feelies.execution.backtest_router import BacktestOrderRouter
from feelies.kernel import orchestrator as orchestrator_mod
from feelies.kernel.orchestrator import Orchestrator
from tools.arch import perfmeasure

_ORCH_ATTRS = (
    "run_backtest",
    "_process_tick",
    "_process_tick_inner",
    "_process_trade_inner",
    "_finalize_tick",
    "_emit_state_transition",
    "_dispatch_sensor_layer",
    "_maybe_transition_cross_sectional_bookend",
    "_flush_pending_sized_intents",
    "_settle_router_acks",
    "_reconcile_resting_fills",
    "_record_net_shadow",
    "_trace_buffered_signals_arbitration",
    "_append_signal_order_trace",
)
_ROUTER_ATTRS = ("on_quote", "submit", "poll_acks")
_MODULE_FUNCS = (
    "_data_health_blocks_trading",
    "_verify_data_integrity",
    "_update_halt_state",
    "_update_ssr_state",
    "_update_regime",
    "_compute_target_quantity",
    "_maybe_flip_buying_power_at_rth_close",
    "_submit_tracked_order",
    "_try_build_order_from_intent",
    "_record_size_shadow",
)

_ORIGINAL_ORCH = {name: Orchestrator.__dict__[name] for name in _ORCH_ATTRS}
_ORIGINAL_ROUTER = {name: BacktestOrderRouter.__dict__[name] for name in _ROUTER_ATTRS}
_ORIGINAL_MOD = {name: getattr(orchestrator_mod, name) for name in _MODULE_FUNCS}

_FAKE_METHOD = "feelies.kernel.orchestrator:Orchestrator._o07_no_such_probe"
_FAKE_MODULE = "feelies.kernel.no_such_o07_module:Missing.method"


def _assert_original_attributes() -> None:
    for name, fn in _ORIGINAL_ORCH.items():
        assert Orchestrator.__dict__[name] is fn, name
    for name, fn in _ORIGINAL_ROUTER.items():
        assert BacktestOrderRouter.__dict__[name] is fn, name
    for name, fn in _ORIGINAL_MOD.items():
        assert getattr(orchestrator_mod, name) is fn, name


def _lookup(target: str) -> tuple[Any, str, Any] | None:
    mod_name, _, attr = target.partition(":")
    try:
        mod = importlib.import_module(mod_name)
    except ImportError:
        return None
    if "." not in attr:
        fn = getattr(mod, attr, None)
        if not callable(fn):
            return None
        return mod, attr, fn
    cls_name, _, meth = attr.partition(".")
    cls = getattr(mod, cls_name, None)
    if cls is None:
        return None
    fn = cls.__dict__.get(meth)
    if fn is None:
        fn = getattr(cls, meth, None)
    if not callable(fn) or isinstance(fn, property):
        return None
    return cls, meth, fn


@contextmanager
def _probe_install(
    probes: list[tuple[int, str, str]],
) -> Iterator[Any]:
    saved_probes = perfmeasure.DIRECT_PROBES
    saved_installed = set(perfmeasure._INSTALLED)
    saved_unresolved = list(perfmeasure._UNRESOLVED)
    saved_resolved = list(perfmeasure._RESOLVED)
    binds = []
    for _engine, _label, target in probes:
        bound = _lookup(target)
        if bound is not None:
            binds.append(bound)
    perfmeasure.DIRECT_PROBES = list(probes)
    perfmeasure._INSTALLED.discard("direct")
    perfmeasure._UNRESOLVED.clear()
    perfmeasure._RESOLVED.clear()
    try:
        yield perfmeasure
    finally:
        for owner, name, fn in binds:
            setattr(owner, name, fn)
        perfmeasure.DIRECT_PROBES = saved_probes
        perfmeasure._INSTALLED.clear()
        perfmeasure._INSTALLED.update(saved_installed)
        perfmeasure._UNRESOLVED[:] = saved_unresolved
        perfmeasure._RESOLVED[:] = saved_resolved


def test_every_direct_probe_resolves() -> None:
    try:
        with _probe_install(list(perfmeasure.DIRECT_PROBES)) as pm:
            pm._install_direct_probes()
            missing = list(pm._UNRESOLVED)
            resolved = list(pm._RESOLVED)
            declared = len(pm.DIRECT_PROBES)
        assert missing == [], "unresolved direct probes:\n" + "\n".join(missing)
        assert declared == 48
        assert len(resolved) == 48
    finally:
        _assert_original_attributes()


def test_unresolved_direct_probe_raises() -> None:
    try:
        probes = [*perfmeasure.DIRECT_PROBES, (0, "o07.fake", _FAKE_METHOD)]
        with _probe_install(probes) as pm:
            with pytest.raises(RuntimeError, match=re.escape(_FAKE_METHOD)):
                pm._install_direct_probes()
        with _probe_install([(0, "o07.badmod", _FAKE_MODULE)]) as pm:
            with pytest.raises(RuntimeError, match=re.escape(_FAKE_MODULE)):
                pm._install_direct_probes()
    finally:
        _assert_original_attributes()
