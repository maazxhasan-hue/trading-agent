import os
import unittest

from nse_market_data import NSEPublicFeed
from nse_agent import NSETradingCompany, Signal, ZerodhaLocked


class TestFreeNSEPath(unittest.TestCase):
    def test_free_provider_is_not_live_authorized(self):
        old = os.environ.get("NSE_MARKET_DATA_PROVIDER")
        try:
            os.environ["NSE_MARKET_DATA_PROVIDER"] = "yahoo"
            feed = NSEPublicFeed()
            self.assertTrue(feed.is_free_data)
            self.assertFalse(feed.is_live_authorized_data)
            self.assertEqual(feed.data_label, "free-research")
            self.assertGreater(feed.freshness_seconds(None), 10**9)
        finally:
            if old is None:
                os.environ.pop("NSE_MARKET_DATA_PROVIDER", None)
            else:
                os.environ["NSE_MARKET_DATA_PROVIDER"] = old

    def test_live_execution_rejects_free_data(self):
        old = {k: os.environ.get(k) for k in (
            "NSE_MARKET_DATA_PROVIDER", "LIVE_TRADING",
            "LIVE_TRADING_ARM", "CLOUD_RUNTIME", "LIVE_RUNTIME_APPROVED"
        )}
        try:
            os.environ["NSE_MARKET_DATA_PROVIDER"] = "yahoo"
            os.environ["LIVE_TRADING"] = "true"
            os.environ["LIVE_TRADING_ARM"] = "I_UNDERSTAND_LIVE_TRADING"
            os.environ["CLOUD_RUNTIME"] = "true"
            os.environ["LIVE_RUNTIME_APPROVED"] = "true"
            with self.assertRaises(ZerodhaLocked):
                NSETradingCompany()
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v


    def test_paper_positions_mark_to_market_and_take_profit(self):
        old = {k: os.environ.get(k) for k in ("NSE_MARKET_DATA_PROVIDER", "PAPER_STARTING_CAPITAL", "AGENT_LEARNING_FILE", "PAPER_TAKE_PROFIT_MULTIPLE")}
        try:
            os.environ["NSE_MARKET_DATA_PROVIDER"] = "yahoo"
            os.environ["PAPER_STARTING_CAPITAL"] = "100000"
            os.environ["PAPER_TAKE_PROFIT_MULTIPLE"] = "2"
            import tempfile
            with tempfile.TemporaryDirectory() as d:
                os.environ["AGENT_LEARNING_FILE"] = os.path.join(d, "learning.json")
                company = NSETradingCompany()
                market = type("M", (), {"market_id": "TCS", "question": "TCS", "tradingsymbol": "TCS", "last_price": 100.0})()
                signal = Signal(market, 1, 0.8, 0.9, 0.01, "test")
                company.paper_or_live(signal)
                self.assertIn("TCS", company.open_positions)
                company.paper_cycle += 1
                company._mark_paper_positions({"TCS": 102.5})
                self.assertNotIn("TCS", company.open_positions)
                self.assertGreater(company.realized_pnl, 0)
                self.assertGreater(company.daily_pnl, 0)
        finally:
            for k, v in old.items():
                if v is None: os.environ.pop(k, None)
                else: os.environ[k] = v
if __name__ == "__main__":
    unittest.main()
