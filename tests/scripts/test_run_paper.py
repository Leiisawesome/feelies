"""Smoke tests for ``scripts/run_paper.py``.

These exercise *only* the script's argument-parsing and early-exit
guards (config file missing, ``MASSIVE_API_KEY`` unset, config mode
mismatch).  The full end-to-end PAPER session requires a real IB
Gateway and real Massive WS connection — neither is reachable from
the test environment.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SCRIPT_PATH = Path(__file__).resolve().parent.parent.parent / "scripts" / "run_paper.py"


def _load_module() -> object:
    spec = importlib.util.spec_from_file_location("run_paper", _SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


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
