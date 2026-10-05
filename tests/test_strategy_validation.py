import unittest

from strategy_validation import walk_forward_report


class StrategyValidationTests(unittest.TestCase):
    def _history(self, correct_flags):
        rows = []
        for i, correct in enumerate(correct_flags):
            rows.append({
                "created_at": float(i),
                "resolved_at": float(i + 1),
                "market_id": "m" + str(i),
                "outcome": 1,
                "confidence": 0.80,
                "directions": {"agent-a": 1 if correct else -1},
            })
        return rows

    def test_insufficient_samples_has_no_false_metrics(self):
        report = walk_forward_report(self._history([True] * 5), "agent-a")
        self.assertEqual(report["samples"], 5)
        self.assertEqual(report["walk_forward_windows"], 0)
        self.assertEqual(report["status"], "insufficient_or_unstable")

    def test_walk_forward_is_chronological(self):
        flags = [True] * 30
        report = walk_forward_report(flags and self._history(flags), "agent-a")
        self.assertEqual(report["walk_forward_windows"], 2)
        self.assertEqual(report["walk_forward_samples"], 20)
        self.assertEqual(report["walk_forward_accuracy"], 1.0)
        self.assertEqual(report["status"], "validated")

    def test_recent_deterioration_blocks_qualification(self):
        flags = [True] * 20 + [False] * 10
        report = walk_forward_report(self._history(flags), "agent-a")
        self.assertLess(report["recent_accuracy"], 0.50)
        self.assertFalse(report["recent_stable"])
        self.assertNotEqual(report["status"], "validated")


if __name__ == "__main__":
    unittest.main()
