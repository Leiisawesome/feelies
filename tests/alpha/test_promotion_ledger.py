"""Tests for the append-only promotion evidence ledger (Workstream F-1).

Covers:
1.  Empty-ledger semantics (file created, ``len == 0``).
2.  Round-trip: append → entries() → equal.
3.  Append-only across multiple opens (two ledger instances on same path).
4.  ``entries_for`` filters by alpha_id deterministically.
5.  ``latest_for`` returns the most recently appended matching entry.
6.  JSONL format hygiene: each line valid JSON, sorted keys for stability.
7.  Schema-version field is present and round-trips.
8.  Corrupt line surfaces a structured ``ValueError`` naming line number.
9.  Missing-required-field surfaces a structured ``ValueError``.
10. ``PromotionLedgerEntry`` is frozen / immutable.
11. ``Decimal`` values in ``metadata.evidence`` round-trip via canonical
    string (forensic-evidence-safe).
12. Replay determinism: 100 round-trips → byte-identical file.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from feelies.alpha.promotion_ledger import (
    LEDGER_SCHEMA_VERSION,
    PromotionLedger,
    PromotionLedgerEntry,
)


def _entry(
    *,
    alpha_id: str = "demo",
    from_state: str = "RESEARCH",
    to_state: str = "PAPER",
    trigger: str = "pass_paper_gate",
    timestamp_ns: int = 1_700_000_000_000_000_000,
    correlation_id: str = "corr-1",
    metadata: dict[str, object] | None = None,
) -> PromotionLedgerEntry:
    return PromotionLedgerEntry(
        alpha_id=alpha_id,
        from_state=from_state,
        to_state=to_state,
        trigger=trigger,
        timestamp_ns=timestamp_ns,
        correlation_id=correlation_id,
        metadata=metadata if metadata is not None else {},
    )


class TestPromotionLedgerEmpty:
    def test_creates_empty_file(self, tmp_path: Path) -> None:
        path = tmp_path / "ledger.jsonl"
        ledger = PromotionLedger(path)

        assert path.exists()
        assert path.read_text(encoding="utf-8") == ""
        assert len(ledger) == 0
        assert list(ledger.entries()) == []

    def test_creates_parent_directory(self, tmp_path: Path) -> None:
        path = tmp_path / "deep" / "nested" / "ledger.jsonl"
        PromotionLedger(path)

        assert path.parent.is_dir()
        assert path.exists()

    def test_path_property_exposes_path(self, tmp_path: Path) -> None:
        path = tmp_path / "ledger.jsonl"
        ledger = PromotionLedger(path)

        assert ledger.path == path


class TestPromotionLedgerAppend:
    def test_append_single_entry_round_trips(self, tmp_path: Path) -> None:
        ledger = PromotionLedger(tmp_path / "ledger.jsonl")
        entry = _entry()

        ledger.append(entry)

        recovered = list(ledger.entries())
        assert recovered == [entry]
        assert len(ledger) == 1

    def test_append_preserves_order(self, tmp_path: Path) -> None:
        ledger = PromotionLedger(tmp_path / "ledger.jsonl")
        entries = [
            _entry(alpha_id=f"alpha_{i}", timestamp_ns=1_700_000_000_000_000_000 + i)
            for i in range(5)
        ]

        for entry in entries:
            ledger.append(entry)

        assert list(ledger.entries()) == entries

    def test_append_only_across_reopens(self, tmp_path: Path) -> None:
        path = tmp_path / "ledger.jsonl"

        first = PromotionLedger(path)
        first.append(_entry(alpha_id="first"))

        second = PromotionLedger(path)
        second.append(_entry(alpha_id="second"))

        third = PromotionLedger(path)
        recovered = list(third.entries())
        assert [e.alpha_id for e in recovered] == ["first", "second"]

    def test_iter_dunder_returns_entries(self, tmp_path: Path) -> None:
        ledger = PromotionLedger(tmp_path / "ledger.jsonl")
        ledger.append(_entry(alpha_id="x"))
        ledger.append(_entry(alpha_id="y"))

        assert [e.alpha_id for e in ledger] == ["x", "y"]


class TestPromotionLedgerFiltering:
    def test_entries_for_filters_by_alpha_id(self, tmp_path: Path) -> None:
        ledger = PromotionLedger(tmp_path / "ledger.jsonl")
        ledger.append(_entry(alpha_id="kyle"))
        ledger.append(_entry(alpha_id="hawkes"))
        ledger.append(_entry(alpha_id="kyle", to_state="LIVE", trigger="pass_live_gate"))
        ledger.append(_entry(alpha_id="inventory"))

        kyle_entries = list(ledger.entries_for("kyle"))
        assert len(kyle_entries) == 2
        assert all(e.alpha_id == "kyle" for e in kyle_entries)
        assert kyle_entries[0].to_state == "PAPER"
        assert kyle_entries[1].to_state == "LIVE"

    def test_entries_for_unknown_alpha_returns_empty(self, tmp_path: Path) -> None:
        ledger = PromotionLedger(tmp_path / "ledger.jsonl")
        ledger.append(_entry(alpha_id="kyle"))

        assert list(ledger.entries_for("nonexistent")) == []

    def test_latest_for_returns_most_recent(self, tmp_path: Path) -> None:
        ledger = PromotionLedger(tmp_path / "ledger.jsonl")
        ledger.append(
            _entry(alpha_id="kyle", to_state="PAPER", timestamp_ns=1_000)
        )
        ledger.append(_entry(alpha_id="other", timestamp_ns=2_000))
        ledger.append(
            _entry(
                alpha_id="kyle",
                from_state="PAPER",
                to_state="LIVE",
                trigger="pass_live_gate",
                timestamp_ns=3_000,
            )
        )

        latest = ledger.latest_for("kyle")
        assert latest is not None
        assert latest.to_state == "LIVE"
        assert latest.timestamp_ns == 3_000

    def test_latest_for_returns_none_when_no_entries(self, tmp_path: Path) -> None:
        ledger = PromotionLedger(tmp_path / "ledger.jsonl")

        assert ledger.latest_for("anything") is None


class TestPromotionLedgerJSONFormat:
    def test_each_line_is_valid_json_with_newline_terminator(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "ledger.jsonl"
        ledger = PromotionLedger(path)

        ledger.append(_entry(alpha_id="a"))
        ledger.append(_entry(alpha_id="b"))

        raw = path.read_text(encoding="utf-8")
        assert raw.endswith("\n")
        lines = raw.splitlines()
        assert len(lines) == 2
        for line in lines:
            assert line.strip() == line  # no leading/trailing whitespace
            import json

            obj = json.loads(line)
            assert isinstance(obj, dict)
            assert "schema_version" in obj
            assert "alpha_id" in obj

    def test_keys_are_sorted_for_stability(self, tmp_path: Path) -> None:
        path = tmp_path / "ledger.jsonl"
        ledger = PromotionLedger(path)
        ledger.append(_entry())

        line = path.read_text(encoding="utf-8").rstrip("\n")
        import json

        # ``sort_keys=True`` produces a canonical, byte-stable encoding
        # so a freshly-encoded copy MUST equal the on-disk line.
        recoded = json.dumps(json.loads(line), sort_keys=True)
        assert recoded == line

    def test_schema_version_present(self, tmp_path: Path) -> None:
        ledger = PromotionLedger(tmp_path / "ledger.jsonl")
        ledger.append(_entry())

        recovered = list(ledger.entries())[0]
        assert recovered.schema_version == LEDGER_SCHEMA_VERSION


class TestPromotionLedgerCorruptInput:
    def test_corrupt_json_line_raises_value_error_with_lineno(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "ledger.jsonl"
        ledger = PromotionLedger(path)
        ledger.append(_entry(alpha_id="ok"))
        with path.open("a", encoding="utf-8") as fh:
            fh.write("{not valid json\n")

        with pytest.raises(ValueError, match=r"ledger\.jsonl:2"):
            list(ledger.entries())

    def test_missing_required_field_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "ledger.jsonl"
        ledger = PromotionLedger(path)
        with path.open("a", encoding="utf-8") as fh:
            fh.write('{"schema_version": "1.0.0", "alpha_id": "x"}\n')

        with pytest.raises(ValueError, match="missing required field"):
            list(ledger.entries())

    def test_non_object_payload_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "ledger.jsonl"
        ledger = PromotionLedger(path)
        with path.open("a", encoding="utf-8") as fh:
            fh.write('"not an object"\n')

        with pytest.raises(ValueError, match="must decode to an object"):
            list(ledger.entries())

    def test_blank_lines_are_ignored(self, tmp_path: Path) -> None:
        path = tmp_path / "ledger.jsonl"
        ledger = PromotionLedger(path)
        ledger.append(_entry(alpha_id="a"))
        with path.open("a", encoding="utf-8") as fh:
            fh.write("\n")
            fh.write("\n")
        ledger.append(_entry(alpha_id="b"))

        recovered = list(ledger.entries())
        assert [e.alpha_id for e in recovered] == ["a", "b"]


class TestPromotionLedgerEntryImmutability:
    def test_entry_is_frozen(self) -> None:
        entry = _entry()

        with pytest.raises(Exception):
            # frozen dataclasses raise FrozenInstanceError; surface as
            # generic Exception so this is robust to py-version drift.
            entry.alpha_id = "mutated"  # type: ignore[misc]

    def test_default_correlation_id_is_empty_string(self) -> None:
        entry = PromotionLedgerEntry(
            alpha_id="x",
            from_state="RESEARCH",
            to_state="PAPER",
            trigger="t",
            timestamp_ns=0,
        )
        assert entry.correlation_id == ""
        assert entry.metadata == {}


class TestPromotionLedgerDecimalSafety:
    def test_decimal_in_metadata_round_trips_as_string(
        self, tmp_path: Path
    ) -> None:
        ledger = PromotionLedger(tmp_path / "ledger.jsonl")
        original_metadata: dict[str, object] = {
            "evidence": {
                "realized_margin_ratio": Decimal("1.234567"),
                "paper_sharpe": Decimal("1.05"),
            },
        }
        entry = _entry(metadata=original_metadata)

        ledger.append(entry)

        recovered = list(ledger.entries())[0]
        ev = recovered.metadata["evidence"]
        assert isinstance(ev, dict)
        # canonical string preserves the exact decimal representation
        assert ev["realized_margin_ratio"] == "1.234567"
        assert ev["paper_sharpe"] == "1.05"

    def test_unsupported_type_raises_type_error(
        self, tmp_path: Path
    ) -> None:
        ledger = PromotionLedger(tmp_path / "ledger.jsonl")
        entry = _entry(metadata={"thing": object()})

        with pytest.raises(TypeError, match="non-JSON-serialisable"):
            ledger.append(entry)


class TestPromotionLedgerReplayDeterminism:
    def test_repeated_append_produces_identical_file(
        self, tmp_path: Path
    ) -> None:
        # Build the same evidence-stream twice in two fresh ledgers and
        # assert the on-disk bytes match exactly.  This is the F-1
        # replay-determinism guarantee that downstream gate-replay
        # tests will rely on.
        evidence_stream = [
            _entry(
                alpha_id=f"alpha_{i % 3}",
                trigger="pass_paper_gate",
                timestamp_ns=1_700_000_000_000_000_000 + i,
                correlation_id=f"corr-{i:04d}",
                metadata={"evidence": {"paper_days": i, "paper_sharpe": 1.0 + 0.01 * i}},
            )
            for i in range(100)
        ]

        path_a = tmp_path / "a.jsonl"
        ledger_a = PromotionLedger(path_a)
        for e in evidence_stream:
            ledger_a.append(e)

        path_b = tmp_path / "b.jsonl"
        ledger_b = PromotionLedger(path_b)
        for e in evidence_stream:
            ledger_b.append(e)

        assert path_a.read_bytes() == path_b.read_bytes()
        assert list(ledger_a.entries()) == list(ledger_b.entries())
