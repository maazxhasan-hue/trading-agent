import json
import tempfile
import unittest

from live_portfolio import LivePortfolioLedger


class LivePortfolioLedgerTests(unittest.TestCase):
    def test_partial_fill_is_idempotent_and_persistent(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = tmp + "/ledger.json"
            ledger = LivePortfolioLedger(path)
            ledger.record_order("o1", "m1", "Question", "BUY_YES", "t1", 10)
            ledger.reconcile_order("o1", "m1", "Question", "BUY_YES", "t1", 10, 4, 0.40, "PARTIALLY_FILLED")
            ledger.reconcile_order("o1", "m1", "Question", "BUY_YES", "t1", 10, 4, 0.40, "PARTIALLY_FILLED")
            ledger.mark("m1", 0.50)

            self.assertEqual(ledger.positions["m1"].matched_size, 4)
            self.assertAlmostEqual(ledger.positions["m1"].cost_basis, 1.60)
            self.assertAlmostEqual(ledger.unrealized_pnl(), 0.40)

            restored = LivePortfolioLedger(path)
            self.assertEqual(restored.positions["m1"].matched_size, 4)
            self.assertAlmostEqual(restored.unrealized_pnl(), 0.40)

    def test_cumulative_fill_never_moves_backwards(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = LivePortfolioLedger(tmp + "/ledger.json")
            ledger.reconcile_order("o1", "m1", "Q", "BUY_YES", "t1", 10, 6, 0.40, "FILLED")
            ledger.reconcile_order("o1", "m1", "Q", "BUY_YES", "t1", 10, 3, 0.40, "FILLED")
            self.assertEqual(ledger.positions["m1"].matched_size, 6)

    def test_unfilled_cancel_does_not_create_position(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = LivePortfolioLedger(tmp + "/ledger.json")
            ledger.reconcile_order("o1", "m1", "Q", "BUY_YES", "t1", 10, 0, 0, "CANCELED")
            self.assertNotIn("m1", ledger.positions)


if __name__ == "__main__":
    unittest.main()
