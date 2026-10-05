import unittest
from fair_value import FairValueModel

class FairValueTests(unittest.TestCase):
    def test_value_is_bounded(self):
        r = FairValueModel().estimate(
            current=0.55, history_fair=0.62, history_confidence=0.80,
            volatility=0.03, book_imbalance=0.5, cross_market_score=0.4,
        )
        self.assertGreaterEqual(r.value, 0.01)
        self.assertLessEqual(r.value, 0.99)
        self.assertGreaterEqual(r.confidence, 0.50)

if __name__ == "__main__":
    unittest.main()
