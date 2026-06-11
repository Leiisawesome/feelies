"""G-5 N0: cross-alpha netting contracts (pure)."""

from __future__ import annotations

from feelies.execution.portfolio_netter import (
    DesiredTargetBook,
    PortfolioNetter,
    StandingTarget,
    standing_target_from_desired,
)
from feelies.execution.position_manager import DesiredPosition


def _t(strategy_id: str, target_qty: int, **kw) -> StandingTarget:
    return StandingTarget(
        strategy_id=strategy_id,
        symbol="AAPL",
        target_qty=target_qty,
        **kw,
    )


class TestPortfolioNetter:
    def test_same_direction_alphas_stack(self) -> None:
        book = DesiredTargetBook()
        book.put(_t("a", 100, edge_bps=10.0))
        book.put(_t("b", 50, edge_bps=20.0))
        net = PortfolioNetter(book).net("AAPL", now_ns=0)
        assert net.target_qty == 150  # conviction stacks
        assert net.direction == 1
        # |qty|-weighted edge over aligned: (10*100 + 20*50)/150 = 13.33…
        assert round(net.edge_bps, 2) == 13.33

    def test_opposing_alphas_offset(self) -> None:
        book = DesiredTargetBook()
        book.put(_t("a", 100))
        book.put(_t("b", -80))
        net = PortfolioNetter(book).net("AAPL", now_ns=0)
        assert net.target_qty == 20  # net of the two
        assert net.direction == 1

    def test_full_offset_is_flat(self) -> None:
        book = DesiredTargetBook()
        book.put(_t("a", 60))
        book.put(_t("b", -60))
        net = PortfolioNetter(book).net("AAPL", now_ns=0)
        assert net.target_qty == 0
        assert net.direction == 0
        assert net.edge_bps == 0.0

    def test_per_alpha_budget_cap_applied_before_sum(self) -> None:
        book = DesiredTargetBook()
        book.put(_t("a", 200, max_abs_qty=100))  # clamped to 100
        book.put(_t("b", 50))
        net = PortfolioNetter(book).net("AAPL", now_ns=0)
        assert net.target_qty == 150  # 100 + 50, not 250

    def test_portfolio_cap_applied_to_net(self) -> None:
        book = DesiredTargetBook()
        book.put(_t("a", 150))
        book.put(_t("b", 150))
        net = PortfolioNetter(book, portfolio_max_abs_qty=200).net(
            "AAPL",
            now_ns=0,
        )
        assert net.target_qty == 200  # 300 capped to 200

    def test_portfolio_cap_is_symmetric_for_shorts(self) -> None:
        book = DesiredTargetBook()
        book.put(_t("a", -150))
        book.put(_t("b", -150))
        net = PortfolioNetter(book, portfolio_max_abs_qty=200).net(
            "AAPL",
            now_ns=0,
        )
        assert net.target_qty == -200

    def test_stale_targets_are_dropped(self) -> None:
        book = DesiredTargetBook()
        book.put(_t("a", 100, expiry_ns=1_000))
        book.put(_t("b", 50, expiry_ns=None))  # never expires
        netter = PortfolioNetter(book)
        assert netter.net("AAPL", now_ns=500).target_qty == 150  # both live
        # Boundary: fresh *at* expiry_ns, stale strictly after (matches the
        # orchestrator's signal-buffer policy ``age <= horizon × 1e9``).
        assert netter.net("AAPL", now_ns=1_000).target_qty == 150
        assert netter.net("AAPL", now_ns=1_001).target_qty == 50  # a expired
        assert netter.net("AAPL", now_ns=2_000).target_qty == 50

    def test_edge_uses_only_net_aligned_contributors(self) -> None:
        # net is long; the opposing short alpha's edge is excluded.
        book = DesiredTargetBook()
        book.put(_t("a", 100, edge_bps=12.0))
        book.put(_t("b", -40, edge_bps=99.0))
        net = PortfolioNetter(book).net("AAPL", now_ns=0)
        assert net.target_qty == 60
        assert net.edge_bps == 12.0  # only the long contributor

    def test_urgency_is_max_over_aligned(self) -> None:
        book = DesiredTargetBook()
        book.put(_t("a", 100, urgency=0.2))
        book.put(_t("b", 50, urgency=0.9))
        net = PortfolioNetter(book).net("AAPL", now_ns=0)
        assert net.urgency == 0.9

    def test_empty_book_is_flat(self) -> None:
        net = PortfolioNetter(DesiredTargetBook()).net("AAPL", now_ns=0)
        assert net.target_qty == 0 and net.direction == 0

    def test_net_is_order_independent(self) -> None:
        a, b, c = _t("a", 100), _t("b", -30), _t("c", 50)
        b1 = DesiredTargetBook()
        for t in (a, b, c):
            b1.put(t)
        b2 = DesiredTargetBook()
        for t in (c, a, b):
            b2.put(t)
        assert (
            PortfolioNetter(b1).net("AAPL", 0).target_qty
            == PortfolioNetter(b2).net("AAPL", 0).target_qty
            == 120
        )

    def test_only_named_symbol_is_netted(self) -> None:
        book = DesiredTargetBook()
        book.put(StandingTarget(strategy_id="a", symbol="AAPL", target_qty=100))
        book.put(StandingTarget(strategy_id="a", symbol="MSFT", target_qty=70))
        assert PortfolioNetter(book).net("AAPL", 0).target_qty == 100


class TestStandingTargetBuilder:
    def test_expiry_from_k_times_horizon(self) -> None:
        d = DesiredPosition(symbol="AAPL", target_qty=100, direction=1)
        st = standing_target_from_desired(
            d,
            strategy_id="a",
            signal_timestamp_ns=1_000_000_000,
            horizon_seconds=60,
            staleness_k=2.0,
            max_abs_qty=500,
        )
        assert st.target_qty == 100
        assert st.max_abs_qty == 500
        # 1e9 + 2 * 60 * 1e9 = 121e9
        assert st.expiry_ns == 121_000_000_000

    def test_no_expiry_when_horizon_or_k_nonpositive(self) -> None:
        d = DesiredPosition(symbol="AAPL", target_qty=100, direction=1)
        assert (
            standing_target_from_desired(
                d,
                strategy_id="a",
                signal_timestamp_ns=1,
                horizon_seconds=0,
                staleness_k=2.0,
            ).expiry_ns
            is None
        )
        assert (
            standing_target_from_desired(
                d,
                strategy_id="a",
                signal_timestamp_ns=1,
                horizon_seconds=60,
                staleness_k=0.0,
            ).expiry_ns
            is None
        )


class TestDesiredTargetBook:
    def test_set_get_clear(self) -> None:
        book = DesiredTargetBook()
        book.put(_t("a", 100))
        assert book.get("a", "AAPL").target_qty == 100
        book.clear("a", "AAPL")
        assert book.get("a", "AAPL") is None

    def test_set_overwrites_same_alpha_symbol(self) -> None:
        book = DesiredTargetBook()
        book.put(_t("a", 100))
        book.put(_t("a", 40))
        assert PortfolioNetter(book).net("AAPL", 0).target_qty == 40
