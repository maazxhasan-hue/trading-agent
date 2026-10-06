import os
import unittest

from live_readiness import audit


class TestLiveReadinessAudit(unittest.TestCase):
    def test_default_state_is_not_live_ready(self):
        old = {
            k: os.environ.get(k)
            for k in (
                "LIVE_TRADING",
                "NSE_MARKET_DATA_PROVIDER",
                "CLOUD_RUNTIME",
                "LIVE_RUNTIME_APPROVED",
                "LIVE_TRADING_ARM",
                "KITE_API_KEY",
                "KITE_ACCESS_TOKEN",
                "ZERODHA_STATIC_IP",
            )
        }
        try:
            for key in old:
                os.environ.pop(key, None)
            result = audit()
            self.assertFalse(result["live_trading_enabled"])
            self.assertFalse(result["ready_for_live"])
            self.assertIn("Authorized Zerodha market-data provider is not configured.", result["blockers"])
            self.assertIn("Paper-performance validation must pass before any live approval.", result["blockers"])
        finally:
            for key, value in old.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


if __name__ == "__main__":
    unittest.main()
