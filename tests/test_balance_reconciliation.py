import unittest

from balance_reconciliation import (
    collateral_sufficient,
    extract_available_collateral,
)


class BalanceReconciliationTests(unittest.TestCase):
    def test_extracts_available_balance(self):
        self.assertEqual(
            extract_available_collateral({"available": "125.50"}),
            125.50,
        )

    def test_extracts_nested_result(self):
        self.assertEqual(
            extract_available_collateral({"result": {"free_balance": 80}}),
            80.0,
        )

    def test_unknown_payload_fails_closed(self):
        self.assertIsNone(extract_available_collateral({"total": 100}))

    def test_reserve_is_enforced(self):
        self.assertTrue(collateral_sufficient(100, 80, reserve_fraction=0.10))
        self.assertFalse(collateral_sufficient(100, 95, reserve_fraction=0.10))

    def test_unknown_balance_rejects(self):
        self.assertFalse(collateral_sufficient(None, 1))


if __name__ == "__main__":
    unittest.main()
