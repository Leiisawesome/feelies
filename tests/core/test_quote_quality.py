"""Quote-quality classifier. One rule, checked in a fixed order."""

from __future__ import annotations

from decimal import Decimal

from feelies.core.quote_quality import QuoteQuality, classify


def test_classify_one_case_per_class_and_precedence() -> None:
    assert classify(Decimal("10"), Decimal("10.02"), 1, 1) is QuoteQuality.VALID
    assert classify(Decimal("0"), Decimal("10"), 1, 1) is QuoteQuality.NONPOS
    assert classify(Decimal("10.02"), Decimal("10"), 1, 1) is QuoteQuality.CROSSED
    assert classify(Decimal("10"), Decimal("10"), 1, 1) is QuoteQuality.LOCKED
    assert classify(Decimal("10"), Decimal("10.02"), 0, 1) is QuoteQuality.ZERO_SZ
    assert classify(Decimal("0"), Decimal("0"), 0, 0) is QuoteQuality.NONPOS
    assert classify(Decimal("10.02"), Decimal("10"), 0, 1) is QuoteQuality.CROSSED
    assert classify(Decimal("10"), Decimal("10"), 0, 0) is QuoteQuality.LOCKED
