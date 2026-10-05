import unittest

from model_validation import validate_fair_value_history


class ModelValidationTests(unittest.TestCase):
    def test_insufficient_history_fails_closed(self):
        result = validate_fair_value_history([0.4 + i * 0.001 for i in range(20)])
        self.assertFalse(result.passed)
        self.assertEqual(result.reason, "insufficient_history")

    def test_directional_history_can_validate(self):
        prices = [0.20 + 0.005 * i for i in range(120)]
        result = validate_fair_value_history(prices)
        self.assertTrue(result.passed)
        self.assertGreaterEqual(result.samples, 30)
        self.assertGreaterEqual(result.accuracy, 0.55)
        self.assertLessEqual(result.brier, 0.25)

    def test_flat_history_does_not_get_validated(self):
        prices = [0.50 + (0.0005 if i % 2 else -0.0005) for i in range(120)]
        result = validate_fair_value_history(prices, min_move=0.005)
        self.assertFalse(result.passed)


if __name__ == "__main__":
    unittest.main()
