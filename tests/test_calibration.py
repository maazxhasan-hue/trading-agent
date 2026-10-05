import tempfile
import unittest

from calibration import CalibrationTracker


class CalibrationTests(unittest.TestCase):
    def test_stats_and_brier(self):
        with tempfile.TemporaryDirectory() as tmp:
            tracker = CalibrationTracker(path=tmp + "/calibration.json")
            tracker.record("agent-a", 0.9, True)
            tracker.record("agent-a", 0.9, False)
            stats = tracker.stats("agent-a")
            self.assertEqual(stats["n"], 2)
            self.assertEqual(stats["accuracy"], 0.5)
            self.assertAlmostEqual(stats["brier"], 0.41)

    def test_empty_agent_is_safe(self):
        with tempfile.TemporaryDirectory() as tmp:
            tracker = CalibrationTracker(path=tmp + "/calibration.json")
            self.assertEqual(
                tracker.stats("unknown"),
                {"n": 0, "accuracy": 0.0, "brier": None},
            )


if __name__ == "__main__":
    unittest.main()
