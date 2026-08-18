"""X3 — a flattening order is permitted in every declared degraded state.

Inv-11 lets safety controls tighten autonomously, and every entry gate in
``BasicRiskEngine`` declares an exemption for the order that reduces
exposure.  PDT minimum equity, Reg-T buying power and the RTH/holiday
session gate each return ``None`` for a pure exit; the per-symbol cap is
measured on the post-fill quantity, which a flatten drives to zero; and the
two force-flatten states answer a flattening order by *demanding* the
flatten rather than refusing it.

Those exemptions hold today.  They are also what a reordering of the gates
removes without anyone noticing, because a suppressed exit emits nothing —
the position simply stays on.

Every case pairs the reduction with a control entry in the same state, and
the control is what makes the reduction assertion mean something.  An inert
gate — a ``None`` PDT constraint, unwired session bounds — permits the
reduction for the wrong reason, and without the control the case would pass
while testing nothing at all.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from feelies.core.events import (
    OrderRequest,
    OrderType,
    RiskAction,
    RiskVerdict,
    Side,
)
from feelies.execution.regulatory.pdt_constraint import (
    AccountType,
    PDTConfig,
    PDTConstraint,
)
from feelies.execution.trading_session import (
    MARKET_HOLIDAY,
    RTH_ENTRY_SUPPRESSED,
    resolve_trading_session_bounds,
)
from feelies.portfolio.memory_position_store import MemoryPositionStore
from feelies.risk.basic_risk import BasicRiskEngine, RiskConfig
from feelies.risk.buying_power import INSUFFICIENT_BUYING_POWER, BuyingPowerConfig

_SYMBOL = "AAPL"
_ACCOUNT = "conformance-acct"
_SESSION_DATE = date(2026, 3, 24)
_SESSION = resolve_trading_session_bounds(_SESSION_DATE)
_MIDDAY_NS = _SESSION.rth_open_ns + 3_600_000_000_000  # 10:30 ET
_AFTER_CLOSE_NS = _SESSION.rth_close_ns + 3_600_000_000_000  # 17:00 ET, same date


def _order(side: Side, quantity: int, timestamp_ns: int = _MIDDAY_NS) -> OrderRequest:
    return OrderRequest(
        timestamp_ns=timestamp_ns,
        correlation_id="x3",
        sequence=1,
        order_id="x3-ord",
        symbol=_SYMBOL,
        side=side,
        order_type=OrderType.MARKET,
        quantity=quantity,
    )


def _long_book(quantity: int = 100, mark: str = "100") -> MemoryPositionStore:
    """A long position, marked flat unless the case wants a loss."""
    store = MemoryPositionStore()
    store.update(_SYMBOL, quantity, Decimal("100"))
    store.update_mark(_SYMBOL, Decimal(mark))
    return store


def _loose_config(**overrides: object) -> RiskConfig:
    """Every limit slack except the one the case degrades."""
    kwargs: dict[str, object] = {
        "max_position_per_symbol": 100_000,
        "max_gross_exposure_pct": 100.0,
        "max_drawdown_pct": 99.0,
        "account_equity": Decimal("100000"),
    }
    kwargs.update(overrides)
    return RiskConfig(**kwargs)  # type: ignore[arg-type]


def _assert_entry_refused(verdict: RiskVerdict, expected_reason: str) -> None:
    """The control: this state really is degraded, and by the named gate.

    Without it a reduction can be permitted because the gate was never
    wired, which is indistinguishable from the exemption working.
    """
    assert verdict.action is RiskAction.REJECT, (
        f"control entry was not refused (action={verdict.action.name}, "
        f"reason={verdict.reason!r}) — the degraded state was never reached, "
        "so the reduction below proves nothing"
    )
    assert expected_reason in verdict.reason, (
        f"control entry was refused for {verdict.reason!r}, not {expected_reason!r} "
        "— the case is exercising a different gate than it claims"
    )


def _assert_reduction_permitted(verdict: RiskVerdict) -> None:
    assert verdict.action is RiskAction.ALLOW, (
        f"flattening order was not permitted: {verdict.action.name} "
        f"({verdict.reason!r}). A degraded state may tighten entries; refusing "
        "the exit strands the exposure it is trying to protect (Inv-11)."
    )


class TestPdtMinimumEquity:
    """PDT-flagged account below the $25k maintenance floor."""

    @staticmethod
    def _engine() -> BasicRiskEngine:
        constraint = PDTConstraint(
            PDTConfig(account_type=AccountType.MARGIN_25K, account_id=_ACCOUNT)
        )
        # Four same-day round trips is what raises the flag; below the floor
        # and unflagged, the gate stays open.
        for i in range(4):
            constraint.record_fill(_ACCOUNT, f"RT{i}", 0, 10, _MIDDAY_NS)
            constraint.record_fill(_ACCOUNT, f"RT{i}", 10, 0, _MIDDAY_NS)
        assert constraint.is_flagged(_ACCOUNT, _MIDDAY_NS)
        return BasicRiskEngine(
            _loose_config(account_equity=Decimal("20000")),
            pdt_constraint=constraint,
            account_id=_ACCOUNT,
        )

    def test_entry_refused_but_flatten_permitted(self) -> None:
        _assert_entry_refused(
            self._engine().check_order(_order(Side.BUY, 100), _long_book()),
            "PDT_MIN_EQUITY",
        )
        _assert_reduction_permitted(
            self._engine().check_order(_order(Side.SELL, 100), _long_book())
        )


class TestBuyingPowerExhausted:
    """Reg-T intraday gross above 4× live NAV.

    This exemption is held twice, so this case survives the removal of
    either guard alone: the entry classifier returns before the gate, and
    the prospective-gross arithmetic subtracts the closed position, which
    cannot exceed a limit the book was already under.  Both had to be
    removed together before the case failed.
    """

    @staticmethod
    def _engine() -> BasicRiskEngine:
        # $1,000 equity → $4,000 intraday limit, against a $10,000 book.
        return BasicRiskEngine(
            _loose_config(account_equity=Decimal("1000")),
            buying_power_config=BuyingPowerConfig(account_type="margin_25k"),
            account_id=_ACCOUNT,
        )

    def test_entry_refused_but_flatten_permitted(self) -> None:
        _assert_entry_refused(
            self._engine().check_order(_order(Side.BUY, 100), _long_book()),
            INSUFFICIENT_BUYING_POWER,
        )
        _assert_reduction_permitted(
            self._engine().check_order(_order(Side.SELL, 100), _long_book())
        )


class TestOutsideRegularHours:
    """Past the RTH close, on a session that is otherwise open."""

    @staticmethod
    def _engine() -> BasicRiskEngine:
        return BasicRiskEngine(
            _loose_config(),
            trading_session_bounds=_SESSION,
            account_id=_ACCOUNT,
        )

    def test_entry_refused_but_flatten_permitted(self) -> None:
        _assert_entry_refused(
            self._engine().check_order(_order(Side.BUY, 100, _AFTER_CLOSE_NS), _long_book()),
            RTH_ENTRY_SUPPRESSED,
        )
        _assert_reduction_permitted(
            self._engine().check_order(_order(Side.SELL, 100, _AFTER_CLOSE_NS), _long_book())
        )


class TestMarketHoliday:
    """A full-day holiday: no session at all, yet a position is on."""

    @staticmethod
    def _engine() -> BasicRiskEngine:
        return BasicRiskEngine(
            _loose_config(),
            trading_session_bounds=resolve_trading_session_bounds(_SESSION_DATE, is_holiday=True),
            account_id=_ACCOUNT,
        )

    def test_entry_refused_but_flatten_permitted(self) -> None:
        _assert_entry_refused(
            self._engine().check_order(_order(Side.BUY, 100), _long_book()),
            MARKET_HOLIDAY,
        )
        _assert_reduction_permitted(
            self._engine().check_order(_order(Side.SELL, 100), _long_book())
        )


class TestPositionLimitReached:
    """The per-symbol cap is already spent."""

    @staticmethod
    def _engine() -> BasicRiskEngine:
        return BasicRiskEngine(
            _loose_config(max_position_per_symbol=100),
            account_id=_ACCOUNT,
        )

    def test_entry_refused_but_flatten_permitted(self) -> None:
        _assert_entry_refused(
            self._engine().check_order(_order(Side.BUY, 100), _long_book()),
            "post-fill position",
        )
        _assert_reduction_permitted(
            self._engine().check_order(_order(Side.SELL, 100), _long_book())
        )


class TestForceFlattenStates:
    """Drawdown breach and non-positive equity.

    These two answer a flattening order with ``FORCE_FLATTEN`` rather than
    ``ALLOW``.  That is not a refusal: the orchestrator responds by
    flattening the book, so the reduction the order asked for happens and
    then some.  Asserting the reason keeps the case honest — a bare
    ``FORCE_FLATTEN`` could come from either state, or from a third.
    """

    def test_drawdown_breach_answers_a_flatten_with_a_flatten(self) -> None:
        engine = BasicRiskEngine(
            _loose_config(max_drawdown_pct=1.0),
            account_id=_ACCOUNT,
        )
        # Marked down to $50: a 5% drawdown on the $100k high-water mark.
        verdict = engine.check_order(_order(Side.SELL, 100), _long_book(mark="50"))
        assert verdict.action is RiskAction.FORCE_FLATTEN, (
            f"drawdown breach answered a flattening order with "
            f"{verdict.action.name} ({verdict.reason!r})"
        )
        assert "drawdown" in verdict.reason

    def test_non_positive_equity_answers_a_flatten_with_a_flatten(self) -> None:
        engine = BasicRiskEngine(_loose_config(), account_id=_ACCOUNT)
        store = MemoryPositionStore()
        # A $120k unrealized loss on a $100k account: live NAV is -$20k.
        store.update(_SYMBOL, 2000, Decimal("100"))
        store.update_mark(_SYMBOL, Decimal("40"))

        verdict = engine.check_order(_order(Side.SELL, 2000), store)
        assert verdict.action is RiskAction.FORCE_FLATTEN, (
            f"non-positive equity answered a flattening order with "
            f"{verdict.action.name} ({verdict.reason!r})"
        )
        assert "non-positive equity" in verdict.reason


class TestGrossExposureCap:
    """The book is already over the portfolio gross cap.

    ``_loose_config`` sets ``max_gross_exposure_pct: 100.0``, a cap that
    never binds on these books, so the other cases cannot reach this
    gate.  This case uses a binding 10% cap and a second symbol whose
    remaining notional still breaches after the flatten — the reduction
    is refused exactly when reducing matters.
    """

    @staticmethod
    def _engine() -> BasicRiskEngine:
        return BasicRiskEngine(
            _loose_config(max_gross_exposure_pct=10.0),
            account_id=_ACCOUNT,
        )

    @staticmethod
    def _over_cap_book() -> MemoryPositionStore:
        # $5,000 AAPL + $10,000 MSFT = $15,000 book against a $10,000 cap.
        store = MemoryPositionStore()
        store.update(_SYMBOL, 50, Decimal("100"))
        store.update("MSFT", 100, Decimal("100"))
        store.update_mark(_SYMBOL, Decimal("100"))
        store.update_mark("MSFT", Decimal("100"))
        return store

    def test_entry_refused_but_flatten_permitted(self) -> None:
        book = self._over_cap_book()
        _assert_entry_refused(
            self._engine().check_order(_order(Side.BUY, 50), book),
            "gross exposure limit",
        )
        _assert_reduction_permitted(
            self._engine().check_order(_order(Side.SELL, 50), book)
        )
