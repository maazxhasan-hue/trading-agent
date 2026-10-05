import unittest

from execution_risk import ExecutionRiskGate


class ExecutionRiskTests(unittest.TestCase):
    def test_kill_switch_rejects(self):
        gate = ExecutionRiskGate(kill_switch=True)
        d = gate.approve(0.03, 1000, 0.50, None, 100, 0)
        self.assertFalse(d.approved)
        self.assertEqual(d.reason, "kill_switch")

    def test_depth_guard_rejects_thin_book(self):
        gate = ExecutionRiskGate(min_book_depth_multiple=2.0)
        d = gate.approve(0.06, 1000, 0.50, None, 100, 0)
        self.assertFalse(d.approved)
        self.assertEqual(d.reason, "insufficient_book_depth")

    def test_valid_trade_passes(self):
        gate = ExecutionRiskGate(min_book_depth_multiple=1.0)
        d = gate.approve(0.03, 1000, 0.50, None, 100, 0)
        self.assertTrue(d.approved)
        self.assertAlmostEqual(d.fraction, 0.03)


if __name__ == "__main__":
    unittest.main()
