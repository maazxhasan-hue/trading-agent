import os
import unittest

from live_readiness import audit


class TestLiveReadinessAudit(unittest.TestCase):
    KEYS = (
        "LIVE_TRADING",
        "MCX_MARKET_DATA_PROVIDER",
        "TRADING_BACKEND",
        "CLOUD_RUNTIME",
        "LIVE_RUNTIME_APPROVED",
        "LIVE_TRADING_ARM",
        "ANGELONE_API_KEY",
        "ANGELONE_CLIENT_CODE",
        "ANGELONE_PIN",
        "ANGELONE_TOTP_SECRET",
        "ANGELONE_CLIENT_PUBLIC_IP",
    )

    def test_default_state_is_not_live_ready(self):
        old = {key: os.environ.get(key) for key in self.KEYS}
        try:
            for key in self.KEYS:
                os.environ.pop(key, None)
            result = audit()
            self.assertFalse(result["live_trading_enabled"])
            self.assertFalse(result["ready_for_live"])
            self.assertFalse(result["checks"]["authorized_market_data_provider"])
            self.assertIn(
                "Angel One MCX backend and market-data provider are not both configured.",
                result["blockers"],
            )
            self.assertIn(
                "Paper-performance validation must pass before any live approval.",
                result["blockers"],
            )
        finally:
            for key, value in old.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def test_angelone_configuration_is_recognized_but_never_approves_live(self):
        old = {key: os.environ.get(key) for key in self.KEYS}
        try:
            values = {
                "LIVE_TRADING": "false",
                "MCX_MARKET_DATA_PROVIDER": "angelone",
                "TRADING_BACKEND": "angelone_mcx",
                "CLOUD_RUNTIME": "true",
                "LIVE_RUNTIME_APPROVED": "true",
                "LIVE_TRADING_ARM": "I_UNDERSTAND_LIVE_TRADING",
                "ANGELONE_API_KEY": "test",
                "ANGELONE_CLIENT_CODE": "test",
                "ANGELONE_PIN": "test",
                "ANGELONE_TOTP_SECRET": "test",
                "ANGELONE_CLIENT_PUBLIC_IP": "203.0.113.10",
            }
            os.environ.update(values)
            result = audit()
            self.assertTrue(result["checks"]["authorized_market_data_provider"])
            self.assertTrue(result["checks"]["angelone_credentials_configured"])
            self.assertTrue(result["checks"]["static_ip_configured"])
            self.assertFalse(result["ready_for_live"])
            self.assertFalse(result["checks"]["final_live_approval"])
        finally:
            for key, value in old.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


if __name__ == "__main__":
    unittest.main()
