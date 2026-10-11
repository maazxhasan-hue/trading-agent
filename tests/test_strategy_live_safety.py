import os
import unittest
from unittest.mock import Mock, patch

from angelone_adapter import OrderRequest
from angelone_order_manager import AngelOneOrderManager, OrderLifecycleError
from strategy_validation import net_walk_forward_report


class StrategyLiveSafetyTests(unittest.TestCase):
    def test_paper_validation_report_never_authorizes_order_submission(self):
        candidate = [self._trade(i, "candidate") for i in range(30)]
        baseline = [self._trade(i, "baseline") for i in range(30)]
        report = net_walk_forward_report(
            candidate,
            strategy_id="candidate",
            baseline_trades=baseline,
            test_size=10,
            min_train_samples=10,
            min_windows=2,
            min_regime_samples=5,
        )
        execution = Mock()
        execution.enabled = True
        execution.orders.return_value = []
        manager = AngelOneOrderManager(execution)
        request = OrderRequest("SBIN-EQ", "3045", "NSE", "BUY", 1, 100, "INTRADAY")

        with patch.dict(os.environ, {
            "LIVE_TRADING": "false",
            "ANGELONE_READONLY": "true",
        }):
            self.assertTrue(report["paper_only_qualified"])
            self.assertFalse(report["live_eligible"])
            with self.assertRaisesRegex(OrderLifecycleError, "live trading is disabled"):
                manager.submit(request, "validation-test-intent")

        execution.orders.assert_called_once_with()
        execution.place_limit.assert_not_called()

    @staticmethod
    def _trade(index, strategy):
        return {
            "strategy_id": strategy,
            "timestamp": index * 60.0,
            "status": "FILLED",
            "gross_pnl": 2.0 if strategy == "candidate" else 0.2,
            "turnover": 100.0,
            "regime": "UP",
            "costs": {"fees": 0.1, "spread": 0.1, "slippage": 0.1, "taxes": 0.1},
        }


if __name__ == "__main__":
    unittest.main()
