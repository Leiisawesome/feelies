"""``feelies forensics circuit-breaker`` — the loop from fills to demotion.

``cost_circuit_breaker`` shipped complete and tested but had no caller outside
its own tests, so nothing acted on its verdict.  Two things had to be true for it
to run against a finished session, and neither was:

* the session's fills had to carry ``realized_pnl`` and ``fees``, which
  ``trade_records_to_dicts`` did not persist — without them
  ``per_alpha_cost_survival`` cannot compute an alpha's net at all;
* an operator entry point had to exist.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from feelies.cli.main import main
from feelies.core.events import Side
from feelies.monitoring.paper_session_recorder import (
    trade_records_from_dicts,
    trade_records_to_dicts,
)
from feelies.storage.trade_journal import TradeRecord

_EXIT_OK = 0
_EXIT_DATA_ERROR = 2
_EXIT_QUARANTINE_RECOMMENDED = 3


def _record(
    strategy_id: str,
    *,
    realized_pnl: str,
    fees: str = "0.10",
    cost_bps: str = "5.0",
    qty: int = 100,
    ts: int = 1_000,
) -> TradeRecord:
    return TradeRecord(
        order_id=f"o-{strategy_id}-{ts}",
        symbol="AAPL",
        strategy_id=strategy_id,
        side=Side.SELL,
        requested_quantity=qty,
        filled_quantity=qty,
        fill_price=Decimal("100.00"),
        signal_timestamp_ns=ts,
        submit_timestamp_ns=ts,
        fill_timestamp_ns=ts,
        cost_bps=Decimal(cost_bps),
        fees=Decimal(fees),
        realized_pnl=Decimal(realized_pnl),
        correlation_id=f"c-{ts}",
    )


def _write_session(tmp_path: Path, records: list[TradeRecord]) -> Path:
    path = tmp_path / "fills.jsonl"
    with path.open("w", encoding="utf-8") as fh:
        for row in trade_records_to_dicts(records):
            fh.write(json.dumps(row, sort_keys=True) + "\n")
    return path


# ── The persistence gap that blocked the loop ───────────────────────────


def test_session_fills_round_trip_the_fields_cost_analysis_needs() -> None:
    """``realized_pnl`` and ``fees`` must survive to disk and back.

    ``per_alpha_cost_survival`` computes net as ``sum(realized_pnl) -
    sum(fees)``.  Neither field was persisted, so a finished session could not be
    scored — the breaker would have read every alpha as flat.
    """
    original = [
        _record("sig_a_v1", realized_pnl="-250.00", fees="1.37"),
        _record("sig_b_v1", realized_pnl="80.25", fees="0.42", ts=2_000),
    ]

    restored = trade_records_from_dicts(trade_records_to_dicts(original))

    assert [r.strategy_id for r in restored] == ["sig_a_v1", "sig_b_v1"]
    assert [r.realized_pnl for r in restored] == [Decimal("-250.00"), Decimal("80.25")]
    assert [r.fees for r in restored] == [Decimal("1.37"), Decimal("0.42")]
    # Decimal, not float — cent-level PnL must not drift through the round-trip.
    assert all(isinstance(r.realized_pnl, Decimal) for r in restored)
    assert [r.filled_quantity for r in restored] == [100, 100]
    assert [r.cost_bps for r in restored] == [Decimal("5.0"), Decimal("5.0")]


# ── Evaluation (read-only) ──────────────────────────────────────────────


def test_bleeding_alpha_is_recommended_for_quarantine(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Net <= 0 over enough fills is the hard trip."""
    fills = _write_session(
        tmp_path,
        [_record("bleeder_v1", realized_pnl="-10.00", ts=i) for i in range(40)],
    )

    code = main(["forensics", "circuit-breaker", str(fills)])

    out = capsys.readouterr().out
    assert "bleeder_v1" in out
    assert "QUARANTINE" in out
    # Exit 3 lets a deployment gate branch without parsing text.
    assert code == _EXIT_QUARANTINE_RECOMMENDED
    # Read-only by default: the operator is told what to do, not surprised by it.
    assert "--apply" in out


def test_thin_history_abstains_rather_than_demoting(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Inv-3: demotion needs evidence, so a short window must not trip."""
    fills = _write_session(
        tmp_path,
        [_record("thin_v1", realized_pnl="-10.00", ts=i) for i in range(3)],
    )

    code = main(["forensics", "circuit-breaker", str(fills)])

    out = capsys.readouterr().out
    assert "INSUFFICIENT_EVIDENCE" in out
    assert "QUARANTINE" not in out
    assert code == _EXIT_OK


def test_healthy_alpha_exits_clean(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    fills = _write_session(
        tmp_path,
        [_record("good_v1", realized_pnl="50.00", fees="0.10", ts=i) for i in range(40)],
    )

    code = main(["forensics", "circuit-breaker", str(fills)])

    assert "QUARANTINE" not in capsys.readouterr().out
    assert code == _EXIT_OK


def test_json_output_is_machine_readable(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fills = _write_session(
        tmp_path,
        [_record("bleeder_v1", realized_pnl="-10.00", ts=i) for i in range(40)],
    )

    main(["forensics", "circuit-breaker", str(fills), "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert payload["applied"] == []
    decision = next(d for d in payload["decisions"] if d["strategy_id"] == "bleeder_v1")
    assert decision["action"] == "QUARANTINE"
    assert decision["n_fills"] == 40
    assert decision["net"] < 0


def test_min_fills_is_tunable(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """The persistence bar is a policy knob, not a constant."""
    fills = _write_session(
        tmp_path,
        [_record("bleeder_v1", realized_pnl="-10.00", ts=i) for i in range(10)],
    )

    assert main(["forensics", "circuit-breaker", str(fills)]) == _EXIT_OK
    capsys.readouterr()

    code = main(["forensics", "circuit-breaker", str(fills), "--min-fills", "5"])
    assert "QUARANTINE" in capsys.readouterr().out
    assert code == _EXIT_QUARANTINE_RECOMMENDED


# ── Failure modes ───────────────────────────────────────────────────────


def test_missing_fills_file_is_a_data_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["forensics", "circuit-breaker", str(tmp_path / "nope.jsonl")])
    assert "not found" in capsys.readouterr().out
    assert code == _EXIT_DATA_ERROR


def test_malformed_jsonl_names_the_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "fills.jsonl"
    path.write_text('{"strategy_id": "a"}\nnot json\n')

    code = main(["forensics", "circuit-breaker", str(path)])

    assert ":2:" in capsys.readouterr().out
    assert code == _EXIT_DATA_ERROR


def test_apply_without_config_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """--apply writes lifecycle state, so it must not guess which alphas."""
    fills = _write_session(
        tmp_path,
        [_record("bleeder_v1", realized_pnl="-10.00", ts=i) for i in range(40)],
    )

    code = main(["forensics", "circuit-breaker", str(fills), "--apply"])

    assert "--apply requires --config" in capsys.readouterr().out
    assert code != _EXIT_OK
