"""Unit tests for identifiers and correlation IDs."""

from __future__ import annotations

import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest

from feelies.core.identifiers import SequenceGenerator, derive_order_id, make_correlation_id


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


class TestDeriveOrderId:
    """Tests for derive_order_id (Inv-5 order-ID determinism primitive)."""

    def test_matches_sha256_contract_directly(self) -> None:
        seed = "AAPL:1700000000000000000:3:entry"
        expected = hashlib.sha256(seed.encode()).hexdigest()[:16]
        assert derive_order_id(seed) == expected

    def test_deterministic_for_same_seed(self) -> None:
        seed = "cid-1:5:AAPL:HAZARD_SPIKE"
        assert derive_order_id(seed) == derive_order_id(seed)

    def test_distinct_seeds_produce_distinct_ids(self) -> None:
        ids = {derive_order_id(f"cid-1:{seq}:AAPL:entry") for seq in range(50)}
        assert len(ids) == 50

    def test_output_is_16_lowercase_hex_chars(self) -> None:
        order_id = derive_order_id("cid-1:0:AAPL:exit")
        assert len(order_id) == 16
        assert order_id == order_id.lower()
        assert all(c in "0123456789abcdef" for c in order_id)


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
