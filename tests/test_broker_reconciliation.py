import unittest

from broker_reconciliation import reconcile


class TestBrokerReconciliation(unittest.TestCase):
    def test_detects_position_mismatch_and_open_order(self):
        result = reconcile(
            [{"tradingsymbol": "TCS", "quantity": 10, "average_price": 100}],
            [{"tradingsymbol": "TCS", "quantity": 5, "average_price": 101}],
            [{"tradingsymbol": "INFY", "quantity": 2, "status": "OPEN"}],
        )
        self.assertFalse(result["in_sync"])
        self.assertEqual(result["position_mismatches"][0]["broker_quantity"], 5)
        self.assertEqual(len(result["open_orders"]), 1)

    def test_matching_positions_are_in_sync_without_open_orders(self):
        result = reconcile(
            [{"tradingsymbol": "TCS", "quantity": 10}],
            [{"tradingsymbol": "TCS", "quantity": 10}],
            [{"tradingsymbol": "INFY", "quantity": 2, "status": "COMPLETE"}],
        )
        self.assertTrue(result["in_sync"])
        self.assertEqual(result["position_mismatches"], [])
        self.assertEqual(result["open_orders"], [])


if __name__ == "__main__":
    unittest.main()
