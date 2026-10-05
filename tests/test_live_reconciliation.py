import unittest

from live_reconciliation import normalize_order, has_new_fill, is_terminal


class LiveReconciliationTests(unittest.TestCase):
    def test_partial_fill_is_normalized(self):
        state = normalize_order(
            "abc",
            {
                "status": "LIVE",
                "original_size": "10",
                "size_matched": "3.5",
                "size_remaining": "6.5",
                "average_price": "0.42",
            },
        )
        self.assertEqual(state.order_id, "abc")
        self.assertEqual(state.status, "LIVE")
        self.assertAlmostEqual(state.requested_size, 10.0)
        self.assertAlmostEqual(state.matched_size, 3.5)
        self.assertAlmostEqual(state.remaining_size, 6.5)
        self.assertAlmostEqual(state.average_price, 0.42)

    def test_new_fill_requires_cumulative_match_increase(self):
        previous = normalize_order("abc", {"status": "LIVE", "size_matched": "2"})
        current = normalize_order("abc", {"status": "LIVE", "size_matched": "2.5"})
        unchanged = normalize_order("abc", {"status": "LIVE", "size_matched": "2"})
        self.assertTrue(has_new_fill(previous, current))
        self.assertFalse(has_new_fill(previous, unchanged))

    def test_terminal_states(self):
        for status in ("FILLED", "CANCELED", "REJECTED", "EXPIRED"):
            self.assertTrue(is_terminal(normalize_order("x", {"status": status})))


if __name__ == "__main__":
    unittest.main()
