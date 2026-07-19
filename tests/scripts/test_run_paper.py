"""Smoke tests for ``scripts/run_paper.py``.

These exercise *only* the script's argument-parsing and early-exit
guards (config file missing, ``MASSIVE_API_KEY`` unset, config mode
mismatch).  The full end-to-end PAPER session requires a real IB
Gateway and real Massive WS connection — neither is reachable from
the test environment.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

import pytest

_SCRIPT_PATH = Path(__file__).resolve().parent.parent.parent / "scripts" / "run_paper.py"


def _load_module() -> object:
    spec = importlib.util.spec_from_file_location("run_paper", _SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _FakeBus:
    def subscribe(self, event_type: object, callback: object) -> None:
        pass


class _FakeOrchestratorForRecorder:
    def __init__(self) -> None:
        self._bus = _FakeBus()

    def set_paper_session_recorder(self, recorder: object) -> None:
        pass


def test_session_start_and_end_ns_are_int(tmp_path: Path) -> None:
    """Audit P2-5: session_start_ns/session_end_ns must be int nanoseconds —
    a float loses precision at current epoch magnitudes (~1.8e18 ns exceeds
    float64's ~2**53 exact-integer range)."""
    from feelies.core.platform_config import OperatingMode, PlatformConfig

    mod = _load_module()
    config = PlatformConfig(mode=OperatingMode.PAPER, symbols=frozenset({"AAPL"}))
    args = argparse.Namespace(
        run_dir=tmp_path,
        emit_signals_jsonl=False,
        emit_order_acks_jsonl=False,
        emit_timing_jsonl=False,
        emit_fills_jsonl=False,
        config="platform.yaml",
    )
    orchestrator = _FakeOrchestratorForRecorder()

    recorder = mod._wire_session_recorder(orchestrator, args, config)  # type: ignore[attr-defined]
    mod._flush_session_recorder(orchestrator, recorder, args)  # type: ignore[attr-defined]

    metadata = json.loads((tmp_path / "metadata.json").read_text(encoding="utf-8"))
    assert isinstance(metadata["session_start_ns"], int)
    assert isinstance(metadata["session_end_ns"], int)


class TestRunPaperGuards:
    def test_help_exits_zero(self) -> None:
        mod = _load_module()
        with pytest.raises(SystemExit) as exc_info:
            mod.main(["--help"])  # type: ignore[attr-defined]
        assert exc_info.value.code == 0

    def test_missing_api_key_returns_one(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.delenv("MASSIVE_API_KEY", raising=False)
        mod = _load_module()
        # Stub load_dotenv so it doesn't read a real ``.env`` file
        # (which on dev machines actually has the key).
        import builtins

        original_import = builtins.__import__

        def _fake_import(name: str, *args: object, **kwargs: object) -> object:
            if name == "dotenv":
                raise ImportError("stubbed")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _fake_import)

        rc = mod.main([])  # type: ignore[attr-defined]
        assert rc == 1
        assert "MASSIVE_API_KEY" in capsys.readouterr().err

    def test_missing_config_file_returns_one(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        tmp_path: Path,
    ) -> None:
        monkeypatch.setenv("MASSIVE_API_KEY", "fake")
        mod = _load_module()
        rc = mod.main(  # type: ignore[attr-defined]
            ["--config", str(tmp_path / "does_not_exist.yaml")],
        )
        assert rc == 1
        assert "Config file not found" in capsys.readouterr().err

    def test_non_paper_mode_returns_one(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        tmp_path: Path,
    ) -> None:
        monkeypatch.setenv("MASSIVE_API_KEY", "fake")
        cfg = tmp_path / "platform.yaml"
        cfg.write_text("symbols: [AAPL]\nmode: BACKTEST\nalpha_specs: [alpha.yaml]\n")
        mod = _load_module()
        rc = mod.main(["--config", str(cfg)])  # type: ignore[attr-defined]
        assert rc == 1
        assert "requires mode: PAPER" in capsys.readouterr().err

    def test_unknown_config_key_strict_config_returns_one(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        tmp_path: Path,
    ) -> None:
        # Audit R-2: --strict-config was wired into the backtest CLI but not
        # into run_paper.py, leaving PAPER mode (real IB Gateway orders) with
        # no way to fail closed on a misspelled config key.
        monkeypatch.setenv("MASSIVE_API_KEY", "fake")
        cfg = tmp_path / "platform.yaml"
        cfg.write_text(
            "symbols: [AAPL]\nmode: PAPER\nalpha_specs: [alpha.yaml]\n"
            "cost_stress_multipler: 2.0\n"
        )
        mod = _load_module()
        rc = mod.main(["--config", str(cfg), "--strict-config"])  # type: ignore[attr-defined]
        assert rc == 1
        assert "unrecognized config key" in capsys.readouterr().err

    def test_unknown_config_key_without_strict_config_warns_and_proceeds(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        tmp_path: Path,
    ) -> None:
        # Default (non-strict) behaviour is unchanged: a typo warns but the
        # config still loads, so the run proceeds to the next guard (here,
        # the BACKTEST-mode check) rather than failing on the config itself.
        monkeypatch.setenv("MASSIVE_API_KEY", "fake")
        cfg = tmp_path / "platform.yaml"
        cfg.write_text(
            "symbols: [AAPL]\nmode: BACKTEST\nalpha_specs: [alpha.yaml]\n"
            "cost_stress_multipler: 2.0\n"
        )
        mod = _load_module()
        rc = mod.main(["--config", str(cfg)])  # type: ignore[attr-defined]
        assert rc == 1
        assert "requires mode: PAPER" in capsys.readouterr().err


class TestRunPaperTeardownOrder:
    def test_finally_shutdown_before_feed_and_ib(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        mod = _load_module()
        calls: list[str] = []

        class _LiveFeed:
            def start(self) -> None:
                calls.append("feed.start")

            def stop(self) -> None:
                calls.append("feed.stop")

        class _IB:
            def connect_and_start(self, **kwargs: object) -> None:
                calls.append("ib.connect")

            def disconnect_and_stop(self) -> None:
                calls.append("ib.disconnect")

        class _Orch:
            macro_state = None

            def __init__(self) -> None:
                from feelies.kernel.macro import MacroState

                self.macro_state = MacroState.READY
                self.live_feed = _LiveFeed()
                self.ib_connection = _IB()

            def boot(self, config: object) -> None:
                calls.append("boot")

            def run_paper(self) -> None:
                calls.append("run_paper")

            def halt(self) -> None:
                calls.append("halt")

            def shutdown(self) -> None:
                calls.append("shutdown")

        def _fake_build(config: object) -> tuple[_Orch, object]:
            return _Orch(), config

        monkeypatch.setenv("MASSIVE_API_KEY", "fake")
        monkeypatch.setattr(mod, "build_platform", _fake_build)

        cfg = Path(__file__).resolve().parents[2] / "configs" / "paper_smoke_rth.yaml"
        if not cfg.is_file():
            pytest.skip("configs/paper_smoke_rth.yaml not present")

        rc = mod.main(["--config", str(cfg)])  # type: ignore[attr-defined]
        assert rc == 0
        assert calls.index("shutdown") < calls.index("feed.stop")
        assert calls.index("shutdown") < calls.index("ib.disconnect")
