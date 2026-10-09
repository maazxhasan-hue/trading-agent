import tempfile
import unittest
from pathlib import Path

from mcx_paper_portfolios import MCXPaperPortfolioBook


class MCXPaperPortfolioBookTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.book = MCXPaperPortfolioBook(
            path=str(Path(self.tmp.name) / "portfolios.json"),
            starting_cash=100,
            max_position_fraction=0.06,
            max_total_exposure_fraction=0.30,
            slippage_bps=0,
            fee_bps=0,
            max_hold_cycles=3,
        )
        self.market = {
            "market_id": "token-1",
            "tradingsymbol": "GOLDM",
            "last_price": 1000,
            "lot_size": 1,
        }

    def test_isolated_portfolios_do_not_share_cash_or_positions(self):
        self.book.ensure_generation(1)
        self.book.ensure_generation(2)
        self.book.process_snapshot(1, self.market, 1)
        first = self.book.snapshot(1)
        second = self.book.snapshot(2)
        self.assertEqual(first["open_positions"], 0)  # ₹6 cap cannot buy one unit at ₹1,000
        self.assertEqual(first["cash"], 100)
        self.assertEqual(second["cash"], 100)
        self.assertFalse(first["live_orders_enabled"])

    def test_affordable_synthetic_unit_can_open_and_close_on_opposite_signal(self):
        market = {**self.market, "last_price": 1, "lot_size": 1}
        result = self.book.process_snapshot(1, market, 1)
        self.assertTrue(result["opened"])
        self.assertEqual(self.book.snapshot(1)["open_positions"], 1)
        closed = self.book.process_snapshot(1, {**market, "last_price": 1.1}, -1)
        self.assertEqual(len(closed["closed_trades"]), 1)
        self.assertEqual(closed["closed_trades"][0]["reason"], "opposite_signal")
        self.assertGreater(closed["closed_trades"][0]["net_pnl"], 0)

    def test_persistence_reloads_each_generation(self):
        self.book.ensure_generation(4)
        reloaded = MCXPaperPortfolioBook(path=self.book.path, starting_cash=999)
        self.assertEqual(reloaded.snapshot(4)["cash"], 100)
        self.assertEqual(reloaded.snapshot(5)["cash"], 999)

    def test_missing_price_does_not_fabricate_generation_exit(self):
        market = {**self.market, "last_price": 10, "lot_size": 1}
        self.book.process_snapshot(1, market, 1)
        closed = self.book.close_generation(1, {}, reason="retired")
        self.assertEqual(closed, [])
        self.assertEqual(self.book.snapshot(1)["open_positions"], 1)


if __name__ == "__main__":
    unittest.main()
