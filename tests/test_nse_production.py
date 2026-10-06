import os
import tempfile
import unittest

from agent_learning import AgentLearningStore
from zerodha_adapter import ZerodhaExecution, ZerodhaLocked


class TestNSEProductionPath(unittest.TestCase):
    def test_live_execution_is_locked_by_default(self):
        old = {k: os.environ.get(k) for k in ("LIVE_TRADING", "LIVE_TRADING_ARM", "CLOUD_RUNTIME", "LIVE_RUNTIME_APPROVED")}
        try:
            for k in old:
                os.environ.pop(k, None)
            z = ZerodhaExecution()
            self.assertFalse(z.enabled)
            self.assertIsNone(z.client)
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def test_learning_accepts_positive_stock_prices_and_relative_moves(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "learning.json")
            old_mode = os.environ.get("LEARNING_MOVE_MODE")
            old_pct = os.environ.get("LEARNING_MIN_MOVE_PCT")
            try:
                os.environ["LEARNING_MOVE_MODE"] = "relative"
                os.environ["LEARNING_MIN_MOVE_PCT"] = "0.001"
                s = AgentLearningStore(path=path)
                s.record_observation("123", 2500.0)
                self.assertEqual(s.history_for_market("123"), [2500.0])
                s.record_forecast("123", "TEST", 2500.0, {"momentum-v1": 1}, 0.7, 0.01, now=0)
                s.resolve(lambda _: 2503.0, now=1000)
                self.assertEqual(s.stats("momentum-v1")["forecasts"], 1)
            finally:
                if old_mode is None: os.environ.pop("LEARNING_MOVE_MODE", None)
                else: os.environ["LEARNING_MOVE_MODE"] = old_mode
                if old_pct is None: os.environ.pop("LEARNING_MIN_MOVE_PCT", None)
                else: os.environ["LEARNING_MIN_MOVE_PCT"] = old_pct


if __name__ == "__main__":
    unittest.main()
