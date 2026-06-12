"""Unit tests for MassiveHistoricalIngestor."""

from __future__ import annotations

import importlib.util
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from feelies.core.clock import SimulatedClock
from feelies.core.errors import DataIntegrityError
from feelies.ingestion.massive_ingestor import (
    InMemoryCheckpoint,
    MassiveHistoricalIngestor,
    _download_raw,
    _model_to_dict,
)
from feelies.ingestion.massive_normalizer import MassiveNormalizer
from feelies.storage.memory_event_log import InMemoryEventLog

# Tests that ``patch("massive.RESTClient", ...)`` need the optional vendor SDK
# to be importable (``mock.patch`` resolves the target module eagerly).  Skip
# them cleanly when the ``massive`` extra is absent so a vanilla checkout is
# green without the vendor dependency (audit ING-09).
_MASSIVE_ABSENT = importlib.util.find_spec("massive") is None
_requires_massive = pytest.mark.skipif(
    _MASSIVE_ABSENT,
    reason="massive SDK not installed; patch('massive.RESTClient') requires the package",
)


def _make_mock_quote(seq: int = 1, ts_ns: int = 1700000000000000000) -> Any:
    """Create a mock object resembling massive Quote model with __annotations__ on class."""

    class MockQuote:
        __annotations__ = {
            "ask_exchange": int,
            "ask_price": float,
            "ask_size": float,
            "bid_exchange": int,
            "bid_price": float,
            "bid_size": float,
            "conditions": list,
            "indicators": list,
            "participant_timestamp": int,
            "sequence_number": int,
            "sip_timestamp": int,
            "tape": int,
            "trf_timestamp": int,
        }

        def __init__(self, **kwargs: Any) -> None:
            for k, v in kwargs.items():
                setattr(self, k, v)

    return MockQuote(
        ask_exchange=12,
        ask_price=150.05,
        ask_size=100.0,
        bid_exchange=11,
        bid_price=150.0,
        bid_size=90.0,
        conditions=[1, 2],
        indicators=[],
        participant_timestamp=None,
        sequence_number=seq,
        sip_timestamp=ts_ns,
        tape=3,
        trf_timestamp=None,
    )


def _make_mock_trade(seq: int = 1, ts_ns: int = 1700000000001000000) -> Any:
    """Create a mock object resembling massive Trade model."""

    class MockTrade:
        __annotations__ = {
            "conditions": list,
            "correction": int,
            "exchange": int,
            "id": str,
            "participant_timestamp": int,
            "price": float,
            "sequence_number": int,
            "sip_timestamp": int,
            "size": float,
            "tape": int,
            "trf_id": int,
            "trf_timestamp": int,
        }

        def __init__(self, **kwargs: Any) -> None:
            for k, v in kwargs.items():
                setattr(self, k, v)

    return MockTrade(
        conditions=[0, 12],
        correction=0,
        exchange=11,
        id="trade123",
        participant_timestamp=None,
        price=150.02,
        sequence_number=seq,
        sip_timestamp=ts_ns,
        size=100.0,
        tape=3,
        trf_id=5,
        trf_timestamp=None,
    )


