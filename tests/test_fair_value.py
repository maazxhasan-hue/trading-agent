import unittest

from fair_value import FairValueModel


class FairValueTests(unittest.TestCase):
    def test_fair_value_and_confidence_are_bounded(self):
        result = FairValueModel().estimate(current=0.99, history_fair=0.01, history_confidence=0.50, volatility=1.0, book_imbalance=1.0, cross_market_score=1.0, news_score=1.0, macro_score=1.0, crypto_score=1.0, social_score=1.0, history=[0.01,0.02,0.98,0.99,0.50] * 20)
        self.assertGreaterEqual(result.value, 0.01)
        self.assertLessEqual(result.value, 0.99)
        self.assertGreaterEqual(result.confidence, 0.50)
        self.assertLessEqual(result.confidence, 0.95)

    def test_history_is_robust_to_outliers(self):
        result = FairValueModel().estimate(current=0.50, history_fair=0.50, history_confidence=0.70, volatility=0.02, history=[0.50] * 18 + [0.99,0.01])
        self.assertAlmostEqual(result.components["historical"], 0.50, places=6)

    def test_external_evidence_adjustments_are_bounded(self):
        result = FairValueModel().estimate(current=0.50, history_fair=0.50, history_confidence=0.70, volatility=0.01, book_imbalance=100, cross_market_score=100)
        self.assertLessEqual(result.components["book_adjustment"], 0.035)
        self.assertLessEqual(result.components["cross_market_adjustment"], 0.025)


if __name__ == "__main__":
    unittest.main()
