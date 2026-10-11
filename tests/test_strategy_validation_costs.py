import unittest

from strategy_validation import net_walk_forward_report


class StrategyValidationCostsTests(unittest.TestCase):
    def trade(
        self,
        index,
        *,
        strategy="candidate",
        gross=2.0,
        fees=0.1,
        spread=0.1,
        slippage=0.1,
        taxes=0.1,
        regime="UP",
        status="FILLED",
    ):
        return {
            "strategy_id": strategy,
            "timestamp": float(index * 60),
            "status": status,
            "gross_pnl": gross,
            "turnover": 100.0,
            "regime": regime,
            "costs": {
                "fees": fees, "spread": spread,
                "slippage": slippage, "taxes": taxes,
            },
        }

    def report(self, trades, baseline=None, **overrides):
        options = {
            "strategy_id": "candidate",
            "baseline_trades": baseline,
            "min_train_samples": 10,
            "test_size": 10,
            "min_windows": 2,
            "min_regime_samples": 5,
            "benchmark_per_hour": 1000.0,
        }
        options.update(overrides)
        return net_walk_forward_report(trades, **options)

    def test_gross_profit_that_loses_after_costs_is_not_eligible(self):
        candidate = [
            self.trade(i, gross=1.0, fees=0.4, spread=0.3, slippage=0.2, taxes=0.2)
            for i in range(30)
        ]
        baseline = [self.trade(i, strategy="baseline", gross=0.0) for i in range(30)]

        report = self.report(candidate, baseline)

        self.assertLess(report["net_pnl"], 0)
        self.assertEqual(report["status"], "NEGATIVE_NET_AFTER_COSTS")
        self.assertEqual(report["benchmark_status"], "RESEARCH_ONLY")

    def test_missing_cost_inputs_fail_closed(self):
        candidate = [self.trade(i) for i in range(30)]
        baseline = [self.trade(i, strategy="baseline") for i in range(30)]
        candidate[15]["costs"].pop("taxes")

        report = self.report(candidate, baseline)

        self.assertEqual(report["status"], "COSTS_INCOMPLETE")
        self.assertIsNone(report["net_pnl"])
        self.assertFalse(report["paper_only_qualified"])

    def test_malformed_candidate_rows_fail_closed(self):
        candidate = [self.trade(i) for i in range(30)]
        baseline = [self.trade(i, strategy="baseline") for i in range(30)]
        candidate.append("malformed row")

        report = self.report(candidate, baseline)

        self.assertEqual(report["status"], "INVALID_DATA")
        self.assertIsNone(report["net_pnl"])
        self.assertFalse(report["live_eligible"])

    def test_missing_regime_labels_cannot_qualify(self):
        candidate = [self.trade(i, regime=None) for i in range(30)]
        baseline = [self.trade(i, strategy="baseline", regime=None) for i in range(30)]

        report = self.report(candidate, baseline)

        self.assertEqual(report["status"], "MISSING_REGIME_LABEL")
        self.assertFalse(report["paper_only_qualified"])

    def test_unknown_regime_label_cannot_qualify(self):
        candidate = [self.trade(i, regime="UNKNOWN") for i in range(30)]
        baseline = [self.trade(i, strategy="baseline") for i in range(30)]

        report = self.report(candidate, baseline)

        self.assertEqual(report["status"], "MISSING_REGIME_LABEL")
        self.assertFalse(report["paper_only_qualified"])

    def test_sparse_baseline_coverage_cannot_qualify(self):
        candidate = [self.trade(i) for i in range(30)]
        baseline = [self.trade(i, strategy="baseline") for i in range(30)]
        sparse_baseline = [baseline[10]]

        report = self.report(candidate, sparse_baseline)

        self.assertEqual(report["status"], "BASELINE_INSUFFICIENT_SAMPLES")
        self.assertFalse(report["paper_only_qualified"])

    def test_walk_forward_excludes_training_and_incomplete_future_window(self):
        candidate = [self.trade(i, gross=1.0) for i in range(31)]
        baseline = [self.trade(i, strategy="baseline", gross=0.2) for i in range(31)]
        candidate[30]["gross_pnl"] = 1_000_000.0

        report = self.report(candidate, baseline)

        self.assertEqual(report["walk_forward_samples"], 20)
        self.assertEqual(report["net_pnl"], 20 * 0.6)
        self.assertEqual(report["walk_forward_windows"], 2)
        self.assertTrue(all(window["train_samples"] < window["test_start"] for window in report["windows"]))

    def test_future_partial_window_cannot_satisfy_sample_floor(self):
        candidate = [self.trade(i) for i in range(31)]
        candidate[15]["status"] = "REJECTED"
        baseline = [self.trade(i, strategy="baseline") for i in range(31)]

        report = self.report(candidate, baseline)

        self.assertEqual(report["status"], "INSUFFICIENT_SAMPLES")

    def test_regime_metrics_and_baseline_comparison_are_reported(self):
        candidate = [
            self.trade(i, gross=(2.0 if i % 2 else 1.0), regime="UP" if i % 2 else "DOWN")
            for i in range(40)
        ]
        baseline = [self.trade(i, strategy="baseline", gross=0.1) for i in range(40)]

        report = self.report(candidate, baseline)

        self.assertEqual(set(report["regimes"]), {"UP", "DOWN"})
        self.assertIsNotNone(report["baseline_net_pnl"])
        self.assertGreater(report["baseline_delta"], 0)
        self.assertIn(report["status"], {"PAPER_ONLY_POSITIVE_AFTER_COSTS", "UNSTABLE_BY_REGIME"})
        self.assertFalse(report["live_eligible"])

    def test_hourly_target_only_changes_reporting_not_eligibility(self):
        candidate = [self.trade(i, gross=2.0) for i in range(30)]
        baseline = [self.trade(i, strategy="baseline", gross=0.0) for i in range(30)]

        modest = self.report(candidate, baseline, benchmark_per_hour=1.0)
        extreme = self.report(candidate, baseline, benchmark_per_hour=1_000_000.0)

        self.assertEqual(modest["status"], extreme["status"])
        self.assertTrue(modest["paper_only_qualified"])
        self.assertFalse(extreme["live_eligible"])
        self.assertNotEqual(modest["target_gap_per_hour"], extreme["target_gap_per_hour"])

    def test_rejected_and_unfilled_orders_are_counted_without_fabricated_profit(self):
        candidate = [self.trade(i, status="REJECTED", gross=50.0) for i in range(30)]
        baseline = [self.trade(i, strategy="baseline", status="REJECTED", gross=50.0) for i in range(30)]

        report = self.report(candidate, baseline)

        self.assertEqual(report["rejected_count"], 20)
        self.assertEqual(report["trade_count"], 0)
        self.assertEqual(report["gross_pnl"], 0.0)
        self.assertEqual(report["net_pnl"], -8.0)
        self.assertEqual(report["status"], "INSUFFICIENT_SAMPLES")


if __name__ == "__main__":
    unittest.main()

