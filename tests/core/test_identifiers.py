"""Unit tests for identifiers and correlation IDs."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest

from feelies.core.identifiers import SequenceGenerator, make_correlation_id


class TestMakeCorrelationId:
    """Tests for make_correlation_id."""

    def test_format(self) -> None:
        cid = make_correlation_id("AAPL", 1700000000000000000, 42)
        assert cid == "AAPL:1700000000000000000:42"

    def test_links_symbol_timestamp_sequence(self) -> None:
        cid = make_correlation_id("MSFT", 1234567890, 1)
        parts = cid.split(":")
        assert parts[0] == "MSFT"
        assert parts[1] == "1234567890"
        assert parts[2] == "1"


class TestSequenceGenerator:
    """Tests for SequenceGenerator."""

    def test_starts_at_zero(self) -> None:
        gen = SequenceGenerator()
        assert gen.next() == 0

    def test_custom_start(self) -> None:
        gen = SequenceGenerator(start=100)
        assert gen.next() == 100
        assert gen.next() == 101

    def test_monotonic(self) -> None:
        gen = SequenceGenerator()
        values = [gen.next() for _ in range(10)]
        assert values == list(range(10))

    def test_thread_safe(self) -> None:
        gen = SequenceGenerator()
        results: list[int] = []

        def consume() -> int:
            return gen.next()

        with ThreadPoolExecutor(max_workers=8) as ex:
            futures = [ex.submit(consume) for _ in range(100)]
            for f in as_completed(futures):
                results.append(f.result())

        assert len(results) == 100
        assert len(set(results)) == 100
        assert sorted(results) == list(range(100))
