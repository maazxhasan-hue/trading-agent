import unittest

from fair_value import FairValueModel
from model_validation import validate_fair_value_history


class ModelStressTests(unittest.TestCase):
    def test_fair_value_and_confidence_stay_bounded(self):
        result = FairValueModel().estimate(
            current=0.99,
            history_fair=0.01,
            history_confidence=0.50,
            volatility=1.0,
            book_imbalance=100,
            cross_market_score=100,
            news_score=100,
            macro_score=100,
            crypto_score=100,
            social_score=100,
        )
        self.assertGreaterEqual(result.value, 0.01)
        self.assertLessEqual(result.value, 0.99)
        self.assertGreaterEqual(result.confidence, 0.50)
        self.assertLessEqual(result.confidence, 0.95)

    def test_historical_median_resists_outliers(self):
        result = FairValueModel().estimate(
            current=0.50,
            history_fair=0.50,
            history_confidence=0.70,
            volatility=0.02,
            history=[0.50] * 18 + [0.99, 0.01],
        )
        self.assertAlmostEqual(result.components["historical"], 0.50, places=6)

    def test_validation_never_passes_without_enough_history(self):
        result = validate_fair_value_history([0.5] * 20)
        self.assertFalse(result.passed)
        self.assertIn("insufficient", result.reason)

    def test_validation_is_deterministic(self):
        prices = [0.40 + 0.01 * (i % 20) for i in range(80)]
        first = validate_fair_value_history(prices, min_samples=10, lookback=20)
        second = validate_fair_value_history(prices, min_samples=10, lookback=20)
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
