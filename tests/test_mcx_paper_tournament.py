import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from mcx_paper_portfolios import MCXPaperPortfolioBook
from mcx_tournament import TournamentLedger
from mcx_paper_tournament import MCXPaperTournamentBridge


class MCXPaperTournamentBridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ledger = TournamentLedger(
            path=str(Path(self.tmp.name) / "ledger.json"),
            target_pnl=1000,
            window_seconds=3600,
            min_trades=3,
            max_drawdown_fraction=0.10,
        )
        self.book = MCXPaperPortfolioBook(
            path=str(Path(self.tmp.name) / "portfolios.json"),
            starting_cash=100,
            max_position_fraction=0.06,
            max_total_exposure_fraction=0.30,
            slippage_bps=0,
            fee_bps=0,
        )
        self.bridge = MCXPaperTournamentBridge(
            self.ledger, self.book, population_size=2, max_quote_age_seconds=10
        )
        self.market = SimpleNamespace(
            market_id="m1", tradingsymbol="SYNTH", last_price=1.0, lot_size=1
        )

    def test_generations_get_isolated_portfolios_and_live_stays_locked(self):
        result = self.bridge.run_cycle(
            [self.market],
            lambda generation, market: 1 if generation == 1 else -1,
            quote_age_seconds=lambda market: 1,
        )
        self.assertEqual(len(result["results"]), 2)
        self.assertNotEqual(
            self.book.state["portfolios"]["1"]["positions"],
            self.book.state["portfolios"]["2"]["positions"],
        )
        self.assertFalse(result["live_orders_enabled"])
        self.assertEqual(result["broker_orders_submitted"], 0)

    def test_stale_quote_skipped_for_all_generations(self):
        result = self.bridge.run_cycle(
            [self.market], lambda generation, market: 1,
            quote_age_seconds=lambda market: 11,
        )
        self.assertTrue(all(row["skipped"] == 1 for row in result["results"]))
        self.assertEqual(self.book.snapshot(1)["open_positions"], 0)

    def test_provider_failure_fails_closed_and_is_reported(self):
        result = self.bridge.run_cycle(
            [self.market],
            lambda generation, market: (_ for _ in ()).throw(RuntimeError("bad strategy")),
            quote_age_seconds=lambda market: 1,
        )
        self.assertTrue(all(row["errors"] for row in result["results"]))
        self.assertEqual(self.book.snapshot(1)["open_positions"], 0)


if __name__ == "__main__":
    unittest.main()
