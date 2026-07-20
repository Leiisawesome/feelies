"""Keep the read-only promotion CLI isolated from trading dependencies.

Subprocesses prevent imports from other tests from contaminating the checks.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap


def _run(snippet: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(snippet)],
        capture_output=True,
        text=True,
    )


def test_building_promote_parser_does_not_import_heavy_stack() -> None:
    result = _run(
        """
        import sys
        from feelies.cli.main import _build_parser

        # Resolve the promote subtree exactly as `feelies promote ...` does.
        _build_parser(["promote", "gate-matrix"])

        forbidden = [
            m
            for m in sys.modules
            if m == "feelies.cli.backtest"
            or m == "feelies.bootstrap"
            or m.startswith("feelies.harness")
        ]
        assert not forbidden, f"promote path imported heavy modules: {forbidden}"
        print("OK")
        """
    )
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout


def test_importing_cli_main_does_not_import_backtest() -> None:
    result = _run(
        """
        import sys
        import feelies.cli.main  # noqa: F401

        assert "feelies.cli.backtest" not in sys.modules
        print("OK")
        """
    )
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout


def test_backtest_subtree_is_still_registered_lazily() -> None:
    # When `backtest` IS the selected command, main() must wire it (which
    # imports the heavy stack on demand).  We only assert the import is
    # attempted — the heavy modules may be absent (no `ib` extra) in this
    # environment, which manifests as a ModuleNotFoundError rather than an
    # argparse "invalid choice", proving the lazy registration fired.
    result = _run(
        """
        import sys
        from feelies.cli.main import _build_parser
        try:
            _build_parser(["backtest"])
        except ModuleNotFoundError:
            # Heavy stack not installed in this env — registration was
            # still attempted (the point of the test).
            print("OK-lazy-import-attempted")
        else:
            assert "feelies.cli.backtest" in sys.modules
            print("OK-registered")
        """
    )
    assert result.returncode == 0, result.stderr
    assert "OK-" in result.stdout
