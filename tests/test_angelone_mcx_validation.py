import unittest
from types import SimpleNamespace

from angelone_mcx_validation import AngelOneMCXValidationReport


class AngelOneMCXValidationReportTests(unittest.TestCase):
    def setUp(self):
        self.report = AngelOneMCXValidationReport()
        self.market = SimpleNamespace(
            market_id="token-1", tradingsymbol="GOLDM", last_price=70000, lot_size=1
        )

    def test_fresh_authorized_observation_is_recorded_without_live_enablement(self):
        self.report.observe_quotes([self.market], lambda market: 1.0, actual_contract_sizing=True)
        result = self.report.build(
            feed_label="angelone-authorized",
            portfolio_snapshots=[{"drawdown_fraction": 0.01}],
            duration_seconds=3600,
        )
        self.assertEqual(result["quote_observations"], 1)
        self.assertTrue(result["checks"]["authorized_angelone_feed"])
        self.assertFalse(result["passed"])  # no closed trades
        self.assertFalse(result["live_orders_enabled"])

    def test_stale_quote_blocks_report(self):
        self.report.observe_quotes([self.market], lambda market: 30.0)
        result = self.report.build(
            feed_label="angelone-authorized",
            portfolio_snapshots=[],
            duration_seconds=3600,
        )
        self.assertFalse(result["checks"]["all_quotes_fresh_and_valid"])
        self.assertFalse(result["passed"])
        self.assertEqual(result["stale_or_invalid_quote_events"], 1)

    def test_yahoo_proxy_never_passes_authorized_feed_gate(self):
        result = self.report.build(
            feed_label="free-research-proxy",
            portfolio_snapshots=[],
            duration_seconds=7200,
        )
        self.assertFalse(result["checks"]["authorized_angelone_feed"])
        self.assertFalse(result["passed"])

    def test_costed_trades_and_real_lot_evidence_are_required(self):
        self.report.observe_quotes([self.market], lambda market: 2.0, actual_contract_sizing=True)
        for pnl in (10, 12, 15):
            self.report.record_closed_trade({
                "net_pnl": pnl, "fees": 1, "slippage": 0.5,
                "quantity": 1, "entry_price": 70000, "exit_price": 70010,
                "market_id": "token-1",
            })
        result = self.report.build(
            feed_label="angelone-authorized",
            portfolio_snapshots=[{"drawdown_fraction": 0.02}],
            duration_seconds=3600,
        )
        self.assertTrue(result["passed"])
        self.assertFalse(result["live_orders_enabled"])
        self.assertTrue(result["operator_approval_required"])

    def test_invalid_trade_rejected_and_counted(self):
        with self.assertRaises(ValueError):
            self.report.record_closed_trade({
                "net_pnl": 10, "fees": 1, "slippage": 0.5,
                "quantity": 0, "entry_price": 70000, "exit_price": 70010,
            })
        self.assertEqual(self.report.risk_violations, 1)


if __name__ == "__main__":
    unittest.main()
