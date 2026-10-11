import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from agent_learning import AgentLearningStore
from zerodha_adapter import ZerodhaExecution, ZerodhaLocked


class TestNSEProductionPath(unittest.TestCase):
    def test_paper_strategy_evaluation_does_not_authenticate_or_submit(self):
        from nse_agent import NSETradingCompany, Signal

        env = {
            "TRADING_BACKEND": "zerodha_nse",
            "NSE_MARKET_DATA_PROVIDER": "yahoo",
            "LIVE_TRADING": "false",
            "ANGELONE_READONLY": "false",
            "PAPER_STARTING_CAPITAL": "100000",
        }
        with tempfile.TemporaryDirectory() as directory:
            env.update({
                "AGENT_LEARNING_FILE": os.path.join(directory, "learning.json"),
                "TRADING_CITY_STATE_FILE": os.path.join(directory, "city.json"),
                "TRADE_JOURNAL_FILE": os.path.join(directory, "journal.jsonl"),
            })
            with patch.dict(os.environ, env), \
                 patch("nse_agent.AngelOneExecution") as angelone_execution, \
                 patch("angelone_adapter._manager_for_environment") as auth_manager, \
                 patch("nse_agent.PAPER_STATE_FILE", os.path.join(directory, "paper.json")):
                company = NSETradingCompany()
                market = SimpleNamespace(
                    market_id="TCS",
                    question="TCS",
                    tradingsymbol="TCS",
                    exchange="NSE",
                    last_price=100.0,
                    lot_size=1,
                )
                features = {
                    "r3": 0.01, "r5": 0.01, "r10": 0.015, "r20": 0.02,
                    "reversion": 0.002, "trend_gap": 0.01, "vol": 0.01,
                    "volume_ratio": 1.5, "range_ratio": 1.2, "rsi": 55,
                    "breakout": 0.01, "breakdown": 0.0, "price": 100.0,
                }
                votes = company.agent_votes(features, market)
                self.assertTrue(votes)

                signal = Signal(market, 1, 0.8, 0.9, 0.01, "paper test")
                company.paper_or_live(signal)

                self.assertIn("TCS", company.open_positions)
                angelone_execution.assert_not_called()
                auth_manager.assert_not_called()

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