class TestModelToDict:
    """Tests for _model_to_dict helper."""

    def test_converts_mock_quote_to_dict(self) -> None:
        quote = _make_mock_quote()
        out = _model_to_dict(quote, "AAPL")
        assert out["ticker"] == "AAPL"
        assert out["bid_price"] == 150.0
        assert out["ask_price"] == 150.05
        assert out["sip_timestamp"] == 1700000000000000000
        assert out["sequence_number"] == 1

    def test_converts_mock_trade_to_dict(self) -> None:
        trade = _make_mock_trade()
        out = _model_to_dict(trade, "MSFT")
        assert out["ticker"] == "MSFT"
        assert out["price"] == 150.02
        assert out["size"] == 100.0
        assert out["sip_timestamp"] == 1700000000001000000

    def test_injects_ticker_if_missing(self) -> None:
        quote = _make_mock_quote()
        out = _model_to_dict(quote, "GOOG")
        assert out["ticker"] == "GOOG"

    def test_plain_dict_passthrough(self) -> None:
        d = {"ticker": "AAPL", "bid_price": 100.0, "sip_timestamp": 123}
        out = _model_to_dict(d, "AAPL")
        assert out == {"ticker": "AAPL", "bid_price": 100.0, "sip_timestamp": 123}

    def test_ticker_mismatch_is_dropped(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """r3-INGEST-05: upstream returning ``ticker="MSFT"`` for an AAPL
        request must not pollute the MSFT state machine.
        """
        d = {"ticker": "MSFT", "bid_price": 100.0, "sip_timestamp": 123}
        with caplog.at_level("WARNING", "feelies.ingestion.massive_ingestor"):
            out = _model_to_dict(d, "AAPL")
        assert out == {}
        assert any(
            "ticker" in r.getMessage() and "does not match" in r.getMessage()
            for r in caplog.records
        )

    def test_ticker_case_insensitive_match(self) -> None:
        # ``"aapl"`` and ``"AAPL"`` are the same symbol per platform
        # conventions; the mismatch guard must not over-match.
        d = {"ticker": "aapl", "bid_price": 100.0, "sip_timestamp": 123}
        out = _model_to_dict(d, "AAPL")
        assert out["ticker"] == "aapl"  # original case preserved


class TestMassiveHistoricalIngestor:
    """Tests for MassiveHistoricalIngestor with mocked REST client."""

    @pytest.mark.skipif(
        importlib.util.find_spec("massive") is not None,
        reason="massive installed; ImportError path only testable when package absent",
    )
    def test_ingest_raises_without_massive_package(self) -> None:
        """When massive is not installed, ingest raises ImportError."""
        ingestor = MassiveHistoricalIngestor(
            api_key="test-key",
            normalizer=MassiveNormalizer(SimulatedClock()),
            event_log=InMemoryEventLog(),
            clock=SimulatedClock(),
        )
        with pytest.raises(ImportError, match="massive"):
            ingestor.ingest(["AAPL"], "2024-01-01", "2024-01-01")

    @_requires_massive
    def test_ingest_with_mocked_rest_client(self) -> None:
        """Ingest uses REST client and persists normalized events."""
        clock = SimulatedClock(1700000000000000000)
        normalizer = MassiveNormalizer(clock)
        event_log = InMemoryEventLog()

        mock_client = MagicMock()
        mock_client.list_quotes = MagicMock(return_value=iter([_make_mock_quote()]))
        mock_client.list_trades = MagicMock(return_value=iter([_make_mock_trade()]))

        ingestor = MassiveHistoricalIngestor(
            api_key="test",
            normalizer=normalizer,
            event_log=event_log,
            clock=clock,
        )

        with patch("massive.RESTClient", return_value=mock_client):
            result = ingestor.ingest(["AAPL"], "2024-01-01", "2024-01-02")

        assert result.events_ingested >= 2  # at least 1 quote + 1 trade
        assert result.symbols_completed == frozenset({"AAPL"})
        assert len(event_log) >= 2


class TestParallelDownload:
    """Tests for ingest_symbol_parallel (parallel download, sequential normalize)."""

    def test_parallel_downloads_both_feeds(self) -> None:
        """ingest_symbol_parallel calls list_quotes and list_trades."""
        clock = SimulatedClock(1700000000000000000)
        normalizer = MassiveNormalizer(clock)
        event_log = InMemoryEventLog()

        mock_client = MagicMock()
        mock_client.list_quotes = MagicMock(return_value=iter([_make_mock_quote()]))
        mock_client.list_trades = MagicMock(return_value=iter([_make_mock_trade()]))

        ingestor = MassiveHistoricalIngestor(
            api_key="test",
            normalizer=normalizer,
            event_log=event_log,
            clock=clock,
        )

        ev_count, pg_count = ingestor.ingest_symbol_parallel(
            mock_client,
            "AAPL",
            "2024-01-01",
            "2024-01-02",
        )

        mock_client.list_quotes.assert_called_once()
        mock_client.list_trades.assert_called_once()
        assert ev_count >= 2
        assert pg_count >= 2
        assert len(event_log) >= 2

    def test_parallel_produces_chronological_order(self) -> None:
        """Events are merge-sorted by sip_timestamp across feeds."""
        clock = SimulatedClock(1700000000000000000)
        normalizer = MassiveNormalizer(clock)
        event_log = InMemoryEventLog()

        q1 = _make_mock_quote(seq=1, ts_ns=1700000000000000000)
        q2 = _make_mock_quote(seq=2, ts_ns=1700000000003000000)
        t1 = _make_mock_trade(seq=1, ts_ns=1700000000001000000)
        t2 = _make_mock_trade(seq=2, ts_ns=1700000000002000000)

        mock_client = MagicMock()
        mock_client.list_quotes = MagicMock(return_value=iter([q1, q2]))
        mock_client.list_trades = MagicMock(return_value=iter([t1, t2]))

        ingestor = MassiveHistoricalIngestor(
            api_key="test",
            normalizer=normalizer,
            event_log=event_log,
            clock=clock,
        )

        ingestor.ingest_symbol_parallel(
            mock_client,
            "AAPL",
            "2024-01-01",
            "2024-01-02",
        )

        events = list(event_log.replay())
        timestamps = [e.exchange_timestamp_ns for e in events]
        assert timestamps == sorted(timestamps), "events must be in chronological order"

    def test_same_ns_quote_trade_run_across_chunk_boundary(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ING-02: a same-nanosecond quote/trade run straddling a chunk
        boundary must not raise ``CausalityViolation``.

        Quotes carry odd vendor sequences, trades carry even ones, all at the
        *same* ``sip_timestamp``.  Under the old raw sort key
        ``(sip_timestamp, sequence_number, type_rank)`` the events interleave
        quote/trade by sequence, and per-chunk canonical stabilization then
        produces a backward merge-key across the chunk boundary.  The aligned
        key ``(sip_timestamp, type_rank, sequence_number)`` keeps all quotes
        before all trades, so no boundary inversion occurs.
        """
        from feelies.storage import event_resequence

        # Force a tiny chunk so 6 events straddle a boundary.
        monkeypatch.setattr("feelies.ingestion.massive_ingestor._CHUNK_SIZE", 4)

        ts = 1700000000000000000
        quotes = [_make_mock_quote(seq=s, ts_ns=ts) for s in (1, 3, 5)]
        trades = [_make_mock_trade(seq=s, ts_ns=ts) for s in (2, 4, 6)]

        clock = SimulatedClock(ts)
        normalizer = MassiveNormalizer(clock)
        event_log = InMemoryEventLog()
        mock_client = MagicMock()
        mock_client.list_quotes = MagicMock(return_value=iter(quotes))
        mock_client.list_trades = MagicMock(return_value=iter(trades))

        ingestor = MassiveHistoricalIngestor(
            api_key="test",
            normalizer=normalizer,
            event_log=event_log,
            clock=clock,
        )

        # Must not raise CausalityViolation.
        ingestor.ingest_symbol_parallel(mock_client, "AAPL", "2024-01-01", "2024-01-01")

        stored = list(event_log.replay())
        assert len(stored) == 6
        keys = [event_resequence.event_merge_sort_key(e) for e in stored]
        assert keys == sorted(keys), "stored events must be in canonical merge-key order"

    def test_multi_symbol_overlapping_timestamps_via_scratch_log(self) -> None:
        """ING-10: per-symbol full-session batches with overlapping exchange
        timestamps accumulate into an order-tolerant scratch log and resequence
        to global order — without tripping the cross-symbol monotonicity guard.
        """
        from feelies.core.events import NBBOQuote, Trade
        from feelies.storage.event_resequence import (
            event_merge_sort_key,
            resequence_event_list,
        )

        ts0 = 1700000000000000000
        clock = SimulatedClock(ts0)
        normalizer = MassiveNormalizer(clock)
        ingestor = MassiveHistoricalIngestor(
            api_key="t",
            normalizer=normalizer,
            event_log=InMemoryEventLog(),
            clock=clock,
        )

        # AAPL spans [ts0, ts0+2000]; MSFT *overlaps* it (starts back at ts0).
        aapl = MagicMock()
        aapl.list_quotes = MagicMock(
            return_value=iter(
                [_make_mock_quote(seq=1, ts_ns=ts0), _make_mock_quote(seq=2, ts_ns=ts0 + 2000)]
            )
        )
        aapl.list_trades = MagicMock(return_value=iter([_make_mock_trade(seq=1, ts_ns=ts0 + 1000)]))
        msft = MagicMock()
        msft.list_quotes = MagicMock(return_value=iter([_make_mock_quote(seq=1, ts_ns=ts0)]))
        msft.list_trades = MagicMock(return_value=iter([_make_mock_trade(seq=1, ts_ns=ts0 + 500)]))

        scratch = InMemoryEventLog(enforce_market_order=False)
        ingestor.ingest_symbol_parallel(aapl, "AAPL", "2024-01-01", "2024-01-01", target_log=scratch)
        # This second append carries earlier timestamps than AAPL's last event;
        # it must NOT raise on the order-tolerant scratch log.
        ingestor.ingest_symbol_parallel(msft, "MSFT", "2024-01-01", "2024-01-01", target_log=scratch)

        merged = [e for e in scratch.replay() if isinstance(e, (NBBOQuote, Trade))]
        reseq = resequence_event_list(merged)
        keys = [event_merge_sort_key(e) for e in reseq]
        assert keys == sorted(keys), "resequenced multi-symbol stream must be globally ordered"
        assert {e.symbol for e in reseq} == {"AAPL", "MSFT"}

    def test_strict_scratch_would_reject_overlapping_second_symbol(self) -> None:
        """ING-10 guard rail: prove the strict log *would* crash — the reason the
        multi-symbol path must accumulate into a relaxed scratch log.
        """
        from feelies.core.errors import CausalityViolation

        ts0 = 1700000000000000000
        clock = SimulatedClock(ts0)
        normalizer = MassiveNormalizer(clock)
        ingestor = MassiveHistoricalIngestor(
            api_key="t",
            normalizer=normalizer,
            event_log=InMemoryEventLog(),
            clock=clock,
        )

        aapl = MagicMock()
        aapl.list_quotes = MagicMock(return_value=iter([_make_mock_quote(seq=1, ts_ns=ts0 + 2000)]))
        aapl.list_trades = MagicMock(return_value=iter([]))
        msft = MagicMock()
        msft.list_quotes = MagicMock(return_value=iter([_make_mock_quote(seq=1, ts_ns=ts0)]))
        msft.list_trades = MagicMock(return_value=iter([]))

        strict = InMemoryEventLog()  # default enforce_market_order=True
        ingestor.ingest_symbol_parallel(aapl, "AAPL", "2024-01-01", "2024-01-01", target_log=strict)
        with pytest.raises(CausalityViolation):
            ingestor.ingest_symbol_parallel(
                msft, "MSFT", "2024-01-01", "2024-01-01", target_log=strict
            )

    @_requires_massive
    def test_ingest_delegates_to_parallel(self) -> None:
        """ingest() routes through ingest_symbol_parallel."""
        clock = SimulatedClock(1700000000000000000)
        normalizer = MassiveNormalizer(clock)
        event_log = InMemoryEventLog()

        mock_client = MagicMock()
        mock_client.list_quotes = MagicMock(return_value=iter([_make_mock_quote()]))
        mock_client.list_trades = MagicMock(return_value=iter([_make_mock_trade()]))

        ingestor = MassiveHistoricalIngestor(
            api_key="test",
            normalizer=normalizer,
            event_log=event_log,
            clock=clock,
        )

        with patch("massive.RESTClient", return_value=mock_client):
            result = ingestor.ingest(["AAPL"], "2024-01-01", "2024-01-02")

        mock_client.list_quotes.assert_called_once()
        mock_client.list_trades.assert_called_once()
        assert result.events_ingested >= 2
        assert result.symbols_completed == frozenset({"AAPL"})


class TestDownloadIntegrityAndCheckpoint:
    """Failed REST pagination must not normalize or checkpoint partial streams."""

    def test_ingest_raises_when_quotes_download_aborts(self) -> None:
        ckpt = InMemoryCheckpoint()
        clock = SimulatedClock(1700000000000000000)
        normalizer = MassiveNormalizer(clock)
        event_log = InMemoryEventLog()

        mock_client = MagicMock()
        mock_client.list_quotes = MagicMock(side_effect=RuntimeError("network"))
        mock_client.list_trades = MagicMock(return_value=iter([_make_mock_trade()]))

        ingestor = MassiveHistoricalIngestor(
            api_key="test",
            normalizer=normalizer,
            event_log=event_log,
            clock=clock,
            checkpoint=ckpt,
        )

        with pytest.raises(DataIntegrityError, match="quotes REST pagination"):
            ingestor.ingest_symbol_parallel(
                mock_client,
                "AAPL",
                "2024-01-01",
                "2024-01-02",
            )

        assert not ckpt.is_done("AAPL", "quotes")
        assert not ckpt.is_done("AAPL", "trades")
        assert len(event_log) == 0

    def test_ingest_raises_when_trades_download_aborts(self) -> None:
        ckpt = InMemoryCheckpoint()
        clock = SimulatedClock(1700000000000000000)
        normalizer = MassiveNormalizer(clock)
        event_log = InMemoryEventLog()

        mock_client = MagicMock()
        mock_client.list_quotes = MagicMock(return_value=iter([_make_mock_quote()]))
        mock_client.list_trades = MagicMock(side_effect=RuntimeError("network"))

        ingestor = MassiveHistoricalIngestor(
            api_key="test",
            normalizer=normalizer,
            event_log=event_log,
            clock=clock,
            checkpoint=ckpt,
        )

        with pytest.raises(DataIntegrityError, match="trades REST pagination"):
            ingestor.ingest_symbol_parallel(
                mock_client,
                "AAPL",
                "2024-01-01",
                "2024-01-02",
            )

        assert not ckpt.is_done("AAPL", "quotes")
        assert not ckpt.is_done("AAPL", "trades")
        assert len(event_log) == 0

    def test_download_raw_reports_incomplete_on_mid_iteration_error(self) -> None:
        """Third-party iterators that raise mid-flight must set completed_ok False."""

        class BoomIterator:
            def __init__(self) -> None:
                self._n = 0

            def __iter__(self) -> BoomIterator:
                return self

            def __next__(self) -> Any:
                self._n += 1
                if self._n == 2:
                    raise RuntimeError("pagination boom")
                return _make_mock_quote(seq=self._n)

        mock_client = MagicMock()

        def _list_fn(symbol: str, **kwargs: Any) -> BoomIterator:
            return BoomIterator()

        raw, pages, ok = _download_raw(
            mock_client,
            "AAPL",
            "2024-01-01",
            "2024-01-01",
            _list_fn,
            "quotes",
        )
        assert ok is False
        assert len(raw) >= 1


class TestDuplicateCountingInIngestor:
    """Tests that IngestResult.duplicates_filtered reflects normalizer counts."""

    @_requires_massive
    def test_reports_duplicates_from_normalizer(self) -> None:
        clock = SimulatedClock(1700000000000000000)
        normalizer = MassiveNormalizer(clock)
        event_log = InMemoryEventLog()

        same_quote = _make_mock_quote(seq=1, ts_ns=1700000000000000000)

        mock_client = MagicMock()
        mock_client.list_quotes = MagicMock(
            return_value=iter([same_quote, same_quote, same_quote]),
        )
        mock_client.list_trades = MagicMock(return_value=iter([]))

        ingestor = MassiveHistoricalIngestor(
            api_key="test",
            normalizer=normalizer,
            event_log=event_log,
            clock=clock,
        )

        with patch("massive.RESTClient", return_value=mock_client):
            result = ingestor.ingest(["AAPL"], "2024-01-01", "2024-01-02")

        assert result.duplicates_filtered == 2
        assert result.events_ingested == 1
