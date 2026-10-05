import os
import unittest
from unittest.mock import patch
from execution_polymarket import LiveExecutionLocked, PolymarketExecution

class ExecutionTests(unittest.TestCase):
    def test_live_is_locked_by_default(self):
        with patch.dict(os.environ, {"LIVE_TRADING": "false"}, clear=False):
            ex = PolymarketExecution()
            self.assertFalse(ex.status()["live_enabled"])

    def test_live_requires_arm(self):
        with patch.dict(os.environ, {
            "LIVE_TRADING": "true",
            "LIVE_TRADING_ARM": "",
        }, clear=False):
            with self.assertRaises(LiveExecutionLocked):
                PolymarketExecution()

if __name__ == "__main__":
    unittest.main()
