import json
import tempfile
import unittest
from datetime import datetime, timezone, timedelta

from mcx_tournament import TournamentLedger


class TournamentLedgerTests(unittest.TestCase):
    def test_net_scorecard_and_champion_selection(self):
        with tempfile.TemporaryDirectory() as d:
            ledger = TournamentLedger(d + "/t.json", target_pnl=1000, min_trades=3)
            start = datetime.now(timezone.utc)
            for pnl in (400, 350, 300):
                ledger.record_trade(1, pnl, fees=10, slippage=5, timestamp=start.isoformat())
            card = ledger.scorecard(1, now=start)
            self.assertEqual(card["net_pnl"], 1035)
            self.assertTrue(card["target_hit"])
            self.assertTrue(card["promotion_eligible"])
            winner = ledger.select_champion(now=start)
            self.assertEqual(winner["generation"], 1)
            ledger.begin_angelone_validation(1)
            result = ledger.record_angelone_validation(
                1, net_pnl=120, trades=5, duration_seconds=3600,
                max_drawdown_fraction=0.04, data_source="angelone_mcx",
                actual_contract_sizing=True,
            )
            self.assertTrue(result["passed"])
            self.assertFalse(result["live_orders_enabled"])
            self.assertTrue(ledger.live_candidate()["requires_separate_operator_approval"])

    def test_one_loss_retires_generation_and_blocks_promotion(self):
        with tempfile.TemporaryDirectory() as d:
            ledger = TournamentLedger(d + "/t.json", target_pnl=100, min_trades=1)
            ledger.record_trade(2, 150)
            card = ledger.record_trade(2, -1)
            self.assertEqual(card["status"], "RETIRED")
            self.assertIsNone(ledger.select_champion())

    def test_validation_fails_closed_on_wrong_feed_or_bad_safety(self):
        with tempfile.TemporaryDirectory() as d:
            ledger = TournamentLedger(d + "/t.json", target_pnl=100, min_trades=1)
            start = datetime.now(timezone.utc)
            ledger.record_trade(1, 150, timestamp=start.isoformat())
            self.assertIsNotNone(ledger.select_champion(now=start))
            ledger.begin_angelone_validation(1)
            result = ledger.record_angelone_validation(
                1, net_pnl=20, trades=1, duration_seconds=3600,
                max_drawdown_fraction=0.2, data_source="yahoo_proxy",
                actual_contract_sizing=False, stale_quote_events=1,
            )
            self.assertFalse(result["passed"])
            self.assertFalse(result["live_orders_enabled"])

    def test_persistent_reload(self):
        with tempfile.TemporaryDirectory() as d:
            path = d + "/t.json"
            TournamentLedger(path).ensure_generation(7)
            restored = TournamentLedger(path)
            self.assertEqual(restored.state["generations"]["7"]["status"], "ACTIVE")


if __name__ == "__main__":
    unittest.main()
