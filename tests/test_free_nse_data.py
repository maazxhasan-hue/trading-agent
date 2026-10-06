import os
import unittest

from nse_market_data import NSEPublicFeed
from nse_agent import NSETradingCompany, ZerodhaLocked


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


if __name__ == "__main__":
    unittest.main()
